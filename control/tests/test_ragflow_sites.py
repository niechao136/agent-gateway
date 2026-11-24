"""RAGFlow 站点路由测试。"""
import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _user_token(client, name="siteuser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def test_sites_route_not_swallowed_by_kb_id(client):
    """GET /api/knowledge/sites 不能被 /{kb_id} 当 int 吞掉（200 而非 422）。"""
    tok = await _user_token(client)
    r = await client.get("/api/knowledge/sites", headers=_h(tok))
    assert r.status_code == 200


async def test_create_site_hides_api_key(client):
    tok = await _user_token(client, "sitecreator")
    r = await client.post("/api/knowledge/sites", headers=_h(tok), json={
        "name": "上海RAG", "base_url": "http://139.224.13.57",
        "api_key": "ragflow-SUPERSECRET123456",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["has_api_key"] is True
    assert "SUPERSECRET" not in str(body)


async def test_site_detail_shows_masked_key(client):
    tok = await _user_token(client, "sitedetail")
    created = (await client.post("/api/knowledge/sites", headers=_h(tok), json={
        "name": "S2", "base_url": "http://x", "api_key": "ragflow-ABCDEFGHIJKLMN",
    })).json()
    r = await client.get(f"/api/knowledge/sites/{created['id']}", headers=_h(tok))
    assert r.status_code == 200
    assert "ABCDEFGHIJKLMN" not in r.text
    assert "ragf" in r.json().get("api_key_masked", "")


@pytest.mark.skip(reason="依赖 Task 3 库路由 site_id 字段，Task 3 后启用")
async def test_delete_referenced_site_requires_force(client):
    tok = await _user_token(client, "siteforce")
    site = (await client.post("/api/knowledge/sites", headers=_h(tok), json={
        "name": "S3", "base_url": "http://x", "api_key": "k",
    })).json()
    agent = (await client.post("/api/agents", headers=_h(tok), json={
        "slug": "forceagent", "name": "F",
    })).json()
    kb = (await client.post("/api/knowledge", headers=_h(tok), json={
        "site_id": site["id"], "name": "lib", "dataset_id": "d1", "dataset_name": "Lib",
    })).json()
    await client.put(f"/api/agents/{agent['id']}/knowledge", headers=_h(tok), json={"kb_ids": [kb["id"]]})
    r = await client.delete(f"/api/knowledge/sites/{site['id']}", headers=_h(tok))
    assert r.status_code == 409
    r = await client.delete(f"/api/knowledge/sites/{site['id']}?force=true", headers=_h(tok))
    assert r.status_code == 200
    assert (await client.get(f"/api/agents/{agent['id']}/knowledge", headers=_h(tok))).json() == []
