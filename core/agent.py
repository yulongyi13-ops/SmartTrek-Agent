"""Agent 核心：支持父子智能体的分层执行。"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from config.settings import Settings
from core.artifact_manager import ArtifactManager
from core.llm_client import LLMClient
from core.memory_manager import MemoryManager
from core.planner import PlanningManager
from skills.registry import SkillRegistry
from prompts.system_prompts import TRAVEL_AGENT_SYSTEM_PROMPT
from tools.base_tool import BaseTool


class BaseAgent:
    """可复用 Agent 基类，支持独立上下文与工具权限。"""

    def __init__(
        self,
        name: str,
        llm_client: LLMClient,
        tools: Optional[List[BaseTool]],
        system_prompt: str,
        max_iterations: int,
        messages: Optional[List[Dict[str, Any]]] = None,
        force_final_summary: bool = False,
        memory_manager: Optional[MemoryManager] = None,
    ) -> None:
        self.name = name
        self.llm_client = llm_client
        self.tools: List[BaseTool] = tools or []
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.messages: List[Dict[str, Any]] = copy.deepcopy(messages or [])
        self.force_final_summary = force_final_summary
        self.last_run_tool_names: List[str] = []
        self.memory_manager = memory_manager or MemoryManager()

    def set_tools(self, tools: List[BaseTool]) -> None:
        self.tools = tools

    def get_messages_snapshot(self) -> List[Dict[str, Any]]:
        """返回当前对话快照，供委派工具提取子任务上下文。"""
        return copy.deepcopy(self.messages)

    def _tool_map(self) -> Dict[str, BaseTool]:
        return {tool.name: tool for tool in self.tools}

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool_schema() for tool in self.tools]

    def _build_run_messages(self, task_prompt: str) -> List[Dict[str, Any]]:
        run_messages = copy.deepcopy(self.messages)
        run_messages.insert(0, {"role": "system", "content": self.system_prompt})
        run_messages.append({"role": "user", "content": task_prompt})
        return run_messages

    def _log_tool_call(self, tool_name: str) -> None:
        print(f"\033[90m[{self.name}] 正在调用工具 {tool_name} ...\033[0m")

    def _summarize_for_child(self, run_messages: List[Dict[str, Any]], draft: str) -> str:
        """子 Agent 结束前强制做一次无工具总结，提炼关键信息。"""
        summary_messages = [
            {
                "role": "system",
                "content": (
                    "你是子智能体总结器。请基于上下文输出精简结论，"
                    "必须包含关键事实、关键数据、失败项（如有）。"
                ),
            },
            *run_messages[-8:],
            {"role": "assistant", "content": draft},
        ]
        response = self.llm_client.chat(messages=summary_messages, tools=None)
        summary = (response.choices[0].message.content or "").strip()
        return summary or draft

    def run(self, task_prompt: str) -> str:
        """执行单次任务。子 Agent 的中间过程不会回写父 Agent。"""
        run_messages = self._build_run_messages(task_prompt)
        tool_map = self._tool_map()
        tool_schemas = self._tool_schemas()
        final_content = ""
        used_tools: List[str] = []

        for _ in range(self.max_iterations):
            # 发送到模型前先做压缩：system + rolling summary + working memory。
            run_messages = self.memory_manager.compress_messages(run_messages, self.llm_client)
            response = self.llm_client.chat(messages=run_messages, tools=tool_schemas or None)
            choice = response.choices[0]
            assistant_message = choice.message
            finish_reason = choice.finish_reason
            run_messages.append(assistant_message.model_dump(exclude_none=True))

            if assistant_message.tool_calls:
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    self._log_tool_call(tool_name)
                    used_tools.append(tool_name)
                    raw_args = tool_call.function.arguments or "{}"
                    try:
                        parsed_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        parsed_args = {}

                    try:
                        tool = tool_map[tool_name]
                        tool_result = tool.run(**parsed_args)
                    except KeyError:
                        tool_result = f"工具调用失败：未注册的工具 {tool_name}。"
                    except Exception as exc:  # noqa: BLE001
                        tool_result = f"工具调用失败：{tool_name} 执行异常，错误信息: {exc}"

                    run_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": tool_result,
                        }
                    )
                continue

            candidate = (assistant_message.content or "").strip()
            if candidate or finish_reason == "stop":
                final_content = candidate or "任务已完成。"
                break

            run_messages.append(
                {
                    "role": "system",
                    "content": "请输出最终完整结果，避免空内容。",
                }
            )

        if not final_content:
            final_content = f"执行失败：{self.name} 达到最大迭代次数({self.max_iterations})。"

        if self.force_final_summary:
            try:
                final_content = self._summarize_for_child(run_messages, final_content)
            except Exception as exc:  # noqa: BLE001
                final_content = f"{final_content}\n（子任务总结失败：{exc}）"

        # 仅持久化本实例上下文，父子实例天然隔离。
        self.last_run_tool_names = used_tools
        self.messages = run_messages
        return final_content


class TravelAgent(BaseAgent):
    """父 Agent：保留计划状态，并支持任务委派。"""

    def __init__(
        self,
        llm_client: LLMClient,
        tools: Optional[List[BaseTool]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(
            name="Parent Agent",
            llm_client=llm_client,
            tools=tools,
            system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
            max_iterations=20,
            messages=messages,
        )
        self.planner = PlanningManager()
        self.skill_registry = SkillRegistry()
        self.artifact_manager = ArtifactManager()
        self.turn_index = 0
        self.turns_since_update = 0

    @classmethod
    def create_with_default_tools(
        cls, llm_client: LLMClient, settings: Settings
    ) -> "TravelAgent":
        agent = cls(llm_client=llm_client)

        # 延迟导入，避免 core.agent <-> tools.delegate_tool 循环依赖。
        from tools.delegate_tool import DelegateTaskTool
        from tools.registry import build_tool_factories

        tool_factories = build_tool_factories(
            settings=settings,
            planner=agent.planner,
            turn_getter=lambda: agent.turn_index,
            skill_registry=agent.skill_registry,
            artifact_manager=agent.artifact_manager,
        )

        parent_tools = [
            tool_factories["weather"](),
            tool_factories["poi"](),
            tool_factories["plan"](),
            tool_factories["skill"](),
            tool_factories["write_report"](),
            DelegateTaskTool(parent_agent=agent, tool_factories=tool_factories),
        ]
        agent.set_tools(parent_tools)
        return agent

    def _build_dynamic_system_prompt(self, force_plan_reminder: bool) -> str:
        manifests = self.skill_registry.get_all_manifests()
        if manifests:
            skill_lines = [
                "【可用领域知识技能库】",
                "你可以使用 LoadSkillTool 加载以下扩展知识：",
            ]
            for item in manifests:
                skill_lines.append(f"- [{item.name}]: {item.description}")
            skill_catalog_text = "\n".join(skill_lines)
        else:
            skill_catalog_text = (
                "【可用领域知识技能库】\n当前未发现技能文档。"
                "如需扩展，请在 skills/data/ 目录新增 .md 文件。"
            )

        sections = [
            TRAVEL_AGENT_SYSTEM_PROMPT,
            "",
            "你必须遵循：当用户提出复杂、多步骤旅游任务时，第一步先调用 `update_plan` 拆解任务。",
            "当出现酒店/住宿多条件筛选与对比任务时，必须调用 `delegate_task` 让子智能体执行。",
            self.planner.render_plan(),
            "",
            skill_catalog_text,
            "请根据计划执行下一步；若实际进展变化，请优先调用 `update_plan` 更新状态。",
            "若最终输出很长，请调用 `write_report_file` 将完整版写入文件，并在回复中给摘要与文件路径。",
        ]
        if force_plan_reminder:
            sections.append(
                "【系统强制提醒】检测到计划已长时间未更新，请确认当前步骤是否已完成，并更新计划状态后再继续。"
            )
        return "\n".join(sections)

    def get_plan_overview(self) -> str:
        return self.planner.render_plan()

    def run(self, task_prompt: str) -> str:
        self.turn_index += 1
        self.system_prompt = self._build_dynamic_system_prompt(
            force_plan_reminder=self.turns_since_update >= 3
        )
        result = super().run(task_prompt)

        if "update_plan" in self.last_run_tool_names:
            self.turns_since_update = 0
        else:
            self.turns_since_update += 1
        return result
