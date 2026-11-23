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
        # ⚠️ lark-oapi 的 ws.Client 在 import 时抓取模块级 event loop，并在 start()
        # 里 loop.run_until_complete()。必须在独立线程中、先 set_event_loop 再 import
        # 并构造 Client，否则会抓到 uvicorn 正在运行的 loop → "This event loop is
        # already running" → 线程秒退、WS 从未握手，但状态却显示 connected。
        app_id, app_secret = self._creds()
        self._loop = asyncio.get_running_loop()

        def _run_ws() -> None:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

            # 确保 SDK 的模块级 loop 属于本线程
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())

            def on_message(data: P2ImMessageReceiveV1) -> None:
                """SDK 回调（线程内）。转发到事件循环。"""
                try:
                    event = data.event
                    msg = event.message
                    chat_id = msg.chat_id
                    if msg.message_type != "text":
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

            # ⚠️ event_handler 必须是 EventDispatcherHandler，普通函数会在 SDK
            # 分发时因缺少 _do_without_validation 抛 AttributeError 而被静默吞掉。
            handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(on_message)
                .build()
            )
            client = lark.ws.Client(
                app_id,
                app_secret,
                event_handler=handler,
                log_level=lark.LogLevel.INFO,
            )
            self._ws_client = client
            logger.info("飞书 WS 客户端启动（connector=%s）", self.connector.id)
            try:
                client.start()
            except Exception as exc:  # noqa: BLE001
                logger.exception("飞书 WS 运行异常（connector=%s）：%s", self.connector.id, exc)

        self._thread = threading.Thread(
            target=_run_ws,
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
