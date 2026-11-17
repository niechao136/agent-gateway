"""Agent 编排测试：CRUD + 归属权限 + disabled_toolsets（v2 批次 1）。

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
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── toolsets（纯函数，最重要）──────────────────────────────
def test_default_disables_dangerous_toolsets():
    d = ts.default_disabled()
    for must in ("terminal", "file", "browser", "code_execution", "delegation"):
        assert must in d, f"默认（只读助手）必须禁用 {must}"


def test_default_keeps_web():
    assert "web" not in ts.default_disabled()


def test_normalize_dedupes_and_sorts():
    assert ts.normalize_disabled(["web", "web", "terminal", "bogus-unknown"]) == [
        "terminal",
        "web",
    ]


def test_normalize_empty_means_nothing_disabled():
    assert ts.normalize_disabled(None) == []
    assert ts.normalize_disabled([]) == []


def test_normalize_never_adds():
    """normalize 只做清洗，绝不会"自动禁用"——禁用集以 DB 存的为准。"""
    assert ts.normalize_disabled(["web"]) == ["web"]


# ── 鉴权 ──────────────────────────────────────────────────
async def test_agents_require_token(client):
    assert (await client.get("/api/agents")).status_code == 401


# ── CRUD ──────────────────────────────────────────────────
async def test_create_agent_success(client):
    tok = await _user_token(client)
    r = await client.post(
        "/api/agents",
        headers=_h(tok),
        json={
            "slug": "my-bot",
            "name": "我的机器人",
            "description": "测试用",
            "soul": "你是一个测试助手",
        },
    )
    assert r.status_code == 201
    b = r.json()
    assert b["slug"] == "my-bot"
    assert b["profile_name"] == "agent-u1-my-bot"  # v2 命名（SPEC-v2 决策 3）
    assert b["owner_id"] == 1
    assert b["profile_exists"] is True
    assert "terminal" in b["disabled_toolsets"]  # 默认只读助手


async def test_create_agent_duplicate_slug(client):
    tok = await _user_token(client)
    body = {"slug": "dup", "name": "Dup"}
    assert (await client.post("/api/agents", headers=_h(tok), json=body)).status_code == 201
    assert (await client.post("/api/agents", headers=_h(tok), json=body)).status_code == 409


async def test_create_agent_invalid_slug(client):
    tok = await _user_token(client)
    for bad in ("UPPER", "has space", "a" * 100, "-leading", "default", "admin"):
        r = await client.post("/api/agents", headers=_h(tok), json={"slug": bad, "name": "X"})
        assert r.status_code == 422, f"slug={bad!r} 应被拒绝，实际 {r.status_code}"


async def test_create_agent_rolls_back_when_profile_fails(client, monkeypatch):
    """profile 创建失败时，DB 不能留下孤儿记录。"""
    tok = await _user_token(client)
    import app.hermes.provisioner as prov

    async def boom(*a, **kw):
        raise prov.ProvisionError("dashboard 挂了")

    monkeypatch.setattr(prov, "create_agent_profile", boom)

    r = await client.post("/api/agents", headers=_h(tok), json={"slug": "orphan", "name": "O"})
    assert r.status_code == 502
    r2 = await client.get("/api/agents", headers=_h(tok))
    assert all(a["slug"] != "orphan" for a in r2.json())


async def test_list_agents_own_only(client):
    t1 = await _user_token(client, "user1")
    t2 = await _user_token(client, "user2")
    await client.post("/api/agents", headers=_h(t1), json={"slug": "mine", "name": "M"})
    r = await client.get("/api/agents", headers=_h(t2))
    assert r.status_code == 200
    assert all(a["slug"] != "mine" for a in r.json())
    r = await client.get("/api/agents", headers=_h(t1))
    assert [a["slug"] for a in r.json()] == ["mine"]


async def test_admin_sees_all_agents(client, atok):
    utok = await _user_token(client)
    await client.post("/api/agents", headers=_h(utok), json={"slug": "u-a", "name": "UA"})
    r = await client.get("/api/agents", headers=_h(atok))
    assert r.status_code == 200
    assert [a["slug"] for a in r.json()] == ["u-a"]


# ── 归属权限（SPEC-v2 决策 4）──────────────────────────────
async def test_other_user_cannot_modify_agent(client):
    t1 = await _user_token(client, "own")
    t2 = await _user_token(client, "intruder")
    aid = (
        await client.post("/api/agents", headers=_h(t1), json={"slug": "x1", "name": "X"})
    ).json()["id"]
    assert (
        await client.patch(f"/api/agents/{aid}", headers=_h(t2), json={"name": "Hacked"})
    ).status_code == 403
    assert (await client.delete(f"/api/agents/{aid}", headers=_h(t2))).status_code == 403
    assert (
        await client.post(f"/api/agents/{aid}/publish", headers=_h(t2))
    ).status_code == 403


async def test_owner_can_modify(client):
    tok = await _user_token(client)
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "own2", "name": "O"})
    ).json()["id"]
    assert (
        await client.patch(f"/api/agents/{aid}", headers=_h(tok), json={"name": "O2"})
    ).status_code == 200


async def test_admin_can_modify_any(client, atok):
    utok = await _user_token(client)
    aid = (
        await client.post("/api/agents", headers=_h(utok), json={"slug": "adm", "name": "A"})
    ).json()["id"]
    r = await client.patch(
        f"/api/agents/{aid}", headers=_h(atok), json={"name": "ByAdmin"}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "ByAdmin"


# ── 发布 / 对话可见性 ──────────────────────────────────────
async def test_published_agent_visible_to_others(client):
    t1 = await _user_token(client, "pub-owner")
    t2 = await _user_token(client, "reader")
    aid = (
        await client.post("/api/agents", headers=_h(t1), json={"slug": "pub", "name": "Pub"})
    ).json()["id"]
    assert (await client.get("/api/chat/agents", headers=_h(t2))).json() == []

    await client.post(f"/api/agents/{aid}/publish", headers=_h(t1))
    r = await client.get("/api/chat/agents", headers=_h(t2))
    assert [a["slug"] for a in r.json()] == ["pub"]


async def test_unpublish_hides_agent(client):
    t1 = await _user_token(client, "pub-owner2")
    t2 = await _user_token(client, "reader2")
    aid = (
        await client.post("/api/agents", headers=_h(t1), json={"slug": "ua", "name": "UA"})
    ).json()["id"]
    await client.post(f"/api/agents/{aid}/publish", headers=_h(t1))
    await client.post(f"/api/agents/{aid}/unpublish", headers=_h(t1))
    assert (await client.get("/api/chat/agents", headers=_h(t2))).json() == []


# ── 更新 ──────────────────────────────────────────────────
async def test_update_agent(client):
    tok = await _user_token(client)
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "user2", "name": "N1"})
    ).json()["id"]
    r = await client.patch(
        f"/api/agents/{aid}", headers=_h(tok), json={"name": "N2", "soul": "新的人格"}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "N2"


async def test_update_disabled_toolsets(client):
    tok = await _user_token(client)
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "t1", "name": "T1"})
    ).json()["id"]
    r = await client.patch(
        f"/api/agents/{aid}", headers=_h(tok), json={"disabled_toolsets": ["terminal"]}
    )
    assert r.status_code == 200
    assert r.json()["disabled_toolsets"] == ["terminal"]


async def test_delete_agent(client):
    tok = await _user_token(client)
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "d1", "name": "D1"})
    ).json()["id"]
    assert (await client.delete(f"/api/agents/{aid}", headers=_h(tok))).status_code == 204
    assert (await client.get("/api/agents", headers=_h(tok))).json() == []


async def test_get_agent_404(client):
    tok = await _user_token(client)
    r = await client.get("/api/agents/9999", headers=_h(tok))
    assert r.status_code == 404
