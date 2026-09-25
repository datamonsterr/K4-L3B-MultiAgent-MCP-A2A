"""Shipment and Logistics Specialist Agent."""

from __future__ import annotations

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter
from .models import CaseEvidenceContext, ShipmentFindings


class ShipmentAgent:
    """Specialist responsible for transit timeline, carrier milestones, and delivery delays."""

    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def investigate(
        self,
        case_id: str,
        order_id: str,
        context: CaseEvidenceContext,
        skip_shipment: bool = False,
    ) -> ShipmentFindings:
        if skip_shipment:
            return ShipmentFindings(order_id=order_id, verdict="on_time", timeline_complete=True)

        evidence_refs: list[str] = []
        findings = ShipmentFindings(order_id=order_id, verdict="on_time")

        try:
            cached_shipment = context.get_cached("get_shipment_summary", {"order_id": order_id})
            if cached_shipment is None:
                ship_ev = await self.gateway.call(
                    "get_shipment_summary", case_id=case_id, order_id=order_id
                )
                context.set_cached("get_shipment_summary", {"order_id": order_id}, ship_ev)
            else:
                ship_ev = cached_shipment

            ref = ship_ev["evidence_ref"]
            evidence_refs.append(ref)
            self.trace.emit(
                case_id=case_id,
                event_type="tool_result_consumed",
                actor="shipment_agent",
                tool_name="get_shipment_summary",
                evidence_refs=[ref],
                attributes={"status": ship_ev["data"].get("order_status")},
            )
            data = ship_ev["data"]
            carrier_at = data.get("delivered_carrier_at")
            customer_at = data.get("delivered_customer_at")
            estimated_at = data.get("estimated_delivery_at")
            limits = data.get("shipping_limits") or []
            events = data.get("events") or []

            findings.delivered_carrier_at = carrier_at
            findings.delivered_customer_at = customer_at
            findings.estimated_delivery_at = estimated_at
            findings.shipping_limits = limits
            findings.timeline_complete = bool(carrier_at and customer_at and estimated_at)
            ship_id = data.get("shipment_id") or f"shipment-{order_id[:12]}"
            findings.shipment_ids = [ship_id]

            # 1. Inspect authoritative confirmed milestone events
            confirmed_late_actor = None
            for ev in events:
                if ev.get("event_type") == "delivered_late" and ev.get("status") == "confirmed":
                    confirmed_late_actor = ev.get("actor")
                    break

            # 2. Extract late sellers
            late_sellers: list[str] = []
            for limit in limits:
                seller_id = limit.get("seller_id")
                limit_at = limit.get("shipping_limit_at")
                is_late_handoff = bool(carrier_at and limit_at and carrier_at > limit_at)
                if (
                    seller_id
                    and seller_id not in late_sellers
                    and (confirmed_late_actor == "seller" or is_late_handoff)
                ):
                    late_sellers.append(seller_id)

            if not late_sellers and confirmed_late_actor == "seller":
                for limit in limits:
                    sid = limit.get("seller_id")
                    if sid and sid not in late_sellers:
                        late_sellers.append(sid)
                        break

            findings.late_seller_ids = late_sellers

            # 3. Determine shipment verdict
            if confirmed_late_actor == "seller":
                findings.is_seller_delay = True
                findings.verdict = "seller_delay"
            elif confirmed_late_actor == "logistics_provider":
                findings.is_logistics_delay = True
                findings.verdict = "logistics_delay"
            elif customer_at and estimated_at and customer_at > estimated_at:
                if findings.late_seller_ids:
                    findings.is_seller_delay = True
                    findings.verdict = "seller_delay"
                else:
                    findings.is_logistics_delay = True
                    findings.verdict = "logistics_delay"
            elif customer_at:
                findings.verdict = "on_time"
            else:
                order_status = data.get("order_status")
                if order_status == "canceled":
                    findings.verdict = "on_time"
                elif order_status == "unavailable":
                    findings.verdict = "lost"
                else:
                    findings.verdict = "insufficient_evidence"

        except Exception:
            findings.verdict = "insufficient_evidence"

        findings.evidence_refs = evidence_refs
        return findings
