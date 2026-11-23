"""工具集强制启用：资源绑定与 Hermes toolset 开关的联动。

背景（生产实测）：
- Hermes 工具集的真实启停由 profile config.yaml 的 `platform_toolsets.api_server`
  控制（opt-in），`agent.disabled_toolsets` 只是本平台前端开关；两者必须一致。
- A2A 端点 / Skill 绑定后，若不启用对应 toolset，模型看不到工具，绑定形同虚设。

规则：
- 绑定 A2A 端点 → 强制 a2a
- 绑定任意 Skill（内置或自定义） → 强制 skills
- 绑定带 scripts 的 Skill → 额外强制 terminal
- 解绑后只解除强制（不再写入），**不主动关闭**工具集
"""

from __future__ import annotations

import logging

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    Agent,
    AgentA2AEndpoint,
    AgentBuiltinSkill,
    AgentCustomSkill,
    CustomSkill,
)
from .a2a import _atomic_write
from .provisioner import ProvisionError, profile_config_path

logger = logging.getLogger(__name__)

# api_server 平台默认复合工具集（覆盖时必须带上，否则丢默认工具）
API_SERVER_DEFAULT = "hermes-api_server"

# 内置 skill 中带脚本的名称前缀（hermes 内置 skill 的 scripts/ 由 hermes 自管，
# 这里只处理自定义 skill 的脚本判定；内置一律只强制 skills）
SCRIPT_TOOLSET = "terminal"


async def compute_forced(agent: Agent, session: AsyncSession) -> list[str]:
    """根据当前绑定计算必须启用的 toolset 列表。"""
    forced: set[str] = set()

    n_a2a = await session.scalar(
        select(AgentA2AEndpoint.id).where(AgentA2AEndpoint.agent_id == agent.id).limit(1)
    )
    if n_a2a is not None:
        forced.add("a2a")

    n_skill = await session.scalar(
        select(AgentCustomSkill.id).where(AgentCustomSkill.agent_id == agent.id).limit(1)
    )
    n_builtin = await session.scalar(
        select(AgentBuiltinSkill.agent_id).where(AgentBuiltinSkill.agent_id == agent.id).limit(1)
    )
    if n_skill is not None or n_builtin is not None:
        forced.add("skills")

    # 自定义 skill 带 scripts/ 目录 → 需要 terminal 执行
    rows = (
        await session.execute(
            select(CustomSkill.files)
            .join(AgentCustomSkill, AgentCustomSkill.skill_id == CustomSkill.id)
            .where(AgentCustomSkill.agent_id == agent.id)
        )
    ).scalars().all()
    for files in rows:
        if isinstance(files, dict) and any(str(k).startswith("scripts/") for k in files):
            forced.add(SCRIPT_TOOLSET)
            break

    return sorted(forced)


def apply_forced_toolsets(agent: Agent, forced: list[str]) -> dict:
    """把强制启用的 toolset 落到 DB（调用方负责 commit）与 profile config.yaml。

    返回写入摘要；profile 未就绪时降级为警告（不阻断绑定操作）。
    """
    from .toolsets import normalize_disabled

    # 1) DB：从 disabled 中移除 forced（自动开启）
    disabled = normalize_disabled(agent.disabled_toolsets or [])
    agent.disabled_toolsets = [d for d in disabled if d not in forced]

    # 2) profile config.yaml：disabled + platform_toolsets.api_server
    settings = get_settings()
    path = profile_config_path(agent.profile_name, settings.hermes_data_root)
    if not path.is_file():
        logger.warning("写入强制 toolset 失败：profile config.yaml 不存在: %s", path)
        return {"forced": forced, "written": False}

    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        return {"forced": forced, "written": False}

    section = cfg.get("agent")
    if not isinstance(section, dict):
        section = {}
    if agent.disabled_toolsets:
        section["disabled_toolsets"] = agent.disabled_toolsets
    else:
        section.pop("disabled_toolsets", None)
    if section:
        cfg["agent"] = section
    else:
        cfg.pop("agent", None)

    if forced:
        pts = cfg.get("platform_toolsets")
        if not isinstance(pts, dict):
            pts = {}
        apis = list(pts.get("api_server") or [API_SERVER_DEFAULT])
        if API_SERVER_DEFAULT not in apis:
            apis.insert(0, API_SERVER_DEFAULT)
        for f in forced:
            if f not in apis:
                apis.append(f)
        pts["api_server"] = apis
        cfg["platform_toolsets"] = pts
    # 注意：forced 为空时不删除已启用的 toolset（解绑只解除强制，不主动关闭）

    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    logger.info("强制 toolset 已写入 %s: forced=%s", path, forced)
    return {"forced": forced, "written": True}
