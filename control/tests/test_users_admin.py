"""用户管理接口测试。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    from app.security import create_access_token

    return create_access_token("boss", "admin")


async def _user(client, name="alice"):
    r = await client.post(
        "/api/auth/register", json={"username": name, "password": "password123"}
    )
    return r.json()["access_token"]


async def test_list_users_requires_admin(client):
    utok = await _user(client)
    assert (await client.get("/api/admin/users", headers=_h(utok))).status_code == 403
    assert (await client.get("/api/admin/users")).status_code == 401


async def test_list_users(client, monkeypatch):
    await _user(client, "alice")
    await _user(client, "bob")
    atok = _admin_token(monkeypatch)

    r = await client.get("/api/admin/users", headers=_h(atok))
    assert r.status_code == 200
    names = {u["username"] for u in r.json()}
    assert {"alice", "bob"} <= names


async def test_list_users_includes_conversation_count(client, monkeypatch):
    utok = await _user(client)
    atok = _admin_token(monkeypatch)

    # 建一个已发布 Agent 并开会话
    await client.post(
        "/api/admin/agents", headers=_h(atok), json={"slug": "b1", "name": "B1"}
    )
    aid = (await client.get("/api/admin/agents", headers=_h(atok))).json()[0]["id"]
    await client.post(f"/api/admin/agents/{aid}/publish", headers=_h(atok))
    await client.post(
        "/api/chat/conversations", headers=_h(utok), json={"agent_slug": "b1"}
    )

    users = (await client.get("/api/admin/users", headers=_h(atok))).json()
    alice = next(u for u in users if u["username"] == "alice")
    assert alice["conversation_count"] == 1


async def test_disable_user(client, monkeypatch):
    utok = await _user(client)
    atok = _admin_token(monkeypatch)

    uid = (await client.get("/api/admin/users", headers=_h(atok))).json()[0]["id"]
    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"disabled": True}
    )
    assert r.status_code == 200
    assert r.json()["disabled"] is True

    # 被禁用后无法再访问需要登录的接口
    r = await client.get("/api/chat/agents", headers=_h(utok))
    assert r.status_code == 401


async def test_enable_user(client, monkeypatch):
    utok = await _user(client)
    atok = _admin_token(monkeypatch)
    uid = (await client.get("/api/admin/users", headers=_h(atok))).json()[0]["id"]

    await client.patch(f"/api/admin/users/{uid}", headers=_h(atok), json={"disabled": True})
    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"disabled": False}
    )
    assert r.json()["disabled"] is False
    assert (await client.get("/api/chat/agents", headers=_h(utok))).status_code == 200


async def test_update_display_name(client, monkeypatch):
    await _user(client)
    atok = _admin_token(monkeypatch)
    uid = (await client.get("/api/admin/users", headers=_h(atok))).json()[0]["id"]

    r = await client.patch(
        f"/api/admin/users/{uid}", headers=_h(atok), json={"display_name": "爱丽丝"}
    )
    assert r.json()["display_name"] == "爱丽丝"


async def test_update_unknown_user_404(client, monkeypatch):
    atok = _admin_token(monkeypatch)
    r = await client.patch(
        "/api/admin/users/9999", headers=_h(atok), json={"disabled": True}
    )
    assert r.status_code == 404


async def test_user_cannot_update_self(client):
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
