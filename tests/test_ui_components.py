"""Tests for UI rendering components."""

from __future__ import annotations

from student_agent.ui.components import (
    format_trace_events_for_display,
    render_agent_badge_html,
    render_tool_call_html,
)
from student_agent.ui.process_parser import AgentToolCall


def test_render_tool_call_html() -> None:
    tool_call = AgentToolCall(
        tool_name="get_shipment_summary",
        evidence_refs=["ev_ship_123"],
        attributes={"carrier_delay_days": 3, "status": "delivered"},
        occurred_at="2026-09-25T08:33:02.000Z",
    )
    html = render_tool_call_html(tool_call)
    assert "get_shipment_summary" in html
    assert "ev_ship_123" in html
    assert "carrier_delay_days" in html


def test_render_agent_badge_html() -> None:
    html = render_agent_badge_html("order_agent", "Order Specialist")
    assert "order_agent" in html
    assert "Order Specialist" in html
    assert "border-radius: 50px" in html


def test_format_trace_events_for_display() -> None:
    traces = [
        {
            "event_id": "evt_1",
            "event_type": "tool_result_consumed",
            "actor": "order_agent",
            "tool_name": "get_order",
            "occurred_at": "2026-09-25T08:33:01.000Z",
        }
    ]
    formatted = format_trace_events_for_display(traces)
    assert "evt_1" in formatted
    assert "order_agent" in formatted
    assert "tool_result_consumed" in formatted
