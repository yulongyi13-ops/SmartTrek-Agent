"""定义工具抽象与注册中心。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseTool(ABC):
    """所有工具都应实现的基础接口。

    设计说明：
    - name/description 用于给 LLM 识别工具用途；
    - to_openai_tool_schema 返回函数调用规范，便于统一注册；
    - run 是本地执行入口，Agent 只依赖这一个方法。
    """

    name: str
    description: str
    safety_level: str = "safe"
    requires_human_approval: bool = False
    base_weight: int = 30
    capabilities: List[str] = []

    @abstractmethod
    def to_openai_tool_schema(self) -> Dict[str, Any]:
        """返回可被 OpenAI/DeepSeek function-calling 识别的 schema。"""

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        """执行工具逻辑并返回字符串结果。"""


class ToolRegistry:
    """工具注册中心，支持后续灵活扩展。"""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已存在：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> BaseTool:
        if tool_name not in self._tools:
            raise KeyError(f"未注册的工具：{tool_name}")
        return self._tools[tool_name]

    def list_openai_tools(self) -> List[Dict[str, Any]]:
        """返回所有工具的 schema，直接用于 LLM 请求。"""
        return [tool.to_openai_tool_schema() for tool in self._tools.values()]
