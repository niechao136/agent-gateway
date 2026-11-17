"""toolset catalog：toolset → 内含工具 的只读展示数据（批次 2）。

数据来源（按用户规则）：
1. hermes dashboard 有 catalog 端点 → 转发
2. 无端点（404）→ 降级为静态表（来自 SPEC.md 实测记录）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..hermes.client import DashboardClient, DashboardError
from ..security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/toolsets", tags=["toolsets"])

# 静态降级表（SPEC.md §4.4 实测）：risk 高/中/低 用于前端着色
STATIC_CATALOG: list[dict] = [
    {"name": "web", "risk": "low", "tools": ["web_search", "web_fetch", "web_news"]},
    {"name": "clarify", "risk": "low", "tools": ["clarify"]},
    {"name": "vision", "risk": "low", "tools": ["vision"]},
    {"name": "image_generation", "risk": "low", "tools": ["image_generate"]},
    {"name": "memory", "risk": "medium", "tools": ["memory_save", "memory_search"]},
    {"name": "session_search", "risk": "medium", "tools": ["session_search"]},
    {"name": "skills", "risk": "medium", "tools": ["skill_list", "skill_use", "skill_manage"]},
    {"name": "cronjob", "risk": "medium", "tools": ["cronjob_create", "cronjob_list", "cronjob_delete"]},
    {"name": "delegation", "risk": "high", "tools": ["delegate"]},
    {"name": "subagents", "risk": "high", "tools": ["spawn_subagent", "list_subagents"]},
    {"name": "a2a", "risk": "high", "tools": ["a2a_call", "a2a_list"]},
    {"name": "terminal", "risk": "high", "tools": ["shell", "process_list"]},
    {"name": "file", "risk": "high", "tools": ["file_read", "file_write", "file_ls"]},
    {"name": "browser", "risk": "high", "tools": ["browser_navigate", "browser_click", "browser_screenshot"]},
    {"name": "code_execution", "risk": "high", "tools": ["execute_code"]},
    {"name": "computer_use", "risk": "high", "tools": ["computer_screenshot", "computer_click", "computer_type"]},
]


@router.get("")
async def toolset_catalog(_: CurrentUser) -> dict:
    """toolset → 内含工具（只读展示；硬约束：内置工具只能按 toolset 整体开关）。"""
    try:
        async with DashboardClient() as client:
            data = await client.try_endpoint("GET", "/api/toolsets/catalog")
            if data is not None:
                items = data if isinstance(data, list) else data.get("toolsets", [])
                return {"source": "dashboard", "toolsets": items}
    except DashboardError as exc:
        logger.warning("dashboard catalog 拉取失败，降级静态表: %s", exc)
        return {"source": "static", "error": str(exc), "toolsets": STATIC_CATALOG}
    return {"source": "static", "toolsets": STATIC_CATALOG}
