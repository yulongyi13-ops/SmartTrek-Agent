"""预算记账工具：把支出记录到外部账本。"""

from __future__ import annotations

from typing import Any, Dict

from core.budget_manager import BudgetManager, ExpenseItem
from .base_tool import BaseTool


class RecordExpenseTool(BaseTool):
    """记录单笔支出并返回最新预算状态。"""

    name = "record_expense"
    description = "记录一笔确认支出并更新剩余预算。"
    safety_level = "write"

    def __init__(self, budget_manager: BudgetManager) -> None:
        self.budget_manager = budget_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "每当确定一项真实花销时必须调用。"
                    "amount 需要传纯数字，系统会自动转成 float。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_name": {"type": "string", "description": "花销项目名称。"},
                        "amount": {"type": "number", "description": "金额（纯数字）。"},
                        "category": {"type": "string", "description": "类别，如交通、住宿。"},
                    },
                    "required": ["item_name", "amount"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        item_name = str(kwargs.get("item_name", "")).strip()
        amount_raw = kwargs.get("amount", 0)
        category = str(kwargs.get("category", "未分类")).strip() or "未分类"

        if not item_name:
            return "记账失败：缺少 item_name。"

        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            return "记账失败：amount 必须是数字。"

        if amount < 0:
            return "记账失败：amount 不能为负数。"

        item = ExpenseItem(item_name=item_name, amount=amount, category=category)
        self.budget_manager.add_expense(item)
        remaining = self.budget_manager.get_remaining_budget()
        return f"记录成功！当前剩余可用预算为 {remaining:.2f} 元。"
