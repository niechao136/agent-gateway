"""知识库（RAGFlow）：库 CRUD + Agent 绑定与检索工具下发。"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..hermes.rag_sync import RagSyncError, apply_knowledge_tool, remove_knowledge_tool
from ..models import Agent, AgentKnowledgeBase, KnowledgeBase, RagflowSite, UserRole
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
agent_router = APIRouter(prefix="/api/agents", tags=["agent-knowledge"])


class KbIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    site_id: int
    description: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    is_shared: bool = False
    enabled: bool = True


class KbUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    is_shared: bool | None = None
    enabled: bool | None = None


class KbOut(BaseModel):
    id: int
    name: str
    owner_id: int
    site_id: int
    site_name: str
    source: str
    description: str | None
    dataset_id: str | None
    dataset_name: str | None
    has_api_key: bool
    is_shared: bool
    enabled: bool


class KbTestIn(BaseModel):
    base_url: str
    api_key: str


class DatasetOut(BaseModel):
    id: str
    name: str


def _out(k: KnowledgeBase, site: RagflowSite) -> KbOut:
    return KbOut(
        id=k.id, name=k.name, owner_id=k.owner_id, site_id=site.id, site_name=site.name,
        source=k.source, description=k.description, dataset_id=k.dataset_id,
        dataset_name=k.dataset_name, has_api_key=bool(site.api_key),
        is_shared=k.is_shared, enabled=k.enabled,
    )


async def _site_map(session: AsyncSession) -> dict[int, RagflowSite]:
    return {s.id: s for s in (await session.execute(select(RagflowSite))).scalars().all()}


async def _ragflow_datasets(base_url: str, api_key: str) -> list[DatasetOut]:
    url = base_url.rstrip("/") + "/api/v1/datasets"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    if r.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RAGFlow 返回 {r.status_code}: {r.text[:200]}")
    data = r.json()
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RAGFlow 业务错误 {data.get('code')}: {data.get('message') or '未知错误'}")
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "RAGFlow 数据集响应格式异常")
    return [DatasetOut(id=str(x.get("id", "")), name=x.get("name") or "") for x in rows if x.get("id")]


@router.get("", response_model=list[KbOut])
async def list_kb(user: CurrentUser, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(KnowledgeBase).where(or_(KnowledgeBase.owner_id == user.id, KnowledgeBase.is_shared.is_(True)))
    )).scalars().all()
    sites = await _site_map(session)
    return [_out(k, sites[k.site_id]) for k in rows if k.site_id in sites]


@router.post("", response_model=KbOut, status_code=201)
async def create_kb(body: KbIn, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    site = (await session.execute(select(RagflowSite).where(RagflowSite.id == body.site_id))).scalar_one_or_none()
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "站点不存在")
    if not can_modify(user, site.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权在该站点下建库")
    exists = (await session.execute(
        select(KnowledgeBase).where(KnowledgeBase.site_id == body.site_id, KnowledgeBase.name == body.name)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "该站点下同名知识库已存在")
    k = KnowledgeBase(
        site_id=site.id, owner_id=site.owner_id, source="ragflow", name=body.name,
        description=body.description, dataset_id=body.dataset_id, dataset_name=body.dataset_name,
        is_shared=bool(body.is_shared) and user.role == UserRole.ADMIN, enabled=body.enabled,
    )
    session.add(k)
    await session.commit()
    await session.refresh(k)
    return _out(k, site)


@router.get("/list-datasets", response_model=list[DatasetOut])
async def list_datasets(base_url: str, api_key: str, _: CurrentUser):
    return await _ragflow_datasets(base_url, api_key)


@router.post("/test")
async def test_kb(body: KbTestIn, _: CurrentUser):
    datasets = await _ragflow_datasets(body.base_url, body.api_key)
    return {"ok": True, "message": f"连接成功，共 {len(datasets)} 个知识库"}


@router.post("/{kb_id}/test")
async def test_kb_saved(kb_id: int, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    k = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
    if not can_modify(user, k.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的知识库")
    site = (await session.execute(select(RagflowSite).where(RagflowSite.id == k.site_id))).scalar_one_or_none()
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "所属站点不存在")
    datasets = await _ragflow_datasets(site.base_url, site.api_key)
    return {"ok": True, "message": f"连接成功，共 {len(datasets)} 个知识库"}


@router.patch("/{kb_id}", response_model=KbOut)
async def update_kb(kb_id: int, body: KbUpdateIn, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    k = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
    if not can_modify(user, k.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权修改他人的知识库")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "is_shared" and user.role != UserRole.ADMIN:
            continue
        if value is not None:
            setattr(k, field, value)
    await session.flush()
    await _sync_bound_agents(session, k)
    site = (await session.execute(select(RagflowSite).where(RagflowSite.id == k.site_id))).scalar_one_or_none()
    await session.commit()
    return _out(k, site)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: int, user: CurrentUser, force: bool = False, session: AsyncSession = Depends(get_session)):
    k = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
    if not can_modify(user, k.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权删除他人的知识库")
    bound = (await session.execute(select(AgentKnowledgeBase).where(AgentKnowledgeBase.kb_id == kb_id))).scalars().all()
    if bound and not force:
        raise HTTPException(status.HTTP_409_CONFLICT, f"仍有 {len(bound)} 个 Agent 绑定，请加 ?force=true")
    for b in bound:
        agent = (await session.execute(select(Agent).where(Agent.id == b.agent_id))).scalar_one_or_none()
        if agent:
            _remove_tool_best_effort(agent.profile_name)
        await session.delete(b)
    await session.flush()
    await session.delete(k)


class BindIn(BaseModel):
    kb_ids: list[int] = []


@agent_router.get("/{agent_id}/knowledge", response_model=list[KbOut])
async def list_agent_kb(agent_id: int, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的 Agent")
    rows = (await session.execute(
        select(KnowledgeBase).join(AgentKnowledgeBase, AgentKnowledgeBase.kb_id == KnowledgeBase.id)
        .where(AgentKnowledgeBase.agent_id == agent_id)
    )).scalars().all()
    sites = await _site_map(session)
    return [_out(k, sites[k.site_id]) for k in rows if k.site_id in sites]


@agent_router.put("/{agent_id}/knowledge")
async def set_agent_kb(agent_id: int, body: BindIn, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权修改他人的 Agent")
    old = (await session.execute(select(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent_id))).scalars().all()
    for b in old:
        await session.delete(b)
    if old:
        await session.flush()
    kbs: list[KnowledgeBase] = []
    if body.kb_ids:
        kbs = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(body.kb_ids)))).scalars().all()
        for k in kbs:
            session.add(AgentKnowledgeBase(agent_id=agent_id, kb_id=k.id))
        await session.flush()
    sync = _sync_tool(agent.profile_name, kbs, await _site_map(session))
    await session.commit()
    return {"bound": len(kbs), "sync": sync}


def _sync_tool(profile: str, kbs: list[KnowledgeBase], sites: dict[int, RagflowSite]) -> dict:
    """写入 RAGFlow 检索工具配置（多站点 base64 下发）。"""
    if not kbs:
        return _remove_tool_best_effort(profile)
    try:
        site_entries = {}
        dataset_sites = {}
        for k in kbs:
            if not k.enabled or k.site_id not in sites:
                continue
            s = sites[k.site_id]
            if not s.enabled or not k.dataset_id:
                continue
            site_entries[str(s.id)] = {"base_url": s.base_url, "api_key": s.api_key}
            dataset_sites[k.dataset_id] = str(s.id)
        return apply_knowledge_tool(profile, sites=site_entries, dataset_sites=dataset_sites)
    except RagSyncError as exc:
        logger.warning("知识库工具下发失败(profile=%s): %s", profile, exc)
        return {"tool": None, "error": str(exc)}


def _remove_tool_best_effort(profile: str) -> dict:
    try:
        return remove_knowledge_tool(profile)
    except Exception as exc:  # noqa: BLE001
        logger.warning("知识库工具清理失败(profile=%s): %s", profile, exc)
        return {"tool": None, "error": str(exc)}


async def _sync_bound_agents(session: AsyncSession, k: KnowledgeBase) -> None:
    aids = (await session.execute(select(AgentKnowledgeBase.agent_id).where(AgentKnowledgeBase.kb_id == k.id))).scalars().all()
    sites = await _site_map(session)
    for aid in aids:
        agent = (await session.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
        if agent:
            kbs = (await session.execute(
                select(KnowledgeBase).join(AgentKnowledgeBase, AgentKnowledgeBase.kb_id == KnowledgeBase.id)
                .where(AgentKnowledgeBase.agent_id == aid)
            )).scalars().all()
            _sync_tool(agent.profile_name, list(kbs), sites)
