"""RAGFlow 站点配置的 base64 编解码（写进 profile .env，避免 dotenv 引号解析问题）。

站点的 api_key 明文只在 DB 与 profile .env 中出现；这里编码后是 base64，
不是加密——权限靠 .env 文件 600 保障。
"""
from __future__ import annotations

import base64
import json
from typing import Any


def encode_sites(
    sites: dict[str, dict[str, Any]],
    dataset_sites: dict[str, str],
) -> tuple[str, str]:
    """把站点映射与 dataset→站点映射编码成两个 base64 串。

    - sites: {"<site.id>": {"base_url": "...", "api_key": "..."}}
    - dataset_sites: {"<dataset_id>": "<site.id>"}
    """
    s_json = json.dumps(sites, ensure_ascii=False, separators=(",", ":"))
    d_json = json.dumps(dataset_sites, ensure_ascii=False, separators=(",", ":"))
    return (
        base64.b64encode(s_json.encode("utf-8")).decode("ascii"),
        base64.b64encode(d_json.encode("utf-8")).decode("ascii"),
    )


def decode_sites(s_b64: str, d_b64: str) -> tuple[dict, dict]:
    """解码；任何异常返回空 dict（best-effort，不抛给调用方）。"""
    out_s: dict = {}
    out_d: dict = {}
    try:
        if s_b64:
            out_s = json.loads(base64.b64decode(s_b64).decode("utf-8"))
    except Exception:
        out_s = {}
    try:
        if d_b64:
            out_d = json.loads(base64.b64decode(d_b64).decode("utf-8"))
    except Exception:
        out_d = {}
    return out_s, out_d
