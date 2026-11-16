"""用户体系测试：注册 / 登录 / scope 隔离。

scope 隔离是 SPEC §3.5 的核心约束：管理员 token 不能当用户 token 用，反之亦然。
"""

import pytest

pytestmark = pytest.mark.asyncio


async def _register(client, username="alice", password="password123", **kw):
    return await client.post(
        "/api/auth/register",
        json={"username": username, "password": password, **kw},
    )


async def test_register_success(client):
    r = await _register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["username"] == "alice"
    assert body["access_token"]
    assert body["token_type"] == "bearer"


async def test_register_duplicate_username(client):
    await _register(client)
    r = await _register(client)
    assert r.status_code == 409
    assert "用户名" in r.json()["detail"]


async def test_register_duplicate_email(client):
    await _register(client, email="a@example.com")
    r = await _register(client, username="bob", email="a@example.com")
    assert r.status_code == 409
    assert "邮箱" in r.json()["detail"]


async def test_register_invalid_username(client):
    r = await _register(client, username="a b")
    assert r.status_code == 422


async def test_register_short_password(client):
    r = await _register(client, password="short")
    assert r.status_code == 422


async def test_login_success(client):
    await _register(client)
    r = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


async def test_login_wrong_password(client):
    await _register(client)
    r = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrongpass1"}
    )
    assert r.status_code == 401


async def test_login_unknown_user_same_message(client):
    """不泄露用户是否存在：未知用户与错误密码返回同样的 401。"""
    r = await client.post(
        "/api/auth/login", json={"username": "nobody", "password": "whatever1"}
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "用户名或密码错误"


async def test_me_with_user_token(client):
    tok = (await _register(client)).json()["access_token"]
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


async def test_me_without_token(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_with_garbage_token(client):
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_admin_token_rejected_as_user(client):
    """★ scope 隔离：admin scope 的 token 调 /me（需 user scope）必须 403。"""
    from app.security import create_access_token

    admin_tok = create_access_token("admin", "admin")
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 403
    assert "用户身份" in r.json()["detail"]


async def test_user_token_rejected_as_admin(client):
    """★ 反向隔离：user scope 的 token 不能通过 get_current_admin。"""
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.security import get_current_admin

    probe = FastAPI()

    @probe.get("/admin-only")
    async def admin_only(_: str = Depends(get_current_admin)):
        return {"ok": True}

    tok = (await _register(client)).json()["access_token"]
    async with AsyncClient(
        transport=ASGITransport(app=probe), base_url="http://probe"
    ) as pc:
        r = await pc.get("/admin-only", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "管理员身份" in r.json()["detail"]


async def test_registration_can_be_disabled(client, monkeypatch):
    """ALLOW_REGISTRATION=false 时注册返回 403。"""
    from app.routes import auth as auth_module

    monkeypatch.setattr(auth_module._settings, "allow_registration", False)
    r = await _register(client, username="carol")
    assert r.status_code == 403
    assert "未开放注册" in r.json()["detail"]
