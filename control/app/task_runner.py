"""定时任务执行引擎：动作（Agent 消息 / A2A 调用）+ 5 种结果处理（可多选）。

由 scheduler 的周期循环调用 run_due_tasks()。所有执行写入 task_runs 表。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import get_settings
from .database import get_session_factory
from .hermes import gateway as gw_mod
from .hermes import conversations as conv_svc
from .hermes import chat_proxy
from .models import (
    Agent,
    A2AOutboundEndpoint,
    Connector,
    KnowledgeBase,
    ScheduledTask,
    TaskRun,
)

logger = logging.getLogger(__name__)

DELIVERY_CHOICES = ("session", "log", "webhook", "connector", "knowledge")


def _due(task: ScheduledTask, now: datetime) -> bool:
    if task.last_run_at is None:
        # 新建任务：首次执行延后一个周期，避免创建即触发
        return False
    if task.schedule_kind == "cron":
        # 简化 cron：支持 "*/N * * * *"（每 N 分钟）与 "HH:MM"（每天固定时间）
        expr = (task.cron_expr or "").strip()
        if ":" in expr and " " not in expr:
            try:
                hour, minute = [int(x) for x in expr.split(":")]
            except ValueError:
                return False
            local = now.astimezone()
            if local.hour != hour or local.minute != minute:
                return False
            return (now - task.last_run_at) > timedelta(hours=20)
        if expr.startswith("*/"):
            try:
                mins = int(expr[2:].split()[0])
            except (ValueError, IndexError):
                return False
            return (now - task.last_run_at) >= timedelta(minutes=mins)
        return False
    return (now - task.last_run_at) >= timedelta(seconds=max(1, task.every_seconds))


def _compute_next(task: ScheduledTask, now: datetime) -> datetime:
    if task.schedule_kind == "cron":
        return now + timedelta(minutes=1)
    return now + timedelta(seconds=max(1, task.every_seconds))


async def _run_action(
    session: AsyncSession, task: ScheduledTask, settings
) -> str:
    """执行动作，返回文本结果摘要（供各 delivery 复用）。"""
    if task.action_type == "a2a_call":
        ep = (
            await session.execute(
                select(A2AOutboundEndpoint).where(
                    A2AOutboundEndpoint.id == task.a2a_endpoint_id
                )
            )
        ).scalar_one_or_none()
        if ep is None:
            raise RuntimeError("A2A 端点不存在")
        headers = {"Content-Type": "application/json"}
        if ep.token:
            headers["Authorization"] = "Bearer " + ep.token
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": task.payload}]}},
        }
        async with httpx.AsyncClient(timeout=ep.timeout or 120) as c:
            r = await c.post(ep.url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        return json.dumps(data.get("result", data), ensure_ascii=False)[:4000]

    # agent_message：走控制层对话链路，产生真实会话
    agent = (
        await session.execute(select(Agent).where(Agent.id == task.target_agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise RuntimeError("目标 Agent 不存在")
    conv = await conv_svc.create_conversation_for_agent(
        session, agent=agent, source="schedule"
    )
    await session.flush()
    chunks: list[str] = []
    async with gw_mod.GatewayClient() as gw:
        async for frame in gw.chat_stream(
            conv.hermes_session_id, task.payload, profile=agent.profile_name
        ):
            text, _ = chat_proxy.extract_text_and_usage(frame)
            if text:
                chunks.append(text)
    return "".join(chunks)[:4000]


async def _deliver(
    session: AsyncSession, task: ScheduledTask, result: str, settings
) -> list[str]:
    """按 delivery 多选处理执行结果，返回实际完成的渠道列表。"""
    channels = [x.strip() for x in (task.delivery or "log").split(",") if x.strip()]
    done: list[str] = []
    for ch in channels:
        if ch not in DELIVERY_CHOICES:
            continue
        try:
            if ch == "webhook":
                if task.webhook_url:
                    async with httpx.AsyncClient(timeout=10) as c:
                        await c.post(
                            task.webhook_url,
                            json={"task": task.name, "result": result},
                        )
                    done.append("webhook")
            elif ch == "connector":
                c = (
                    await session.execute(
                        select(Connector).where(Connector.id == task.connector_id)
                    )
                ).scalar_one_or_none()
                if c is not None:
                    # 通过连接器的 runner 回发（若在线）
                    from .connectors.base import registry

                    runner = registry._runners.get(c.id)
                    if runner is not None:
                        await runner.send("schedule", f"【{task.name}】{result}")
                        done.append("connector")
            elif ch == "knowledge":
                kb = (
                    await session.execute(
                        select(KnowledgeBase).where(KnowledgeBase.id == task.knowledge_id)
                    )
                ).scalar_one_or_none()
                if kb is not None:
                    from .hermes import ragflow_ingest

                    await ragflow_ingest.ingest_text(kb, f"{task.name}\n{result}")
                    done.append("knowledge")
            elif ch == "session":
                # 会话由 agent_message 动作天然产生；a2a_call 则记录到 run 摘要
                done.append("session")
            elif ch == "log":
                done.append("log")
        except Exception as exc:
            logger.warning("任务 %s 的 %s 投递失败: %s", task.id, ch, exc)
    return done


async def run_task(task_id: int) -> str:
    """手动执行指定任务一次，返回结果摘要。"""
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    settings = get_settings()
    now = datetime.now(UTC)
    async with factory() as session:
        task = (await session.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))).scalar_one_or_none()
        if task is None:
            raise RuntimeError("任务不存在")
        run = TaskRun(task_id=task_id, status="running")
        session.add(run)
        await session.flush()
        try:
            result = await _run_action(session, task, settings)
            delivered = await _deliver(session, task, result, settings)
            run.status = "ok"
            run.result = result
            run.summary = result[:200]
            run.delivered = ",".join(delivered)
            task.last_status = "ok"
        except Exception as exc:
            run.status = "error"
            run.summary = str(exc)[:300]
            task.last_status = "error"
            logger.exception("手动执行任务 %s 失败", task_id)
        task.last_run_at = now
        task.next_run_at = _compute_next(task, now)
        await session.commit()
        return run.summary or ""


async def run_due_tasks(limit: int = 20) -> int:
    """扫描并执行到期任务；返回本次执行数量。"""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    now = datetime.now(UTC)
    ran = 0
    async with factory() as session:
        tasks = (
            (
                await session.execute(
                    select(ScheduledTask).where(ScheduledTask.enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for task in tasks:
            if ran >= limit:
                break
            task.last_run_at = task.last_run_at or now  # 首次扫描只初始化，不触发
            if not _due(task, now):
                await session.commit()
                continue
            run = TaskRun(task_id=task.id, status="running")
            session.add(run)
            await session.flush()
            try:
                result = await _run_action(session, task, settings)
                delivered = await _deliver(session, task, result, settings)
                run.status = "ok"
                run.result = result
                run.summary = result[:200]
                run.delivered = ",".join(delivered)
                task.last_status = "ok"
            except Exception as exc:
                run.status = "error"
                run.summary = str(exc)[:300]
                task.last_status = "error"
                logger.exception("定时任务 %s 执行失败", task.id)
            task.last_run_at = now
            task.next_run_at = _compute_next(task, now)
            ran += 1
            await session.commit()
    return ran
