"""知识库工具化：绑定后写 MCP 工具配置 + .env 允许列表。"""

import pytest

pytestmark = pytest.mark.asyncio


def test_ragflow_mcp_server_tool_list():
    """内置 MCP server：初始化 + tools/list 暴露 retrieve 工具。"""
    import json
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "app" / "hermes" / "ragflow_mcp_server.py"
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    r = subprocess.run(
        [sys.executable, str(script)], input=stdin, capture_output=True, text=True, timeout=15
    )
    assert r.returncode == 0, r.stderr
    replies = [json.loads(line) for line in r.stdout.strip().splitlines() if line]
    tools = next(x for x in replies if x.get("id") == 2)["result"]["tools"]
    assert len(tools) == 1 and tools[0]["name"] == "retrieve"
    assert "dataset_ids" in tools[0]["inputSchema"]["properties"]


def test_apply_knowledge_tool_writes_env_and_mcp(tmp_path):
    """工具化下发：.env 写入 RAGFLOW_*，config.yaml 合并 mcp_servers 不覆盖已有项。"""
    from app.hermes.rag_sync import apply_knowledge_tool, remove_knowledge_tool
    from app.hermes.a2a import profile_config_path

    profile = "agent-u1-test"
    cfg = profile_config_path(profile, str(tmp_path))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("mcp:\n  servers:\n    - name: existing\n      transport: stdio\n      command: echo\n", encoding="utf-8")

    class KB:
        def __init__(self, url, key, dsid):
            self.base_url, self.api_key, self.dataset_id = url, key, dsid

    # 用 monkeypatch 让 rag_sync 的 data_root 指向 tmp_path（模块级 get_settings）
    from types import SimpleNamespace
    from app.hermes import rag_sync

    rag_sync.get_settings = lambda: SimpleNamespace(hermes_data_root=str(tmp_path))
    res = apply_knowledge_tool(
        profile, base_url="http://rag:9380", api_key="k", dataset_ids=["d1", "d2"]
    )
    assert res.get("tool") or res.get("env") or res.get("ok")  # 成功返回
    env = (cfg.parent / ".env").read_text(encoding="utf-8")
    assert "RAGFLOW_ALLOWED_DATASETS=d1,d2" in env
    assert "RAGFLOW_API_KEY=k" in env
    import yaml

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert any(s.get("name") == "existing" for s in data["mcp"]["servers"])  # 合并而非覆盖
    assert any(s.get("name") == "ragflow-retrieve" for s in data["mcp"]["servers"])

    remove_knowledge_tool(profile)
    env2 = (cfg.parent / ".env").read_text(encoding="utf-8")
    assert "RAGFLOW_ALLOWED_DATASETS" not in env2
