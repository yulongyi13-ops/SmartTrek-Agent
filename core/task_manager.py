"""DAG 任务管理器：一任务一文件持久化，并维护双向依赖。"""

from __future__ import annotations

import json
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务状态枚举。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


class Task(BaseModel):
    """任务实体。"""

    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    blockedBy: List[str] = Field(default_factory=list)
    blocks: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    result_summary: str = ""


class TaskManager:
    """任务核心管理器。"""

    def __init__(self, workspace_dir: str = ".tasks") -> None:
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _task_file(self, task_id: str) -> Path:
        return self.workspace / f"{task_id}.json"

    def _task_to_dict(self, task: Task) -> dict:
        if hasattr(task, "model_dump"):
            return task.model_dump(mode="json")  # pydantic v2
        return task.dict()  # pydantic v1

    def _save_task_unlocked(self, task: Task) -> None:
        path = self._task_file(task.id)
        path.write_text(
            json.dumps(self._task_to_dict(task), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_task(self, task: Task) -> None:
        with self._lock:
            self._save_task_unlocked(task)

    def _load_task_unlocked(self, task_id: str) -> Optional[Task]:
        path = self._task_file(task_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return None
            data = json.loads(raw)
            return Task(**data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def _load_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._load_task_unlocked(task_id)

    def _iter_all_tasks(self) -> List[Task]:
        tasks: List[Task] = []
        for file in self.workspace.glob("*.json"):
            try:
                task_id = file.stem
                task = self._load_task(task_id)
                if task is not None:
                    tasks.append(task)
            except OSError:
                continue
        return tasks

    def create_task(
        self,
        subject: str,
        description: str,
        blockedBy: Optional[List[str]] = None,
        owner: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Task:
        deps = list(dict.fromkeys(blockedBy or []))
        new_task = Task(
            id=task_id or str(uuid.uuid4())[:8],
            subject=subject,
            description=description,
            blockedBy=deps,
            owner=owner,
        )
        self._save_task(new_task)

        # 维护双向依赖：前置任务必须记录它会解锁当前任务。
        for upstream_id in deps:
            upstream = self._load_task(upstream_id)
            if upstream is None:
                continue
            if new_task.id not in upstream.blocks:
                upstream.blocks.append(new_task.id)
                self._save_task(upstream)
        return new_task

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        result_summary: str = "",
        owner: Optional[str] = None,
    ) -> Optional[Task]:
        with self._lock:
            task = self._load_task_unlocked(task_id)
            if task is None:
                return None

            task.status = new_status
            if owner is not None:
                task.owner = owner
            if result_summary:
                task.result_summary = result_summary
            self._save_task_unlocked(task)

            # 自动解锁：完成后将自己从所有后继任务 blockedBy 中移除。
            if new_status == TaskStatus.COMPLETED:
                for downstream_id in task.blocks:
                    downstream = self._load_task_unlocked(downstream_id)
                    if downstream is None:
                        continue
                    if task.id in downstream.blockedBy:
                        downstream.blockedBy = [
                            dep_id for dep_id in downstream.blockedBy if dep_id != task.id
                        ]
                        self._save_task_unlocked(downstream)
            return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._load_task(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[Task]:
        tasks = self._iter_all_tasks()
        if status is None:
            return tasks
        return [task for task in tasks if task.status == status]

    def get_ready_tasks(self) -> List[Task]:
        ready: List[Task] = []
        for task in self._iter_all_tasks():
            if task.status == TaskStatus.DELETED:
                continue
            if task.status == TaskStatus.IN_PROGRESS:
                ready.append(task)
                continue
            if task.status == TaskStatus.PENDING and not task.blockedBy:
                ready.append(task)
        return ready
