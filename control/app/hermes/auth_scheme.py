"""MCP / A2A 出站调用的五种鉴权方式（SPEC-v2 批次 2）。

两种传输面的落地：
- HTTP 面（sse / http / streamable_http）：生成 headers 或 query 参数
- stdio 面：生成注入子进程的环境变量（MCP_AUTH_TOKEN 等，hermes 侧约定）

auth_type 取值：
- none       不鉴权
- bearer     Authorization: Bearer <token>
- header     自定义 header：<auth_name>: <token>
- query      URL query：<auth_name>=<token>（如 ?api_key=...）
- basic      Basic base64(user:pass)，auth_name 当作用户名，token 为密码
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from urllib.parse import urlencode

AUTH_TYPES = ("none", "bearer", "header", "query", "basic")


@dataclass
class AuthConfig:
    auth_type: str = "none"
    token: str | None = None
    auth_name: str | None = None  # header 名 / query 参数名 / basic 用户名

    def validate(self) -> str | None:
        """返回错误信息，None 表示合法。"""
        if self.auth_type not in AUTH_TYPES:
            return f"auth_type 必须是 {'/'.join(AUTH_TYPES)} 之一"
        if self.auth_type == "none":
            return None
        if not self.token:
            return f"auth_type={self.auth_type} 需要提供 token"
        if self.auth_type in ("header", "query") and not self.auth_name:
            return f"auth_type={self.auth_type} 需要提供 auth_name（{self.auth_type} 参数名）"
        return None


@dataclass
class HttpAuth:
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)


def build_http_auth(cfg: AuthConfig) -> HttpAuth:
    """HTTP 面（sse/http/streamable）的鉴权落点。"""
    err = cfg.validate()
    if err:
        raise ValueError(err)
    out = HttpAuth()
    t = cfg.auth_type
    if t == "bearer":
        out.headers["Authorization"] = f"Bearer {cfg.token}"
    elif t == "header":
        out.headers[cfg.auth_name or "X-Auth"] = cfg.token or ""
    elif t == "query":
        out.query[cfg.auth_name or "api_key"] = cfg.token or ""
    elif t == "basic":
        raw = f"{cfg.auth_name or ''}:{cfg.token or ''}".encode()
        out.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    return out


def append_query(url: str, query: dict[str, str]) -> str:
    if not query:
        return url
    sep = "&" if "?" in url else "?"
    return f"{sep.join([url, urlencode(query)])}" if sep == "&" else f"{url}?{urlencode(query)}"


def build_stdio_env(cfg: AuthConfig) -> dict[str, str]:
    """stdio 面的鉴权落点：注入子进程环境变量（hermes 约定）。"""
    err = cfg.validate()
    if err:
        raise ValueError(err)
    if cfg.auth_type == "none":
        return {}
    env = {
        "MCP_AUTH_TYPE": cfg.auth_type,
        "MCP_AUTH_TOKEN": cfg.token or "",
    }
    if cfg.auth_name:
        env["MCP_AUTH_NAME"] = cfg.auth_name
    return env


def redact(cfg: AuthConfig) -> dict:
    """接口回显用：不回明文（用户拍板）。"""
    return {
        "auth_type": cfg.auth_type,
        "has_token": bool(cfg.token),
        "auth_name": cfg.auth_name,
    }
