"""Agent CRUD：单一用户体系（SPEC-v2 批次 1）。

权限模型（SPEC-v2 决策 2/4）：
- /api/agents/*    登录即可访问；写操作校验归属（can_modify）
- /api/chat/agents 登录即可，返回自己拥有的 + 所有 published
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes import provisioner as prov
from ..hermes import (
    ProvisionError,
    profile_name_for,
    profile_status,
    validate_slug,
)
from ..hermes.toolsets import default_disabled, normalize_disabled
from ..models import Agent, AgentStatus, UserRole
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])
chat_router = APIRouter(prefix="/api/chat/agents", tags=["chat:agents"])


# ── Schemas ───────────────────────────────────────────────
class AgentCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    soul: str | None = None
    model: str | None = None
    provider: str | None = None
    disabled_toolsets: list[str] | None = None  # 缺省 = 只读助手默认集
    status: AgentStatus = AgentStatus.DRAFT


class AgentUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    soul: str | None = None
    model: str | None = None
    provider: str | None = None
    disabled_toolsets: list[str] | None = None
    curator_enabled: bool | None = None
    status: AgentStatus | None = None


class AgentOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None
    profile_name: str
    owner_id: int
    status: str
    disabled_toolsets: list[str] = []
    curator_enabled: bool | None = None

    model_config = {"from_attributes": True}


class AgentStatusOut(AgentOut):
    """带 hermes 侧实时信息。"""
    gateway_running: bool | None = None
    profile_exists: bool | None = None


def _to_out(agent: Agent, *, with_status: bool = False, live: dict | None = None) -> AgentOut:
    base = AgentOut.model_validate(agent)
    base.disabled_toolsets = list(agent.disabled_toolsets or [])
    if not with_status:
        return base
    out = AgentStatusOut(**base.model_dump())
    if live is not None:
        out.profile_exists = True
        out.gateway_running = bool(live.get("gateway_running"))
    else:
        out.profile_exists = False
        out.gateway_running = False
    return out


# ── 列表 / 详情 ───────────────────────────────────────────
@router.get("", response_model=list[AgentOut])
async def list_agents(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AgentOut]:
    # 管理员看全部；普通用户看自己拥有的（含草稿）
    if user.role == UserRole.ADMIN:
        stmt = select(Agent).order_by(Agent.created_at.desc())
    else:
        stmt = select(Agent).where(Agent.owner_id == user.id).order_by(Agent.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_out(a) for a in rows]


@router.post("", response_model=AgentStatusOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    try:
        validate_slug(body.slug)
    except ProvisionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    exists = (
        await session.execute(select(Agent).where(Agent.slug == body.slug))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug 已被占用")

    disabled = (
        normalize_disabled(body.disabled_toolsets)
        if body.disabled_toolsets is not None
        else default_disabled()
    )

    agent = Agent(
        slug=body.slug,
        name=body.name,
        description=body.description,
        profile_name=profile_name_for(user.id, body.slug),
        owner_id=user.id,
        status=body.status,
        disabled_toolsets=disabled,
    )
    session.add(agent)
    await session.flush()  # 拿到 id

    # 先建 profile，失败则回滚 DB（避免出现"有记录没 profile"）
    try:
        result = await prov.create_agent_profile(
            agent, soul=body.soul, model=body.model, provider=body.provider
        )
    except ProvisionError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    await session.commit()
    await session.refresh(agent)

    logger.info("创建 Agent %s -> profile %s (owner=%s)", agent.slug, agent.profile_name, user.id)
    out = _to_out(agent, with_status=True)
    out.profile_exists = True
    out.gateway_running = bool(result.get("served_now", True))
    return out


@router.get("/{agent_id}", response_model=AgentStatusOut)
async def get_agent(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    live: bool = Query(default=False),
) -> AgentStatusOut:
    agent = await _get_owned_or_404(session, agent_id, user)
    live_info = None
    if live:
        try:
            live_info = await profile_status(agent.owner_id, agent.slug)
        except Exception as exc:  # noqa: BLE001 - dashboard 不可用不应让接口 500
            logger.warning("查询 profile 状态失败: %s", exc)
    return _to_out(agent, with_status=True, live=live_info)


@router.patch("/{agent_id}", response_model=AgentStatusOut)
async def update_agent(
    agent_id: int,
    body: AgentUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    agent = await _get_owned_or_404(session, agent_id, user)

    if body.name is not None:
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description
    if body.status is not None:
        agent.status = body.status
    if body.disabled_toolsets is not None:
        agent.disabled_toolsets = normalize_disabled(body.disabled_toolsets)
    if body.curator_enabled is not None:
        agent.curator_enabled = body.curator_enabled

    try:
        await prov.sync_agent_profile(
            agent, soul=body.soul, model=body.model, provider=body.provider
        )
    except ProvisionError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    # 工具集开关落盘 + 强制工具集（绑定了 A2A/Skill 的自动开启且不可关闭）
    if body.disabled_toolsets is not None:
        from ..hermes.toolset_forcing import apply_forced_toolsets, compute_forced

        forced = await compute_forced(agent, session)
        apply_forced_toolsets(agent, forced)

    await session.commit()
    await session.refresh(agent)
    return _to_out(agent, with_status=True)


@router.get("/{agent_id}/soul")
async def get_agent_soul(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """读取该 Agent profile 当前生效的 SOUL.md（编辑页回填用）。"""
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的 Agent")
    return {"soul": prov.read_soul(agent.profile_name)}


@router.get("/{agent_id}/forced-toolsets")
async def get_forced_toolsets(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """该 Agent 因绑定资源而强制开启的工具集（前端据此禁用开关并说明原因）。"""
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的 Agent")
    from ..hermes.toolset_forcing import compute_forced

    forced = await compute_forced(agent, session)
    reason_map = {
        "a2a": "已绑定 A2A 端点",
        "skills": "已绑定 Skill",
        "terminal": "已绑定带脚本的 Skill",
    }
    reasons = {name: reason_map[name] for name in forced if name in reason_map}
    return {"forced": sorted(forced), "reasons": reasons}


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    agent = await _get_owned_or_404(session, agent_id, user)
    try:
        await prov.delete_agent_profile(agent)
    except Exception as exc:  # noqa: BLE001
        # profile 删除失败不应阻止 DB 清理，但要记录
        logger.warning("删除 profile 失败（继续删 DB 记录）: %s", exc)
    await session.delete(agent)
    await session.commit()


@router.post("/{agent_id}/publish", response_model=AgentStatusOut)
async def publish_agent(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    agent = await _get_owned_or_404(session, agent_id, user)
    agent.status = AgentStatus.PUBLISHED
    await session.commit()
    await session.refresh(agent)
    return _to_out(agent, with_status=True)


@router.post("/{agent_id}/unpublish", response_model=AgentStatusOut)
async def unpublish_agent(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    agent = await _get_owned_or_404(session, agent_id, user)
    agent.status = AgentStatus.DRAFT
    await session.commit()
    await session.refresh(agent)
    return _to_out(agent, with_status=True)


# ── 对话页可见列表：自己的 + published ─────────────────────
@chat_router.get("", response_model=list[AgentOut])
async def list_visible_agents(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AgentOut]:
    stmt = (
        select(Agent)
        .where(
            or_(
                Agent.owner_id == user.id,
                Agent.status == AgentStatus.PUBLISHED,
            )
        )
        .order_by(Agent.name)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_out(a) for a in rows]


async def _get_owned_or_404(session: AsyncSession, agent_id: int, user) -> Agent:
    """读取并校验归属：admin 全通过，否则必须 owner_id == user.id（SPEC-v2 决策 4）。"""
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")
    return agent
