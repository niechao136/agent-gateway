"""MCP 独立表全链路测试（批次 2）。

覆盖：CRUD / 共享可见性 / 绑定同步 / create-and-bind / token 不回明文 / 403 矩阵。
"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


STDIO_BODY = {
    "name": "fs",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "auth_type": "none",
}
HTTP_BODY = {
    "name": "remote",
    "transport": "http",
    "url": "https://mcp.example.com/v1",
    "auth_type": "bearer",
    "token": "secret-token",
}


async def _user_token(client, name="mcpuser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def _agent(client, tok, slug="mcpa1"):
    r = await client.post("/api/agents", headers=_h(tok), json={"slug": slug, "name": slug})
    return r.json()["id"]


# ── CRUD ──────────────────────────────────────────────────
async def test_create_stdio(client):
    tok = await _user_token(client)
    r = await client.post("/api/mcp", headers=_h(tok), json=STDIO_BODY)
    assert r.status_code == 201
    b = r.json()
    assert b["transport"] == "stdio"
    assert b["owner_id"] == 1
    assert b["is_shared"] is False


async def test_create_http_with_token_no_echo(client):
    tok = await _user_token(client)
    r = await client.post("/api/mcp", headers=_h(tok), json=HTTP_BODY)
    assert r.status_code == 201
    b = r.json()
    assert b["has_token"] is True
    assert "secret-token" not in r.text  # ★ 不回明文


async def test_create_validation(client):
    tok = await _user_token(client)
    # stdio 缺 command
    r = await client.post("/api/mcp", headers=_h(tok), json={"name": "x", "transport": "stdio"})
    assert r.status_code == 422
    # http 缺 url
    r = await client.post("/api/mcp", headers=_h(tok), json={"name": "x", "transport": "http"})
    assert r.status_code == 422
    # bearer 缺 token
    r = await client.post(
        "/api/mcp", headers=_h(tok),
        json={"name": "x", "transport": "http", "url": "https://a", "auth_type": "bearer"},
    )
    assert r.status_code == 422
    # header 缺 auth_name
    r = await client.post(
        "/api/mcp", headers=_h(tok),
        json={"name": "x", "transport": "http", "url": "https://a",
              "auth_type": "header", "token": "t"},
    )
    assert r.status_code == 422
    # 未知 transport
    r = await client.post("/api/mcp", headers=_h(tok), json={"name": "x", "transport": "grpc"})
    assert r.status_code == 422


async def test_duplicate_name_409(client):
    tok = await _user_token(client)
    assert (await client.post("/api/mcp", headers=_h(tok), json=STDIO_BODY)).status_code == 201
    assert (await client.post("/api/mcp", headers=_h(tok), json=STDIO_BODY)).status_code == 409


async def test_update_preserves_token_when_absent(client):
    """token 不传 = 保持不变（不回明文的配套语义）。"""
    tok = await _user_token(client)
    sid = (await client.post("/api/mcp", headers=_h(tok), json=HTTP_BODY)).json()["id"]
    r = await client.patch(f"/api/mcp/{sid}", headers=_h(tok), json={"description": "改名"})
    assert r.status_code == 200
    assert r.json()["has_token"] is True
    # 显式传 "" = 清除
    r = await client.patch(f"/api/mcp/{sid}", headers=_h(tok), json={"token": ""})
    assert r.json()["has_token"] is False


# ── 共享可见性 ────────────────────────────────────────────
async def test_shared_visible_to_others(client, atok):
    u = await _user_token(client)
    body = {**HTTP_BODY, "name": "shared-mcp", "is_shared": True}
    # 普通用户不能共享
    r = await client.post("/api/mcp", headers=_h(u), json=body)
    assert r.status_code == 201
    assert r.json()["is_shared"] is False  # 静默降级为不共享
    # 管理员共享
    r = await client.post("/api/mcp", headers=_h(atok), json=body)
    assert r.json()["is_shared"] is True
    sid = r.json()["id"]
    # 共享的他人可见（列表），但不可改删
    assert any(x["id"] == sid for x in (await client.get("/api/mcp", headers=_h(u))).json())
    assert (await client.patch(f"/api/mcp/{sid}", headers=_h(u), json={"url": "https://x"})).status_code == 403
    assert (await client.delete(f"/api/mcp/{sid}", headers=_h(u))).status_code == 403


async def test_private_invisible_to_others(client):
    t1 = await _user_token(client, "mcpa")
    t2 = await _user_token(client, "mcpb")
    sid = (await client.post("/api/mcp", headers=_h(t1), json=STDIO_BODY)).json()["id"]
    assert all(x["id"] != sid for x in (await client.get("/api/mcp", headers=_h(t2))).json())
    assert (await client.patch(f"/api/mcp/{sid}", headers=_h(t2), json={"description": "x"})).status_code == 403


# ── 绑定 + 同步 ───────────────────────────────────────────
async def test_bind_and_sync(client, monkeypatch, tmp_path):
    """绑定后写入 profile config.yaml 的 mcp.servers 段。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_data_root", str(tmp_path))

    tok = await _user_token(client)
    sid = (await client.post("/api/mcp", headers=_h(tok), json=HTTP_BODY)).json()["id"]
    aid = await _agent(client, tok)

    r = await client.put(f"/api/agents/{aid}/mcp", headers=_h(tok), json={"mcp_server_ids": [sid]})
    assert r.status_code == 200
    assert r.json()["bound"] == 1

    # profile config.yaml 落盘校验
    import yaml
    from app.hermes.a2a import profile_config_path

    cfg_path = profile_config_path("agent-u1-mcpa1", str(tmp_path))
    # conftest 的 FakeDashboard 可能没真建 profile；若 config.yaml 不存在则同步降级 ok=False
    if cfg_path.is_file():
        cfg = yaml.safe_load(cfg_path.read_text())
        servers = cfg.get("mcp", {}).get("servers", [])
        assert servers and servers[0]["name"] == "remote"
        assert servers[0]["headers"]["Authorization"] == "Bearer secret-token"
    else:
        assert r.json()["sync"].get("ok") is False  # 降级记录 warning


async def test_bind_forbidden_private_of_others(client):
    t1 = await _user_token(client, "mcpown")
    t2 = await _user_token(client, "mcpbind")
    sid = (await client.post("/api/mcp", headers=_h(t1), json=STDIO_BODY)).json()["id"]
    aid = await _agent(client, t2, slug="binda")
    r = await client.put(f"/api/agents/{aid}/mcp", headers=_h(t2), json={"mcp_server_ids": [sid]})
    assert r.status_code == 403


async def test_create_and_bind(client):
    tok = await _user_token(client)
    aid = await _agent(client, tok, slug="cb1")
    r = await client.post(
        f"/api/agents/{aid}/mcp/create-and-bind", headers=_h(tok), json=HTTP_BODY
    )
    assert r.status_code == 201
    b = r.json()
    assert b["created"] is True
    assert b["server"]["name"] == "remote"
    # 再调一次同名 → 直接绑定已存在的
    r2 = await client.post(
        f"/api/agents/{aid}/mcp/create-and-bind", headers=_h(tok), json=HTTP_BODY
    )
    assert r2.json()["created"] is False


async def test_delete_with_binding_requires_force(client):
    tok = await _user_token(client)
    sid = (await client.post("/api/mcp", headers=_h(tok), json=STDIO_BODY)).json()["id"]
    aid = await _agent(client, tok, slug="dela")
    await client.put(f"/api/agents/{aid}/mcp", headers=_h(tok), json={"mcp_server_ids": [sid]})

    r = await client.delete(f"/api/mcp/{sid}", headers=_h(tok))
    assert r.status_code == 409
    r = await client.delete(f"/api/mcp/{sid}?force=true", headers=_h(tok))
    assert r.status_code == 204


async def test_rebind_same_server_is_idempotent(client):
    """重复保存同一绑定（先删后插同主键）不应 500（回归：唯一约束冲突）。"""
    tok = await _user_token(client, "rebind")
    sid = (await client.post("/api/mcp", headers=_h(tok), json=STDIO_BODY)).json()["id"]
    aid = await _agent(client, tok, slug="rebinda1")

    for _ in range(3):
        r = await client.put(
            f"/api/agents/{aid}/mcp", headers=_h(tok), json={"mcp_server_ids": [sid]}
        )
        assert r.status_code == 200, r.text
        assert r.json()["bound"] == 1


async def test_mcp_requires_login(client):
    assert (await client.get("/api/mcp")).status_code == 401
