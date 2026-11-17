"""管理员登录 + 历史消息规范化测试。"""

import pytest

from app.routes.chat import _flatten_content, _normalize_messages

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}


# ── 历史消息规范化（纯函数）────────────────────────────────
def test_normalize_filters_session_meta():
    """★ session_meta 是 hermes 内部记录，必须过滤。"""
    raw = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
        {"role": "session_meta", "content": None},
    ]
    out = _normalize_messages(raw)
    assert len(out) == 2
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert out[0]["content"] == "你好"


def test_normalize_filters_system_and_run_meta():
    raw = [
        {"role": "system", "content": "you are..."},
        {"role": "run_meta", "content": "x"},
        {"role": "user", "content": "hi"},
    ]
    assert len(_normalize_messages(raw)) == 1


def test_normalize_skips_empty_assistant():
    raw = [
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "  "},
        {"role": "user", "content": "q"},
    ]
    out = _normalize_messages(raw)
    assert len(out) == 1
    assert out[0]["role"] == "user"


def test_normalize_keeps_empty_tool():
    """工具消息即使 content 为空也保留（前端显示"无输出"）。"""
    raw = [{"role": "tool", "content": "", "tool_name": "web_search"}]
    out = _normalize_messages(raw)
    assert len(out) == 1
    assert out[0]["toolName"] == "web_search"


def test_normalize_flattens_multimodal():
    raw = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}],
        }
    ]
    out = _normalize_messages(raw)
    assert out[0]["content"] == "第一段\n第二段"


def test_flatten_content_string_passthrough():
    assert _flatten_content("abc") == "abc"


def test_normalize_unknown_role_becomes_assistant():
    raw = [{"role": "function", "content": "some output"}]
    out = _normalize_messages(raw)
    assert len(out) == 1
    assert out[0]["role"] == "assistant"


def test_normalize_empty_input():
    assert _normalize_messages([]) == []


def test_normalize_assigns_stable_ids():
    raw = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    out = _normalize_messages(raw)
    assert [m["id"] for m in out] == ["h-0", "h-1"]


# ── 管理员登录 ────────────────────────────────────────────
# ── v2 统一登录（admin-login 已删除，以下为替代语义）─────────
async def test_unified_login_returns_role(client, bootstrap_admin):
    """统一登录返回 role=admin 的用户信息。"""
    r = await client.post(
        "/api/auth/login",
        json={"username": bootstrap_admin, "password": "password123"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["user"]["role"] == "admin"
    assert b["access_token"]


async def test_unified_login_wrong_password(client, bootstrap_admin):
    r = await client.post(
        "/api/auth/login", json={"username": bootstrap_admin, "password": "nope"}
    )
    assert r.status_code == 401


async def test_unified_login_wrong_username(client):
    r = await client.post(
        "/api/auth/login", json={"username": "ghost-user", "password": "x"}
    )
    assert r.status_code == 401


async def test_admin_token_works_everywhere(client, atok):
    """v2：admin 的 token 登录接口与用户接口都能访问（归属由后端校验）。"""
    assert (await client.get("/api/agents", headers=_h(atok))).status_code == 200
    assert (await client.get("/api/chat/agents", headers=_h(atok))).status_code == 200
    assert (await client.get("/api/auth/me", headers=_h(atok))).status_code == 200
