"""Process parser extracting multi-agent steps, MCP calls, and verification status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentToolCall:
    tool_name: str
    evidence_refs: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class CoordinatorStep:
    claimed_order_id: str | None = None
    resolved_order_id: str | None = None
    rejected_candidates: list[str] = field(default_factory=list)
    customer_hint: str | None = None
    tool_calls: list[AgentToolCall] = field(default_factory=list)


@dataclass
class SpecialistStep:
    actor: str
    role_title: str
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    status: str = "completed"
    summary: str = ""


@dataclass
class PolicyStep:
    decision: str | None = None
    responsible_party: str | None = None
    refund_amount: float | None = None
    confidence: float | None = None
    claims: list[dict[str, Any]] = field(default_factory=list)
    rationale: str | None = None


@dataclass
class VerifierStep:
    passed: bool = True
    schema_valid: bool = True
    invariants_passed: bool = True
    evidence_audit_passed: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class MultiAgentProcess:
    case_id: str
    customer_message: str
    coordinator: CoordinatorStep
    order_agent: SpecialistStep
    shipment_agent: SpecialistStep
    payment_agent: SpecialistStep
    policy_agent: PolicyStep
    verifier_agent: VerifierStep
    raw_traces: list[dict[str, Any]] = field(default_factory=list)


def parse_case_process(
    case: dict[str, Any],
    traces: list[dict[str, Any]] | None = None,
    output: dict[str, Any] | None = None,
) -> MultiAgentProcess:
    case_id = case.get("case_id", "")
    traces = traces or []
    output = output or {}

    cust_req = case.get("customer_request", {})
    customer_msg = cust_req.get("message", "")
    claimed_order = cust_req.get("claimed_order_id")
    customer_hint = case.get("customer_unique_id_hint")

    # Coordinator
    coord_tools: list[AgentToolCall] = []
    order_tools: list[AgentToolCall] = []
    shipment_tools: list[AgentToolCall] = []
    payment_tools: list[AgentToolCall] = []
    verifier_completed = False
    schema_valid = True
    invariants_passed = True

    for ev in traces:
        if ev.get("case_id") != case_id:
            continue
        ev_type = ev.get("event_type")
        actor = ev.get("actor", "")

        if ev_type == "tool_result_consumed":
            tool_call = AgentToolCall(
                tool_name=ev.get("tool_name", ""),
                evidence_refs=list(ev.get("evidence_refs", [])),
                attributes=dict(ev.get("attributes", {})),
                occurred_at=ev.get("occurred_at", ""),
            )
            if actor == "coordinator":
                coord_tools.append(tool_call)
            elif actor == "order_agent":
                order_tools.append(tool_call)
            elif actor == "shipment_agent":
                shipment_tools.append(tool_call)
            elif actor == "payment_agent":
                payment_tools.append(tool_call)
        elif ev_type == "verification_completed":
            verifier_completed = True
            attrs = ev.get("attributes", {})
            schema_valid = bool(attrs.get("schema_valid", True))
            invariants_passed = bool(attrs.get("invariants_passed", True))

    # Entity resolution details from output or fallback
    entity_res = output.get("entity_resolution", {})
    resolved_order_ids = entity_res.get("resolved_order_ids", [])
    resolved_order = resolved_order_ids[0] if resolved_order_ids else claimed_order
    rejected_candidates = entity_res.get(
        "rejected_candidates",
        [c for c in case.get("candidate_order_ids", []) if c != resolved_order],
    )

    coordinator_step = CoordinatorStep(
        claimed_order_id=claimed_order,
        resolved_order_id=resolved_order,
        rejected_candidates=rejected_candidates,
        customer_hint=customer_hint,
        tool_calls=coord_tools,
    )

    # Specialist steps
    order_step = SpecialistStep(
        actor="order_agent",
        role_title="Order",
        tool_calls=order_tools,
        summary=f"{len(order_tools)} tool calls",
    )
    shipment_step = SpecialistStep(
        actor="shipment_agent",
        role_title="Shipment",
        tool_calls=shipment_tools,
        summary=f"{len(shipment_tools)} tool calls",
    )
    payment_step = SpecialistStep(
        actor="payment_agent",
        role_title="Payment",
        tool_calls=payment_tools,
        summary=f"{len(payment_tools)} tool calls",
    )

    # Policy step
    dispute_res = output.get("dispute_resolution", {})
    assessment = output.get("assessment", {})
    policy_step = PolicyStep(
        decision=dispute_res.get("decision") or assessment.get("case_status"),
        responsible_party=dispute_res.get("responsible_party"),
        refund_amount=dispute_res.get("refund_amount"),
        confidence=assessment.get("confidence"),
        claims=output.get("claim_assessments", []),
        rationale=dispute_res.get("rationale"),
    )

    # Verifier step
    verifier_notes: list[str] = []
    if schema_valid:
        verifier_notes.append("Schema: valid")
    if invariants_passed:
        verifier_notes.append("Invariants: passed")
    verifier_step = VerifierStep(
        passed=verifier_completed or bool(output),
        schema_valid=schema_valid,
        invariants_passed=invariants_passed,
        evidence_audit_passed=True,
        notes=verifier_notes,
    )

    return MultiAgentProcess(
        case_id=case_id,
        customer_message=customer_msg,
        coordinator=coordinator_step,
        order_agent=order_step,
        shipment_agent=shipment_step,
        payment_agent=payment_step,
        policy_agent=policy_step,
        verifier_agent=verifier_step,
        raw_traces=[t for t in traces if t.get("case_id") == case_id],
    )
