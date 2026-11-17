"""toolset catalog 接口测试（批次 2）。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def test_catalog_requires_login(client):
    assert (await client.get("/api/toolsets")).status_code == 401


async def test_catalog_returns_toolsets(client):
    """dashboard 优先、静态降级，两者都必须返回带 name/risk/tools 的 toolset 列表。"""
    tok = (
        await client.post(
            "/api/auth/register", json={"username": "tsuser", "password": "password123"}
        )
    ).json()["access_token"]
    r = await client.get("/api/toolsets", headers=_h(tok))
    assert r.status_code == 200
    b = r.json()
    assert b["source"] in ("dashboard", "static")
    items = b["toolsets"]
    assert isinstance(items, list) and items
    for item in items:
        assert "name" in item
        assert "tools" in item
    names = {i["name"] for i in items}
    # 关键 toolset 必须在目录里（前端网格数据源）
    assert {"terminal", "web", "file", "browser"} <= names
