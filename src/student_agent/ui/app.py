"""Streamlit Multi-Agent Dispute Chatbot Application."""

from __future__ import annotations

import streamlit as st

from .chat_engine import DisputeChatEngine
from .components import format_trace_events_for_display, render_multiagent_flow
from .styles import get_custom_css


def init_session_state(session: dict) -> None:
    if "messages" not in session:
        session["messages"] = [
            {
                "role": "assistant",
                "content": "Select or enter case ID to investigate.",
                "process": None,
                "raw_traces": [],
            }
        ]
    if "active_case_id" not in session:
        session["active_case_id"] = None


def run_app() -> None:
    st.set_page_config(
        page_title="Dispute Chatbot",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Inject light theme, 50px border-radius, compact styling, hide sidebar/header/logo
    st.markdown(get_custom_css(), unsafe_allow_html=True)

    init_session_state(st.session_state)
    engine = DisputeChatEngine.from_workspace()
    all_cases = engine.list_cases()

    # Minimal header without slogans or badges
    st.markdown(
        '<div style="border-bottom: 1px solid #E2E8F0; padding-bottom: 4px; margin-bottom: 8px;">'
        '<h3 style="margin: 0; font-size: 15px; font-weight: 700; color: #0F172A;">'
        "Dispute Chatbot</h3></div>",
        unsafe_allow_html=True,
    )

    # Preset case pills (50px border-radius)
    fallback_cases = ["L3B_CASE_001", "L3B_CASE_002", "L3B_CASE_003"]
    sample_cases = all_cases[:6] if all_cases else fallback_cases
    cols = st.columns(len(sample_cases))
    for idx, cid in enumerate(sample_cases):
        with cols[idx]:
            if st.button(cid, key=f"btn_case_{cid}", use_container_width=True):
                result = engine.process_user_message(cid)
                st.session_state.active_case_id = result["case_id"]
                st.session_state.messages.append({"role": "user", "content": cid})
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": result["reply"],
                        "process": result["process"],
                        "raw_traces": result["raw_traces"],
                    }
                )
                st.rerun()

    st.markdown("<div style='margin-bottom: 8px;'></div>", unsafe_allow_html=True)

    # Render Chat History
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Multiagent process visualization
            process = msg.get("process")
            if process:
                render_multiagent_flow(st, process)

            # Togglable raw trace event view
            raw_traces = msg.get("raw_traces")
            if raw_traces:
                show_trace = st.toggle("Raw Trace", key=f"toggle_trace_{idx}", value=False)
                if show_trace:
                    formatted_trace = format_trace_events_for_display(raw_traces)
                    st.markdown(
                        f'<div class="trace-container"><pre style="margin: 0; white-space: '
                        f'pre-wrap; font-size: 10.5px; color: #38BDF8;">'
                        f"{formatted_trace}</pre></div>",
                        unsafe_allow_html=True,
                    )

    # Fixed bottom chat input
    user_prompt = st.chat_input("Case ID or question...")
    if user_prompt:
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        result = engine.process_user_message(
            user_prompt, active_case_id=st.session_state.active_case_id
        )
        if result["case_id"]:
            st.session_state.active_case_id = result["case_id"]
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["reply"],
                "process": result["process"],
                "raw_traces": result["raw_traces"],
            }
        )
        st.rerun()


if __name__ == "__main__":
    run_app()
