"""模型模板库 + 应用到 Agent（登录即可，写操作校验归属）。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..hermes.a2a import A2AError
from ..hermes.models_cfg import apply_model, read_model
from ..models import Agent, ModelTemplate, UserRole
from ..security import CurrentUser, can_modify

logger = logging.getLogger(__name__)
_settings = get_settings()

router = APIRouter(tags=["models"])


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="custom", max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    description: str | None = None


class TemplateUpdateIn(BaseModel):
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    description: str | None = None


class TemplateOut(BaseModel):
    id: int
    name: str
    owner_id: int
    model: str
    provider: str
    base_url: str | None
    has_api_key: bool
    description: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}


def _out(t: ModelTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id,
        name=t.name,
        owner_id=t.owner_id,
        model=t.model,
        provider=t.provider,
        base_url=t.base_url,
        has_api_key=bool(t.api_key),
        description=t.description,
        created_at=t.created_at,
    )


@router.get("/api/models", response_model=list[TemplateOut])
async def list_templates(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TemplateOut]:
    stmt = select(ModelTemplate).order_by(ModelTemplate.id)
    if user.role != UserRole.ADMIN:
        stmt = stmt.where(ModelTemplate.owner_id == user.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_out(t) for t in rows]


@router.post("/api/models", response_model=TemplateOut, status_code=201)
async def create_template(
    body: TemplateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TemplateOut:
    exists = (
        await session.execute(select(ModelTemplate).where(ModelTemplate.name == body.name))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名模板已存在")

    t = ModelTemplate(
        name=body.name,
        model=body.model,
        provider=body.provider,
        base_url=body.base_url,
        api_key=body.api_key,
        description=body.description,
        owner_id=user.id,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _out(t)


@router.patch("/api/models/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: int,
    body: TemplateUpdateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TemplateOut:
    t = (
        await session.execute(select(ModelTemplate).where(ModelTemplate.id == template_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    if not can_modify(user, t.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权修改他人的模板")

    for field in ("model", "provider", "base_url", "api_key", "description"):
        v = getattr(body, field)
        if v is not None:
            setattr(t, field, v)

    await session.commit()
    await session.refresh(t)
    return _out(t)


@router.delete("/api/models/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    t = (
        await session.execute(select(ModelTemplate).where(ModelTemplate.id == template_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    if not can_modify(user, t.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权删除他人的模板")
    await session.delete(t)
    await session.commit()


@router.post("/api/agents/{agent_id}/apply-model/{template_id}")
async def apply_template(
    agent_id: int,
    template_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """把模板写入该 Agent 的 profile config.yaml。"""
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人的 Agent")

    t = (
        await session.execute(select(ModelTemplate).where(ModelTemplate.id == template_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    if not can_modify(user, t.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权使用他人的模板")

    try:
        res = apply_model(
            agent.profile_name,
            _settings.hermes_data_root,
            model=t.model,
            provider=t.provider,
            base_url=t.base_url,
            api_key=t.api_key,
        )
    except A2AError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"applied": True, **res}


@router.get("/api/agents/{agent_id}/effective-model")
async def effective_model(
    agent_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    if not can_modify(user, agent.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看他人的 Agent")
    return {
        "profile": agent.profile_name,
        "model": read_model(agent.profile_name, _settings.hermes_data_root),
    }
