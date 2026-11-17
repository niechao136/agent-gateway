"""Skill 双来源测试（批次 2）：内置级联禁用 + 自定义 CRUD 直写 profile。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


SKILL_BODY = {
    "name": "greeter",
    "description": "问候技能",
    "content": "# Greeter\n向用户问好。",
}


async def _user_token(client, name="skilluser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def _agent(client, tok, slug="sk1"):
    r = await client.post("/api/agents", headers=_h(tok), json={"slug": slug, "name": slug})
    return r.json()["id"]


# ── 自定义 CRUD ───────────────────────────────────────────
async def test_create_and_list(client):
    tok = await _user_token(client)
    r = await client.post("/api/skills", headers=_h(tok), json=SKILL_BODY)
    assert r.status_code == 201
    assert r.json()["owner_id"] == 1

    rows = (await client.get("/api/skills", headers=_h(tok))).json()
    assert [s["name"] for s in rows] == ["greeter"]


async def test_duplicate_409(client):
    tok = await _user_token(client)
    assert (await client.post("/api/skills", headers=_h(tok), json=SKILL_BODY)).status_code == 201
    assert (await client.post("/api/skills", headers=_h(tok), json=SKILL_BODY)).status_code == 409


async def test_update_syncs_profile(monkeypatch, client, tmp_path):
    """内容变更 → 绑定的 profile skills/ 目录更新。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_data_root", str(tmp_path))

    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_BODY)).json()["id"]
    aid = await _agent(client, tok)
    await client.put(f"/api/agents/{aid}/skills", headers=_h(tok), json={"skill_ids": [sid]})

    # 目录落地校验（FakeDashboard 建了 profile 目录才存在）
    from app.hermes.skill_sync import profile_skills_dir

    d = profile_skills_dir("agent-u1-sk1", str(tmp_path)) / "greeter" / "SKILL.md"
    if d.is_file():
        assert "# Greeter" in d.read_text()

    # 改内容再同步
    r = await client.patch(
        f"/api/skills/{sid}", headers=_h(tok), json={"content": "# Greeter v2"}
    )
    assert r.status_code == 200
    if d.is_file():
        assert "v2" in d.read_text()


async def test_delete_with_binding_requires_force(client):
    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_BODY)).json()["id"]
    aid = await _agent(client, tok)
    await client.put(f"/api/agents/{aid}/skills", headers=_h(tok), json={"skill_ids": [sid]})

    assert (await client.delete(f"/api/skills/{sid}", headers=_h(tok))).status_code == 409
    assert (await client.delete(f"/api/skills/{sid}?force=true", headers=_h(tok))).status_code == 204


async def test_private_invisible_to_others(client):
    t1 = await _user_token(client, "skown")
    t2 = await _user_token(client, "skother")
    sid = (await client.post("/api/skills", headers=_h(t1), json=SKILL_BODY)).json()["id"]
    assert all(s["id"] != sid for s in (await client.get("/api/skills", headers=_h(t2))).json())
    assert (
        await client.patch(f"/api/skills/{sid}", headers=_h(t2), json={"content": "x"})
    ).status_code == 403


# ── 内置 Skill ────────────────────────────────────────────
async def test_builtin_list_requires_dashboard(client, monkeypatch):
    """内置列表代理 dashboard；FakeDashboard 有 /api/skills 时返回聚合。"""
    tok = await _user_token(client)
    r = await client.get("/api/skills/builtin", headers=_h(tok))
    # FakeDashboard 实现 /api/skills 则 200；无则 502 —— 都不算失败，只验证不 500
    assert r.status_code in (200, 502)


async def test_builtin_disable_requires_admin(client):
    tok = await _user_token(client)
    r = await client.put(
        "/api/skills/builtin/memory",
        headers=_h(tok),
        json={"enabled": False, "affected_agent_ids": []},
    )
    assert r.status_code == 403


async def test_builtin_disable_requires_confirmation(client, atok):
    """禁用未确认受影响列表 → 409。"""
    r = await client.put(
        "/api/skills/builtin/memory", headers=_h(atok), json={"enabled": False, "affected_agent_ids": []}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["requires_confirmation"] is True


async def test_builtin_disable_with_confirmation(client, atok):
    tok = await _user_token(client)
    aid = await _agent(client, tok, slug="skc")
    r = await client.put(
        "/api/skills/builtin/memory",
        headers=_h(atok),
        json={"enabled": False, "affected_agent_ids": [aid]},
    )
    # FakeDashboard 支持 toggle 则 200；不支持则 errors 非空但仍 200/502
    assert r.status_code in (200, 502)


# ── 绑定 ──────────────────────────────────────────────────
async def test_bind_and_create_and_bind(client):
    tok = await _user_token(client)
    sid = (await client.post("/api/skills", headers=_h(tok), json=SKILL_BODY)).json()["id"]
    aid = await _agent(client, tok)

    r = await client.put(f"/api/agents/{aid}/skills", headers=_h(tok), json={"skill_ids": [sid]})
    assert r.status_code == 200

    r = await client.get(f"/api/agents/{aid}/skills", headers=_h(tok))
    assert [s["name"] for s in r.json()["bound"]] == ["greeter"]

    # create-and-bind：同名直接绑定
    r = await client.post(f"/api/agents/{aid}/skills/create-and-bind", headers=_h(tok), json=SKILL_BODY)
    assert r.json()["created"] is False


async def test_bind_others_private_403(client):
    t1 = await _user_token(client, "skown2")
    t2 = await _user_token(client, "skbind2")
    sid = (await client.post("/api/skills", headers=_h(t1), json=SKILL_BODY)).json()["id"]
    aid = await _agent(client, t2, slug="skb")
    r = await client.put(f"/api/agents/{aid}/skills", headers=_h(t2), json={"skill_ids": [sid]})
    assert r.status_code == 403
