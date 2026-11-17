"""AgentAPIKey 管理测试（批次 3）。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _user_token(client, name="keyuser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def _agent(client, tok, slug="ka1"):
    r = await client.post("/api/agents", headers=_h(tok), json={"slug": slug, "name": slug})
    return r.json()["id"]


async def test_create_key_returns_plaintext_once(client):
    tok = await _user_token(client)
    aid = await _agent(client, tok)
    r = await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json={"name": "default"})
    assert r.status_code == 201
    b = r.json()
    assert b["key"].startswith("agk_")
    assert len(b["key"]) == 36  # agk_ + 32 hex
    assert b["key_prefix"] == b["key"][:12]
    assert b["enabled"] is True


async def test_list_never_returns_plaintext(client):
    tok = await _user_token(client)
    aid = await _agent(client, tok)
    created = (
        await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json={"name": "k1"})
    ).json()
    rows = (await client.get(f"/api/agents/{aid}/api-keys", headers=_h(tok))).json()
    assert len(rows) == 1
    assert "key" not in rows[0]  # 明文不再出现
    assert rows[0]["key_prefix"] == created["key"][:12]


async def test_duplicate_name_409(client):
    tok = await _user_token(client)
    aid = await _agent(client, tok)
    body = {"name": "dup"}
    assert (await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json=body)).status_code == 201
    assert (await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json=body)).status_code == 409


async def test_enable_disable_and_delete(client):
    tok = await _user_token(client)
    aid = await _agent(client, tok)
    kid = (
        await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json={"name": "k"})
    ).json()["id"]

    r = await client.patch(f"/api/agents/{aid}/api-keys/{kid}", headers=_h(tok), json={"enabled": False})
    assert r.json()["enabled"] is False

    assert (
        await client.delete(f"/api/agents/{aid}/api-keys/{kid}", headers=_h(tok))
    ).status_code == 204
    assert (await client.get(f"/api/agents/{aid}/api-keys", headers=_h(tok))).json() == []


async def test_other_user_cannot_manage_keys(client):
    t1 = await _user_token(client, "keyown")
    t2 = await _user_token(client, "keyother")
    aid = await _agent(client, t1)

    assert (
        await client.post(f"/api/agents/{aid}/api-keys", headers=_h(t2), json={"name": "x"})
    ).status_code == 403
    assert (await client.get(f"/api/agents/{aid}/api-keys", headers=_h(t2))).status_code == 403


async def test_manual_generation_no_auto_key(client):
    """创建 Agent 时不自动生成 Key（用户拍板：手动生成）。"""
    tok = await _user_token(client)
    aid = await _agent(client, tok, slug="nokey")
    rows = (await client.get(f"/api/agents/{aid}/api-keys", headers=_h(tok))).json()
    assert rows == []
