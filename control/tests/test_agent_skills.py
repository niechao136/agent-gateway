"""Agent Skill 配置接口测试。

Skills 由 conftest 的 Fixture 打桩，不连真实 dashboard。
"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}



async def _make_agent(client, atok, slug="b1") -> int:
    await client.post(
        "/api/agents", headers=_h(atok), json={"slug": slug, "name": slug}
    )
    agents = (await client.get("/api/agents", headers=_h(atok))).json()
    return next(a["id"] for a in agents if a["slug"] == slug)


@pytest.fixture(autouse=True)
def patch_skills(monkeypatch):
    """把 skills 模块的实现替换为内存版。"""
    import app.hermes.skills as sk
    import app.routes.agent_skills as route

    state: dict[str, bool] = {"codex": True, "web": False, "memory": True}

    async def fake_list(profile: str):
        return [
            {"name": k, "description": f"{k} desc", "category": "test", "enabled": v,
             "locked": False, "provenance": "bundled"}
            for k, v in state.items()
        ]

    async def fake_toggle(profile: str, name: str, enabled: bool):
        if name not in state:
            raise sk.SkillError("not found")
        state[name] = enabled
        return {"ok": True, "name": name, "enabled": enabled}

    async def fake_set(profile: str, names: list[str]):
        changed = 0
        for k in state:
            want = k in set(names)
            if state[k] != want:
                state[k] = want
                changed += 1
        return {"changed": changed}

    monkeypatch.setattr(route, "list_skills", fake_list)
    monkeypatch.setattr(route, "toggle_skill", fake_toggle)
    monkeypatch.setattr(route, "set_skills", fake_set)
    yield state


async def test_list_agent_skills(client, atok, patch_skills):
    aid = await _make_agent(client, atok)
    r = await client.get(f"/api/agents/{aid}/skills", headers=_h(atok))
    assert r.status_code == 200
    names = {s["name"] for s in r.json()}
    assert names == {"codex", "web", "memory"}


async def test_toggle_skill(client, atok, patch_skills):
    aid = await _make_agent(client, atok)
    r = await client.post(
        f"/api/agents/{aid}/skills/toggle",
        headers=_h(atok),
        json={"name": "codex", "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert patch_skills["codex"] is False


async def test_toggle_unknown_skill_404(client, atok, patch_skills):
    aid = await _make_agent(client, atok)
    r = await client.post(
        f"/api/agents/{aid}/skills/toggle",
        headers=_h(atok),
        json={"name": "nope", "enabled": True},
    )
    assert r.status_code == 404


async def test_replace_skills(client, atok, patch_skills):
    aid = await _make_agent(client, atok)
    r = await client.put(
        f"/api/agents/{aid}/skills",
        headers=_h(atok),
        json={"enabled": ["web"]},
    )
    assert r.status_code == 200
    enabled = {s["name"] for s in r.json() if s["enabled"]}
    assert enabled == {"web"}


async def test_skills_requires_login(client):
    assert (await client.get("/api/agents/1/skills")).status_code == 401


async def test_skills_unknown_agent_404(client, atok):
    r = await client.get("/api/agents/9999/skills", headers=_h(atok))
    assert r.status_code == 404
