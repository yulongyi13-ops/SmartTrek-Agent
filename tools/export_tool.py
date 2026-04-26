"""行程导出工具：将结构化行程导出为 ICS 日历文件。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from icalendar import Calendar, Event
from pydantic import BaseModel, Field, ValidationError

from core.security import PermissionManager
from .base_tool import BaseTool


class ItineraryEvent(BaseModel):
    """单条行程事件模型。"""

    summary: str = Field(..., min_length=1, description="事件标题")
    start_time: str = Field(..., min_length=1, description="开始时间，格式 YYYY-MM-DD HH:MM")
    end_time: str = Field(..., min_length=1, description="结束时间，格式 YYYY-MM-DD HH:MM")
    location: str = Field(default="", description="地点")
    description: str = Field(default="", description="详情描述")


class ExportIcsTool(BaseTool):
    """把行程事件列表导出为标准 ICS 文件。"""

    name = "export_ics"
    description = "将结构化行程导出为 .ics 日历文件并返回保存路径。"
    safety_level = "dangerous"
    requires_human_approval = True

    def __init__(self, artifact_dir: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.artifact_dir = Path(artifact_dir) if artifact_dir else (project_root / "workspace" / "artifacts")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "将行程事件列表导出为 ICS 文件。"
                    "时间必须使用绝对格式 YYYY-MM-DD HH:MM。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "文件名（不含或含 .ics 均可），例如 tibet_trip。",
                        },
                        "events": {
                            "type": "array",
                            "description": "结构化行程事件列表。",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string"},
                                    "start_time": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                                    "end_time": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                                    "location": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "required": ["summary", "start_time", "end_time"],
                            },
                        },
                    },
                    "required": ["events", "filename"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        filename = str(kwargs.get("filename", "")).strip()
        events_raw = kwargs.get("events", [])
        if not filename:
            return "导出失败：缺少 filename 参数。"
        if not isinstance(events_raw, list) or not events_raw:
            return "导出失败：events 必须是非空列表。"

        try:
            events = [ItineraryEvent.model_validate(item) for item in events_raw]
        except ValidationError as exc:
            return f"导出失败：事件结构不合法。错误信息: {exc}"

        cal = Calendar()
        cal.add("prodid", "-//Travel Agent Itinerary//CN")
        cal.add("version", "2.0")

        for idx, item in enumerate(events, start=1):
            try:
                start_dt = datetime.strptime(item.start_time, "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(item.end_time, "%Y-%m-%d %H:%M")
            except ValueError:
                return (
                    f"导出失败：第 {idx} 条事件时间格式错误。"
                    "请使用 YYYY-MM-DD HH:MM，例如 2026-05-01 09:00。"
                )

            if end_dt <= start_dt:
                return f"导出失败：第 {idx} 条事件结束时间必须晚于开始时间。"

            event = Event()
            event.add("summary", item.summary)
            event.add("dtstart", start_dt)
            event.add("dtend", end_dt)
            if item.location:
                event.add("location", item.location)
            if item.description:
                event.add("description", item.description)
            cal.add_component(event)

        safe_name = filename if filename.lower().endswith(".ics") else f"{filename}.ics"
        file_path = PermissionManager.enforce_artifact_path(self.artifact_dir, safe_name)
        file_path.write_bytes(cal.to_ical())

        rel_path = file_path.relative_to(file_path.parents[2]).as_posix()
        return (
            f"日历文件已成功生成并保存至 {rel_path}。"
            "请在最终回复中告知用户可以下载该文件。"
        )
