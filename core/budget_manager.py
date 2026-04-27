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

    total_assets: float = Field(..., ge=0, description="总资产")
    current_task_budget: float | None = Field(default=None, ge=0, description="本次任务专项预算")
    expenses: List[ExpenseItem] = Field(default_factory=list)

    def set_task_budget(self, amount: float) -> None:
        self.current_task_budget = round(float(amount), 2)

    def add_expense(self, item: ExpenseItem) -> None:
        self.expenses.append(item)

    def get_total_spent(self) -> float:
        return round(sum(item.amount for item in self.expenses), 2)

    def get_remaining_assets(self) -> float:
        return round(self.total_assets - self.get_total_spent(), 2)

    def get_task_spent(self) -> float:
        # 当前版本默认将本次会话内记账都视为当前任务开销。
        return self.get_total_spent()

    def get_remaining_task_budget(self) -> float | None:
        if self.current_task_budget is None:
            return None
        return round(self.current_task_budget - self.get_task_spent(), 2)

    def render_ledger(self) -> str:
        spent_total = self.get_total_spent()
        remaining_assets = self.get_remaining_assets()
        task_budget = self.current_task_budget
        task_spent = self.get_task_spent()
        task_remaining = self.get_remaining_task_budget()
        lines = [
            "=== 当前财务状况 ===",
            f"总资产: {self.total_assets:.2f}元 | 全局已花: {spent_total:.2f}元 | 资产剩余: {remaining_assets:.2f}元",
        ]
        if task_budget is None:
            lines.append("本次行程预算: 未设置（请先调用 SetTaskBudgetTool）")
        else:
            lines.append(
                f"本次行程预算: {task_budget:.2f}元 (已花 {task_spent:.2f}元, 剩余 {task_remaining:.2f}元)"
            )
        lines.append("已记账明细:")
        if not self.expenses:
            lines.append("1. 暂无记账记录")
            return "\n".join(lines)

        for idx, item in enumerate(self.expenses, start=1):
            lines.append(f"{idx}. {item.item_name} ({item.amount:.2f}元, 类别: {item.category})")
        return "\n".join(lines)
