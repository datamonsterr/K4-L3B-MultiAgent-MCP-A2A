"""Coordinator and Router Agent for Day09 L3B Multi-Agent Pipeline."""

from __future__ import annotations

import asyncio
from typing import Any

from ..contracts import Contracts
from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter
from .models import CaseEvidenceContext
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

    delivery_topics = {"late_delivery_seller", "late_delivery_logistics"}
    payment_topics = {
        "valid_split_payment",
        "duplicate_charge",
        "payment_mismatch",
        "canceled_order_paid",
        "unavailable_order_paid",
        "refund_pending",
        "refund_failed",
    }

    is_delivery_dispute = bool(topics & delivery_topics) or (
        "unsupported_claim" in topics
        and any(
            w in message for w in ["giao", "ship", "vận chuyển", "nhận hàng", "delivery", "late"]
        )
    )
    is_payment_dispute = bool(topics & payment_topics) or (
        "unsupported_claim" in topics
        and any(w in message for w in ["thanh toán", "tiền", "charge", "refund", "trả"])
    )

    needs_shipment = is_delivery_dispute or (not is_payment_dispute)
    needs_order = True
    needs_items = (
        is_delivery_dispute or ("payment_mismatch" in topics) or ("canceled_order_paid" in topics)
    )
    needs_sellers = "late_delivery_seller" in topics
    needs_payment_rows = is_payment_dispute
    needs_payment_timeline = bool(topics & {"duplicate_charge", "payment_mismatch"})
    needs_refund_timeline = bool(topics & {"refund_pending", "refund_failed"})
    needs_product_context = bool(
        scope.get("include_product_context", False)
        and any(
            w in message
            for w in ["sản phẩm", "mô tả", "hàng hóa", "catalog", "product", "category"]
        )
    )
    needs_customer_history = bool(
        scope.get("include_customer_history", False) and case.get("customer_unique_id_hint")
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
        self.order_agent = OrderAgent(gateway, trace)
        self.shipment_agent = ShipmentAgent(gateway, trace)
        self.payment_agent = PaymentAgent(gateway, trace)
        self.policy_agent = PolicyAgent(gateway, trace)
        self.verifier_agent = VerifierAgent(trace, contracts)

    async def solve(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]
        context = CaseEvidenceContext(case_id)
        plan = determine_required_investigations(case)

        # 1. Entity Resolution & Customer Context
        claimed_id = case.get("customer_request", {}).get("claimed_order_id")
        candidate_ids = case.get("candidate_order_ids", [])
        hint = case.get("customer_unique_id_hint")

        # Query customer history only when scoped and needed
        related_order_ids: list[str] = []
        customer_unique_id: str | None = hint
        if plan["needs_customer_history"] and hint:
            try:
                cust_ev = await self.gateway.call(
                    "get_customer_history", case_id=case_id, customer_unique_id=hint
                )
                context.record_evidence("get_customer_history", cust_ev)
                ref = cust_ev["evidence_ref"]
                self.trace.emit(
                    case_id=case_id,
                    event_type="tool_result_consumed",
                    actor="coordinator",
                    tool_name="get_customer_history",
                    evidence_refs=[ref],
                    attributes={"orders_found": len(cust_ev["data"].get("orders", []))},
                )
                cust_data = cust_ev["data"]
                customer_unique_id = cust_data.get("customer_unique_id") or hint
                for o in cust_data.get("orders", []):
                    oid = o.get("order_id")
                    if oid and oid not in related_order_ids:
                        related_order_ids.append(oid)
            except Exception:
                pass

        # Disambiguate candidates
        # Real order IDs are 32-hex characters; mock candidates start with 'candidate-'
        resolved_order_id = claimed_id
        rejected_candidates: list[str] = []

        for cand in candidate_ids:
            if cand.startswith("candidate-"):
                rejected_candidates.append(cand)
            elif len(cand) == 32:
                resolved_order_id = cand
            else:
                rejected_candidates.append(cand)

        if not resolved_order_id:
            resolved_order_id = candidate_ids[0] if candidate_ids else "unknown_order"

        if resolved_order_id not in related_order_ids and resolved_order_id != "unknown_order":
            related_order_ids.insert(0, resolved_order_id)

        # 2. Task Assignment to Specialists (bounded and selective)
        scope = case.get("investigation_scope", {})

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

        # Handoff to specialists
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="coordinator",
            target="specialists",
            attributes={"order_id": resolved_order_id},
        )

        # 3. Parallel Specialist Execution (with efficiency controls)
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

        # 4. Handoff to Policy Agent
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

        # 5. Verifier Agent: Invariants, Math, and Schema Validation
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
