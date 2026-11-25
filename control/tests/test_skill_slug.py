"""技能目录 slug 与 curator 相关单元测试。"""
from __future__ import annotations

from app.hermes.skill_sync import skill_slug


def test_slug_ascii_name_unchanged() -> None:
    assert skill_slug("weather-alert") == "weather-alert"


def test_slug_chinese_name_becomes_ascii() -> None:
    """中文名不能直接做目录名（POSIX locale 下路径解析脆弱）。"""
    slug = skill_slug("天气查询")
    assert slug.isascii(), f"应为 ASCII，实际 {slug!r}"
    assert slug, "slug 不能为空"
    assert "/" not in slug and " " not in slug


def test_slug_stable_and_unique_per_name() -> None:
    """同名稳定（幂等），不同名不冲突。"""
    assert skill_slug("天气查询") == skill_slug("天气查询")
    assert skill_slug("天气查询") != skill_slug("文本分析")


def test_slug_sanitizes_path_separators() -> None:
    for bad in ("a/b", "a b", "../etc", "x\\y"):
        slug = skill_slug(bad)
        assert "/" not in slug and "\\" not in slug and " " not in slug
        assert not slug.startswith(".")
