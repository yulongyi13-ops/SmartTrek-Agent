"""按 user_id 构建请求级 Agent（无状态入口 + 持久化隔离）。"""

from __future__ import annotations

from pathlib import Path

from config.settings import get_settings
from core.agent import TravelAgent
from core.artifact_manager import ArtifactManager
from core.llm_client import LLMClient
from core.long_term_memory import MemoryManager as LongTermMemoryManager
from core.mcp_manager import MCPManager
from core.security import Mode
from core.task_manager import TaskManager
from tools.delegate_tool import DelegateTaskTool
from tools.registry import build_mcp_parent_tools, build_tool_factories


def _safe_user_id(user_id: str) -> str:
    cleaned = "".join(ch for ch in user_id.strip() if ch.isalnum() or ch in {"_", "-", "."})
    return cleaned or "anonymous"


def build_user_agent(user_id: str, mode: Mode = Mode.DEFAULT, initial_budget: float = 50000.0) -> TravelAgent:
    settings = get_settings()
    safe_user_id = _safe_user_id(user_id)
    project_root = Path(__file__).resolve().parent.parent
    user_root = project_root / "workspace" / "users" / safe_user_id

    llm_client = LLMClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.parent_model,
    )
    agent = TravelAgent(llm_client=llm_client, initial_budget=initial_budget, mode=mode)
    agent.mcp_manager = MCPManager(config_path=settings.mcp_config_path)
    agent.mcp_manager.start_all()

    # 覆写为用户隔离存储。
    agent.task_manager = TaskManager(workspace_dir=str(user_root / "tasks"))
    agent.long_term_memory = LongTermMemoryManager(file_path=str(user_root / "memory" / "user_profile.json"))
    agent.artifact_manager = ArtifactManager(base_dir=str(user_root / "results"))
    agent.artifact_manager.child_logs_dir = user_root / "child_logs"
    agent.artifact_manager.child_logs_dir.mkdir(parents=True, exist_ok=True)
    agent.artifact_manager.workspace_dir = user_root
    agent.artifact_manager.legacy_artifacts_dir = user_root / "artifacts"

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

