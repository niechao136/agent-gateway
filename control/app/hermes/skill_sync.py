"""自定义 Skill 落地：写入 profile 的 skills/ 目录（直写，dashboard 无此 API）。

目录约定（hermes）：<data_root>/profiles/<profile>/skills/<name>/SKILL.md
绑定变更 / 内容变更 / 删除时全量重写该 profile 的自定义技能目录。

内置 Skill 走 dashboard API（GET /api/skills、PUT /api/skills/toggle），
见 hermes/skills.py —— 两者按「有 API 用 API，没有则直写」分工。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .a2a import _atomic_write

logger = logging.getLogger(__name__)


class SkillSyncError(Exception):
    pass


def profile_skills_dir(profile: str, data_root: str) -> Path:
    root = Path(data_root)
    if profile == "default":
        return root / "skills"
    return root / "profiles" / profile / "skills"


def _skill_md(name: str, description: str | None, content: str) -> str:
    """生成 SKILL.md（含 frontmatter）。"""
    desc = (description or "").replace('"', "'")
    return f"---\nname: {name}\ndescription: \"{desc}\"\n---\n\n{content}\n"


def apply_custom_skills(
    profile: str,
    data_root: str,
    skills: list,
) -> dict:
    """把自定义技能列表全量写入 profile 的 skills/ 目录。

    skills: CustomSkill ORM 对象（或鸭子类型：name/description/content/files）。
    全量语义：先清除本控制层管理的目录（_managed 标记），再写入新集合，
    不碰非本控制层写入的目录（如内置技能）。
    """
    base = profile_skills_dir(profile, data_root)
    managed = base / "_managed_by_gateway"
    removed = 0
    written = 0

    # 清除旧托管技能：读 manifest
    old_names: set[str] = set()
    if managed.is_file():
        old_names = {
            line.strip() for line in managed.read_text(encoding="utf-8").splitlines() if line.strip()
        }
        for name in old_names:
            d = base / name
            if d.is_dir():
                import shutil

                shutil.rmtree(d, ignore_errors=True)
                removed += 1

    new_names: list[str] = []
    for s in skills:
        name = s.name
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / "SKILL.md", _skill_md(name, s.description, s.content))
        for fname, fcontent in (s.files or {}).items():
            # 防路径穿越
            safe = Path(fname).name
            _atomic_write(d / safe, str(fcontent))
        new_names.append(name)
        written += 1

    # 更新 manifest（无托管技能时移除标记文件）
    if new_names:
        _atomic_write(managed, "\n".join(new_names) + "\n")
    else:
        managed.unlink(missing_ok=True)

    logger.info("profile %s 自定义技能同步：写 %d 删 %d", profile, written, removed)
    return {"written": written, "removed": removed, "dir": str(base)}


def remove_skill_dir(profile: str, data_root: str, name: str) -> None:
    """删除单个技能目录（删除自定义技能时调用）。"""
    import shutil

    d = profile_skills_dir(profile, data_root) / name
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        logger.info("已删除技能目录 %s", d)
