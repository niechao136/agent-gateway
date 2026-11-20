"""A2A 服务端测试：Agent Card / JSON-RPC / API Key 鉴权。"""

import json

import pytest

from test_v1 import _h, _setup

pytestmark = pytest.mark.asyncio


async def test_agent_card_ok(client):
    _, aid, k = await _setup(client, slug="a2abot")
    r = await client.get("/a2a/a2abot/.well-known/agent-card.json")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["name"] == "a2abot"
    assert card["url"].endswith("/a2a/a2abot")
    assert any(i.get("protocolBinding") == "JSONRPC" for i in card["supportedInterfaces"])


async def test_agent_card_unpublished_404(client):
    # 只建不发
    r = await client.post(
        "/api/auth/register",
        json={"username": "a2au", "password": "password123"},
    )
    tok = r.json()["access_token"] if r.status_code == 201 else (
        await client.post(
            "/api/auth/login", json={"username": "a2au", "password": "password123"}
        )
    ).json()["access_token"]
    await client.post("/api/agents", headers=_h(tok), json={"slug": "drafta2a", "name": "d"})
    assert (await client.get("/a2a/drafta2a")).status_code == 404


async def test_rpc_requires_key(client):
    await _setup(client, slug="a2akey")
    r = await client.post(
        "/a2a/a2akey",
        json={"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}},
    )
    assert r.status_code == 401


async def test_rpc_send_message_ok(client):
    from test_chat import _gw

    _, aid, k = await _setup(client, slug="a2asend")
    # FakeGateway 产出 hermes 原始帧；translate_stream 才翻译成 token/done
    _gw().stream_frames = [
        b'event: assistant.delta\ndata: {"delta": "hello"}\n\n',
        b'event: assistant.completed\ndata: {"content": "hello"}\n\n',
    ]
    r = await client.post(
        "/a2a/a2asend",
        headers={"x-api-key": k},
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "message/send",
            "params": {
                "message": {"role": "user", "parts": [{"kind": "text", "text": "你好"}]}
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == 7
    # 结果里应包含模型回复文本（结构允许 message/artifacts 两种形态）
    assert "hello" in json.dumps(body["result"], ensure_ascii=False)


async def test_rpc_wrong_key_401(client):
    _, aid, k = await _setup(client, slug="a2awrong")
    r = await client.post(
        "/a2a/a2awrong",
        headers={"x-api-key": "agk_" + "0" * 32},
        json={"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}},
    )
    assert r.status_code == 401


async def test_rpc_invalid_jsonrpc_400(client):
    _, aid, k = await _setup(client, slug="a2abad")
    r = await client.post(
        "/a2a/a2abad",
        headers={"x-api-key": k},
        json={"jsonrpc": "1.0", "id": 1, "method": "message/send", "params": {}},
    )
    assert r.status_code == 400
