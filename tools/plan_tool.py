"""计划管理工具：让模型显式更新执行计划。"""

from __future__ import annotations

from typing import Any, Callable, Dict

from core.planner import PlanningManager
from .base_tool import BaseTool


class UpdatePlanTool(BaseTool):
    """用于制定或修正计划。"""

    name = "update_plan"
    description = "更新任务计划步骤及状态（todo/in_progress/completed）。"
    safety_level = "write"

    def __init__(self, planner: PlanningManager, turn_getter: Callable[[], int]) -> None:
        self.planner = planner
        self.turn_getter = turn_getter

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "制定或更新执行计划。复杂任务开始前必须先调用，"
                    "后续步骤状态变化时也应及时更新。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan_steps": {
                            "type": "array",
                            "description": "计划步骤列表。",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task_description": {
                                        "type": "string",
                                        "description": "步骤描述。",
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["todo", "in_progress", "completed"],
                                        "description": "步骤状态。",
                                    },
                                },
                                "required": ["task_description", "status"],
                            },
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["replace", "append"],
                            "description": "更新模式：replace 全量替换，append 增量追加。",
                        },
                    },
                    "required": ["plan_steps"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        plan_steps = kwargs.get("plan_steps", [])
        mode = kwargs.get("mode", "replace")
        payload = {"plan_steps": plan_steps, "mode": mode}
        return self.planner.update_plan(payload, current_turn=self.turn_getter())
