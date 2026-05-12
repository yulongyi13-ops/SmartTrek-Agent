"""封装 DeepSeek(OpenAI 兼容) 客户端调用。"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

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

    def iter_chat_stream_text(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterator[str]:
        """流式输出 assistant 文本 delta（仅 content 片段，不含 tool_calls 解析）。

        工具轮仍应使用非流式 `chat`；终稿无工具时可调用本方法做 token 级流式。
        若 API 在流中返回 tool_calls，本迭代器会忽略（调用方需保证 tools=None 或模型不返回工具）。
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        stream = self.client.chat.completions.create(**payload)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            piece = getattr(delta, "content", None) or ""
            if piece:
                yield piece

    def chat_stream_collect(self, messages: List[Dict[str, Any]]) -> str:
        """无工具流式调用并拼接完整文本；失败时抛出由调用方捕获。"""
        return "".join(self.iter_chat_stream_text(messages, tools=None))
