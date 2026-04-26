"""技能加载工具：按需读取领域知识正文。"""

from __future__ import annotations

from typing import Any, Dict

from skills.registry import SkillRegistry
from .base_tool import BaseTool


class LoadSkillTool(BaseTool):
    """让模型在需要时主动加载技能正文。"""

    name = "load_skill"
    description = "按技能名称加载扩展知识正文，避免系统提示词过长。"
    safety_level = "safe"

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self.skill_registry = skill_registry

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "根据技能名称加载详细领域知识。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "技能名称，必须来自技能目录。",
                        }
                    },
                    "required": ["skill_name"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        skill_name = str(kwargs.get("skill_name", "")).strip()
        if not skill_name:
            return "技能加载失败：缺少 skill_name 参数。"

        try:
            doc = self.skill_registry.get_skill_document(skill_name)
            return f"技能已加载：{doc.name}\n\n{doc.content}"
        except KeyError as exc:
            return f"技能加载失败：{exc}"
        except Exception as exc:  # noqa: BLE001
            return f"技能加载失败：发生未知错误，错误信息: {exc}"
