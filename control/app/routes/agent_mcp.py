"""管理员：Agent 的 MCP 服务器配置。"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes import mcp as mcp_svc
from ..models import Agent
from ..security import CurrentAdmin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/agents", tags=["admin:mcp"])


class MCPServerIn(BaseModel):
    """MCP 服务器定义。

    transport 决定必填字段：
      stdio            → command（可选 args / env）
      sse / http / streamable_http → url（可选 headers）
    """

    name: str = Field(min_length=1, max_length=64)
    transport: str = Field(default="stdio")
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool = True


async def _agent_or_404(session: AsyncSession, agent_id: int) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    return agent


@router.get("/{agent_id}/mcp")
async def list_mcp(
    agent_id: int,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_or_404(session, agent_id)
    try:
        servers = await mcp_svc.list_servers(agent.profile_name)
    except mcp_svc.MCPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"profile": agent.profile_name, "servers": servers}


@router.post("/{agent_id}/mcp", status_code=201)
async def add_mcp(
    agent_id: int,
    body: MCPServerIn,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_or_404(session, agent_id)
    payload: dict[str, Any] = {
        "name": body.name,
        "transport": body.transport,
        "enabled": body.enabled,
    }
    if body.transport == "stdio":
        if not body.command:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "stdio 传输必须提供 command"
            )
        payload["command"] = body.command
        if body.args:
            payload["args"] = body.args
        if body.env:
            payload["env"] = body.env
    else:
        if not body.url:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{body.transport} 传输必须提供 url"
            )
        payload["url"] = body.url
        if body.headers:
            payload["headers"] = body.headers

    try:
        return await mcp_svc.add_server(agent.profile_name, payload)
    except mcp_svc.MCPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.delete("/{agent_id}/mcp/{name}", status_code=204)
async def delete_mcp(
    agent_id: int,
    name: str,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    agent = await _agent_or_404(session, agent_id)
    try:
        await mcp_svc.delete_server(agent.profile_name, name)
    except mcp_svc.MCPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/{agent_id}/mcp/{name}/test")
async def test_mcp(
    agent_id: int,
    name: str,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_or_404(session, agent_id)
    try:
        return await mcp_svc.test_server(agent.profile_name, name)
    except mcp_svc.MCPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.put("/{agent_id}/mcp/{name}/enabled")
async def toggle_mcp(
    agent_id: int,
    name: str,
    body: dict,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_or_404(session, agent_id)
    enabled = bool(body.get("enabled"))
    try:
        return await mcp_svc.set_enabled(agent.profile_name, name, enabled)
    except mcp_svc.MCPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/mcp-catalog/all")
async def get_catalog(_: CurrentAdmin) -> dict:
    """官方精选 MCP 目录（全局，与 profile 无关）。"""
    try:
        return {"entries": await mcp_svc.catalog()}
    except mcp_svc.MCPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
