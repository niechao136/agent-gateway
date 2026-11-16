"""A2A 端点配置测试。

覆盖：校验、CRUD、config.yaml 写入、删除后清理。
真实写文件到临时目录，不依赖 hermes 容器。
"""

import pytest
import yaml

from app.hermes.a2a import (
    A2AError,
    apply_a2a_endpoints,
    profile_config_path,
    read_a2a_section,
    validate_endpoint,
)

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _admin_token():
    from app.security import create_access_token

    return create_access_token("admin", "admin")


# ── 校验（纯函数）──────────────────────────────────────────
def test_validate_ok():
    validate_endpoint("researcher", "http://localhost:9900")


def test_validate_bad_name():
    for bad in ("has space", "", "a" * 100, "-leading", "中文"):
        with pytest.raises(A2AError):
            validate_endpoint(bad, "http://x.com")


def test_validate_bad_url():
    for bad in ("ftp://x.com", "x.com", "not a url", ""):
        with pytest.raises(A2AError):
            validate_endpoint("ok", bad)


# ── 文件写入（真实文件）────────────────────────────────────
def _make_profile(root, name="p1"):
    p = profile_config_path(name, str(root))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "model:\n  default: gemini-2.5-flash\n  provider: custom\n_config_version: 53\n",
        encoding="utf-8",
    )
    return p


def test_apply_creates_section(tmp_path):
    p = _make_profile(tmp_path)
    apply_a2a_endpoints(
        "p1",
        str(tmp_path),
        [{"name": "r1", "url": "http://a.com", "capabilities": ["web"], "timeout": 60}],
    )
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert cfg["a2a_agents"]["r1"]["url"] == "http://a.com"
    assert cfg["a2a_agents"]["r1"]["capabilities"] == ["web"]
    assert cfg["a2a_agents"]["r1"]["timeout"] == 60


def test_apply_preserves_other_sections(tmp_path):
    p = _make_profile(tmp_path)
    apply_a2a_endpoints(
        "p1", str(tmp_path), [{"name": "r1", "url": "http://a.com"}]
    )
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert cfg["model"]["default"] == "gemini-2.5-flash"
    assert cfg["_config_version"] == 53


def test_apply_replaces_existing(tmp_path):
    _make_profile(tmp_path)
    apply_a2a_endpoints(
        "p1", str(tmp_path), [{"name": "old", "url": "http://old.com"}]
    )
    apply_a2a_endpoints(
        "p1", str(tmp_path), [{"name": "new", "url": "http://new.com"}]
    )
    section = read_a2a_section("p1", str(tmp_path))
    assert "old" not in section
    assert section["new"]["url"] == "http://new.com"


def test_apply_empty_removes_section(tmp_path):
    p = _make_profile(tmp_path)
    apply_a2a_endpoints("p1", str(tmp_path), [{"name": "r1", "url": "http://a.com"}])
    apply_a2a_endpoints("p1", str(tmp_path), [])
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "a2a_agents" not in cfg


def test_apply_missing_profile_raises(tmp_path):
    with pytest.raises(A2AError):
        apply_a2a_endpoints("nope", str(tmp_path), [{"name": "x", "url": "http://a.com"}])


def test_read_missing_section(tmp_path):
    _make_profile(tmp_path)
    assert read_a2a_section("p1", str(tmp_path)) == {}


# ── HTTP 接口 ────────────────────────────────────────────
async def _make_agent(client, slug="b1") -> int:
    atok = _admin_token()
    await client.post(
        "/api/admin/agents", headers=_h(atok), json={"slug": slug, "name": slug}
    )
    agents = (await client.get("/api/admin/agents", headers=_h(atok))).json()
    return next(a["id"] for a in agents if a["slug"] == slug)


async def test_create_endpoint(client, monkeypatch):
    from app.routes import agent_a2a as route

    calls = {}
    monkeypatch.setattr(
        route, "apply_a2a_endpoints", lambda *a, **kw: calls.setdefault("ok", True) or {}
    )
    aid = await _make_agent(client)
    r = await client.post(
        f"/api/admin/agents/{aid}/a2a",
        headers=_h(_admin_token()),
        json={"name": "r1", "url": "http://a.com", "capabilities": ["web"]},
    )
    assert r.status_code == 201
    assert r.json()["endpoint"]["name"] == "r1"
    assert r.json()["apply_error"] is None


async def test_create_duplicate_name_409(client, monkeypatch):
    from app.routes import agent_a2a as route

    monkeypatch.setattr(route, "apply_a2a_endpoints", lambda *a, **kw: {})
    aid = await _make_agent(client)
    body = {"name": "dup", "url": "http://a.com"}
    h = _h(_admin_token())
    assert (await client.post(f"/api/admin/agents/{aid}/a2a", headers=h, json=body)).status_code == 201
    assert (await client.post(f"/api/admin/agents/{aid}/a2a", headers=h, json=body)).status_code == 409


async def test_create_invalid_url_422(client):
    aid = await _make_agent(client)
    r = await client.post(
        f"/api/admin/agents/{aid}/a2a",
        headers=_h(_admin_token()),
        json={"name": "bad", "url": "ftp://x"},
    )
    assert r.status_code == 422


async def test_apply_error_is_reported_not_raised(client, monkeypatch):
    """写入 config 失败时，DB 仍保存，接口返回 apply_error。"""
    from app.hermes.a2a import A2AError
    from app.routes import agent_a2a as route

    def boom(*a, **kw):
        raise A2AError("文件不存在")

    monkeypatch.setattr(route, "apply_a2a_endpoints", boom)
    aid = await _make_agent(client)
    r = await client.post(
        f"/api/admin/agents/{aid}/a2a",
        headers=_h(_admin_token()),
        json={"name": "x1", "url": "http://a.com"},
    )
    assert r.status_code == 201
    assert r.json()["apply_error"] == "文件不存在"
    # 记录仍然存在
    lst = await client.get(f"/api/admin/agents/{aid}/a2a", headers=_h(_admin_token()))
    assert len(lst.json()) == 1


async def test_delete_endpoint(client, monkeypatch):
    from app.routes import agent_a2a as route

    monkeypatch.setattr(route, "apply_a2a_endpoints", lambda *a, **kw: {})
    aid = await _make_agent(client)
    h = _h(_admin_token())
    eid = (
        await client.post(
            f"/api/admin/agents/{aid}/a2a", headers=h, json={"name": "d1", "url": "http://a.com"}
        )
    ).json()["endpoint"]["id"]

    assert (await client.delete(f"/api/admin/agents/{aid}/a2a/{eid}", headers=h)).status_code == 204
    assert (await client.get(f"/api/admin/agents/{aid}/a2a", headers=h)).json() == []


async def test_a2a_requires_admin(client):
    utok = (
        await client.post(
            "/api/auth/register", json={"username": "user2", "password": "password123"}
        )
    ).json()["access_token"]
    aid = await _make_agent(client)
    assert (
        await client.get(f"/api/admin/agents/{aid}/a2a", headers=_h(utok))
    ).status_code == 403
