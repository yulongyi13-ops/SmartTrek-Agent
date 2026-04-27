"""Agent 事件与运行上下文定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentEvent(str, Enum):
    """Agent 生命周期事件。"""

    ON_RUN_START = "on_run_start"
    ON_LLM_START = "on_llm_start"
    ON_LLM_END = "on_llm_end"
    ON_TOOL_START = "on_tool_start"
    ON_TOOL_END = "on_tool_end"
    ON_ERROR = "on_error"


@dataclass
class RunContext:
    """运行态上下文，供 Hook 共享状态。"""

    agent_name: str
    messages: List[Dict[str, Any]]
    current_tool: Optional[Any] = None
    kwargs: Optional[Dict[str, Any]] = None
    llm_response: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
