def _route_ranking_value(route: dict, metric: str) -> float:
    m = str(metric or "profit_total").strip().lower()
    profit = float(route.get("profit_total", 0.0) or 0.0)
    isk_used = float(route.get("isk_used", 0.0) or 0.0)
    m3_used = float(route.get("m3_used", 0.0) or 0.0)
    if m in ("profit_per_m3", "isk_per_m3"):
        return profit / max(1e-9, m3_used)
    if m in ("profit_pct", "profit_per_isk"):
        return profit / max(1e-9, isk_used)
    return profit


def _profit_dominance(route: dict) -> tuple[float, float, bool]:
    picks = list(route.get("picks", []) or [])
    profits = sorted([max(0.0, float(p.get("profit", 0.0) or 0.0)) for p in picks], reverse=True)
    total_profit = max(0.0, float(route.get("profit_total", 0.0) or 0.0))
    if total_profit <= 0.0 or not profits:
        return 0.0, 0.0, False
    top3 = sum(profits[:3]) / total_profit
    top5 = sum(profits[:5]) / total_profit
    dominant = top3 > 0.60 or top5 > 0.60
    return top3, top5, dominant


def _pick_fee_components(pick: dict) -> dict[str, float]:
    sales_tax_isk = float(pick.get("sales_tax_isk", pick.get("sales_tax_total", 0.0)) or 0.0)
    broker_fee_isk = float(pick.get("broker_fee_isk", pick.get("sell_broker_fee_total", 0.0)) or 0.0)
    scc_surcharge_isk = float(pick.get("scc_surcharge_isk", pick.get("scc_surcharge_total", 0.0)) or 0.0)
    relist_fee_isk = float(pick.get("relist_fee_isk", pick.get("relist_budget_total", 0.0)) or 0.0)
    buy_broker_fee_isk = float(pick.get("buy_broker_fee_total", 0.0) or 0.0)
    return {
        "sales_tax_isk": sales_tax_isk,
        "broker_fee_isk": broker_fee_isk,
        "scc_surcharge_isk": scc_surcharge_isk,
        "relist_fee_isk": relist_fee_isk,
        "buy_broker_fee_isk": buy_broker_fee_isk,
    }


def _pick_total_fees_taxes(pick: dict) -> float:
    f = _pick_fee_components(pick)
    return (
        float(f["buy_broker_fee_isk"])
        + float(f["broker_fee_isk"])
        + float(f["sales_tax_isk"])
        + float(f["scc_surcharge_isk"])
        + float(f["relist_fee_isk"])
    )


def write_execution_plan_profiles(path: str, timestamp: str, route_results: list[dict]) -> None:
    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("EXECUTION PLAN (ROUTE PROFILES)")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    lines.append("")

    total_cost = 0.0
    total_revenue = 0.0
    total_profit = 0.0
    total_fees_taxes = 0.0
    total_shipping_cost = 0.0
    total_route_costs = 0.0

    for idx, leg in enumerate(route_results, start=1):
        picks = list(leg.get("picks", []) or [])
        lines.append(f"PLAN {idx}: {leg.get('route_label', '')}")
        lines.append("-" * max(8, len(lines[-1])))
        src_info = leg.get("source_node_info", {}) if isinstance(leg.get("source_node_info", {}), dict) else {}
        dst_info = leg.get("dest_node_info", {}) if isinstance(leg.get("dest_node_info", {}), dict) else {}
        if src_info:
            if str(src_info.get("node_kind", "")) == "location":
                lines.append(
                    f"Source: {src_info.get('node_label', leg.get('source_label', ''))} "
                    f"(location_id {int(src_info.get('location_id', src_info.get('node_id', 0)) or 0)}, "
                    f"region {int(src_info.get('node_region_id', 0) or 0)})"
                )
            else:
                lines.append(
                    f"Source: {src_info.get('node_label', leg.get('source_label', ''))} "
                    f"(structure_id {int(src_info.get('structure_id', src_info.get('node_id', 0)) or 0)})"
                )
        if dst_info:
            if str(dst_info.get("node_kind", "")) == "location":
                lines.append(
                    f"Dest: {dst_info.get('node_label', leg.get('dest_label', ''))} "
                    f"(location_id {int(dst_info.get('location_id', dst_info.get('node_id', 0)) or 0)}, "
                    f"region {int(dst_info.get('node_region_id', 0) or 0)})"
                )
            else:
                lines.append(
                    f"Dest: {dst_info.get('node_label', leg.get('dest_label', ''))} "
                    f"(structure_id {int(dst_info.get('structure_id', dst_info.get('node_id', 0)) or 0)})"
                )
        shipping_lane_id = str(leg.get("shipping_lane_id", "") or "")
        if shipping_lane_id:
            lines.append(f"Shipping Lane: {shipping_lane_id}")
            provider = str(leg.get("shipping_provider", "") or "")
            if provider:
                lines.append(f"provider: {provider}")
            pricing_model = str(leg.get("shipping_pricing_model", "") or "")
            if pricing_model:
                lines.append(f"pricing_model: {pricing_model}")
            contracts_used = int(leg.get("shipping_contracts_used", 0) or 0)
            if contracts_used > 0:
                lines.append(f"contracts_used: {contracts_used}")
            split_reason = str(leg.get("shipping_split_reason", "") or "")
            if split_reason:
                lines.append(f"split_reason: {split_reason}")
            est_collateral = float(leg.get("estimated_collateral_isk", 0.0) or 0.0)
            if est_collateral > 0.0:
                lines.append(f"estimated_collateral_isk: {fmt_isk_de(est_collateral)}")
            lane_params = leg.get("shipping_lane_params", {})
            if isinstance(lane_params, dict) and lane_params:
                for key in (
                    "per_m3_rate",
                    "minimum_reward",
                    "full_load_reward",
                    "collateral_rate",
                    "additional_collateral_rate",
                    "max_volume_per_contract_m3",
                    "max_collateral_per_contract_isk",
                    "max_value",
                    "collateral_basis",
                ):
                    if key in lane_params:
                        lines.append(f"{key}: {lane_params.get(key)}")
        cost_model_confidence = str(leg.get("cost_model_confidence", "normal") or "normal")
        if cost_model_confidence != "normal":
            lines.append(f"transport_cost_confidence: {cost_model_confidence}")
            warn_msg = str(leg.get("cost_model_warning", "") or "")
            if warn_msg:
                lines.append(f"transport_cost_warning: {warn_msg}")
        leg_cost = float(leg.get("isk_used", 0.0))
        leg_revenue = sum(float(p.get("revenue_net", 0.0)) for p in picks)
        leg_profit = float(leg.get("profit_total", 0.0))
        leg_fees_taxes = sum(_pick_total_fees_taxes(p) for p in picks)
        leg_route_costs = float(leg.get("total_transport_cost", 0.0))
        leg_shipping_costs = float(leg.get("total_shipping_cost", 0.0))
        total_cost += leg_cost
        total_revenue += leg_revenue
        total_profit += leg_profit
        total_fees_taxes += leg_fees_taxes
        total_shipping_cost += leg_shipping_costs
        total_route_costs += leg_route_costs
        lines.append(f"Total Cost: {fmt_isk_de(leg_cost)}")
        lines.append(f"Total Net Revenue: {fmt_isk_de(leg_revenue)}")
        lines.append(f"Total Expected Net Profit: {fmt_isk_de(leg_profit)}")
        lines.append(f"Total Fees and Taxes: {fmt_isk_de(leg_fees_taxes)}")
        lines.append(f"Total Route Costs: {fmt_isk_de(leg_route_costs)}")
        lines.append(f"total_route_m3: {float(leg.get('total_route_m3', leg.get('m3_used', 0.0)) or 0.0):.2f} m3")
        if leg_shipping_costs > 0.0:
            lines.append(f"Shipping Cost Total: {fmt_isk_de(leg_shipping_costs)}")
            lines.append(f"shipping_cost_total: {fmt_isk_de(leg_shipping_costs)}")
        budget_total = float(leg.get("budget_total", 0.0))
        budget_used = float(leg.get("isk_used", 0.0))
        budget_left = max(0.0, budget_total - budget_used)
        if budget_total > 0 and (budget_left / budget_total) >= 0.05:
            lines.append(
                "Budget Rest: "
                f"{fmt_isk_de(budget_left)}. Grund: Keine weiteren Picks erfuellen Profit-Floors nach Gebuehren und Routenkosten."
            )
        lines.append("")
        ordered = sorted(picks, key=lambda x: float(x.get("profit", 0.0)), reverse=True)
        for p_i, p in enumerate(ordered, start=1):
            qty = int(p.get("qty", 0))
            buy_avg = float(p.get("buy_avg", 0.0))
            buy_total = buy_avg * qty
            sell_unit = float(p.get("target_sell_price", 0.0) or p.get("sell_avg", 0.0))
            sell_total = sell_unit * qty
            duration = int(float(p.get("order_duration_days", 0) or 0))
            is_instant = bool(p.get("instant", False)) or str(p.get("mode", "")).lower() == "instant"
            exp_days = float(p.get("expected_days_to_sell", 0.0) or 0.0)
            fill_prob = float(p.get("fill_probability", 0.0) or 0.0) * 100.0
            profit = float(p.get("profit", 0.0) or 0.0)
            pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(qty)
            unit_m3 = float(p.get("unit_volume", 0.0) or 0.0)
            lines.append(f"{p_i}. {p.get('name', '')} (type_id {int(p.get('type_id', 0))})")
            lines.append(
                f"   BUY  [{p.get('buy_at') or leg.get('source_label', 'SOURCE')}] qty={qty} @ {fmt_isk_de(buy_avg)} "
                f"(Total {fmt_isk_de(buy_total)})"
            )
            if is_instant:
                lines.append(
                    f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SOFORTVERKAUF/Buy-Order @ {fmt_isk_de(sell_unit)} "
                    f"(Total {fmt_isk_de(sell_total)}) | SOFORT"
                )
            else:
                lines.append(
                    f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SELL-ORDER @ {fmt_isk_de(sell_unit)} "
                    f"(Total {fmt_isk_de(sell_total)}) | Laufzeit {duration}d"
                )
            lines.append(f"   Erwartet: {exp_days:.1f}d bis Verkauf | Fill {fill_prob:.1f}%")
            lines.append(f"   Erwarteter Net Profit: {fmt_isk_de(profit)}")
            fee_components = _pick_fee_components(p)
            lines.append(f"   Fees+Taxes: {fmt_isk_de(_pick_total_fees_taxes(p))}")
            lines.append(f"   sales_tax_isk: {fmt_isk_de(fee_components['sales_tax_isk'])}")
            lines.append(f"   broker_fee_isk: {fmt_isk_de(fee_components['broker_fee_isk'])}")
            lines.append(f"   scc_surcharge_isk: {fmt_isk_de(fee_components['scc_surcharge_isk'])}")
            lines.append(f"   relist_fee_isk: {fmt_isk_de(fee_components['relist_fee_isk'])}")
            lines.append(f"   Route/Shipping Cost: {fmt_isk_de(float(p.get('transport_cost', 0.0)))}")
            lines.append(f"   unit_volume: {unit_m3:.2f} m3 | total_m3: {pick_m3:.2f} m3")
            lines.append(f"   Cargo fuer diesen Pick: {pick_m3:.2f} m3")
            lines.append("")
        if not ordered:
            lines.append("Keine Picks fuer diese Route.")
            lines.append("")

    lines.append("=" * 70)
    lines.append(f"TOTAL COST: {fmt_isk_de(total_cost)}")
    lines.append(f"TOTAL NET REVENUE: {fmt_isk_de(total_revenue)}")
    lines.append(f"TOTAL EXPECTED NET PROFIT: {fmt_isk_de(total_profit)}")
    lines.append(f"TOTAL FEES AND TAXES: {fmt_isk_de(total_fees_taxes)}")
    if total_shipping_cost > 0.0:
        lines.append(f"TOTAL SHIPPING COST: {fmt_isk_de(total_shipping_cost)}")
        lines.append(f"shipping_cost_total: {fmt_isk_de(total_shipping_cost)}")
    lines.append(f"TOTAL ROUTE COSTS: {fmt_isk_de(total_route_costs)}")
    lines.append("=" * 70)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_route_leaderboard(path: str, timestamp: str, route_results: list[dict], ranking_metric: str, max_routes: int) -> None:
    metric = str(ranking_metric or "profit_total").strip().lower()
    ranked = sorted(
        list(route_results or []),
        key=lambda r: (_route_ranking_value(r, metric), float(r.get("profit_total", 0.0))),
        reverse=True
    )[: max(1, int(max_routes or 10))]

    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("ROUTE LEADERBOARD")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    lines.append(f"ranking_metric: {metric}")
    lines.append(f"routes_considered: {len(list(route_results or []))}")
    lines.append(f"top_n: {len(ranked)}")
    lines.append("")
    if not ranked:
        lines.append("Keine Routen mit Picks gefunden.")
    for idx, r in enumerate(ranked, start=1):
        profit = float(r.get("profit_total", 0.0) or 0.0)
        isk_used = float(r.get("isk_used", 0.0) or 0.0)
        m3_used = float(r.get("m3_used", 0.0) or 0.0)
        top3_ratio, top5_ratio, dominant = _profit_dominance(r)
        lines.append(f"{idx}. Route {r.get('route_label', '')}")
        lines.append(f"   Start: {r.get('source_label', '')}")
        lines.append(f"   Ziel: {r.get('dest_label', '')}")
        lines.append(f"   provider: {str(r.get('shipping_provider', '') or '')}")
        cost_model_confidence = str(r.get("cost_model_confidence", "normal") or "normal")
        if cost_model_confidence != "normal":
            lines.append(f"   transport_cost_confidence: {cost_model_confidence}")
            warn_msg = str(r.get("cost_model_warning", "") or "")
            if warn_msg:
                lines.append(f"   transport_cost_warning: {warn_msg}")
        lines.append(f"   Total Cost: {fmt_isk_de(isk_used)}")
        lines.append(f"   Total Net Revenue: {fmt_isk_de(float(r.get('net_revenue_total', 0.0) or 0.0))}")
        lines.append(f"   Total Expected Net Profit: {fmt_isk_de(profit)}")
        lines.append(f"   Total Fees and Taxes: {fmt_isk_de(float(r.get('total_fees_taxes', 0.0) or 0.0))}")
        lines.append(f"   Total Route Costs: {fmt_isk_de(float(r.get('total_route_cost', 0.0) or 0.0))}")
        lines.append(f"   Total Shipping Cost: {fmt_isk_de(float(r.get('shipping_cost_total', 0.0) or 0.0))}")
        lines.append(f"   Profit per m3: {profit / max(1e-9, m3_used):.2f} ISK/m3")
        lines.append(f"   Profit per ISK: {profit / max(1e-9, isk_used):.6f}")
        lines.append(f"   Gesamt m3: {m3_used:.2f}")
        lines.append(f"   Picks Count: {int(r.get('items_count', 0) or 0)}")
        lines.append(f"   Budget Usage: {float(r.get('budget_util_pct', 0.0) or 0.0):.2f}%")
        lines.append(f"   Cargo Usage: {float(r.get('cargo_util_pct', 0.0) or 0.0):.2f}%")
        lines.append(f"   Top3 Profit Share: {top3_ratio*100.0:.2f}%")
        lines.append(f"   Top5 Profit Share: {top5_ratio*100.0:.2f}%")
        lines.append(f"   Dominance Flag (>60%): {'YES' if dominant else 'NO'}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
