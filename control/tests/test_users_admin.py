"""用户管理接口测试。"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _user(client, name="alice"):
    r = await client.post(
        "/api/auth/register", json={"username": name, "password": "password123"}
    )
    return r.json()["access_token"]


async def test_list_users_requires_admin(client, atok):
    utok = await _user(client)
    assert (await client.get("/api/admin/users", headers=_h(utok))).status_code == 403
    assert (await client.get("/api/admin/users")).status_code == 401


async def test_bootstrap_created_admin_can_login(client, bootstrap_admin):
    """引导管理员：启动引导创建的账号能用配置密码登录且 role=admin。"""
    r = await client.post(
        "/api/auth/login", json={"username": bootstrap_admin, "password": "password123"}
    )
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"


async def test_list_users(client, atok, monkeypatch):
    await _user(client, "alice")
    await _user(client, "bob")
    
    r = await client.get("/api/admin/users", headers=_h(atok))
    assert r.status_code == 200
    names = {u["username"] for u in r.json()}
    assert {"alice", "bob"} <= names


async def test_list_users_includes_role_field(client, atok, monkeypatch):
    await _user(client, "alice")
    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    assert all("role" in u for u in users)
    root = next(u for u in users if u["username"] == "testadmin")
    assert root["role"] == "admin"


async def test_list_users_includes_conversation_count(client, atok, monkeypatch):
    utok = await _user(client)
    
    # 建一个已发布 Agent 并开会话
    aid = (
        await client.post("/api/agents", headers=_h(atok), json={"slug": "b1", "name": "B1"})
    ).json()["id"]
    await client.post(f"/api/agents/{aid}/publish", headers=_h(atok))
    await client.post(
        "/api/chat/conversations", headers=_h(utok), json={"agent_slug": "b1"}
    )

    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    alice = next(u for u in users if u["username"] == "alice")
    assert alice["conversation_count"] == 1


async def test_disable_user(client, atok, monkeypatch):
    utok = await _user(client)
    
    uid = next(
        u["id"] for u in (await client.get("/api/admin/users", headers=_h(atok))).json()
        if u["username"] == "alice"
    )
    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"disabled": True}
    )
    assert r.status_code == 200
    assert r.json()["disabled"] is True

    # 被禁用后无法再访问需要登录的接口
    r = await client.get("/api/chat/agents", headers=_h(utok))
    assert r.status_code == 401


async def test_change_role(client, atok, monkeypatch):
    """v2 新增：管理员可调整用户角色。"""
    utok = await _user(client, "upme")
    uid = next(
        u["id"] for u in (await client.get("/api/admin/users", headers=_h(atok))).json()
        if u["username"] == "upme"
    )

    r = await client.patch(f"/api/admin/users/{uid}", headers=_h(atok), json={"role": "admin"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    # 提权后该用户可通过管理员接口
    assert (await client.get("/api/admin/users", headers=_h(utok))).status_code == 200

    # 再降回 user
    r = await client.patch(f"/api/admin/users/{uid}", headers=_h(atok), json={"role": "user"})
    assert r.json()["role"] == "user"
    assert (await client.get("/api/admin/users", headers=_h(utok))).status_code == 403


async def test_cannot_change_own_role(client, atok, monkeypatch):
    """新规则（修复 7）：任何管理员都不能改自己的角色，先于"最后一名管理员"判定。"""
    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    me = next(u for u in users if u["username"] == "testadmin")
    r = await client.patch(
        f"/api/admin/users/{me['id']}", headers=_h(atok), json={"role": "user"}
    )
    assert r.status_code == 403
    assert "自己的权限" in r.json()["detail"]


async def test_invalid_role_422(client, atok, monkeypatch):
    await _user(client, "rolecheck")
    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    target = next(u for u in users if u["username"] == "rolecheck")
    r = await client.patch(
        f"/api/admin/users/{target['id']}", headers=_h(atok), json={"role": "superadmin"}
    )
    assert r.status_code == 422


async def test_enable_user(client, atok, monkeypatch):
    utok = await _user(client)
    uid = next(
        u["id"] for u in (await client.get("/api/admin/users", headers=_h(atok))).json()
        if u["username"] == "alice"
    )

    await client.patch(f"/api/admin/users/{uid}", headers=_h(atok), json={"disabled": True})
    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"disabled": False}
    )
    assert r.json()["disabled"] is False
    assert (await client.get("/api/chat/agents", headers=_h(utok))).status_code == 200


async def test_update_display_name(client, atok, monkeypatch):
    await _user(client)
    uid = next(
        u["id"] for u in (await client.get("/api/admin/users", headers=_h(atok))).json()
        if u["username"] == "alice"
    )

    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"display_name": "爱丽丝"}
    )
    assert r.json()["display_name"] == "爱丽丝"


async def test_update_unknown_user_404(client, atok, monkeypatch):
    r = await client.patch(
        "/api/admin/users/9999", headers=_h(atok), json={"disabled": True}
    )
    assert r.status_code == 404


async def test_user_cannot_update_self(client, atok):
    """普通用户不能调用管理接口改自己。"""
    utok = await _user(client)
    r = await client.patch(
        "/api/admin/users/1", headers=_h(utok), json={"disabled": False}
    )
    assert r.status_code == 403


# ── 定时清理任务 ──────────────────────────────────────────
async def test_cleanup_task_starts_and_stops():
    """清理任务能正常启停，不在启动时阻塞。"""
    import asyncio

    from app.scheduler import CleanupTask

    task = CleanupTask()
    task.start()
    assert task._task is not None
    await asyncio.sleep(0.05)
    await task.stop()
    assert task._task is None


async def test_cleanup_task_idempotent_start():
    from app.scheduler import CleanupTask

    task = CleanupTask()
    task.start()
    first = task._task
    task.start()  # 重复 start 不应新建
    assert task._task is first
    await task.stop()
