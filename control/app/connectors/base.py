"""连接器框架：进程内长连接管理（SPEC-v2 批次 3，硬约束：不用 webhook）。

- ConnectorRunner 抽象：start/stop/status，收到消息回调 on_message
- registry：进程内单例管理器；lifespan 启动时拉起全部 enabled 连接器
- 会话映射（用户拍板）：{platform}:{connector_id}:{chat_id} 每 chat 一个会话
- 平台回发失败：重试 + 指数退避
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy import select

from ..database import SessionLocal
from ..hermes import chat_proxy, conversations as conv_svc
from ..hermes import gateway as gw_mod
from ..models import Agent, Connector, Conversation

logger = logging.getLogger(__name__)

# 每条消息回发的最大尝试
_SEND_RETRIES = 3


@dataclass
class RunnerStatus:
    state: str = "idle"  # idle | connecting | connected | error | stopped
    last_error: str | None = None
    last_connected_at: float | None = None
    messages_in: int = 0
    messages_out: int = 0

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "last_error": self.last_error,
            "last_connected_at": self.last_connected_at,
            "messages_in": self.messages_in,
            "messages_out": self.messages_out,
        }


class ConnectorRunner(ABC):
    """平台适配器基类。子类实现 _connect/_send，收发均由框架驱动。"""

    platform: str = ""

    def __init__(self, connector: Connector):
        self.connector = connector
        self.status = RunnerStatus()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # ── 生命周期 ──
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self.status.state = "connecting"
        self._task = asyncio.create_task(self._run(), name=f"connector-{self.connector.id}")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: S110
                pass  # 停止即成功，错误已在 _run 里记录
            self._task = None
        self.status.state = "stopped"

    async def _run(self) -> None:
        """带退避的重连循环。"""
        backoff = 1
        while not self._stop_event.is_set():
            try:
                await self._connect()
                self.status.state = "connected"
                self.status.last_connected_at = time.time()
                self.status.last_error = None
                backoff = 1
                await self._poll_loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.status.state = "error"
                self.status.last_error = str(exc)[:300]
                logger.warning(
                    "连接器 %s(%s) 异常，%ss 后重连: %s",
                    self.connector.id, self.platform, backoff, exc,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break  # stop 被触发
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60)

    @abstractmethod
    async def _connect(self) -> None:
        """建立连接/初始化 SDK 客户端。"""

    @abstractmethod
    async def _poll_loop(self) -> None:
        """阻塞循环：拉取消息 → self.on_message(...)。"""

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> None:
        """向平台回发消息（带重试）。"""

    async def send_with_retry(self, chat_id: str, text: str) -> None:
        delay = 1
        for attempt in range(1, _SEND_RETRIES + 1):
            try:
                await self.send(chat_id, text)
                self.status.messages_out += 1
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "回发失败（%s/%s）connector=%s: %s",
                    attempt, _SEND_RETRIES, self.connector.id, exc,
                )
                if attempt == _SEND_RETRIES:
                    raise
                await asyncio.sleep(delay)
                delay *= 2

    # ── 消息处理：平台 → hermes → 平台 ──
    async def on_message(self, chat_id: str, user_id: str, text: str) -> None:
        """归一化消息入口。会话映射：{platform}:{connector_id}:{chat_id}。"""
        self.status.messages_in += 1
        cid = self.connector.id

        # 记录最近会话，供定时任务的 connector 回报定位目标 chat。
        try:
            self.connector.default_chat_id = chat_id
        except Exception:  # 只读对象等异常不影响主流程
            pass

        def session_title() -> str:
            return f"[{self.platform}:{cid}:{chat_id}]"

        async with SessionLocal() as session:
            agent = (
                await session.execute(select(Agent).where(Agent.id == self.connector.agent_id))
            ).scalar_one_or_none()
            if agent is None:
                logger.error("连接器 %s 绑定的 Agent 不存在", cid)
                return

            # 持久化最近会话：定时任务的 connector 回报需要它作为发送目标。
            try:
                await session.execute(
                    update(Connector)
                    .where(Connector.id == cid)
                    .values(default_chat_id=chat_id)
                )
                await session.commit()
            except Exception as exc:  # 记录失败不应阻断消息处理
                logger.warning("记录连接器 %s 默认会话失败: %s", cid, exc)
                await session.rollback()

            # 用平台/chat 作为 title 前缀，便于检索；session id 完全交给 hermes 生成，
            # 不能手动覆盖——否则 DB 存的 sid 与 hermes 里的不一致，查历史必然 404。
            # 匹配键只取 chat_id 前 16 位：飞书 chat_id 含 _ 等 LIKE 元字符，且兼容
            # 旧格式 [feishu{cid}_{chat_id前11}] 与新格式 [feishu:{cid}:{chat_id}]。
            short = chat_id[:11]  # 兼容旧会话 title 里截断的 chat_id
            candidates = (
                f"[{self.platform}{cid}_{short}%",   # 旧格式
                f"[{self.platform}:{cid}:{short}%",  # 新格式
            )
            conv = None
            for marker in candidates:
                conv = (
                    await session.execute(
                        select(Conversation).where(
                            Conversation.agent_id == agent.id,
                            Conversation.title.like(marker),
                        )
                    )
                ).scalar_one_or_none()
                if conv is not None:
                    break
            if conv is None:
                conv = await conv_svc.create_conversation_for_agent(
                    session, agent=agent, source=f"{self.platform}{cid}"[:20]
                )
                conv.title = f"[{self.platform}{cid}_{short}] " + conv.title
                await session.commit()

            sid = conv.hermes_session_id
            reply_parts: list[str] = []
            try:
                gw = gw_mod.GatewayClient()
                async with gw:
                    async for frame in chat_proxy.translate_stream(
                        gw.chat_stream(sid, text, profile=agent.profile_name), thread_id=sid
                    ):
                        t, _ = chat_proxy.extract_text_and_usage(frame)
                        if t:
                            reply_parts.append(t)
            except Exception as exc:  # noqa: BLE001
                logger.exception("连接器对话失败 connector=%s", cid)
                await self.send_with_retry(chat_id, f"⚠️ 处理失败: {exc}")
                return

            await conv_svc.touch_conversation(session, conv)

        reply = "".join(reply_parts).strip() or "（无回复）"
        await self.send_with_retry(chat_id, reply)


class ConnectorRegistry:
    """进程内连接器管理器。"""

    def __init__(self) -> None:
        self._runners: dict[int, ConnectorRunner] = {}

    def _make_runner(self, c: Connector) -> ConnectorRunner:
        from .telegram import TelegramRunner

        if c.platform == "telegram":
            return TelegramRunner(c)
        if c.platform == "feishu":
            from .feishu import FeishuRunner

            return FeishuRunner(c)
        if c.platform == "slack":
            from .slack import SlackRunner

            return SlackRunner(c)
        raise ValueError(f"未知平台: {c.platform}")

    async def ensure_started(self, c: Connector) -> None:
        if not c.enabled:
            return
        runner = self._runners.get(c.id)
        if runner is None or runner.status.state in ("stopped", "error"):
            runner = self._make_runner(c)
            self._runners[c.id] = runner
        await runner.start()

    async def reload(self, c: Connector, was_enabled: bool) -> None:
        """配置变更后：启停对齐 + 凭证变更重启。"""
        old = self._runners.get(c.id)
        if old:
            await old.stop()
            del self._runners[c.id]
        if c.enabled:
            await self.ensure_started(c)

    async def restart(self, c: Connector) -> None:
        await self.reload(c, c.enabled)

    async def stop(self, connector_id: int) -> None:
        runner = self._runners.pop(connector_id, None)
        if runner:
            await runner.stop()

    async def start_all(self) -> int:
        """lifespan 启动：拉起全部 enabled 连接器。返回数量。"""
        async with SessionLocal() as session:
            rows = (
                await session.execute(select(Connector).where(Connector.enabled == True))  # noqa: E712
            ).scalars().all()
            for c in rows:
                try:
                    await self.ensure_started(c)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("连接器 %s 启动失败: %s", c.id, exc)
            return len(rows)

    async def stop_all(self) -> None:
        for rid in list(self._runners):
            await self.stop(rid)

    def status_of(self, connector_id: int) -> dict | None:
        runner = self._runners.get(connector_id)
        return runner.status.as_dict() if runner else None

    async def test(self, c: Connector) -> dict:
        """连通性自检：尝试创建 runner 并调平台 ping（不真发消息）。"""
        try:
            runner = self._make_runner(c)
            ok, detail = await runner.ping()
            return {"ok": ok, "detail": detail}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}


registry = ConnectorRegistry()
