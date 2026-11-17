"""Telegram 连接器：裸 HTTP getUpdates 长轮询（零第三方依赖）。"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .base import ConnectorRunner

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"


class TelegramRunner(ConnectorRunner):
    platform = "telegram"

    def __init__(self, connector):
        super().__init__(connector)
        self._offset = 0
        self._client: httpx.AsyncClient | None = None

    def _token(self) -> str:
        return self.connector.credentials["bot_token"]

    async def ping(self) -> tuple[bool, str]:
        """getMe 验证 token。"""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{API}/bot{self._token()}/getMe")
            data = r.json()
            if data.get("ok"):
                me = data["result"]
                return True, f"bot @{me.get('username')}"
            return False, f"token 无效: {data.get('description')}"

    async def _connect(self) -> None:
        # webhook 模式会与长轮询冲突（硬约束 3：不用 webhook），确保清除
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{API}/bot{self._token()}/deleteWebhook")
        self._client = httpx.AsyncClient(timeout=35)  # > 长轮询 timeout

    async def _poll_loop(self) -> None:
        assert self._client is not None
        while not self._stop_event.is_set():
            r = await self._client.post(
                f"{API}/bot{self._token()}/getUpdates",
                json={
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                },
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"getUpdates 失败: {data.get('description')}")

            for update in data.get("result", []):
                self._offset = update["update_id"] + 1
                msg = update.get("message") or {}
                text = msg.get("text")
                chat_id = str((msg.get("chat") or {}).get("id") or "")
                user_id = str((msg.get("from") or {}).get("id") or "")
                if text and chat_id:
                    # 并发处理不阻塞轮询
                    asyncio.create_task(
                        self.on_message(chat_id, user_id, text),
                        name=f"tg-msg-{chat_id}",
                    )

    async def send(self, chat_id: str, text: str) -> None:
        assert self._client is not None
        r = await self._client.post(
            f"{API}/bot{self._token()}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000]},
        )
        if not r.json().get("ok"):
            raise RuntimeError(f"sendMessage 失败: {r.text[:200]}")
