"""父 Agent 委派工具：按需拉起子 Agent 执行子任务。"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Callable, Dict, List

from core.security import PermissionManager
from tools.base_tool import BaseTool


class DelegateTaskTool(BaseTool):
    """父 Agent 专属委派工具。"""

    name = "delegate_task"
    description = (
        "当且仅当你需要查询天气、搜索航班、查找酒店、搜索景点等具体外部信息时，"
        "必须调用此工具委派子智能体去完成。你自身没有直接访问外部互联网或地图 API 的权限。"
        "在委派时，请在 sub_task_description 中清晰描述你需要子智能体帮你查什么，"
        "并在 required_tools 中传入子智能体需要的工具名称（如 ['weather', 'poi']）。"
    )

    def __init__(
        self,
        parent_agent: Any,
        tool_factories: Dict[str, Callable[[], BaseTool]],
        child_max_iterations: int = 6,
    ) -> None:
        self.parent_agent = parent_agent
        self.tool_factories = tool_factories
        self.child_max_iterations = child_max_iterations

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "当且仅当你需要查询天气、搜索航班、查找酒店、搜索景点等具体外部信息时，"
                    "必须调用此工具委派子智能体去完成。你自身没有直接访问外部互联网或地图 API 的权限。"
                    "在委派时，请在 sub_task_description 中清晰描述你需要子智能体帮你查什么，"
                    "并在 required_tools 中传入子智能体需要的工具名称（如 ['weather', 'poi']）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sub_task_description": {
                            "type": "string",
                            "description": "子任务描述，例如查询北京未来天气并推荐景点。",
                        },
                        "required_tools": {
                            "type": "array",
                            "description": "子任务允许使用的工具键名列表。",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["sub_task_description", "required_tools"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        sub_task_description = str(kwargs.get("sub_task_description", "")).strip()
        required_tools = kwargs.get("required_tools", [])

        if not sub_task_description:
            return "委派失败：缺少 sub_task_description。"
        if not isinstance(required_tools, list) or not required_tools:
            return "委派失败：required_tools 必须是非空列表。"

        normalized_tools = [
            str(name).strip().lower().replace("-", "_")
            for name in required_tools
            if str(name).strip()
        ]
        alias_map = {
            "hotel": "poi",
            "hotels": "poi",
            "scenic": "poi",
            "sightseeing": "poi",
            "route_planning": "route",
            "routeplanning": "route",
            "search": "web_search",
            "websearch": "web_search",
            "tavily": "web_search",
        }
        resolved_tools = [alias_map.get(name, name) for name in normalized_tools]

        if not resolved_tools:
            return "委派失败：required_tools 为空。"

        invalid = [name for name in resolved_tools if name not in self.tool_factories]
        if invalid:
            return f"委派失败：存在未注册工具键名 {invalid}。"

        try:
            from core.agent import BaseAgent  # 局部导入，规避循环依赖

            print("\033[95m[Parent Agent] 决定委派任务...\033[0m")

            child_tools = [self.tool_factories[name]() for name in resolved_tools]
            parent_messages = self.parent_agent.get_messages_snapshot()
            context_tail = copy.deepcopy(parent_messages[-6:])
            planning_state = self.parent_agent.get_plan_overview()

            child_prompt = (
                f"你是一个专注于执行子任务的子智能体。\n"
                f"子任务目标：{sub_task_description}\n"
                "请只使用授权工具完成任务，并输出精简且包含关键数据的结果总结。\n"
                "如果失败，明确写出失败原因与可重试建议。\n"
                f"\n父级计划状态参考：\n{planning_state}"
            )

            child_agent = BaseAgent(
                name=f"Child Agent - {resolved_tools[0]}",
                llm_client=self.parent_agent.llm_client,
                tools=child_tools,
                system_prompt=child_prompt,
                max_iterations=self.child_max_iterations,
                messages=context_tail,
                force_final_summary=True,
                permission_manager=PermissionManager(
                    mode=self.parent_agent.permission_manager.mode
                ),
            )

            print("\033[94m    [Child Agent - Task] 开始执行子任务...\033[0m")
            child_result = child_agent.run(sub_task_description)
            print("\033[94m    [Child Agent - Task] 提取结果返回...\033[0m")
            print("\033[95m[Parent Agent] 收到子任务结果，更新计划...\033[0m")

            # Layer 1：大结果落盘，只把预览放回父 Agent 上下文。
            if len(child_result) > 900:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"child_report_{stamp}.md"
                preview = self.parent_agent.artifact_manager.save_artifact(
                    filename=filename,
                    content=child_result,
                )
                return f"子任务完成（长结果已落盘）：{preview}"

            return f"子任务完成：{child_result}"
        except Exception as exc:  # noqa: BLE001
            return f"委派执行失败：{exc}"
