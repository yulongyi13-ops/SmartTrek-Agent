"""对话记忆压缩管理：滑动窗口 + 滚动摘要。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from core.llm_client import LLMClient


class MemoryManager:
    """管理上下文长度，避免 messages 膨胀。"""

    def __init__(self, max_tokens: int = 6000, keep_recent_user_turns: int = 4) -> None:
        self.max_tokens = max_tokens
        self.keep_recent_user_turns = keep_recent_user_turns
        self.rolling_summary = ""

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        return int(len(str(messages)) / 3.5)

    def _build_summary_prompt(self, old_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        content = json.dumps(old_messages, ensure_ascii=False)
        summary_context = self.rolling_summary or "无"
        return [
            {
                "role": "system",
                "content": (
                    "你是对话压缩器。请把旧对话压缩成结构化连续性摘要。"
                    "严格按以下 5 个部分输出 Markdown：\n"
                    "1. 当前任务目标 (Current Goal)\n"
                    "2. 已完成的关键动作 (Completed Actions)\n"
                    "3. 已修改或重点查看过的文件 (Artifacts/Files)\n"
                    "4. 关键决定与约束 (Decisions & Constraints)\n"
                    "5. 下一步应该做什么 (Next Steps)\n"
                    "要求简洁、可执行、无废话。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"旧 rolling_summary:\n{summary_context}\n\n"
                    f"需要压缩的历史消息(JSON):\n{content}"
                ),
            },
        ]

    def _split_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """拆分为 system / old / working 三段。"""
        if not messages:
            return [], [], []

        system_messages = [messages[0]] if messages[0].get("role") == "system" else []
        body = messages[1:] if system_messages else messages[:]
        user_indices = [idx for idx, msg in enumerate(body) if msg.get("role") == "user"]

        if len(user_indices) <= self.keep_recent_user_turns:
            return system_messages, [], body

        start_idx = user_indices[-self.keep_recent_user_turns]
        old_messages = body[:start_idx]
        working_messages = body[start_idx:]
        return system_messages, old_messages, working_messages

    def compress_messages(
        self, messages: List[Dict[str, Any]], llm_client: LLMClient
    ) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        if self._estimate_tokens(messages) <= self.max_tokens:
            return messages

        system_messages, old_messages, working_messages = self._split_messages(messages)
        if not old_messages:
            return messages

        try:
            summary_messages = self._build_summary_prompt(old_messages)
            response = llm_client.chat(messages=summary_messages, tools=None)
            new_summary = (response.choices[0].message.content or "").strip()
            if new_summary:
                self.rolling_summary = new_summary
        except Exception:
            # 压缩失败时保留原摘要，避免主流程中断。
            pass

        compressed: List[Dict[str, Any]] = []
        compressed.extend(system_messages)
        if self.rolling_summary:
            compressed.append(
                {
                    "role": "system",
                    "content": f"【Rolling Summary】\n{self.rolling_summary}",
                }
            )
        compressed.extend(working_messages)
        return compressed
