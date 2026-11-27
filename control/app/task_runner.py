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


def _extract_a2a_text(data: dict) -> str:
    """从 A2A JSON-RPC 响应中提取纯文本回复。

    A2A `message/send` 返回的是完整 JSON-RPC 信封：::

        {"id": "...", "contextId": "...", "status": {"state": "completed"},
         "artifacts": [{"parts": [{"kind": "text", "text": "真正回答"}]}]}

    直接 json.dumps 整个信封会把协议字段一起发给连接器/日志，
    用户体验差。这里只拼接 ``artifacts[].parts[].text``，并做多级兜底。
    """
    result = data.get("result", data) if isinstance(data, dict) else data
    if not isinstance(result, dict):
        return str(result)

    texts: list[str] = []
    for artifact in result.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        for part in artifact.get("parts") or []:
            if not isinstance(part, dict):
                continue
            txt = part.get("text")
            if txt:
                texts.append(str(txt))
    if texts:
        return "\n".join(texts).strip()[:4000]

    # 兜底 1：status.message.parts（部分实现把最终回复放在 status 里）
    status = result.get("status")
    if isinstance(status, dict):
        msg = status.get("message")
        if isinstance(msg, dict):
            for part in msg.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
    if texts:
        return "\n".join(texts).strip()[:4000]

    # 兜底 2：任务失败时给可读错误，而不是整坨 JSON
    if isinstance(status, dict):
        state = status.get("state")
        if state and state != "completed":
            msg = status.get("message") or ""
            return f"A2A 调用未完成（state={state}）：{msg}"[:4000]

    return json.dumps(result, ensure_ascii=False)[:4000]


def _detach_task(task: ScheduledTask):
    """把 ORM 对象的常用字段拍成脱离 session 的轻量对象。

    耗时阶段（Agent 流式对话 / A2A HTTP / webhook）不持有 DB session，
    _run_action / _deliver 靠本函数提供的简单属性安全读取配置。
    """
    from types import SimpleNamespace

    fields = (
        "id name action_type target_agent_id payload a2a_endpoint_id "
        "delivery webhook_url connector_id knowledge_id enabled"
    ).split()
    return SimpleNamespace(**{f: getattr(task, f, None) for f in fields})


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


async def _run_action(task: ScheduledTask, settings) -> str:
    """执行动作，返回文本结果摘要（供各 delivery 复用）。

    耗时阶段（Agent 流式对话 / A2A HTTP）绝不持有 DB session：
    本函数自己开短 session 取完配置就关闭，避免占住连接池导致
    并发的 /run 请求在 get_session() 处排队（表现为"卡 10 秒"）。
    """
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    if task.action_type == "a2a_call":
        async with factory() as session:
            ep = (
                await session.execute(
                    select(A2AOutboundEndpoint).where(
                        A2AOutboundEndpoint.id == task.a2a_endpoint_id
                    )
                )
            ).scalar_one_or_none()
            ep_data = (
                dict(url=ep.url, token=ep.token, timeout=ep.timeout)
                if ep is not None
                else None
            )
        if ep_data is None:
            raise RuntimeError("A2A 端点不存在")
        headers = {"Content-Type": "application/json"}
        if ep_data["token"]:
            headers["Authorization"] = "Bearer " + ep_data["token"]
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": task.payload}]}},
        }
        # 内部端点存的是相对路径（/a2a/<slug>），httpx 需要绝对 URL。
        from .hermes.a2a import _absolute_a2a_url

        target = _absolute_a2a_url(ep_data["url"])
        if not target:
            raise RuntimeError("A2A 端点 URL 为空，且未配置 PUBLIC_BASE_URL")
        async with httpx.AsyncClient(timeout=ep_data["timeout"] or 120) as c:
            r = await c.post(target, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        return _extract_a2a_text(data)

    # agent_message：走控制层对话链路，产生真实会话
    # 只在短 session 里建会话，随后流式对话不占连接池
    async with factory() as session:
        agent = (
            await session.execute(select(Agent).where(Agent.id == task.target_agent_id))
        ).scalar_one_or_none()
        if agent is None:
            raise RuntimeError("目标 Agent 不存在")
        conv = await conv_svc.create_conversation_for_agent(
            session, agent=agent, source="schedule"
        )
        await session.commit()
        sid = conv.hermes_session_id
        profile = agent.profile_name
    chunks: list[str] = []
    async with gw_mod.GatewayClient() as gw:
        # 必须先经 chat_proxy.translate_stream 翻译：hermes 原始帧是
        # assistant.delta / run.completed 等，extract_text_and_usage 只认
        # 翻译后的 token 事件。直接喂原始帧会永远提取到空字符串，
        # 导致连接器/日志/知识库收到的结果全空（只剩任务名）。
        raw = gw.chat_stream(sid, task.payload, profile=profile)
        async for frame in chat_proxy.translate_stream(raw, thread_id=sid):
            text, _ = chat_proxy.extract_text_and_usage(frame)
            if text:
                chunks.append(text)
    result = "".join(chunks).strip()
    if not result:
        logger.warning(
            "任务 %s 的 Agent 回复为空（session=%s），请检查模型与 profile 配置",
            task.id,
            sid,
        )
        result = "（Agent 未返回内容）"
    return result[:4000]


async def _deliver(task: ScheduledTask, result: str, settings) -> list[str]:
    """按 delivery 多选处理执行结果，返回实际完成的渠道列表。

    同样自己管理短 session：DB 查询用完即关，网络投递（webhook/连接器）
    不占连接池。
    """
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
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
                async with factory() as session:
                    c = (
                        await session.execute(
                            select(Connector).where(Connector.id == task.connector_id)
                        )
                    ).scalar_one_or_none()
                    c_data = (
                        dict(id=c.id, default_chat_id=c.default_chat_id, enabled=c.enabled)
                        if c is not None
                        else None
                    )
                if c_data is not None:
                    from .connectors.base import registry

                    # 目标会话：用连接器记录的最近会话（收到过消息才有）。
                    target_chat = c_data["default_chat_id"] or ""
                    if not target_chat:
                        logger.warning(
                            "任务 %s 的 connector 回报跳过：连接器 %s 尚无已知会话"
                            "（需先在该连接器收到一条消息）",
                            task.name,
                            c_data["id"],
                        )
                    elif not c_data["enabled"]:
                        logger.warning("任务 %s 的 connector 回报跳过：连接器 %s 未启用", task.name, c_data["id"])
                    else:
                        runner = registry._runners.get(c_data["id"])
                        if runner is None:
                            logger.warning(
                                "任务 %s 的 connector 回报跳过：连接器 %s 未运行", task.name, c_data["id"]
                            )
                        else:
                            await runner.send_with_retry(target_chat, f"【{task.name}】{result}")
                            done.append("connector")
            elif ch == "knowledge":
                async with factory() as session:
                    kb = (
                        await session.execute(
                            select(KnowledgeBase).where(KnowledgeBase.id == task.knowledge_id)
                        )
                    ).scalar_one_or_none()
                    if kb is not None:
                        from .models import RagflowSite

                        site = (
                            await session.execute(
                                select(RagflowSite).where(RagflowSite.id == kb.site_id)
                            )
                        ).scalar_one_or_none()
                        kb_data = dict(id=kb.id, name=kb.name, site_id=kb.site_id)
                        site_data = (
                            dict(base_url=site.base_url, api_key=site.api_key)
                            if site is not None else None
                        )
                if site_data is not None:
                    from types import SimpleNamespace
                    from .hermes import ragflow_ingest

                    await ragflow_ingest.ingest_text(
                        SimpleNamespace(**kb_data), f"{task.name}\n{result}",
                        base_url=site_data["base_url"], api_key=site_data["api_key"],
                    )
                    done.append("knowledge")
            elif ch == "session":
                # 会话由 agent_message 动作天然产生；a2a_call 则记录到 run 摘要
                done.append("session")
            elif ch == "log":
                done.append("log")
        except Exception as exc:
            logger.warning("任务 %s 的 %s 投递失败: %s", task.id, ch, exc)
    return done


async def create_run(task_id: int) -> int:
    """先落一条 TaskRun 记录并立即返回其 id（不等待执行）。

    供 "立即运行" API 使用：接口只负责排队，执行在后台进行，
    前端凭 run_id 轮询 /runs 看进度与结果。
    """
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    async with factory() as session:
        task = (
            await session.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        ).scalar_one_or_none()
        if task is None:
            raise RuntimeError("任务不存在")
        run = TaskRun(task_id=task_id, status="queued")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def execute_run(run_id: int, task_id: int) -> None:
    """执行一个已排队的 TaskRun（后台任务入口）。

    关键：DB session 只在「读配置 / 写状态」这几步短暂持有，
    Agent 对话这种耗时操作绝不占用连接池——否则并发的 /run 请求
    会在 get_session() 处排队等待，表现为接口"卡 10 秒"。
    """
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    settings = get_settings()
    now = datetime.now(UTC)

    # 短事务 1：标记 running
    async with factory() as session:
        run = (await session.execute(select(TaskRun).where(TaskRun.id == run_id))).scalar_one_or_none()
        task = (
            await session.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        ).scalar_one_or_none()
        if run is None or task is None:
            logger.warning("执行任务失败：run=%s task=%s 不存在", run_id, task_id)
            return
        run.status = "running"
        run.started_at = now
        await session.commit()

    # 耗时阶段：不持有任何 DB session
    result = ""
    delivered: list[str] = []
    status = "ok"
    summary = ""
    try:
        async with factory() as session:
            task = (
                await session.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
            ).scalar_one_or_none()
            if task is None:
                raise RuntimeError("任务不存在")
            # 分离 ORM 对象：_run_action/_deliver 自己开短 session，
            # 这里先把需要的标量字段取出来，避免在耗时阶段持有外部 session。
            task_data = _detach_task(task)
        result = await _run_action(task_data, settings)
        delivered = await _deliver(task_data, result, settings)
        summary = result[:200]
    except Exception as exc:
        status = "error"
        summary = str(exc)[:300]
        logger.exception("执行任务 %s 失败", task_id)

    # 短事务 2：写回最终结果
    async with factory() as session:
        run = (await session.execute(select(TaskRun).where(TaskRun.id == run_id))).scalar_one_or_none()
        task = (
            await session.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        ).scalar_one_or_none()
        if run is None:
            return
        run.status = status
        run.result = result
        run.summary = summary
        run.delivered = ",".join(delivered)
        if task is not None:
            task.last_status = status
            task.last_run_at = now
            task.next_run_at = _compute_next(task, now)
        await session.commit()


async def run_task(task_id: int) -> str:
    """手动执行指定任务一次并等待完成（内部/兼容用）。

    注意：HTTP 接口不应直接 await 它（Agent 对话可能耗时数分钟），
    应先 create_run() 立即返回 run_id，再 execute_run() 后台执行。
    """
    run_id = await create_run(task_id)
    await execute_run(run_id, task_id)
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    async with factory() as session:
        run = (await session.execute(select(TaskRun).where(TaskRun.id == run_id))).scalar_one_or_none()
        return (run.summary if run else "") or ""


async def run_due_tasks(limit: int = 20) -> int:
    """扫描并执行到期任务；返回本次执行数量。"""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    now = datetime.now(UTC)
    ran = 0
    due_ids: list[int] = []
    # 阶段 1：只在短事务里扫描到期任务并更新调度字段，立即释放 session。
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
            if len(due_ids) >= limit:
                break
            task.last_run_at = task.last_run_at or now  # 首次扫描只初始化，不触发
            if not _due(task, now):
                continue
            due_ids.append(task.id)
            task.last_run_at = now
            task.next_run_at = _compute_next(task, now)
        await session.commit()
    # 阶段 2：session 已释放，再排队执行，避免与 create_run/execute_run 争连接。
    import asyncio

    for task_id in due_ids:
        run_id = await create_run(task_id)
        asyncio.create_task(execute_run(run_id, task_id))
        ran += 1
    return ran
