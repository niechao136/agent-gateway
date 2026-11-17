"""飞书连接器：lark-oapi WebSocket 长连接（SDK 阻塞，跑独立线程）。

事件：im.message.receive_v1 → on_message → 回发（线程内同步调 SDK API）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

from .base import ConnectorRunner

logger = logging.getLogger(__name__)


class FeishuRunner(ConnectorRunner):
    platform = "feishu"

    def __init__(self, connector):
        super().__init__(connector)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_client = None  # lark ws.Client，线程内运行

    def _creds(self) -> tuple[str, str]:
        return self.connector.credentials["app_id"], self.connector.credentials["app_secret"]

    async def ping(self) -> tuple[bool, str]:
        """tenant_access_token 内部凭证获取验证 app 凭证。"""
        import httpx

        app_id, app_secret = self._creds()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = r.json()
            code = data.get("code")
            if code == 0:
                return True, "app 凭证有效"
            return False, f"凭证无效: code={code} {data.get('msg')}"

    async def _connect(self) -> None:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            P2ImMessageReceiveV1,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )

        self._lark = lark
        self._reply_types = (ReplyMessageRequest, ReplyMessageRequestBody)
        app_id, app_secret = self._creds()
        self._loop = asyncio.get_running_loop()

        def on_message(data: P2ImMessageReceiveV1) -> None:
            """SDK 回调（线程内）。转发到事件循环。"""
            try:
                event = data.event
                msg = event.message
                chat_id = msg.chat_id
                msg_type = msg.message_type
                if msg_type != "text":
                    return
                content = json.loads(msg.content or "{}")
                text = content.get("text", "")
                user_id = event.sender.sender_id.open_id if event.sender else ""
                if not text or not chat_id:
                    return
                asyncio.run_coroutine_threadsafe(
                    self.on_message(chat_id, user_id or "unknown", text), self._loop
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("飞书消息解析失败: %s", exc)

        self._ws_client = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=on_message,
            log_level=lark.LogLevel.WARNING,
        )

        # SDK 的 start 是阻塞的 → 独立线程
        self._thread = threading.Thread(
            target=self._ws_client.start,
            name=f"feishu-ws-{self.connector.id}",
            daemon=True,
        )
        self._thread.start()

    async def _poll_loop(self) -> None:
        """SDK 在自己的线程里收事件；这里只等待 stop。"""
        await self._stop_event.wait()

    async def send(self, chat_id: str, text: str) -> None:
        """线程内同步调 SDK reply API（通过 to_thread）。"""
        import lark_oapi as lark

        app_id, app_secret = self._creds()

        def _do_send():
            client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
            req = self._reply_types[0](
                message_id="",  # reply 需要原消息 id；此处用 chat 发送代替
            )
            # 用 create 接口按 chat_id 发送（无需原消息 id）
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            req = CreateMessageRequest.builder().receive_id_type("chat_id").build()
            req.request_body = CreateMessageRequestBody.builder().receive_id(chat_id).content(
                json.dumps({"text": text[:4000]})
            ).msg_type("text").build()
            resp = client.im.v1.message.create(req)
            if not resp.success():
                raise RuntimeError(f"feishu send 失败: {resp.code} {resp.msg}")

        await asyncio.to_thread(_do_send)
