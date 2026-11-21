"""定时自动化任务：CRUD + 手动运行 + 执行历史。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import ScheduledTask, TaskRun, UserRole
from ..security import CurrentUser, can_modify
from ..task_runner import DELIVERY_CHOICES, run_due_tasks, run_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    schedule_kind: str = "interval"  # interval | cron
    every_seconds: int = Field(default=3600, ge=10)
    cron_expr: str | None = None
    action_type: str = "agent_message"  # agent_message | a2a_call
    target_agent_id: int | None = None
    a2a_endpoint_id: int | None = None
    payload: str = ""
    delivery: str = "log"  # 逗号分隔，多选
    webhook_url: str | None = None
    connector_id: int | None = None
    knowledge_id: int | None = None


class TaskOut(BaseModel):
    id: int
    name: str
    owner_id: int
    enabled: bool
    schedule_kind: str
    every_seconds: int
    cron_expr: str | None
    action_type: str
    target_agent_id: int | None
    a2a_endpoint_id: int | None
    payload: str
    delivery: str
    webhook_url: str | None
    connector_id: int | None
    knowledge_id: int | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_status: str | None


def _out(t: ScheduledTask) -> TaskOut:
    return TaskOut(
        id=t.id, name=t.name, owner_id=t.owner_id, enabled=t.enabled,
        schedule_kind=t.schedule_kind, every_seconds=t.every_seconds,
        cron_expr=t.cron_expr, action_type=t.action_type,
        target_agent_id=t.target_agent_id, a2a_endpoint_id=t.a2a_endpoint_id,
        payload=t.payload, delivery=t.delivery, webhook_url=t.webhook_url,
        connector_id=t.connector_id, knowledge_id=t.knowledge_id,
        last_run_at=t.last_run_at, next_run_at=t.next_run_at, last_status=t.last_status,
    )


def _validate(body: TaskIn) -> None:
    if body.action_type == "agent_message" and body.target_agent_id is None:
        raise HTTPException(422, "agent_message 动作必须指定 target_agent_id")
    if body.action_type == "a2a_call" and body.a2a_endpoint_id is None:
        raise HTTPException(422, "a2a_call 动作必须指定 a2a_endpoint_id")
    if body.schedule_kind not in ("interval", "cron"):
        raise HTTPException(422, "schedule_kind 只能是 interval 或 cron")
    for ch in [x.strip() for x in body.delivery.split(",") if x.strip()]:
        if ch not in DELIVERY_CHOICES:
            raise HTTPException(422, f"不支持的结果处理方式: {ch}")


async def _task_or_404(session: AsyncSession, task_id: int, user) -> ScheduledTask:
    t = (await session.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "任务不存在")
    if not can_modify(user, t.owner_id):
        raise HTTPException(403, "无权操作他人的任务")
    return t


@router.get("", response_model=list[TaskOut])
async def list_tasks(user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]):
    q = select(ScheduledTask)
    if user.role != UserRole.ADMIN:
        q = q.where(ScheduledTask.owner_id == user.id)
    rows = (await session.execute(q.order_by(ScheduledTask.id.desc()))).scalars().all()
    return [_out(t) for t in rows]


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(body: TaskIn, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]):
    _validate(body)
    t = ScheduledTask(owner_id=user.id, **body.model_dump())
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _out(t)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, body: TaskIn, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]):
    t = await _task_or_404(session, task_id, user)
    _validate(body)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await session.commit()
    await session.refresh(t)
    return _out(t)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: int, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]):
    t = await _task_or_404(session, task_id, user)
    await session.delete(t)
    await session.commit()


@router.post("/{task_id}/run", response_model=dict)
async def run_now(task_id: int, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]):
    t = await _task_or_404(session, task_id, user)
    summary = await run_task(t.id)
    return {"ok": True, "summary": summary[:300]}


@router.post("/sweep", response_model=dict)
async def sweep(user: CurrentUser):
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "仅管理员可手动触发扫描")
    n = await run_due_tasks()
    return {"executed": n}


@router.get("/{task_id}/runs", response_model=list[dict])
async def task_runs(task_id: int, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]):
    await _task_or_404(session, task_id, user)
    rows = (
        await session.execute(
            select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.id.desc()).limit(50)
        )
    ).scalars().all()
    return [
        {
            "id": r.id, "started_at": r.started_at, "status": r.status,
            "summary": r.summary, "delivered": r.delivered,
        }
        for r in rows
    ]
