from pathlib import Path

import pytest

from student_agent.contracts import Contracts
from student_agent.pipeline.models import (
    A2AMessage,
    AdjudicationDraft,
    CaseEvidenceContext,
    OrderFindings,
    PaymentFindings,
    ShipmentFindings,
)
from student_agent.pipeline.policy_agent import DEFAULT_POLICY_RULES
from student_agent.pipeline.verifier_agent import VerifierAgent
from student_agent.trace import TraceWriter


def test_a2a_message_creation_and_hop():
    msg = A2AMessage(
        case_id="L3B_CASE_001",
        sender="coordinator",
        recipient="order_agent",
        intent="task_assign",
        payload={"task": "inspect_order"},
    )
    assert msg.hop_count == 0
    assert msg.sender == "coordinator"
    assert msg.recipient == "order_agent"

    next_msg = msg.next_hop(
        recipient="policy_agent",
        intent="handoff",
        payload={"order_findings": "ok"},
    )
    assert next_msg.hop_count == 1
    assert next_msg.sender == "order_agent"
    assert next_msg.recipient == "policy_agent"


def test_a2a_cycle_prevention():
    msg = A2AMessage(
        case_id="L3B_CASE_001",
        sender="agent_a",
        recipient="agent_b",
        intent="task_assign",
        payload={},
        hop_count=9,
    )
    next_msg = msg.next_hop("agent_c", "handoff", {})
    assert next_msg.hop_count == 10

    with pytest.raises(RuntimeError, match="A2A cycle detected"):
        next_msg.next_hop("agent_a", "handoff", {})


def test_case_evidence_context_caching():
    ctx = CaseEvidenceContext("L3B_CASE_001")
    assert ctx.get_cached("get_order", {"order_id": "123"}) is None

    fake_ev = {"evidence_ref": "ev_1234567890123456789012", "data": {"status": "ok"}}
    ctx.set_cached("get_order", {"order_id": "123"}, fake_ev)

    cached = ctx.get_cached("get_order", {"order_id": "123"})
    assert cached == fake_ev
    assert "ev_1234567890123456789012" in ctx.collected_evidence_refs


def test_order_findings_defaults():
    of = OrderFindings(order_id="test_order")
    assert of.order_id == "test_order"
    assert of.total_items_price_brl == 0.0
    assert of.item_ids == []


def test_shipment_findings_verdict():
    sf = ShipmentFindings(order_id="test_order", verdict="on_time")
    assert sf.verdict == "on_time"
    assert sf.is_seller_delay is False


def test_payment_findings_reconciliation():
    pf = PaymentFindings(order_id="test_order", verdict="reconciled")
    assert pf.captured_total_brl == 0.0
    assert pf.refundable_total_brl == 0.0


def test_selective_specialist_routing_delivery_policy():
    from student_agent.pipeline.coordinator import determine_required_investigations

    case = {
        "case_id": "L3B_CASE_001",
        "customer_request": {
            "claims": [
                {"claim_id": "c1", "topic": "late_delivery_logistics"},
                {"claim_id": "c2", "topic": "requested_full_refund"},
            ]
        },
        "investigation_scope": {
            "include_customer_history": True,
            "include_product_context": False,
        },
    }
    plan = determine_required_investigations(case)
    assert plan["needs_shipment"] is True
    assert plan["needs_order"] is True
    assert plan["needs_payment_timeline"] is False
    assert plan["needs_refund_timeline"] is False
    assert plan["needs_product_context"] is False


def test_selective_specialist_routing_payment_dispute():
    from student_agent.pipeline.coordinator import determine_required_investigations

    case = {
        "case_id": "L3B_CASE_002",
        "customer_request": {
            "claims": [
                {"claim_id": "c1", "topic": "payment_mismatch"},
                {"claim_id": "c2", "topic": "requested_full_refund"},
            ]
        },
        "investigation_scope": {
            "include_customer_history": True,
            "include_product_context": True,
        },
    }
    plan = determine_required_investigations(case)
    assert plan["needs_shipment"] is False
    assert plan["needs_order"] is True
    assert plan["needs_payment_rows"] is True
    assert plan["needs_payment_timeline"] is True
    assert plan["needs_refund_timeline"] is False
    assert plan["needs_product_context"] is False


def test_verifier_cross_field_consistency():
    contracts = Contracts(Path("contracts/schemas"))
    trace_path = Path("traces/test_trace.jsonl")
    trace = TraceWriter(trace_path, contracts)
    verifier = VerifierAgent(trace, contracts)

    case = {
        "case_id": "L3B_CASE_001",
        "customer_request": {
            "claims": [
                {"claim_id": "c1", "topic": "late_delivery_seller"},
                {"claim_id": "c2", "topic": "requested_full_refund"},
            ]
        },
    }
    context = CaseEvidenceContext("L3B_CASE_001")
    context.collected_evidence_refs = ["ev_1234567890123456789012", "ev_2234567890123456789012"]

    adj = AdjudicationDraft(
        primary_issue="late_delivery_seller",
        case_status="action_required",
        confidence=0.95,
        recommended_action="refund_freight",
        recommended_refund_brl=25.0,
        cause_code="LATE_DELIVERY_SELLER",
        responsible_parties=[{"party_type": "seller", "party_id": "seller_01"}],
        claim_verdicts={"c1": "supported", "c2": "partially_supported"},
        rationale="Late seller handoff",
    )
    of = OrderFindings(order_id="order_01", item_ids=["item_01"], seller_ids=["seller_01"])
    sf = ShipmentFindings(
        order_id="order_01", verdict="seller_delay", late_seller_ids=["seller_01"]
    )
    pf = PaymentFindings(order_id="order_01", verdict="reconciled", captured_total_brl=100.0)

    output = verifier.verify_and_build(
        case=case,
        resolved_order_id="order_01",
        rejected_candidates=["candidate-01"],
        customer_unique_id="cust_01",
        related_order_ids=["order_01"],
        order_findings=of,
        shipment_findings=sf,
        payment_findings=pf,
        adjudication=adj,
        context=context,
    )

    # Invariant: seller fault must not assign logistics provider
    parties = [p["party_type"] for p in output["root_cause_analysis"]["responsible_parties"]]
    assert "seller" in parties
    assert "logistics_provider" not in parties

    # Invariant: confidence strictly bounded
    conf = output["assessment"]["confidence"]
    assert 0.70 <= conf <= 0.98

    # Invariant: refund lines sum to recommended_refund_brl
    refund_sum = sum(item["amount_brl"] for item in output["financial_resolution"]["refund_lines"])
    assert refund_sum == output["financial_resolution"]["recommended_refund_brl"]


@pytest.mark.parametrize(
    "issue,party_type,expected_status,expect_refund",
    [
        ("canceled_order_paid", "platform", "action_required", True),
        ("unavailable_order_paid", "seller", "action_required", True),
        ("late_delivery_seller", "seller", "action_required", True),
        ("late_delivery_logistics", "logistics_provider", "action_required", True),
        ("valid_split_payment", "customer", "no_action", False),
        ("payment_mismatch", "payment_provider", "action_required", True),
        ("duplicate_charge", "payment_provider", "action_required", True),
        ("refund_pending", "payment_provider", "needs_investigation", False),
        ("refund_failed", "payment_provider", "action_required", True),
        ("unsupported_claim", "customer", "no_action", False),
    ],
)
def test_all_ten_dispute_categories_schema_and_invariants(
    issue, party_type, expected_status, expect_refund
):
    contracts = Contracts(Path("contracts/schemas"))
    trace_path = Path("traces/test_trace.jsonl")
    trace = TraceWriter(trace_path, contracts)
    verifier = VerifierAgent(trace, contracts)

    case = {
        "case_id": "L3B_CASE_099",
        "customer_request": {
            "claims": [
                {"claim_id": "c1", "topic": issue},
                {"claim_id": "c2", "topic": "requested_full_refund"},
            ]
        },
    }
    context = CaseEvidenceContext("L3B_CASE_099")
    context.collected_evidence_refs = [
        "ev_1234567890123456789012",
        "ev_2234567890123456789012",
        "ev_3234567890123456789012",
    ]

    rule = DEFAULT_POLICY_RULES[issue]
    rec_refund = 50.0 if expect_refund else 0.0
    action = rule["recommended_action"]

    adj = AdjudicationDraft(
        primary_issue=issue,
        case_status=expected_status,
        confidence=0.96 if expect_refund else 0.88,
        recommended_action=action,
        recommended_refund_brl=rec_refund,
        cause_code="CAUSE_" + issue.upper(),
        responsible_parties=[{"party_type": party_type, "party_id": "test_party"}],
        claim_verdicts={
            "c1": "supported" if expect_refund else "unsupported",
            "c2": "partially_supported" if expect_refund else "unsupported",
        },
        rationale=f"Resolved as {issue}",
    )
    of = OrderFindings(
        order_id="order_99",
        total_freight_brl=16.0,
        item_ids=["item_99"],
        seller_ids=["seller_99"],
    )
    sf = ShipmentFindings(
        order_id="order_99",
        verdict="seller_delay" if issue == "late_delivery_seller" else "on_time",
        late_seller_ids=["seller_99"],
    )
    pf = PaymentFindings(order_id="order_99", verdict="reconciled", captured_total_brl=100.0)

    output = verifier.verify_and_build(
        case=case,
        resolved_order_id="order_99",
        rejected_candidates=["candidate-99"],
        customer_unique_id="cust_99",
        related_order_ids=["order_99"],
        order_findings=of,
        shipment_findings=sf,
        payment_findings=pf,
        adjudication=adj,
        context=context,
    )

    # Validate output schema
    contracts.validate_output(output, "test_case")

    # Invariants
    assert output["assessment"]["primary_issue"] == issue
    assert output["assessment"]["case_status"] == expected_status
    actual_parties = [p["party_type"] for p in output["root_cause_analysis"]["responsible_parties"]]
    assert party_type in actual_parties

    if expect_refund:
        assert output["financial_resolution"]["recommended_refund_brl"] > 0
        assert len(output["financial_resolution"]["refund_lines"]) == 1
    else:
        assert output["financial_resolution"]["recommended_refund_brl"] == 0.0
        assert len(output["financial_resolution"]["refund_lines"]) == 0

    assert 0.70 <= output["assessment"]["confidence"] <= 0.98


def test_mcp_gateway_no_retry_on_deterministic_tool_error():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from student_agent.mcp_gateway import EvidenceGateway

    async def run():
        session = MagicMock()
        error_result = MagicMock()
        error_result.is_error = True
        text_block = MagicMock()
        text_block.text = "Entity not found"
        error_result.content = [text_block]
        session.call_tool = AsyncMock(return_value=error_result)

        contracts = Contracts(Path("contracts/schemas"))
        gw = EvidenceGateway(session, contracts)

        with pytest.raises(RuntimeError, match="Entity not found"):
            await gw.call("get_order", case_id="CASE_01", order_id="nonexistent")

        # Invariant: session.call_tool was called exactly ONCE (zero retries)
        assert session.call_tool.call_count == 1

    asyncio.run(run())


def test_policy_agent_contradictory_telemetry_reconciliation():
    import asyncio
    from unittest.mock import MagicMock

    from student_agent.pipeline.policy_agent import PolicyAgent

    async def run():
        gw = MagicMock()
        trace = MagicMock()
        agent = PolicyAgent(gw, trace)
        agent.client = None  # test deterministic path

        case = {
            "case_id": "L3B_CASE_TEST",
            "customer_request": {
                "message": "My order arrived late!",
                "claims": [
                    {"claim_id": "c1", "topic": "late_delivery_seller"},
                    {"claim_id": "c2", "topic": "requested_full_refund"},
                ],
            },
        }
        context = CaseEvidenceContext("L3B_CASE_TEST")
        of = OrderFindings(order_id="ord_01", total_freight_brl=15.0)
        # Telemetry says on_time!
        sf = ShipmentFindings(order_id="ord_01", verdict="on_time", is_seller_delay=False)
        pf = PaymentFindings(order_id="ord_01", verdict="reconciled", captured_total_brl=100.0)

        draft, _ = await agent.adjudicate(case, of, sf, pf, context)

        # Invariant: claim of late delivery is refuted by on_time telemetry
        assert draft.primary_issue == "unsupported_claim"
        assert draft.case_status == "no_action"
        assert draft.recommended_refund_brl == 0.0
        assert draft.claim_verdicts["c1"] == "unsupported"

    asyncio.run(run())


def test_order_agent_skips_get_sellers_when_items_present():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from student_agent.pipeline.order_agent import OrderAgent

    async def run():
        gw = MagicMock()
        order_ev = {
            "evidence_ref": "ev_order_12345678901234567890",
            "data": {"order_status": "delivered"},
        }
        items_ev = {
            "evidence_ref": "ev_items_12345678901234567890",
            "data": [
                {
                    "order_item_id": "item_1",
                    "seller_id": "seller_abc",
                    "price": "50.0",
                    "freight_value": "10.0",
                }
            ],
        }

        async def fake_call(tool_name: str, **kwargs):
            if tool_name == "get_order":
                return order_ev
            if tool_name == "get_order_items":
                return items_ev
            if tool_name == "get_sellers":
                raise AssertionError("get_sellers should NOT be called when items have sellers!")
            raise ValueError(f"Unexpected tool {tool_name}")

        gw.call = AsyncMock(side_effect=fake_call)
        trace = MagicMock()
        order_agent = OrderAgent(gw, trace)
        context = CaseEvidenceContext("L3B_CASE_TEST")

        findings = await order_agent.investigate(
            case_id="L3B_CASE_TEST",
            order_id="ord_01",
            scope={},
            context=context,
            needs_items=True,
            needs_sellers=True,
        )

        assert findings.seller_ids == ["seller_abc"]
        # Verify get_sellers was never called
        called_tools = [call.args[0] for call in gw.call.call_args_list]
        assert "get_sellers" not in called_tools

    asyncio.run(run())
