#!/usr/bin/env python3
"""校验/格式化 JSON，或按点号路径提取字段（Python 标准库）。

用法：
    python3 fmt_json.py '{"a":1}' [--indent N] [--get a.b]
    python3 fmt_json.py @file.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("value", help="JSON 字符串，或 @文件路径")
    ap.add_argument("--indent", type=int, default=2)
    ap.add_argument("--get", help="点号路径，如 user.name")
    args = ap.parse_args()

    raw = Path(args.value[1:]).read_text(encoding="utf-8") if args.value.startswith("@") else args.value
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "ok": False,
            "error": f"非法 JSON: {exc.msg} (行 {exc.lineno}, 列 {exc.colno})",
        }, ensure_ascii=False))
        return

    if args.get:
        cur = obj
        for part in args.get.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                print(json.dumps({"ok": False, "error": f"字段不存在: {args.get}"}, ensure_ascii=False))
                return
        print(json.dumps({"ok": True, "path": args.get, "value": cur}, ensure_ascii=False, indent=args.indent))
        return

    print(json.dumps({"ok": True, "formatted": json.dumps(obj, ensure_ascii=False, indent=args.indent)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
