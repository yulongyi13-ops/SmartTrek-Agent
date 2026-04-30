"""状态注入 Hook：在 LLM 调用前注入动态系统状态。"""

from __future__ import annotations

from core.events import RunContext
from core.hooks import BaseHook


class StateInjectionHook(BaseHook):
    """ON_LLM_START 时注入最新系统提示词。"""

    def on_llm_start(self, context: RunContext) -> None:
        prompt_builder = context.metadata.get("prompt_builder")
        if prompt_builder is None:
            return

        memory_manager = context.metadata.get("memory_manager")
        skill_registry = context.metadata.get("skill_registry")
        budget_manager = context.metadata.get("budget_manager")
        prompt_text = str(
            prompt_builder.build(
                context=context,
                memory_manager=memory_manager,
                skill_registry=skill_registry,
                budget_manager=budget_manager,
            )
        )
        if context.messages and context.messages[0].get("role") == "system":
            context.messages[0]["content"] = prompt_text
        else:
            context.messages.insert(0, {"role": "system", "content": prompt_text})
