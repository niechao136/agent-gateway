"""A2A 入站：健康检查与配置展示。

hermes 的 A2A 入站服务由环境变量控制（A2A_HOST / A2A_PORT / A2A_BEARER_TOKEN /
A2A_TRUSTED_PEERS），没有 HTTP 写接口。控制层只做**只读展示 + 连通性探测**。

⚠️ 三项缺一不可（SPEC §7.3，实测）：
1. A2A_BEARER_TOKEN（或 A2A_PEER_TOKENS）—— 否则只绑 127.0.0.1
2. A2A_HOST=0.0.0.0 —— 否则出不了容器
3. A2A_TRUSTED_PEERS —— 否则 dispatch 返回 "peer not trusted"
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()


def _read_dotenv() -> dict[str, str]:
    """读取 hermes 的 .env（A2A 配置的来源）。"""
    out: dict[str, str] = {}
    p = Path(_settings.hermes_dotenv_path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _mask(v: str | None) -> str | None:
    if not v:
        return None
    return f"{v[:4]}…{v[-2:]}" if len(v) > 8 else "***"


async def inbound_status() -> dict:
    """返回 A2A 入站配置与健康状况。"""
    env = _read_dotenv()
    host = env.get("A2A_HOST") or "127.0.0.1"
    port = int(env.get("A2A_PORT") or 9900)
    token = env.get("A2A_BEARER_TOKEN")
    peer_tokens = env.get("A2A_PEER_TOKENS")
    trusted = env.get("A2A_TRUSTED_PEERS")
    allow_all = (env.get("A2A_ALLOW_ALL_USERS") or "").lower() in ("1", "true", "yes")

    # 三项检查清单
    checks = {
        "token_configured": bool(token or peer_tokens),
        "host_widened": host not in ("127.0.0.1", "localhost"),
        "trusted_peers_configured": bool(trusted) or allow_all,
    }
    ready = all(checks.values())

    # 连通性探测 + Agent Card
    # ⚠️ 控制层与 hermes 在不同容器，127.0.0.1 会指向控制层自己。
    #    hermes 服务在 compose 网络里叫 ag-hermes。
    reachable = False
    card: dict | None = None
    error: str | None = None
    base = _probe_base()
    try:
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.get(f"{base}/.well-known/agent-card.json")
            reachable = r.status_code == 200
            if reachable:
                card = r.json()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:200]

    return {
        "host": host,
        "port": port,
        "probe_base": base,
        "bearer_token_masked": _mask(token),
        "peer_tokens_count": len([x for x in (peer_tokens or "").split(",") if x.strip()]),
        "trusted_peers": trusted or None,
        "allow_all_users": allow_all,
        "checks": checks,
        "ready": ready,
        "reachable": reachable,
        "agent_card": card,
        "error": error,
    }


def _probe_base() -> str:
    """探测 A2A 入站服务用的基址。

    hermes 在 compose 里是 ag-hermes，端口固定 9900（A2A_PORT 只在容器内有效）。
    """
    from urllib.parse import urlparse

    gw = urlparse(_settings.hermes_gateway_url)
    hostname = gw.hostname or "ag-hermes"
    return f"http://{hostname}:9900"


async def ping_inbound() -> dict:
    """探测入站服务是否响应（供前端手动刷新）。"""
    base = _probe_base()
    try:
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.get(f"{base}/.well-known/agent-card.json")
            return {"ok": r.status_code == 200, "status": r.status_code, "probe_base": base}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160], "probe_base": base}
