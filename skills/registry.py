"""技能注册表：扫描本地 Markdown 作为按需知识源。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from core.skill_models import SkillDocument, SkillManifest


class SkillRegistry:
    """统一管理技能目录与正文。"""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent
        self.data_dir = Path(data_dir) if data_dir else (base_dir / "data")
        self._documents: Dict[str, SkillDocument] = {}
        self._manifests: Dict[str, SkillManifest] = {}
        self._load_from_files()

    def _load_from_files(self) -> None:
        if not self.data_dir.exists():
            return

        for path in sorted(self.data_dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                continue

            lines = raw.splitlines()
            description = ""
            content_start_idx = 0

            # 约定首行可用注释定义描述：<!-- description: ... -->
            first = lines[0].strip() if lines else ""
            marker = "<!-- description:"
            if first.startswith(marker) and first.endswith("-->"):
                description = first[len(marker) : -3].strip()
                content_start_idx = 1
            else:
                # 若未显式定义描述，则取正文第一行（去掉 markdown 标题符）
                description = lines[0].lstrip("# ").strip()

            body = "\n".join(lines[content_start_idx:]).strip()
            if not body:
                continue

            name = path.stem
            doc = SkillDocument(name=name, content=body)
            manifest = SkillManifest(name=name, description=description or "无描述")
            self._documents[name] = doc
            self._manifests[name] = manifest

    def get_all_manifests(self) -> List[SkillManifest]:
        """返回全部轻量目录。"""
        return [self._manifests[key] for key in sorted(self._manifests.keys())]

    def get_skill_document(self, skill_name: str) -> SkillDocument:
        """按名称获取技能正文。"""
        name = skill_name.strip()
        if name not in self._documents:
            available = ", ".join(sorted(self._documents.keys())) or "无"
            raise KeyError(f"未找到技能 {name}。可用技能：{available}")
        return self._documents[name]
