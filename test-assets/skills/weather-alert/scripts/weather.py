#!/usr/bin/env python3
"""通过 wttr.in 查询城市天气，输出 JSON（Python 标准库，无需依赖）。

用法：
    python3 scripts/weather.py 北京
    python3 scripts/weather.py "New York"
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "请提供城市名，例：python3 weather.py 北京"}, ensure_ascii=False))
        return
    city = sys.argv[1]
    url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        desc = current.get("weatherDesc", [{}])[0].get("value", "")
        result = {
            "city": (area.get("areaName") or [{}])[0].get("value", city),
            "country": (area.get("country") or [{}])[0].get("value", ""),
            "description": desc,
            "temp_c": current.get("temp_C"),
            "feels_like_c": current.get("FeelsLikeC"),
            "humidity": current.get("humidity"),
            "wind_kmh": current.get("windspeedKmph"),
            "precip_mm": current.get("precipMM"),
        }
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": f"天气查询失败: {exc}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
