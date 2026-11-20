"""A2A 服务端：把本平台已发布的 Agent 暴露为 A2A Agent 供外部 Agent 调用。

参照 a2a-gateway 的 a2a_server.py 实现，不依赖 a2a-sdk；与 v1 对外 API 共用
AgentAPIKey 鉴权、会话与对话管道。

对外端点（公开，无需 JWT，用 agk_ API Key 鉴权）：
    GET  /a2a/{slug}/.well-known/agent-card.json   Agent Card
    GET  /a2a/{slug}                               Agent Card（兼容）
    POST /a2a/{slug}                               JSON-RPC 2.0
                                                   - message/send / SendMessage（同步）
                                                   - message/stream / SendStreamingMessage（SSE）
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes import chat_proxy
from ..hermes import conversations as conv_svc
from ..hermes import gateway as gw_mod
from ..models import Agent, AgentAPIKey, AgentStatus
from .api_keys import hash_key
from .v1 import _get_or_create_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["a2a-server"])

METHOD_ALIASES = {
    "SendMessage": "SendMessage",
    "message/send": "SendMessage",
    "SendStreamingMessage": "SendStreamingMessage",
    "message/stream": "SendStreamingMessage",
}


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def _card(agent: Agent, base_url: str) -> dict:
    path = f"/a2a/{agent.slug}"
    url = base_url.rstrip("/") + path
    return {
        "name": agent.name,
        "description": agent.description or "",
        "url": url,
        "version": "1.0.0",
        "protocolVersion": "1.0",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "supportedInterfaces": [
            {"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "skills": [
            {
                "id": f"agent-{agent.id}",
                "name": agent.name,
                "description": agent.description or f"调用 Agent {agent.slug}",
                "tags": ["chat"],
            }
        ],
    }


async def _resolve_agent(request: Request, session: AsyncSession, slug: str) -> Agent:
    """X-Api-Key 或 Bearer → 校验 key 属于该已发布 Agent。"""
    xkey = (request.headers.get("x-api-key") or "").strip()
    auth = (request.headers.get("authorization") or "").strip()
    plain = xkey or (auth[7:].strip() if auth.lower().startswith("bearer ") else "")
    if not plain.startswith("agk_"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少或无效的 A2A API Key")

    key = (
        await session.execute(
            select(AgentAPIKey).where(AgentAPIKey.key_hash == hash_key(plain))
        )
    ).scalar_one_or_none()
    if key is None or not key.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key 无效或已禁用")

    agent = (
        await session.execute(select(Agent).where(Agent.id == key.agent_id))
    ).scalar_one_or_none()
    if agent is None or agent.slug != slug:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该 API Key 无权访问此 Agent")
    if agent.status != AgentStatus.PUBLISHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 未发布")
    try:
        key.last_used_at = datetime.now(UTC)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    return agent


def _extract_text(params: dict[str, Any]) -> str:
    msg = params.get("message") or params
    parts = msg.get("parts") if isinstance(msg, dict) else None
    if isinstance(parts, list):
        for p in parts:
            if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip():
                return p["text"]
    for k in ("text", "query", "message"):
        v = params.get(k)
        if isinstance(v, str) and v.strip():
            return v
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "message 中没有可用文本")


def _rpc_result(rpc_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _rpc_error(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def _agent_card_response(slug: str, request: Request, session: AsyncSession) -> dict:
    agent = (await session.execute(select(Agent).where(Agent.slug == slug))).scalar_one_or_none()
    if agent is None or agent.status != AgentStatus.PUBLISHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在或未发布")
    # 反代场景：nginx 传的 Host 可能是 upstream 名（control_backend），
    # 优先用显式配置的 PUBLIC_BASE_URL（如 http://43.156.187.79:10100）。
    import os

    public = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if public:
        base = public
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        base = f"{proto}://{host}"
    return _card(agent, base)


@router.get("/a2a/{slug}/.well-known/agent-card.json")
async def agent_card_wellknown(
    slug: str, request: Request, session: AsyncSession = Depends(get_session)
):
    return await _agent_card_response(slug, request, session)


@router.get("/a2a/{slug}")
async def agent_card_alias(
    slug: str, request: Request, session: AsyncSession = Depends(get_session)
):
    return await _agent_card_response(slug, request, session)


@router.post("/a2a/{slug}")
async def a2a_rpc(
    slug: str,
    body: RpcRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    agent = await _resolve_agent(request, session, slug)
    method = METHOD_ALIASES.get(body.method)

    if method not in ("SendMessage", "SendStreamingMessage"):
        return _rpc_error(body.id, -32601, f"不支持的方法: {body.method}")

    text = _extract_text(body.params)
    context_id = body.params.get("contextId") or body.params.get("context_id")
    conv = await _get_or_create_session(session, agent, context_id)
    sid = conv.hermes_session_id

    if method == "SendMessage":
        parts: list[str] = []
        gw = gw_mod.GatewayClient()
        try:
            async with gw:
                async for frame in chat_proxy.translate_stream(
                    gw.chat_stream(sid, text, profile=agent.profile_name), thread_id=sid
                ):
                    t, _ = chat_proxy.extract_text_and_usage(frame)
                    if t:
                        parts.append(t)
        except gw_mod.GatewayError as exc:
            return _rpc_error(body.id, -32000, f"对话失败: {exc}")
        try:
            await conv_svc.touch_conversation(session, conv)
        except Exception:  # noqa: BLE001
            pass
        return _rpc_result(body.id, {
            "id": datetime.now(UTC).isoformat(),
            "contextId": sid,
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"text": "".join(parts)}]}],
        })

    # SendStreamingMessage：A2A streaming 以 SSE 返回 task 事件
    async def gen() -> AsyncIterator[bytes]:
        async def emit(obj: dict) -> bytes:
            return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode()

        yield await emit({
            "jsonrpc": "2.0", "id": body.id,
            "result": {"id": datetime.now(UTC).isoformat(), "contextId": sid,
                       "status": {"state": "working"}},
        })
        gw = gw_mod.GatewayClient()
        try:
            async with gw:
                async for frame in chat_proxy.translate_stream(
                    gw.chat_stream(sid, text, profile=agent.profile_name), thread_id=sid
                ):
                    t, _ = chat_proxy.extract_text_and_usage(frame)
                    if t:
                        yield await emit({
                            "jsonrpc": "2.0", "id": body.id,
                            "result": {"contextId": sid, "artifact": {"parts": [{"text": t}]}},
                        })
        except gw_mod.GatewayError as exc:
            yield await emit(_rpc_error(body.id, -32000, f"对话失败: {exc}"))
        try:
            await conv_svc.touch_conversation(session, conv)
        except Exception:  # noqa: BLE001
            pass
        yield await emit({
            "jsonrpc": "2.0", "id": body.id,
            "result": {"contextId": sid, "status": {"state": "completed"}},
        })

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
