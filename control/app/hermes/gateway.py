"""hermes gateway 客户端：sessions API + 流式对话。

契约来自实测（见 SPEC §5.2）：
- POST /api/sessions        → 201，body {"id": ...}；重复 id → 409
- GET  /api/sessions        → {"object","data","limit","offset","has_more"}
                              ★ 列表字段是 `data`，不是 `sessions`
- GET  /api/sessions/{id}/messages → 消息列表
- DELETE /api/sessions/{id} → 200
- POST /api/sessions/{id}/chat/stream → SSE

★ hermes 的 session **没有业务用户归属**（`user_id` 恒为 `uid:1000` 或 null），
  所以「用户 A 只能看到自己的会话」必须由控制层的 conversations 表保证。
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()


def resolve_api_key() -> str:
    """解析实际生效的 hermes API key。

    ⚠️ 关键（实测，见 SPEC §11.8.1）：
    hermes 用 `override=True` 加载 `/opt/data/.env`，其中的 `API_SERVER_KEY`
    会**覆盖**容器环境变量。所以 compose 传入的值通常不是生效值。

    优先级：
        1. `HERMES_DOTENV_PATH` 指向的文件里的 API_SERVER_KEY（最可靠）
        2. 环境变量 `HERMES_API_KEY`
    """
    dotenv = _settings.hermes_dotenv_path
    if dotenv:
        key = _read_dotenv_key(Path(dotenv))
        if key:
            return key

    if _settings.hermes_api_key:
        return _settings.hermes_api_key
    logger.error(
        "无法解析 hermes API key：%s 不可读且 HERMES_API_KEY 为空", dotenv
    )
    return ""


def _read_dotenv_key(path: Path) -> str:
    """从指定 .env 文件读 API_SERVER_KEY。"""
    try:
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"\s*API_SERVER_KEY\s*=\s*(.*)", line)
                if m:
                    key = m.group(1).strip().strip('"').strip("'")
                    if key:
                        return key
    except OSError as exc:
        logger.warning("读取 %s 失败: %s", path, exc)
    return ""


def profile_api_key(profile: str) -> str:
    """profile 专属 API_SERVER_KEY（hermes multiplex 路由必需）。

    hermes 以 GATEWAY_MULTIPLEX_PROFILES=true 运行时，`/p/<profile>/...`
    必须用该 profile 自己 .env 里的 API_SERVER_KEY，全局 key 会被拒（401）。
    这里确定性派生 sha256(全局key + profile)，与 provisioner 写入 profile
    .env 的值严格一致，控制层无需在 DB 另存 key。
    """
    import hashlib

    return hashlib.sha256((resolve_api_key() + profile).encode()).hexdigest()


class GatewayError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class GatewayClient:
    """hermes gateway（OpenAI 兼容 API server）的 client。

    鉴权用 Bearer `HERMES_API_KEY`。
    ⚠️ 这个值必须是 `/opt/data/.env` 里实际生效的那个，
    不能用 compose 里的 ``API_SERVER_KEY``（会被 .env 覆盖，见 SPEC §11.8.1）。
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self._base = (base_url or _settings.hermes_gateway_url).rstrip("/")
        # 延迟解析：每次实例化都重新读 .env，避免 hermes 重新生成 key 后失效
        self._key = api_key or resolve_api_key()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GatewayClient:
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(300.0, connect=10.0),
            headers={"Authorization": f"Bearer {self._key}"},
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GatewayClient 必须在 async with 内使用")
        return self._client

    def _headers(self, profile: str | None) -> dict[str, str] | None:
        """profile 专属 API 用该 profile 的 API_SERVER_KEY 鉴权；
        默认 profile 用 client 的全局 key（返回 None 走 client 默认 header）。"""
        if not profile:
            return None
        return {"Authorization": f"Bearer {profile_api_key(profile)}"}

    def _p(self, profile: str | None, path: str) -> str:
        """profile 专属路由前缀（与 _profile_path 等价，内部统一用这个）。"""
        return self._profile_path(profile, path)

    def _headers(self, profile: str | None) -> dict[str, str]:
        """profile 专属鉴权头：multiplex 路由必须用该 profile 自己的 key。"""
        if not profile:
            return {"Authorization": f"Bearer {self._key}"}
        return {"Authorization": f"Bearer {profile_api_key(profile)}"}

    def _p(self, profile: str | None, path: str) -> str:
        """profile 路由前缀 + 路径。"""
        return self._profile_path(profile, path)

    async def _json(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise GatewayError(
                f"gateway HTTP {r.status_code}", status=r.status_code, detail=r.text[:500]
            )
        if not r.content:
            return None
        return r.json()

    # ── sessions ──────────────────────────────────────────
    async def create_session(
        self, session_id: str, *, title: str | None = None, profile: str | None = None
    ) -> dict:
        """创建会话。重复 id 抛 GatewayError(status=409)。"""
        body: dict[str, Any] = {"id": session_id}
        if title:
            body["title"] = title
        path = self._p(profile, "/api/sessions")
        r = await self._c().post(path, json=body, headers=self._headers(profile))
        return await self._json(r)

    async def list_sessions(
        self, *, limit: int = 50, offset: int = 0, profile: str | None = None
    ) -> list[dict]:
        path = self._p(profile, "/api/sessions")
        r = await self._c().get(
            path, params={"limit": limit, "offset": offset}, headers=self._headers(profile)
        )
        data = await self._json(r) or {}
        # 实测字段是 data，兼容性兜底 sessions
        return data.get("data") or data.get("sessions") or []

    async def get_session(self, session_id: str, *, profile: str | None = None) -> dict | None:
        """通过列表过滤出单个会话（无 GET /api/sessions/{id} 单查端点）。"""
        for s in await self.list_sessions(limit=200, profile=profile):
            if s.get("id") == session_id:
                return s
        return None

    async def delete_session(self, session_id: str, *, profile: str | None = None) -> None:
        path = self._p(profile, f"/api/sessions/{session_id}")
        r = await self._c().delete(path, headers=self._headers(profile))
        await self._json(r)

    async def session_messages(
        self, session_id: str, *, limit: int | None = None, profile: str | None = None
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        path = self._p(profile, f"/api/sessions/{session_id}/messages")
        r = await self._c().get(path, params=params, headers=self._headers(profile))
        data = await self._json(r) or {}
        if isinstance(data, list):
            return data
        return data.get("data") or data.get("messages") or []

    # ── 流式对话 ──────────────────────────────────────────
    async def chat_stream(
        self, session_id: str, message: str, *, profile: str | None = None
    ) -> AsyncIterator[bytes]:
        """SSE 原始字节流。解析交给上层（chat_proxy）。

        ⚠️ 请求体格式（实测，见 SPEC §5.4）：
            {"message": "<字符串>"}     ← 正确
            {"messages": [...]}         ← 错误，会 400 missing_message

        `_session_chat_user_message` 只认 `message` 或 `input`，不是 OpenAI 的 messages 数组。
        """
        payload = {"message": message}
        path = self._p(profile, f"/api/sessions/{session_id}/chat/stream")
        async with self._c().stream(
            "POST", path, json=payload, headers=self._headers(profile)
        ) as r:
            if r.status_code >= 400:
                body = await r.aread()
                raise GatewayError(
                    f"chat stream HTTP {r.status_code}",
                    status=r.status_code,
                    detail=body.decode("utf-8", "replace")[:500],
                )
            async for chunk in r.aiter_bytes():
                yield chunk

    # ── 工具 ──────────────────────────────────────────────
    def _profile_path(self, profile: str | None, path: str) -> str:
        """多 profile 路由：/p/<profile>/..."""
        if not profile:
            return path
        return f"/p/{profile}{path}"

    async def toolsets(self, profile: str | None = None) -> dict:
        """读取实际生效的 toolset（安全验证用）。"""
        path = self._profile_path(profile, "/v1/toolsets")
        r = await self._c().get(path, headers=self._headers(profile))
        return await self._json(r) or {}
