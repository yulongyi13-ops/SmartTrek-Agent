"""管理大文本生成物落盘，减少上下文污染。"""

from __future__ import annotations

from pathlib import Path


class ArtifactManager:
    """将长文本保存到本地文件，并返回短预览。"""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.artifact_dir = Path(base_dir) if base_dir else (project_root / "workspace" / "artifacts")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def save_artifact(self, filename: str, content: str) -> str:
        safe_name = filename.strip() or "artifact.md"
        target = self.artifact_dir / safe_name
        target.write_text(content, encoding="utf-8")

        preview_head = content[:80].replace("\n", " ")
        preview_tail = content[-60:].replace("\n", " ") if len(content) > 140 else ""
        rel_path = target.relative_to(target.parents[2]).as_posix()
        if preview_tail:
            preview = f"{preview_head} ... {preview_tail}"
        else:
            preview = preview_head
        return f"[详细报告已保存至 {rel_path}，内容预览：{preview}]"
