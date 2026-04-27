"""Hook 抽象与分发管理。"""

from __future__ import annotations

from typing import List

from core.events import AgentEvent, RunContext


class BaseHook:
    """Hook 抽象基类。"""

    def on_run_start(self, context: RunContext) -> None:
        pass

    def on_llm_start(self, context: RunContext) -> None:
        pass

    def on_llm_end(self, context: RunContext) -> None:
        pass

    def on_tool_start(self, context: RunContext) -> None:
        pass

    def on_tool_end(self, context: RunContext) -> None:
        pass

    def on_error(self, context: RunContext) -> None:
        pass


class HookManager:
    """管理并分发 Hook。"""

    def __init__(self) -> None:
        self.hooks: List[BaseHook] = []

    def add_hook(self, hook: BaseHook) -> None:
        self.hooks.append(hook)

    def trigger(self, event: AgentEvent, context: RunContext) -> None:
        method_name = event.value
        for hook in self.hooks:
            method = getattr(hook, method_name, None)
            if callable(method):
                method(context)
