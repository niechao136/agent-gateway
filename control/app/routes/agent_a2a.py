"""Agent 的 A2A 端点配置（登录即可，写操作校验归属）。"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..hermes.a2a import (
    A2AError,
    apply_a2a_endpoints,
    read_a2a_section,
    validate_endpoint,
)
from ..models import A2AEndpoint, Agent
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(prefix="/api/agents", tags=["agent-a2a"])


class EndpointIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=8, max_length=512)
    capabilities: list[str] = Field(default_factory=list)
    timeout: int = Field(default=120, ge=1, le=3600)
    enabled: bool = True


class EndpointUpdateIn(BaseModel):
    name: str | None = None
    url: str | None = None
    capabilities: list[str] | None = None
    timeout: int | None = Field(default=None, ge=1, le=3600)
    enabled: bool | None = None


class EndpointOut(BaseModel):
    id: int
    name: str
    url: str
    capabilities: list[str] = []
    timeout: int
    enabled: bool

    model_config = {"from_attributes": True}


def _out(e: A2AEndpoint) -> EndpointOut:
    return EndpointOut(
        id=e.id,
        name=e.name,
        url=e.url,
        capabilities=list(e.capabilities or []),
        timeout=e.timeout,
        enabled=e.enabled,
    )


async def _agent_or_404(session: AsyncSession, agent_id: int, user) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")
    return agent


async def _apply(agent: Agent, session: AsyncSession) -> str | None:
    """下发到 profile 的 config.yaml。返回错误信息（None 表示成功）。

    写入失败不回滚 DB——配置已存，用户可以修好环境后重试下发。
    """
    rows = (
        await session.execute(
            select(A2AEndpoint)
            .where(A2AEndpoint.agent_id == agent.id, A2AEndpoint.enabled.is_(True))
            .order_by(A2AEndpoint.id)
        )
    ).scalars().all()

    payload = [
        {
            "name": r.name,
            "url": r.url,
            "timeout": r.timeout,
            "capabilities": r.capabilities or [],
        }
        for r in rows
    ]

    try:
        apply_a2a_endpoints(agent.profile_name, _settings.hermes_data_root, payload)
        return None
    except A2AError as exc:
        logger.warning("下发 A2A 配置失败（DB 已保存）: %s", exc)
        return str(exc)


@router.get("/{agent_id}/a2a", response_model=list[EndpointOut])
async def list_endpoints(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[EndpointOut]:
    await _agent_or_404(session, agent_id, user)
    rows = (
        await session.execute(
            select(A2AEndpoint)
            .where(A2AEndpoint.agent_id == agent_id)
            .order_by(A2AEndpoint.id)
        )
    ).scalars().all()
    return [_out(e) for e in rows]


@router.post("/{agent_id}/a2a", response_model=dict, status_code=201)
async def create_endpoint(
    agent_id: int,
    body: EndpointIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_or_404(session, agent_id, user)
    try:
        validate_endpoint(body.name, body.url)
    except A2AError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    exists = (
        await session.execute(
            select(A2AEndpoint).where(
                A2AEndpoint.agent_id == agent_id, A2AEndpoint.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名端点已存在")

    ep = A2AEndpoint(
        agent_id=agent_id,
        name=body.name,
        url=body.url,
        capabilities=body.capabilities or None,
        timeout=body.timeout,
        enabled=body.enabled,
    )
    session.add(ep)
    await session.commit()
    await session.refresh(ep)

    err = await _apply(agent, session)
    return {"endpoint": _out(ep).model_dump(), "apply_error": err}


@router.patch("/{agent_id}/a2a/{endpoint_id}", response_model=dict)
async def update_endpoint(
    agent_id: int,
    endpoint_id: int,
    body: EndpointUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_or_404(session, agent_id, user)
    ep = (
        await session.execute(
            select(A2AEndpoint).where(
                A2AEndpoint.id == endpoint_id, A2AEndpoint.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "端点不存在")

    if body.name is not None or body.url is not None:
        try:
            validate_endpoint(body.name or ep.name, body.url or ep.url)
        except A2AError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    if body.name is not None:
        ep.name = body.name
    if body.url is not None:
        ep.url = body.url
    if body.capabilities is not None:
        ep.capabilities = body.capabilities or None
    if body.timeout is not None:
        ep.timeout = body.timeout
    if body.enabled is not None:
        ep.enabled = body.enabled

    await session.commit()
    await session.refresh(ep)
    err = await _apply(agent, session)
    return {"endpoint": _out(ep).model_dump(), "apply_error": err}


@router.delete("/{agent_id}/a2a/{endpoint_id}", status_code=204)
async def delete_endpoint(
    agent_id: int,
    endpoint_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    agent = await _agent_or_404(session, agent_id, user)
    ep = (
        await session.execute(
            select(A2AEndpoint).where(
                A2AEndpoint.id == endpoint_id, A2AEndpoint.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "端点不存在")

    await session.delete(ep)
    await session.commit()
    await _apply(agent, session)


@router.get("/{agent_id}/a2a/effective")
async def get_effective(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """读取 profile 里**实际生效**的 a2a_agents（排查配置漂移用）。"""
    agent = await _agent_or_404(session, agent_id, user)
    effective = read_a2a_section(agent.profile_name, _settings.hermes_data_root)
    return {"profile": agent.profile_name, "a2a_agents": effective}
