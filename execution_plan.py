from explainability import (
    build_rejected_candidate_table,
    ensure_record_explainability,
    format_reason_digest,
)
from route_search import route_ranking_value, summarize_route_for_ranking


def _route_ranking_value(route: dict, metric: str) -> float:
    return float(route_ranking_value(route, metric))


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


def _append_reason_lines(lines: list[str], indent: str, reasons: list[dict], label: str, *, detail_mode: bool) -> None:
    if not reasons:
        return
    if not detail_mode:
        digest = format_reason_digest(reasons)
        if digest:
            lines.append(f"{indent}{label}: {digest}")
        return
    lines.append(f"{indent}{label}:")
    for reason in reasons:
        lines.append(f"{indent}- {reason.get('code', '')}: {reason.get('text', '')}")


def _detail_max_liq_days(leg: dict) -> float:
    filters_used = leg.get("filters_used", {}) if isinstance(leg.get("filters_used", {}), dict) else {}
    return float(filters_used.get("max_expected_days_to_sell", 90.0) or 90.0)


def write_execution_plan_profiles(path: str, timestamp: str, route_results: list[dict], detail_mode: bool = False) -> None:
    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("EXECUTION PLAN (ROUTE PROFILES)")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    plan_id = ""
    for leg in list(route_results or []):
        plan_id = str(leg.get("plan_id", "") or "").strip()
        if plan_id:
            break
    if plan_id:
        lines.append(f"Plan ID: {plan_id}")
    lines.append("")

    total_cost = 0.0
    total_revenue = 0.0
    total_profit = 0.0
    total_fees_taxes = 0.0
    total_shipping_cost = 0.0
    total_route_costs = 0.0

    for idx, leg in enumerate(route_results, start=1):
        picks = list(leg.get("picks", []) or [])
        route_summary = summarize_route_for_ranking(leg)
        actionable = bool(route_summary.get("actionable", False))
        plan_title = f"PLAN {idx}: {leg.get('route_label', '')}"
        if not actionable:
            plan_title += " [NOT ACTIONABLE]"
        lines.append(plan_title)
        lines.append("-" * max(8, len(lines[-1])))
        route_id = str(leg.get("route_id", leg.get("route_tag", "")) or "")
        if route_id:
            lines.append(f"Route ID: {route_id}")
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
        route_prune_reason = str(leg.get("route_prune_reason", route_summary.get("route_prune_reason", "")) or "")
        if route_prune_reason:
            lines.append(f"route_prune_reason: {route_prune_reason}")
        leg_cost = float(leg.get("isk_used", 0.0))
        leg_revenue = sum(float(p.get("revenue_net", 0.0)) for p in picks)
        leg_profit = float(route_summary.get("total_expected_realized_profit", leg.get("profit_total", 0.0)))
        leg_full_sell_profit = float(route_summary.get("total_full_sell_profit", leg.get("profit_total", 0.0)))
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
        lines.append(f"Total Expected Realized Profit: {fmt_isk_de(leg_profit)}")
        lines.append(f"Total Full Sell Profit: {fmt_isk_de(leg_full_sell_profit)}")
        lines.append(f"route_confidence: {float(route_summary.get('route_confidence', 0.0)):.2f}")
        lines.append(f"raw_route_confidence: {float(route_summary.get('raw_route_confidence', route_summary.get('route_confidence', 0.0))):.2f}")
        lines.append(f"calibrated_route_confidence: {float(route_summary.get('calibrated_route_confidence', route_summary.get('route_confidence', 0.0))):.2f}")
        lines.append(f"transport_confidence: {float(route_summary.get('transport_confidence', 0.0)):.2f}")
        lines.append(f"raw_transport_confidence: {float(route_summary.get('raw_transport_confidence', route_summary.get('transport_confidence', 0.0))):.2f}")
        lines.append(f"calibrated_transport_confidence: {float(route_summary.get('calibrated_transport_confidence', route_summary.get('transport_confidence', 0.0))):.2f}")
        lines.append(f"capital_lock_risk: {float(route_summary.get('capital_lock_risk', 0.0)):.2f}")
        calibration_warning = str(route_summary.get("calibration_warning", leg.get("calibration_warning", "")) or "")
        if calibration_warning:
            lines.append(f"calibration_warning: {calibration_warning}")
        _append_reason_lines(lines, "", list(route_summary.get("positive_reasons", []) or []), "route_positive_reasons", detail_mode=detail_mode)
        _append_reason_lines(lines, "", list(route_summary.get("negative_reasons", []) or []), "route_negative_reasons", detail_mode=detail_mode)
        _append_reason_lines(lines, "", list(route_summary.get("warnings", []) or []), "route_warnings", detail_mode=detail_mode)
        if detail_mode:
            pruned_reason = route_summary.get("pruned_reason")
            if isinstance(pruned_reason, dict) and pruned_reason:
                lines.append(f"route_pruned_reason: {pruned_reason.get('code', '')} - {pruned_reason.get('text', '')}")
            lines.append("route_score_breakdown:")
            for contributor in list(route_summary.get("score_contributors", []) or []):
                lines.append(
                    f"- {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.2f} "
                    f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                )
            lines.append("route_confidence_breakdown:")
            for contributor in list(route_summary.get("confidence_contributors", []) or []):
                lines.append(
                    f"- {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.4f} "
                    f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                )
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
            ensure_record_explainability(p, max_liq_days=_detail_max_liq_days(leg))
            qty = int(p.get("qty", 0))
            buy_avg = float(p.get("buy_avg", 0.0))
            buy_total = buy_avg * qty
            sell_unit = float(p.get("target_sell_price", 0.0) or p.get("sell_avg", 0.0))
            sell_total = sell_unit * qty
            duration = int(float(p.get("order_duration_days", 0) or 0))
            is_instant = bool(p.get("instant", False)) or str(p.get("mode", "")).lower() == "instant"
            exit_type = str(p.get("exit_type", "instant" if is_instant else "speculative") or "speculative")
            exp_days = float(p.get("expected_days_to_sell", 0.0) or 0.0)
            fill_prob = float(p.get("fill_probability", 0.0) or 0.0) * 100.0
            profit = float(p.get("expected_realized_profit_90d", p.get("expected_profit_90d", p.get("profit", 0.0))) or 0.0)
            full_sell_profit = float(p.get("gross_profit_if_full_sell", p.get("profit", 0.0)) or 0.0)
            pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(qty)
            unit_m3 = float(p.get("unit_volume", 0.0) or 0.0)
            lines.append(f"{p_i}. {p.get('name', '')} (type_id {int(p.get('type_id', 0))})")
            pick_id = str(p.get("pick_id", p.get("journal_entry_id", "")) or "")
            if pick_id:
                lines.append(f"   Pick ID: {pick_id}")
            lines.append(f"   Exit Type: {exit_type}")
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
            lines.append(f"   Expected Realized Profit: {fmt_isk_de(profit)}")
            lines.append(f"   Full Sell Profit: {fmt_isk_de(full_sell_profit)}")
            lines.append(f"   Expected Units Sold: {float(p.get('expected_units_sold_90d', 0.0) or 0.0):.2f}")
            lines.append(f"   Expected Units Unsold: {float(p.get('expected_units_unsold_90d', 0.0) or 0.0):.2f}")
            lines.append(f"   liquidity_confidence: {float(p.get('liquidity_confidence', p.get('fill_probability', 0.0)) or 0.0):.2f}")
            lines.append(f"   transport_cost_model: {str(p.get('transport_cost_confidence', leg.get('cost_model_confidence', 'normal')) or 'normal')}")
            lines.append(f"   raw_transport_confidence: {float(p.get('raw_transport_confidence', route_summary.get('raw_transport_confidence', route_summary.get('transport_confidence', 0.0))) or 0.0):.2f}")
            lines.append(f"   calibrated_transport_confidence: {float(p.get('calibrated_transport_confidence', route_summary.get('calibrated_transport_confidence', route_summary.get('transport_confidence', 0.0))) or 0.0):.2f}")
            lines.append(f"   overall_confidence: {float(p.get('overall_confidence', p.get('strict_confidence_score', p.get('fill_probability', 0.0))) or 0.0):.2f}")
            lines.append(f"   raw_confidence: {float(p.get('raw_confidence', p.get('raw_overall_confidence', p.get('overall_confidence', 0.0))) or 0.0):.2f}")
            lines.append(f"   calibrated_confidence: {float(p.get('calibrated_confidence', p.get('calibrated_overall_confidence', p.get('overall_confidence', 0.0))) or 0.0):.2f}")
            lines.append(f"   market_plausibility_score: {float(p.get('market_plausibility_score', 1.0) or 1.0):.2f}")
            lines.append(f"   manipulation_risk_score: {float(p.get('manipulation_risk_score', 0.0) or 0.0):.2f}")
            lines.append(f"   profit_at_top_of_book: {fmt_isk_de(float(p.get('profit_at_top_of_book', p.get('profit', 0.0)) or 0.0))}")
            lines.append(
                f"   profit_at_conservative_executable_price: "
                f"{fmt_isk_de(float(p.get('profit_at_conservative_executable_price', p.get('expected_realized_profit_90d', p.get('profit', 0.0))) or 0.0))}"
            )
            pick_warning = str(p.get("calibration_warning", "") or "")
            if pick_warning:
                lines.append(f"   calibration_warning: {pick_warning}")
            _append_reason_lines(lines, "   ", list(p.get("positive_reasons", []) or []), "positive_reasons", detail_mode=detail_mode)
            _append_reason_lines(lines, "   ", list(p.get("negative_reasons", []) or []), "negative_reasons", detail_mode=detail_mode)
            _append_reason_lines(lines, "   ", list(p.get("warnings", []) or []), "warnings", detail_mode=detail_mode)
            if detail_mode:
                pruned_reason = p.get("pruned_reason")
                if isinstance(pruned_reason, dict) and pruned_reason:
                    lines.append(f"   pruned_reason: {pruned_reason.get('code', '')} - {pruned_reason.get('text', '')}")
                lines.append("   score_breakdown:")
                for contributor in list(p.get("score_contributors", []) or []):
                    lines.append(
                        f"   - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.2f} "
                        f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                    )
                lines.append("   confidence_breakdown:")
                for contributor in list(p.get("confidence_contributors", []) or []):
                    lines.append(
                        f"   - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.4f} "
                        f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                    )
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
            lines.append("Keine Picks fuer diese Route. Route ist nicht actionable.")
            lines.append("")
        elif detail_mode:
            rejected = list(leg.get("top_rejected_candidates", []) or build_rejected_candidate_table(leg.get("explain")))
            if rejected:
                lines.append("Top Rejected Candidates:")
                for entry in rejected[:10]:
                    lines.append(
                        f"- {entry.get('name', '')} (type_id {int(entry.get('type_id', 0))}) "
                        f"| reason={entry.get('reason_code', '')} | proxy={fmt_isk_de(float(entry.get('nominal_profit_proxy', 0.0)))} "
                        f"| {entry.get('reason_text', '')}"
                    )
                lines.append("")

    lines.append("=" * 70)
    lines.append(f"TOTAL COST: {fmt_isk_de(total_cost)}")
    lines.append(f"TOTAL NET REVENUE: {fmt_isk_de(total_revenue)}")
    lines.append(f"TOTAL EXPECTED REALIZED PROFIT: {fmt_isk_de(total_profit)}")
    lines.append(f"TOTAL FEES AND TAXES: {fmt_isk_de(total_fees_taxes)}")
    if total_shipping_cost > 0.0:
        lines.append(f"TOTAL SHIPPING COST: {fmt_isk_de(total_shipping_cost)}")
        lines.append(f"shipping_cost_total: {fmt_isk_de(total_shipping_cost)}")
    lines.append(f"TOTAL ROUTE COSTS: {fmt_isk_de(total_route_costs)}")
    lines.append("=" * 70)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_route_leaderboard(path: str, timestamp: str, route_results: list[dict], ranking_metric: str, max_routes: int, detail_mode: bool = False) -> None:
    metric = str(ranking_metric or "risk_adjusted_expected_profit").strip().lower()
    route_summaries = [(r, summarize_route_for_ranking(r)) for r in list(route_results or [])]
    actionable = [entry for entry in route_summaries if bool(entry[1].get("actionable", False))]
    pruned = [entry for entry in route_summaries if not bool(entry[1].get("actionable", False))]
    ranked = sorted(
        actionable,
        key=lambda entry: (
            _route_ranking_value(entry[0], metric),
            float(entry[1].get("total_expected_realized_profit", 0.0)),
        ),
        reverse=True,
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
    lines.append(f"actionable_routes: {len(actionable)}")
    lines.append(f"pruned_routes: {len(pruned)}")
    lines.append(f"top_n: {len(ranked)}")
    lines.append("")
    if not ranked:
        lines.append("Keine Routen mit Picks gefunden.")
    for idx, (r, summary) in enumerate(ranked, start=1):
        profit = float(summary.get("total_expected_realized_profit", 0.0) or 0.0)
        full_sell_profit = float(summary.get("total_full_sell_profit", r.get("profit_total", 0.0)) or 0.0)
        isk_used = float(r.get("isk_used", 0.0) or 0.0)
        m3_used = float(r.get("m3_used", 0.0) or 0.0)
        top3_ratio, top5_ratio, dominant = _profit_dominance(r)
        lines.append(f"{idx}. Route {r.get('route_label', '')}")
        lines.append(f"   Start: {r.get('source_label', '')}")
        lines.append(f"   Ziel: {r.get('dest_label', '')}")
        lines.append(f"   provider: {str(r.get('shipping_provider', '') or '')}")
        lines.append(f"   route_confidence: {float(summary.get('route_confidence', 0.0)):.2f}")
        lines.append(f"   raw_route_confidence: {float(summary.get('raw_route_confidence', summary.get('route_confidence', 0.0))):.2f}")
        lines.append(f"   calibrated_route_confidence: {float(summary.get('calibrated_route_confidence', summary.get('route_confidence', 0.0))):.2f}")
        lines.append(f"   transport_confidence: {float(summary.get('transport_confidence', 0.0)):.2f}")
        lines.append(f"   raw_transport_confidence: {float(summary.get('raw_transport_confidence', summary.get('transport_confidence', 0.0))):.2f}")
        lines.append(f"   calibrated_transport_confidence: {float(summary.get('calibrated_transport_confidence', summary.get('transport_confidence', 0.0))):.2f}")
        lines.append(f"   capital_lock_risk: {float(summary.get('capital_lock_risk', 0.0)):.2f}")
        calibration_warning = str(summary.get("calibration_warning", r.get("calibration_warning", "")) or "")
        if calibration_warning:
            lines.append(f"   calibration_warning: {calibration_warning}")
        _append_reason_lines(lines, "   ", list(summary.get("positive_reasons", []) or []), "positive_reasons", detail_mode=detail_mode)
        _append_reason_lines(lines, "   ", list(summary.get("negative_reasons", []) or []), "negative_reasons", detail_mode=detail_mode)
        _append_reason_lines(lines, "   ", list(summary.get("warnings", []) or []), "warnings", detail_mode=detail_mode)
        cost_model_confidence = str(r.get("cost_model_confidence", "normal") or "normal")
        if cost_model_confidence != "normal":
            lines.append(f"   transport_cost_confidence: {cost_model_confidence}")
            warn_msg = str(r.get("cost_model_warning", "") or "")
            if warn_msg:
                lines.append(f"   transport_cost_warning: {warn_msg}")
        lines.append(f"   Total Cost: {fmt_isk_de(isk_used)}")
        lines.append(f"   Total Net Revenue: {fmt_isk_de(float(r.get('net_revenue_total', 0.0) or 0.0))}")
        lines.append(f"   Total Expected Realized Profit: {fmt_isk_de(profit)}")
        lines.append(f"   Total Full Sell Profit: {fmt_isk_de(full_sell_profit)}")
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
        if detail_mode:
            lines.append("   score_breakdown:")
            for contributor in list(summary.get("score_contributors", []) or []):
                lines.append(
                    f"   - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.2f} "
                    f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                )
            lines.append("   confidence_breakdown:")
            for contributor in list(summary.get("confidence_contributors", []) or []):
                lines.append(
                    f"   - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.4f} "
                    f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                )
        lines.append("")
    if pruned:
        lines.append("PRUNED / NOT ACTIONABLE")
        lines.append("-" * 24)
        for r, summary in pruned:
            reason = str(summary.get("route_prune_reason", r.get("route_prune_reason", "no_picks")) or "no_picks")
            reason_code = ""
            pruned_reason = summary.get("pruned_reason")
            if isinstance(pruned_reason, dict):
                reason_code = str(pruned_reason.get("code", "") or "")
            suffix = f" [{reason_code}]" if reason_code else ""
            lines.append(f"- {r.get('route_label', '')}: {reason}{suffix}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
