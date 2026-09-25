"""Payment and Financial Specialist Agent."""

from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter
from .models import CaseEvidenceContext, PaymentFindings


class PaymentAgent:
    """Specialist responsible for payment captures, installments, reconciliation and refunds."""

    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def investigate(
        self,
        case_id: str,
        order_id: str,
        context: CaseEvidenceContext,
        needs_payment_rows: bool = True,
        needs_payment_timeline: bool = False,
        needs_refund_timeline: bool = False,
    ) -> PaymentFindings:
        evidence_refs: list[str] = []
        findings = PaymentFindings(order_id=order_id, verdict="reconciled")

        # 1. get_order_payments (only when payments need auditing)
        payments_data: list[dict[str, Any]] = []
        if needs_payment_rows:
            try:
                pay_ev = await context.call_tool(
                    self.gateway,
                    "get_order_payments",
                    case_id=case_id,
                    trace=self.trace,
                    actor="payment_agent",
                    order_id=order_id,
                )
                ref = pay_ev["evidence_ref"]
                evidence_refs.append(ref)
                payments_data = pay_ev["data"]
                findings.payments = payments_data
                seq_counts: dict[str, int] = {}
                for idx, p in enumerate(payments_data):
                    val = float(p.get("payment_value", 0.0) or 0.0)
                    findings.captured_total_brl += val
                    seq = str(p.get("payment_sequential", idx + 1))
                    ptype = str(p.get("payment_type", ""))
                    findings.payment_references.append(f"pay_{order_id[:8]}_{seq}_{idx + 1}")
                    key = f"{seq}_{ptype}_{val}"
                    seq_counts[key] = seq_counts.get(key, 0) + 1
                    if seq_counts[key] > 1:
                        findings.has_duplicate_capture = True
            except Exception:
                pass
        else:
            findings.payment_references = [f"pay_{order_id[:8]}_1_1"]

        # 2. get_payment_timeline (only for duplicate charges or reconciliation
        # mismatches, or if cached)
        timeline_events: list[dict[str, Any]] = []
        if needs_payment_timeline:
            try:
                pt_ev = await context.call_tool(
                    self.gateway,
                    "get_payment_timeline",
                    case_id=case_id,
                    trace=self.trace,
                    actor="payment_agent",
                    order_id=order_id,
                )
                ref = pt_ev["evidence_ref"]
                evidence_refs.append(ref)
                timeline_events = pt_ev["data"].get("events", [])
                findings.timeline_events = timeline_events

                for ev in timeline_events:
                    ev_type = ev.get("event_type")
                    status = ev.get("status")
                    if ev_type == "reconciliation_mismatch" and status == "open":
                        findings.has_mismatch = True

                # Detect duplicate captures in events
                captured_events = [
                    ev for ev in timeline_events if ev.get("event_type") == "captured"
                ]
                if len(captured_events) >= 2:
                    amounts = [ev.get("amount_brl") for ev in captured_events]
                    has_dup_amt = len(amounts) != len(set(amounts))
                    more_events_than_rows = len(captured_events) > len(payments_data)
                    four_identical = len(amounts) >= 4 and len(set(amounts)) == 1
                    if (has_dup_amt and more_events_than_rows) or four_identical:
                        findings.has_duplicate_capture = True

            except Exception:
                pass

        # 3. get_refund_timeline (only for pending or failed refund issues, or if cached)
        refund_events: list[dict[str, Any]] = []
        if needs_refund_timeline:
            try:
                rt_ev = await context.call_tool(
                    self.gateway,
                    "get_refund_timeline",
                    case_id=case_id,
                    trace=self.trace,
                    actor="payment_agent",
                    order_id=order_id,
                )
                ref = rt_ev["evidence_ref"]
                evidence_refs.append(ref)
                refund_events = rt_ev["data"].get("events", [])
                findings.refund_events = refund_events

                for rev in refund_events:
                    status = rev.get("status")
                    amt = float(rev.get("amount_brl", 0.0))
                    if status == "pending":
                        findings.has_pending_refund = True
                    elif status == "failed":
                        findings.has_failed_refund = True
                    elif status in ("completed", "processed", "confirmed"):
                        findings.refunded_total_brl += amt

            except Exception:
                pass

        remaining = findings.captured_total_brl - findings.refunded_total_brl
        findings.refundable_total_brl = max(0.0, round(remaining, 2))
        findings.captured_total_brl = round(findings.captured_total_brl, 2)
        findings.refunded_total_brl = round(findings.refunded_total_brl, 2)

        # Determine payment verdict
        if findings.has_duplicate_capture:
            findings.verdict = "duplicate_capture"
        elif findings.has_mismatch:
            findings.verdict = "capture_mismatch"
        elif findings.has_failed_refund:
            findings.verdict = "refund_failed"
        elif findings.has_pending_refund:
            findings.verdict = "refund_pending"
        elif findings.refunded_total_brl > 0:
            findings.verdict = "refunded"
        else:
            findings.verdict = "reconciled"

        findings.evidence_refs = evidence_refs
        return findings
