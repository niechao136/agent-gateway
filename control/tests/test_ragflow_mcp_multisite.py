"""RAGFlow MCP server 多站点路由测试。"""
import base64
import json

from app.hermes import ragflow_mcp_server as mcp


def _set_env(monkeypatch, sites, dataset_sites):
    monkeypatch.setenv("RAGFLOW_SITES_B64", base64.b64encode(
        json.dumps(sites).encode()).decode())
    monkeypatch.setenv("RAGFLOW_DATASET_SITES_B64", base64.b64encode(
        json.dumps(dataset_sites).encode()).decode())


def test_multisite_routes_to_correct_site(monkeypatch):
    _set_env(monkeypatch,
             {"1": {"base_url": "http://a", "api_key": "KA"},
              "2": {"base_url": "http://b", "api_key": "KB"}},
             {"d1": "1", "d2": "2"})
    calls = []

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            return json.dumps({"data": {"chunks": [{"content": "hit", "dataset_id": "d2", "similarity": 0.9}]}}).encode()

    def fake_urlopen(req, timeout=30):
        calls.append((req.full_url, dict(req.header_items())))
        return FakeResp()

    monkeypatch.setattr(mcp.urllib.request, "urlopen", fake_urlopen)
    res = mcp._do_retrieve({"question": "q", "dataset_ids": ["d2"]})
    assert len(calls) == 1
    assert calls[0][0].startswith("http://b/api/v1/retrieval")
    assert any("KB" in str(v) for k, v in calls[0][1].items())
    assert res["chunks"][0]["dataset_id"] == "d2"


def test_site_error_is_reported(monkeypatch):
    _set_env(monkeypatch,
             {"1": {"base_url": "http://a", "api_key": "KA"}},
             {"d1": "1"})

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            return json.dumps({"code": 403, "message": "upgrade plan"}).encode()

    monkeypatch.setattr(mcp.urllib.request, "urlopen", lambda req, timeout=30: FakeResp())
    res = mcp._do_retrieve({"question": "q"})
    assert res.get("site_errors")
    assert any("403" in str(e) for e in res["site_errors"])
