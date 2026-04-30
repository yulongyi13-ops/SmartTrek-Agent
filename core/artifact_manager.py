"""管理大文本生成物落盘，减少上下文污染。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from core.security import PermissionManager


class ArtifactManager:
    """将长文本保存到本地文件，并返回短预览。"""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.workspace_dir = project_root / "workspace"
        self.results_dir = Path(base_dir) if base_dir else (self.workspace_dir / "results")
        self.child_logs_dir = self.workspace_dir / "child_logs"
        self.legacy_artifacts_dir = self.workspace_dir / "artifacts"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.child_logs_dir.mkdir(parents=True, exist_ok=True)

    def _render_preview(self, target: Path, content: str) -> str:
        rel_path = target.relative_to(target.parents[2]).as_posix()
        preview_head = content[:80].replace("\n", " ")
        preview_tail = content[-60:].replace("\n", " ") if len(content) > 140 else ""
        preview = f"{preview_head} ... {preview_tail}" if preview_tail else preview_head
        return f"[详细报告已保存至 {rel_path}，内容预览：{preview}]"

    def _save_to_dir(self, target_dir: Path, filename: str, content: str) -> str:
        safe_name = filename.strip() or "artifact.md"
        target = PermissionManager.enforce_artifact_path(target_dir, safe_name)
        target.write_text(content, encoding="utf-8")
        return self._render_preview(target=target, content=content)

    def save_artifact(self, filename: str, content: str) -> str:
        """默认保存到最终结果目录。"""
        return self._save_to_dir(target_dir=self.results_dir, filename=filename, content=content)

    def save_child_log(self, filename: str, content: str) -> str:
        """保存子智能体日志到专属目录。"""
        return self._save_to_dir(target_dir=self.child_logs_dir, filename=filename, content=content)

    def migrate_legacy_outputs(self) -> List[str]:
        """迁移旧目录输出（幂等，不覆盖已存在文件）。"""
        logs: List[str] = []

        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.child_logs_dir.mkdir(parents=True, exist_ok=True)
        if not self.legacy_artifacts_dir.exists():
            return logs

        for src in self.legacy_artifacts_dir.glob("*.md"):
            if not src.is_file():
                continue
            if src.name.startswith("child_report_"):
                dst = self.child_logs_dir / src.name
            else:
                dst = self.results_dir / src.name
            if dst.exists():
                logs.append(f"skip:{src.name}")
                continue
            shutil.move(str(src), str(dst))
            logs.append(f"moved:{src.name}->{dst.parent.name}")
        return logs
