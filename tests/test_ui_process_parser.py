"""Tests for multi-agent process parser for Streamlit UI."""

from __future__ import annotations

from student_agent.ui.process_parser import (
    MultiAgentProcess,
    parse_case_process,
)


def test_parse_case_process_from_trace_and_output() -> None:
    case = {
        "case_id": "L3B_CASE_001",
        "opened_at": "2018-01-01T09:00:00-03:00",
        "customer_request": {
            "message": "Delivery is late and order is damaged",
            "claimed_order_id": "order-123",
            "claims": [{"claim_id": "c1", "topic": "late_delivery"}],
        },
        "candidate_order_ids": ["order-123", "candidate-bad"],
    }

    traces = [
        {
            "case_id": "L3B_CASE_001",
            "event_type": "case_received",
            "actor": "coordinator",
            "occurred_at": "2026-09-25T08:33:00.000Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "coordinator",
            "tool_name": "get_customer_history",
            "evidence_refs": ["ev_cust_1"],
            "attributes": {"orders_found": 2},
            "occurred_at": "2026-09-25T08:33:01.000Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "task_assigned",
            "actor": "coordinator",
            "target": "order_agent",
            "occurred_at": "2026-09-25T08:33:01.100Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "task_assigned",
            "actor": "coordinator",
            "target": "shipment_agent",
            "occurred_at": "2026-09-25T08:33:01.101Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "task_assigned",
            "actor": "coordinator",
            "target": "payment_agent",
            "occurred_at": "2026-09-25T08:33:01.102Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "order_agent",
            "tool_name": "get_order",
            "evidence_refs": ["ev_ord_1"],
            "attributes": {"status": "delivered"},
            "occurred_at": "2026-09-25T08:33:02.000Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "shipment_agent",
            "tool_name": "get_shipment_summary",
            "evidence_refs": ["ev_ship_1"],
            "attributes": {"carrier_delay_days": 4},
            "occurred_at": "2026-09-25T08:33:02.050Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "tool_result_consumed",
            "actor": "payment_agent",
            "tool_name": "get_order_payments",
            "evidence_refs": ["ev_pay_1"],
            "attributes": {"payment_rows": 1},
            "occurred_at": "2026-09-25T08:33:02.080Z",
        },
        {
            "case_id": "L3B_CASE_001",
            "event_type": "verification_completed",
            "actor": "verifier_agent",
            "attributes": {"schema_valid": True, "invariants_passed": True},
            "occurred_at": "2026-09-25T08:33:04.000Z",
        },
    ]

    output = {
        "schema_version": "day09-l3b-output-v2",
        "case_id": "L3B_CASE_001",
        "assessment": {
            "primary_issue": "late_delivery_logistics",
            "case_status": "action_required",
            "confidence": 0.95,
        },
        "entity_resolution": {
            "status": "resolved",
            "resolved_order_ids": ["order-123"],
            "rejected_candidates": ["candidate-bad"],
            "confidence": 0.98,
        },
        "claim_assessments": [
            {"claim_id": "c1", "verdict": "supported", "evidence_refs": ["ev_ship_1"]}
        ],
        "dispute_resolution": {
            "decision": "refund_approved",
            "refund_amount": 50.0,
            "responsible_party": "carrier",
            "rationale": "Late by 4 days",
        },
    }

    process: MultiAgentProcess = parse_case_process(case, traces, output)

    assert process.case_id == "L3B_CASE_001"
    assert process.coordinator.resolved_order_id == "order-123"
    assert "candidate-bad" in process.coordinator.rejected_candidates
    assert len(process.coordinator.tool_calls) == 1
    assert process.coordinator.tool_calls[0].tool_name == "get_customer_history"

    # Parallel specialists
    assert len(process.order_agent.tool_calls) == 1
    assert process.order_agent.tool_calls[0].tool_name == "get_order"
    assert process.order_agent.tool_calls[0].evidence_refs == ["ev_ord_1"]

    assert len(process.shipment_agent.tool_calls) == 1
    assert process.shipment_agent.tool_calls[0].tool_name == "get_shipment_summary"
    assert process.shipment_agent.tool_calls[0].evidence_refs == ["ev_ship_1"]

    assert len(process.payment_agent.tool_calls) == 1
    assert process.payment_agent.tool_calls[0].tool_name == "get_order_payments"

    # Policy and verifier
    assert process.policy_agent.decision == "refund_approved"
    assert process.policy_agent.responsible_party == "carrier"
    assert process.verifier_agent.passed is True
    assert process.verifier_agent.schema_valid is True
