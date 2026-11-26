#!/usr/bin/env python3
"""通过 wttr.in 查询城市天气，输出 JSON（Python 标准库，无需依赖）。

用法：
    python3 scripts/weather.py 北京
    python3 scripts/weather.py "New York"

支持中文城市名（内置常见城市映射为拼音，避免 wttr.in 把中文当无效地名）。
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

# 常见中文城市 → 拼音/英文（wttr.in 需要拉丁字母地名）。
# 未收录的中文名会退化为直接请求，并在结果里提示。
CITY_MAP = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "苏州": "Suzhou",
    "昆山": "Kunshan",
    "无锡": "Wuxi",
    "常州": "Changzhou",
    "天津": "Tianjin",
    "重庆": "Chongqing",
    "成都": "Chengdu",
    "武汉": "Wuhan",
    "西安": "Xi'an",
    "长沙": "Changsha",
    "郑州": "Zhengzhou",
    "济南": "Jinan",
    "青岛": "Qingdao",
    "沈阳": "Shenyang",
    "大连": "Dalian",
    "哈尔滨": "Harbin",
    "长春": "Changchun",
    "石家庄": "Shijiazhuang",
    "太原": "Taiyuan",
    "合肥": "Hefei",
    "福州": "Fuzhou",
    "厦门": "Xiamen",
    "南昌": "Nanchang",
    "南宁": "Nanning",
    "昆明": "Kunming",
    "贵阳": "Guiyang",
    "兰州": "Lanzhou",
    "西宁": "Xining",
    "银川": "Yinchuan",
    "乌鲁木齐": "Urumqi",
    "呼和浩特": "Hohhot",
    "拉萨": "Lhasa",
    "海口": "Haikou",
    "三亚": "Sanya",
    "香港": "Hong Kong",
    "澳门": "Macau",
    "台北": "Taipei",
}


def resolve_city(raw: str) -> tuple[str, bool]:
    """返回 (请求用地名, 是否来自映射)。"""
    key = raw.strip()
    if key in CITY_MAP:
        return CITY_MAP[key], True
    # 已是拉丁字母，原样使用
    if all(ord(ch) < 128 for ch in key):
        return key, False
    # 未收录的中文名：去掉「市/县/区」后缀再试一次
    stripped = key.rstrip("市县区")
    if stripped in CITY_MAP:
        return CITY_MAP[stripped], True
    return key, False


def main() -> None:
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {"error": "请提供城市名，例：python3 weather.py 北京"},
                ensure_ascii=False,
            )
        )
        return

    raw = sys.argv[1]
    city, mapped = resolve_city(raw)
    url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        desc = current.get("weatherDesc", [{}])[0].get("value", "")
        resolved = (area.get("areaName") or [{}])[0].get("value", city)
        result = {
            "query": raw,
            "city": resolved,
            "country": (area.get("country") or [{}])[0].get("value", ""),
            "description": desc,
            "temp_c": current.get("temp_C"),
            "feels_like_c": current.get("FeelsLikeC"),
            "humidity": current.get("humidity"),
            "wind_kmh": current.get("windspeedKmph"),
            "precip_mm": current.get("precipMM"),
        }
        # 查询名与返回地名明显不符时给出提示，避免模型误以为是目标城市。
        if not mapped and all(ord(ch) >= 128 for ch in raw.strip()):
            result["warning"] = (
                f"'{raw}' 未在内置城市表中，wttr.in 返回的是 '{resolved}'。"
                "如不符请改用拼音（如 Kunshan）重试一次。"
            )
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": f"天气查询失败: {exc}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
