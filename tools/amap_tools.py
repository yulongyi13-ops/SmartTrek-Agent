"""高德 Web 服务工具集：天气查询 + POI 搜索。"""

from __future__ import annotations

from typing import Any, Dict, List

import requests
from pydantic import BaseModel, Field, ValidationError

from .base_tool import BaseTool


class AmapWeatherCast(BaseModel):
    """单日天气预报数据。"""

    date: str = "未知日期"
    dayweather: str = "未知"
    nightweather: str = "未知"
    daytemp: str = "?"
    nighttemp: str = "?"


class AmapWeatherForecast(BaseModel):
    """天气预报主体。"""

    city: str = "未知城市"
    province: str = ""
    casts: List[AmapWeatherCast] = Field(default_factory=list)


class AmapWeatherResponse(BaseModel):
    """天气 API 响应模型。"""

    status: str
    info: str = "未知错误"
    forecasts: List[AmapWeatherForecast] = Field(default_factory=list)


class AmapBizExt(BaseModel):
    """POI 的商家扩展信息。"""

    rating: str | None = None
    cost: str | None = None


class AmapPOIItem(BaseModel):
    """POI 单条结果。"""

    name: str = "未知名称"
    address: str = "暂无地址"
    rating: str | None = None
    cost: str | None = None
    biz_ext: AmapBizExt | None = None


class AmapPOIResponse(BaseModel):
    """POI 搜索 API 响应模型。"""

    status: str
    info: str = "未知错误"
    pois: List[AmapPOIItem] = Field(default_factory=list)


class WeatherTool(BaseTool):
    """天气查询工具（调用高德天气 API）。"""

    name = "get_weather_forecast"
    description = "查询指定城市的天气预报信息（未来几天）。"

    _endpoint = "https://restapi.amap.com/v3/weather/weatherInfo"

    def __init__(self, amap_api_key: str) -> None:
        self.amap_api_key = amap_api_key

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "用于查询城市天气预报，适合出行前的天气评估。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称或 adcode，例如北京、310000。",
                        }
                    },
                    "required": ["city"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        city = str(kwargs.get("city", "")).strip()
        if not city:
            return "天气查询失败：缺少 city 参数。"

        params = {
            "city": city,
            "key": self.amap_api_key,
            "extensions": "all",  # all 返回预报，base 返回实况
        }

        try:
            resp = requests.get(self._endpoint, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            return f"天气查询失败，请检查网络或城市名。错误信息: {exc}"
        except ValueError:
            return "天气查询失败：服务返回了无法解析的 JSON。"
        except Exception as exc:  # noqa: BLE001
            return f"天气查询失败：请求过程中发生未知错误，错误信息: {exc}"

        try:
            parsed = AmapWeatherResponse.model_validate(data)
        except ValidationError as exc:
            return f"天气查询失败：返回数据结构异常，错误信息: {exc}"

        if parsed.status != "1":
            info = parsed.info
            return f"天气查询失败，请检查网络或城市名。错误信息: {info}"

        forecasts = parsed.forecasts
        if not forecasts:
            return "天气查询失败：未获取到有效预报数据。"

        forecast = forecasts[0]
        city_name = forecast.city or city
        province = forecast.province or ""
        casts = forecast.casts
        if not casts:
            return f"天气查询结果为空：{city_name} 暂无可用预报。"

        lines = [f"天气预报结果：{province}{city_name}".strip()]
        for item in casts[:5]:
            date = item.date
            day_weather = item.dayweather
            night_weather = item.nightweather
            day_temp = item.daytemp
            night_temp = item.nighttemp
            lines.append(
                f"- {date}: 白天{day_weather} {day_temp}C, 夜间{night_weather} {night_temp}C"
            )

        return "\n".join(lines)


class POISearchTool(BaseTool):
    """POI 关键字搜索工具（可用于酒店与景点）。"""

    name = "search_poi"
    description = "在指定城市按关键字搜索地点，可用于查酒店和景点。"

    _endpoint = "https://restapi.amap.com/v3/place/text"

    def __init__(self, amap_api_key: str) -> None:
        self.amap_api_key = amap_api_key

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "用于查询酒店、景点等地点信息，返回名称、地址与补充字段。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，例如北京、上海。",
                        },
                        "keywords": {
                            "type": "string",
                            "description": "搜索关键字，例如全季酒店、故宫、著名景点。",
                        },
                        "types": {
                            "type": "string",
                            "description": "POI 类型码（可选）。",
                        },
                    },
                    "required": ["city", "keywords"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        city = str(kwargs.get("city", "")).strip()
        keywords = str(kwargs.get("keywords", "")).strip()
        types = str(kwargs.get("types", "")).strip()

        if not city or not keywords:
            return "地点搜索失败：缺少 city 或 keywords 参数。"

        params: Dict[str, Any] = {
            "city": city,
            "keywords": keywords,
            "key": self.amap_api_key,
        }
        if types:
            params["types"] = types

        try:
            resp = requests.get(self._endpoint, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            return f"地点搜索失败，请检查网络或关键字。错误信息: {exc}"
        except ValueError:
            return "地点搜索失败：服务返回了无法解析的 JSON。"
        except Exception as exc:  # noqa: BLE001
            return f"地点搜索失败：请求过程中发生未知错误，错误信息: {exc}"

        try:
            parsed = AmapPOIResponse.model_validate(data)
        except ValidationError as exc:
            return f"地点搜索失败：返回数据结构异常，错误信息: {exc}"

        if parsed.status != "1":
            info = parsed.info
            return f"地点搜索失败，请检查网络或关键字。错误信息: {info}"

        pois = parsed.pois
        if not pois:
            return f"地点搜索结果为空：在 {city} 未找到“{keywords}”相关地点。"

        lines = [f"地点搜索结果：city={city}; keywords={keywords}; top=5"]
        for idx, poi in enumerate(pois[:5], start=1):
            name = poi.name
            address = poi.address
            rating = (poi.biz_ext.rating if poi.biz_ext else None) or poi.rating
            cost = (poi.biz_ext.cost if poi.biz_ext else None) or poi.cost

            extras = []
            if rating:
                extras.append(f"评分={rating}")
            if cost:
                extras.append(f"参考价={cost}")
            extra_text = f" ({', '.join(extras)})" if extras else ""

            lines.append(f"{idx}. {name} - {address}{extra_text}")

        return "\n".join(lines)
