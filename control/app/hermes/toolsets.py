"""Toolset 分级：tier → disabled_toolsets 的映射与写入。

这是**安全核心**（SPEC §4.4 / §14）。

实测确认：`/v1` 走的是 `api_server` 平台预设，它默认**保留 terminal / file /
browser / code_execution**。不显式禁掉，公开用户就拿到了容器 shell。

实测 `/v1/toolsets` 的默认返回（未配置 disabled_toolsets 时）：
    web            enabled=true
    browser        enabled=true   ← 危险
    terminal       enabled=true   ← 危险
    file           enabled=true   ← 危险
    code_execution enabled=true   ← 危险
"""

from __future__ import annotations

from ..models import ToolsetTier

# ── 各档位要禁掉的 toolset ────────────────────────────────
# 依据工具的实际危险度，而不是名字好听与否。
PUBLIC_DISABLED: tuple[str, ...] = (
    "terminal",        # 容器 shell —— 最高危
    "file",            # 任意文件读写
    "browser",         # 浏览器自动化，可操作登录态
    "code_execution",  # execute_code
    "computer_use",    # 桌面控制
    "delegation",      # 派生子 agent，可绕过本层限制
    "cronjob",         # 持久化定时任务
    "skills",          # skill_manage 可自写技能
    "memory",          # 跨会话记忆，有泄漏风险
)

MEMBER_DISABLED: tuple[str, ...] = tuple(
    t for t in PUBLIC_DISABLED if t not in ("memory",)
)

ADMIN_DISABLED: tuple[str, ...] = ()

# 公开档位允许的 toolset（白名单式校验用）
PUBLIC_ALLOWED: frozenset[str] = frozenset({"web", "clarify", "vision", "image_generation"})


def disabled_toolsets_for(tier: str) -> tuple[str, ...]:
    """按 tier 返回应禁用的 toolset 列表。未知 tier 按最严格处理（fail closed）。"""
    match tier:
        case ToolsetTier.PUBLIC:
            return PUBLIC_DISABLED
        case ToolsetTier.MEMBER:
            return MEMBER_DISABLED
        case ToolsetTier.ADMIN:
            return ADMIN_DISABLED
        case _:
            # 未知档位 → 按 public 处理，绝不放开
            return PUBLIC_DISABLED


def build_agent_config_overrides(tier: str) -> dict:
    """生成要写入 profile config.yaml 的 agent 段。

    hermes 的 `agent.disabled_toolsets` 在平台预设**之后**应用，
    所以列在这里的一定被移除（configuration.md:1035-1050）。
    """
    disabled = disabled_toolsets_for(tier)
    if not disabled:
        return {}
    return {"agent": {"disabled_toolsets": list(disabled)}}
