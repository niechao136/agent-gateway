"""会话归属与 SSE 翻译测试。

重点（SPEC §5.1 / §5.4）：
- 用户 A 绝不能看到/操作 用户 B 的会话
- SSE 解析器必须跳过 keepalive 注释行
- 必须解析 hermes 的**真实**事件格式（assistant.delta / assistant.completed）

真实报文来自实测抓包（见 REAL_SSE_SAMPLE）。
"""

import json

import pytest

from app.hermes import chat_proxy
from app.hermes import conversations as conv_svc

pytestmark = pytest.mark.asyncio

# 实测抓到的真实 hermes SSE 报文（含 keepalive）
REAL_SSE_SAMPLE = (
    'event: run.started\n'
    'data: {"user_message":{"role":"user","content":"hi"},"session_id":"s","run_id":"run_1","seq":1}\n'
    "\n"
    'event: message.started\n'
    'data: {"message":{"id":"msg_1","role":"assistant"},"seq":2}\n'
    "\n"
    ": keepalive\n"
    "\n"
    'event: assistant.delta\n'
    'data: {"delta":"你好","message_id":"msg_1","seq":3}\n'
    "\n"
    'event: assistant.delta\n'
    'data: {"delta":"世界","message_id":"msg_1","seq":4}\n'
    "\n"
    'event: assistant.completed\n'
    'data: {"content":"你好世界","message_id":"msg_1","completed":true,"seq":5}\n'
    "\n"
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _user(client, name="alice"):
    r = await client.post(
        "/api/auth/register", json={"username": name, "password": "password123"}
    )
    return r.json()["access_token"]


async def _pub_agent(client, atok):
    await client.post(
        "/api/agents", headers=_h(atok), json={"slug": "bot1", "name": "Bot1"}
    )
    agents = (await client.get("/api/agents", headers=_h(atok))).json()
    aid = next(a["id"] for a in agents if a["slug"] == "bot1")
    await client.post(f"/api/agents/{aid}/publish", headers=_h(atok))
    return "bot1"


def _gw():
    from app.hermes.gateway import GatewayClient

    return GatewayClient


# ── SSE 解析（纯函数，最关键）──────────────────────────────
def test_parse_skips_keepalive_comment():
    """★ keepalive 行 `: keepalive` 必须被跳过，不能当数据。"""
    assert chat_proxy.parse_sse_block(": keepalive") == (None, None)


def test_parse_keepalive_inside_block():
    ev, data = chat_proxy.parse_sse_block(
        ': keepalive\nevent: token\ndata: {"content":"hi"}'
    )
    assert ev == "token"
    assert json.loads(data)["content"] == "hi"


def test_parse_event_and_data():
    ev, data = chat_proxy.parse_sse_block('event: token\ndata: {"content":"你好"}')
    assert ev == "token"
    assert json.loads(data) == {"content": "你好"}


def test_parse_empty_block():
    assert chat_proxy.parse_sse_block("") == (None, None)


# ── SSE 翻译 ──────────────────────────────────────────────
async def _collect(frames):
    return [f.decode() async for f in frames]


async def _translate(blocks: list[bytes], thread_id="s"):
    async def src():
        for b in blocks:
            yield b

    return "".join(await _collect(chat_proxy.translate_stream(src(), thread_id=thread_id)))


async def test_translate_real_hermes_format():
    """★ 用实测真实报文验证：事件名是 assistant.delta，增量在顶层 delta。"""
    joined = await _translate([REAL_SSE_SAMPLE.encode()], thread_id="real1")
    assert joined.count("event: token") == 2, joined
    assert "你好" in joined and "世界" in joined
    assert "event: done" in joined
    assert "event: error" not in joined


async def test_translate_keepalive_does_not_break():
    """★ keepalive 不能中断解析。"""
    async def src():
        yield b'event: assistant.delta\ndata: {"delta":"A"}\n\n'
        yield b": keepalive\n\n"
        yield b": keepalive\n\n"
        yield b'event: assistant.delta\ndata: {"delta":"B"}\n\n'
        yield b'event: assistant.completed\ndata: {"content":"AB"}\n\n'

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="k1")))
    assert "A" in joined and "B" in joined
    assert "event: done" in joined
    assert "event: error" not in joined


async def test_translate_openai_style_chunk_still_works():
    """兼容 OpenAI 风格（防御性）。"""
    joined = await _translate(
        [b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'], thread_id="o1"
    )
    assert "Hi" in joined
    assert "event: done" in joined


async def test_translate_non_streaming_uses_completed_content():
    """非流式模型只发 assistant.completed：要把 content 当一次 token 发出。"""
    async def src():
        yield 'event: assistant.completed\ndata: {"content":"完整回答"}\n\n'.encode()

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="n1")))
    assert "event: token" in joined
    assert "完整回答" in joined
    assert "event: done" in joined


async def test_translate_handles_crlf():
    async def src():
        yield b'event: assistant.delta\r\ndata: {"delta":"X"}\r\n\r\n'

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="c1")))
    assert "X" in joined


async def test_translate_run_failed_emits_error():
    async def src():
        yield b'event: run.failed\ndata: {"error":"model unavailable"}\n\n'

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="f1")))
    assert "event: error" in joined
    assert "model unavailable" in joined


async def test_translate_emits_error_on_exception():
    async def src():
        yield b'event: assistant.delta\ndata: {"delta":"ok"}\n\n'
        raise RuntimeError("boom")

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="e1")))
    assert "event: error" in joined


async def test_translate_tool_progress():
    async def src():
        yield b'event: tool.progress\ndata: {"tool_name":"web_search","delta":"searching"}\n\n'
        yield b'event: tool.completed\ndata: {"tool_name":"web_search","output":"3 results"}\n\n'

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="t1")))
    assert "event: tool_start" in joined
    assert "event: tool_end" in joined
    assert "web_search" in joined


async def test_translate_empty_stream_is_error():
    async def src():
        if False:
            yield b""

    joined = "".join(await _collect(chat_proxy.translate_stream(src(), thread_id="z1")))
    assert "event: error" in joined


# ── 会话归属（安全核心）──────────────────────────────────
async def test_create_conversation(client, atok):
    tok = await _user(client)
    await _pub_agent(client, atok)
    r = await client.post(
        "/api/chat/conversations",
        headers=_h(tok),
        json={"agent_slug": "bot1", "first_message": "帮我写个函数"},
    )
    assert r.status_code == 201
    b = r.json()
    assert b["hermes_session_id"].startswith("ag_u")
    assert b["title"] == "帮我写个函数"


async def test_conversation_requires_published_agent(client):
    tok = await _user(client)
    r = await client.post(
        "/api/chat/conversations", headers=_h(tok), json={"agent_slug": "nope"}
    )
    assert r.status_code == 404


async def test_user_cannot_see_others_conversations(client, atok):
    """★ 用户 B 的列表里不能出现 用户 A 的会话。"""
    a = await _user(client, "alice")
    b = await _user(client, "bob")
    await _pub_agent(client, atok)

    await client.post(
        "/api/chat/conversations", headers=_h(a), json={"agent_slug": "bot1"}
    )
    assert len((await client.get("/api/chat/conversations", headers=_h(a))).json()) == 1
    assert (await client.get("/api/chat/conversations", headers=_h(b))).json() == []


async def test_user_cannot_access_others_conversation_by_id(client, atok):
    """★ 猜 id 直接访问别人的会话必须 404（所有端点）。"""
    a = await _user(client, "alice")
    b = await _user(client, "bob")
    await _pub_agent(client, atok)

    cid = (
        await client.post(
            "/api/chat/conversations", headers=_h(a), json={"agent_slug": "bot1"}
        )
    ).json()["id"]

    for method, path, kw in (
        ("get", f"/api/chat/conversations/{cid}", {}),
        ("get", f"/api/chat/conversations/{cid}/messages", {}),
        ("delete", f"/api/chat/conversations/{cid}", {}),
        ("post", f"/api/chat/conversations/{cid}/restore", {}),
        ("post", f"/api/chat/conversations/{cid}/stream", {"json": {"message": "hi"}}),
    ):
        r = await getattr(client, method)(path, headers=_h(b), **kw)
        assert r.status_code == 404, f"{method} {path} 应为 404，实际 {r.status_code}"

    # A 自己仍可访问
    assert (
        await client.get(f"/api/chat/conversations/{cid}", headers=_h(a))
    ).status_code == 200


async def test_soft_delete_hides_but_keeps_hermes_session(client, atok):
    """★ 软删：列表消失，但 hermes 侧 session 仍在、未被调用删除。"""
    tok = await _user(client)
    await _pub_agent(client, atok)
    conv = (
        await client.post(
            "/api/chat/conversations", headers=_h(tok), json={"agent_slug": "bot1"}
        )
    ).json()
    sid = conv["hermes_session_id"]

    assert (
        await client.delete(f"/api/chat/conversations/{conv['id']}", headers=_h(tok))
    ).status_code == 204
    assert (await client.get("/api/chat/conversations", headers=_h(tok))).json() == []
    assert sid in _gw().store
    assert not any(c == ("delete", sid) for c in _gw().calls)


async def test_restore_conversation(client, atok):
    tok = await _user(client)
    await _pub_agent(client, atok)
    conv = (
        await client.post(
            "/api/chat/conversations", headers=_h(tok), json={"agent_slug": "bot1"}
        )
    ).json()

    await client.delete(f"/api/chat/conversations/{conv['id']}", headers=_h(tok))
    r = await client.post(
        f"/api/chat/conversations/{conv['id']}/restore", headers=_h(tok)
    )
    assert r.status_code == 200
    assert (
        len((await client.get("/api/chat/conversations", headers=_h(tok))).json()) == 1
    )


async def test_stream_endpoint_returns_sse(client, atok):
    tok = await _user(client)
    await _pub_agent(client, atok)
    conv = (
        await client.post(
            "/api/chat/conversations", headers=_h(tok), json={"agent_slug": "bot1"}
        )
    ).json()

    _gw().stream_frames = [
        b'event: assistant.delta\ndata: {"delta":"hi"}\n\n',
        b'event: assistant.completed\ndata: {"content":"hi"}\n\n',
    ]
    r = await client.post(
        f"/api/chat/conversations/{conv['id']}/stream",
        headers=_h(tok),
        json={"message": "hello"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: token" in r.text
    assert "event: done" in r.text


# ── 工具函数 ──────────────────────────────────────────────
def test_derive_title_truncates():
    assert conv_svc.derive_title("短标题") == "短标题"
    t = conv_svc.derive_title("x" * 100, limit=40)
    assert len(t) <= 40
    assert t.endswith("…")


def test_derive_title_empty():
    assert conv_svc.derive_title("   ") == "新会话"


def test_new_session_id_unique_and_prefixed():
    a = conv_svc.new_session_id(1)
    b = conv_svc.new_session_id(1)
    assert a != b
    assert a.startswith("ag_u1_")
