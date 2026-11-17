"""Slack 连接器：Socket Mode 长连接（slack-bolt，无需公网 webhook）。"""

from __future__ import annotations

import asyncio
import logging

from .base import ConnectorRunner

logger = logging.getLogger(__name__)


class SlackRunner(ConnectorRunner):
    platform = "slack"

    def __init__(self, connector):
        super().__init__(connector)
        self._handler = None
        self._client = None

    def _app_token(self) -> str:
        return self.connector.credentials["app_token"]  # xapp-

    def _bot_token(self) -> str:
        return self.connector.credentials["bot_token"]  # xoxb-

    async def ping(self) -> tuple[bool, str]:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {self._bot_token()}"},
            )
            data = r.json()
            if data.get("ok"):
                return True, f"workspace {data.get('team')}"
            return False, f"token 无效: {data.get('error')}"

    async def _connect(self) -> None:
        from slack_bolt.adapter.socket_mode.asyncio import AsyncSocketModeHandler
        from slack_bolt.async_app import AsyncApp

        bot_token = self._bot_token()
        loop = asyncio.get_running_loop()

        app = AsyncApp(token=bot_token, process_before_response=True)

        @app.event("message")
        async def handle_message(event, say):
            """slack-bolt 回调；转发到主循环，避免阻塞 bolt 的处理。"""
            # 忽略 bot 自己的消息，防死循环
            if event.get("bot_id") or event.get("subtype"):
                return
            text = event.get("text") or ""
            chat_id = event.get("channel") or ""
            user_id = event.get("user") or "unknown"
            if not text or not chat_id:
                return
            asyncio.run_coroutine_threadsafe(
                self.on_message(chat_id, user_id, text), loop
            ) if False else asyncio.create_task(
                self.on_message(chat_id, user_id, text),
                name=f"slack-msg-{chat_id}",
            )

        self._handler = AsyncSocketModeHandler(app, self._app_token)

    async def _poll_loop(self) -> None:
        """SocketModeHandler.connect() 阻塞维持连接；取消时自动断开。"""
        assert self._handler is not None
        await self._handler.connect_async()
        # connect_async 返回后连接保持；等待 stop
        await self._stop_event.wait()

    async def send(self, chat_id: str, text: str) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self._bot_token()}"},
                json={"channel": chat_id, "text": text[:4000]},
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"slack send 失败: {data.get('error')}")
