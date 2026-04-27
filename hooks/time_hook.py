"""时间注入 Hook：为相对时间语义提供现实锚点。"""

from __future__ import annotations

from datetime import datetime

from core.events import RunContext
from core.hooks import BaseHook


class TimeInjectionHook(BaseHook):
    """在 LLM 调用前注入当前系统时钟。"""

    def on_llm_start(self, context: RunContext) -> None:
        current_time = datetime.now().strftime("%Y-%m-%d %A %H:%M")
        context.metadata["current_time_text"] = (
            f"当前真实世界时间是：{current_time}。"
            "用户口中的“今天”“明天”请以此为基准进行推算。"
        )
