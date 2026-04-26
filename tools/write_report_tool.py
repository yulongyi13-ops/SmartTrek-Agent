"""文件写入工具：将最终长结果保存为文本/Markdown。"""

from __future__ import annotations

from typing import Any, Dict

from core.artifact_manager import ArtifactManager
from .base_tool import BaseTool


class WriteReportTool(BaseTool):
    """把结果写入本地文件，减少对话输出长度。"""

    name = "write_report_file"
    description = "将长篇结果保存到本地文件，并返回文件路径与简要预览。"

    def __init__(self, artifact_manager: ArtifactManager) -> None:
        self.artifact_manager = artifact_manager

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "把完整报告写入文本文件，回复中仅保留摘要和文件路径。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "目标文件名，如 tibet_plan.md 或 report.txt。",
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入文件的完整正文。",
                        },
                    },
                    "required": ["filename", "content"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        filename = str(kwargs.get("filename", "")).strip()
        content = str(kwargs.get("content", "")).strip()
        if not filename:
            return "写入失败：缺少 filename 参数。"
        if not content:
            return "写入失败：content 为空。"

        try:
            return self.artifact_manager.save_artifact(filename=filename, content=content)
        except Exception as exc:  # noqa: BLE001
            return f"写入失败：{exc}"
