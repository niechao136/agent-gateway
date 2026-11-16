"""Agent 管理：管理员 CRUD + 用户可见列表。

权限模型（SPEC §9）：
- /api/admin/agents/*  需 admin scope
- /api/chat/agents     需 user scope，只返回 published
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes import provisioner as prov
from ..hermes import (
    ProvisionError,
    disabled_toolsets_for,
    profile_name_for,
    profile_status,
    validate_slug,
)
from ..models import Agent, AgentStatus, ToolsetTier
from ..security import CurrentAdmin, CurrentUser

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin/agents", tags=["admin:agents"])
user_router = APIRouter(prefix="/api/chat/agents", tags=["chat:agents"])


# ── Schemas ───────────────────────────────────────────────
class AgentCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    soul: str | None = None
    model: str | None = None
    provider: str | None = None
    toolset_tier: ToolsetTier = ToolsetTier.PUBLIC
    status: AgentStatus = AgentStatus.DRAFT


class AgentUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    soul: str | None = None
    model: str | None = None
    provider: str | None = None
    toolset_tier: ToolsetTier | None = None
    status: AgentStatus | None = None


class AgentOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None
    profile_name: str
    status: str
    toolset_tier: str
    disabled_toolsets: list[str] = []

    model_config = {"from_attributes": True}


class AgentStatusOut(AgentOut):
    """带 hermes 侧实时信息。"""
    gateway_running: bool | None = None
    profile_exists: bool | None = None


def _to_out(agent: Agent, *, with_status: bool = False, live: dict | None = None) -> AgentOut:
    base = AgentOut.model_validate(agent)
    base.disabled_toolsets = list(disabled_toolsets_for(agent.toolset_tier))
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


# ── 管理员 ────────────────────────────────────────────────
@admin_router.get("", response_model=list[AgentOut])
async def list_agents(
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AgentOut]:
    rows = (
        await session.execute(select(Agent).order_by(Agent.created_at.desc()))
    ).scalars().all()
    return [_to_out(a) for a in rows]


@admin_router.post("", response_model=AgentStatusOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreateIn,
    _: CurrentAdmin,
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

    agent = Agent(
        slug=body.slug,
        name=body.name,
        description=body.description,
        profile_name=profile_name_for(body.slug),
        status=body.status,
        toolset_tier=body.toolset_tier,
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

    logger.info("创建 Agent %s -> profile %s", agent.slug, agent.profile_name)
    out = _to_out(agent, with_status=True)
    out.profile_exists = True
    out.gateway_running = bool(result.get("served_now", True))
    return out


@admin_router.get("/{agent_id}", response_model=AgentStatusOut)
async def get_agent(
    agent_id: int,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    live: bool = Query(default=False),
) -> AgentStatusOut:
    agent = await _get_or_404(session, agent_id)
    live_info = None
    if live:
        try:
            live_info = await profile_status(agent.slug)
        except Exception as exc:  # noqa: BLE001 - dashboard 不可用不应让接口 500
            logger.warning("查询 profile 状态失败: %s", exc)
    return _to_out(agent, with_status=True, live=live_info)


@admin_router.patch("/{agent_id}", response_model=AgentStatusOut)
async def update_agent(
    agent_id: int,
    body: AgentUpdateIn,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    agent = await _get_or_404(session, agent_id)

    if body.name is not None:
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description
    if body.status is not None:
        agent.status = body.status
    if body.toolset_tier is not None:
        agent.toolset_tier = body.toolset_tier

    try:
        await prov.sync_agent_profile(
            agent, soul=body.soul, model=body.model, provider=body.provider
        )
    except ProvisionError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    await session.commit()
    await session.refresh(agent)
    return _to_out(agent, with_status=True)


@admin_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: int,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    agent = await _get_or_404(session, agent_id)
    try:
        await prov.delete_agent_profile(agent)
    except Exception as exc:  # noqa: BLE001
        # profile 删除失败不应阻止 DB 清理，但要记录
        logger.warning("删除 profile 失败（继续删 DB 记录）: %s", exc)
    await session.delete(agent)
    await session.commit()


@admin_router.post("/{agent_id}/publish", response_model=AgentStatusOut)
async def publish_agent(
    agent_id: int,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    agent = await _get_or_404(session, agent_id)
    agent.status = AgentStatus.PUBLISHED
    await session.commit()
    await session.refresh(agent)
    return _to_out(agent, with_status=True)


@admin_router.post("/{agent_id}/unpublish", response_model=AgentStatusOut)
async def unpublish_agent(
    agent_id: int,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentStatusOut:
    agent = await _get_or_404(session, agent_id)
    agent.status = AgentStatus.DRAFT
    await session.commit()
    await session.refresh(agent)
    return _to_out(agent, with_status=True)


# ── 用户（只读，只看 published）────────────────────────────
@user_router.get("", response_model=list[AgentOut])
async def list_visible_agents(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AgentOut]:
    rows = (
        await session.execute(
            select(Agent)
            .where(Agent.status == AgentStatus.PUBLISHED)
            .order_by(Agent.name)
        )
    ).scalars().all()
    return [_to_out(a) for a in rows]


async def _get_or_404(session: AsyncSession, agent_id: int) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    return agent
