---
name: weather-alert
description: 查询城市天气并通过 wttr.in 获取实时天气数据。当用户询问某个城市的天气、气温、降雨时必须使用本技能。
---

# 天气查询技能

当用户询问天气相关问题时，运行 `scripts/weather.py` 获取实时数据。

## 使用方法

```bash
python3 scripts/weather.py 北京
python3 scripts/weather.py "New York"
```

脚本输出 JSON，包含：城市、描述、气温、体感温度、湿度、风速、降雨量。

## 说明

- 数据源为 wttr.in（公开接口，无需 API Key），需要联网。
- 支持中文城市名和英文名；城市名含空格时请加引号。
- 参考 `references/cities.md` 了解常见城市写法和格式化示例。

## 回答格式

拿到 JSON 后用自然语言总结，并保留关键数值（温度、天气状况、湿度）。如果脚本报错（如网络不通），如实告知用户。
