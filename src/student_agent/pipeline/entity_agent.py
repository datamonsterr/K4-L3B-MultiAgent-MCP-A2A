"""Entity Resolution Specialist Agent."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter
from .models import CaseEvidenceContext

HEX_32_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class EntityFindings(BaseModel):
    resolved_order_id: str
    rejected_candidates: list[str] = Field(default_factory=list)
    customer_unique_id: str | None = None
    related_order_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.95


class EntityAgent:
    """Specialist responsible for disambiguating orders, users, and customer entities."""

    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def resolve(
        self,
        case: dict[str, Any],
        context: CaseEvidenceContext,
    ) -> EntityFindings:
        case_id = case["case_id"]
        req = case.get("customer_request", {})
        claimed_id = req.get("claimed_order_id")
        candidate_ids = case.get("candidate_order_ids", [])
        hint = case.get("customer_unique_id_hint")

        self.trace.emit(
            case_id=case_id,
            event_type="task_assigned",
            actor="coordinator",
            target="entity_agent",
            attributes={"task": "resolve_entities_and_user_data"},
        )

        resolved_id = None
        rejected_candidates: list[str] = []
        customer_unique_id: str | None = hint
        related_order_ids: list[str] = []

        # 1. Resolve claimed order ID against candidates
        if claimed_id and HEX_32_PATTERN.match(claimed_id) and claimed_id in candidate_ids:
            resolved_id = claimed_id
            rejected_candidates = [c for c in candidate_ids if c != claimed_id]
        else:
            # Check candidate order IDs for valid 32-char hex
            valid_candidates = [c for c in candidate_ids if HEX_32_PATTERN.match(c)]
            if len(valid_candidates) == 1:
                resolved_id = valid_candidates[0]
                rejected_candidates = [c for c in candidate_ids if c != resolved_id]
            elif context.is_tool_allowed("get_customer_history") and hint:
                try:
                    cust_ev = await context.call_tool(
                        self.gateway,
                        "get_customer_history",
                        case_id=case_id,
                        trace=self.trace,
                        actor="entity_agent",
                        customer_unique_id=hint,
                    )
                    cust_data = cust_ev.get("data", {})
                    customer_unique_id = cust_data.get("customer_unique_id") or hint
                    orders = cust_data.get("orders", [])
                    related_order_ids = [
                        o.get("order_id") for o in orders if o.get("order_id") in candidate_ids
                    ]
                    for cand in candidate_ids:
                        if cand in related_order_ids:
                            resolved_id = cand
                            break
                    if resolved_id:
                        rejected_candidates = [c for c in candidate_ids if c != resolved_id]
                except Exception:
                    pass

        if not resolved_id:
            resolved_id = candidate_ids[0] if candidate_ids else (claimed_id or "unknown_order")
            rejected_candidates = [c for c in candidate_ids if c != resolved_id]

        confidence = 0.96 if rejected_candidates else 0.92

        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="entity_agent",
            target="coordinator",
            attributes={
                "resolved_order_id": resolved_id,
                "rejected_count": len(rejected_candidates),
            },
        )

        return EntityFindings(
            resolved_order_id=resolved_id,
            rejected_candidates=rejected_candidates,
            customer_unique_id=customer_unique_id,
            related_order_ids=related_order_ids,
            confidence=confidence,
        )
