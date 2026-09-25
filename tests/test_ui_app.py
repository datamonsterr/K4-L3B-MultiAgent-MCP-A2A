"""Tests for Streamlit app entrypoint and helpers."""

from __future__ import annotations

from student_agent.ui.app import init_session_state


def test_init_session_state() -> None:
    mock_session: dict = {}
    init_session_state(mock_session)
    assert "messages" in mock_session
    assert "active_case_id" in mock_session
    assert len(mock_session["messages"]) >= 1
    assert mock_session["messages"][0]["role"] == "assistant"
