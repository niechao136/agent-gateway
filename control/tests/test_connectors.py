"""连接器 CRUD 与 runner 框架测试（批次 3）。平台 SDK 全部 mock。"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


TG_BODY = {
    "name": "my-tg",
    "platform": "telegram",
    "agent_id": 0,  # 运行时替换
    "credentials": {"bot_token": "123:ABC-DEF"},
}


async def _user_token(client, name="connuser"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "password123"})
    if r.status_code == 201:
        return r.json()["access_token"]
    r = await client.post("/api/auth/login", json={"username": name, "password": "password123"})
    return r.json()["access_token"]


async def _setup(client, slug="conbot"):
    tok = await _user_token(client)
    r = await client.post("/api/agents", headers=_h(tok), json={"slug": slug, "name": slug})
    aid = r.json()["id"]
    await client.post(f"/api/agents/{aid}/publish", headers=_h(tok))
    return tok, aid


async def test_create_connector_cred_redacted(client):
    tok, aid = await _setup(client)
    r = await client.post(
        "/api/connectors", headers=_h(tok), json={**TG_BODY, "agent_id": aid}
    )
    assert r.status_code == 201
    b = r.json()
    assert b["platform"] == "telegram"
    # bot_token 脱敏：明文不出现在响应
    assert "ABC-DEF" not in b["credentials"]["bot_token"]
    assert "•••" in b["credentials"]["bot_token"]
    # 启用即拉起 runner（FakeRunner 下状态可见）
    assert b["runtime"]["state"] in ("connecting", "connected", "error")


async def test_missing_credentials_422(client):
    tok, aid = await _setup(client, slug="nocred")
    r = await client.post(
        "/api/connectors",
        headers=_h(tok),
        json={"name": "bad-tg", "platform": "telegram", "agent_id": aid, "credentials": {}},
    )
    assert r.status_code == 422
    assert "bot_token" in r.json()["detail"]

    # 未知平台
    r = await client.post(
        "/api/connectors",
        headers=_h(tok),
        json={"name": "bad", "platform": "discord", "agent_id": aid, "credentials": {}},
    )
    assert r.status_code == 422


async def test_cannot_bind_others_agent(client):
    t1 = await _user_token(client, "connown")
    t2 = await _user_token(client, "connbind")
    aid1 = (
        await client.post("/api/agents", headers=_h(t1), json={"slug": "cown", "name": "c"})
    ).json()["id"]
    r = await client.post(
        "/api/connectors", headers=_h(t2), json={**TG_BODY, "agent_id": aid1}
    )
    assert r.status_code == 403


async def test_platform_field_validation(client):
    tok, aid = await _setup(client, slug="platv")
    r = await client.post(
        "/api/connectors",
        headers=_h(tok),
        json={**TG_BODY, "agent_id": aid, "platform": "qq"},
    )
    assert r.status_code == 422


async def test_update_restart_delete(client):
    from app.connectors.base import registry

    tok, aid = await _setup(client, slug="crudcon")
    cid = (
        await client.post(
            "/api/connectors", headers=_h(tok), json={**TG_BODY, "agent_id": aid}
        )
    ).json()["id"]

    # 修改凭证 → 重启
    r = await client.patch(
        f"/api/connectors/{cid}",
        headers=_h(tok),
        json={"credentials": {"bot_token": "999:NEW-TOKEN"}},
    )
    assert r.status_code == 200
    assert "NEW-TOKEN" not in r.json()["credentials"]["bot_token"]

    # restart
    r = await client.post(f"/api/connectors/{cid}/restart", headers=_h(tok))
    assert r.status_code == 200

    # delete → runner 停止
    assert (await client.delete(f"/api/connectors/{cid}", headers=_h(tok))).status_code == 204
    assert registry.status_of(cid) is None


async def test_list_includes_runtime(client):
    tok, aid = await _setup(client, slug="rtcon")
    cid = (
        await client.post(
            "/api/connectors", headers=_h(tok), json={**TG_BODY, "agent_id": aid}
        )
    ).json()["id"]
    rows = (await client.get("/api/connectors", headers=_h(tok))).json()
    mine = next(x for x in rows if x["id"] == cid)
    assert mine["runtime"]["state"] in ("connecting", "connected", "error")
    assert mine["agent_slug"] == "rtcon"


async def test_disabled_not_started(client):
    from app.connectors.base import registry

    registry._runners.clear()  # 全局单例，跨测试隔离
    tok, aid = await _setup(client, slug="offcon")
    cid = (
        await client.post(
            "/api/connectors",
            headers=_h(tok),
            json={**TG_BODY, "agent_id": aid, "enabled": False},
        )
    ).json()["id"]
    assert registry.status_of(cid) is None


# ── runner 单元测试：FakeRunner 验证消息管道 ────────────────
async def test_runner_message_pipeline(monkeypatch, session_factory, client):
    """on_message：平台消息 → hermes 会话 → 回发（全链路 mock）。

    on_message 用全局 SessionLocal；单测下重定向到测试内存库；
    Agent 通过 HTTP 接口真实创建（id 与绑定关系有效）。
    """
    from app.connectors import base as base_mod
    from app.connectors.base import ConnectorRunner, ConnectorRegistry
    from app.models import Connector

    monkeypatch.setattr(base_mod, "SessionLocal", session_factory)

    tok, aid = await _setup(client, slug="pipebot")

    class FakeRunner(ConnectorRunner):
        platform = "fake"
        sent: list = []

        async def _connect(self):
            pass

        async def _poll_loop(self):
            pass

        async def send(self, chat_id: str, text: str):
            FakeRunner.sent.append((chat_id, text))

    c = Connector(
        id=aid,  # 绑定真实存在的 Agent
        owner_id=1,
        name="fake",
        platform="fake",
        agent_id=aid,
        credentials={},
    )
    r = FakeRunner(c)

    async def _fake_frames():
        yield b'data: {"content": "hi"}\nevent: token\n\n'

    monkeypatch.setattr(
        "app.hermes.chat_proxy.translate_stream",
        lambda source, thread_id=None: _fake_frames(),
    )

    await r.on_message("chat-1", "user-1", "你好")
    assert FakeRunner.sent, "正常回复或错误提示都应回发"
    chat_id, text = FakeRunner.sent[0]
    assert chat_id == "chat-1"


async def test_telegram_ping_signature():
    """TelegramRunner.ping 只依赖 credentials.bot_token。"""
    from app.connectors.telegram import TelegramRunner
    from app.models import Connector

    c = Connector(id=1, owner_id=1, name="t", platform="telegram", agent_id=1,
                  credentials={"bot_token": "1:x"})
    r = TelegramRunner(c)
    assert r._token() == "1:x"
