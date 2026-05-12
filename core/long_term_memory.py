"""长期记忆管理：跨会话用户画像持久化。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError, field_validator


class MemoryItem(BaseModel):
    """带元数据的单条长期记忆。"""

    value: str
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m"))
    condition: str = "全局通用"


class MemoryProfile(BaseModel):
    """用户长期画像。"""

    preferences: Dict[str, MemoryItem] = Field(default_factory=dict)
    corrections: List[str] = Field(default_factory=list)
    conventions: Dict[str, MemoryItem] = Field(default_factory=dict)
    external_pointers: Dict[str, MemoryItem] = Field(default_factory=dict)

    @staticmethod
    def _normalize_memory_map(raw: Any) -> Dict[str, Dict[str, str]]:
        if not isinstance(raw, dict):
            return {}
        normalized: Dict[str, Dict[str, str]] = {}
        default_ts = datetime.now().strftime("%Y-%m")
        for key, value in raw.items():
            if isinstance(value, str):
                normalized[str(key)] = {
                    "value": value,
                    "timestamp": default_ts,
                    "condition": "全局通用",
                }
                continue
            if isinstance(value, dict):
                normalized[str(key)] = {
                    "value": str(value.get("value", "")).strip(),
                    "timestamp": str(value.get("timestamp") or default_ts).strip(),
                    "condition": str(value.get("condition") or "全局通用").strip(),
                }
                continue
            normalized[str(key)] = {
                "value": str(value),
                "timestamp": default_ts,
                "condition": "全局通用",
            }
        return normalized

    @field_validator("preferences", "conventions", "external_pointers", mode="before")
    @classmethod
    def _migrate_legacy_memory_items(cls, value: Any) -> Dict[str, Dict[str, str]]:
        """向后兼容旧数据：`str` 自动升级为完整 MemoryItem 结构。"""
        return cls._normalize_memory_map(value)


class MemoryManager:
    """管理长期记忆文件的加载、更新与渲染。"""

    _transient_patterns = [
        r"当天",
        r"本次",
        r"这次",
        r"周末",
        r"明天",
        r"后天",
        r"今天",
        r"\d+天",
        r"行程",
        r"往返",
    ]

    def _is_transient_value(self, text: str) -> bool:
        raw = text.strip()
        if not raw:
            return True
        return any(re.search(p, raw) for p in self._transient_patterns)

    def __init__(self, file_path: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.file_path = (
            Path(file_path)
            if file_path
            else (project_root / "workspace" / "memory" / "user_profile.json")
        )
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = MemoryProfile()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self.file_path.exists():
            self.profile = MemoryProfile()
            return
        try:
            raw = self.file_path.read_text(encoding="utf-8").strip()
            if not raw:
                self.profile = MemoryProfile()
                return
            data = json.loads(raw)
            self.profile = MemoryProfile.model_validate(data)
        except (OSError, json.JSONDecodeError, ValidationError):
            # 容错：坏文件不让系统崩溃，回退为空画像。
            self.profile = MemoryProfile()

    def migrate_legacy_profile(self) -> str:
        """迁移旧版 user_profile.json 到 memory 目录（幂等）。"""
        workspace_dir = self.file_path.parent.parent
        legacy_path = workspace_dir / "user_profile.json"
        if not legacy_path.exists():
            return "no_legacy_profile"
        if self.file_path.exists():
            return "skip_existing_profile"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(self.file_path))
        return "moved_legacy_profile"

    def save_to_disk(self) -> None:
        payload = self.profile.model_dump()
        self.file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def update_memory(
        self,
        category: str,
        action: str,
        key: str,
        value: str,
        condition: str = "全局通用",
        conflict_resolution: str = "",
    ) -> str:
        cat = category.strip()
        act = action.strip().lower()
        k = key.strip()
        v = value.strip()
        cond = condition.strip() or "全局通用"
        conflict = conflict_resolution.strip().lower()

        if cat not in {"preferences", "corrections", "conventions", "external_pointers"}:
            return f"更新失败：不支持的 category={cat}。"
        if act not in {"add", "update", "delete"}:
            return f"更新失败：不支持的 action={act}。"

        if cat == "corrections":
            items = self.profile.corrections
            if act == "delete":
                target = v or k
                if target in items:
                    items.remove(target)
                    return f"已删除纠正记录：{target}"
                return f"未找到纠正记录：{target}"

            target = v or k
            if not target:
                return "更新失败：corrections 在 add/update 时需提供 key 或 value。"
            if target not in items:
                items.append(target)
            return f"已记录纠正信息：{target}"

        bucket = getattr(self.profile, cat)
        if not isinstance(bucket, dict):
            return f"更新失败：category={cat} 不是键值映射。"

        # 记忆去噪：约定与偏好仅接受长期稳定信息。
        if act in {"add", "update"} and cat in {"preferences", "conventions"}:
            if self._is_transient_value(v):
                return "更新失败：检测到短期/行程型信息，长期记忆已拒绝写入。"

        if act == "delete":
            if not k:
                return "更新失败：delete 操作需要 key。"
            if k in bucket:
                del bucket[k]
                return f"已删除 {cat}.{k}"
            return f"未找到 {cat}.{k}"

        if not k or not v:
            return "更新失败：add/update 操作需要 key 和 value。"

        if cat == "conventions":
            allowed_keys = {"常驻出发地", "常住城市", "出发地", "坐标系", "常用交通"}
            if k not in allowed_keys:
                return f"更新失败：conventions 仅允许键 {sorted(allowed_keys)}。"

        now_ts = datetime.now().strftime("%Y-%m")
        if conflict and conflict not in {"overwrite_global", "add_as_exception"}:
            return "更新失败：conflict_resolution 仅支持 overwrite_global 或 add_as_exception。"

        if conflict == "overwrite_global":
            bucket[k] = MemoryItem(value=v, timestamp=now_ts, condition="全局通用")
            return f"已覆盖全局记忆 {cat}.{k} = {v}"

        if conflict == "add_as_exception":
            exception_key = f"{k}_特例_{cond}"
            bucket[exception_key] = MemoryItem(value=v, timestamp=now_ts, condition=cond)
            return f"已新增条件记忆 {cat}.{exception_key} = {v}"

        bucket[k] = MemoryItem(value=v, timestamp=now_ts, condition=cond)
        return f"已更新 {cat}.{k} = {v}"

    def render_memory_prompt(self) -> str:
        p = self.profile

        def render_map(title: str, data: Dict[str, MemoryItem]) -> List[str]:
            lines = [f"### {title}"]
            if not data:
                lines.append("- 暂无")
            else:
                for k, v in data.items():
                    lines.append(
                        f"- {k}: {v.value} [生效场景: {v.condition}] (记录于 {v.timestamp})"
                    )
            return lines

        lines: List[str] = ["## 用户长期档案"]
        lines.extend(render_map("偏好 (preferences)", p.preferences))
        lines.append("### 纠正记录 (corrections)")
        if not p.corrections:
            lines.append("- 暂无")
        else:
            for item in p.corrections:
                lines.append(f"- {item}")
        lines.extend(render_map("背景约定 (conventions)", p.conventions))
        lines.extend(render_map("外部指针 (external_pointers)", p.external_pointers))
        return "\n".join(lines)
