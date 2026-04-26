"""封装 DeepSeek(OpenAI 兼容) 客户端调用。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import OpenAI


class LLMClient:
    """LLM 调用封装。

    设计说明：
    - Agent 不直接依赖 SDK 细节，便于未来切换模型或统一做重试/日志；
    - chat 方法保留 tools 参数，支持 function-calling。
    """

    def __init__(
        self, api_key: str, base_url: str, model: str = "deepseek-chat"
    ) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        # DeepSeek 官方建议工具调用优先使用 deepseek-chat（V3）。
        self.model = (model or "deepseek-chat").strip()

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return self.client.chat.completions.create(**payload)
