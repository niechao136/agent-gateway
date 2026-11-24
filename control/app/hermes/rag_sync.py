"""知识库 → Agent profile 下发（MCP 工具方式）。

不再生成 Skill/脚本。而是：
1. profile .env 注入 RAGFLOW_BASE_URL / RAGFLOW_API_KEY / RAGFLOW_ALLOWED_DATASETS
2. profile config.yaml 的 mcp.servers 合并加入一个内置 stdio MCP：
   ragflow-retrieve（脚本位于 control 镜像 /app/app/hermes/ragflow_mcp_server.py）
   该 MCP 暴露唯一工具 retrieve(question, dataset_ids[], top_k)，
   dataset_ids 数组由用户在 Agent 编辑页勾选的知识库决定（写入 ALLOWED）。

使用合并式写入，避免覆盖该 Agent 已绑定的其它 MCP。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from ..config import get_settings
from .rag_env import encode_sites
from .a2a import _atomic_write, profile_config_path

logger = logging.getLogger(__name__)

MCP_NAME = "ragflow-retrieve"
# control 镜像里脚本的绝对位置（Dockerfile WORKDIR /app）
SERVER_SCRIPT = "/app/app/hermes/ragflow_mcp_server.py"


class RagSyncError(Exception):
    pass


def _profile_root(profile: str) -> Path:
    root = Path(get_settings().hermes_data_root)
    return root if profile == "default" else root / "profiles" / profile


def _env_path(profile: str) -> Path:
    return _profile_root(profile) / ".env"


def _write_env(profile: str, *, sites: dict, dataset_sites: dict) -> dict:
    """写多站点配置到 .env（base64 JSON 单行），权限 600。"""
    path = _env_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = [ln for ln in existing.splitlines() if not ln.startswith("RAGFLOW_")]
    if sites and dataset_sites:
        s_b64, d_b64 = encode_sites(sites, dataset_sites)
        lines += [f"RAGFLOW_SITES_B64={s_b64}", f"RAGFLOW_DATASET_SITES_B64={d_b64}"]
    text = "\n".join(lines).rstrip() + "\n"
    try:
        _atomic_write(path, text)
        os.chmod(path, 0o600)
    except OSError as exc:
        raise RagSyncError(f"写入 {path} 失败: {exc}") from exc
    return {"path": str(path), "vars": 2 if (sites and dataset_sites) else 0}


def _sync_mcp_entry(profile: str, *, enabled: bool) -> dict:
    """合并式写入/移除 config.yaml mcp.servers 中的内置 MCP 项。"""
    path = profile_config_path(profile, get_settings().hermes_data_root)
    if not path.is_file():
        raise RagSyncError(f"profile {profile} 的 config.yaml 不存在: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise RagSyncError(f"{path} 根节点不是映射，拒绝改写")
    section = cfg.get("mcp")
    if not isinstance(section, dict):
        section = {}
    servers = section.get("servers")
    servers = list(servers) if isinstance(servers, list) else []
    servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == MCP_NAME)]
    if enabled:
        servers.append({
            "name": MCP_NAME,
            "transport": "stdio",
            "command": "python3",
            "args": [SERVER_SCRIPT],
            "description": "RAGFlow 知识库检索（dataset_ids 数组）",
        })
    if servers:
        section["servers"] = servers
        cfg["mcp"] = section
    else:
        section.pop("servers", None)
        if not section:
            cfg.pop("mcp", None)
    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    return {"path": str(path), "mcp": MCP_NAME if enabled else None}


def apply_knowledge_tool(profile: str, *, sites: dict, dataset_sites: dict) -> dict:
    """绑定知识库：写多站点 .env + 合并内置 MCP 项。"""
    env = _write_env(profile, sites=sites, dataset_sites=dataset_sites)
    mcp = _sync_mcp_entry(profile, enabled=bool(dataset_sites))
    return {"env": env, "mcp": mcp}


def remove_knowledge_tool(profile: str) -> dict:
    """解绑全部知识库：清 .env + 移除内置 MCP 项。"""
    env = _write_env(profile, sites={}, dataset_sites={})
    mcp = _sync_mcp_entry(profile, enabled=False)
    return {"env": env, "mcp": mcp}
