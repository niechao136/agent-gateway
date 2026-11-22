---
name: json-formatter
description: 校验并格式化 JSON 字符串，或提取其中指定字段。当用户提供 JSON 并要求格式化、校验、提取字段时使用。
---

# JSON 格式化技能

运行 `scripts/fmt_json.py` 处理 JSON。

## 使用方法

```bash
# 格式化
python3 scripts/fmt_json.py '{"a":1,"b":[2,3]}'

# 指定缩进
python3 scripts/fmt_json.py '{"a":1}' --indent 4

# 提取字段（点号路径）
python3 scripts/fmt_json.py '{"user":{"name":"Tom"}}' --get user.name

# 从文件读取
python3 scripts/fmt_json.py @/path/to/file.json
```

## 输出

成功返回格式化后的 JSON；非法 JSON 返回明确的错误信息（含位置）。
