"""从最终文本中提取地图路线点。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from core.llm_client import LLMClient


def _coerce_route_list(data: Any) -> List[Dict[str, Any]]:
    """将 JSON 数组规范为 name/lng/lat 列表。"""
    if not isinstance(data, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        try:
            lng = float(item.get("lng"))
            lat = float(item.get("lat"))
        except (TypeError, ValueError):
            continue
        if not name:
            continue
        normalized.append({"name": name, "lng": lng, "lat": lat})
    return normalized


def _regex_extract(text: str) -> List[Dict[str, Any]]:
    route: List[Dict[str, Any]] = []
    # 兼容示例：故宫(116.39,39.90) / 故宫：116.39, 39.90
    pattern = re.compile(
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9·\-_]{2,30})\s*(?:[:：\(（\s])+\s*"
        r"(?P<lng>1[0-7]\d(?:\.\d+)?)\s*[,，]\s*(?P<lat>[0-8]?\d(?:\.\d+)?)"
    )
    for match in pattern.finditer(text):
        try:
            lng = float(match.group("lng"))
            lat = float(match.group("lat"))
        except (TypeError, ValueError):
            continue
        route.append(
            {
                "name": match.group("name"),
                "lng": lng,
                "lat": lat,
            }
        )
    return route


def _json_candidates(blob: str) -> List[str]:
    """从代码块原文中尝试多种截取方式解析 JSON 数组。"""
    blob = blob.strip()
    if not blob:
        return []
    candidates = [blob]
    start = blob.find("[")
    end = blob.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidates.append(blob[start : end + 1])
    return candidates


def _fenced_json_extract(text: str) -> List[Dict[str, Any]]:
    """解析 Markdown 围栏代码块中的路线 JSON 数组（语言标记常为 json）。"""
    fence = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
    for match in fence.finditer(text):
        inner = match.group(1).strip()
        for candidate in _json_candidates(inner):
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            normalized = _coerce_route_list(data)
            if normalized:
                return normalized
    return []


def _llm_extract(text: str, llm_client: LLMClient) -> List[Dict[str, Any]]:
    prompt = (
        "请从下述旅游路线文本中提取地图点位，严格返回 JSON 数组，"
        "每项格式为 {\"name\": \"点位名\", \"lng\": 116.39, \"lat\": 39.90}。"
        "若无有效点位返回 []。不要返回任何额外文字。\n\n"
        f"文本如下：\n{text}"
    )
    response = llm_client.chat(
        messages=[
            {"role": "system", "content": "你是 JSON 提取器，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        tools=None,
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
        return _coerce_route_list(data)
    except json.JSONDecodeError:
        return []


def extract_map_route(text: str, llm_client: LLMClient | None = None) -> List[Dict[str, Any]]:
    """优先正则，其次围栏 JSON，最后可选 LLM 提取。"""
    route = _regex_extract(text)
    if route:
        return route
    route = _fenced_json_extract(text)
    if route:
        return route
    if llm_client is None:
        return []
    return _llm_extract(text=text, llm_client=llm_client)
