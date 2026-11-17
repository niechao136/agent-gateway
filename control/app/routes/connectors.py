"""连接器 CRUD（批次 3）：Telegram / 飞书 / Slack 长连接。

- 一个连接器绑定一个 Agent；credentials 脱敏返回
- 生命周期由 app/connectors/runner.py 管理：增改删即时启停
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..connectors.base import registry
from ..database import get_session, SessionLocal
from ..models import Agent, Connector, UserRole
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

PLATFORMS = ("telegram", "feishu", "slack")

# 各平台凭证字段（校验 + 脱敏）
_CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token",),
    "feishu": ("app_id", "app_secret"),
    "slack": ("app_token", "bot_token"),
}
_SECRET_MARKERS = ("token", "secret")


class ConnectorIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    platform: str
    agent_id: int
    credentials: dict[str, str]
    enabled: bool = True


class ConnectorUpdateIn(BaseModel):
    name: str | None = None
    agent_id: int | None = None
    credentials: dict[str, str] | None = None
    enabled: bool | None = None


class ConnectorOut(BaseModel):
    id: int
    name: str
    owner_id: int
    platform: str
    agent_id: int
    agent_slug: str | None = None
    credentials: dict[str, str]  # 脱敏后
    enabled: bool


def _redact(platform: str, creds: dict) -> dict:
    out: dict[str, str] = {}
    for k, v in (creds or {}).items():
        if any(m in k.lower() for m in _SECRET_MARKERS):
            out[k] = (v[:4] + "•••") if v else ""
        else:
            out[k] = v
    return out


def _validate_platform_creds(platform: str, creds: dict) -> None:
    if platform not in PLATFORMS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"platform 只能是 {'/'.join(PLATFORMS)}",
        )
    required = _CREDENTIAL_FIELDS[platform]
    missing = [f for f in required if not (creds or {}).get(f)]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{platform} 缺少凭证字段: {', '.join(missing)}",
        )


def _out(c: Connector, agent_slug: str | None = None, runtime: dict | None = None) -> dict:
    d = {
        "id": c.id,
        "name": c.name,
        "owner_id": c.owner_id,
        "platform": c.platform,
        "agent_id": c.agent_id,
        "agent_slug": agent_slug,
        "credentials": _redact(c.platform, c.credentials),
        "enabled": c.enabled,
    }
    if runtime:
        d["runtime"] = runtime
    return d


async def _conn_or_404(session: AsyncSession, connector_id: int, user) -> Connector:
    c = (
        await session.execute(select(Connector).where(Connector.id == connector_id))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "连接器不存在")
    if not can_modify(user, c.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的连接器")
    return c


async def _agent_slug(session: AsyncSession, agent_id: int) -> str | None:
    a = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    return a.slug if a else None


@router.get("")
async def list_connectors(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    if user.role == UserRole.ADMIN:
        rows = (
            await session.execute(select(Connector).order_by(Connector.id))
        ).scalars().all()
    else:
        rows = (
            await session.execute(
                select(Connector)
                .where(Connector.owner_id == user.id)
                .order_by(Connector.id)
            )
        ).scalars().all()
    out = []
    for c in rows:
        out.append(
            _out(c, await _agent_slug(session, c.agent_id), registry.status_of(c.id))
        )
    return out


@router.post("", status_code=201)
async def create_connector(
    body: ConnectorIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _validate_platform_creds(body.platform, body.credentials)

    agent = (
        await session.execute(select(Agent).where(Agent.id == body.agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "绑定的 Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能绑定自己的 Agent")

    exists = (
        await session.execute(
            select(Connector).where(
                Connector.owner_id == user.id, Connector.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名连接器已存在")

    c = Connector(
        owner_id=user.id,
        name=body.name,
        platform=body.platform,
        agent_id=body.agent_id,
        credentials=body.credentials,
        enabled=body.enabled,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)

    if c.enabled:
        await registry.ensure_started(c)
    return _out(c, agent.slug, registry.status_of(c.id))


@router.patch("/{connector_id}")
async def update_connector(
    connector_id: int,
    body: ConnectorUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    c = await _conn_or_404(session, connector_id, user)

    if body.credentials is not None:
        _validate_platform_creds(c.platform, body.credentials)
        c.credentials = body.credentials
    if body.agent_id is not None:
        agent = (
            await session.execute(select(Agent).where(Agent.id == body.agent_id))
        ).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "绑定的 Agent 不存在")
        if not can_modify(user, agent.owner_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只能绑定自己的 Agent")
        c.agent_id = body.agent_id
    if body.name:
        c.name = body.name

    was_enabled = c.enabled
    if body.enabled is not None:
        c.enabled = body.enabled
    await session.commit()
    await session.refresh(c)

    # 变更即重启（凭证/绑定可能变了）
    await registry.reload(c, was_enabled)
    return _out(c, await _agent_slug(session, c.agent_id), registry.status_of(c.id))


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    c = await _conn_or_404(session, connector_id, user)
    await registry.stop(c.id)
    await session.delete(c)
    await session.commit()


@router.post("/{connector_id}/restart")
async def restart_connector(
    connector_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    c = await _conn_or_404(session, connector_id, user)
    await registry.restart(c)
    return {"ok": True, "status": registry.status_of(c.id)}


@router.post("/{connector_id}/test")
async def test_connector(
    connector_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """发一条测试消息到绑定 Agent，验证全链路（不真发平台消息）。"""
    c = await _conn_or_404(session, connector_id, user)
    return await registry.test(c)


@router.get("/events")
async def connector_events(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """SSE 推送连接器状态（批次 4 决策：SSE 而非轮询）。

    每 3s 全量推一次当前用户可见连接器的运行状态快照；
    客户端关闭时由 StreamingResponse 自动结束。
    """
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    uid = user.id
    is_admin = user.role == UserRole.ADMIN

    async def gen():
        while True:
            try:
                async with SessionLocal() as s:
                    stmt = select(Connector).order_by(Connector.id)
                    if not is_admin:
                        stmt = stmt.where(Connector.owner_id == uid)
                    rows = (await s.execute(stmt)).scalars().all()
                    out = []
                    for c in rows:
                        agent = (
                            await s.execute(
                                select(Agent).where(Agent.id == c.agent_id)
                            )
                        ).scalar_one_or_none()
                        out.append(
                            _out(
                                c,
                                agent.slug if agent else None,
                                registry.status_of(c.id),
                            )
                        )
                yield f"data: {json.dumps(out, ensure_ascii=False, default=str)}\n\n"
            except Exception as exc:  # noqa: BLE001
                logger.warning("SSE 推送失败: %s", exc)
                yield f"event: error\ndata: {{\"detail\": \"推送失败\"}}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
