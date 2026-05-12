"""SSE 事件协议工具。"""

from __future__ import annotations

import json
from typing import Any, Dict


def event_to_sse(data: Dict[str, Any]) -> str:
    """将字典编码为标准 SSE data 块。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

