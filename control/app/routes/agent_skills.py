"""Agent 的 Skill 配置（登录即可，写操作校验归属）。"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes.skills import SkillError, list_skills, set_skills, toggle_skill
from ..models import Agent
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agent-skills"])


class SkillOut(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    enabled: bool = False
    locked: bool = False
    provenance: str | None = None


class ToggleIn(BaseModel):
    name: str
    enabled: bool


class SetSkillsIn(BaseModel):
    enabled: list[str]


async def _agent_or_404(session: AsyncSession, agent_id: int, user) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")
    return agent


@router.get("/{agent_id}/skills", response_model=list[SkillOut])
async def get_agent_skills(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SkillOut]:
    agent = await _agent_or_404(session, agent_id, user)
    try:
        raw = await list_skills(agent.profile_name)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return [
        SkillOut(
            name=s.get("name", ""),
            description=s.get("description"),
            category=s.get("category"),
            enabled=bool(s.get("enabled")),
            locked=bool(s.get("locked")),
            provenance=s.get("provenance"),
        )
        for s in raw
        if s.get("name")
    ]


@router.put("/{agent_id}/skills", response_model=list[SkillOut])
async def replace_agent_skills(
    agent_id: int,
    body: SetSkillsIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SkillOut]:
    """把该 Agent 的 skills 设为指定集合（其余禁用）。"""
    agent = await _agent_or_404(session, agent_id, user)
    try:
        await set_skills(agent.profile_name, body.enabled)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return await get_agent_skills(agent_id, user, session)


@router.post("/{agent_id}/skills/toggle", response_model=SkillOut)
async def toggle_agent_skill(
    agent_id: int,
    body: ToggleIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SkillOut:
    agent = await _agent_or_404(session, agent_id, user)
    # 先确认该 skill 存在，避免下游 502（未知 skill 语义上是 404）
    current = await list_skills(agent.profile_name)
    if not any(s.get("name") == body.name for s in current):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"skill {body.name} 不存在")

    try:
        await toggle_skill(agent.profile_name, body.name, body.enabled)
    except SkillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    current = await list_skills(agent.profile_name)
    for s in current:
        if s.get("name") == body.name:
            return SkillOut(
                name=s.get("name", ""),
                description=s.get("description"),
                category=s.get("category"),
                enabled=bool(s.get("enabled")),
                locked=bool(s.get("locked")),
                provenance=s.get("provenance"),
            )
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"skill {body.name} 不存在")
