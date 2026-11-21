"""A2A 出站端点独立表：CRUD + Agent 绑定 + 变更即同步（SPEC-v2 批次 2）。

与 MCP 完全对称的权限模型；profile 写入复用 hermes/a2a.py 的
apply_a2a_endpoints（整体替换 a2a_agents 段）。
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..hermes.a2a import A2AError, apply_a2a_endpoints, validate_endpoint
from ..hermes.auth_scheme import AUTH_TYPES
from ..models import (
    A2AOutboundEndpoint,
    Agent,
    AgentA2AEndpoint,
    AgentStatus,
    UserRole,
)
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(prefix="/api/a2a/endpoints", tags=["a2a"])
agent_router = APIRouter(prefix="/api/agents", tags=["agent-a2a"])


# ── Schemas ───────────────────────────────────────────────
class EndpointIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    url: str = ""
    target_type: str = "external"
    target_agent_id: int | None = None
    capabilities: list[str] | None = None
    timeout: int = 120
    auth_type: str = "none"
    token: str | None = None
    auth_name: str | None = None
    is_shared: bool = False
    enabled: bool = True


class EndpointUpdateIn(BaseModel):
    description: str | None = None
    url: str | None = None
    target_type: str | None = None
    target_agent_id: int | None = None
    capabilities: list[str] | None = None
    timeout: int | None = None
    auth_type: str | None = None
    token: str | None = None  # None = 不更新；"" = 清除
    auth_name: str | None = None
    is_shared: bool | None = None
    enabled: bool | None = None


class EndpointOut(BaseModel):
    id: int
    name: str
    owner_id: int
    description: str | None
    target_type: str
    target_agent_id: int | None
    url: str
    capabilities: list[str] | None
    timeout: int
    auth_type: str
    has_token: bool
    auth_name: str | None
    is_shared: bool
    enabled: bool


def _out(e: A2AOutboundEndpoint) -> EndpointOut:
    return EndpointOut(
        id=e.id,
        name=e.name,
        owner_id=e.owner_id,
        description=e.description,
        target_type=e.target_type,
        target_agent_id=e.target_agent_id,
        url=e.url,
        capabilities=e.capabilities,
        timeout=e.timeout,
        auth_type=e.auth_type,
        has_token=bool(e.token),
        auth_name=e.auth_name,
        is_shared=e.is_shared,
        enabled=e.enabled,
    )


def _endpoint_dict(e: A2AOutboundEndpoint) -> dict:
    """端点 → apply_a2a_endpoints 需要的 dict 形状。"""
    auth_headers: dict[str, str] = {}
    auth_query: dict[str, str] = {}
    url = e.url
    if e.auth_type != "none":
        from ..hermes.auth_scheme import AuthConfig, build_http_auth

        cfg = AuthConfig(auth_type=e.auth_type, token=e.token, auth_name=e.auth_name)
        http = build_http_auth(cfg)
        auth_headers = http.headers
        if http.query:
            from urllib.parse import urlencode

            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode(http.query)}"

    entry: dict = {"url": url, "token": e.token, "auth_type": e.auth_type}
    if auth_headers:
        entry["headers"] = auth_headers
    if e.capabilities:
        entry["capabilities"] = list(e.capabilities)
    if e.timeout:
        entry["timeout"] = int(e.timeout)
    return entry


def _validate_auth(body: EndpointIn | EndpointUpdateIn) -> None:
    t = body.auth_type or "none"
    if t not in AUTH_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"auth_type 只能是 {'/'.join(AUTH_TYPES)}")
    if t != "none":
        if not body.token:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"auth_type={t} 需要提供 token")
        if t in ("header", "query") and not body.auth_name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"auth_type={t} 需要提供 auth_name")


# ── 资源 CRUD ─────────────────────────────────────────────
@router.get("", response_model=list[EndpointOut])
async def list_endpoints(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[EndpointOut]:
    if user.role == UserRole.ADMIN:
        stmt = select(A2AOutboundEndpoint).order_by(A2AOutboundEndpoint.id)
    else:
        stmt = select(A2AOutboundEndpoint).where(
            or_(
                A2AOutboundEndpoint.owner_id == user.id,
                A2AOutboundEndpoint.is_shared == True,  # noqa: E712
            )
        ).order_by(A2AOutboundEndpoint.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_out(e) for e in rows]


@router.post("", response_model=EndpointOut, status_code=201)
async def create_endpoint(
    body: EndpointIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EndpointOut:
    _validate_auth(body)

    url = body.url
    target_agent = None
    if body.target_type == "internal":
        if body.target_agent_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "内部 A2A 必须选择目标 Agent")
        target_agent = (
            await session.execute(select(Agent).where(Agent.id == body.target_agent_id))
        ).scalar_one_or_none()
        if target_agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "目标 Agent 不存在")
        if target_agent.status != AgentStatus.PUBLISHED:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "目标 Agent 尚未发布，无法作为 A2A 端点")
        # 内部端点 URL 由平台生成，忽略用户填写
        url = f"/a2a/{target_agent.slug}"
    else:
        try:
            validate_endpoint(body.name, body.url)
        except A2AError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    exists = (
        await session.execute(
            select(A2AOutboundEndpoint).where(
                A2AOutboundEndpoint.owner_id == user.id, A2AOutboundEndpoint.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名端点已存在")

    e = A2AOutboundEndpoint(
        owner_id=user.id,
        name=body.name,
        description=body.description,
        target_type=body.target_type,
        target_agent_id=body.target_agent_id,
        url=url,  # 内部端点为上面自动生成的 /a2a/{slug}，外部为用户填写
        capabilities=body.capabilities,
        timeout=body.timeout,
        auth_type=body.auth_type,
        token=body.token,
        auth_name=body.auth_name,
        is_shared=body.is_shared and user.role == UserRole.ADMIN,
        enabled=body.enabled,
    )
    session.add(e)
    await session.commit()
    await session.refresh(e)
    return _out(e)


async def _ep_or_404(session: AsyncSession, endpoint_id: int, user) -> A2AOutboundEndpoint:
    e = (
        await session.execute(
            select(A2AOutboundEndpoint).where(A2AOutboundEndpoint.id == endpoint_id)
        )
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "端点不存在")
    if not can_modify(user, e.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的端点")
    return e


@router.patch("/{endpoint_id}", response_model=EndpointOut)
async def update_endpoint(
    endpoint_id: int,
    body: EndpointUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EndpointOut:
    e = await _ep_or_404(session, endpoint_id, user)

    if body.token is not None:
        e.token = body.token or None
    for field in ("description", "url", "capabilities", "timeout", "auth_type",
                  "auth_name", "enabled", "target_type", "target_agent_id"):
        v = getattr(body, field)
        if v is not None:
            setattr(e, field, v)
    # 切到内部模式时按目标 Agent 自动生成 URL
    if body.target_type == "internal" and body.target_agent_id is not None:
        target = (
            await session.execute(select(Agent).where(Agent.id == body.target_agent_id))
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "目标 Agent 不存在")
        e.url = f"/a2a/{target.slug}"
    if body.is_shared is not None:
        if user.role != UserRole.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "共享/取消共享需要管理员")
        e.is_shared = body.is_shared

    if body.url is not None and e.target_type != "internal":
        try:
            validate_endpoint(e.name, e.url)
        except A2AError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    _validate_auth(e)  # 组合校验（e 有 token/auth_name/auth_type 属性）

    await session.commit()
    await session.refresh(e)
    await _sync_bound_agents(session, e)
    return _out(e)


@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    force: bool = False,
) -> None:
    e = await _ep_or_404(session, endpoint_id, user)
    bound = (
        await session.execute(
            select(AgentA2AEndpoint).where(AgentA2AEndpoint.endpoint_id == endpoint_id)
        )
    ).scalars().all()
    if bound and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"该端点仍被 {len(bound)} 个 Agent 绑定；传 ?force=true 确认删除并解绑",
        )
    agent_ids = [b.agent_id for b in bound]
    for b in bound:
        await session.delete(b)
    await session.flush()
    for aid in agent_ids:
        await _sync_agent_by_id(session, aid)
    await session.delete(e)
    await session.commit()


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


@agent_router.get("/{agent_id}/a2a")
async def list_agent_endpoints(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_owned_or_404(session, agent_id, user)
    rows = (
        await session.execute(
            select(A2AOutboundEndpoint)
            .join(AgentA2AEndpoint, AgentA2AEndpoint.endpoint_id == A2AOutboundEndpoint.id)
            .where(AgentA2AEndpoint.agent_id == agent_id)
            .order_by(A2AOutboundEndpoint.id)
        )
    ).scalars().all()
    from ..hermes.a2a import read_a2a_section

    return {
        "agent_id": agent_id,
        "profile": agent.profile_name,
        "bound": [_out(e) for e in rows],
        "effective_in_profile": read_a2a_section(agent.profile_name, _settings.hermes_data_root),
    }


@agent_router.put("/{agent_id}/a2a")
async def set_agent_endpoints(
    agent_id: int,
    body: dict,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_owned_or_404(session, agent_id, user)
    ids = body.get("endpoint_ids")
    if not isinstance(ids, list):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "endpoint_ids 必须是数组")

    endpoints: list[A2AOutboundEndpoint] = []
    for eid in ids:
        e = (
            await session.execute(
                select(A2AOutboundEndpoint).where(A2AOutboundEndpoint.id == eid)
            )
        ).scalar_one_or_none()
        if e is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"端点 {eid} 不存在")
        if e.owner_id != user.id and not e.is_shared:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"端点 {e.name} 不可绑定（非本人且未共享）")
        endpoints.append(e)

    old = (
        await session.execute(
            select(AgentA2AEndpoint).where(AgentA2AEndpoint.agent_id == agent_id)
        )
    ).scalars().all()
    for b in old:
        await session.delete(b)
    # 先 flush 删除，避免同主键的 DELETE/INSERT 顺序不确定导致唯一约束冲突（重复保存 500）。
    if old:
        await session.flush()
    for e in endpoints:
        session.add(AgentA2AEndpoint(agent_id=agent_id, endpoint_id=e.id))
    await session.flush()

    res = await _sync_profile(session, agent)
    await session.commit()
    return {"bound": len(endpoints), "sync": res}


@agent_router.post("/{agent_id}/a2a/create-and-bind", status_code=201)
async def create_and_bind(
    agent_id: int,
    body: EndpointIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = await _agent_owned_or_404(session, agent_id, user)
    _validate_auth(body)

    exists = (
        await session.execute(
            select(A2AOutboundEndpoint).where(
                A2AOutboundEndpoint.owner_id == user.id, A2AOutboundEndpoint.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        e = exists
        created = False
    else:
        e = A2AOutboundEndpoint(
            owner_id=user.id,
            name=body.name,
            description=body.description,
            url=body.url,
            capabilities=body.capabilities,
            timeout=body.timeout,
            auth_type=body.auth_type,
            token=body.token,
            auth_name=body.auth_name,
            is_shared=body.is_shared and user.role == UserRole.ADMIN,
            enabled=body.enabled,
        )
        session.add(e)
        await session.flush()
        created = True

    dup = (
        await session.execute(
            select(AgentA2AEndpoint).where(
                AgentA2AEndpoint.agent_id == agent_id, AgentA2AEndpoint.endpoint_id == e.id
            )
        )
    ).scalar_one_or_none()
    if dup is None:
        session.add(AgentA2AEndpoint(agent_id=agent_id, endpoint_id=e.id))
        await session.flush()

    res = await _sync_profile(session, agent)
    await session.commit()
    return {"created": created, "endpoint": _out(e).model_dump(), "sync": res}


# ── 同步引擎 ──────────────────────────────────────────────
async def _bound_endpoints(session: AsyncSession, agent_id: int) -> list[A2AOutboundEndpoint]:
    return list(
        (
            await session.execute(
                select(A2AOutboundEndpoint)
                .join(AgentA2AEndpoint, AgentA2AEndpoint.endpoint_id == A2AOutboundEndpoint.id)
                .where(AgentA2AEndpoint.agent_id == agent_id)
                .order_by(A2AOutboundEndpoint.id)
            )
        ).scalars().all()
    )


def _payload(endpoints: list[A2AOutboundEndpoint]) -> list[dict]:
    return [
        {"name": e.name, **_endpoint_dict(e)}
        for e in endpoints
        if e.enabled
    ]


async def _sync_profile(session: AsyncSession, agent: Agent) -> dict:
    try:
        return apply_a2a_endpoints(
            agent.profile_name, _settings.hermes_data_root, _payload(await _bound_endpoints(session, agent.id))
        )
    except A2AError as exc:
        logger.warning("A2A 同步失败（agent=%s）：%s", agent.slug, exc)
        return {"ok": False, "error": str(exc)}


async def _sync_agent_by_id(session: AsyncSession, agent_id: int) -> None:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is not None:
        await _sync_profile(session, agent)


async def _sync_bound_agents(session: AsyncSession, e: A2AOutboundEndpoint) -> None:
    rows = (
        await session.execute(
            select(AgentA2AEndpoint).where(AgentA2AEndpoint.endpoint_id == e.id)
        )
    ).scalars().all()
    for b in rows:
        await _sync_agent_by_id(session, b.agent_id)
