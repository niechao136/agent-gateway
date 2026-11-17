"""Toolset 开关：disabled_toolsets 列表的默认值与校验。

这是**安全核心**（SPEC §4.4 / §14、SPEC-v2 决策 5）。

实测确认：`/v1` 走的是 `api_server` 平台预设，它默认**保留 terminal / file /
browser / code_execution**。不显式禁掉，公开用户就拿到了容器 shell。

硬约束（实测）：hermes 内置工具只能按 toolset 整体开关，无法单工具禁用
（`hermes tools disable web_search` 报 Unknown toolset）。

v2：tier 三档废除，Agent 直接存 disabled_toolsets 列表；
新建 Agent 默认 = 只读助手（只保留 web / clarify / vision / image_generation）。
"""

from __future__ import annotations

# 新建 Agent 的默认禁用集（只读助手）：
# 除白名单外全部禁用，宁可太严不能太松。
DEFAULT_DISABLED: tuple[str, ...] = (
    "terminal",        # 容器 shell —— 最高危
    "file",            # 任意文件读写
    "browser",         # 浏览器自动化，可操作登录态
    "code_execution",  # execute_code
    "computer_use",    # 桌面控制
    "delegation",      # 派生子 agent，可绕过本层限制
    "cronjob",         # 持久化定时任务
    "skills",          # skill_manage 可自写技能
    "memory",          # 跨会话记忆，有泄漏风险
    "subagents",       # 子 agent 编排
    "a2a",             # agent 间调用
)

# 允许保留的 toolset 白名单（用于校验请求里的 disabled_toolsets 之外，
# 也用于前端展示"这个 toolset 里有哪些工具"）
KNOWN_TOOLSETS: frozenset[str] = frozenset(
    {
        "web",
        "clarify",
        "vision",
        "image_generation",
        "memory",
        "session_search",
        "skills",
        "cronjob",
        "delegation",
        "subagents",
        "a2a",
        "terminal",
        "file",
        "browser",
        "code_execution",
        "computer_use",
    }
)


def normalize_disabled(disabled: list[str] | tuple[str, ...] | None) -> list[str]:
    """清洗请求中的 disabled_toolsets：去未知项、去重、排序。

    安全取向：未知 toolset 不报错而是丢弃（避免 hermes 升级新增 toolset
    导致旧数据写入失败），但永远不"自动放开"任何东西。
    """
    if not disabled:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for name in disabled:
        name = (name or "").strip()
        if name and name in KNOWN_TOOLSETS and name not in seen:
            seen.add(name)
            out.append(name)
    return sorted(out)


def default_disabled() -> list[str]:
    """新建 Agent 的默认禁用集（只读助手）。"""
    return sorted(DEFAULT_DISABLED)
