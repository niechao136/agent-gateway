"""模型 Base URL 的部署环境重写（方案 A）。

设计约束：
- 模板里永远存**逻辑地址**（如 https://generativelanguage.googleapis.com/v1beta/openai/），
  环境相关的隧道地址不入库，生产/测试共用同一份数据。
- 仅当 TUNNEL_ENABLED=1 且 URL 的 host 命中 TUNNEL_UPSTREAM_HOSTS 时重写。
- 只替换 scheme://host[:port]，path/query 原样保留。
- 幂等：已是本地隧道地址时不重复处理。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from ..config import get_settings


def rewrite_base_url(url: str | None) -> str | None:
    """返回按当前部署环境重写后的 base_url；不需要重写时原样返回。"""
    if not url:
        return url
    s = get_settings()
    if not s.tunnel_enabled:
        return url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    allowed = {h.strip().lower() for h in s.tunnel_upstream_hosts.split(",") if h.strip()}
    if host not in allowed:
        return url
    local = s.tunnel_local_base.rstrip("/")
    lp = urlsplit(local)
    # 用本地出口的 scheme://netloc + 原始 path/query
    return urlunsplit((lp.scheme, lp.netloc, parts.path, parts.query, parts.fragment))
