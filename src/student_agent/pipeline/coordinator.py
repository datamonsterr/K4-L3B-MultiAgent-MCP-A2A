"""Coordinator and Router Agent for Day09 L3B Multi-Agent Pipeline."""

from __future__ import annotations

import asyncio
from typing import Any

from ..contracts import Contracts
from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter
from .entity_agent import EntityAgent
from .models import ALLOWED_TOOLS_BY_TOPIC, CaseEvidenceContext
from .order_agent import OrderAgent
from .payment_agent import PaymentAgent
from .policy_agent import PolicyAgent
from .shipment_agent import ShipmentAgent
from .verifier_agent import VerifierAgent


def determine_required_investigations(case: dict[str, Any]) -> dict[str, bool]:
    """Analyze case claims and scope to avoid unnecessary or forbidden MCP tool calls."""
    claims = case.get("customer_request", {}).get("claims", [])
    topics = {c.get("topic") for c in claims if c.get("topic")}
    scope = case.get("investigation_scope", {})
    message = case.get("customer_request", {}).get("message", "").lower()
    claimed_id = case.get("customer_request", {}).get("claimed_order_id")

    delivery_topics = {"late_delivery_seller", "late_delivery_logistics"}
    payment_topics = {
        "valid_split_payment",
        "duplicate_charge",
        "payment_mismatch",
        "refund_pending",
        "refund_failed",
    }
    cancel_topics = {"canceled_order_paid", "unavailable_order_paid"}

    is_delivery_dispute = bool(topics & delivery_topics)
    is_payment_dispute = bool(topics & payment_topics)
    is_cancel_dispute = bool(topics & cancel_topics)
    is_unsupported_claim = "unsupported_claim" in topics

    needs_shipment = is_delivery_dispute or (
        is_unsupported_claim
        and any(
            w in message for w in ["giao", "ship", "vận chuyển", "nhận hàng", "delivery", "late"]
        )
    )
    needs_order = True
    needs_items = is_delivery_dispute or ("payment_mismatch" in topics)
    needs_payment_rows = (
        is_payment_dispute
        or is_cancel_dispute
        or (
            is_unsupported_claim
            and any(w in message for w in ["thanh toán", "tiền", "charge", "refund", "trả"])
        )
    )
    needs_payment_timeline = bool(topics & {"duplicate_charge", "payment_mismatch"})
    needs_refund_timeline = bool(topics & {"refund_pending", "refund_failed"})
    needs_sellers = bool(
        scope.get("include_seller_locations", False) and ("late_delivery_seller" in topics)
    )
    needs_product_context = bool(
        scope.get("include_product_context", False)
        and any(
            w in message
            for w in ["sản phẩm", "mô tả", "hàng hóa", "catalog", "product", "category"]
        )
    )
    needs_customer_history = bool(
        scope.get("include_customer_history", False)
        and (not claimed_id or len(claimed_id) != 32)
        and case.get("customer_unique_id_hint")
    )

    return {
        "needs_order": needs_order,
        "needs_items": needs_items,
        "needs_sellers": needs_sellers,
        "needs_shipment": needs_shipment,
        "needs_payment_rows": needs_payment_rows,
        "needs_payment_timeline": needs_payment_timeline,
        "needs_refund_timeline": needs_refund_timeline,
        "needs_product_context": needs_product_context,
        "needs_customer_history": needs_customer_history,
    }


class CoordinatorAgent:
    """Supervises entity resolution, specialist routing, and the lifecycle pipeline."""

    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter, contracts: Contracts) -> None:
        self.gateway = gateway
        self.trace = trace
        self.contracts = contracts
        self.entity_agent = EntityAgent(gateway, trace)
        self.order_agent = OrderAgent(gateway, trace)
        self.shipment_agent = ShipmentAgent(gateway, trace)
        self.payment_agent = PaymentAgent(gateway, trace)
        self.policy_agent = PolicyAgent(gateway, trace)
        self.verifier_agent = VerifierAgent(trace, contracts)

    async def solve(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]

        # 1. Inspect input structure and primary topic
        claims = case.get("customer_request", {}).get("claims", [])
        primary_topic = claims[0].get("topic") if claims else "unsupported_claim"

        # Gated case context: restrict allowed tools based on dispute topic
        allowed_tools = ALLOWED_TOOLS_BY_TOPIC.get(primary_topic)
        context = CaseEvidenceContext(case_id, allowed_tools=allowed_tools)

        # 2. Entity Agent: disambiguate customer, user data, and order candidates
        entity_findings = await self.entity_agent.resolve(case, context)
        resolved_order_id = entity_findings.resolved_order_id
        rejected_candidates = entity_findings.rejected_candidates
        customer_unique_id = entity_findings.customer_unique_id
        related_order_ids = entity_findings.related_order_ids

        # 3. Topic-driven Specialist Routing (especially first topic)
        plan = determine_required_investigations(case)

        # Emit task assignment for active specialist agents
        if plan["needs_order"]:
            self.trace.emit(
                case_id=case_id,
                event_type="task_assigned",
                actor="coordinator",
                target="order_agent",
                attributes={"task": "inspect_order_items_sellers_catalog"},
            )
        if plan["needs_shipment"]:
            self.trace.emit(
                case_id=case_id,
                event_type="task_assigned",
                actor="coordinator",
                target="shipment_agent",
                attributes={"task": "inspect_shipment_transit_timeline"},
            )
        if (
            plan["needs_payment_rows"]
            or plan["needs_payment_timeline"]
            or plan["needs_refund_timeline"]
        ):
            self.trace.emit(
                case_id=case_id,
                event_type="task_assigned",
                actor="coordinator",
                target="payment_agent",
                attributes={"task": "inspect_payments_reconciliation_refunds"},
            )

        # Handoff to active specialists
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="coordinator",
            target="specialists",
            attributes={"order_id": resolved_order_id, "primary_topic": primary_topic},
        )

        # 4. Parallel Specialist Execution (with strict topic-based budget)
        scope = case.get("investigation_scope", {})
        order_task = self.order_agent.investigate(
            case_id,
            resolved_order_id,
            scope,
            context,
            needs_items=plan["needs_items"],
            needs_sellers=plan["needs_sellers"],
            needs_product_context=plan["needs_product_context"],
        )
        shipment_task = self.shipment_agent.investigate(
            case_id,
            resolved_order_id,
            context,
            skip_shipment=not plan["needs_shipment"],
        )
        payment_task = self.payment_agent.investigate(
            case_id,
            resolved_order_id,
            context,
            needs_payment_rows=plan["needs_payment_rows"],
            needs_payment_timeline=plan["needs_payment_timeline"],
            needs_refund_timeline=plan["needs_refund_timeline"],
        )

        order_findings, shipment_findings, payment_findings = await asyncio.gather(
            order_task, shipment_task, payment_task
        )

        # Financial consistency protection when payment specialist is skipped
        if (
            payment_findings.captured_total_brl == 0.0
            and order_findings.total_order_value_brl > 0.0
        ):
            payment_findings.captured_total_brl = order_findings.total_order_value_brl
            payment_findings.refundable_total_brl = order_findings.total_order_value_brl

        # 5. Handoff to Policy Agent
        self.trace.emit(
            case_id=case_id,
            event_type="task_assigned",
            actor="coordinator",
            target="policy_agent",
            attributes={"task": "resolve_conflicts_and_adjudicate_claims"},
        )
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="specialists",
            target="policy_agent",
            attributes={"evidence_ready": True},
        )

        adjudication, _ = await self.policy_agent.adjudicate(
            case, order_findings, shipment_findings, payment_findings, context
        )

        # 6. Verifier Agent: Invariants, Math, and Schema Validation
        self.trace.emit(
            case_id=case_id,
            event_type="task_assigned",
            actor="coordinator",
            target="verifier_agent",
            attributes={"task": "verify_invariants_and_audit_provenance"},
        )

        output = self.verifier_agent.verify_and_build(
            case=case,
            resolved_order_id=resolved_order_id,
            rejected_candidates=rejected_candidates,
            customer_unique_id=customer_unique_id,
            related_order_ids=related_order_ids,
            order_findings=order_findings,
            shipment_findings=shipment_findings,
            payment_findings=payment_findings,
            adjudication=adjudication,
            context=context,
        )

        return output
