"""Tests for DisputeChatEngine in Streamlit UI."""

from __future__ import annotations

import pytest

from student_agent.ui.chat_engine import DisputeChatEngine


@pytest.fixture
def mock_engine(tmp_path) -> DisputeChatEngine:
    case_1 = {
        "case_id": "L3B_CASE_001",
        "opened_at": "2018-01-01T09:00:00-03:00",
        "customer_request": {
            "message": "Order arrived broken and late, need full refund.",
            "claimed_order_id": "order-123",
            "claims": [{"claim_id": "c1", "topic": "late_delivery"}],
        },
        "candidate_order_ids": ["order-123", "candidate-bad"],
    }
    output_1 = {
        "schema_version": "day09-l3b-output-v2",
        "case_id": "L3B_CASE_001",
        "assessment": {
            "primary_issue": "late_delivery_logistics",
            "case_status": "action_required",
            "confidence": 0.96,
        },
        "entity_resolution": {
            "status": "resolved",
            "resolved_order_ids": ["order-123"],
            "rejected_candidates": ["candidate-bad"],
            "confidence": 0.98,
        },
        "dispute_resolution": {
            "decision": "refund_approved",
            "refund_amount": 120.50,
            "responsible_party": "carrier",
            "rationale": "Transit delayed by 5 days beyond SLA.",
        },
        "claim_assessments": [
            {"claim_id": "c1", "verdict": "supported", "evidence_refs": ["ev_ship_99"]}
        ],
    }
    traces_1 = [
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "shipment_agent",
            "tool_name": "get_shipment_summary",
            "evidence_refs": ["ev_ship_99"],
            "attributes": {"carrier_delay_days": 5},
            "occurred_at": "2026-09-25T08:33:02.000Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "order_agent",
            "tool_name": "get_order",
            "evidence_refs": ["ev_ord_99"],
            "attributes": {"status": "delivered"},
            "occurred_at": "2026-09-25T08:33:02.010Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "payment_agent",
            "tool_name": "get_order_payments",
            "evidence_refs": ["ev_pay_99"],
            "attributes": {"payment_rows": 1, "total_value": 120.50},
            "occurred_at": "2026-09-25T08:33:02.020Z",
        },
    ]

    return DisputeChatEngine(
        cases={"L3B_CASE_001": case_1},
        outputs={"L3B_CASE_001": output_1},
        traces={"L3B_CASE_001": traces_1},
    )


def test_chat_engine_list_cases(mock_engine: DisputeChatEngine) -> None:
    cases = mock_engine.list_cases()
    assert "L3B_CASE_001" in cases


def test_chat_engine_investigate_case_query(mock_engine: DisputeChatEngine) -> None:
    result = mock_engine.process_user_message("Please investigate L3B_CASE_001")
    assert result["case_id"] == "L3B_CASE_001"
    assert "refund_approved" in result["reply"]
    assert "carrier" in result["reply"]
    assert result["process"] is not None
    assert result["process"].coordinator.resolved_order_id == "order-123"
    assert len(result["process"].shipment_agent.tool_calls) == 1
    assert len(result["raw_traces"]) == 3


def test_chat_engine_follow_up_questions(mock_engine: DisputeChatEngine) -> None:
    # First activate case
    mock_engine.process_user_message("L3B_CASE_001")

    # Ask about shipment
    res_shipment = mock_engine.process_user_message(
        "What did shipment agent find?", active_case_id="L3B_CASE_001"
    )
    assert "shipment" in res_shipment["reply"].lower() or "delay" in res_shipment["reply"].lower()

    # Ask about payment
    res_payment = mock_engine.process_user_message(
        "What was the refund or payment amount?", active_case_id="L3B_CASE_001"
    )
    assert "120.5" in res_payment["reply"] or "refund" in res_payment["reply"].lower()


def test_chat_engine_unknown_query(mock_engine: DisputeChatEngine) -> None:
    result = mock_engine.process_user_message("hello, how are you?")
    assert "L3B_CASE_001" in result["reply"]
    assert result["process"] is None
