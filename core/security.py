"""权限与 HITL 安全管理。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict


class Mode(str, Enum):
    """运行模式。"""

    PLAN = "plan"
    AUTO = "auto"
    DEFAULT = "default"


class SecurityException(Exception):
    """安全策略触发时抛出的异常。"""


@dataclass
class PermissionDecision:
    """权限检查结果。"""

    allowed: bool
    needs_approval: bool = False
    reason: str = ""


class PermissionManager:
    """工具执行权限控制器。"""

    _default_whitelist = {
        "set_task_budget",
        "load_skill",
        "update_memory",
        "delegate_task",
        "task_create",
        "task_update",
        "task_get",
        "task_list",
        "record_expense",
        "web_search",
        "get_weather_forecast",
        "search_poi",
        "plan_route",
    }

    def __init__(self, mode: Mode = Mode.DEFAULT) -> None:
        self.mode = mode

    def check(self, tool: Any, kwargs: Dict[str, Any], current_mode: Mode | None = None) -> PermissionDecision:
        mode = current_mode or self.mode
        safety_level = getattr(tool, "safety_level", "safe")
        needs_human = bool(getattr(tool, "requires_human_approval", False))

        if mode == Mode.PLAN:
            if safety_level in {"write", "dangerous"}:
                return PermissionDecision(
                    allowed=False,
                    reason=f"PLAN 模式禁止写操作工具：{getattr(tool, 'name', 'unknown')}",
                )
            return PermissionDecision(allowed=True)

        if mode == Mode.AUTO:
            if needs_human:
                return PermissionDecision(
                    allowed=True,
                    needs_approval=True,
                    reason="该工具被标记为需要人工审批。",
                )
            # 高危规则：大额记账需要审批。
            if getattr(tool, "name", "") == "record_expense":
                try:
                    amount = float(kwargs.get("amount", 0))
                except (TypeError, ValueError):
                    amount = 0
                if amount >= 3000:
                    return PermissionDecision(
                        allowed=True,
                        needs_approval=True,
                        reason=f"检测到大额记账（{amount:.2f} 元），需要人工确认。",
                    )
            return PermissionDecision(allowed=True)

        # DEFAULT 模式：白名单外全部人工审批。
        tool_name = getattr(tool, "name", "")
        if tool_name not in self._default_whitelist or needs_human:
            return PermissionDecision(
                allowed=True,
                needs_approval=True,
                reason="DEFAULT 模式下该工具不在自动白名单内。",
            )
        return PermissionDecision(allowed=True)

    @staticmethod
    def enforce_artifact_path(base_dir: Path, filename: str) -> Path:
        """防路径穿越：最终路径必须落在 artifacts 目录下。"""
        safe_name = (filename or "").strip()
        if not safe_name:
            raise SecurityException("文件名为空。")
        candidate = (base_dir / safe_name).resolve()
        base = base_dir.resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise SecurityException(
                f"检测到非法路径写入请求（可能路径穿越）：{filename}"
            ) from exc
        return candidate
