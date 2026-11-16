"""模型模板：把控制层的模型配置写入 profile 的 config.yaml: model 段。

与 A2A 共用同一套「直接读写 config.yaml + 原子写」策略（见 a2a.py 的说明）。

⚠️ 关键约束（实测，见 SPEC §11.9.9）：
- `OPENAI_API_KEY` 环境变量**不生效**，必须写 `model.api_key`
- `provider: gemini` 会发 thinking_config，部分模型不支持 → 用 `custom` 更稳
- base_url 要指向完整的 OpenAI 兼容端点（如 .../v1beta/openai）
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import yaml

from .a2a import A2AError, profile_config_path

logger = logging.getLogger(__name__)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".model-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply_model(
    profile: str,
    data_root: str,
    *,
    model: str,
    provider: str = "custom",
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """写入 profile 的 model 段，其他配置段原样保留。"""
    path = profile_config_path(profile, data_root)
    if not path.is_file():
        raise A2AError(f"profile {profile} 的 config.yaml 不存在: {path}")

    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise A2AError(f"解析 {path} 失败: {exc}") from exc
    if not isinstance(cfg, dict):
        raise A2AError(f"{path} 的根节点不是映射，拒绝改写")

    section: dict = {"default": model, "provider": provider}
    if base_url:
        section["base_url"] = base_url
    if api_key:
        section["api_key"] = api_key

    cfg["model"] = section
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)
    _atomic_write(path, text)
    logger.info("已写入 %s：model=%s provider=%s", path, model, provider)
    return {"path": str(path), "model": model, "provider": provider}


def read_model(profile: str, data_root: str) -> dict:
    """读取 profile 当前生效的 model 段（不含 api_key）。"""
    path = profile_config_path(profile, data_root)
    if not path.is_file():
        return {}
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(cfg, dict):
        return {}
    section = cfg.get("model")
    if not isinstance(section, dict):
        return {}
    return {k: v for k, v in section.items() if k != "api_key"}
