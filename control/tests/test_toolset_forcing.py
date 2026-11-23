"""强制工具集：绑定资源自动开启，解绑只解除强制。"""

from app.hermes.toolset_forcing import API_SERVER_DEFAULT, apply_forced_toolsets
from app.models import Agent


class _DummyAgent:
    profile_name = "agent-u1-test"
    disabled_toolsets = ["terminal", "web", "a2a"]
    slug = "test"


def test_apply_forced_removes_from_disabled(tmp_path, monkeypatch):
    """强制项从 disabled 移除，且写入 profile 的 platform_toolsets.api_server。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "hermes_data_root", str(tmp_path))
    prof = tmp_path / "profiles" / "agent-u1-test"
    prof.mkdir(parents=True)
    cfg = prof / "config.yaml"
    cfg.write_text("model:\n  default: x\n", encoding="utf-8")

    agent = _DummyAgent()
    res = apply_forced_toolsets(agent, ["a2a", "terminal"])  # type: ignore[arg-type]
    assert res["written"] is True
    assert "a2a" not in agent.disabled_toolsets
    assert "terminal" not in agent.disabled_toolsets
    assert "web" in agent.disabled_toolsets  # 非强制项保留

    import yaml

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    apis = data["platform_toolsets"]["api_server"]
    assert API_SERVER_DEFAULT in apis and "a2a" in apis and "terminal" in apis


def test_apply_forced_empty_keeps_existing(tmp_path, monkeypatch):
    """解绑后 forced 为空：不删除已启用的 toolset。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "hermes_data_root", str(tmp_path))
    prof = tmp_path / "profiles" / "agent-u1-test"
    prof.mkdir(parents=True)
    cfg = prof / "config.yaml"
    cfg.write_text(
        "platform_toolsets:\n  api_server:\n  - hermes-api_server\n  - a2a\n",
        encoding="utf-8",
    )
    apply_forced_toolsets(_DummyAgent(), [])  # type: ignore[arg-type]
    import yaml

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "a2a" in data["platform_toolsets"]["api_server"]
