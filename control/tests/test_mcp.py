"""MCP 代理接口测试（hermes dashboard 用 fake 替代）。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}



async def _make_agent(client, atok, slug="m1") -> int:
    await client.post(
        "/api/agents", headers=_h(atok), json={"slug": slug, "name": slug}
    )
    agents = (await client.get("/api/agents", headers=_h(atok))).json()
    return next(a["id"] for a in agents if a["slug"] == slug)


@pytest.fixture(autouse=True)
def patch_mcp(monkeypatch):
    """用内存版替换 mcp 服务层。"""
    import app.routes.agent_mcp as route

    state: dict[str, dict] = {}

    async def fake_list(profile: str):
        return list(state.values())

    async def fake_add(profile: str, body: dict):
        if body["name"] in state:
            import app.hermes.mcp as m

            raise m.MCPError("already exists")
        state[body["name"]] = {
            "name": body["name"],
            "transport": body.get("transport", "stdio"),
            "url": body.get("url"),
            "command": body.get("command"),
            "args": body.get("args"),
            "enabled": body.get("enabled", True),
        }
        return state[body["name"]]

    async def fake_delete(profile: str, name: str):
        state.pop(name, None)

    async def fake_test(profile: str, name: str):
        return {"ok": name in state, "tools": [{"name": "t1"}]}

    async def fake_enabled(profile: str, name: str, enabled: bool):
        if name in state:
            state[name]["enabled"] = enabled
        return {"ok": True}

    async def fake_catalog():
        return [{"name": "filesystem", "description": "本地文件"}]

    monkeypatch.setattr(route.mcp_svc, "list_servers", fake_list)
    monkeypatch.setattr(route.mcp_svc, "add_server", fake_add)
    monkeypatch.setattr(route.mcp_svc, "delete_server", fake_delete)
    monkeypatch.setattr(route.mcp_svc, "test_server", fake_test)
    monkeypatch.setattr(route.mcp_svc, "set_enabled", fake_enabled)
    monkeypatch.setattr(route.mcp_svc, "catalog", fake_catalog)
    yield state


async def test_list_empty(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    r = await client.get(f"/api/agents/{aid}/mcp", headers=_h(atok))
    assert r.status_code == 200
    assert r.json()["servers"] == []


async def test_add_stdio(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    r = await client.post(
        f"/api/agents/{aid}/mcp",
        headers=_h(atok),
        json={
            "name": "fs",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "pkg"],
        },
    )
    assert r.status_code == 201
    assert r.json()["name"] == "fs"
    assert r.json()["command"] == "npx"


async def test_add_stdio_without_command_422(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    r = await client.post(
        f"/api/agents/{aid}/mcp",
        headers=_h(atok),
        json={"name": "bad", "transport": "stdio"},
    )
    assert r.status_code == 422


async def test_add_http_without_url_422(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    r = await client.post(
        f"/api/agents/{aid}/mcp",
        headers=_h(atok),
        json={"name": "bad", "transport": "sse"},
    )
    assert r.status_code == 422


async def test_add_http(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    r = await client.post(
        f"/api/agents/{aid}/mcp",
        headers=_h(atok),
        json={"name": "remote", "transport": "sse", "url": "https://x/sse"},
    )
    assert r.status_code == 201
    assert r.json()["url"] == "https://x/sse"


async def test_duplicate_name_502(client, atok, patch_mcp):
    """hermes 侧重复会报错，控制层透传为 502。"""
    aid = await _make_agent(client, atok)
    h = _h(atok)
    body = {"name": "dup", "transport": "stdio", "command": "x"}
    assert (await client.post(f"/api/agents/{aid}/mcp", headers=h, json=body)).status_code == 201
    assert (await client.post(f"/api/agents/{aid}/mcp", headers=h, json=body)).status_code == 502


async def test_test_and_toggle(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    h = _h(atok)
    await client.post(
        f"/api/agents/{aid}/mcp",
        headers=h,
        json={"name": "fs", "transport": "stdio", "command": "x"},
    )
    r = await client.post(f"/api/agents/{aid}/mcp/fs/test", headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = await client.put(
        f"/api/agents/{aid}/mcp/fs/enabled", headers=h, json={"enabled": False}
    )
    assert r.status_code == 200
    assert patch_mcp["fs"]["enabled"] is False


async def test_delete(client, atok, patch_mcp):
    aid = await _make_agent(client, atok)
    h = _h(atok)
    await client.post(
        f"/api/agents/{aid}/mcp",
        headers=h,
        json={"name": "fs", "transport": "stdio", "command": "x"},
    )
    assert (await client.delete(f"/api/agents/{aid}/mcp/fs", headers=h)).status_code == 204
    assert (await client.get(f"/api/agents/{aid}/mcp", headers=h)).json()["servers"] == []


async def test_catalog(client, atok, patch_mcp):
    r = await client.get("/api/agents/mcp-catalog/all", headers=_h(atok))
    assert r.status_code == 200
    assert r.json()["entries"][0]["name"] == "filesystem"


async def test_requires_admin(client, atok, patch_mcp):
    utok = (
        await client.post(
            "/api/auth/register", json={"username": "muser", "password": "password123"}
        )
    ).json()["access_token"]
    aid = await _make_agent(client, atok)
    assert (
        await client.get(f"/api/agents/{aid}/mcp", headers=_h(utok))
    ).status_code == 403
