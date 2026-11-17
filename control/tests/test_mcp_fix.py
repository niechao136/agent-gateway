"""MCP 测试端点降级测试（修复 3：新增 MCP 后测试失败）。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _user_token(client):
    r = await client.post(
        "/api/auth/register", json={"username": "testfix", "password": "password123"}
    )
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post(
        "/api/auth/login", json={"username": "testfix", "password": "password123"}
    )
    return r.json()["access_token"]


async def test_mcp_test_falls_back_when_dashboard_has_no_endpoint(client, monkeypatch):
    """dashboard 没有 test 端点（抛异常）时，应降级本地校验而非报错。"""
    import app.hermes.client as client_mod
    from app.hermes.client import DashboardError

    tok = await _user_token(client)
    sid = (
        await client.post(
            "/api/mcp",
            headers=_h(tok),
            json={
                "name": "http-test",
                "transport": "http",
                "url": "http://127.0.0.1:59999",
                "auth_type": "none",
            },
        )
    ).json()["id"]

    class BrokenDashboard:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def try_endpoint(self, *a, **kw):
            raise DashboardError("404 或 405: Not Found")

    monkeypatch.setattr(client_mod, "DashboardClient", BrokenDashboard)

    r = await client.post(f"/api/mcp/{sid}/test", headers=_h(tok))
    assert r.status_code == 200
    b = r.json()
    # 关键：不再因 dashboard 报错而 ok=False
    assert b["source"] in ("local-probe", "dashboard")
    # 本地探测会如实报告连接失败，但接口本身 200（测试功能可用）
    assert "detail" in b or "ok" in b


async def test_mcp_test_stdio_command_check(client, monkeypatch):
    """stdio 类型用 command 存在性校验，dashboard 不可用时也不报错。"""
    import app.hermes.client as client_mod
    from app.hermes.client import DashboardError

    tok = await _user_token(client)
    sid = (
        await client.post(
            "/api/mcp",
            headers=_h(tok),
            json={"name": "stdio-test", "transport": "stdio", "command": "echo"},
        )
    ).json()["id"]

    class BrokenDashboard:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def try_endpoint(self, *a, **kw):
            raise DashboardError("no endpoint")

    monkeypatch.setattr(client_mod, "DashboardClient", BrokenDashboard)

    r = await client.post(f"/api/mcp/{sid}/test", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["ok"] is True  # echo 在 PATH 中
