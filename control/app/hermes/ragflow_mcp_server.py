#!/usr/bin/env python3
"""RAGFlow 检索 MCP server（stdio JSON-RPC 2.0，无第三方依赖）。

暴露一个工具：
    retrieve(question: str, dataset_ids: string[] = [], top_k: int = 5) -> 检索结果

环境变量（由控制层在 Agent profile .env 注入）：
    RAGFLOW_BASE_URL / RAGFLOW_API_KEY / RAGFLOW_ALLOWED_DATASETS

安全：传入的 dataset_ids 被限制在 ALLOWED 列表内；未传则检索全部允许的库。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request

TOOL_NAME = "retrieve"
TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "从绑定的 RAGFlow 知识库检索资料。当用户询问知识库/内部文档内容时必须调用。"
        "dataset_ids 可不传（检索全部允许的知识库），也可传数组指定范围。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "检索问题"},
            "dataset_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：指定知识库 id 数组（仅限本 Agent 允许的库）",
            },
            "top_k": {"type": "integer", "description": "返回片段数，默认 5", "default": 5},
        },
        "required": ["question"],
    },
}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _config() -> tuple[dict, dict]:
    """解码 profile .env 注入的多站点配置（base64 JSON）。"""
    def dec(name):
        raw = os.environ.get(name, "")
        if not raw:
            return {}
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            return {}
    sites = dec("RAGFLOW_SITES_B64")
    dsmap = dec("RAGFLOW_DATASET_SITES_B64")
    # 兼容旧 profile（单站点）：无新配置时读旧变量
    if not sites or not dsmap:
        base = os.environ.get("RAGFLOW_BASE_URL", "").rstrip("/")
        key = os.environ.get("RAGFLOW_API_KEY", "")
        allowed = [x.strip() for x in os.environ.get("RAGFLOW_ALLOWED_DATASETS", "").split(",") if x.strip()]
        if base and key:
            sites = {"legacy": {"base_url": base, "api_key": key}}
            dsmap = {d: "legacy" for d in allowed}
    return sites, dsmap


def _do_retrieve(args: dict) -> dict:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "请提供检索问题 question"}
    sites, dsmap = _config()
    if not sites or not dsmap:
        return {"error": "该 Agent 未绑定任何知识库"}
    requested = args.get("dataset_ids") or []
    if not isinstance(requested, list):
        return {"error": "dataset_ids 必须是数组"}
    ids = [str(x) for x in requested] if requested else list(dsmap.keys())
    ids = [x for x in ids if x in dsmap]
    if not ids:
        return {"error": "指定的知识库不在允许列表中"}

    top_k = int(args.get("top_k") or 5)
    by_site: dict[str, list[str]] = {}
    for ds in ids:
        by_site.setdefault(dsmap[ds], []).append(ds)

    out: list[dict] = []
    site_errors: list[str] = []
    for site_id, ds_ids in by_site.items():
        cfg = sites.get(site_id)
        if not cfg:
            site_errors.append(f"站点 {site_id} 配置缺失")
            continue
        body = json.dumps(
            {"dataset_ids": ds_ids, "question": question, "top_k": top_k}, ensure_ascii=False
        ).encode()
        req = urllib.request.Request(
            cfg["base_url"].rstrip("/") + "/api/v1/retrieval",
            data=body, method="POST",
            headers={"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, dict) and data.get("code") not in (None, 0):
                site_errors.append(f"站点 {site_id}: {data.get('code')} {data.get('message') or ''}")
                continue
            chunks = (data.get("data") or {}).get("chunks") or []
            site_name = cfg.get("name") or site_id
            for c in chunks:
                out.append({
                    "content": c.get("content", ""),
                    "doc": c.get("docnm_kwd", ""),
                    "dataset_id": c.get("dataset_id", ""),
                    "site_name": site_name,
                    "score": c.get("similarity"),
                })
        except Exception as exc:
            site_errors.append(f"站点 {site_id}: {exc}")
    out.sort(key=lambda x: (x.get("score") is None, -(x.get("score") or 0)))
    out = out[:top_k]
    res = {"chunks": out, "datasets": ids}
    if site_errors:
        res["site_errors"] = site_errors
    return res


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _send({
                "jsonrpc": "2.0", "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ragflow-retrieve", "version": "1.0.0"},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL_DEF]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name != TOOL_NAME:
                _send({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32602, "message": f"Unknown tool: {name}"}})
                continue
            result = _do_retrieve(params.get("arguments") or {})
            _send({
                "jsonrpc": "2.0", "id": mid,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": "error" in result,
                },
            })
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": f"Method not found: {method}"}})


if __name__ == "__main__":
    main()
