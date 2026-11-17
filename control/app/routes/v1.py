"""对外 API v1（SPEC-v2 批次 3）。

设计要点（硬约束）：
- **不做 OpenAI 兼容**：Agent 有 profile/skills/会话状态，不是无状态 completion。
  语义用 Messages：POST /api/v1/agents/{slug}/messages
- 鉴权独立于登录用户体系：Authorization: Bearer agk_xxx
- 限流：滑动窗口，默认 60 req/min/key

会话：
- 请求不带 session_id → 新建会话
- 带 session_id → 复用（必须属于该 key 的 Agent）
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..hermes import chat_proxy, conversations as conv_svc
from ..hermes import gateway as gw_mod
from ..models import Agent, AgentAPIKey, AgentStatus, Conversation
from ..routes.api_keys import hash_key

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["v1"])

# ── 限流（进程内滑动窗口）─────────────────────────────────
_RATE_LIMIT = 60  # 次
_RATE_WINDOW = 60.0  # 秒
_hits: dict[str, deque[float]] = {}


def _check_rate_limit(key_id: str) -> None:
    now = time.monotonic()
    q = _hits.setdefault(key_id, deque())
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        retry = int(_RATE_WINDOW - (now - q[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"请求过于频繁，请 {retry} 秒后重试",
            headers={"Retry-After": str(retry)},
        )
    q.append(now)


def _reset_rate_limit() -> None:
    """测试用。"""
    _hits.clear()


# ── 鉴权 ──────────────────────────────────────────────────
async def api_key_agent_impl(
    request: Request,
    session: AsyncSession,
):
    """校验 agk_ Bearer → 返回 (key, agent)。"""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "缺少 API Key（Authorization: Bearer agk_...）",
            headers={"WWW-Authenticate": "Bearer"},
        )
    plain = auth[7:].strip()
    if not plain.startswith("agk_"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key 格式无效")

    key = (
        await session.execute(
            select(AgentAPIKey).where(AgentAPIKey.key_hash == hash_key(plain))
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key 无效")
    if not key.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API Key 已禁用")

    _check_rate_limit(str(key.id))

    agent = (
        await session.execute(select(Agent).where(Agent.id == key.agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key 关联的 Agent 已删除")

    # 记录使用时间（失败不影响主流程）
    try:
        key.last_used_at = datetime.now(UTC)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新 key.last_used_at 失败: %s", exc)
        await session.rollback()

    return key, agent


# ── Schemas（Messages 语义，非 OpenAI）────────────────────
class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=32000)
    session_id: str | None = None
    stream: bool = False


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class MessageOut(BaseModel):
    session_id: str
    agent: str
    reply: str
    usage: Usage | None = None
    created_at: str


class AgentBrief(BaseModel):
    slug: str
    name: str
    description: str | None
    status: str


class SessionOut(BaseModel):
    session_id: str
    agent: str
    title: str | None
    created_at: str
    last_active_at: str


def _brief(a: Agent) -> AgentBrief:
    return AgentBrief(slug=a.slug, name=a.name, description=a.description, status=a.status)


async def _resolve_agent_for_key(session: AsyncSession, ka: tuple, slug: str) -> Agent:
    key, bound = ka
    agent = (
        await session.execute(select(Agent).where(Agent.slug == slug))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if agent.id != bound.id:
        # Key 是按 Agent 隔离的（SPEC）：不能借自己的 key 访问别人的 Agent
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该 API Key 无权访问此 Agent")
    if agent.status != AgentStatus.PUBLISHED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent 未发布，对外 API 不可用")
    return agent


async def _get_or_create_session(
    session: AsyncSession, agent: Agent, session_id: str | None
) -> Conversation:
    """session_id 为空 → 新建；否则必须属于该 Agent。"""
    if not session_id:
        try:
            return await conv_svc.create_conversation_for_agent(session, agent=agent)
        except conv_svc.ConversationError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.hermes_session_id == session_id,
                Conversation.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在或不属于该 Agent")
    return conv


# ── 端点 ──────────────────────────────────────────────────
@router.get("/agents", response_model=list[AgentBrief])
async def list_my_agents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[AgentBrief]:
    key, agent = await api_key_agent_impl(request, session)
    return [_brief(agent)]


@router.post("/agents/{slug}/messages")
async def post_message(
    slug: str,
    body: MessageIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """发消息。stream=false 返回完整回复；stream=true 返回 SSE（与前端同一翻译管道）。"""
    ka = await api_key_agent_impl(request, session)
    agent = await _resolve_agent_for_key(session, ka, slug)
    conv = await _get_or_create_session(session, agent, body.session_id)
    sid = conv.hermes_session_id

    if body.stream:
        async def gen():
            gw = gw_mod.GatewayClient()
            try:
                async with gw:
                    async for frame in chat_proxy.translate_stream(
                        gw.chat_stream(sid, body.message), thread_id=sid
                    ):
                        yield frame
            finally:
                try:
                    await conv_svc.touch_conversation(session, conv)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("更新会话活跃时间失败: %s", exc)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # 非流式：聚合完整回复
    parts: list[str] = []
    usage: Usage | None = None
    gw = gw_mod.GatewayClient()
    try:
        async with gw:
            async for frame in chat_proxy.translate_stream(
                gw.chat_stream(sid, body.message), thread_id=sid
            ):
                text, u = chat_proxy.extract_text_and_usage(frame)
                if text:
                    parts.append(text)
                if u:
                    usage = Usage(**u)
    except gw_mod.GatewayError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"对话失败: {exc}") from exc
    finally:
        try:
            await conv_svc.touch_conversation(session, conv)
        except Exception as exc:  # noqa: BLE001
            logger.warning("更新会话活跃时间失败: %s", exc)

    return MessageOut(
        session_id=sid,
        agent=agent.slug,
        reply="".join(parts),
        usage=usage,
        created_at=datetime.now(UTC).isoformat(),
    )


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    key, agent = await api_key_agent_impl(request, session)
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.hermes_session_id == session_id,
                Conversation.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    return SessionOut(
        session_id=conv.hermes_session_id,
        agent=agent.slug,
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        last_active_at=conv.last_active_at.isoformat(),
    )


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = 200,
):
    key, agent = await api_key_agent_impl(request, session)
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.hermes_session_id == session_id,
                Conversation.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")

    from .chat import _normalize_messages

    async with gw_mod.GatewayClient() as gw:
        try:
            raw = await gw.session_messages(conv.hermes_session_id, limit=limit)
        except gw_mod.GatewayError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"读取历史失败: {exc}") from exc

    return {
        "session_id": conv.hermes_session_id,
        "agent": agent.slug,
        "messages": _normalize_messages(raw),
    }
