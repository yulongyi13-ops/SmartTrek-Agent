"""工具动态亲和度算分。"""

from __future__ import annotations

from typing import Dict, List

from tools.base_tool import BaseTool


def calculate_dynamic_weights(tools: List[BaseTool], task_text: str) -> Dict[str, int]:
    """根据任务文本和工具能力标签计算动态得分。"""
    normalized_text = (task_text or "").strip().lower()
    weights: Dict[str, int] = {}

    for tool in tools:
        base = int(getattr(tool, "base_weight", 30))
        labels = [str(item).strip().lower() for item in getattr(tool, "capabilities", []) if str(item).strip()]
        matched = any(label in normalized_text for label in labels) if normalized_text and labels else False
        weights[tool.name] = base + 50 if matched else base

    return weights
