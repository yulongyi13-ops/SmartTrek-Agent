"""外部账本与预算管理器。"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ExpenseItem(BaseModel):
    """单笔支出条目。"""

    item_name: str = Field(..., min_length=1, description="花销项目名称")
    amount: float = Field(..., ge=0, description="金额（元）")
    category: str = Field(default="未分类", description="支出类别")


class BudgetManager(BaseModel):
    """预算账本管理。"""

    total_budget: float = Field(..., ge=0, description="总预算")
    expenses: List[ExpenseItem] = Field(default_factory=list)

    def add_expense(self, item: ExpenseItem) -> None:
        self.expenses.append(item)

    def get_total_spent(self) -> float:
        return round(sum(item.amount for item in self.expenses), 2)

    def get_remaining_budget(self) -> float:
        return round(self.total_budget - self.get_total_spent(), 2)

    def render_ledger(self) -> str:
        spent = self.get_total_spent()
        remaining = self.get_remaining_budget()
        lines = [
            "=== 当前财务状况 ===",
            f"总预算: {self.total_budget:.2f}元 | 已花费: {spent:.2f}元 | 剩余: {remaining:.2f}元",
            "已记账明细:",
        ]
        if not self.expenses:
            lines.append("1. 暂无记账记录")
            return "\n".join(lines)

        for idx, item in enumerate(self.expenses, start=1):
            lines.append(f"{idx}. {item.item_name} ({item.amount:.2f}元, 类别: {item.category})")
        return "\n".join(lines)
