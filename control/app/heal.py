"""启动自愈：把存量环境的 profile 技能状态对齐到当前设计。

历史问题（都会导致"脚本存在但模型找不到"或"技能选错"）：

1. 目录名用中文（如 ``天气查询``），在 POSIX locale 的容器里路径解析脆弱
   → 迁移为 ASCII slug（``weather-alert``），并删除旧目录。
2. ``_sync_forced`` 与 ``_apply_profile`` 顺序错误导致 terminal 被误判为禁用，
   脚本被剥离 → 重新下发一次，脚本即可恢复。
3. Hermes curator 自动沉淀的"影子技能"（如 ``weather-query``）与自定义
   Skill 语义重叠 → curator 关闭时归档它们，避免模型选错。

全部操作幂等：无问题时不产生任何写入。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings

logger = logging.getLogger(__name__)


async def heal_profiles(session: AsyncSession) -> dict:
    """对全部 Agent 做一次技能自愈。返回统计，异常不阻断启动。"""
    from .models import Agent, CustomSkill, AgentCustomSkill
    from .hermes import skill_sync
    from .hermes.toolset_forcing import compute_forced, apply_forced_toolsets

    stats = {"agents": 0, "resynced": 0, "errors": 0}
    settings = get_settings()
    data_root = settings.hermes_data_root

    agents = (await session.execute(select(Agent))).scalars().all()
    for agent in agents:
        stats["agents"] += 1
        try:
            bound = (
                await session.execute(
                    select(CustomSkill)
                    .join(
                        AgentCustomSkill,
                        AgentCustomSkill.skill_id == CustomSkill.id,
                    )
                    .where(AgentCustomSkill.agent_id == agent.id)
                )
            ).scalars().all()
            if not bound:
                continue

            # 先对齐强制工具集（terminal 等），再下发技能，
            # 否则 skill_sync 会按过期的 disabled_toolsets 剥离脚本。
            forced = await compute_forced(agent, session)
            apply_forced_toolsets(agent, forced)
            await session.flush()

            skill_sync.apply_custom_skills(
                agent.profile_name,
                data_root,
                list(bound),
                disabled_toolsets=list(agent.disabled_toolsets or []),
            )
            stats["resynced"] += 1
        except Exception as exc:  # 单个 Agent 失败不影响其他
            stats["errors"] += 1
            logger.warning("技能自愈失败 agent=%s: %s", agent.slug, exc)

    # curator 关闭时，归档它此前生成的影子技能
    if not settings.curator_enabled:
        stats["archived"] = await _archive_curator_skills(agents, data_root)

    return stats


async def _archive_curator_skills(agents: list, data_root: str) -> int:
    """把 curator 生成的技能（provenance=agent 且不在平台管理表）归档。

    只移动目录到 ``.archived/``，不删除内容，可人工恢复。
    """
    from pathlib import Path
    from .hermes.skills import list_skills
    from .hermes.skill_sync import profile_skills_dir, skill_slug

    archived = 0
    for agent in agents:
        try:
            available = await list_skills(agent.profile_name)
        except Exception:
            continue
        base = profile_skills_dir(agent.profile_name, data_root)
        managed_file = base / "_managed_by_gateway"
        managed: set[str] = set()
        if managed_file.is_file():
            managed = {
                line.strip()
                for line in managed_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        for s in available:
            name = s.get("name") or ""
            if not name:
                continue
            if (s.get("provenance") or "") != "agent":
                continue
            if name in managed:
                continue  # 平台下发的自定义技能，不动
            # 目录名可能是 ASCII slug（新）或原始 name（旧），两者都试
            from types import SimpleNamespace

            slug = skill_slug(SimpleNamespace(name=name, id=None, slug=None))
            candidates = [base / slug, base / name]
            src = next((c for c in candidates if c.is_dir()), None)
            if src is None:
                continue
            dst_dir = base / ".archived"
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            try:
                if dst.exists():
                    import shutil

                    shutil.rmtree(dst, ignore_errors=True)
                src.rename(dst)
                archived += 1
                logger.info(
                    "已归档 curator 技能 profile=%s name=%s",
                    agent.profile_name,
                    name,
                )
            except OSError as exc:
                logger.warning("归档 curator 技能失败 %s: %s", name, exc)
    return archived
