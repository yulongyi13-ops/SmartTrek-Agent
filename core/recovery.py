"""错误恢复与自愈引擎。"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.events import RunContext

try:
    from openai import APIConnectionError, APITimeoutError, RateLimitError
except Exception:  # noqa: BLE001
    APIConnectionError = ()  # type: ignore[assignment]
    APITimeoutError = ()  # type: ignore[assignment]
    RateLimitError = ()  # type: ignore[assignment]


class RecoveryDecision(str, Enum):
    """恢复动作决策。"""

    RETRY_WITH_BACKOFF = "retry_with_backoff"
    FORCE_COMPRESS = "force_compress"
    CONTINUE_GENERATION = "continue_generation"
    REWRITE_TOOL = "rewrite_tool"
    ABORT = "abort"


class RecoveryState(BaseModel):
    """恢复状态机。"""

    retry_count: int = 0
    max_retries: int = 3
    last_error_type: str = ""
    accumulated_content: str = ""


def _has_truncated_tool_call(response: Any) -> bool:
    try:
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return False
        for tool_call in tool_calls:
            raw = str(getattr(tool_call.function, "arguments", "") or "").strip()
            if not raw:
                return True
            if not raw.endswith("}"):
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def analyze_and_recover(exception_or_response: Any, state: RecoveryState, context: RunContext) -> RecoveryDecision:
    """分析异常或响应，并给出恢复决策。"""
    if state.retry_count >= state.max_retries:
        state.last_error_type = "max_retries_exceeded"
        return RecoveryDecision.ABORT

    # 路径一、路径二：异常型恢复
    if isinstance(exception_or_response, Exception):
        exc = exception_or_response
        text = str(exc).lower()

        if isinstance(exc, (APIConnectionError, RateLimitError, APITimeoutError)):
            state.last_error_type = exc.__class__.__name__
            return RecoveryDecision.RETRY_WITH_BACKOFF

        if "context_length_exceeded" in text or "maximum context length" in text or "too many tokens" in text:
            state.last_error_type = "context_length_exceeded"
            return RecoveryDecision.FORCE_COMPRESS

        state.last_error_type = exc.__class__.__name__
        return RecoveryDecision.RETRY_WITH_BACKOFF

    # 路径三：输出截断恢复
    response = exception_or_response
    try:
        finish_reason = str(response.choices[0].finish_reason or "").lower()
    except Exception:  # noqa: BLE001
        state.last_error_type = "invalid_response"
        return RecoveryDecision.RETRY_WITH_BACKOFF

    if finish_reason in {"length", "max_tokens"}:
        if _has_truncated_tool_call(response):
            state.last_error_type = "tool_call_truncated"
            context.messages.append(
                {
                    "role": "system",
                    "content": "你的工具调用因长度限制被截断，请放弃续写，直接重新输出完整的工具调用 JSON。",
                }
            )
            return RecoveryDecision.REWRITE_TOOL

        partial_text = str(response.choices[0].message.content or "")
        if partial_text:
            state.accumulated_content += partial_text
        state.last_error_type = "text_truncated"
        context.messages.append(
            {
                "role": "user",
                "content": "你的输出被截断了，请精确地从最后一个字开始继续输出，不要重复前面的内容。",
            }
        )
        return RecoveryDecision.CONTINUE_GENERATION

    state.last_error_type = "unrecoverable_response"
    return RecoveryDecision.ABORT


def apply_recovery_side_effect(decision: RecoveryDecision, state: RecoveryState, context: RunContext, memory_manager: Any, llm_client: Any) -> None:
    """执行恢复决策对应的副作用动作。"""
    if decision == RecoveryDecision.RETRY_WITH_BACKOFF:
        delay = max(1, 2 ** state.retry_count)
        time.sleep(delay)
        state.retry_count += 1
        return

    if decision == RecoveryDecision.FORCE_COMPRESS:
        context.messages = memory_manager.compress_messages(context.messages, llm_client)
        state.retry_count += 1
        return

    if decision in {RecoveryDecision.CONTINUE_GENERATION, RecoveryDecision.REWRITE_TOOL}:
        state.retry_count += 1
        return
