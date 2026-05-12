"""权限检查 Hook：在工具执行前拦截。"""

from __future__ import annotations

import logging

from core.events import RunContext
from core.hooks import BaseHook

logger = logging.getLogger(__name__)


def _running_inside_streamlit() -> bool:
    """Streamlit 重跑脚本时无 stdin，不可用 input() 阻塞审批。"""
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (  # type: ignore[import-not-found]
            get_script_run_ctx,
        )
    except ImportError:
        return False
    try:
        return get_script_run_ctx() is not None
    except Exception:  # noqa: BLE001
        return False


class PermissionCheckHook(BaseHook):
    """ON_TOOL_START 时执行权限判断与 HITL 审批。"""

    def on_tool_start(self, context: RunContext) -> None:
        permission_manager = context.metadata.get("permission_manager")
        tool = context.current_tool
        kwargs = context.kwargs or {}
        if permission_manager is None or tool is None:
            return

        decision = permission_manager.check(
            tool=tool,
            kwargs=kwargs,
            current_mode=permission_manager.mode,
        )
        if not decision.allowed:
            raise PermissionError(f"执行被权限系统拒绝：{decision.reason}。请调整方案。")

        if decision.needs_approval:
            tool_name = getattr(tool, "name", "unknown_tool")
            if _running_inside_streamlit():
                logger.info(
                    "Streamlit 环境自动放行需审批工具（无终端 input）：%s",
                    tool_name,
                )
                return
            approval = input(
                f"[安全审核] Agent 请求执行 {tool_name}({kwargs})。是否允许？[y/N]: "
            ).strip().lower()
            if approval not in {"y", "yes"}:
                raise PermissionError("执行被用户拒绝，请调整方案。")
