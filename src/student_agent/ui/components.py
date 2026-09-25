"""Reusable UI rendering components for multi-agent processes and MCP tools."""

from __future__ import annotations

import json
from html import escape
from typing import Any

from .process_parser import AgentToolCall, MultiAgentProcess, SpecialistStep


def render_agent_badge_html(actor: str, label: str) -> str:
    color_map = {
        "coordinator": ("#DBEAFE", "#1E40AF"),
        "order_agent": ("#E0E7FF", "#3730A3"),
        "shipment_agent": ("#FEF3C7", "#92400E"),
        "payment_agent": ("#DCFCE7", "#166534"),
        "policy_agent": ("#F3E8FF", "#6B21A8"),
        "verifier_agent": ("#FCE7F3", "#9D174D"),
    }
    bg, fg = color_map.get(actor, ("#F1F5F9", "#334155"))
    return (
        f'<span style="display:inline-block; padding: 2px 9px; border-radius: 50px; '
        f'background-color: {bg}; color: {fg}; font-size: 11px; font-weight: 600;">'
        f"{escape(actor)} • {escape(label)}</span>"
    )


def render_tool_call_html(tool: AgentToolCall) -> str:
    attrs_items = [
        f"{escape(str(k))}={escape(str(v))}" for k, v in list(tool.attributes.items())[:3]
    ]
    attrs_str = f" ({', '.join(attrs_items)})" if attrs_items else ""

    refs_html = "".join(
        f'<span style="display:inline-block; font-family: monospace; font-size: 10px; '
        f"padding: 1px 6px; border-radius: 50px; background-color: #FEF9C3; color: #854D0E; "
        f'border: 1px solid #FEF08A; margin: 1px 2px;">{escape(ref)}</span>'
        for ref in tool.evidence_refs
    )

    occ_time = escape(tool.occurred_at[-13:-1] if tool.occurred_at else "")
    refs_container = f"<div style='margin-top: 3px;'>{refs_html}</div>" if refs_html else ""
    return (
        f'<div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; '
        f'padding: 6px 8px; margin-bottom: 5px; font-size: 11.5px;">'
        f'<div style="display: flex; align-items: center; justify-content: space-between;">'
        f'<span style="font-family: monospace; font-weight: 600; color: #1E293B;">'
        f"🛠️ {escape(tool.tool_name)}</span>"
        f'<span style="font-size: 10px; color: #64748B;">{occ_time}</span>'
        f"</div>"
        f'<div style="color: #475569; font-size: 11px; margin-top: 2px;">{attrs_str}</div>'
        f"{refs_container}"
        f"</div>"
    )


def format_trace_events_for_display(traces: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for t in traces:
        lines.append(json.dumps(t, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def render_specialist_lane(st_module: Any, specialist: SpecialistStep, badge_title: str) -> None:
    badge_html = render_agent_badge_html(specialist.actor, badge_title)
    st_module.markdown(badge_html, unsafe_allow_html=True)
    st_module.caption(specialist.summary)

    if not specialist.tool_calls:
        no_tools_html = (
            '<div style="color: #94A3B8; font-size: 11px; font-style: italic;">'
            "No direct tool calls</div>"
        )
        st_module.markdown(no_tools_html, unsafe_allow_html=True)
        return

    count = len(specialist.tool_calls)
    st_module.markdown(
        f'<div style="font-size: 11px; font-weight: 600; color: #475569; margin: 4px 0 2px 0;">'
        f"MCP Tool Calls ({count}):</div>",
        unsafe_allow_html=True,
    )
    for tool in specialist.tool_calls:
        st_module.markdown(render_tool_call_html(tool), unsafe_allow_html=True)


def render_multiagent_flow(st_module: Any, process: MultiAgentProcess) -> None:
    """Render the full process: Coordinator -> Parallel Specialists -> Policy -> Verifier."""

    # 1. Coordinator Step
    with st_module.expander("📍 Phase 1: Coordinator & Entity Resolution", expanded=True):
        st_module.markdown(
            render_agent_badge_html("coordinator", "Supervisor & Router"),
            unsafe_allow_html=True,
        )
        c = process.coordinator
        rej_list = [f"<code>{escape(cand)}</code>" for cand in c.rejected_candidates]
        rej_str = ", ".join(rej_list) if rej_list else "None"
        st_module.markdown(
            f'<div style="margin-top: 6px; font-size: 12px; line-height: 1.4;">'
            f"• <b>Claimed Order ID</b>: <code>{escape(str(c.claimed_order_id))}</code><br>"
            f"• <b>Resolved Order ID</b>: <code>{escape(str(c.resolved_order_id))}</code><br>"
            f"• <b>Rejected Candidates</b>: {rej_str}<br>"
            f"• <b>Customer Hint</b>: <code>{escape(str(c.customer_hint or 'None'))}</code>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if c.tool_calls:
            st_module.markdown(
                '<div style="font-size: 11px; font-weight: 600; color: #475569; '
                'margin-top: 6px;">Coordinator MCP Evidence Calls:</div>',
                unsafe_allow_html=True,
            )
            for tool in c.tool_calls:
                st_module.markdown(render_tool_call_html(tool), unsafe_allow_html=True)

    # 2. Async Parallel Specialists (MUST show parallel)
    with st_module.expander("⚡ Phase 2: Async Parallel Specialists Execution", expanded=True):
        concurrent_badge = (
            '<span style="padding: 1px 7px; border-radius: 50px; background: #DCFCE7; '
            'color: #15803D; font-size: 10.5px; font-weight: 600;">Concurrent</span>'
        )
        st_module.markdown(
            f'<div style="display:flex; align-items:center; gap: 8px; margin-bottom: 8px;">'
            f'<span style="font-size: 12px; font-weight: 600; color: #1E293B;">'
            f"Parallel Specialist Lanes (asyncio.gather)</span>"
            f"{concurrent_badge}"
            f"</div>",
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st_module.columns(3)
        with col1:
            render_specialist_lane(st_module, process.order_agent, "Order & Catalog")
        with col2:
            render_specialist_lane(st_module, process.shipment_agent, "Logistics & Tracking")
        with col3:
            render_specialist_lane(st_module, process.payment_agent, "Payments & Refunds")

    # 3. Policy & Conflict Resolution
    with st_module.expander("⚖️ Phase 3: Policy & Conflict Adjudication", expanded=True):
        st_module.markdown(
            render_agent_badge_html("policy_agent", "Conflict Resolver"),
            unsafe_allow_html=True,
        )
        p = process.policy_agent
        refund_disp = f"${p.refund_amount:.2f}" if p.refund_amount is not None else "No refund"
        conf_disp = f"{p.confidence * 100:.1f}%" if p.confidence else "N/A"
        dec_span = f'<span style="font-weight:600; color:#1D4ED8;">{escape(str(p.decision))}</span>'
        party_str = escape(str(p.responsible_party or "platform"))
        rat_str = escape(str(p.rationale or "Adjudicated against dispute guidelines."))
        st_module.markdown(
            f'<div style="margin-top: 6px; font-size: 12px; line-height: 1.4;">'
            f"• <b>Decision</b>: {dec_span} (Responsible: <b>{party_str}</b>)<br>"
            f"• <b>Refund Amount</b>: <b>{refund_disp}</b> | <b>Confidence</b>: {conf_disp}<br>"
            f"• <b>Policy Rationale</b>: {rat_str}"
            f"</div>",
            unsafe_allow_html=True,
        )
        if p.claims:
            st_module.markdown(
                '<div style="font-size: 11px; font-weight: 600; color: #475569; '
                'margin-top: 6px;">Claim Breakdown:</div>',
                unsafe_allow_html=True,
            )
            for claim in p.claims:
                cid = claim.get("claim_id", "")
                verdict = claim.get("verdict", "")
                refs = claim.get("evidence_refs", [])
                refs_str = ", ".join(f"<code>{r}</code>" for r in refs) if refs else "None"
                st_module.markdown(
                    f'<div style="font-size: 11px; padding: 2px 0;">'
                    f"• <code>{escape(cid)}</code>: <b>{escape(verdict)}</b> "
                    f"(Evidence: {refs_str})</div>",
                    unsafe_allow_html=True,
                )

    # 4. Verifier Agent
    with st_module.expander("🛡️ Phase 4: Invariants & Provenance Verification", expanded=True):
        st_module.markdown(
            render_agent_badge_html("verifier_agent", "Invariant Verifier"),
            unsafe_allow_html=True,
        )
        v = process.verifier_agent
        status_color = "#16A34A" if v.passed else "#DC2626"
        status_text = "PASSED ALL INVARIANTS" if v.passed else "VERIFICATION FAILED"
        st_module.markdown(
            f'<div style="margin-top: 4px; font-weight: 600; font-size: 12px; '
            f'color: {status_color};">Status: {status_text}</div>',
            unsafe_allow_html=True,
        )
        notes_html = "".join(f"<li>{escape(n)}</li>" for n in v.notes)
        st_module.markdown(
            f'<ul style="margin-top: 4px; margin-bottom: 2px; padding-left: 18px; '
            f'font-size: 11.5px; color: #334155;">{notes_html}</ul>',
            unsafe_allow_html=True,
        )
