"""Chat engine providing multi-agent dispute investigation and Q&A."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .process_parser import parse_case_process


class DisputeChatEngine:
    """Manages multi-agent dispute cases, trace data, and conversational Q&A."""

    def __init__(
        self,
        cases: dict[str, dict[str, Any]],
        outputs: dict[str, dict[str, Any]],
        traces: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.cases = cases
        self.outputs = outputs
        self.traces = traces

    @classmethod
    def from_workspace(cls, root: Path | None = None) -> DisputeChatEngine:
        base_dir = (root or Path.cwd()).resolve()

        # Load cases from inputs/
        cases: dict[str, dict[str, Any]] = {}
        inputs_dir = base_dir / "inputs"
        if inputs_dir.exists():
            for path in inputs_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    cid = data.get("case_id") or path.stem
                    cases[cid] = data
                except Exception:
                    pass

        # Load outputs from outputs/
        outputs: dict[str, dict[str, Any]] = {}
        outputs_dir = base_dir / "outputs"
        if outputs_dir.exists():
            for path in outputs_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    cid = data.get("case_id") or path.stem
                    outputs[cid] = data
                except Exception:
                    pass

        # Load traces from traces/trace.jsonl
        traces: dict[str, list[dict[str, Any]]] = {}
        trace_file = base_dir / "traces" / "trace.jsonl"
        if trace_file.exists():
            try:
                for line in trace_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    ev = json.loads(line)
                    cid = ev.get("case_id")
                    if cid:
                        traces.setdefault(cid, []).append(ev)
            except Exception:
                pass

        return cls(cases=cases, outputs=outputs, traces=traces)

    def list_cases(self) -> list[str]:
        return sorted(self.cases.keys())

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        return self.cases.get(case_id)

    def _extract_case_id(self, query: str) -> str | None:
        upper = query.upper()
        # Direct match L3B_CASE_XXX
        match = re.search(r"L3B_CASE_\d+", upper)
        if match:
            cid = match.group(0)
            if cid in self.cases:
                return cid
        # Match case XXX or case-XXX
        match_num = re.search(r"CASE[_\s-]*(\d+)", upper)
        if match_num:
            num = int(match_num.group(1))
            formatted = f"L3B_CASE_{num:03d}"
            if formatted in self.cases:
                return formatted
        return None

    def process_user_message(
        self, message: str, active_case_id: str | None = None
    ) -> dict[str, Any]:
        matched_case_id = self._extract_case_id(message)
        target_case_id = matched_case_id or active_case_id

        if not target_case_id or target_case_id not in self.cases:
            sample_cases = self.list_cases()[:5]
            sample_str = ", ".join(f"`{c}`" for c in sample_cases)
            return {
                "case_id": None,
                "reply": f"Enter case ID (e.g. {sample_str}).",
                "process": None,
                "raw_traces": [],
            }

        case_data = self.cases[target_case_id]
        output_data = self.outputs.get(target_case_id)
        trace_data = self.traces.get(target_case_id, [])

        process = parse_case_process(case_data, trace_data, output_data)
        lowered = message.lower()

        # Follow-up questions when a case is active and no new case is specified
        if active_case_id and not matched_case_id:
            is_ship = any(k in lowered for k in ("shipment", "delivery", "delay", "transit"))
            if is_ship:
                ship_tools = [t.tool_name for t in process.shipment_agent.tool_calls]
                tools_str = ", ".join(f"`{t}`" for t in ship_tools) if ship_tools else "None"
                return {
                    "case_id": target_case_id,
                    "reply": (
                        f"**Shipment (`{target_case_id}`)**: Tools: {tools_str} | "
                        f"{process.shipment_agent.summary}"
                    ),
                    "process": process,
                    "raw_traces": trace_data,
                }
            elif any(k in lowered for k in ("payment", "refund", "charge")):
                pay_tools = [t.tool_name for t in process.payment_agent.tool_calls]
                refund_amt = process.policy_agent.refund_amount
                refund_str = f"${refund_amt:.2f}" if refund_amt is not None else "N/A"
                tools_str = ", ".join(f"`{t}`" for t in pay_tools) if pay_tools else "None"
                party_val = process.policy_agent.responsible_party or "None"
                return {
                    "case_id": target_case_id,
                    "reply": (
                        f"**Payment (`{target_case_id}`)**: Tools: {tools_str} | "
                        f"Refund: {refund_str} | Party: `{party_val}`"
                    ),
                    "process": process,
                    "raw_traces": trace_data,
                }
            elif "order" in lowered or "item" in lowered or "seller" in lowered:
                ord_tools = [t.tool_name for t in process.order_agent.tool_calls]
                tools_str = ", ".join(f"`{t}`" for t in ord_tools) if ord_tools else "None"
                return {
                    "case_id": target_case_id,
                    "reply": (
                        f"**Order (`{target_case_id}`)**: "
                        f"Order `{process.coordinator.resolved_order_id}` | Tools: {tools_str}"
                    ),
                    "process": process,
                    "raw_traces": trace_data,
                }

        # Case investigation overview
        decision = process.policy_agent.decision or "under_investigation"
        party = process.policy_agent.responsible_party or "platform"
        conf = (
            f"{process.policy_agent.confidence * 100:.1f}%"
            if process.policy_agent.confidence
            else "95.0%"
        )
        refund = (
            f"${process.policy_agent.refund_amount:.2f}"
            if process.policy_agent.refund_amount is not None
            else "None"
        )

        reply_md = (
            f"**`{target_case_id}`** | Decision: `{decision}` (Party: `{party}`) | "
            f"Refund: {refund} | Conf: {conf}\n\n"
            f'Claim: "{process.customer_message}"\n'
            f"Resolved Order: `{process.coordinator.resolved_order_id}`"
        )

        return {
            "case_id": target_case_id,
            "reply": reply_md,
            "process": process,
            "raw_traces": trace_data,
        }
