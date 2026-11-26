---
name: weather-alert
description: 查询城市天气并通过 wttr.in 获取实时天气数据。当用户询问某个城市的天气、气温、降雨时必须使用本技能。
---

# 天气查询技能

当用户询问天气相关问题时，运行 `scripts/weather.py` 获取实时数据。

## 使用方法

```bash
python3 "${HERMES_SKILL_DIR}/scripts/weather.py" 北京
python3 "${HERMES_SKILL_DIR}/scripts/weather.py" "New York"
```

脚本输出 JSON，包含：城市、描述、气温、体感温度、湿度、风速、降雨量。

## 关键规则（避免重复执行）

1. **只调用一次脚本**。拿到 JSON 后直接回答用户，不要为了"确认"再查一遍。
2. 脚本内置常见中文城市名映射（北京、上海、昆山等），直接用中文传参即可。
3. 如果返回的 `city` 与用户问的城市明显不符，**最多再用拼音重试一次**（如 `Kunshan`），
   仍不符就如实说明，不要反复查询。
4. 只有脚本返回 `error`（网络故障等）时才告知用户失败；不要改用其他方式（web 搜索、
   自己编造）获取天气。

## 说明

- 数据源为 wttr.in（公开接口，无需 API Key），需要联网。
- 参考 `references/cities.md` 了解常见城市写法和格式化示例。

## 回答格式

拿到 JSON 后用自然语言总结，并保留关键数值（温度、天气状况、湿度）。
