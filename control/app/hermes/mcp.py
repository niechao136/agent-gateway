"""MCP 服务器：控制层做薄封装，转发到 hermes dashboard。

为什么用转发而不是自己存：
- MCP 服务器的定义最终要写进 profile 的 config.yaml，hermes 已有完整实现
  （包括 auth、OAuth、catalog、测试连通性）
- 自己在控制层再存一份会立刻产生同步问题

profile 作用域：所有端点都带 `?profile=<name>`，hermes 用 config_write_scope 隔离。
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import Agent
from .client import DashboardClient, DashboardError

logger = logging.getLogger(__name__)


class MCPError(RuntimeError):
    pass


async def list_servers(profile: str) -> list[dict]:
    async with DashboardClient() as client:
        try:
            data = await client._request("GET", f"/api/mcp/servers?profile={profile}")
        except DashboardError as exc:
            raise MCPError(f"读取 MCP 服务器失败: {exc}") from exc
    if isinstance(data, dict):
        return data.get("servers", [])
    return []


async def add_server(profile: str, body: dict[str, Any]) -> dict:
    payload = {**body, "profile": profile}
    async with DashboardClient() as client:
        try:
            return await client._request(
                "POST", f"/api/mcp/servers?profile={profile}", json=payload
            )
        except DashboardError as exc:
            raise MCPError(f"添加 MCP 服务器失败: {exc}") from exc


async def update_server(profile: str, body: dict[str, Any]) -> dict:
    payload = {**body, "profile": profile}
    async with DashboardClient() as client:
        try:
            return await client._request(
                "PUT", f"/api/mcp/servers?profile={profile}", json=payload
            )
        except DashboardError as exc:
            raise MCPError(f"更新 MCP 服务器失败: {exc}") from exc


async def delete_server(profile: str, name: str) -> None:
    async with DashboardClient() as client:
        try:
            await client._request(
                "DELETE", f"/api/mcp/servers/{name}?profile={profile}"
            )
        except DashboardError as exc:
            raise MCPError(f"删除 MCP 服务器失败: {exc}") from exc


async def test_server(profile: str, name: str) -> dict:
    async with DashboardClient() as client:
        try:
            return await client._request(
                "POST", f"/api/mcp/servers/{name}/test?profile={profile}"
            )
        except DashboardError as exc:
            raise MCPError(f"测试 MCP 服务器失败: {exc}") from exc


async def set_enabled(profile: str, name: str, enabled: bool) -> dict:
    async with DashboardClient() as client:
        try:
            return await client._request(
                "PUT",
                f"/api/mcp/servers/{name}/enabled?profile={profile}",
                json={"enabled": enabled},
            )
        except DashboardError as exc:
            raise MCPError(f"切换 MCP 服务器状态失败: {exc}") from exc


async def catalog() -> list[dict]:
    """官方精选 MCP 目录（全局，与 profile 无关）。"""
    async with DashboardClient() as client:
        try:
            data = await client._request("GET", "/api/mcp/catalog")
        except DashboardError as exc:
            raise MCPError(f"读取 MCP 目录失败: {exc}") from exc
    if isinstance(data, dict):
        return data.get("entries") or data.get("catalog") or []
    return []
