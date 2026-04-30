"""任务管理工具：提供 DAG 任务的增删改查能力。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.task_manager import TaskManager, TaskStatus
from tools.base_tool import BaseTool


class TaskCreateTool(BaseTool):
    name = "task_create"
    description = "当你需要拆解复杂目标时，使用此工具创建子任务。可通过 blockedBy 指定必须先完成的任务ID。"
    safety_level = "write"

    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "description": "一句话任务目标。"},
                        "description": {"type": "string", "description": "任务补充说明。"},
                        "blockedBy": {
                            "type": "array",
                            "description": "前置任务 ID 列表。",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["subject", "description"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        subject = str(kwargs.get("subject", "")).strip()
        description = str(kwargs.get("description", "")).strip()
        blocked_by_raw = kwargs.get("blockedBy", [])
        blocked_by = (
            [str(item).strip() for item in blocked_by_raw if str(item).strip()]
            if isinstance(blocked_by_raw, list)
            else []
        )
        if not subject:
            return "创建失败：subject 不能为空。"
        if not description:
            return "创建失败：description 不能为空。"

        task = self.task_manager.create_task(
            subject=subject,
            description=description,
            blockedBy=blocked_by,
        )
        return f"创建成功：{task.id} | {task.subject} | blockedBy={task.blockedBy or '[]'}"


class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = "用于推进任务状态。当任务完成时，必须将状态设为 completed，并务必在 result_summary 中写明任务产出，以便后续任务读取。"
    safety_level = "write"

    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "任务 ID。"},
                        "status": {
                            "type": "string",
                            "enum": [item.value for item in TaskStatus],
                            "description": "目标状态。",
                        },
                        "result_summary": {
                            "type": "string",
                            "description": "完成任务后的产出摘要。",
                        },
                        "owner": {"type": "string", "description": "负责人名称。"},
                    },
                    "required": ["task_id", "status"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        task_id = str(kwargs.get("task_id", "")).strip()
        status_raw = str(kwargs.get("status", "")).strip()
        result_summary = str(kwargs.get("result_summary", "")).strip()
        owner = kwargs.get("owner")
        owner_text = str(owner).strip() if owner is not None else None

        if not task_id:
            return "更新失败：task_id 不能为空。"
        try:
            status = TaskStatus(status_raw)
        except ValueError:
            valid = ", ".join([item.value for item in TaskStatus])
            return f"更新失败：status 非法，可选值为 {valid}。"

        if status == TaskStatus.COMPLETED and not result_summary:
            return "更新失败：当 status=completed 时必须提供 result_summary。"

        task = self.task_manager.update_task_status(
            task_id=task_id,
            new_status=status,
            result_summary=result_summary,
            owner=owner_text,
        )
        if task is None:
            return f"更新失败：任务不存在 {task_id}。"
        return (
            f"更新成功：{task.id} -> {task.status.value} | owner={task.owner or 'None'} "
            f"| blockedBy={task.blockedBy} | blocks={task.blocks}"
        )


class TaskGetTool(BaseTool):
    name = "task_get"
    description = "读取某个特定任务的详细信息，特别是读取前置任务的 result_summary。"
    safety_level = "safe"

    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string", "description": "任务 ID。"}},
                    "required": ["task_id"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        task_id = str(kwargs.get("task_id", "")).strip()
        if not task_id:
            return "读取失败：task_id 不能为空。"
        task = self.task_manager.get_task(task_id)
        if task is None:
            return f"读取失败：任务不存在 {task_id}。"
        return task.model_dump_json(indent=2, ensure_ascii=False)


class TaskListTool(BaseTool):
    name = "task_list"
    description = "获取当前系统的全盘任务快照（全局视角）。"
    safety_level = "safe"

    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": [item.value for item in TaskStatus],
                            "description": "可选状态过滤，不传则返回全部任务。",
                        }
                    },
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        status_raw: Optional[str] = kwargs.get("status")
        status: Optional[TaskStatus] = None
        if status_raw:
            try:
                status = TaskStatus(str(status_raw).strip())
            except ValueError:
                valid = ", ".join([item.value for item in TaskStatus])
                return f"查询失败：status 非法，可选值为 {valid}。"

        tasks = self.task_manager.list_tasks(status=status)
        if not tasks:
            return "[]"
        payload: List[Dict[str, Any]] = [task.model_dump(mode="json") for task in tasks]
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2)
