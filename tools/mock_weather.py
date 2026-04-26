"""示例工具：模拟天气查询。"""

from __future__ import annotations

from typing import Any, Dict

from .base_tool import BaseTool


class MockWeatherTool(BaseTool):
    """一个演示用途的假天气工具。

    设计说明：
    - 当前返回固定模板数据，便于先跑通 Agent 架构；
    - 后续可将 run 内部替换为真实天气 API，无需改动 Agent 框架。
    """

    name = "get_mock_weather"
    description = "查询某个城市指定日期的模拟天气信息。"

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "目标城市，如北京、上海。",
                        },
                        "date": {
                            "type": "string",
                            "description": "日期描述，如今天、明天、2026-05-01。",
                        },
                    },
                    "required": ["city"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        city = str(kwargs.get("city", "")).strip() or "未知城市"
        date = str(kwargs.get("date", "今天")).strip() or "今天"

        # 这里使用固定返回，强调“结构化结果”的输出格式，便于 LLM 进一步整理回答。
        return (
            f"天气查询结果: city={city}; date={date}; "
            "weather=晴; temperature=18~26C; humidity=35%; "
            "advice=适合户外活动，建议携带薄外套。"
        )
