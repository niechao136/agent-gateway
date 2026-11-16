"""hermes dashboard 客户端：cookie 会话认证 + profile 管理。

重要（实测结论，见 SPEC §8.2.1）：
- dashboard **不接受 HTTP Basic**，带 Basic 头会 401 且日志记 `no_cookie`
- 必须走 POST /auth/password-login（body 需带 provider）换 cookie
- password-login 缺 provider 返回 422，不是 401
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()


class DashboardError(RuntimeError):
    """dashboard 调用失败。"""

    def __init__(self, message: str, *, status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class DashboardClient:
    """hermes dashboard 的 typed client。

    用法：
        async with DashboardClient() as c:
            await c.list_profiles()

    cookie 过期会自动重登一次。
    """

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._base = (base_url or _settings.hermes_dashboard_url).rstrip("/")
        self._user = username or _settings.hermes_dashboard_user
        self._pass = password or _settings.hermes_dashboard_password
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False

    async def __aenter__(self) -> DashboardClient:
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=False,
        )
        await self.login()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── 认证 ──────────────────────────────────────────────
    async def login(self) -> None:
        """用 password-login 换 cookie。provider 字段必填。"""
        assert self._client is not None
        try:
            r = await self._client.post(
                "/auth/password-login",
                json={
                    "provider": "basic",
                    "username": self._user,
                    "password": self._pass,
                },
            )
        except httpx.HTTPError as exc:
            raise DashboardError(f"无法连接 dashboard: {exc}") from exc

        if r.status_code == 422:
            raise DashboardError(
                "password-login 返回 422：请求体缺 provider 或其他字段", status=422, detail=r.text
            )
        if r.status_code >= 400:
            raise DashboardError(
                f"dashboard 登录失败 (HTTP {r.status_code})", status=r.status_code, detail=r.text
            )
        self._logged_in = True
        logger.info("dashboard 登录成功: %s", self._base)

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        assert self._client is not None
        r = await self._client.request(method, path, **kw)

        # cookie 过期 → 重登一次再试
        if r.status_code in (401, 403) and self._logged_in:
            logger.warning("dashboard 会话失效，重新登录")
            self._logged_in = False
            await self.login()
            r = await self._client.request(method, path, **kw)

        if r.status_code >= 400:
            raise DashboardError(
                f"{method} {path} -> HTTP {r.status_code}", status=r.status_code, detail=r.text
            )
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ── profiles ──────────────────────────────────────────
    async def list_profiles(self) -> list[dict]:
        data = await self._request("GET", "/api/profiles")
        return data.get("profiles", []) if isinstance(data, dict) else data

    async def get_profile(self, name: str) -> dict | None:
        for p in await self.list_profiles():
            if p.get("name") == name:
                return p
        return None

    async def create_profile(
        self,
        *,
        name: str,
        soul: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        description: str | None = None,
        mcp_servers: list[dict] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"name": name}
        if soul is not None:
            body["soul"] = soul
        if model:
            body["model"] = model
        if provider:
            body["provider"] = provider
        if description is not None:
            body["description"] = description
        if mcp_servers:
            body["mcp_servers"] = mcp_servers
        return await self._request("POST", "/api/profiles", json=body)

    async def update_profile(self, name: str, **fields: Any) -> Any:
        return await self._request("PATCH", f"/api/profiles/{name}", json=fields)

    async def delete_profile(self, name: str) -> Any:
        return await self._request("DELETE", f"/api/profiles/{name}")

    async def set_soul(self, name: str, soul: str) -> Any:
        return await self._request("PUT", f"/api/profiles/{name}/soul", json={"soul": soul})

    async def set_model(self, name: str, model: str, provider: str | None = None) -> Any:
        body: dict[str, Any] = {"model": model}
        if provider:
            body["provider"] = provider
        return await self._request(
            "POST", "/api/model/set", params={"profile": name}, json=body
        )

    async def set_description(self, name: str, description: str) -> Any:
        return await self._request(
            "PUT", f"/api/profiles/{name}/description", json={"description": description}
        )

    # ── 只读探查 ──────────────────────────────────────────
    async def auth_providers(self) -> list[dict]:
        data = await self._request("GET", "/api/auth/providers")
        return data.get("providers", []) if isinstance(data, dict) else []
