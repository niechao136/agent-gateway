# 城市名与输出格式参考

## 常见城市写法

| 输入 | wttr.in 识别 |
|---|---|
| 北京 / Beijing | 北京 |
| 上海 / Shanghai | 上海 |
| 广州 | 广州 |
| 深圳 | 深圳 |
| New York | New York |
| London | London |

- 中文城市名可直接传，脚本会自动 URL 编码。
- 含空格的英文名（如 "New York"）在 shell 中加引号。

## 输出示例

```json
{
  "city": "Beijing",
  "country": "China",
  "description": "Partly cloudy",
  "temp_c": "22",
  "feels_like_c": "21",
  "humidity": "56",
  "wind_kmh": "12",
  "precip_mm": "0.0"
}
```

## 回答模板

> {city} 当前 {description}，气温 {temp_c}°C（体感 {feels_like_c}°C），湿度 {humidity}%，风速 {wind_kmh} km/h。
