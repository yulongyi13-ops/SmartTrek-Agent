"""Agent 核心：支持父子智能体的分层执行。"""

from __future__ import annotations

import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterator, List, Optional

from config.settings import Settings
from core.artifact_manager import ArtifactManager
from core.budget_manager import BudgetManager
from core.events import AgentEvent, RunContext
from core.hooks import HookManager
from core.llm_client import LLMClient
from core.long_term_memory import MemoryManager as LongTermMemoryManager
from core.mcp_manager import MCPManager
from core.memory_manager import MemoryManager
from core.recovery import (
    RecoveryDecision,
    RecoveryState,
    analyze_and_recover,
    apply_recovery_side_effect,
)
from core.security import Mode, PermissionManager
from core.security import SecurityException
from core.task_manager import Task, TaskManager, TaskStatus
from hooks import LoggingHook, PermissionCheckHook, StateInjectionHook, TimeInjectionHook
from prompts.builder import SystemPromptBuilder
from skills.registry import SkillRegistry
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
        permission_manager: Optional[PermissionManager] = None,
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
        self.permission_manager = permission_manager or PermissionManager(mode=Mode.DEFAULT)
        self.deny_count = 0
        self.hook_manager = HookManager()
        self.hook_manager.add_hook(TimeInjectionHook())
        self.hook_manager.add_hook(StateInjectionHook())
        self.hook_manager.add_hook(PermissionCheckHook())
        self.hook_manager.add_hook(LoggingHook())

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

    def _summarize_for_child(self, run_messages: List[Dict[str, Any]], draft: str) -> str:
        """子 Agent 结束前强制做一次无工具总结，提炼关键信息。"""
        tail_messages = run_messages[-8:]
        normalized_tail: List[Dict[str, Any]] = []
        valid_tool_call_ids = set()

        # 只保留“assistant(tool_calls) -> tool(tool_call_id)”成对结构，避免 API 400。
        for message in tail_messages:
            role = message.get("role")
            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                for call in tool_calls:
                    call_id = call.get("id")
                    if call_id:
                        valid_tool_call_ids.add(call_id)
                normalized_tail.append(message)
                continue

            if role == "tool":
                tool_call_id = message.get("tool_call_id")
                if tool_call_id and tool_call_id in valid_tool_call_ids:
                    normalized_tail.append(message)
                continue

            normalized_tail.append(message)

        summary_messages = [
            {
                "role": "system",
                "content": (
                    "你是子智能体总结器。请基于上下文输出精简结论，"
                    "必须包含关键事实、关键数据、失败项（如有）。"
                ),
            },
            *normalized_tail,
            {"role": "assistant", "content": draft},
        ]
        response = self.llm_client.chat(messages=summary_messages, tools=None)
        summary = (response.choices[0].message.content or "").strip()
        return summary or draft

    def _call_llm_with_recovery(
        self, context: RunContext, tool_schemas: Optional[List[Dict[str, Any]]]
    ) -> Any:
        """带自愈循环的 LLM 调用。"""
        recovery_state = RecoveryState()

        while True:
            try:
                response = self.llm_client.chat(messages=context.messages, tools=tool_schemas or None)
            except Exception as exc:  # noqa: BLE001
                decision = analyze_and_recover(exc, recovery_state, context)
                if decision == RecoveryDecision.ABORT:
                    raise SecurityException(
                        f"LLM 调用失败且超过恢复阈值，错误类型={recovery_state.last_error_type}"
                    ) from exc
                apply_recovery_side_effect(
                    decision=decision,
                    state=recovery_state,
                    context=context,
                    memory_manager=self.memory_manager,
                    llm_client=self.llm_client,
                )
                continue

            finish_reason = str(response.choices[0].finish_reason or "").lower()
            if finish_reason in {"length", "max_tokens"}:
                decision = analyze_and_recover(response, recovery_state, context)
                if decision == RecoveryDecision.ABORT:
                    raise SecurityException(
                        f"LLM 输出截断且超过恢复阈值，错误类型={recovery_state.last_error_type}"
                    )
                apply_recovery_side_effect(
                    decision=decision,
                    state=recovery_state,
                    context=context,
                    memory_manager=self.memory_manager,
                    llm_client=self.llm_client,
                )
                continue

            if recovery_state.accumulated_content:
                merged = recovery_state.accumulated_content + (response.choices[0].message.content or "")
                response.choices[0].message.content = merged
            return response

    def _parse_tool_args(self, raw_args: str) -> Dict[str, Any]:
        try:
            return json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            return {}

    def _run_single_tool(self, tool_map: Dict[str, BaseTool], tool_name: str, parsed_args: Dict[str, Any]) -> str:
        try:
            tool = tool_map[tool_name]
            return tool.run(**parsed_args)
        except KeyError:
            return f"工具调用失败：未注册的工具 {tool_name}。"
        except Exception as exc:  # noqa: BLE001
            return f"工具调用失败：{tool_name} 执行异常，错误信息: {exc}"

    def _build_fanin_summary(self, rows: List[Dict[str, str]]) -> str:
        lines = ["## 并发子任务汇总"]
        for idx, row in enumerate(rows, start=1):
            content = row["result"].replace("\n", " ").strip()
            compact = content[:220] + ("..." if len(content) > 220 else "")
            lines.append(f"- 任务{idx}（{row['tool_call_id']}）：{compact}")
        return "\n".join(lines)

    def _execute_tool_calls(
        self,
        context: RunContext,
        assistant_message: Any,
        run_messages: List[Dict[str, Any]],
        tool_map: Dict[str, BaseTool],
        used_tools: List[str],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Optional[str]:
        def _emit(ev: Dict[str, Any]) -> None:
            if progress_callback is not None:
                progress_callback(ev)

        tool_calls = assistant_message.tool_calls or []
        delegate_only = bool(tool_calls) and all(
            call.function.name == "delegate_task" for call in tool_calls
        )

        if delegate_only and len(tool_calls) > 1:
            _emit(
                {
                    "type": "node",
                    "message": f"并发启动 {len(tool_calls)} 个 delegate_task 子任务…",
                }
            )
            future_map = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    used_tools.append(tool_name)
                    args = self._parse_tool_args(tool_call.function.arguments or "{}")
                    future = executor.submit(self._run_single_tool, tool_map, tool_name, args)
                    future_map[future] = tool_call.id

                rows: List[Dict[str, str]] = []
                for future in as_completed(future_map):
                    call_id = future_map[future]
                    rows.append({"tool_call_id": call_id, "result": future.result()})
                    short_id = (call_id or "")[:10]
                    _emit(
                        {
                            "type": "node",
                            "message": f"一路 delegate_task 已完成（call …{short_id}）",
                        }
                    )

            rows.sort(key=lambda item: item["tool_call_id"])
            summary = self._build_fanin_summary(rows)
            primary_id = rows[0]["tool_call_id"]
            for row in rows:
                content = summary if row["tool_call_id"] == primary_id else f"并发结果已汇总到 {primary_id}"
                run_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": row["tool_call_id"],
                        "name": "delegate_task",
                        "content": content,
                    }
                )
            context.messages = run_messages
            return None

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            used_tools.append(tool_name)
            parsed_args = self._parse_tool_args(tool_call.function.arguments or "{}")
            _emit({"type": "node", "message": f"正在执行工具 `{tool_name}` …"})
            _emit(
                {
                    "type": "log",
                    "message": f"`{tool_name}` 参数摘要: {str(parsed_args)[:200]}",
                    "tool": tool_name,
                    "phase": "tool_start",
                }
            )

            try:
                tool = tool_map[tool_name]
                context.current_tool = tool
                context.kwargs = parsed_args
                self.hook_manager.trigger(AgentEvent.ON_TOOL_START, context)
                if tool_name.startswith("mcp_"):
                    mcp_manager = context.metadata.get("mcp_manager")
                    if mcp_manager is None:
                        raise RuntimeError("MCP 管理器不可用，无法执行 MCP 工具。")
                    tool_result = mcp_manager.call_tool(tool_name, parsed_args)
                else:
                    tool_result = tool.run(**parsed_args)
                self.deny_count = 0
                context.metadata["deny_count"] = self.deny_count
            except KeyError:
                tool_result = f"工具调用失败：未注册的工具 {tool_name}。"
                context.metadata["last_error"] = tool_result
                self.hook_manager.trigger(AgentEvent.ON_ERROR, context)
            except PermissionError as exc:
                self.deny_count += 1
                context.metadata["deny_count"] = self.deny_count
                tool_result = str(exc)
                context.metadata["last_error"] = tool_result
                self.hook_manager.trigger(AgentEvent.ON_ERROR, context)
                if self.deny_count >= 3:
                    severe_warning = "你已连续多次触发安全限制，当前任务中止，请重新审视你的目标。"
                    run_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": severe_warning,
                        }
                    )
                    self.messages = run_messages
                    return severe_warning
            except Exception as exc:  # noqa: BLE001
                tool_result = f"工具调用失败：{tool_name} 执行异常，错误信息: {exc}"
                context.metadata["last_error"] = tool_result
                self.hook_manager.trigger(AgentEvent.ON_ERROR, context)

            run_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result,
                }
            )
            context.messages = run_messages
            self.hook_manager.trigger(AgentEvent.ON_TOOL_END, context)
            preview = (tool_result or "")[:160].replace("\n", " ")
            _emit(
                {
                    "type": "log",
                    "message": f"`{tool_name}` 完成，结果预览: {preview}{'…' if len(tool_result or '') > 160 else ''}",
                    "tool": tool_name,
                    "phase": "tool_end",
                }
            )
        return None

    def run(self, task_prompt: str) -> str:
        """执行单次任务。子 Agent 的中间过程不会回写父 Agent。"""
        run_messages = self._build_run_messages(task_prompt)
        tool_map = self._tool_map()
        tool_schemas = self._tool_schemas()
        final_content = ""
        used_tools: List[str] = []
        context = RunContext(
            agent_name=self.name,
            messages=run_messages,
            metadata={
                "permission_manager": self.permission_manager,
                "deny_count": self.deny_count,
                "available_tools": self.tools,
                "mcp_manager": getattr(self, "mcp_manager", None),
            },
        )
        self.hook_manager.trigger(AgentEvent.ON_RUN_START, context)

        for _ in range(self.max_iterations):
            # 发送到模型前先做压缩：system + rolling summary + working memory。
            self.hook_manager.trigger(AgentEvent.ON_LLM_START, context)
            run_messages = self.memory_manager.compress_messages(context.messages, self.llm_client)
            context.messages = run_messages
            response = self._call_llm_with_recovery(context=context, tool_schemas=tool_schemas)
            context.llm_response = response
            self.hook_manager.trigger(AgentEvent.ON_LLM_END, context)
            choice = response.choices[0]
            assistant_message = choice.message
            finish_reason = choice.finish_reason
            run_messages.append(assistant_message.model_dump(exclude_none=True))
            context.messages = run_messages

            if assistant_message.tool_calls:
                severe_warning = self._execute_tool_calls(
                    context=context,
                    assistant_message=assistant_message,
                    run_messages=run_messages,
                    tool_map=tool_map,
                    used_tools=used_tools,
                )
                if severe_warning:
                    return severe_warning
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
        initial_budget: float = 50000.0,
        mode: Mode = Mode.DEFAULT,
        mcp_manager: Optional[MCPManager] = None,
    ) -> None:
        super().__init__(
            name="Parent Agent",
            llm_client=llm_client,
            tools=tools,
            system_prompt="你是一个专业、耐心的旅游规划助手。",
            max_iterations=50,
            messages=messages,
            permission_manager=PermissionManager(mode=mode),
        )
        self.budget_manager = BudgetManager(total_assets=initial_budget)
        self.long_term_memory = LongTermMemoryManager()
        self.skill_registry = SkillRegistry()
        self.artifact_manager = ArtifactManager()
        self.task_manager = TaskManager()
        self.prompt_builder = SystemPromptBuilder()
        self.mcp_manager = mcp_manager
        self.artifact_manager.migrate_legacy_outputs()
        self.long_term_memory.migrate_legacy_profile()
        self.turn_index = 0

    @classmethod
    def create_with_default_tools(
        cls,
        llm_client: LLMClient,
        settings: Settings,
        initial_budget: float = 50000.0,
        mode: Mode = Mode.DEFAULT,
    ) -> "TravelAgent":
        agent = cls(llm_client=llm_client, initial_budget=initial_budget, mode=mode)

        # 延迟导入，避免 core.agent <-> tools.delegate_tool 循环依赖。
        from tools.delegate_tool import DelegateTaskTool
        from tools.registry import build_mcp_parent_tools, build_tool_factories

        mcp_manager = MCPManager(config_path=settings.mcp_config_path)
        mcp_manager.start_all()
        agent.mcp_manager = mcp_manager

        tool_factories = build_tool_factories(
            settings=settings,
            skill_registry=agent.skill_registry,
            artifact_manager=agent.artifact_manager,
            budget_manager=agent.budget_manager,
            long_term_memory_manager=agent.long_term_memory,
            task_manager=agent.task_manager,
        )

        parent_tools = [
            tool_factories["set_task_budget"](),
            tool_factories["budget"](),
            tool_factories["skill"](),
            tool_factories["update_memory"](),
            tool_factories["write_report"](),
            tool_factories["export_ics"](),
            tool_factories["task_create"](),
            tool_factories["task_update"](),
            tool_factories["task_get"](),
            tool_factories["task_list"](),
            DelegateTaskTool(
                parent_agent=agent,
                tool_factories=tool_factories,
                child_llm_client_builder=lambda: LLMClient(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                    model=settings.child_model,
                ),
            ),
        ]
        parent_tools.extend(build_mcp_parent_tools(mcp_manager=agent.mcp_manager))
        agent.set_tools(parent_tools)
        return agent

    def close(self) -> None:
        if self.mcp_manager is not None:
            self.mcp_manager.stop_all()

    def _render_task_snapshot(self) -> str:
        tasks = self.task_manager.list_tasks()
        if not tasks:
            return "### 当前任务看板\n- 暂无任务（请先调用 `task_create` 拆解目标）"

        def _sort_key(item: Task) -> tuple[int, str]:
            status_order = {
                TaskStatus.IN_PROGRESS: 0,
                TaskStatus.PENDING: 1,
                TaskStatus.COMPLETED: 2,
                TaskStatus.DELETED: 3,
            }
            return (status_order.get(item.status, 9), item.id)

        lines = ["### 当前任务看板"]
        for task in sorted(tasks, key=_sort_key):
            lines.append(
                f"- [{task.status.value}] {task.subject} (id={task.id}, blockedBy={task.blockedBy or []})"
            )
        return "\n".join(lines)

    def get_plan_overview(self) -> str:
        return self._render_task_snapshot()

    def get_budget_overview(self) -> str:
        return self.budget_manager.render_ledger()

    def _auto_extract_long_term_memory(self, task_prompt: str) -> None:
        """从用户输入中自动提取高价值长期信息。"""
        text = task_prompt.strip()
        patterns = [
            r"我在(?P<city>[\u4e00-\u9fa5]{2,10})上学",
            r"我在(?P<city>[\u4e00-\u9fa5]{2,10})工作",
            r"我常住(?P<city>[\u4e00-\u9fa5]{2,10})",
            r"我长期住在(?P<city>[\u4e00-\u9fa5]{2,10})",
            r"我在(?P<city>[\u4e00-\u9fa5]{2,10})读书",
        ]
        for p in patterns:
            match = re.search(p, text)
            if match:
                city = match.group("city")
                self.long_term_memory.update_memory(
                    category="conventions",
                    action="update",
                    key="常驻出发地",
                    value=city,
                )
                self.long_term_memory.save_to_disk()
                break

    def _auto_set_task_budget(self, task_prompt: str) -> None:
        """自动识别用户在本次输入中的专项预算。"""
        text = task_prompt.strip()
        match = re.search(r"预算\s*([0-9]+(?:\.[0-9]+)?)\s*元?", text)
        if match:
            amount = float(match.group(1))
            self.budget_manager.set_task_budget(amount)
            return

        if self.budget_manager.current_task_budget is None:
            # 回退到总资产，避免因未设置任务预算导致预算工具不工作。
            self.budget_manager.set_task_budget(self.budget_manager.total_assets)

    def run(self, task_prompt: str) -> str:
        self.turn_index += 1
        self._auto_extract_long_term_memory(task_prompt)
        self._auto_set_task_budget(task_prompt)

        run_messages = self._build_run_messages(task_prompt)
        context = RunContext(
            agent_name=self.name,
            messages=run_messages,
            metadata={
                "permission_manager": self.permission_manager,
                "deny_count": self.deny_count,
                "prompt_builder": self.prompt_builder,
                "memory_manager": self.long_term_memory,
                "skill_registry": self.skill_registry,
                "budget_manager": self.budget_manager,
                "task_manager": self.task_manager,
                "available_tools": self.tools,
                "mcp_manager": self.mcp_manager,
            },
        )
        self.hook_manager.trigger(AgentEvent.ON_RUN_START, context)

        result = self._run_with_context(context)
        return result

    def iter_run_events(self, task_prompt: str) -> Iterator[Dict[str, Any]]:
        """流式产出规划进度（node / log / text_delta）与最终 `final` 事件；供 Streamlit 等 UI 消费。"""
        self.turn_index += 1
        self._auto_extract_long_term_memory(task_prompt)
        self._auto_set_task_budget(task_prompt)

        run_messages = self._build_run_messages(task_prompt)
        context = RunContext(
            agent_name=self.name,
            messages=run_messages,
            metadata={
                "permission_manager": self.permission_manager,
                "deny_count": self.deny_count,
                "prompt_builder": self.prompt_builder,
                "memory_manager": self.long_term_memory,
                "skill_registry": self.skill_registry,
                "budget_manager": self.budget_manager,
                "task_manager": self.task_manager,
                "available_tools": self.tools,
                "mcp_manager": self.mcp_manager,
                "emit_stream_events": True,
                "synthetic_stream_chunk_size": 48,
            },
        )
        self.hook_manager.trigger(AgentEvent.ON_RUN_START, context)
        try:
            yield from self._iter_run_with_context(context)
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "message": str(exc)}
            yield {"type": "final", "text": f"Agent 运行出错: {exc}"}

    def _run_with_context(self, context: RunContext) -> str:
        """同步执行：消费事件流直至 `final`（不向调用方暴露中间事件）。"""
        final_text = ""
        for ev in self._iter_run_with_context(context):
            if ev.get("type") == "final":
                final_text = str(ev.get("text", ""))
        return final_text

    def _iter_run_with_context(self, context: RunContext) -> Iterator[Dict[str, Any]]:
        """主规划循环：产出结构化事件；终稿使用基于缓冲文本的分块 text_delta（避免双次 LLM）。"""
        run_messages = context.messages
        tool_map = self._tool_map()
        tool_schemas = self._tool_schemas()
        final_content = ""
        used_tools: List[str] = []
        emit_stream = bool(context.metadata.get("emit_stream_events", False))
        chunk_sz = max(8, int(context.metadata.get("synthetic_stream_chunk_size", 48) or 48))

        for iter_idx in range(self.max_iterations):
            yield {
                "type": "log",
                "message": f"第 {iter_idx + 1}/{self.max_iterations} 轮：压缩上下文并请求模型…",
                "phase": "llm_round",
            }
            self.hook_manager.trigger(AgentEvent.ON_LLM_START, context)
            run_messages = self.memory_manager.compress_messages(context.messages, self.llm_client)
            context.messages = run_messages
            response = self._call_llm_with_recovery(context=context, tool_schemas=tool_schemas)
            context.llm_response = response
            self.hook_manager.trigger(AgentEvent.ON_LLM_END, context)
            choice = response.choices[0]
            assistant_message = choice.message
            finish_reason = choice.finish_reason
            run_messages.append(assistant_message.model_dump(exclude_none=True))
            context.messages = run_messages

            if assistant_message.tool_calls:
                progress_buf: List[Dict[str, Any]] = []
                severe_warning = self._execute_tool_calls(
                    context=context,
                    assistant_message=assistant_message,
                    run_messages=run_messages,
                    tool_map=tool_map,
                    used_tools=used_tools,
                    progress_callback=progress_buf.append,
                )
                for ev in progress_buf:
                    yield ev
                if severe_warning:
                    self.last_run_tool_names = used_tools
                    yield {"type": "final", "text": severe_warning}
                    return
                continue

            candidate = (assistant_message.content or "").strip()
            if candidate or finish_reason == "stop":
                if re.search(r"\d+(?:\.\d+)?\s*元", candidate) and not self.budget_manager.expenses:
                    yield {
                        "type": "log",
                        "message": "检测到方案含金额但账本为空，要求模型先记账再继续。",
                        "phase": "budget_gate",
                    }
                    run_messages.append(
                        {
                            "role": "system",
                            "content": (
                                "检测到你已给出包含金额的最终方案，但账本仍为空。"
                                "请先调用 `record_expense` 记录所有已确定花费，再输出最终结果。"
                            ),
                        }
                    )
                    context.messages = run_messages
                    continue
                yield {"type": "node", "message": "正在输出最终行程方案…"}
                if emit_stream and candidate:
                    for i in range(0, len(candidate), chunk_sz):
                        yield {"type": "text_delta", "text": candidate[i : i + chunk_sz]}
                final_content = candidate or "任务已完成。"
                break

            yield {"type": "log", "message": "模型返回空内容，已注入重试提示。", "phase": "empty_reply"}
            run_messages.append(
                {
                    "role": "system",
                    "content": "请输出最终完整结果，避免空内容。",
                }
            )

        if not final_content:
            final_content = f"执行失败：{self.name} 达到最大迭代次数({self.max_iterations})。"

        self.last_run_tool_names = used_tools
        self.messages = run_messages
        yield {"type": "final", "text": final_content}
