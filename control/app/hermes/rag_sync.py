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
# control 镜像里脚本源位置（Dockerfile WORKDIR /app）
SERVER_SCRIPT_SRC = "/app/app/hermes/ragflow_mcp_server.py"
# Hermes 容器内可执行位置：共享挂载 /opt/data（control 在下发时把脚本复制过去）
SERVER_SCRIPT = "/opt/data/ragflow_mcp_server.py"


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
    ms = cfg.get("mcp_servers")
    if not isinstance(ms, dict):
        ms = {}
    ms.pop(MCP_NAME, None)
    if enabled:
        env = {}
        env_path = profile_config_path(profile, get_settings().hermes_data_root).parent / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("RAGFLOW_"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
        ms[MCP_NAME] = {
            "command": "python3",
            "args": [SERVER_SCRIPT],
            "transport": "stdio",
            "enabled": True,
            "env": env,
            "description": "RAGFlow 知识库检索（dataset_ids 数组）",
        }
    # 把旧格式 mcp.servers 条目迁移到 mcp_servers，统一为 Hermes 标准格式
    old_mcp = cfg.get("mcp")
    if isinstance(old_mcp, dict) and isinstance(old_mcp.get("servers"), list):
        for srv in old_mcp["servers"]:
            if not isinstance(srv, dict):
                continue
            name = srv.get("name")
            if not name:
                continue
            item = {k: v for k, v in srv.items() if k != "name"}
            item.setdefault("enabled", True)
            ms.setdefault(name, item)
        old_mcp.pop("servers", None)
        if not old_mcp:
            cfg.pop("mcp", None)
    if ms:
        cfg["mcp_servers"] = ms
    else:
        cfg.pop("mcp_servers", None)
    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    return {"path": str(path), "mcp": MCP_NAME if enabled else None}


def _ensure_server_script() -> None:
    """把 MCP server 脚本复制到 Hermes 容器可见的共享目录（/opt/data）。

    MCP 子进程由 Hermes 启动（stdio），Hermes 容器没有 control 的 /app 目录；
    /opt/data 是 control 与 hermes 的共享挂载，因此脚本必须放这里。
    内容一致则不重写，保持幂等。
    """
    root = Path(get_settings().hermes_data_root)
    root.mkdir(parents=True, exist_ok=True)
    src = Path(SERVER_SCRIPT_SRC)
    if not src.is_file():
        raise RagSyncError(f"MCP server 脚本源不存在: {src}")
    data = src.read_bytes()
    dst = root / "ragflow_mcp_server.py"
    if dst.is_file() and dst.read_bytes() == data:
        return
    _atomic_write(dst, data.decode("utf-8"))


def apply_knowledge_tool(profile: str, *, sites: dict, dataset_sites: dict) -> dict:
    """绑定知识库：写多站点 .env + 合并内置 MCP 项。"""
    env = _write_env(profile, sites=sites, dataset_sites=dataset_sites)
    mcp = _sync_mcp_entry(profile, enabled=bool(dataset_sites))
    if dataset_sites:
        _ensure_server_script()
    return {"env": env, "mcp": mcp}


def remove_knowledge_tool(profile: str) -> dict:
    """解绑全部知识库：清 .env + 移除内置 MCP 项。"""
    env = _write_env(profile, sites={}, dataset_sites={})
    mcp = _sync_mcp_entry(profile, enabled=False)
    return {"env": env, "mcp": mcp}
