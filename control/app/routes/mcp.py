"""MCP 独立表：资源 CRUD + Agent 绑定 + 变更即同步（SPEC-v2 批次 2）。

权限：
- /api/mcp          登录即可；写操作仅 owner/admin（共享资源他人只读）
- /api/agents/{id}/mcp  写操作需 Agent 归属
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_session
from ..hermes.auth_scheme import AUTH_TYPES
from ..hermes.mcp_sync import MCPSyncError, apply_mcp_servers, read_mcp_section
from ..models import Agent, AgentMCPServer, MCPServer, UserRole
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
agent_router = APIRouter(prefix="/api/agents", tags=["agent-mcp"])

TRANSPORTS = ("stdio", "sse", "http", "streamable_http")


# ── Schemas ───────────────────────────────────────────────
class MCPServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    transport: str = "stdio"
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    auth_type: str = "none"
    token: str | None = None
    auth_name: str | None = None
    is_shared: bool = False
    enabled: bool = True


class MCPServerUpdateIn(BaseModel):
    description: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    auth_type: str | None = None
    token: str | None = None  # None = 不更新（不回明文语义）
    auth_name: str | None = None
    is_shared: bool | None = None
    enabled: bool | None = None


class MCPServerOut(BaseModel):
    id: int
    name: str
    owner_id: int
    description: str | None
    transport: str
    command: str | None
    args: list[str] | None
    env: dict[str, str] | None
    url: str | None
    auth_type: str
    has_token: bool
    auth_name: str | None
    is_shared: bool
    enabled: bool


def _out(s: MCPServer) -> MCPServerOut:
    return MCPServerOut(
        id=s.id,
        name=s.name,
        owner_id=s.owner_id,
        description=s.description,
        transport=s.transport,
        command=s.command,
        args=s.args,
        env=s.env,
        url=s.url,
        auth_type=s.auth_type,
        has_token=bool(s.token),
        auth_name=s.auth_name,
        is_shared=s.is_shared,
        enabled=s.enabled,
    )


def _validate(body: MCPServerIn | MCPServerUpdateIn) -> None:
    transport = body.transport or "stdio"
    auth_type = body.auth_type or "none"
    if transport not in TRANSPORTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"transport 只能是 {'/'.join(TRANSPORTS)}")
    if auth_type not in AUTH_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"auth_type 只能是 {'/'.join(AUTH_TYPES)}")
    if auth_type != "none" and not body.token:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"auth_type={auth_type} 需要提供 token")
    if auth_type in ("header", "query") and not body.auth_name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"auth_type={auth_type} 需要提供 auth_name")
    if transport == "stdio" and not body.command:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "stdio 必须提供 command")
    if transport != "stdio" and not body.url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{transport} 必须提供 url")


# ── 资源 CRUD ─────────────────────────────────────────────
@router.get("", response_model=list[MCPServerOut])
async def list_servers(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MCPServerOut]:
    """我的 + 共享的。admin 额外看到全部（含未共享的他人资源，便于管理）。"""
    if user.role == UserRole.ADMIN:
        stmt = select(MCPServer).order_by(MCPServer.id)
    else:
        stmt = select(MCPServer).where(
            or_(MCPServer.owner_id == user.id, MCPServer.is_shared == True)  # noqa: E712
        ).order_by(MCPServer.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_out(s) for s in rows]


@router.post("", response_model=MCPServerOut, status_code=201)
async def create_server(
    body: MCPServerIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MCPServerOut:
    _validate(body)
    exists = (
        await session.execute(
            select(MCPServer).where(MCPServer.owner_id == user.id, MCPServer.name == body.name)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名 MCP 服务器已存在")

    # 共享是管理员能力（普通用户误共享影响面大）
    is_shared = body.is_shared and user.role == UserRole.ADMIN

    s = MCPServer(
        owner_id=user.id,
        name=body.name,
        description=body.description,
        transport=body.transport,
        command=body.command,
        args=body.args,
        env=body.env,
        url=body.url,
        auth_type=body.auth_type,
        token=body.token,
        auth_name=body.auth_name,
        is_shared=is_shared,
        enabled=body.enabled,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return _out(s)


async def _server_or_404(session: AsyncSession, server_id: int, user) -> MCPServer:
    s = (
        await session.execute(select(MCPServer).where(MCPServer.id == server_id))
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP 服务器不存在")
    if not can_modify(user, s.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 MCP 服务器")
    return s


@router.patch("/{server_id}", response_model=MCPServerOut)
async def update_server(
    server_id: int,
    body: MCPServerUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MCPServerOut:
    s = await _server_or_404(session, server_id, user)

    # token 语义：显式传 "" 清除；不传（None）保持不变
    if body.token is not None:
        s.token = body.token or None

    for field in ("description", "transport", "command", "args", "env", "url",
                  "auth_type", "auth_name", "enabled"):
        v = getattr(body, field)
        if v is not None:
            setattr(s, field, v)
    if body.is_shared is not None:
        if user.role != UserRole.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "共享/取消共享需要管理员")
        s.is_shared = body.is_shared

    # 校验组合合法性
    class _Chk:  # 复用 _validate 的最小形状
        transport = s.transport
        auth_type = s.auth_type
        token = s.token
        auth_name = s.auth_name
        command = s.command
        url = s.url

    if s.transport not in TRANSPORTS or s.auth_type not in AUTH_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "transport/auth_type 非法")
    if s.transport == "stdio" and not s.command:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "stdio 必须提供 command")
    if s.transport != "stdio" and not s.url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{s.transport} 必须提供 url")

    await session.commit()
    await session.refresh(s)

    # 变更即同步：所有绑定该资源的 Agent profile 重写
    await _sync_bound_agents(session, s)
    return _out(s)


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    force: bool = False,
) -> None:
    s = await _server_or_404(session, server_id, user)

    bound = (
        await session.execute(
            select(AgentMCPServer).where(AgentMCPServer.mcp_server_id == server_id)
        )
    ).scalars().all()
    if bound and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"该服务器仍被 {len(bound)} 个 Agent 绑定；传 ?force=true 确认删除并解绑",
        )

    # 先解绑并同步受影响 Agent，再删资源
    agent_ids = [b.agent_id for b in bound]
    for b in bound:
        await session.delete(b)
    await session.flush()
    for aid in agent_ids:
        await _sync_agent_by_id(session, aid)

    await session.delete(s)
    await session.commit()


@router.post("/{server_id}/test")
async def test_server(
    server_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """连通性测试：dashboard 有对应端点则转发；否则本地校验 + 实际连接探测。

    注意：多数 hermes 版本没有 /api/mcp/{name}/test 端点，且可能返回 405/500 而非
    404。因此任何 dashboard 探测异常都降级为本地校验，绝不让"测试"因 dashboard
    本身的问题而误报失败（修复：新增 MCP 后测试失败）。
    """
    s = await _server_or_404(session, server_id, user)
    from ..hermes.client import DashboardClient

    # 1) 先构建配置校验（字段名/auth_type 是否合法）
    try:
        build_entry_check(s)
    except MCPSyncError as e:
        return {"ok": False, "source": "static-check", "error": str(e)}

    # 2) dashboard 端点探测（best-effort，成功才用其结果）
    try:
        async with DashboardClient() as client:
            res = await client.try_endpoint("POST", f"/api/mcp/{s.name}/test")
            if isinstance(res, dict) and res.get("ok"):
                return {"ok": True, "source": "dashboard", **res}
    except Exception:  # noqa: BLE001 - dashboard 不可用/无端点都属正常
        pass

    # 3) 本地实际连接探测
    ok, detail = await _probe_connection(s)
    return {"ok": ok, "source": "local-probe", "detail": detail}


async def _probe_connection(s: MCPServer) -> tuple[bool, str]:
    """按 transport 做轻量连通性探测。

    - http 系：TCP 连接 host:port（不发业务请求，避免触发副作用）
    - stdio：确认 command 可执行（shutil.which）
    """
    import asyncio
    import shutil
    from urllib.parse import urlparse

    if s.transport == "stdio":
        cmd = (s.command or "").split()[0] if s.command else ""
        if not cmd:
            return False, "未配置启动命令"
        if shutil.which(cmd):
            return True, f"可执行文件已找到: {cmd}"
        return False, f"命令不在 PATH 中: {cmd}"

    url = s.url or ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"URL 协议不支持: {parsed.scheme or '(空)'}"
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False, "URL 缺少主机名"
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
        writer.close()
        await writer.wait_closed()
        return True, f"可连接 {host}:{port}"
    except Exception as exc:  # noqa: BLE001
        return False, f"无法连接 {host}:{port}: {exc}"


def build_entry_check(s: MCPServer) -> None:
    from ..hermes.mcp_sync import build_mcp_entry

    build_mcp_entry(s)


# ── Agent 绑定 ────────────────────────────────────────────
async def _agent_owned_or_404(session: AsyncSession, agent_id: int, user) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")
    return agent


@agent_router.get("/{agent_id}/mcp")
async def list_agent_mcp(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_owned_or_404(session, agent_id, user)
    rows = (
        await session.execute(
            select(MCPServer)
            .join(AgentMCPServer, AgentMCPServer.mcp_server_id == MCPServer.id)
            .where(AgentMCPServer.agent_id == agent_id)
            .order_by(MCPServer.id)
        )
    ).scalars().all()
    effective = await session.execute(
        select(MCPServer)
        .join(AgentMCPServer, AgentMCPServer.mcp_server_id == MCPServer.id)
        .where(AgentMCPServer.agent_id == agent_id, MCPServer.enabled == True)  # noqa: E712
    )
    return {
        "agent_id": agent_id,
        "profile": agent.profile_name,
        "bound": [_out(s) for s in rows],
        "effective_in_profile": read_mcp_section(agent.profile_name, _settings.hermes_data_root),
    }


@agent_router.put("/{agent_id}/mcp")
async def set_agent_mcp(
    agent_id: int,
    body: dict,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """整体替换绑定列表：body = {"mcp_server_ids": [..]}。

    只允许绑定：自己的 或 共享的。
    """
    agent = await _agent_owned_or_404(session, agent_id, user)
    ids = body.get("mcp_server_ids")
    if not isinstance(ids, list):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mcp_server_ids 必须是数组")

    servers: list[MCPServer] = []
    for sid in ids:
        s = (
            await session.execute(select(MCPServer).where(MCPServer.id == sid))
        ).scalar_one_or_none()
        if s is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"MCP 服务器 {sid} 不存在")
        if s.owner_id != user.id and not s.is_shared:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"MCP 服务器 {s.name} 不可绑定（非本人且未共享）")
        servers.append(s)

    # 替换绑定
    old = (
        await session.execute(
            select(AgentMCPServer).where(AgentMCPServer.agent_id == agent_id)
        )
    ).scalars().all()
    for b in old:
        await session.delete(b)
    for s in servers:
        session.add(AgentMCPServer(agent_id=agent_id, mcp_server_id=s.id))
    await session.flush()

    # 变更即同步
    res = await _sync_profile(session, agent)
    await session.commit()
    return {"bound": len(servers), "sync": res}


@agent_router.post("/{agent_id}/mcp/create-and-bind", status_code=201)
async def create_and_bind(
    agent_id: int,
    body: MCPServerIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """「+ 新建并绑定」：一步创建资源并绑定到该 Agent。"""
    agent = await _agent_owned_or_404(session, agent_id, user)
    _validate(body)

    exists = (
        await session.execute(
            select(MCPServer).where(MCPServer.owner_id == user.id, MCPServer.name == body.name)
        )
    ).scalar_one_or_none()
    if exists is not None:
        # 同名已存在：直接绑定已存在的（前端语义为"选中并绑定"）
        s = exists
        created = False
    else:
        is_shared = body.is_shared and user.role == UserRole.ADMIN
        s = MCPServer(
            owner_id=user.id,
            name=body.name,
            description=body.description,
            transport=body.transport,
            command=body.command,
            args=body.args,
            env=body.env,
            url=body.url,
            auth_type=body.auth_type,
            token=body.token,
            auth_name=body.auth_name,
            is_shared=is_shared,
            enabled=body.enabled,
        )
        session.add(s)
        await session.flush()
        created = True

    dup = (
        await session.execute(
            select(AgentMCPServer).where(
                AgentMCPServer.agent_id == agent_id, AgentMCPServer.mcp_server_id == s.id
            )
        )
    ).scalar_one_or_none()
    if dup is None:
        session.add(AgentMCPServer(agent_id=agent_id, mcp_server_id=s.id))
        await session.flush()

    res = await _sync_profile(session, agent)
    await session.commit()
    return {"created": created, "server": _out(s).model_dump(), "sync": res}


# ── 同步引擎（变更即同步）─────────────────────────────────
async def _bound_servers(session: AsyncSession, agent_id: int) -> list[MCPServer]:
    return list(
        (
            await session.execute(
                select(MCPServer)
                .join(AgentMCPServer, AgentMCPServer.mcp_server_id == MCPServer.id)
                .where(AgentMCPServer.agent_id == agent_id)
                .order_by(MCPServer.id)
            )
        ).scalars().all()
    )


async def _sync_profile(session: AsyncSession, agent: Agent) -> dict:
    """把该 Agent 当前绑定写入 profile（enabled=False 的资源视为已解绑）。"""
    servers = [
        s for s in await _bound_servers(session, agent.id) if s.enabled
    ]
    try:
        return apply_mcp_servers(agent.profile_name, _settings.hermes_data_root, servers)
    except MCPSyncError as exc:
        logger.warning("MCP 同步失败（agent=%s）：%s", agent.slug, exc)
        return {"ok": False, "error": str(exc)}


async def _sync_agent_by_id(session: AsyncSession, agent_id: int) -> None:
    from ..models import Agent as AgentM

    agent = (
        await session.execute(select(AgentM).where(AgentM.id == agent_id))
    ).scalar_one_or_none()
    if agent is not None:
        await _sync_profile(session, agent)


async def _sync_bound_agents(session: AsyncSession, server: MCPServer) -> None:
    rows = (
        await session.execute(
            select(AgentMCPServer).where(AgentMCPServer.mcp_server_id == server.id)
        )
    ).scalars().all()
    for b in rows:
        await _sync_agent_by_id(session, b.agent_id)
