"""项目入口：命令行交互式旅游 Agent。"""

from __future__ import annotations

from config.settings import get_settings
from core.agent import TravelAgent
from core.llm_client import LLMClient


COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_RESET = "\033[0m"


def build_agent() -> TravelAgent:
    """组装 Agent 依赖。"""
    settings = get_settings()

    llm_client = LLMClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )

    return TravelAgent.create_with_default_tools(llm_client=llm_client, settings=settings)


def main() -> None:
    print("=== Travel Agent 已启动（输入 exit 退出）===")
    agent = build_agent()

    while True:
        user_input = input("\n你: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("已退出。")
            break

        print("Agent: 正在思考并可能调用工具...")
        try:
            reply = agent.run(user_input)
            print(f"{COLOR_GREEN}Agent: {reply}{COLOR_RESET}")
            print(f"{COLOR_CYAN}\n--- PlanningState 概览 ---")
            print(agent.get_plan_overview())
            print(f"-------------------------{COLOR_RESET}")
        except Exception as exc:  # noqa: BLE001
            # 在实践项目里保留异常输出，方便调试 Agent 链路。
            print(f"Agent 运行出错: {exc}")


if __name__ == "__main__":
    main()
