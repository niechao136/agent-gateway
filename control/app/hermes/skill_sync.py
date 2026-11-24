"""自定义 Skill 落地：写入 profile 的 skills/ 目录（直写，dashboard 无此 API）。

目录约定（SPEC 6.2）：<data_root>/profiles/<profile>/skills/<name>/
    ├── SKILL.md
    ├── references/  ── 参考文档（白名单前移：写入时过滤，见 SPEC 6.3）
    ├── templates/
    ├── scripts/     ── 可执行脚本（需 terminal，见 SPEC 6.4/6.5）
    └── assets/

下发逻辑（SPEC 6.5）：
- 技能无 scripts/ → 原样下发
- 技能含 scripts/ 且该 Agent 禁用了 terminal → 剥离 scripts/，
  并在 SKILL.md frontmatter 注入 requires_toolsets: [terminal]，
  使 hermes 自动隐藏该技能（避免断链/行为不一致）
- 技能含 scripts/ 且 terminal 可用 → 原样下发
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .a2a import _atomic_write

logger = logging.getLogger(__name__)

# 允许写入的子目录（白名单前移，SPEC 6.3）
_ALLOWED_DIRS = {"references", "templates", "scripts", "assets"}


class SkillSyncError(Exception):
    pass


def profile_skills_dir(profile: str, data_root: str) -> Path:
    root = Path(data_root)
    if profile == "default":
        return root / "skills"
    return root / "profiles" / profile / "skills"


def _inject_requires_terminal(skill_md: str) -> str:
    """在 SKILL.md frontmatter 注入 requires_toolsets: [terminal]。

    frontmatter 形如：
        ---
        name: xxx
        description: "..."
        ---
    注入后：
        ---
        name: xxx
        description: "..."
        metadata:
          hermes:
            requires_toolsets: [terminal]
        ---
    已有 metadata.hermes 时追加，避免重复。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_md, re.DOTALL)
    if not m:
        # 无 frontmatter：补一个最小的
        head = "---\nmetadata:\n  hermes:\n    requires_toolsets: [terminal]\n---\n\n"
        return head + skill_md

    fm = m.group(1)
    body = skill_md[m.end():]
    if "requires_toolsets" in fm:
        return skill_md  # 已声明，幂等
    # 已有 metadata: 块则在其 hermes 下追加；否则新建
    if re.search(r"^metadata:\s*$", fm, re.MULTILINE):
        if re.search(r"^\s+hermes:\s*$", fm, re.MULTILINE):
            fm = re.sub(
                r"(^\s+hermes:\s*$)",
                r"\1\n    requires_toolsets: [terminal]",
                fm,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            fm = re.sub(
                r"(^metadata:\s*$)",
                r"\1\n  hermes:\n    requires_toolsets: [terminal]",
                fm,
                count=1,
                flags=re.MULTILINE,
            )
    else:
        fm = fm + "\nmetadata:\n  hermes:\n    requires_toolsets: [terminal]"
    return f"---\n{fm}\n---\n{body}"


def _skill_md(skill, *, strip_scripts: bool) -> str:
    desc = (skill.description or "").replace('"', "'")
    # 不再注入重复的 hermermes frontmatter：toolset_forcing 会在绑定带脚本
    # 的 skill 时强制开启 terminal 并禁止关闭，脚本始终可用；注入
    # requires_toolsets 会让 Hermes 隐藏技能且产生两个 --- frontmatter 块。
    return f"---\nname: {skill.name}\ndescription: \"{desc}\"\n---\n\n{skill.content}\n"


def _safe_rel_path(fname: str) -> Path | None:
    """把文件清单里的相对路径限制在白名单子目录内，防路径穿越。"""
    p = Path(fname)
    parts = p.parts
    if len(parts) == 1:
        # 根级文件（非 SKILL.md，如 README）——忽略
        return None
    top = parts[0]
    if top not in _ALLOWED_DIRS:
        return None
    if ".." in parts or any(str(x).startswith("/") for x in parts):
        return None  # 防路径穿越
    return Path(*parts)


def apply_custom_skills(
    profile: str,
    data_root: str,
    skills: list,
    *,
    disabled_toolsets: list[str] | None = None,
) -> dict:
    """把自定义技能列表全量写入 profile 的 skills/ 目录。

    skills: CustomSkill ORM 对象（name/description/content/files）。
    disabled_toolsets: 该 Agent 禁用的 toolset 列表；含 terminal 时剥离 scripts/。
    """
    base = profile_skills_dir(profile, data_root)
    managed = base / "_managed_by_gateway"
    terminal_disabled = "terminal" in (disabled_toolsets or [])
    removed = 0
    written = 0
    stripped = 0

    # 清除旧托管技能（读 manifest）
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
        files = s.files or {}
        has_scripts = any(
            (f.startswith("scripts/") or "/scripts/" in f) for f in files.keys()
        )
        strip_scripts = has_scripts and terminal_disabled
        if strip_scripts:
            stripped += 1

        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / "SKILL.md", _skill_md(s, strip_scripts=strip_scripts))

        for fname, fcontent in files.items():
            rel = _safe_rel_path(fname)
            if rel is None:
                continue
            if strip_scripts and rel.parts[0] == "scripts":
                continue  # SPEC 6.5：剥离脚本
            target = d / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, str(fcontent))

        new_names.append(name)
        written += 1

    if new_names:
        _atomic_write(managed, "\n".join(new_names) + "\n")
    else:
        managed.unlink(missing_ok=True)

    logger.info(
        "profile %s 自定义技能同步：写 %d 删 %d 剥离脚本 %d (terminal_disabled=%s)",
        profile, written, removed, stripped, terminal_disabled,
    )
    return {
        "written": written,
        "removed": removed,
        "scripts_stripped": stripped,
        "dir": str(base),
    }


def remove_skill_dir(profile: str, data_root: str, name: str) -> None:
    import shutil

    d = profile_skills_dir(profile, data_root) / name
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        logger.info("已删除技能目录 %s", d)
