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

    stats = {"agents": 0, "resynced": 0, "errors": 0, "toolsets": 0}
    settings = get_settings()
    data_root = settings.hermes_data_root

    agents = (await session.execute(select(Agent))).scalars().all()
    for agent in agents:
        stats["agents"] += 1
        try:
            # 1) 强制工具集自愈：对所有 Agent 生效（不只是绑定了 Skill 的）。
            # 绑定 A2A 但没绑 Skill 的 Agent（如 person）此前被 `if not bound: continue`
            # 跳过，导致 a2a 工具集没被自动启用，A2A 调用失效。
            forced = await compute_forced(agent, session)
            if forced:
                apply_forced_toolsets(agent, forced)
                await session.flush()
                stats["toolsets"] += 1

            # 2) 自定义 Skill 重新下发：仅对绑定了 Skill 的 Agent 执行。
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

            # terminal 等强制工具集已在上面对齐，skill_sync 不会误剥离脚本。
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

        # 迁移历史误归档：早期版本把影子技能移到 skills/.archived，
        # 但 Hermes 仍会扫描到它。这里搬到 skills/ 之外。
        legacy_arch = base / ".archived"
        if legacy_arch.is_dir():
            outside = base.parent / ".archived-skills"
            outside.mkdir(parents=True, exist_ok=True)
            import shutil

            for child in list(legacy_arch.iterdir()):
                tgt = outside / child.name
                try:
                    if tgt.exists():
                        shutil.rmtree(tgt, ignore_errors=True)
                    child.rename(tgt)
                    archived += 1
                except OSError:
                    pass
            shutil.rmtree(legacy_arch, ignore_errors=True)

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
            # 目录名可能是 ASCII slug（新）或原始 name（旧），两者都试
            from types import SimpleNamespace

            slug = skill_slug(SimpleNamespace(name=name, id=None, slug=None))
            candidates = [base / slug, base / name]
            src = next((c for c in candidates if c.is_dir()), None)
            if src is None:
                continue
            # 关键：平台下发的自定义技能目录也在这个目录里，必须按**目录名**
            # 判断归属，不能只按 Hermes 上报的 name。历史版本把 SKILL.md 的
            # name 写成了中文展示名，导致 name 与 manifest 里的 slug 对不上，
            # 仅凭 name 判断会把真正的自定义技能误归档（表现为"技能莫名消失"）。
            if src.name in managed or name in managed:
                continue
            # 归档目录必须在 skills/ 之外：Hermes 会扫描 skills/ 下所有子目录，
            # 放在 skills/.archived 里仍然会被当成可用技能。
            dst_dir = base.parent / ".archived-skills"
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
