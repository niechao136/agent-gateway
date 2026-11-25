"""技能目录 slug 单元测试。

目录名必须是 ASCII：中文名在 POSIX locale 容器里路径解析脆弱，
且 Hermes 注入 skill_dir 后模型拼路径也可能出错。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.hermes.skill_sync import skill_slug


def _s(name: str, sid: int | None = 1, slug: str | None = None):
    return SimpleNamespace(name=name, id=sid, slug=slug)


def test_slug_ascii_name_unchanged() -> None:
    assert skill_slug(_s("weather-alert")) == "weather-alert"


def test_slug_chinese_name_becomes_ascii() -> None:
    """中文名不能直接做目录名。"""
    slug = skill_slug(_s("天气查询", sid=2))
    assert slug.isascii(), f"应为 ASCII，实际 {slug!r}"
    assert slug, "slug 不能为空"
    assert "/" not in slug and " " not in slug


def test_slug_stable_and_unique_per_name() -> None:
    """同名稳定（幂等），不同名不冲突。"""
    assert skill_slug(_s("天气查询", sid=2)) == skill_slug(_s("天气查询", sid=2))
    assert skill_slug(_s("天气查询", sid=2)) != skill_slug(_s("文本分析", sid=3))


def test_slug_prefers_persisted_slug() -> None:
    """DB 里存了 slug 时优先使用，保证改名后目录不变。"""
    assert skill_slug(_s("天气查询", sid=2, slug="weather-alert")) == "weather-alert"


def test_slug_sanitizes_path_separators() -> None:
    for bad in ("a/b", "a b", "../etc", "x\\y"):
        slug = skill_slug(_s(bad))
        assert "/" not in slug and "\\" not in slug and " " not in slug
        assert not slug.startswith(".")
