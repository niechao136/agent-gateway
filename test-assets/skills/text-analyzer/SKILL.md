---
name: text-analyzer
description: 对一段文本做统计分析（行数、词数、高频词、字数），并按固定模板生成分析报告。当用户要求"分析这段文本""统计词频""生成文本报告"时使用。
---

# 文本分析技能

运行 `scripts/analyze.py` 分析文本，输出 JSON；再套用 `templates/report.md` 的格式给用户报告。

## 使用方法

把待分析文本写入临时文件（如 `/tmp/input.txt`），然后：

```bash
python3 scripts/analyze.py /tmp/input.txt
```

支持参数：`--top 10` 指定高频词数量（默认 10）。

## 报告格式

参考 `templates/report.md`，用自然中文输出：总览（行数/词数/字数）+ 高频词列表 + 简短结论。

## 注意

- 脚本只依赖 Python 标准库。
- 若文本含中文，按单字统计高频"词"，在报告里说明这一点。
