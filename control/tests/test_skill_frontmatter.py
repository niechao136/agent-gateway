"""SKILL.md 生成的契约测试。

关键约定：Hermes 用 frontmatter 的 ``name`` 作为技能**身份**
（``tools/skills_tool.py: frontmatter.get("name", skill_md.parent.name)``）。
若写成中文展示名，Hermes 上报的 name 就和平台托管名单里的 ASCII slug
对不上，该技能会被误判成 curator 自动生成的"影子技能"——表现为
curator 卡片里冒出中文技能、且删不掉。所以 name 必须是 slug，
中文名放 display_name。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.hermes.skill_sync import _skill_md, skill_slug


def _skill(name: str, sid: int = 2, display_name: str | None = None, content: str = "正文"):
    return SimpleNamespace(
        name=name,
        id=sid,
        slug=None,
        display_name=display_name,
        description="测试技能",
        content=content,
        files=None,
    )


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n"), "SKILL.md 必须以 frontmatter 开头"
    end = text.index("\n---\n", 4)
    out: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def test_frontmatter_name_is_ascii_slug() -> None:
    """name 必须是 ASCII slug，不能是中文展示名。"""
    s = _skill("天气查询", sid=2, display_name="天气查询")
    fm = _frontmatter(_skill_md(s, strip_scripts=False))
    assert fm["name"] == skill_slug(s)
    assert fm["name"].isascii()
    assert fm["name"] != "天气查询"


def test_display_name_preserved_in_frontmatter() -> None:
    """中文展示名仍要保留下来（供 UI / 模型阅读）。"""
    s = _skill("天气查询", sid=2, display_name="天气查询")
    fm = _frontmatter(_skill_md(s, strip_scripts=False))
    assert fm.get("display_name") == "天气查询"


def test_ascii_name_no_redundant_display_name() -> None:
    """名字本身就是 ASCII 且等于展示名时，不写冗余 display_name。"""
    s = _skill("weather-alert", sid=3, display_name="weather-alert")
    fm = _frontmatter(_skill_md(s, strip_scripts=False))
    assert fm["name"] == "weather-alert"
    assert "display_name" not in fm


def test_single_frontmatter_block() -> None:
    """只能有一个 frontmatter，否则 Hermes 解析会错位。"""
    s = _skill("天气查询", sid=2, display_name="天气查询", content="---\nname: 旧\n---\n正文")
    text = _skill_md(s, strip_scripts=False)
    # 正文里自带的 frontmatter 必须被剥掉，不能出现第二个 name:
    name_lines = [ln for ln in text.splitlines() if ln.startswith("name:")]
    assert len(name_lines) == 1, f"只能有一个 name 行，实际 {name_lines}"
    assert name_lines[0] == f"name: {skill_slug(s)}"
