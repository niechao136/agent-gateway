"""Base URL 隧道重写：模板存逻辑地址，环境决定是否重写。"""
import pytest

from app.hermes.base_url_rewrite import rewrite_base_url


@pytest.fixture
def settings(monkeypatch):
    import app.config as cfg

    s = cfg.Settings(
        tunnel_enabled=True,
        tunnel_upstream_hosts="generativelanguage.googleapis.com,other.example.com",
        tunnel_local_base="http://127.0.0.1:8899",
    )
    monkeypatch.setattr(cfg, "get_settings", lambda: s)
    return s


def test_rewrite_matching_host_keeps_path(settings):
    url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert rewrite_base_url(url) == "http://127.0.0.1:8899/v1beta/openai/"


def test_rewrite_preserves_query(settings):
    url = "https://generativelanguage.googleapis.com/v1beta/openai/models?x=1"
    assert rewrite_base_url(url) == "http://127.0.0.1:8899/v1beta/openai/models?x=1"


def test_no_rewrite_for_other_host(settings):
    url = "http://172.22.132.148:8088/v1"
    assert rewrite_base_url(url) == url


def test_no_rewrite_when_disabled(monkeypatch):
    import app.config as cfg

    s = cfg.Settings(tunnel_enabled=False)
    monkeypatch.setattr(cfg, "get_settings", lambda: s)
    url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert rewrite_base_url(url) == url


def test_idempotent_when_already_local(settings):
    url = "http://127.0.0.1:8899/v1beta/openai/"
    assert rewrite_base_url(url) == url


def test_none_passthrough(settings):
    assert rewrite_base_url(None) is None
