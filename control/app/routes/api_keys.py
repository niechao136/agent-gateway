"""AgentAPIKey 管理（批次 3）：生成 / 列表 / 启停 / 删除。

安全语义（用户拍板）：
- 手动生成，创建 Agent 不自动发 Key
- key_hash = SHA-256(明文)，明文仅创建响应返回一次
- 列表只回 key_prefix（agk_ 前 8 位）
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Agent, AgentAPIKey
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["api-keys"])

KEY_PREFIX_TAG = "agk_"


def generate_key() -> tuple[str, str, str]:
    """(明文, hash, prefix)。明文仅此刻存在，调用方负责一次性返回。"""
    plain = KEY_PREFIX_TAG + secrets.token_hex(16)  # agk_ + 32 hex
    key_hash = hashlib.sha256(plain.encode()).hexdigest()
    key_prefix = plain[:12]  # agk_xxxxxxxx
    return plain, key_hash, key_prefix


def hash_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


class APIKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class APIKeyOut(BaseModel):
    id: int
    agent_id: int
    name: str
    key_prefix: str
    enabled: bool
    created_at: datetime | None
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class APIKeyCreatedOut(APIKeyOut):
    """创建响应：明文仅此一次。"""
    key: str


async def _agent_owned_or_404(session: AsyncSession, agent_id: int, user) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")
    return agent


@router.get("/{agent_id}/api-keys", response_model=list[APIKeyOut])
async def list_keys(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[APIKeyOut]:
    await _agent_owned_or_404(session, agent_id, user)
    rows = (
        await session.execute(
            select(AgentAPIKey)
            .where(AgentAPIKey.agent_id == agent_id)
            .order_by(AgentAPIKey.id)
        )
    ).scalars().all()
    return [APIKeyOut.model_validate(k) for k in rows]


@router.post("/{agent_id}/api-keys", response_model=APIKeyCreatedOut, status_code=201)
async def create_key(
    agent_id: int,
    body: APIKeyIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> APIKeyCreatedOut:
    await _agent_owned_or_404(session, agent_id, user)

    exists = (
        await session.execute(
            select(AgentAPIKey).where(
                AgentAPIKey.agent_id == agent_id, AgentAPIKey.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名 Key 已存在")

    plain, key_hash, key_prefix = generate_key()
    k = AgentAPIKey(
        agent_id=agent_id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    session.add(k)
    await session.commit()
    await session.refresh(k)

    logger.info("生成 API Key agent=%s name=%s", agent_id, body.name)
    out = APIKeyCreatedOut(
        key=plain,
        **APIKeyOut.model_validate(k).model_dump(),
    )
    return out


@router.patch("/{agent_id}/api-keys/{key_id}", response_model=APIKeyOut)
async def update_key(
    agent_id: int,
    key_id: int,
    body: dict,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> APIKeyOut:
    await _agent_owned_or_404(session, agent_id, user)
    k = (
        await session.execute(
            select(AgentAPIKey).where(
                AgentAPIKey.id == key_id, AgentAPIKey.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key 不存在")

    if "enabled" in body:
        k.enabled = bool(body["enabled"])
    if "name" in body and body["name"]:
        k.name = body["name"]
    await session.commit()
    await session.refresh(k)
    return APIKeyOut.model_validate(k)


@router.delete("/{agent_id}/api-keys/{key_id}", status_code=204)
async def delete_key(
    agent_id: int,
    key_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await _agent_owned_or_404(session, agent_id, user)
    k = (
        await session.execute(
            select(AgentAPIKey).where(
                AgentAPIKey.id == key_id, AgentAPIKey.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key 不存在")
    await session.delete(k)
    await session.commit()
