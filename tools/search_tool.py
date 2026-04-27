"""联网搜索工具：调用 Tavily Search API。"""

from __future__ import annotations

from typing import Any, Dict, List

import requests
from pydantic import BaseModel, Field, ValidationError

from .base_tool import BaseTool


class TavilyResultItem(BaseModel):
    """Tavily 单条结果。"""

    title: str = "无标题"
    content: str = ""


class TavilySearchResponse(BaseModel):
    """Tavily 搜索响应。"""

    answer: str = "暂无直接总结。"
    results: List[TavilyResultItem] = Field(default_factory=list)


class WebSearchTool(BaseTool):
    """为 Agent 提供实时网络搜索能力。"""

    name = "web_search"
    description = "警告：绝对禁止用此工具直接搜索“XX城市三日游攻略”。本工具仅限用于查询具体的票务、营业状态、政策及实时避雷评价。"
    safety_level = "safe"

    _endpoint = "https://api.tavily.com/search"

    def __init__(self, tavily_api_key: str) -> None:
        self.tavily_api_key = tavily_api_key

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "警告：绝对禁止用此工具直接搜索“XX城市三日游攻略”。本工具仅限用于查询具体的票务、营业状态、政策及实时避雷评价，并返回精简总结与来源摘要。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词或自然语言问题。",
                        }
                    },
                    "required": ["query"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return "搜索失败：缺少 query 参数。"

        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": 3,
        }

        try:
            response = requests.post(self._endpoint, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            parsed = TavilySearchResponse.model_validate(data)
        except requests.RequestException as exc:
            return f"搜索失败：网络请求异常。错误信息: {exc}"
        except ValidationError as exc:
            return f"搜索失败：返回数据结构异常。错误信息: {exc}"
        except ValueError:
            return "搜索失败：服务返回了无法解析的 JSON。"
        except Exception as exc:  # noqa: BLE001
            return f"搜索失败：发生未知错误。错误信息: {exc}"

        lines = [f"【搜索总结】: {parsed.answer}"]
        lines.append("【参考来源】:")
        if not parsed.results:
            lines.append("1. 暂无有效网页摘要结果。")
            return "\n".join(lines)

        for idx, item in enumerate(parsed.results[:3], start=1):
            title = item.title.strip() or "无标题"
            content = (item.content or "").strip().replace("\n", " ")
            snippet = (content[:180] + "...") if len(content) > 180 else content
            lines.append(f"{idx}. {title} - {snippet}")
        return "\n".join(lines)
