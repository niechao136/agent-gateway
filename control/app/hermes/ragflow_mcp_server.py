#!/usr/bin/env python3
"""RAGFlow 检索 MCP server（stdio JSON-RPC 2.0，无第三方依赖）。

暴露一个工具：
    retrieve(question: str, dataset_ids: string[] = [], top_k: int = 5) -> 检索结果

环境变量（由控制层在 Agent profile .env 注入）：
    RAGFLOW_BASE_URL / RAGFLOW_API_KEY / RAGFLOW_ALLOWED_DATASETS

安全：传入的 dataset_ids 被限制在 ALLOWED 列表内；未传则检索全部允许的库。
"""

from __future__ import annotations

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


def _allowed() -> list[str]:
    return [x.strip() for x in os.environ.get("RAGFLOW_ALLOWED_DATASETS", "").split(",") if x.strip()]


def _do_retrieve(args: dict) -> dict:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "请提供检索问题 question"}
    allowed = _allowed()
    if not allowed:
        return {"error": "该 Agent 未绑定任何知识库"}
    requested = args.get("dataset_ids") or []
    if not isinstance(requested, list):
        return {"error": "dataset_ids 必须是数组"}
    ids = [str(x) for x in requested] if requested else allowed
    ids = [x for x in ids if x in allowed]
    if not ids:
        return {"error": "指定的知识库不在允许列表中"}

    base = os.environ.get("RAGFLOW_BASE_URL", "").rstrip("/")
    key = os.environ.get("RAGFLOW_API_KEY", "")
    if not base or not key:
        return {"error": "知识库服务未配置完整"}
    top_k = int(args.get("top_k") or 5)
    body = json.dumps(
        {"dataset_ids": ids, "question": question, "top_k": top_k}, ensure_ascii=False
    ).encode()
    req = urllib.request.Request(
        base + "/api/v1/retrieval",
        data=body,
        method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        chunks = (data.get("data") or {}).get("chunks") or []
        out = [
            {
                "content": c.get("content", ""),
                "doc": c.get("docnm_kwd", ""),
                "dataset_id": c.get("dataset_id", ""),
                "score": c.get("similarity"),
            }
            for c in chunks
        ]
        return {"chunks": out, "datasets": ids}
    except Exception as exc:
        return {"error": str(exc)}


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
