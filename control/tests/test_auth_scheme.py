"""五方式鉴权单测（auth_scheme.py）。"""

import pytest

from app.hermes.auth_scheme import (
    AuthConfig,
    build_http_auth,
    build_stdio_env,
    redact,
)


def test_bearer():
    h = build_http_auth(AuthConfig("bearer", token="tk1"))
    assert h.headers == {"Authorization": "Bearer tk1"}
    assert h.query == {}


def test_custom_header():
    h = build_http_auth(AuthConfig("header", token="tk", auth_name="X-Key"))
    assert h.headers == {"X-Key": "tk"}


def test_query():
    h = build_http_auth(AuthConfig("query", token="k1", auth_name="api_key"))
    assert h.query == {"api_key": "k1"}
    assert build_http_auth and append_q("https://x/y", h.query)


def append_q(url, q):
    from app.hermes.auth_scheme import append_query

    return append_query(url, q)


def test_basic():
    h = build_http_auth(AuthConfig("basic", token="pw", auth_name="user"))
    assert h.headers["Authorization"].startswith("Basic ")


def test_none_no_auth():
    h = build_http_auth(AuthConfig("none"))
    assert h.headers == {} and h.query == {}
    assert build_stdio_env(AuthConfig("none")) == {}


def test_stdio_env():
    env = build_stdio_env(AuthConfig("bearer", token="tk", auth_name="ignored"))
    assert env["MCP_AUTH_TYPE"] == "bearer"
    assert env["MCP_AUTH_TOKEN"] == "tk"
    assert env["MCP_AUTH_NAME"] == "ignored"


def test_header_requires_auth_name():
    with pytest.raises(ValueError):
        build_http_auth(AuthConfig("header", token="tk"))
    with pytest.raises(ValueError):
        build_http_auth(AuthConfig("query", token="tk"))
    with pytest.raises(ValueError):
        build_http_auth(AuthConfig("bearer"))  # 缺 token


def test_unknown_type():
    with pytest.raises(ValueError):
        build_http_auth(AuthConfig("sigv4", token="x"))


def test_redact_never_returns_token():
    r = redact(AuthConfig("bearer", token="supersecret", auth_name="X"))
    assert "supersecret" not in str(r)
    assert r["has_token"] is True
