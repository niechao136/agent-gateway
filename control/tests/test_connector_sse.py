"""连接器 SSE 端点测试（批次 4）。

ASGITransport 下 StreamingResponse 不是真流式，故直接读生成器首帧。
生成器内部用 SessionLocal，需重定向到测试内存库。
"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def test_events_requires_login(client):
    assert (await client.get("/api/connectors/events")).status_code == 401


async def test_events_generator_emits_snapshot(monkeypatch, session_factory):
    """SSE 生成器首帧应是连接器数组快照。"""
    import json

    from app.models import User
    from app.routes import connectors as connectors_mod

    monkeypatch.setattr(connectors_mod, "SessionLocal", session_factory)

    user = User(id=1, username="sse", role="user", password_hash="x")
    resp = await connectors_mod.connector_events(user=user, session=None)
    assert resp.media_type == "text/event-stream"

    gen = resp.body_iterator
    try:
        first = await gen.__anext__()
    finally:
        await gen.aclose()

    text = first.decode("utf-8") if isinstance(first, bytes) else first
    assert text.startswith("data: "), f"首帧不是 data: {text[:200]}"
    payload = json.loads(text[len("data: "):].strip())
    assert isinstance(payload, list)
