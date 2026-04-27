"""工具工厂注册表：支持按名称为子 Agent 分配权限。"""

from __future__ import annotations

from typing import Any, Callable, Dict

from config.settings import Settings
from core.artifact_manager import ArtifactManager
from core.budget_manager import BudgetManager
from core.planner import PlanningManager
from tools.amap_tools import POISearchTool, RoutePlanningTool, WeatherTool
from tools.base_tool import BaseTool
from tools.budget_tool import RecordExpenseTool, SetTaskBudgetTool
from tools.export_tool import ExportIcsTool
from tools.memory_tool import UpdateMemoryTool
from tools.plan_tool import UpdatePlanTool
from tools.search_tool import WebSearchTool
from tools.skill_tool import LoadSkillTool
from tools.write_report_tool import WriteReportTool
from skills.registry import SkillRegistry

ToolFactory = Callable[[], BaseTool]


def build_tool_factories(
    settings: Settings,
    planner: PlanningManager,
    turn_getter: Callable[[], int],
    skill_registry: SkillRegistry,
    artifact_manager: ArtifactManager,
    budget_manager: BudgetManager,
    long_term_memory_manager: Any,
) -> Dict[str, ToolFactory]:
    """构建可复用的工具工厂映射。"""
    return {
        "weather": lambda: WeatherTool(amap_api_key=settings.amap_api_key),
        "poi": lambda: POISearchTool(amap_api_key=settings.amap_api_key),
        "route": lambda: RoutePlanningTool(amap_api_key=settings.amap_api_key),
        "plan": lambda: UpdatePlanTool(planner=planner, turn_getter=turn_getter),
        "budget": lambda: RecordExpenseTool(budget_manager=budget_manager),
        "set_task_budget": lambda: SetTaskBudgetTool(budget_manager=budget_manager),
        "skill": lambda: LoadSkillTool(skill_registry=skill_registry),
        "web_search": lambda: WebSearchTool(tavily_api_key=settings.tavily_api_key),
        "update_memory": lambda: UpdateMemoryTool(memory_manager=long_term_memory_manager),
        "write_report": lambda: WriteReportTool(artifact_manager=artifact_manager),
        "export_ics": lambda: ExportIcsTool(),
    }
