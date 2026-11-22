#!/usr/bin/env python3
"""测试用 MCP server：本地文本统计（stdio JSON-RPC 2.0，零依赖）。

transport: stdio
工具：
  - count_lines(text)        统计行数/字符数
  - word_freq(text, top_n)   词频统计（英文按空格，中文按单字）

用途：验证 stdio 型 MCP 的启动、工具发现与调用。
"""

from __future__ import annotations

import json
import re
import sys

TOOLS = [
    {
        "name": "count_lines",
        "description": "统计文本的行数、非空行数、字符数",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "待统计文本"}},
            "required": ["text"],
        },
    },
    {
        "name": "word_freq",
        "description": "统计文本词频，返回出现次数最多的 N 个词",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待统计文本"},
                "top_n": {"type": "integer", "description": "返回前 N 个，默认 10", "default": 10},
            },
            "required": ["text"],
        },
    },
]


def _count_lines(a: dict) -> dict:
    text = str(a.get("text") or "")
    lines = text.splitlines()
    return {
        "lines": len(lines),
        "non_empty": sum(1 for x in lines if x.strip()),
        "chars": len(text),
    }


def _word_freq(a: dict) -> dict:
    text = str(a.get("text") or "").lower()
    top_n = int(a.get("top_n") or 10)
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text)
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return {"total_words": len(words), "top": [{"word": w, "count": c} for w, c in top]}


HANDLERS = {"count_lines": _count_lines, "word_freq": _word_freq}


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
                "serverInfo": {"name": "file-stats-test", "version": "1.0.0"},
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
