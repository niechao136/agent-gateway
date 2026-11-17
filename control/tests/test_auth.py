"""用户体系测试：注册 / 登录 / role 隔离（v2 统一登录）。"""

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


async def test_ghost_admin_token_rejected(client):
    """token 里的用户必须真实存在（防伪造 claim）。"""
    from app.security import create_access_token

    tok = create_access_token("ghost-admin", "admin")
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


async def test_user_token_rejected_as_admin(client):
    """★ role 隔离：role=user 的 token 不能通过 get_current_admin。"""
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.security import get_current_admin

    probe = FastAPI()
    # 复用 conftest 挂到主 app 上的 session override，让 probe 也能查 users 表
    from app.database import get_session as _gs

    main_override = app.dependency_overrides.get(_gs)
    if main_override is not None:
        probe.dependency_overrides[_gs] = main_override

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
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_registration", False)
    r = await _register(client, username="carol")
    assert r.status_code == 403
    assert "未开放注册" in r.json()["detail"]


# ── 引导管理员（SPEC-v2 决策 1）────────────────────────────
# 引导逻辑的真实验证放在 test_users_admin.py::test_bootstrap_created_admin_can_login：
# conftest 的 bootstrap_admin fixture 把 main.get_session_factory 重定向到测试库，
# 然后调用 _bootstrap_admin()，再用配置的密码走 /api/auth/login 全链路验证。
# 这里只补一个纯逻辑检查：JWT 里 role 不再参与 scope 判定。

async def test_role_claim_does_not_gate_login_endpoints(client, user_token):
    """role=user 的 token 访问 /me 正常（v2 无 scope 概念）。"""
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"
