#!/usr/bin/env python3
"""文本统计：行数/词数/字数/高频词（Python 标准库）。

用法：
    python3 analyze.py <文件路径> [--top N]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="待分析文本文件")
    ap.add_argument("--top", type=int, default=10, help="高频词数量")
    args = ap.parse_args()

    text = Path(args.path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    counts = Counter(words)
    top = [{"word": w, "count": c} for w, c in counts.most_common(args.top)]

    print(json.dumps({
        "lines": len(lines),
        "non_empty_lines": sum(1 for x in lines if x.strip()),
        "words": len(words),
        "chars": len(text),
        "unique_words": len(counts),
        "top_words": top,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
