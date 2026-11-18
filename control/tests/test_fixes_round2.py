"""本轮修复的后端测试：内置 skill 选择 / 修改密码 / 模型测试 / -self 权限保护。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _user_token(client, name="fixuser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


# ── 修改密码 ──────────────────────────────────────────────
async def test_change_password_wrong_current(client):
    tok = await _user_token(client, "pwuser")
    r = await client.post(
        "/api/auth/change-password",
        headers=_h(tok),
        json={"current_password": "wrongpass", "new_password": "newpassword123"},
    )
    assert r.status_code == 403
    assert "原密码" in r.json()["detail"]


async def test_change_password_success_and_old_fails(client):
    tok = await _user_token(client, "pwok")
    r = await client.post(
        "/api/auth/change-password",
        headers=_h(tok),
        json={"current_password": "password123", "new_password": "newpassword123"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 旧密码登录失败，新密码成功
    assert (
        await client.post(
            "/api/auth/login", json={"username": "pwok", "password": "password123"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/auth/login", json={"username": "pwok", "password": "newpassword123"}
        )
    ).status_code == 200


async def test_change_password_same_password_422(client):
    tok = await _user_token(client, "pwsame")
    r = await client.post(
        "/api/auth/change-password",
        headers=_h(tok),
        json={"current_password": "password123", "new_password": "password123"},
    )
    assert r.status_code == 422


async def _find_uid(client, atok, username: str) -> int:
    """通过管理接口查用户 id（避免直连全局 SessionLocal）。"""
    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    return next(u["id"] for u in users if u["username"] == username)


# ── 禁止改自己权限 ────────────────────────────────────────
async def test_admin_cannot_change_own_role(client, atok):
    from sqlalchemy import select  # noqa: F401

    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    me = next(u for u in users if u["username"] == "testadmin")

    r = await client.patch(
        f"/api/admin/users/{me['id']}", headers=_h(atok), json={"role": "user"}
    )
    assert r.status_code == 403
    assert "自己的权限" in r.json()["detail"]


async def test_admin_cannot_disable_self(client, atok):
    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    me = next(u for u in users if u["username"] == "testadmin")

    r = await client.patch(
        f"/api/admin/users/{me['id']}", headers=_h(atok), json={"disabled": True}
    )
    assert r.status_code == 403


async def test_admin_can_change_other_role(client, atok):
    await _user_token(client, "otheruser")
    uid = await _find_uid(client, atok, "otheruser")

    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"role": "admin"}
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


# ── 内置 Skill 按 Agent 选择 ──────────────────────────────
async def test_agent_builtin_skills_default_empty(client):
    """新建 Agent 的内置 Skill 默认全不选。"""
    tok = await _user_token(client, "bsuser")
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "bsbot", "name": "b"})
    ).json()["id"]
    r = await client.get(f"/api/agents/{aid}/skills/builtin", headers=_h(tok))
    assert r.status_code == 200
    b = r.json()
    assert b["agent_id"] == aid
    # FakeDashboard 返回 memory-helper/greeter/echo；默认都未选中
    assert all(not s["selected"] for s in b["skills"])


async def test_agent_builtin_skills_set_and_isolate(client):
    """选择内置 Skill 后持久；与自定义绑定 state 隔离。"""
    tok = await _user_token(client, "bsuser2")
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "bsbot2", "name": "b"})
    ).json()["id"]

    r = await client.put(
        f"/api/agents/{aid}/skills/builtin",
        headers=_h(tok),
        json={"skill_names": ["greeter", "echo"]},
    )
    assert r.status_code == 200
    assert set(r.json()["selected"]) == {"greeter", "echo"}

    # 再读一次确认持久
    r2 = await client.get(f"/api/agents/{aid}/skills/builtin", headers=_h(tok))
    selected = {s["name"] for s in r2.json()["skills"] if s["selected"]}
    assert selected == {"greeter", "echo"}

    # 自定义 Skill 绑定列表不含内置名（ID 空间隔离）
    r3 = await client.get(f"/api/agents/{aid}/skills", headers=_h(tok))
    assert all(isinstance(s["id"], int) for s in r3.json()["bound"])


async def test_agent_builtin_skills_validation(client):
    tok = await _user_token(client, "bsuser3")
    aid = (
        await client.post("/api/agents", headers=_h(tok), json={"slug": "bsbot3", "name": "b"})
    ).json()["id"]
    r = await client.put(
        f"/api/agents/{aid}/skills/builtin",
        headers=_h(tok),
        json={"skill_names": "not-a-list"},
    )
    assert r.status_code == 422


# ── 模型测试端点 ──────────────────────────────────────────
async def test_model_test_no_base_url_ok(client):
    tok = await _user_token(client, "mtuser")
    tid = (
        await client.post(
            "/api/models",
            headers=_h(tok),
            json={"name": "simple", "model": "gemini-2.5-flash", "provider": "gemini"},
        )
    ).json()["id"]
    r = await client.post(f"/api/models/{tid}/test", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "Base URL" in r.json()["detail"]


async def test_model_test_with_mock_endpoint(client, monkeypatch):
    """有 base_url 时用 httpx mock 验证请求，不回显 key。"""
    import httpx

    tok = await _user_token(client, "mtuser2")
    tid = (
        await client.post(
            "/api/models",
            headers=_h(tok),
            json={
                "name": "remote",
                "model": "gpt-x",
                "provider": "custom",
                "base_url": "https://api.example.com/v1",
                "api_key": "supersecret-key",
            },
        )
    ).json()["id"]

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"id": "gpt-x"}]}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            FakeClient.last = (url, headers)
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    r = await client.post(f"/api/models/{tid}/test", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["models"] == ["gpt-x"]
    # 不回显 key
    assert "supersecret-key" not in r.text
