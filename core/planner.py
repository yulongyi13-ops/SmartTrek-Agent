"""显式计划管理器：独立于消息历史的外部状态。"""

from __future__ import annotations

from typing import Any, List, Literal

from pydantic import BaseModel, Field, ValidationError


PlanStatus = Literal["todo", "in_progress", "completed"]


class PlanStep(BaseModel):
    """计划步骤模型。"""

    task_description: str = Field(..., min_length=1, description="任务步骤描述")
    status: PlanStatus = Field(default="todo", description="步骤状态")


class PlanningManager(BaseModel):
    """维护计划步骤及更新元信息。"""

    steps: List[PlanStep] = Field(default_factory=list)
    last_updated_turn: int = 0

    def render_plan(self) -> str:
        """将当前计划渲染为结构化 Markdown 文本。"""
        if not self.steps:
            return "### 当前执行计划\n- 暂无计划（请先调用 `update_plan` 拆解复杂任务）"

        lines = ["### 当前执行计划"]
        for idx, step in enumerate(self.steps, start=1):
            lines.append(f"- 步骤{idx}: {step.task_description} ({step.status})")
        lines.append(f"- 最后更新时间轮次: {self.last_updated_turn}")
        return "\n".join(lines)

    def update_plan(self, new_plan_json: Any, current_turn: int) -> str:
        """更新计划，支持全量替换和增量追加。

        支持两种输入：
        1) list: 直接视为 plan_steps，执行全量替换；
        2) dict: {"plan_steps": [...], "mode": "replace|append"}。
        """
        try:
            mode = "replace"
            incoming_steps_raw: Any = new_plan_json

            if isinstance(new_plan_json, dict):
                incoming_steps_raw = new_plan_json.get("plan_steps", [])
                mode = str(new_plan_json.get("mode", "replace")).strip().lower()

            if not isinstance(incoming_steps_raw, list):
                return "计划更新失败：plan_steps 必须是列表。"

            incoming_steps = [PlanStep.model_validate(item) for item in incoming_steps_raw]

            if mode == "append":
                self.steps.extend(incoming_steps)
            else:
                self.steps = incoming_steps

            self.last_updated_turn = current_turn
            return f"计划已更新：共 {len(self.steps)} 步，模式={mode}。"
        except ValidationError as exc:
            return f"计划更新失败：步骤数据校验失败。错误信息: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"计划更新失败：发生未知错误。错误信息: {exc}"
