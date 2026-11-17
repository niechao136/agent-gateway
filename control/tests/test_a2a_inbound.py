"""A2A 入站状态测试。

覆盖三项配置检查（这是 SPEC §7.3 强调的"缺一不可"）。
"""

import pytest

pytestmark = pytest.mark.asyncio


def _h(t):
    return {"Authorization": f"Bearer {t}"}



@pytest.fixture
def dotenv(tmp_path, monkeypatch):
    """把 hermes_dotenv_path 指向临时文件，可按需写入 A2A 配置。"""
    import app.hermes.a2a_inbound as mod

    p = tmp_path / ".env"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod._settings, "hermes_dotenv_path", str(p))
    monkeypatch.setattr(mod._settings, "hermes_gateway_url", "http://ag-hermes:8642")

    def write(lines: list[str]) -> None:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    write([])
    return write


async def test_inbound_requires_login(client):
    utok = (
        await client.post(
            "/api/auth/register", json={"username": "ain1", "password": "password123"}
        )
    ).json()["access_token"]
    assert (await client.get("/api/a2a/inbound", headers=_h(utok))).status_code == 200
    assert (await client.get("/api/a2a/inbound")).status_code == 401


async def test_all_checks_false_when_empty(client, user_token, dotenv):
    r = await client.get("/api/a2a/inbound", headers=_h(user_token))
    assert r.status_code == 200
    b = r.json()
    assert b["ready"] is False
    assert b["checks"]["token_configured"] is False
    assert b["checks"]["host_widened"] is False
    assert b["checks"]["trusted_peers_configured"] is False


async def test_token_only_not_ready(client, user_token, dotenv):
    dotenv(["A2A_BEARER_TOKEN=abc123"])
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    assert b["checks"]["token_configured"] is True
    assert b["checks"]["host_widened"] is False
    assert b["ready"] is False


async def test_all_three_ready(client, user_token, dotenv):
    dotenv(
        [
            "A2A_HOST=0.0.0.0",
            "A2A_PORT=9900",
            "A2A_BEARER_TOKEN=abc123",
            "A2A_TRUSTED_PEERS=ip:127.0.0.1",
        ]
    )
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    assert b["ready"] is True
    assert all(b["checks"].values())
    assert b["trusted_peers"] == "ip:127.0.0.1"


async def test_allow_all_users_counts_as_trusted(client, user_token, dotenv):
    dotenv(
        [
            "A2A_HOST=0.0.0.0",
            "A2A_BEARER_TOKEN=t",
            "A2A_ALLOW_ALL_USERS=true",
        ]
    )
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    assert b["checks"]["trusted_peers_configured"] is True
    assert b["allow_all_users"] is True


async def test_token_is_masked(client, user_token, dotenv):
    dotenv(
        [
            "A2A_HOST=0.0.0.0",
            "A2A_BEARER_TOKEN=super-secret-token-value",
            "A2A_TRUSTED_PEERS=ip:127.0.0.1",
        ]
    )
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    # 不能回传明文
    assert "super-secret-token-value" not in str(b)
    assert b["bearer_token_masked"]


async def test_peer_tokens_counted(client, user_token, dotenv):
    dotenv(["A2A_PEER_TOKENS=alice:t1,bob:t2", "A2A_HOST=0.0.0.0"])
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    assert b["peer_tokens_count"] == 2
    assert b["checks"]["token_configured"] is True


async def test_probe_base_uses_compose_hostname(client, user_token, dotenv):
    """控制层与 hermes 不同容器，探测地址不能用 127.0.0.1。"""
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    assert "ag-hermes" in b["probe_base"]
    assert "127.0.0.1" not in b["probe_base"]


async def test_reachable_false_when_service_down(client, user_token, dotenv):
    """服务没起时 reachable=False 且带 error，但接口本身不 500。"""
    dotenv(["A2A_HOST=0.0.0.0", "A2A_BEARER_TOKEN=t", "A2A_TRUSTED_PEERS=ip:127.0.0.1"])
    b = (await client.get("/api/a2a/inbound", headers=_h(user_token))).json()
    assert b["ready"] is True  # 配置正确
    assert b["reachable"] is False  # 但测试环境没有真实服务
    assert b["error"]
