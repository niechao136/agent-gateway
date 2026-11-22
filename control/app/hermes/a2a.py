"""A2A 端点：存放在控制层 DB，按需写入 profile 的 config.yaml。

设计（SPEC §7）：
- **定义**在控制层（`a2a_endpoints` 表），可跨 Agent 复用
- **绑定**通过写 profile 的 `config.yaml: a2a_agents` 完成

实现方式选择（重要）：
  最初想用 `hermes -p <profile> config set`，但那需要 docker CLI + docker.sock，
  等于把宿主机 root 权限交给控制层，且 apt 安装极慢。
  改为**直接读写 config.yaml 文件**（控制层已挂载 hermes 数据目录）。

  ⚠️ 直接改文件的代价：绕过了 hermes 的配置锁。所以：
  1. 写入必须是原子的（临时文件 + rename）
  2. 写入后 hermes 需要重载才生效（新建 profile 即时生效，改已有 profile 需重载）
  3. 用 YAML 库解析再序列化，保留其他配置段

⚠️ `capabilities` 字段是 `a2a_orchestrate` 的路由依据，必填。
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_HOST_RE = re.compile(r"^https?://\S+$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class A2AError(RuntimeError):
    pass


def validate_endpoint(name: str, url: str) -> None:
    """校验端点名与 URL。"""
    if not _NAME_RE.match(name or ""):
        raise A2AError("端点名只能含字母/数字/下划线/连字符，长度 1-64")
    if not _HOST_RE.match(url or ""):
        raise A2AError("URL 必须以 http:// 或 https:// 开头")


def profile_config_path(profile: str, data_root: str) -> Path:
    """profile 的 config.yaml 路径。

    default profile 在 data_root/config.yaml，
    其他在 data_root/profiles/<name>/config.yaml。
    """
    root = Path(data_root)
    if profile == "default":
        return root / "config.yaml"
    return root / "profiles" / profile / "config.yaml"


def _atomic_write(path: Path, text: str) -> None:
    """原子写入：临时文件 + rename，避免写一半被 hermes 读到。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cfg-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _absolute_a2a_url(url: str) -> str:
    """相对 URL（/a2a/xxx）补全为对外可访问地址。

    Hermes 的 a2a_call 工具需要 http(s):// 绝对地址；内部端点存的是相对路径。
    """
    url = (url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        import os

        base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        if base:
            return base + url
    return url


def _absolute_a2a_url(url: str) -> str:
    """内部端点存的是相对路径 /a2a/<slug>，转成对外绝对 URL。"""
    url = (url or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        return f"{base}{url}" if base else url
    return url


def apply_a2a_endpoints(
    profile: str, data_root: str, endpoints: list[dict]
) -> dict:
    """把端点列表写入 profile 的 config.yaml 的 a2a_agents 段。

    会**整体替换** a2a_agents，避免残留已删除的端点。
    同时确保 a2a toolset 未被禁用（否则模型看不到 a2a_call 工具）。
    其他配置段原样保留。
    """
    path = profile_config_path(profile, data_root)
    if not path.is_file():
        raise A2AError(f"profile {profile} 的 config.yaml 不存在: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
        cfg = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise A2AError(f"解析 {path} 失败: {exc}") from exc
    if not isinstance(cfg, dict):
        raise A2AError(f"{path} 的根节点不是映射，拒绝改写")

    if endpoints:
        section: dict = {}
        for ep in endpoints:
            entry: dict = {"url": _absolute_a2a_url(ep["url"])}
            caps = ep.get("capabilities") or []
            if caps:
                entry["capabilities"] = list(caps)
            if ep.get("timeout"):
                entry["timeout"] = int(ep["timeout"])
            if ep.get("token"):
                entry["auth"] = {"type": "bearer", "token": ep["token"]}
            section[ep["name"]] = entry
        cfg["a2a_agents"] = section
        # 绑定了端点就必须启用 a2a toolset，否则 Hermes 不会向模型暴露 a2a_call。
        agent_cfg = cfg.get("agent")
        if isinstance(agent_cfg, dict):
            disabled = agent_cfg.get("disabled_toolsets")
            if isinstance(disabled, list) and "a2a" in disabled:
                agent_cfg["disabled_toolsets"] = [x for x in disabled if x != "a2a"]
    else:
        cfg.pop("a2a_agents", None)

    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)
    _atomic_write(path, text)
    logger.info("已写入 %s：%d 个 A2A 端点", path, len(endpoints))
    return {"path": str(path), "written": len(endpoints)}


def read_a2a_section(profile: str, data_root: str) -> dict:
    """读取 profile 当前生效的 a2a_agents 段。"""
    path = profile_config_path(profile, data_root)
    if not path.is_file():
        return {}
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(cfg, dict):
        return {}
    section = cfg.get("a2a_agents")
    return section if isinstance(section, dict) else {}
