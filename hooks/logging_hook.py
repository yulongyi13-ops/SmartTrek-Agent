"""日志 Hook：统一打印事件轨迹。"""

from __future__ import annotations

from core.events import RunContext
from core.hooks import BaseHook


class LoggingHook(BaseHook):
    """按事件打印日志，替代散落 print。"""

    def _log(self, color: str, msg: str) -> None:
        print(f"{color}{msg}\033[0m")

    def on_run_start(self, context: RunContext) -> None:
        self._log("\033[96m", f"[{context.agent_name}] run started")

    def on_llm_start(self, context: RunContext) -> None:
        self._log("\033[90m", f"[{context.agent_name}] llm start")

    def on_llm_end(self, context: RunContext) -> None:
        self._log("\033[90m", f"[{context.agent_name}] llm end")

    def on_tool_start(self, context: RunContext) -> None:
        tool_name = getattr(context.current_tool, "name", "unknown")
        self._log("\033[95m", f"[{context.agent_name}] tool start: {tool_name}")

    def on_tool_end(self, context: RunContext) -> None:
        tool_name = getattr(context.current_tool, "name", "unknown")
        self._log("\033[95m", f"[{context.agent_name}] tool end: {tool_name}")

    def on_error(self, context: RunContext) -> None:
        error = context.metadata.get("last_error", "unknown")
        self._log("\033[91m", f"[{context.agent_name}] error: {error}")
