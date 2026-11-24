"""RAGFlow 站点管理路由（独立前缀 /api/knowledge/sites，先于 knowledge.router 注册）。"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..models import AgentKnowledgeBase, KnowledgeBase, RagflowSite, UserRole
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(prefix="/api/knowledge/sites", tags=["ragflow-sites"])


def _mask(key: str) -> str:
    return (key[:4] + "•••") if key else ""


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=512)
    is_shared: bool = False
    enabled: bool = True


class SiteUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_shared: bool | None = None
    enabled: bool | None = None


class SiteOut(BaseModel):
    id: int
    name: str
    base_url: str
    has_api_key: bool
    is_shared: bool
    enabled: bool


class SiteDetailOut(SiteOut):
    api_key_masked: str = ""


def _out(s: RagflowSite, detail: bool = False) -> dict:
    d = {
        "id": s.id, "name": s.name, "base_url": s.base_url,
        "has_api_key": bool(s.api_key), "is_shared": s.is_shared, "enabled": s.enabled,
    }
    if detail:
        d["api_key_masked"] = _mask(s.api_key)
    return d


async def _ragflow_datasets(base_url: str, api_key: str) -> list[dict]:
    url = base_url.rstrip("/") + "/api/v1/datasets"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RAGFlow 连接失败: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RAGFlow HTTP {r.status_code}")
    data = r.json()
    if data.get("code") != 0:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RAGFlow 业务错误 {data.get('code')}: {data.get('message')}")
    return [{"id": x["id"], "name": x.get("name") or x["id"]} for x in (data.get("data") or [])]


async def _site_or_404(session: AsyncSession, site_id: int, user) -> RagflowSite:
    s = (await session.execute(select(RagflowSite).where(RagflowSite.id == site_id))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "站点不存在")
    if not can_modify(user, s.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的站点")
    return s


@router.get("", response_model=list[SiteOut])
async def list_sites(user: CurrentUser, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(RagflowSite).where(or_(RagflowSite.owner_id == user.id, RagflowSite.is_shared))
    )).scalars().all()
    return [_out(s) for s in rows]


@router.post("", response_model=SiteOut, status_code=201)
async def create_site(body: SiteIn, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    exists = (await session.execute(
        select(RagflowSite).where(RagflowSite.owner_id == user.id, RagflowSite.name == body.name)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名站点已存在")
    s = RagflowSite(
        owner_id=user.id, name=body.name, base_url=body.base_url, api_key=body.api_key,
        is_shared=body.is_shared if user.role == UserRole.ADMIN else False,
        enabled=body.enabled,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return _out(s)


@router.get("/{site_id}", response_model=SiteDetailOut)
async def get_site(site_id: int, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return _out(await _site_or_404(session, site_id, user), detail=True)


@router.patch("/{site_id}", response_model=SiteOut)
async def update_site(site_id: int, body: SiteUpdate, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    s = await _site_or_404(session, site_id, user)
    for key in ("name", "base_url", "api_key", "is_shared", "enabled"):
        value = getattr(body, key)
        if value is not None:
            setattr(s, key, value)
    await session.commit()
    await session.refresh(s)
    return _out(s)


async def _sync_agents_of_site(session: AsyncSession, site: RagflowSite) -> list[str]:
    """占位：Task 4 实现真正下发。此处仅返回空错误列表。"""
    return []


@router.delete("/{site_id}", status_code=200)
async def delete_site(
    site_id: int,
    user: CurrentUser,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    s = await _site_or_404(session, site_id, user)
    kbs = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.site_id == site_id))).scalars().all()
    if kbs and not force:
        raise HTTPException(status.HTTP_409_CONFLICT, "站点下有知识库，需 ?force=true 强制删除")
    if kbs:
        ids = [k.id for k in kbs]
        binds = (await session.execute(
            select(AgentKnowledgeBase).where(AgentKnowledgeBase.kb_id.in_(ids))
        )).scalars().all()
        for b in binds:
            await session.delete(b)
        for k in kbs:
            await session.delete(k)
    await session.delete(s)
    await session.commit()
    sync_errors = await _sync_agents_of_site(session, s)
    return {"deleted": True, "sync_errors": sync_errors}


@router.post("/{site_id}/test")
async def test_site(site_id: int, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    s = await _site_or_404(session, site_id, user)
    datasets = await _ragflow_datasets(s.base_url, s.api_key)
    return {"ok": True, "message": f"连接成功，共 {len(datasets)} 个知识库"}


@router.get("/{site_id}/datasets")
async def site_datasets(site_id: int, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    s = await _site_or_404(session, site_id, user)
    return await _ragflow_datasets(s.base_url, s.api_key)
