"""Order and Product Specialist Agent."""

from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter
from .models import CaseEvidenceContext, OrderFindings


class OrderAgent:
    """Specialist responsible for order status, item inventory,
    seller details and catalog context.
    """

    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def investigate(
        self,
        case_id: str,
        order_id: str,
        scope: dict[str, Any],
        context: CaseEvidenceContext,
        needs_items: bool = True,
        needs_sellers: bool = False,
        needs_product_context: bool = False,
    ) -> OrderFindings:
        evidence_refs: list[str] = []
        findings = OrderFindings(order_id=order_id)

        # 1. get_order (always authoritative baseline)
        try:
            order_ev = await context.call_tool(
                self.gateway,
                "get_order",
                case_id=case_id,
                trace=self.trace,
                actor="order_agent",
                order_id=order_id,
            )
            ref = order_ev["evidence_ref"]
            evidence_refs.append(ref)
            data = order_ev["data"]
            findings.order_status = data.get("order_status")
            findings.purchase_timestamp = data.get("order_purchase_timestamp")
            findings.approved_at = data.get("order_approved_at")
        except Exception:
            pass

        # 2. get_order_items (only when items, sellers, or freight are needed)
        if needs_items:
            try:
                items_ev = await context.call_tool(
                    self.gateway,
                    "get_order_items",
                    case_id=case_id,
                    trace=self.trace,
                    actor="order_agent",
                    trace_attrs={"item_count": 0},
                    order_id=order_id,
                )
                ref = items_ev["evidence_ref"]
                evidence_refs.append(ref)
                items_data = items_ev["data"]
                findings.items = items_data
                for item in items_data:
                    iid = item.get("order_item_id")
                    if iid and str(iid) not in findings.item_ids:
                        findings.item_ids.append(str(iid))

                    sid = item.get("seller_id")
                    if sid and sid not in findings.seller_ids:
                        findings.seller_ids.append(sid)

                    pid = item.get("product_id")
                    if pid and pid not in findings.product_ids:
                        findings.product_ids.append(pid)

                    try:
                        price = float(item.get("price", 0.0) or 0.0)
                    except (ValueError, TypeError):
                        price = 0.0

                    try:
                        freight = float(item.get("freight_value", 0.0) or 0.0)
                    except (ValueError, TypeError):
                        freight = 0.0

                    findings.total_items_price_brl += price
                    findings.total_freight_brl += freight

                    if sid:
                        if sid not in findings.seller_financials:
                            findings.seller_financials[sid] = {
                                "items": [],
                                "item_price": 0.0,
                                "freight": 0.0,
                                "total": 0.0,
                            }
                        findings.seller_financials[sid]["items"].append(str(iid) if iid else pid)
                        findings.seller_financials[sid]["item_price"] = round(
                            findings.seller_financials[sid]["item_price"] + price, 2
                        )
                        findings.seller_financials[sid]["freight"] = round(
                            findings.seller_financials[sid]["freight"] + freight, 2
                        )
                        findings.seller_financials[sid]["total"] = round(
                            findings.seller_financials[sid]["item_price"]
                            + findings.seller_financials[sid]["freight"],
                            2,
                        )

                    deadline = item.get("shipping_limit_date")
                    if deadline:
                        findings.shipping_deadlines.append(
                            {
                                "order_item_id": str(iid) if iid else "",
                                "seller_id": sid or "",
                                "shipping_limit_date": str(deadline),
                            }
                        )

                findings.total_items_price_brl = round(findings.total_items_price_brl, 2)
                findings.total_freight_brl = round(findings.total_freight_brl, 2)
                findings.total_order_value_brl = round(
                    findings.total_items_price_brl + findings.total_freight_brl, 2
                )
            except Exception:
                pass

        # 3. get_sellers (only if seller identification is required and not present, or if cached)
        cached_sellers = context.get_cached("get_sellers", {"order_id": order_id})
        if (needs_sellers and not findings.seller_ids) or cached_sellers is not None:
            try:
                sellers_ev = await context.call_tool(
                    self.gateway,
                    "get_sellers",
                    case_id=case_id,
                    trace=self.trace,
                    actor="order_agent",
                    order_id=order_id,
                )
                ref = sellers_ev["evidence_ref"]
                evidence_refs.append(ref)
                sellers_data = sellers_ev["data"]
                for s in sellers_data:
                    sid = s.get("seller_id")
                    if sid and sid not in findings.seller_ids:
                        findings.seller_ids.append(sid)
                    if sid:
                        findings.seller_locations[sid] = {
                            "city": s.get("seller_city", ""),
                            "state": s.get("seller_state", ""),
                            "zip_code_prefix": str(s.get("seller_zip_code_prefix", "")),
                        }
            except Exception:
                pass

        # 4. get_product_context (only when explicitly needed by catalog/product scope,
        # or if cached)
        cached_prod = context.get_cached("get_product_context", {"order_id": order_id})
        if (
            needs_product_context and scope.get("include_product_context", True)
        ) or cached_prod is not None:
            try:
                prod_ev = await context.call_tool(
                    self.gateway,
                    "get_product_context",
                    case_id=case_id,
                    trace=self.trace,
                    actor="order_agent",
                    order_id=order_id,
                )
                ref = prod_ev["evidence_ref"]
                evidence_refs.append(ref)
                prod_data = prod_ev["data"]
                for p in prod_data:
                    pid = p.get("product_id")
                    if pid and pid not in findings.product_ids:
                        findings.product_ids.append(pid)
                    cat = p.get("category_name_english") or (p.get("product", {}) or {}).get(
                        "product_category_name"
                    )
                    if cat and cat not in findings.product_categories:
                        findings.product_categories.append(cat)
            except Exception:
                pass

        findings.evidence_refs = evidence_refs
        return findings
