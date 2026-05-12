"""项目入口：命令行交互式旅游 Agent。"""

from __future__ import annotations

from config.settings import get_settings
from core.agent import TravelAgent
from core.llm_client import LLMClient
from core.security import Mode


COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_RESET = "\033[0m"


def choose_mode() -> Mode:
    """启动时选择权限模式。"""
    print("\n请选择运行模式：")
    print("1) PLAN    - 只读模式：仅允许查询类工具，拒绝所有写操作。")
    print("2) AUTO    - 探索模式：多数操作自动放行；高危操作（如大额记账）需审批。")
    print("3) DEFAULT - 人机协同：白名单外工具一律人工审批（推荐）。")

    mapping = {
        "1": Mode.PLAN,
        "plan": Mode.PLAN,
        "2": Mode.AUTO,
        "auto": Mode.AUTO,
        "3": Mode.DEFAULT,
        "default": Mode.DEFAULT,
        "": Mode.DEFAULT,
    }
    while True:
        choice = input("输入模式编号或名称 [默认 3]: ").strip().lower()
        if choice in mapping:
            mode = mapping[choice]
            print(f"已选择模式: {mode.value.upper()}")
            return mode
        print("输入无效，请输入 1/2/3 或 plan/auto/default。")


def build_agent(mode: Mode) -> TravelAgent:
    """组装 Agent 依赖。"""
    settings = get_settings()

    llm_client = LLMClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.parent_model,
    )

    budget = choose_initial_budget()
    return TravelAgent.create_with_default_tools(
        llm_client=llm_client,
        settings=settings,
        initial_budget=budget,
        mode=mode,
    )


def choose_initial_budget() -> float:
    """启动时输入初始总资产。"""
    while True:
        raw = input("请输入系统初始总资产（元）[默认 50000]: ").strip()
        if not raw:
            print("已使用默认总资产: 50000.00 元")
            return 50000.0
        try:
            value = float(raw)
            if value < 0:
                print("总资产不能为负数，请重输。")
                continue
            print(f"已设置总资产: {value:.2f} 元")
            return value
        except ValueError:
            print("输入无效，请输入数字，例如 6000 或 50000。")


def main() -> None:
    print("=== Travel Agent 已启动（输入 exit 退出）===")
    mode = choose_mode()
    agent = build_agent(mode=mode)

    try:
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
                print("\n--- Budget Ledger 概览 ---")
                print(agent.get_budget_overview())
                print(f"-------------------------{COLOR_RESET}")
            except Exception as exc:  # noqa: BLE001
                # 在实践项目里保留异常输出，方便调试 Agent 链路。
                print(f"Agent 运行出错: {exc}")
    finally:
        agent.close()


if __name__ == "__main__":
    main()
