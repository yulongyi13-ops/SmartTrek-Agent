"""SmartTrek AI：Streamlit 本地对话界面（对接现有 TravelAgent 核心）。"""

from __future__ import annotations

from typing import Any, Dict, List

import folium
import streamlit as st
from streamlit_folium import st_folium

# --- 对接 Agent：与 main.build_agent 一致（get_settings + LLMClient + create_with_default_tools）---
from config.settings import get_settings
from core.agent import TravelAgent
from core.llm_client import LLMClient
from core.security import Mode

# --- 对接地图：与 api.server.chat_stream 中 extract_map_route 用法一致 ---
from api.map_extractor import extract_map_route

# --- 可选：若需按 user_id 隔离 workspace，可改为 from api.agent_factory import build_user_agent ---


def render_map(route_data: List[Dict[str, Any]]) -> None:
    """使用 folium 绘制途径点与连线；无数据时不渲染。"""
    if not route_data:
        return
    lats = [float(p["lat"]) for p in route_data]
    lngs = [float(p["lng"]) for p in route_data]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)
    m = folium.Map(location=[center_lat, center_lng], zoom_start=11, control_scale=True)
    for p in route_data:
        folium.Marker(
            location=[float(p["lat"]), float(p["lng"])],
            popup=str(p.get("name", "")),
            tooltip=str(p.get("name", "")),
        ).add_to(m)
    if len(route_data) >= 2:
        folium.PolyLine(
            locations=[[float(p["lat"]), float(p["lng"])] for p in route_data],
            color="blue",
            weight=3,
            opacity=0.7,
        ).add_to(m)
    st_folium(m, width=700, height=500)


def build_travel_agent(mode: Mode, initial_budget: float) -> TravelAgent:
    """组装 TravelAgent（逻辑对齐 main.build_agent，无交互式 input）。"""
    settings = get_settings()
    llm_client = LLMClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.parent_model,
    )
    return TravelAgent.create_with_default_tools(
        llm_client=llm_client,
        settings=settings,
        initial_budget=initial_budget,
        mode=mode,
    )


def _mode_option_label(mode: Mode) -> str:
    return {
        Mode.PLAN: "PLAN — 只读",
        Mode.AUTO: "AUTO — 探索",
        Mode.DEFAULT: "DEFAULT — 人机协同（推荐）",
    }[mode]


def _reply_with_budget_block(agent: TravelAgent, reply_body: str) -> str:
    """在助手正文后附加账本 Markdown，便于对话流内直接看到花费。"""
    budget_md = agent.get_budget_overview()
    return f"{reply_body.rstrip()}\n\n---\n**账本概览**\n{budget_md}"


st.set_page_config(page_title="SmartTrek AI", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("会话与 Agent")
    mode = st.selectbox(
        "运行模式",
        options=[Mode.PLAN, Mode.AUTO, Mode.DEFAULT],
        format_func=_mode_option_label,
        index=2,
    )
    initial_budget = st.number_input(
        "初始总资产（元）",
        min_value=0.0,
        value=50000.0,
        step=1000.0,
        help="仅在创建或重新初始化 Agent 时生效。",
    )
    if st.button("重新初始化 Agent（关闭 MCP、清空对话）", type="primary"):
        if "agent" in st.session_state:
            st.session_state.agent.close()
            del st.session_state.agent
        st.session_state.messages = []
        st.rerun()

if "agent" not in st.session_state:
    st.session_state.agent = build_travel_agent(mode=mode, initial_budget=initial_budget)

with st.sidebar:
    st.divider()
    st.subheader("账本概览（实时）")
    st.markdown(st.session_state.agent.get_budget_overview())

st.title("SmartTrek AI")
st.caption("在底部输入旅行需求；Agent 任务看板与记忆在会话内持续保留，直至你点击侧边栏重新初始化。")

if prompt := st.chat_input("输入你的旅行需求..."):
    st.session_state.messages.append({"role": "user", "content": prompt})

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("route"):
            render_map(message["route"])

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_text = st.session_state.messages[-1]["content"]
    with st.chat_message("assistant"):
        text_stream_chunks: List[str] = []
        reply = ""
        route = None
        with st.status("首席规划师正在工作中...", expanded=True) as status:
            try:
                for ev in st.session_state.agent.iter_run_events(user_text):
                    et = ev.get("type")
                    if et == "node":
                        status.write(ev.get("message", ""))
                    elif et == "log":
                        status.write(f"_(log)_ {ev.get('message', '')}")
                    elif et == "text_delta":
                        text_stream_chunks.append(ev.get("text", "") or "")
                    elif et == "error":
                        status.write(f"错误: {ev.get('message', '')}")
                    elif et == "final":
                        reply = str(ev.get("text", ""))
                        status.update(label="规划完成！", state="complete", expanded=False)
            except Exception as exc:  # noqa: BLE001
                reply = f"Agent 运行出错: {exc}"
                status.update(label="运行出错", state="complete", expanded=True)

        if text_stream_chunks:
            st.write_stream(iter(text_stream_chunks))
            st.markdown("---\n**账本概览**\n" + st.session_state.agent.get_budget_overview())
        else:
            display_reply_once = _reply_with_budget_block(st.session_state.agent, reply)
            st.markdown(display_reply_once)

        route = extract_map_route(reply, llm_client=st.session_state.agent.llm_client)
        if route:
            render_map(route)
        with st.expander("任务看板（PlanningState）"):
            st.markdown(st.session_state.agent.get_plan_overview())

        display_reply = _reply_with_budget_block(st.session_state.agent, reply)
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": display_reply,
            "route": route if route else None,
        }
    )
