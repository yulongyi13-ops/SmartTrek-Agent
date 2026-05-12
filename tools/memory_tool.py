"""长期记忆更新工具。"""

from __future__ import annotations

from typing import Any, Dict

from core.long_term_memory import MemoryManager
from .base_tool import BaseTool


class UpdateMemoryTool(BaseTool):
    """允许 Agent 自主维护长期用户画像。"""

    name = "update_memory"
    description = "更新用户长期档案（偏好、纠正、约定、外部指针）并落盘。"
    safety_level = "write"

    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "当用户表达长期偏好、纠正反馈或稳定背景信息时，"
                    "调用本工具更新长期档案并持久化。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "preferences",
                                "corrections",
                                "conventions",
                                "external_pointers",
                            ],
                        },
                        "action": {
                            "type": "string",
                            "enum": ["add", "update", "delete"],
                        },
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "condition": {
                            "type": "string",
                            "description": "记忆生效场景，默认全局通用，如：穷游时、爬山时。",
                            "default": "全局通用",
                        },
                        "conflict_resolution": {
                            "type": "string",
                            "enum": ["overwrite_global", "add_as_exception"],
                            "description": "冲突处理策略：全局覆盖或新增特例。",
                        },
                    },
                    "required": ["category", "action", "key"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        category = str(kwargs.get("category", "")).strip()
        action = str(kwargs.get("action", "")).strip()
        key = str(kwargs.get("key", "")).strip()
        value = str(kwargs.get("value", "")).strip()
        condition = str(kwargs.get("condition", "全局通用")).strip() or "全局通用"
        conflict_resolution = str(kwargs.get("conflict_resolution", "")).strip()
        try:
            msg = self.memory_manager.update_memory(
                category=category,
                action=action,
                key=key,
                value=value,
                condition=condition,
                conflict_resolution=conflict_resolution,
            )
            # 仅当更新动作正常执行时落盘；失败消息也可落盘保持一致，这里选择总是保存当前状态。
            self.memory_manager.save_to_disk()
            return f"{msg}（长期记忆已保存）"
        except Exception as exc:  # noqa: BLE001
            return f"更新长期记忆失败：{exc}"
