"""对外 API v1 测试（批次 3）：agk 鉴权 / Messages 语义 / 限流 / 会话。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _kh(k):
    return {"Authorization": f"Bearer {k}"}


async def _setup(client, slug="v1bot"):
    """注册用户 → 建 Agent → 发布 → 生成 Key。返回 (user_tok, agent_id, key)。"""
    r = await client.post(
        "/api/auth/register", json={"username": "v1user", "password": "password123"}
    )
    tok = r.json()["access_token"] if r.status_code == 201 else (
        await client.post("/api/auth/login", json={"username": "v1user", "password": "password123"})
    ).json()["access_token"]

    r = await client.post("/api/agents", headers=_h(tok), json={"slug": slug, "name": slug})
    aid = r.json()["id"]
    await client.post(f"/api/agents/{aid}/publish", headers=_h(tok))
    k = (
        await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json={"name": "k"})
    ).json()["key"]
    return tok, aid, k


async def test_missing_key_401(client):
    r = await client.post("/api/v1/agents/x/messages", json={"message": "hi"})
    assert r.status_code == 401


async def test_invalid_key_401(client):
    r = await client.post(
        "/api/v1/agents/x/messages", headers=_kh("agk_" + "0" * 32), json={"message": "hi"}
    )
    assert r.status_code == 401


async def test_non_agk_format_401(client):
    r = await client.post(
        "/api/v1/agents/x/messages", headers=_kh("sk-abc"), json={"message": "hi"}
    )
    assert r.status_code == 401


async def test_key_bound_to_other_agent_403(client):
    _, _, k = await _setup(client, slug="ownbot")
    # 另一个用户发布另一个 Agent，用自己的 key 访问别人的 slug
    r = await client.post(
        "/api/auth/register", json={"username": "v1other", "password": "password123"}
    )
    t2 = r.json()["access_token"] if r.status_code == 201 else (
        await client.post("/api/auth/login", json={"username": "v1other", "password": "password123"})
    ).json()["access_token"]
    aid2 = (
        await client.post("/api/agents", headers=_h(t2), json={"slug": "otherbot", "name": "o"})
    ).json()["id"]
    await client.post(f"/api/agents/{aid2}/publish", headers=_h(t2))

    r = await client.post(
        "/api/v1/agents/otherbot/messages", headers=_kh(k), json={"message": "hi"}
    )
    assert r.status_code == 403
    assert "无权访问" in r.json()["detail"]


async def test_unpublished_agent_403(client):
    tok = await _user_token_plain(client, "v1draft")
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "draftbot", "name": "d"})
    ).json()["id"]
    k = (
        await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json={"name": "k"})
    ).json()["key"]

    r = await client.post(
        "/api/v1/agents/draftbot/messages", headers=_kh(k), json={"message": "hi"}
    )
    assert r.status_code == 403
    assert "未发布" in r.json()["detail"]


async def _user_token_plain(client, name):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def test_disabled_key_403(client):
    tok = await _user_token_plain(client, "v1dis")
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "disbot", "name": "d"})
    ).json()["id"]
    await client.post(f"/api/agents/{aid}/publish", headers=_h(tok))
    created = (
        await client.post(f"/api/agents/{aid}/api-keys", headers=_h(tok), json={"name": "k"})
    ).json()
    await client.patch(
        f"/api/agents/{aid}/api-keys/{created['id']}", headers=_h(tok), json={"enabled": False}
    )
    r = await client.post(
        "/api/v1/agents/disbot/messages", headers=_kh(created["key"]), json={"message": "hi"}
    )
    assert r.status_code == 403


async def test_list_my_agents(client):
    _, _, k = await _setup(client, slug="listbot")
    r = await client.get("/api/v1/agents", headers=_kh(k))
    assert r.status_code == 200
    assert [a["slug"] for a in r.json()] == ["listbot"]


async def test_rate_limit_429(client):
    from app.routes.v1 import _reset_rate_limit

    _reset_rate_limit()
    _, _, k = await _setup(client, slug="rlb bot".replace(" ", ""))
    # 60 次额度打满
    for _ in range(60):
        await client.get("/api/v1/agents", headers=_kh(k))
    r = await client.get("/api/v1/agents", headers=_kh(k))
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    _reset_rate_limit()


async def test_unknown_session_404(client):
    _, _, k = await _setup(client, slug="sessbot")
    r = await client.post(
        "/api/v1/agents/sessbot/messages",
        headers=_kh(k),
        json={"message": "hi", "session_id": "ag_nonexistent"},
    )
    assert r.status_code == 404
