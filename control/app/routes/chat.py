"""对话路由：会话 CRUD + SSE 流式对话。

所有端点都要求 user scope，且**强制**归属校验（SPEC §5.1）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes import chat_proxy, conversations as conv_svc
from ..hermes import gateway as gw_mod
from ..models import Agent, AgentStatus, Conversation
from ..security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Schemas ───────────────────────────────────────────────
class ConversationCreateIn(BaseModel):
    agent_slug: str
    first_message: str | None = None


class ConversationOut(BaseModel):
    id: int
    agent_id: int
    agent_slug: str | None = None
    hermes_session_id: str
    title: str | None
    created_at: str
    last_active_at: str

    model_config = {"from_attributes": True}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=32000)


def _out(conv: Conversation, slug: str | None = None) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        agent_id=conv.agent_id,
        agent_slug=slug,
        hermes_session_id=conv.hermes_session_id,
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        last_active_at=conv.last_active_at.isoformat(),
    )


async def _published_agent(session: AsyncSession, slug: str) -> Agent:
    agent = (
        await session.execute(
            select(Agent).where(
                Agent.slug == slug, Agent.status == AgentStatus.PUBLISHED
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在或未发布")
    return agent


# ── 会话 CRUD ─────────────────────────────────────────────
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    agent_slug: str | None = None,
) -> list[ConversationOut]:
    agent_id = None
    slug = None
    if agent_slug:
        agent = await _published_agent(session, agent_slug)
        agent_id, slug = agent.id, agent.slug

    rows = await conv_svc.list_conversations(session, user=user, agent_id=agent_id)

    # 批量取 slug 映射，避免 N+1
    if rows and slug is None:
        ids = {c.agent_id for c in rows}
        agents = (
            await session.execute(select(Agent).where(Agent.id.in_(ids)))
        ).scalars().all()
        slug_map = {a.id: a.slug for a in agents}
    else:
        slug_map = {agent_id: slug} if agent_id and slug else {}

    return [_out(c, slug_map.get(c.agent_id)) for c in rows]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationOut:
    agent = await _published_agent(session, body.agent_slug)
    try:
        conv = await conv_svc.create_conversation(
            session, user=user, agent=agent, first_message=body.first_message
        )
    except conv_svc.ConversationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return _out(conv, agent.slug)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationOut:
    try:
        conv = await conv_svc.get_owned_conversation(
            session, user=user, conversation_id=conversation_id
        )
    except conv_svc.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    agent = (
        await session.execute(select(Agent).where(Agent.id == conv.agent_id))
    ).scalar_one_or_none()
    return _out(conv, agent.slug if agent else None)


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 100,
) -> dict:
    """从 hermes 拉历史消息。"""
    try:
        conv = await conv_svc.get_owned_conversation(
            session, user=user, conversation_id=conversation_id
        )
    except conv_svc.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    async with gw_mod.GatewayClient() as gw:
        try:
            msgs = await gw.session_messages(conv.hermes_session_id, limit=limit)
        except gw_mod.GatewayError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"读取历史失败: {exc}") from exc
    return {"conversation_id": conversation_id, "messages": msgs}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """软删：只标记，不删 hermes 侧（SPEC §12 决策 4）。"""
    try:
        conv = await conv_svc.get_owned_conversation(
            session, user=user, conversation_id=conversation_id
        )
    except conv_svc.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await conv_svc.soft_delete_conversation(session, conv)


@router.post("/conversations/{conversation_id}/restore", response_model=ConversationOut)
async def restore_conversation(
    conversation_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationOut:
    try:
        conv = await conv_svc.restore_conversation(
            session, user=user, conversation_id=conversation_id
        )
    except conv_svc.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _out(conv)


# ── 流式对话 ──────────────────────────────────────────────
@router.post("/conversations/{conversation_id}/stream")
async def chat_stream(
    conversation_id: int,
    body: ChatIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    """把 hermes 的 SSE 翻译成前端契约后返回。"""
    try:
        conv = await conv_svc.get_owned_conversation(
            session, user=user, conversation_id=conversation_id
        )
    except conv_svc.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    sid = conv.hermes_session_id

    async def gen() -> AsyncIterator[bytes]:
        gw = gw_mod.GatewayClient()
        try:
            async with gw:
                async for frame in chat_proxy.translate_stream(
                    gw.chat_stream(sid, body.message), thread_id=sid
                ):
                    yield frame
        finally:
            # 更新活跃时间（失败不影响流已发出的内容）
            try:
                await conv_svc.touch_conversation(session, conv)
            except Exception as exc:  # noqa: BLE001
                logger.warning("更新会话活跃时间失败: %s", exc)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 让 nginx 不缓冲 SSE
            "Connection": "keep-alive",
        },
    )
