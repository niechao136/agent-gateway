"""Skill 双来源（SPEC-v2 批次 2）：

- 内置 Skill：只读代理 hermes dashboard API（GET /api/skills）+
  级联禁用（先 409 列出受影响 Agent，确认后逐个 toggle）
- 自定义 Skill：控制层 CRUD + Agent 绑定 + 直写 profile skills/ 目录
"""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..hermes.skill_sync import SkillSyncError, apply_custom_skills, remove_skill_dir
from ..hermes.toolset_forcing import apply_forced_toolsets as _apply_forced_toolsets
from ..hermes.toolset_forcing import compute_forced as _compute_forced
from ..hermes.skills import SkillError, list_skills, read_skill, toggle_skill
from ..models import (
    Agent,
    AgentBuiltinSkill,
    AgentCustomSkill,
    BuiltinSkillState,
    CustomSkill,
    UserRole,
)
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)


async def _sync_forced(agent: "Agent", session: "AsyncSession") -> None:
    """绑定/解绑 Skill 后同步强制工具集（skills / scripts→terminal）。"""
    try:
        forced = await _compute_forced(agent, session)
        _apply_forced_toolsets(agent, forced)
    except Exception as exc:  # noqa: BLE001
        logger.warning("同步强制工具集失败（agent=%s）：%s", agent.slug, exc)
_settings = get_settings()

router = APIRouter(prefix="/api/skills", tags=["skills"])
agent_router = APIRouter(prefix="/api/agents", tags=["agent-skills"])


# ── 内置 Skill（只读代理 + 级联禁用）───────────────────────
class BuiltinSkillOut(BaseModel):
    name: str
    description: str | None = None
    enabled: bool = True
    used_by_agents: list[int] = []


class BuiltinToggleIn(BaseModel):
    enabled: bool
    affected_agent_ids: list[int] = []  # 确认级联时要禁用的 Agent 列表


@router.get("/builtin", response_model=list[BuiltinSkillOut])
async def list_builtin(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    profile: str | None = None,
) -> list[BuiltinSkillOut]:
    """聚合 hermes dashboard 的 skill 列表 + 控制层启停状态 + 使用中的 Agent。"""
    try:
        raw = await list_skills(profile or "default")
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    states = {
        s.name: s.enabled
        for s in (
            await session.execute(select(BuiltinSkillState))
        ).scalars().all()
    }
    # 使用中：绑定了任一自定义技能无关；内置技能无法精确知道 Agent 使用情况，
    # 用"该 Agent 上次 toggle 的记录"近似——控制层只存全局状态，用于级联提示
    out: list[BuiltinSkillOut] = []
    for s in raw:
        name = s.get("name") or ""
        if not name:
            continue
        out.append(
            BuiltinSkillOut(
                name=name,
                description=s.get("description"),
                enabled=states.get(name, bool(s.get("enabled", True))),
            )
        )
    return out


@router.get("/builtin/{name}/content")
async def get_builtin_content(
    name: str,
    _: CurrentUser,
    profile: str | None = None,
) -> dict:
    """读取内置技能 SKILL.md 正文（用 default profile，供管理页查看）。"""
    try:
        meta = await read_skill(profile or "default", name)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if (meta.get("provenance") or "") != "bundled":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "不是内置技能")
    return {
        "name": meta.get("name") or name,
        "description": meta.get("description"),
        "content": meta.get("content") or "",
    }


@router.put("/builtin/{name}")
async def toggle_builtin(
    name: str,
    body: BuiltinToggleIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """内置技能全局启停。

    - 传 enabled=False 且未确认 affected_agent_ids 时：
      若有 Agent 绑定了该技能（无法精确探测，控制层以 409 提示确认），返回 409
    - 确认后：逐个对 affected Agent profile 调 hermes toggle + 记录全局状态
    """
    if not user or user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "内置技能启停需要管理员")

    if not body.enabled and not body.affected_agent_ids:
        # 级联确认：内置技能是全局资源，禁用影响所有 Agent
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "禁用内置技能会影响使用它的 Agent，请确认受影响列表",
                "requires_confirmation": True,
            },
        )

    results: list[dict] = []
    errors: list[str] = []
    for aid in body.affected_agent_ids:
        agent = (
            await session.execute(select(Agent).where(Agent.id == aid))
        ).scalar_one_or_none()
        if agent is None:
            errors.append(f"Agent {aid} 不存在")
            continue
        try:
            await toggle_skill(agent.profile_name, name, body.enabled)
            results.append({"agent_id": aid, "ok": True})
        except SkillError as exc:
            errors.append(f"Agent {aid}: {exc}")
            results.append({"agent_id": aid, "ok": False, "error": str(exc)})

    # 记录全局状态
    st = (
        await session.execute(
            select(BuiltinSkillState).where(BuiltinSkillState.name == name)
        )
    ).scalar_one_or_none()
    if st is None:
        st = BuiltinSkillState(name=name, enabled=body.enabled)
        session.add(st)
    else:
        st.enabled = body.enabled
    await session.commit()

    return {
        "name": name,
        "enabled": body.enabled,
        "agents": results,
        "errors": errors,
    }


# ── 自定义 Skill CRUD ─────────────────────────────────────
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _validate_name(name: str) -> str:
    """技能名必须是 ASCII slug（小写字母/数字/下划线/连字符）。

    它同时作为 profile 里的目录名和 Hermes 的技能标识，非 ASCII 会带来
    路径/locale 问题。中文等展示需求请用 display_name。
    """
    v = (name or "").strip()
    if not _NAME_RE.match(v):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "技能名只能是小写英文字母、数字、下划线或连字符（如 weather-alert）；"
            "中文请填「显示名称」",
        )
    return v


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    content: str = Field(min_length=1)
    files: dict[str, str] | None = None
    is_shared: bool = False


class SkillUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    content: str | None = None
    files: dict[str, str] | None = None
    is_shared: bool | None = None


class SkillOut(BaseModel):
    id: int
    name: str
    display_name: str | None = None
    owner_id: int
    description: str | None
    is_shared: bool
    bound_agents: list[int] = []


class SkillDetailOut(SkillOut):
    content: str
    files: dict[str, str] | None = None


def _out(s: CustomSkill, bound: list[int] | None = None) -> SkillOut:
    return SkillOut(
        id=s.id,
        name=s.name,
        display_name=s.display_name,
        owner_id=s.owner_id,
        description=s.description,
        is_shared=s.is_shared,
        bound_agents=bound or [],
    )


@router.get("/{skill_id}", response_model=SkillDetailOut)
async def get_skill(
    skill_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SkillDetailOut:
    """技能详情（含正文与 files），用于编辑回填。"""
    s = (
        await session.execute(select(CustomSkill).where(CustomSkill.id == skill_id))
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "技能不存在")
    if s.owner_id != user.id and not s.is_shared:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的技能正文")
    return SkillDetailOut(
        **_out(s).model_dump(),
        content=s.content,
        files=s.files,
    )


@router.get("", response_model=list[SkillOut])
async def list_skills_route(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SkillOut]:
    if user.role == UserRole.ADMIN:
        stmt = select(CustomSkill).order_by(CustomSkill.id)
    else:
        stmt = select(CustomSkill).where(
            or_(CustomSkill.owner_id == user.id, CustomSkill.is_shared == True)  # noqa: E712
        ).order_by(CustomSkill.id)
    rows = (await session.execute(stmt)).scalars().all()

    bindings = (
        await session.execute(select(AgentCustomSkill))
    ).scalars().all()
    by_skill: dict[int, list[int]] = {}
    for b in bindings:
        by_skill.setdefault(b.skill_id, []).append(b.agent_id)
    return [_out(s, by_skill.get(s.id, [])) for s in rows]


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(
    body: SkillIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SkillOut:
    name = _validate_name(body.name)
    exists = (
        await session.execute(
            select(CustomSkill).where(
                CustomSkill.owner_id == user.id, CustomSkill.name == name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名技能已存在")

    s = CustomSkill(
        owner_id=user.id,
        name=name,
        display_name=(body.display_name or body.name),
        description=body.description,
        content=body.content,
        files=body.files,
        is_shared=body.is_shared and user.role == UserRole.ADMIN,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return _out(s)


async def _skill_or_404(session: AsyncSession, skill_id: int, user) -> CustomSkill:
    s = (
        await session.execute(select(CustomSkill).where(CustomSkill.id == skill_id))
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "技能不存在")
    if not can_modify(user, s.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的技能")
    return s


@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: int,
    body: SkillUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SkillOut:
    s = await _skill_or_404(session, skill_id, user)
    for field in ("description", "content", "files"):
        v = getattr(body, field)
        if v is not None:
            setattr(s, field, v)
    if body.is_shared is not None:
        if user.role != UserRole.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "共享/取消共享需要管理员")
        s.is_shared = body.is_shared
    await session.commit()
    await session.refresh(s)

    # 内容变更 → 同步所有绑定 profile
    await _sync_bound_agents(session, s)
    return _out(s)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    force: bool = False,
) -> None:
    s = await _skill_or_404(session, skill_id, user)
    bound = (
        await session.execute(
            select(AgentCustomSkill).where(AgentCustomSkill.skill_id == skill_id)
        )
    ).scalars().all()
    if bound and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"该技能仍被 {len(bound)} 个 Agent 绑定；传 ?force=true 确认删除并解绑",
        )
    agent_ids = [b.agent_id for b in bound]
    for b in bound:
        await session.delete(b)
    await session.flush()

    # 删 profile 里的目录
    for aid in agent_ids:
        agent = (
            await session.execute(select(Agent).where(Agent.id == aid))
        ).scalar_one_or_none()
        if agent is not None:
            try:
                remove_skill_dir(agent.profile_name, _settings.hermes_data_root, s.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("删除技能目录失败: %s", exc)

    await session.delete(s)
    await session.commit()


# ── Agent 内置 Skill 选择（按 Agent 隔离，默认全不选）──────
@agent_router.get("/{agent_id}/skills/builtin")
async def list_agent_builtin_skills(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """列出该 Agent 可选的内置 Skill，附 selected 状态。

    内置技能列表来自 hermes dashboard（GET /api/skills）；默认全不选。
    与自定义 Skill 用独立的 AgentBuiltinSkill 表，ID 空间互不干扰。
    """
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    selected = set(
        (
            await session.execute(
                select(AgentBuiltinSkill.skill_name).where(
                    AgentBuiltinSkill.agent_id == agent_id
                )
            )
        ).scalars().all()
    )
    try:
        available = await list_skills(agent.profile_name)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    # 平台管理的自定义技能名：这些有自己的管理页，不算"内置"。
    managed_names = set(
        (await session.execute(select(CustomSkill.name))).scalars().all()
    )

    items = []
    for s in available:
        name = s.get("name") or ""
        if not name:
            continue
        # 只列 Hermes 自带的内置技能。provenance 取值：
        # 排除"非内置"的两类：
        #   1) 平台下发的自定义 Skill（有自己的管理页，且已绑定时按名称排除）
        #   2) curator 运行时自动沉淀的影子技能（归入"自定义"区）
        # 判定用 provenance 优先；若上游未提供该字段（旧版本/精简实现），
        # 退化为"不在平台自定义技能表里即视为内置"，避免把真正的内置技能过滤掉。
        prov = s.get("provenance")
        if prov is not None:
            if prov != "bundled":
                continue
        elif name in managed_names:
            continue
        items.append(
            {
                "name": name,
                "description": s.get("description"),
                "category": s.get("category"),
                "usage": s.get("usage", 0),
                "locked": bool(s.get("locked")),
                "enabled": bool(s.get("enabled")),
                "selected": name in selected,
            }
        )
    return {"agent_id": agent_id, "profile": agent.profile_name, "skills": items}


@agent_router.get("/{agent_id}/skills/curated")
async def list_agent_curated_skills(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """列出 Hermes curator（技能策展器）在该 Agent profile 里自动沉淀的技能。

    curator 是 Hermes 的后台自动学习机制：把成功解决过的问题固化成技能。
    这些技能由运行时产生、不在平台的 custom_skills 表里，但对模型可见并与
    自定义 Skill 争夺匹配，因此单独列出（归入"自定义"区），并按 Hermes 里
    的实际启用状态显示，便于用户查看/关闭。
    """
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    # 平台管理的自定义技能名（这些不算 curator 产物）
    managed = set(
        (
            await session.execute(
                select(CustomSkill.name).join(
                    AgentCustomSkill, AgentCustomSkill.skill_id == CustomSkill.id
                ).where(AgentCustomSkill.agent_id == agent_id)
            )
        ).scalars().all()
    )

    try:
        available = await list_skills(agent.profile_name)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    items = []
    for s in available:
        name = s.get("name") or ""
        if not name:
            continue
        if (s.get("provenance") or "") == "bundled":
            continue
        if name in managed:
            continue
        items.append(
            {
                "name": name,
                "description": s.get("description"),
                "category": s.get("category"),
                "usage": s.get("usage", 0),
                "enabled": bool(s.get("enabled")),
                "provenance": s.get("provenance"),
            }
        )
    return {
        "agent_id": agent_id,
        "profile": agent.profile_name,
        "curator_enabled": bool(get_settings().curator_enabled),
        "skills": items,
    }


@agent_router.get("/{agent_id}/skills/builtin/{name}")
async def get_builtin_skill_detail(
    agent_id: int,
    name: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """读取单个内置 Skill 的详情（含 SKILL.md 正文），供 UI 展开查看。"""
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的 Agent")
    try:
        meta = await read_skill(agent.profile_name, name)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    # 只允许查看内置技能，避免越权读取其他来源的目录内容
    if (meta.get("provenance") or "") != "bundled":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "不是内置技能")
    return {
        "name": meta.get("name") or name,
        "description": meta.get("description"),
        "category": meta.get("category"),
        "enabled": meta.get("enabled"),
        "usage": meta.get("usage"),
        "content": meta.get("content") or "",
    }


@agent_router.put("/{agent_id}/skills/builtin")
async def set_agent_builtin_skills(
    agent_id: int,
    body: dict,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """整体替换该 Agent 选中的内置 Skill：body = {"skill_names": [...]}。

    对差异项逐个调 hermes toggle（内置技能按 profile 隔离），
    并更新控制层记录。默认全不选 = 传空数组 = 全部关闭。
    """
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    names = body.get("skill_names")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "skill_names 必须是字符串数组")
    want = set(names)

    old_rows = (
        await session.execute(
            select(AgentBuiltinSkill).where(AgentBuiltinSkill.agent_id == agent_id)
        )
    ).scalars().all()
    old = {r.skill_name for r in old_rows}

    changed: list[str] = []
    errors: list[str] = []

    # 取消选择：从表里移除 + hermes 关闭
    for r in old_rows:
        if r.skill_name not in want:
            try:
                await toggle_skill(agent.profile_name, r.skill_name, False)
            except SkillError as exc:
                errors.append(f"关闭 {r.skill_name}: {exc}")
            await session.delete(r)
            changed.append(r.skill_name)

    # 新增选择：写表 + hermes 开启
    for name in want - old:
        session.add(AgentBuiltinSkill(agent_id=agent_id, skill_name=name))
        try:
            await toggle_skill(agent.profile_name, name, True)
        except SkillError as exc:
            errors.append(f"开启 {name}: {exc}")
        changed.append(name)

    await _sync_forced(agent, session)
    await session.commit()
    return {
        "agent_id": agent_id,
        "selected": sorted(want),
        "changed": changed,
        "errors": errors,
    }


# ── Agent 绑定（自定义技能）────────────────────────────────
@agent_router.get("/{agent_id}/skills")
async def list_agent_skills(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    rows = (
        await session.execute(
            select(CustomSkill)
            .join(AgentCustomSkill, AgentCustomSkill.skill_id == CustomSkill.id)
            .where(AgentCustomSkill.agent_id == agent_id)
        )
    ).scalars().all()
    return {
        "agent_id": agent_id,
        "profile": agent.profile_name,
        "bound": [_out(s) for s in rows],
    }


@agent_router.put("/{agent_id}/skills")
async def set_agent_skills(
    agent_id: int,
    body: dict,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """body = {"skill_ids": [...]}。整体替换绑定并同步 profile。"""
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    ids = body.get("skill_ids")
    if not isinstance(ids, list):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "skill_ids 必须是数组")

    skills: list[CustomSkill] = []
    for sid in ids:
        s = (
            await session.execute(select(CustomSkill).where(CustomSkill.id == sid))
        ).scalar_one_or_none()
        if s is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"技能 {sid} 不存在")
        if s.owner_id != user.id and not s.is_shared:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"技能 {s.name} 不可绑定（非本人且未共享）")
        skills.append(s)

    old = (
        await session.execute(
            select(AgentCustomSkill).where(AgentCustomSkill.agent_id == agent_id)
        )
    ).scalars().all()
    for b in old:
        await session.delete(b)
    # 先 flush 删除，避免同主键的 DELETE/INSERT 顺序不确定触发唯一约束（重复保存 500）。
    if old:
        await session.flush()
    for s in skills:
        session.add(AgentCustomSkill(agent_id=agent_id, skill_id=s.id))
    await session.flush()

    # 先同步强制工具集（从 disabled 移除 skills/terminal 并写 config），
    # 再下发技能文件——否则 skill_sync 读到旧的 disabled 状态会剥离 scripts/。
    await _sync_forced(agent, session)
    res = _apply_profile(agent, skills)
    await session.commit()
    return {"bound": len(skills), "sync": res}


@agent_router.post("/{agent_id}/skills/create-and-bind", status_code=201)
async def create_and_bind_skill(
    agent_id: int,
    body: SkillIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    exists = (
        await session.execute(
            select(CustomSkill).where(
                CustomSkill.owner_id == user.id, CustomSkill.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        s = exists
        created = False
    else:
        s = CustomSkill(
            owner_id=user.id,
            name=body.name,
            description=body.description,
            content=body.content,
            files=body.files,
            is_shared=body.is_shared and user.role == UserRole.ADMIN,
        )
        session.add(s)
        await session.flush()
        created = True

    dup = (
        await session.execute(
            select(AgentCustomSkill).where(
                AgentCustomSkill.agent_id == agent_id, AgentCustomSkill.skill_id == s.id
            )
        )
    ).scalar_one_or_none()
    if dup is None:
        session.add(AgentCustomSkill(agent_id=agent_id, skill_id=s.id))
        await session.flush()

    # 重新取全量绑定再同步
    bound = list(
        (
            await session.execute(
                select(CustomSkill)
                .join(AgentCustomSkill, AgentCustomSkill.skill_id == CustomSkill.id)
                .where(AgentCustomSkill.agent_id == agent_id)
            )
        ).scalars().all()
    )
    await _sync_forced(agent, session)
    res = _apply_profile(agent, bound)
    await session.commit()
    return {"created": created, "skill": _out(s).model_dump(), "sync": res}


# ── 同步 ──────────────────────────────────────────────────
def _apply_profile(agent: Agent, skills: list[CustomSkill]) -> dict:
    try:
        return apply_custom_skills(
            agent.profile_name,
            _settings.hermes_data_root,
            skills,
            disabled_toolsets=list(agent.disabled_toolsets or []),
        )
    except (SkillSyncError, OSError) as exc:
        logger.warning("自定义技能同步失败（agent=%s）：%s", agent.slug, exc)
        return {"ok": False, "error": str(exc)}


async def _sync_bound_agents(session: AsyncSession, s: CustomSkill) -> None:
    rows = (
        await session.execute(
            select(AgentCustomSkill).where(AgentCustomSkill.skill_id == s.id)
        )
    ).scalars().all()
    for b in rows:
        agent = (
            await session.execute(select(Agent).where(Agent.id == b.agent_id))
        ).scalar_one_or_none()
        if agent is None:
            continue
        bound = list(
            (
                await session.execute(
                    select(CustomSkill)
                    .join(AgentCustomSkill, AgentCustomSkill.skill_id == CustomSkill.id)
                    .where(AgentCustomSkill.agent_id == agent.id)
                )
            ).scalars().all()
        )
        _apply_profile(agent, bound)
