"""A2A 出站端点独立表全链路测试（批次 2）。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}

EP_BODY = {
    "name": "translate-bot",
    "url": "http://127.0.0.1:9001",
    "auth_type": "bearer",
    "token": "ep-secret",
    "capabilities": ["translation"],
}


async def _user_token(client, name="a2auser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def _agent(client, tok, slug="a2aa1"):
    r = await client.post("/api/agents", headers=_h(tok), json={"slug": slug, "name": slug})
    return r.json()["id"]


async def test_crud_and_no_token_echo(client):
    tok = await _user_token(client)
    r = await client.post("/api/a2a/endpoints", headers=_h(tok), json=EP_BODY)
    assert r.status_code == 201
    b = r.json()
    assert b["has_token"] is True
    assert "ep-secret" not in r.text

    eid = b["id"]
    r = await client.patch(
        f"/api/a2a/endpoints/{eid}", headers=_h(tok), json={"timeout": 60}
    )
    assert r.json()["timeout"] == 60
    assert r.json()["has_token"] is True  # token 未被清除

    assert (await client.delete(f"/api/a2a/endpoints/{eid}", headers=_h(tok))).status_code == 204


async def test_invalid_url_422(client):
    tok = await _user_token(client)
    r = await client.post(
        "/api/a2a/endpoints", headers=_h(tok), json={**EP_BODY, "name": "bad", "url": "not-a-url"}
    )
    assert r.status_code == 422


async def test_shared_visibility(client, atok):
    u = await _user_token(client)
    r = await client.post(
        "/api/a2a/endpoints",
        headers=_h(atok),
        json={**EP_BODY, "name": "shared-ep", "is_shared": True},
    )
    eid = r.json()["id"]
    assert r.json()["is_shared"] is True

    # 他人可见可绑定，不可改删
    assert any(x["id"] == eid for x in (await client.get("/api/a2a/endpoints", headers=_h(u))).json())
    assert (
        await client.patch(f"/api/a2a/endpoints/{eid}", headers=_h(u), json={"timeout": 1})
    ).status_code == 403


async def test_bind_sync_and_effective(client, monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_data_root", str(tmp_path))

    tok = await _user_token(client)
    eid = (await client.post("/api/a2a/endpoints", headers=_h(tok), json=EP_BODY)).json()["id"]
    aid = await _agent(client, tok)

    r = await client.put(f"/api/agents/{aid}/a2a", headers=_h(tok), json={"endpoint_ids": [eid]})
    assert r.status_code == 200

    # 详情接口含 profile 实际生效段
    r = await client.get(f"/api/agents/{aid}/a2a", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["profile"] == "agent-u1-a2aa1"


async def test_create_and_bind(client):
    tok = await _user_token(client)
    aid = await _agent(client, tok, slug="a2acb")
    r = await client.post(f"/api/agents/{aid}/a2a/create-and-bind", headers=_h(tok), json=EP_BODY)
    assert r.status_code == 201
    assert r.json()["created"] is True


async def test_bind_others_private_403(client):
    t1 = await _user_token(client, "a2aown")
    t2 = await _user_token(client, "a2abind")
    eid = (await client.post("/api/a2a/endpoints", headers=_h(t1), json=EP_BODY)).json()["id"]
    aid = await _agent(client, t2)
    r = await client.put(f"/api/agents/{aid}/a2a", headers=_h(t2), json={"endpoint_ids": [eid]})
    assert r.status_code == 403


async def test_internal_endpoint_autofills_url(client):
    """内部 A2A 端点：选目标 Agent 后 URL 自动生成且字段正确落库（回归）。"""
    tok = await _user_token(client, "a2ainternal")
    aid = await _agent(client, tok, slug="ainternal")
    await client.post(f"/api/agents/{aid}/publish", headers=_h(tok))

    r = await client.post(
        "/api/a2a/endpoints",
        headers=_h(tok),
        json={"name": "内部目标", "target_type": "internal", "target_agent_id": aid, "url": ""},
    )
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["target_type"] == "internal"
    assert b["target_agent_id"] == aid
    assert b["url"] == "/a2a/ainternal"


async def test_requires_login(client):
    assert (await client.get("/api/a2a/endpoints")).status_code == 401
