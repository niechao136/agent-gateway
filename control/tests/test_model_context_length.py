"""模型 context_length 下发：小窗口本地模型必须写入 profile config。"""
from pathlib import Path

from app.hermes.models_cfg import apply_model, read_model


def test_apply_model_writes_context_length(tmp_path: Path):
    profile = "agent-u1-test"
    cfg_dir = tmp_path / "profiles" / profile
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text("agent:\n  disabled_toolsets: []\n", encoding="utf-8")

    res = apply_model(
        profile, str(tmp_path),
        model="gemma4", provider="custom",
        base_url="http://172.22.132.148:8088/v1",
        api_key="EMPTY", context_length=64000,
    )
    assert res["model"] == "gemma4"
    text = cfg_file.read_text(encoding="utf-8")
    assert "context_length: 64000" in text, text
    assert "api_key: EMPTY" in text, text


def test_read_model_returns_context_length(tmp_path: Path):
    profile = "agent-u1-test2"
    cfg_dir = tmp_path / "profiles" / profile
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "model:\n  default: gemma4\n  provider: custom\n  context_length: 64000\n",
        encoding="utf-8",
    )
    m = read_model(profile, str(tmp_path))
    assert m.get("context_length") == 64000
