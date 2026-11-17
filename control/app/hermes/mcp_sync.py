"""MCP 配置下发：把绑定到 Agent 的 MCPServer 资源写入 profile config.yaml。

写入段（hermes 约定）：config.yaml 的 mcp.servers 列表。
鉴权落点：
- http 系 transport → headers / url query
- stdio → env 注入（MCP_AUTH_*）
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .a2a import _atomic_write, profile_config_path
from .auth_scheme import AuthConfig, build_http_auth, build_stdio_env

logger = logging.getLogger(__name__)

TRANSPORTS = ("stdio", "sse", "http", "streamable_http")


class MCPSyncError(Exception):
    pass


def build_mcp_entry(s) -> dict:
    """MCPServer 资源 → hermes mcp.servers 列表项。

    注意：token 落到 config.yaml 是明文——profile 目录在服务器本地，
    与 api_key 下发同一安全模型。
    """
    if s.transport not in TRANSPORTS:
        raise MCPSyncError(f"未知 transport: {s.transport}")

    cfg = AuthConfig(auth_type=s.auth_type, token=s.token, auth_name=s.auth_name)
    entry: dict = {"name": s.name, "transport": s.transport}

    if s.transport == "stdio":
        if not s.command:
            raise MCPSyncError(f"MCP {s.name}: stdio 必须提供 command")
        entry["command"] = s.command
        entry["args"] = list(s.args or [])
        env = dict(s.env or {})
        env.update(build_stdio_env(cfg))
        if env:
            entry["env"] = env
    else:
        if not s.url:
            raise MCPSyncError(f"MCP {s.name}: {s.transport} 必须提供 url")
        http = build_http_auth(cfg)
        url = s.url
        if http.query:
            from urllib.parse import urlencode

            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode(http.query)}"
        entry["url"] = url
        if http.headers:
            entry["headers"] = http.headers

    if s.description:
        entry["description"] = s.description
    return entry


def apply_mcp_servers(profile: str, data_root: str, servers: list) -> dict:
    """把绑定服务器列表写入 profile 的 mcp.servers 段（整体替换）。"""
    path = profile_config_path(profile, data_root)
    if not path.is_file():
        raise MCPSyncError(f"profile {profile} 的 config.yaml 不存在: {path}")

    raw = path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(raw) or {}
    if not isinstance(cfg, dict):
        raise MCPSyncError(f"{path} 根节点不是映射，拒绝改写")

    entries = [build_mcp_entry(s) for s in servers]
    if entries:
        section = cfg.get("mcp")
        if not isinstance(section, dict):
            section = {}
        section["servers"] = entries
        cfg["mcp"] = section
    else:
        if isinstance(cfg.get("mcp"), dict):
            cfg["mcp"].pop("servers", None)
            if not cfg["mcp"]:
                cfg.pop("mcp", None)

    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    logger.info("已写入 %s：%d 个 MCP 服务器", path, len(entries))
    return {"path": str(path), "written": len(entries)}


def read_mcp_section(profile: str, data_root: str) -> list:
    """读取 profile 里实际生效的 mcp.servers（排查漂移用）。"""
    path = profile_config_path(profile, data_root)
    if not path.is_file():
        return []
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mcp = cfg.get("mcp")
    if not isinstance(mcp, dict):
        return []
    servers = mcp.get("servers")
    return servers if isinstance(servers, list) else []
