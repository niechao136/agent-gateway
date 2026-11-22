#!/usr/bin/env python3
"""测试用 MCP server：文本工具箱（stdio JSON-RPC 2.0，零依赖）。

transport: stdio
工具：
  - reverse(text)            反转文本
  - word_count(text)         词数统计
  - extract_emails(text)     提取邮箱地址

用途：验证一个 MCP 暴露多个工具时，模型能否正确选择工具。
"""

from __future__ import annotations

import json
import re
import sys

TOOLS = [
    {
        "name": "reverse",
        "description": "把输入文本反转",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "word_count",
        "description": "统计文本的单词数和字符数",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "extract_emails",
        "description": "从文本中提取所有邮箱地址",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def _reverse(a: dict) -> dict:
    return {"result": str(a.get("text") or "")[::-1]}


def _word_count(a: dict) -> dict:
    text = str(a.get("text") or "")
    return {"words": len(text.split()), "chars": len(text)}


def _extract_emails(a: dict) -> dict:
    text = str(a.get("text") or "")
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return {"emails": sorted(set(emails)), "count": len(set(emails))}


HANDLERS = {"reverse": _reverse, "word_count": _word_count, "extract_emails": _extract_emails}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


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
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "text-utils-test", "version": "1.0.0"},
            }})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            name = p.get("name")
            if name not in HANDLERS:
                _send({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32602, "message": f"Unknown tool: {name}"}})
                continue
            result = HANDLERS[name](p.get("arguments") or {})
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            }})
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": f"Method not found: {method}"}})


if __name__ == "__main__":
    main()
