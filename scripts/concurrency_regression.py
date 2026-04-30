"""最小并发回归脚本：
1) 验证 delegate_task 并发执行 + 扇入摘要；
2) 验证 TaskManager 并发更新不崩溃且依赖解锁正常。
"""

from __future__ import annotations

import json
import sys
import shutil
import tempfile
import threading
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试环境兜底：若未安装 icalendar，提供最小 stub 以加载 core.agent。
if "icalendar" not in sys.modules:
    fake_icalendar = types.ModuleType("icalendar")

    class _Calendar:  # noqa: D401
        """stub Calendar"""

    class _Event:  # noqa: D401
        """stub Event"""

    fake_icalendar.Calendar = _Calendar
    fake_icalendar.Event = _Event
    sys.modules["icalendar"] = fake_icalendar

from core.agent import BaseAgent
from core.task_manager import TaskManager, TaskStatus
from tools.base_tool import BaseTool


class DelegateSleepTool(BaseTool):
    """模拟子任务执行耗时与结果。"""

    name = "delegate_task"
    description = "mock delegate task"

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sub_task_description": {"type": "string"},
                    },
                    "required": ["sub_task_description"],
                },
            },
        }

    def run(self, **kwargs: Any) -> str:
        task = str(kwargs.get("sub_task_description", "")).strip() or "unknown"
        time.sleep(0.2)
        # 产生略长的文本，便于观察 fan-in 是否被压缩。
        payload = " | ".join([f"{task}-result-{i}" for i in range(30)])
        return f"{task}: {payload}"


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction


class FakeAssistantMessage:
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[List[FakeToolCall]] = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": "assistant"}
        if self.content is not None or not exclude_none:
            payload["content"] = self.content
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in self.tool_calls
            ]
        return payload


@dataclass
class FakeChoice:
    message: FakeAssistantMessage
    finish_reason: str


@dataclass
class FakeResponse:
    choices: List[FakeChoice]


class FakeLLMClient:
    """两轮对话：首轮给出并发 tool_calls，次轮验证 fan-in 后返回最终答案。"""

    def __init__(self) -> None:
        self.call_count = 0

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Any:
        self.call_count += 1
        if self.call_count == 1:
            calls = [
                FakeToolCall(
                    id=f"call_{idx}",
                    function=FakeFunction(
                        name="delegate_task",
                        arguments=json.dumps({"sub_task_description": f"task_{idx}"}),
                    ),
                )
                for idx in range(3)
            ]
            return FakeResponse(choices=[FakeChoice(message=FakeAssistantMessage(tool_calls=calls), finish_reason="tool_calls")])

        # 第二轮检查 fan-in 聚合是否生效
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 3, f"期望至少3条tool消息，实际={len(tool_msgs)}"
        summaries = [m.get("content", "") for m in tool_msgs]
        assert any("并发子任务汇总" in item for item in summaries), "未发现并发汇总摘要"
        assert not all("result-29" in item for item in summaries), "疑似未做扇入压缩"
        return FakeResponse(
            choices=[FakeChoice(message=FakeAssistantMessage(content="concurrency-pass"), finish_reason="stop")]
        )


def run_agent_fanin_regression() -> None:
    agent = BaseAgent(
        name="Regression Agent",
        llm_client=FakeLLMClient(),  # type: ignore[arg-type]
        tools=[DelegateSleepTool()],
        system_prompt="you are test agent",
        max_iterations=3,
    )
    output = agent.run("run concurrent delegate test")
    assert output == "concurrency-pass", f"期望输出 concurrency-pass，实际={output}"
    print("[PASS] agent concurrency fan-in regression")


def run_task_manager_thread_safety_regression() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="task_lock_regression_"))
    try:
        manager = TaskManager(workspace_dir=str(tmp_dir))
        root = manager.create_task("root", "root task")
        down_1 = manager.create_task("down_1", "blocked by root", blockedBy=[root.id])
        down_2 = manager.create_task("down_2", "blocked by root", blockedBy=[root.id])

        errors: List[str] = []

        def _worker(idx: int) -> None:
            try:
                manager.update_task_status(
                    task_id=root.id,
                    new_status=TaskStatus.COMPLETED,
                    result_summary=f"done by worker {idx}",
                    owner=f"worker-{idx}",
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发更新出现异常: {errors}"
        loaded_1 = manager.get_task(down_1.id)
        loaded_2 = manager.get_task(down_2.id)
        assert loaded_1 is not None and loaded_2 is not None
        assert root.id not in loaded_1.blockedBy, "down_1 未被自动解锁"
        assert root.id not in loaded_2.blockedBy, "down_2 未被自动解锁"
        print("[PASS] task manager lock regression")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_agent_fanin_regression()
    run_task_manager_thread_safety_regression()
    print("All concurrency regressions passed.")
