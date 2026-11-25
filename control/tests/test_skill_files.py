"""Skill 详情接口 + reference/脚本下发测试（修复 5）。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


SKILL_WITH_FILES = {
    "name": "deploy-helper",
    "description": "部署助手",
    "content": "# Deploy\n按步骤部署。",
    "files": {
        "references/api.md": "# API 文档",
        "scripts/run.sh": "echo hello",
        "assets/config.json": "{}",
        "../evil.txt": "应被拒绝写入",
    },
}


async def _user_token(client, name="fileuser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def test_skill_detail_returns_content_and_files(client):
    """详情接口回填正文与 files（修复编辑页无法回填）。"""
    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_WITH_FILES)).json()["id"]

    r = await client.get(f"/api/skills/{sid}", headers=_h(tok))
    assert r.status_code == 200
    b = r.json()
    assert b["content"] == SKILL_WITH_FILES["content"]
    assert b["files"]["references/api.md"] == "# API 文档"
    assert "scripts/run.sh" in b["files"]


async def test_skill_files_keep_subdirs_and_block_traversal(monkeypatch, client, tmp_path):
    """reference/脚本按子目录落盘；路径穿越被拒绝。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_data_root", str(tmp_path))

    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_WITH_FILES)).json()["id"]
    r = await client.post(
        "/api/agents",
        headers=_h(tok),
        json={"slug": "filebot", "name": "f", "disabled_toolsets": []},  # 启用 terminal
    )
    aid = r.json()["id"]
    await client.put(f"/api/agents/{aid}/skills", headers=_h(tok), json={"skill_ids": [sid]})

    from app.hermes.skill_sync import profile_skills_dir

    base = profile_skills_dir("agent-u1-filebot", str(tmp_path)) / "deploy-helper"
    # 子目录保留
    assert (base / "references" / "api.md").is_file()
    assert (base / "scripts" / "run.sh").is_file()
    assert (base / "assets" / "config.json").is_file()
    # 路径穿越文件不能写到技能目录的父级
    assert not (base.parent / "evil.txt").exists()
    assert not (base / ".." / "evil.txt").exists()


async def test_scripts_kept_because_terminal_forced_on(monkeypatch, client, tmp_path):
    """绑定带脚本的 Skill 时，toolset_forcing 会强制开启 terminal，脚本必须保留。

    历史上 ``_sync_forced`` 在 ``_apply_profile`` 之后执行，导致 skill_sync
    按过期的 disabled_toolsets 误判 terminal 被禁用而剥离 scripts/，
    最终模型执行脚本时报 No such file or directory。
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_data_root", str(tmp_path))

    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_WITH_FILES)).json()["id"]
    await client.post("/api/agents", headers=_h(tok), json={"slug": "noterm", "name": "n"})
    aid = (await client.get("/api/agents", headers=_h(tok))).json()[0]["id"]
    await client.put(f"/api/agents/{aid}/skills", headers=_h(tok), json={"skill_ids": [sid]})

    from app.hermes.skill_sync import profile_skills_dir

    base = profile_skills_dir("agent-u1-noterm", str(tmp_path)) / "deploy-helper"
    # 带脚本的 Skill 会强制开启 terminal，脚本必须存在（否则技能无法工作）
    assert (base / "scripts" / "run.sh").is_file(), "terminal 被强制开启后脚本应保留"
    skill_md = (base / "SKILL.md").read_text(encoding="utf-8")
    # 不注入 requires_toolsets（会让 Hermes 隐藏技能，天气 skill 曾因此失效）
    assert "requires_toolsets" not in skill_md
    assert skill_md.count("---") == 2, "只应有一个 frontmatter 块"
    # 其他目录保留
    assert (base / "references" / "api.md").is_file()


async def test_scripts_kept_when_terminal_enabled(monkeypatch, client, tmp_path):
    """启用 terminal 的 Agent：脚本保留且不注入 requires_toolsets。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_data_root", str(tmp_path))

    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_WITH_FILES)).json()["id"]
    r = await client.post(
        "/api/agents",
        headers=_h(tok),
        json={"slug": "withterm", "name": "w", "disabled_toolsets": []},
    )
    aid = r.json()["id"]
    await client.put(f"/api/agents/{aid}/skills", headers=_h(tok), json={"skill_ids": [sid]})

    from app.hermes.skill_sync import profile_skills_dir

    base = profile_skills_dir("agent-u1-withterm", str(tmp_path)) / "deploy-helper"
    assert (base / "scripts" / "run.sh").is_file(), "启用 terminal 时脚本应保留"
    assert "requires_toolsets" not in (base / "SKILL.md").read_text(encoding="utf-8")
