"""工具工厂注册表：支持本地工具与 MCP 工具统一注册。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from config.settings import Settings
from core.artifact_manager import ArtifactManager
from core.budget_manager import BudgetManager
from core.mcp_manager import MCPManager
from core.task_manager import TaskManager
from tools.amap_tools import POISearchTool, RoutePlanningTool, WeatherTool
from tools.base_tool import BaseTool
from tools.budget_tool import RecordExpenseTool, SetTaskBudgetTool
from tools.export_tool import ExportIcsTool
from tools.memory_tool import UpdateMemoryTool
from tools.search_tool import WebSearchTool
from tools.skill_tool import LoadSkillTool
from tools.task_tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool
from tools.write_report_tool import WriteReportTool
from skills.registry import SkillRegistry

ToolFactory = Callable[[], BaseTool]


def _adapt_mcp_schema_to_function_params(input_schema: Dict[str, Any] | None) -> Dict[str, Any]:
    """将 MCP inputSchema 适配为 OpenAI/DeepSeek function parameters。"""
    schema = input_schema or {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    merged = dict(schema)
    if merged.get("type") != "object":
        merged["type"] = "object"
    merged.setdefault("properties", {})
    return merged


class MCPProxyTool(BaseTool):
    """MCP 工具代理：由前缀工具名路由到 MCPManager。"""

    safety_level = "safe"
    base_weight = 20

    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: Dict[str, Any],
        mcp_manager: MCPManager,
    ) -> None:
        self.name = name
        self.description = description or "MCP 工具代理"
        self.parameters_schema = parameters_schema
        self.mcp_manager = mcp_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def run(self, **kwargs: Any) -> str:
        return self.mcp_manager.call_tool(self.name, kwargs)


def build_mcp_parent_tools(mcp_manager: MCPManager | None) -> List[BaseTool]:
    """把 MCP 工具动态转换并并入父 Agent 工具集合。"""
    if mcp_manager is None:
        return []
    tools: List[BaseTool] = []
    for item in mcp_manager.list_prefixed_tools():
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        parameters = _adapt_mcp_schema_to_function_params(item.get("inputSchema"))
        tools.append(
            MCPProxyTool(
                name=name,
                description=str(item.get("description", "")).strip(),
                parameters_schema=parameters,
                mcp_manager=mcp_manager,
            )
        )
    return tools


def build_tool_factories(
    settings: Settings,
    skill_registry: SkillRegistry,
    artifact_manager: ArtifactManager,
    budget_manager: BudgetManager,
    long_term_memory_manager: Any,
    task_manager: TaskManager,
) -> Dict[str, ToolFactory]:
    """构建可复用的工具工厂映射。"""
    return {
        "weather": lambda: WeatherTool(amap_api_key=settings.amap_api_key),
        "poi": lambda: POISearchTool(amap_api_key=settings.amap_api_key),
        "route": lambda: RoutePlanningTool(amap_api_key=settings.amap_api_key),
        "budget": lambda: RecordExpenseTool(budget_manager=budget_manager),
        "set_task_budget": lambda: SetTaskBudgetTool(budget_manager=budget_manager),
        "skill": lambda: LoadSkillTool(skill_registry=skill_registry),
        "web_search": lambda: WebSearchTool(tavily_api_key=settings.tavily_api_key),
        "update_memory": lambda: UpdateMemoryTool(memory_manager=long_term_memory_manager),
        "write_report": lambda: WriteReportTool(artifact_manager=artifact_manager),
        "export_ics": lambda: ExportIcsTool(),
        "task_create": lambda: TaskCreateTool(task_manager=task_manager),
        "task_update": lambda: TaskUpdateTool(task_manager=task_manager),
        "task_get": lambda: TaskGetTool(task_manager=task_manager),
        "task_list": lambda: TaskListTool(task_manager=task_manager),
    }
