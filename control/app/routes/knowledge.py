"""知识库（RAGFlow）：连接 CRUD + 数据集列表 + 连通性测试 + Agent 绑定与检索 Skill 下发。

权限：登录可用；写操作仅 owner/admin；共享知识库他人只读可绑。
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..hermes.rag_sync import (
    RagSyncError,
    apply_knowledge_skill,
    remove_knowledge_skill,
)
from ..models import (
    Agent,
    AgentKnowledgeBase,
    KnowledgeBase,
    UserRole,
)
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
agent_router = APIRouter(prefix="/api/agents", tags=["agent-knowledge"])


# ── Schemas ───────────────────────────────────────────────
class KbIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=512)
    dataset_id: str | None = None
    dataset_name: str | None = None
    is_shared: bool = False
    enabled: bool = True


class KbUpdateIn(BaseModel):
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # None=不更新
    dataset_id: str | None = None
    dataset_name: str | None = None
    is_shared: bool | None = None
    enabled: bool | None = None


class KbOut(BaseModel):
    id: int
    name: str
    owner_id: int
    source: str
    description: str | None
    base_url: str
    dataset_id: str | None
    dataset_name: str | None
    is_shared: bool
    enabled: bool

    model_config = {"from_attributes": True}


class KbTestIn(BaseModel):
    base_url: str
    api_key: str


class DatasetOut(BaseModel):
    id: str
    name: str


def _out(k: KnowledgeBase) -> KbOut:
    return KbOut(
        id=k.id,
        name=k.name,
        owner_id=k.owner_id,
        source=k.source,
        description=k.description,
        base_url=k.base_url,
        dataset_id=k.dataset_id,
        dataset_name=k.dataset_name,
        is_shared=k.is_shared,
        enabled=k.enabled,
    )


def _mask(key: str) -> str:
    return key[:4] + "•••" if len(key) > 4 else "•••"


async def _ragflow_datasets(base_url: str, api_key: str) -> list[DatasetOut]:
    """调 RAGFlow GET /api/v1/datasets 拉数据集列表。"""
    url = base_url.rstrip("/") + "/api/v1/datasets"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    if r.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RAGFlow 返回 {r.status_code}: {r.text[:200]}")
    data = r.json()
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "RAGFlow 数据集响应格式异常")
    return [DatasetOut(id=str(x.get("id", "")), name=x.get("name") or "") for x in rows if x.get("id")]


# ── 连接 CRUD ─────────────────────────────────────────────
@router.get("", response_model=list[KbOut])
async def list_kb(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(KnowledgeBase).where(
                or_(KnowledgeBase.owner_id == user.id, KnowledgeBase.is_shared.is_(True))
            )
        )
    ).scalars().all()
    return [_out(k) for k in rows]


@router.post("", response_model=KbOut, status_code=201)
async def create_kb(
    body: KbIn,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    exists = (
        await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.owner_id == user.id, KnowledgeBase.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名知识库已存在")
    k = KnowledgeBase(
        owner_id=user.id,
        source="ragflow",
        **body.model_dump(),
        is_shared=body.is_shared if user.role == UserRole.ADMIN else False,
    )
    session.add(k)
    await session.flush()
    return _out(k)


@router.get("/list-datasets", response_model=list[DatasetOut])
async def list_datasets(
    base_url: str,
    api_key: str,
    _: CurrentUser,
):
    """用临时凭据拉 RAGFlow 数据集列表（新建表单用）。"""
    return await _ragflow_datasets(base_url, api_key)


@router.post("/test")
async def test_kb(
    body: KbTestIn,
    _: CurrentUser,
):
    datasets = await _ragflow_datasets(body.base_url, body.api_key)
    return {"ok": True, "message": f"连接成功，共 {len(datasets)} 个知识库"}


@router.patch("/{kb_id}", response_model=KbOut)
async def update_kb(
    kb_id: int,
    body: KbUpdateIn,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    k = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
    if not can_modify(user, k.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权修改他人的知识库")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "is_shared" and user.role != UserRole.ADMIN:
            continue  # 普通用户不能共享
        if value is not None:
            setattr(k, field, value)
    await session.flush()
    # 配置变更 → 重新同步所有绑定 Agent 的检索 skill
    await _sync_bound_agents(session, k)
    return _out(k)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: int,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    force: bool = False,
):
    k = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
    if not can_modify(user, k.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权删除他人的知识库")
    bound = (
        await session.execute(
            select(AgentKnowledgeBase).where(AgentKnowledgeBase.kb_id == kb_id)
        )
    ).scalars().all()
    if bound and not force:
        raise HTTPException(status.HTTP_409_CONFLICT, f"仍有 {len(bound)} 个 Agent 绑定，请加 ?force=true")
    for b in bound:
        agent = (await session.execute(select(Agent).where(Agent.id == b.agent_id))).scalar_one_or_none()
        if agent:
            _remove_skill_best_effort(agent.profile_name)
        await session.delete(b)
    await session.flush()
    await session.delete(k)


# ── Agent 绑定 ────────────────────────────────────────────
class BindIn(BaseModel):
    kb_ids: list[int] = []


@agent_router.get("/{agent_id}/knowledge", response_model=list[KbOut])
async def list_agent_kb(
    agent_id: int,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的 Agent")
    rows = (
        await session.execute(
            select(KnowledgeBase)
            .join(AgentKnowledgeBase, AgentKnowledgeBase.kb_id == KnowledgeBase.id)
            .where(AgentKnowledgeBase.agent_id == agent_id)
        )
    ).scalars().all()
    return [_out(k) for k in rows]


@agent_router.put("/{agent_id}/knowledge")
async def set_agent_kb(
    agent_id: int,
    body: BindIn,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权修改他人的 Agent")

    old = (
        await session.execute(
            select(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent_id)
        )
    ).scalars().all()
    for b in old:
        await session.delete(b)
    if old:
        await session.flush()

    kbs: list[KnowledgeBase] = []
    if body.kb_ids:
        kbs = (
            await session.execute(
                select(KnowledgeBase).where(KnowledgeBase.id.in_(body.kb_ids))
            )
        ).scalars().all()
        for k in kbs:
            session.add(AgentKnowledgeBase(agent_id=agent_id, kb_id=k.id))
        await session.flush()

    sync = _sync_skill(agent.profile_name, kbs)
    await session.commit()
    return {"bound": len(kbs), "sync": sync}


# ── 同步辅助 ──────────────────────────────────────────────
def _sync_skill(profile: str, kbs: list[KnowledgeBase]) -> dict:
    if not kbs:
        return _remove_skill_best_effort(profile)
    first = next((k for k in kbs if k.enabled), kbs[0])
    try:
        return apply_knowledge_skill(
            profile,
            _settings.hermes_data_root,
            base_url=first.base_url,
            api_key=first.api_key,
            dataset_ids=[k.dataset_id for k in kbs if k.dataset_id],
        )
    except RagSyncError as exc:
        logger.warning("知识库 skill 下发失败(profile=%s): %s", profile, exc)
        return {"skill": None, "error": str(exc)}


def _remove_skill_best_effort(profile: str) -> dict:
    try:
        return remove_knowledge_skill(profile, _settings.hermes_data_root)
    except Exception as exc:  # noqa: BLE001 - 清理失败不阻断解绑
        logger.warning("知识库 skill 清理失败(profile=%s): %s", profile, exc)
        return {"skill": None, "error": str(exc)}


async def _sync_bound_agents(session: AsyncSession, k: KnowledgeBase) -> None:
    aids = (
        await session.execute(
            select(AgentKnowledgeBase.agent_id).where(AgentKnowledgeBase.kb_id == k.id)
        )
    ).scalars().all()
    for aid in aids:
        agent = (await session.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
        if agent:
            kbs = (
                await session.execute(
                    select(KnowledgeBase)
                    .join(AgentKnowledgeBase, AgentKnowledgeBase.kb_id == KnowledgeBase.id)
                    .where(AgentKnowledgeBase.agent_id == aid)
                )
            ).scalars().all()
            _sync_skill(agent.profile_name, list(kbs))
