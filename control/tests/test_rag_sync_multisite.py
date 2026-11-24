"""rag_sync 多站点下发测试。"""
from pathlib import Path
import os
import pytest

from app.hermes.rag_env import decode_sites
from app.hermes.rag_sync import apply_knowledge_tool, remove_knowledge_tool


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("app.hermes.rag_sync.get_settings",
                        lambda: SimpleNamespace(hermes_data_root=str(tmp_path)))
    d = tmp_path / "profiles" / "agent-u1-test"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("model:\n  default: x\n", encoding="utf-8")
    return d


def test_apply_multisite_env_and_mcp(profile_dir):
    res = apply_knowledge_tool(
        "agent-u1-test",
        sites={"1": {"base_url": "http://a", "api_key": "KEY_A"},
               "2": {"base_url": "http://b", "api_key": "KEY_B"}},
        dataset_sites={"d1": "1", "d2": "2"},
    )
    env = (profile_dir / ".env").read_text(encoding="utf-8")
    s_line = [x for x in env.splitlines() if x.startswith("RAGFLOW_SITES_B64=")][0]
    d_line = [x for x in env.splitlines() if x.startswith("RAGFLOW_DATASET_SITES_B64=")][0]
    sites, dsmap = decode_sites(s_line.split("=", 1)[1], d_line.split("=", 1)[1])
    assert sites["1"]["api_key"] == "KEY_A" and sites["2"]["api_key"] == "KEY_B"
    assert dsmap == {"d1": "1", "d2": "2"}
    import yaml
    cfg = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    names = [s["name"] for s in cfg["mcp"]["servers"]]
    assert "ragflow-retrieve" in names
    assert res["env"]["vars"] == 2


def test_env_file_mode_600(profile_dir):
    apply_knowledge_tool("agent-u1-test", sites={"1": {"base_url": "http://a", "api_key": "k"}},
                         dataset_sites={"d1": "1"})
    mode = os.stat(profile_dir / ".env").st_mode & 0o777
    assert mode == 0o600


def test_server_script_copied_to_shared_root(profile_dir):
    apply_knowledge_tool("agent-u1-test", sites={"1": {"base_url": "http://a", "api_key": "k"}},
                         dataset_sites={"d1": "1"})
    import yaml
    cfg = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    srv = [s for s in cfg["mcp"]["servers"] if s["name"] == "ragflow-retrieve"][0]
    assert srv["args"] == ["/opt/data/ragflow_mcp_server.py"]
    # 脚本被复制到 hermes 可见的共享根（测试里 monkeypatch 到 tmp_path）
    assert (profile_dir.parent.parent / "ragflow_mcp_server.py").is_file()


def test_remove_clears_env(profile_dir):
    apply_knowledge_tool("agent-u1-test", sites={"1": {"base_url": "http://a", "api_key": "k"}},
                         dataset_sites={"d1": "1"})
    remove_knowledge_tool("agent-u1-test")
    env = (profile_dir / ".env").read_text(encoding="utf-8")
    assert "RAGFLOW_SITES_B64" not in env
