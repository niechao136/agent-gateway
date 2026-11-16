"""Agent 编排测试：CRUD + 权限隔离 + toolset 分级。

DashboardClient 由 conftest 的全局 fixture patch 成 FakeDashboard。
"""

import pytest

from app.hermes import toolsets as ts

pytestmark = pytest.mark.asyncio


def _admin_token():
    from app.security import create_access_token

    return create_access_token("admin", "admin")


async def _user_token(client, name="bob"):
    r = await client.post(
        "/api/auth/register", json={"username": name, "password": "password123"}
    )
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── toolset 分级（纯函数，最重要）──────────────────────────
def test_public_tier_disables_dangerous_toolsets():
    d = ts.disabled_toolsets_for("public")
    for must in ("terminal", "file", "browser", "code_execution", "delegation"):
        assert must in d, f"public 档位必须禁用 {must}"


def test_member_tier_keeps_memory():
    member = set(ts.disabled_toolsets_for("member"))
    public = set(ts.disabled_toolsets_for("public"))
    assert "memory" in public
    assert "memory" not in member
    assert "terminal" in member


def test_admin_tier_disables_nothing():
    assert ts.disabled_toolsets_for("admin") == ()


def test_unknown_tier_fails_closed():
    assert ts.disabled_toolsets_for("whatever") == ts.PUBLIC_DISABLED


def test_build_config_overrides_empty_for_admin():
    assert ts.build_agent_config_overrides("admin") == {}


def test_build_config_overrides_shape():
    cfg = ts.build_agent_config_overrides("public")
    assert "agent" in cfg
    assert "terminal" in cfg["agent"]["disabled_toolsets"]


# ── 权限隔离 ──────────────────────────────────────────────
async def test_admin_endpoints_reject_user_token(client):
    tok = await _user_token(client)
    assert (await client.get("/api/admin/agents", headers=_h(tok))).status_code == 403
    r = await client.post(
        "/api/admin/agents", headers=_h(tok), json={"slug": "x", "name": "X"}
    )
    assert r.status_code == 403


async def test_user_endpoint_rejects_admin_token(client):
    r = await client.get("/api/chat/agents", headers=_h(_admin_token()))
    assert r.status_code == 403


async def test_admin_endpoints_require_token(client):
    assert (await client.get("/api/admin/agents")).status_code == 401


# ── CRUD ──────────────────────────────────────────────────
async def test_create_agent_success(client):
    tok = _admin_token()
    r = await client.post(
        "/api/admin/agents",
        headers=_h(tok),
        json={
            "slug": "my-bot",
            "name": "我的机器人",
            "description": "测试用",
            "soul": "你是一个测试助手",
            "toolset_tier": "public",
        },
    )
    assert r.status_code == 201
    b = r.json()
    assert b["slug"] == "my-bot"
    assert b["profile_name"] == "agent-my-bot"
    assert b["profile_exists"] is True
    assert "terminal" in b["disabled_toolsets"]


async def test_create_agent_duplicate_slug(client):
    tok = _admin_token()
    body = {"slug": "dup", "name": "Dup"}
    assert (
        await client.post("/api/admin/agents", headers=_h(tok), json=body)
    ).status_code == 201
    assert (
        await client.post("/api/admin/agents", headers=_h(tok), json=body)
    ).status_code == 409


async def test_create_agent_invalid_slug(client):
    tok = _admin_token()
    for bad in ("UPPER", "has space", "a" * 100, "-leading", "default", "admin"):
        r = await client.post(
            "/api/admin/agents", headers=_h(tok), json={"slug": bad, "name": "X"}
        )
        assert r.status_code == 422, f"slug={bad!r} 应被拒绝，实际 {r.status_code}"


async def test_create_agent_rolls_back_when_profile_fails(client, monkeypatch):
    """profile 创建失败时，DB 不能留下孤儿记录。"""
    tok = _admin_token()
    import app.hermes.provisioner as prov

    async def boom(*a, **kw):
        raise prov.ProvisionError("dashboard 挂了")

    monkeypatch.setattr(prov, "create_agent_profile", boom)

    r = await client.post(
        "/api/admin/agents", headers=_h(tok), json={"slug": "orphan", "name": "Orphan"}
    )
    assert r.status_code == 502
    r2 = await client.get("/api/admin/agents", headers=_h(tok))
    assert all(a["slug"] != "orphan" for a in r2.json())


async def test_list_agents_admin(client):
    tok = _admin_token()
    await client.post(
        "/api/admin/agents", headers=_h(tok), json={"slug": "a1", "name": "A1"}
    )
    r = await client.get("/api/admin/agents", headers=_h(tok))
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_publish_makes_agent_visible_to_users(client):
    atok, utok = _admin_token(), await _user_token(client)
    await client.post(
        "/api/admin/agents", headers=_h(atok), json={"slug": "pub", "name": "Pub"}
    )
    assert (await client.get("/api/chat/agents", headers=_h(utok))).json() == []

    aid = (await client.get("/api/admin/agents", headers=_h(atok))).json()[0]["id"]
    assert (
        await client.post(f"/api/admin/agents/{aid}/publish", headers=_h(atok))
    ).status_code == 200

    r = await client.get("/api/chat/agents", headers=_h(utok))
    assert len(r.json()) == 1
    assert r.json()[0]["slug"] == "pub"


async def test_unpublish_hides_agent(client):
    atok, utok = _admin_token(), await _user_token(client)
    await client.post(
        "/api/admin/agents", headers=_h(atok), json={"slug": "u1", "name": "U1"}
    )
    aid = (await client.get("/api/admin/agents", headers=_h(atok))).json()[0]["id"]
    await client.post(f"/api/admin/agents/{aid}/publish", headers=_h(atok))
    await client.post(f"/api/admin/agents/{aid}/unpublish", headers=_h(atok))
    assert (await client.get("/api/chat/agents", headers=_h(utok))).json() == []


async def test_update_agent(client):
    tok = _admin_token()
    await client.post(
        "/api/admin/agents", headers=_h(tok), json={"slug": "u2", "name": "N1"}
    )
    aid = (await client.get("/api/admin/agents", headers=_h(tok))).json()[0]["id"]
    r = await client.patch(
        f"/api/admin/agents/{aid}",
        headers=_h(tok),
        json={"name": "N2", "soul": "新的人格"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "N2"


async def test_update_agent_tier_changes_disabled_list(client):
    tok = _admin_token()
    await client.post(
        "/api/admin/agents", headers=_h(tok), json={"slug": "t1", "name": "T1"}
    )
    aid = (await client.get("/api/admin/agents", headers=_h(tok))).json()[0]["id"]
    r = await client.patch(
        f"/api/admin/agents/{aid}", headers=_h(tok), json={"toolset_tier": "admin"}
    )
    assert r.status_code == 200
    assert r.json()["disabled_toolsets"] == []


async def test_delete_agent(client):
    tok = _admin_token()
    await client.post(
        "/api/admin/agents", headers=_h(tok), json={"slug": "d1", "name": "D1"}
    )
    aid = (await client.get("/api/admin/agents", headers=_h(tok))).json()[0]["id"]
    assert (
        await client.delete(f"/api/admin/agents/{aid}", headers=_h(tok))
    ).status_code == 204
    assert (await client.get("/api/admin/agents", headers=_h(tok))).json() == []


async def test_get_agent_404(client):
    r = await client.get("/api/admin/agents/9999", headers=_h(_admin_token()))
    assert r.status_code == 404
