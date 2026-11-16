"""模型模板测试：CRUD + 应用到 profile 的 config.yaml。"""

import pytest
import yaml

from app.hermes.a2a import profile_config_path
from app.hermes.models_cfg import apply_model, read_model

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _admin_token():
    from app.security import create_access_token

    return create_access_token("admin", "admin")


# ── 文件写入（真实文件）────────────────────────────────────
def _make_profile(root, name="p1"):
    p = profile_config_path(name, str(root))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "model:\n  default: old-model\n  provider: old\n"
        "a2a_agents:\n  peer:\n    url: http://x\n_config_version: 53\n",
        encoding="utf-8",
    )
    return p


def test_apply_model_updates_section(tmp_path):
    p = _make_profile(tmp_path)
    apply_model(
        "p1",
        str(tmp_path),
        model="gemini-2.5-flash",
        provider="custom",
        base_url="http://127.0.0.1:8899/v1beta/openai",
        api_key="k123",
    )
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert cfg["model"]["default"] == "gemini-2.5-flash"
    assert cfg["model"]["provider"] == "custom"
    assert cfg["model"]["api_key"] == "k123"


def test_apply_model_preserves_other_sections(tmp_path):
    p = _make_profile(tmp_path)
    apply_model("p1", str(tmp_path), model="m", provider="custom")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert cfg["a2a_agents"]["peer"]["url"] == "http://x"
    assert cfg["_config_version"] == 53


def test_read_model_hides_api_key(tmp_path):
    _make_profile(tmp_path)
    apply_model("p1", str(tmp_path), model="m", provider="custom", api_key="secret")
    got = read_model("p1", str(tmp_path))
    assert got["default"] == "m"
    assert "api_key" not in got


def test_apply_model_missing_profile(tmp_path):
    from app.hermes.a2a import A2AError

    with pytest.raises(A2AError):
        apply_model("nope", str(tmp_path), model="m")


# ── HTTP 接口 ────────────────────────────────────────────
async def _make_agent(client, slug="mm1") -> int:
    atok = _admin_token()
    await client.post(
        "/api/admin/agents", headers=_h(atok), json={"slug": slug, "name": slug}
    )
    agents = (await client.get("/api/admin/agents", headers=_h(atok))).json()
    return next(a["id"] for a in agents if a["slug"] == slug)


async def test_create_template(client):
    r = await client.post(
        "/api/admin/models",
        headers=_h(_admin_token()),
        json={"name": "t1", "model": "gemini-2.5-flash", "provider": "custom"},
    )
    assert r.status_code == 201
    b = r.json()
    assert b["name"] == "t1"
    assert b["has_api_key"] is False


async def test_create_with_key_hides_value(client):
    r = await client.post(
        "/api/admin/models",
        headers=_h(_admin_token()),
        json={"name": "t2", "model": "m", "api_key": "supersecret"},
    )
    assert r.json()["has_api_key"] is True
    # 响应里不能出现明文 key
    assert "supersecret" not in r.text


async def test_duplicate_template_409(client):
    h = _h(_admin_token())
    body = {"name": "dup", "model": "m"}
    assert (await client.post("/api/admin/models", headers=h, json=body)).status_code == 201
    assert (await client.post("/api/admin/models", headers=h, json=body)).status_code == 409


async def test_list_and_delete(client):
    h = _h(_admin_token())
    tid = (
        await client.post("/api/admin/models", headers=h, json={"name": "x", "model": "m"})
    ).json()["id"]
    assert len((await client.get("/api/admin/models", headers=h)).json()) == 1
    assert (await client.delete(f"/api/admin/models/{tid}", headers=h)).status_code == 204
    assert (await client.get("/api/admin/models", headers=h)).json() == []


async def test_update_template(client):
    h = _h(_admin_token())
    tid = (
        await client.post("/api/admin/models", headers=h, json={"name": "u", "model": "m1"})
    ).json()["id"]
    r = await client.patch(
        f"/api/admin/models/{tid}", headers=h, json={"model": "m2", "provider": "openai"}
    )
    assert r.json()["model"] == "m2"
    assert r.json()["provider"] == "openai"


async def test_apply_to_agent(client, monkeypatch):
    from app.routes import models as route

    monkeypatch.setattr(route, "apply_model", lambda *a, **kw: {"path": "/x"})
    h = _h(_admin_token())
    tid = (
        await client.post(
            "/api/admin/models",
            headers=h,
            json={"name": "ap", "model": "gemini-2.5-flash", "provider": "custom"},
        )
    ).json()["id"]
    aid = await _make_agent(client)

    r = await client.post(f"/api/admin/agents/{aid}/apply-model/{tid}", headers=h)
    assert r.status_code == 200
    assert r.json()["applied"] is True


async def test_apply_unknown_agent_404(client):
    h = _h(_admin_token())
    tid = (
        await client.post("/api/admin/models", headers=h, json={"name": "z", "model": "m"})
    ).json()["id"]
    r = await client.post(f"/api/admin/agents/9999/apply-model/{tid}", headers=h)
    assert r.status_code == 404


async def test_models_requires_admin(client):
    utok = (
        await client.post(
            "/api/auth/register", json={"username": "muser2", "password": "password123"}
        )
    ).json()["access_token"]
    assert (await client.get("/api/admin/models", headers=_h(utok))).status_code == 403
