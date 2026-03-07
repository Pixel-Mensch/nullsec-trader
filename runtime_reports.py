from __future__ import annotations

import json

from explainability import build_rejected_candidate_table, ensure_record_explainability, format_reason_digest
from models import FilterFunnel, TradeCandidate
from route_search import summarize_route_for_ranking


def fmt_isk(x: float) -> str:
    x = float(x)
    if x >= 1_000_000_000:
        return f"{x/1_000_000_000:.2f}b"
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}m"
    if x >= 1_000:
        return f"{x/1_000:.2f}k"
    return f"{x:.0f}"


def _fmt_isk_de(x: float) -> str:
    s = f"{float(x):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} ISK"


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


def pick_total_fees_taxes(pick: dict) -> float:
    f = _pick_fee_components(pick)
    return (
        float(f["buy_broker_fee_isk"])
        + float(f["broker_fee_isk"])
        + float(f["sales_tax_isk"])
        + float(f["scc_surcharge_isk"])
        + float(f["relist_fee_isk"])
    )


def write_csv(path: str, picks: list[dict]) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = [
            "type_id",
            "name",
            "ingame_search",
            "qty",
            "unit_volume_m3",
            "buy_avg_price",
            "sell_avg_price",
            "cost",
            "revenue_net",
            "profit",
            "profit_pct",
            "buy_broker_fee_total",
            "sell_broker_fee_total",
            "sales_tax_total",
            "scc_surcharge_total",
            "relist_budget_total",
            "sales_tax_isk",
            "broker_fee_isk",
            "scc_surcharge_isk",
            "relist_fee_isk",
            "shipping_cost",
            "route_cost",
            "transport_cost",
            "instant",
            "exit_type",
            "suggested_sell_price",
            "order_duration_days",
            "profit_per_m3",
            "profit_per_m3_per_day",
            "turnover_factor",
            "dest_buy_depth_units",
            "instant_fill_ratio",
            "fill_probability",
            "competition_price_levels_near_best",
            "queue_ahead_units",
            "daily_volume",
            "history_volume_30d",
            "liquidity_score",
            "mode",
            "target_sell_price",
            "avg_daily_volume_30d",
            "avg_daily_volume_7d",
            "expected_days_to_sell",
            "sell_through_ratio_90d",
            "risk_score",
            "expected_profit_90d",
            "expected_profit_per_m3_90d",
            "gross_profit_if_full_sell",
            "expected_units_sold_90d",
            "expected_units_unsold_90d",
            "expected_realized_profit_90d",
            "expected_realized_profit_per_m3_90d",
            "exit_confidence",
            "liquidity_confidence",
            "raw_transport_confidence",
            "calibrated_transport_confidence",
            "overall_confidence",
            "raw_confidence",
            "calibrated_confidence",
            "decision_overall_confidence",
            "calibration_warning",
            "market_plausibility_score",
            "manipulation_risk_score",
            "profit_at_top_of_book",
            "profit_at_usable_depth",
            "profit_at_conservative_executable_price",
            "used_volume_fallback",
            "reference_price",
            "reference_price_source",
            "reference_price_average",
            "reference_price_adjusted",
            "jita_split_price",
            "buy_discount_vs_ref",
            "sell_markup_vs_ref",
            "reference_price_penalty",
            "strict_confidence_score",
            "strict_mode_enabled",
            "buy_at",
            "sell_at",
            "route_hops",
            "carried_through_legs",
            "route_src_index",
            "route_dst_index",
            "extra_leg_penalty",
            "route_wide_selected",
            "route_adjusted_score",
            "estimated_transport_cost",
            "transport_confidence",
            "release_leg_index",
        ]
        w.writerow(header)
        for p in picks:
            search_name = str(p.get("name", "")).replace("â€™", "'").replace('"', "")
            expected_realized = float(p.get("expected_realized_profit_90d", p.get("expected_profit_90d", 0.0)) or 0.0)
            expected_realized_density = float(
                p.get("expected_realized_profit_per_m3_90d", p.get("expected_profit_per_m3_90d", 0.0)) or 0.0
            )
            row = [
                p["type_id"],
                p["name"],
                search_name,
                p["qty"],
                f'{p["unit_volume"]:.4f}',
                f'{p["buy_avg"]:.2f}',
                f'{p["sell_avg"]:.2f}',
                f'{p["cost"]:.2f}',
                f'{p["revenue_net"]:.2f}',
                f'{p["profit"]:.2f}',
                f'{p["profit_pct"]:.4f}',
                f'{float(p.get("buy_broker_fee_total", 0.0)):.2f}',
                f'{float(p.get("sell_broker_fee_total", 0.0)):.2f}',
                f'{float(p.get("sales_tax_total", 0.0)):.2f}',
                f'{float(p.get("scc_surcharge_total", p.get("scc_surcharge_isk", 0.0))):.2f}',
                f'{float(p.get("relist_budget_total", 0.0)):.2f}',
                f'{float(p.get("sales_tax_isk", p.get("sales_tax_total", 0.0))):.2f}',
                f'{float(p.get("broker_fee_isk", p.get("sell_broker_fee_total", 0.0))):.2f}',
                f'{float(p.get("scc_surcharge_isk", p.get("scc_surcharge_total", 0.0))):.2f}',
                f'{float(p.get("relist_fee_isk", p.get("relist_budget_total", 0.0))):.2f}',
                f'{float(p.get("shipping_cost", 0.0)):.2f}',
                f'{float(p.get("route_cost", 0.0)):.2f}',
                f'{float(p.get("transport_cost", 0.0)):.2f}',
                p.get("instant", True),
                str(p.get("exit_type", "instant" if p.get("instant", False) else "planned")),
                f'{p.get("suggested_sell_price", "")}',
                p.get("order_duration_days", ""),
                f'{float(p.get("profit_per_m3", 0.0)):.4f}',
                f'{float(p.get("profit_per_m3_per_day", 0.0)):.4f}',
                f'{float(p.get("turnover_factor", 0.0)):.4f}',
                int(p.get("dest_buy_depth_units", 0)),
                f'{float(p.get("instant_fill_ratio", 1.0)):.4f}',
                f'{float(p.get("fill_probability", 0.0)):.4f}',
                int(p.get("competition_price_levels_near_best", 0)),
                int(p.get("queue_ahead_units", 0)),
                f'{float(p.get("daily_volume", 0.0)):.2f}',
                int(p.get("history_volume_30d", 0)),
                int(p.get("liquidity_score", 0)),
                p.get("mode", "instant"),
                f'{float(p.get("target_sell_price", 0.0)):.2f}',
                f'{float(p.get("avg_daily_volume_30d", 0.0)):.4f}',
                f'{float(p.get("avg_daily_volume_7d", 0.0)):.4f}',
                f'{float(p.get("expected_days_to_sell", 0.0)):.4f}',
                f'{float(p.get("sell_through_ratio_90d", 0.0)):.4f}',
                f'{float(p.get("risk_score", 0.0)):.4f}',
                f"{expected_realized:.2f}",
                f"{expected_realized_density:.4f}",
                f'{float(p.get("gross_profit_if_full_sell", p.get("profit", 0.0))):.2f}',
                f'{float(p.get("expected_units_sold_90d", p.get("qty", 0))):.4f}',
                f'{float(p.get("expected_units_unsold_90d", 0.0)):.4f}',
                f"{expected_realized:.2f}",
                f"{expected_realized_density:.4f}",
                f'{float(p.get("exit_confidence", p.get("strict_confidence_score", 0.0))):.4f}',
                f'{float(p.get("liquidity_confidence", 0.0)):.4f}',
                f'{float(p.get("raw_transport_confidence", p.get("transport_confidence", 1.0))):.4f}',
                f'{float(p.get("calibrated_transport_confidence", p.get("raw_transport_confidence", p.get("transport_confidence", 1.0)))):.4f}',
                f'{float(p.get("overall_confidence", p.get("strict_confidence_score", 0.0))):.4f}',
                f'{float(p.get("raw_confidence", p.get("raw_overall_confidence", p.get("overall_confidence", 0.0)))):.4f}',
                f'{float(p.get("calibrated_confidence", p.get("calibrated_overall_confidence", p.get("overall_confidence", 0.0)))):.4f}',
                f'{float(p.get("decision_overall_confidence", p.get("calibrated_confidence", p.get("overall_confidence", 0.0)))):.4f}',
                str(p.get("calibration_warning", "")),
                f'{float(p.get("market_plausibility_score", 1.0)):.4f}',
                f'{float(p.get("manipulation_risk_score", 0.0)):.4f}',
                f'{float(p.get("profit_at_top_of_book", p.get("profit", 0.0))):.2f}',
                f'{float(p.get("profit_at_usable_depth", p.get("expected_realized_profit_90d", p.get("profit", 0.0)))):.2f}',
                f'{float(p.get("profit_at_conservative_executable_price", p.get("expected_realized_profit_90d", p.get("profit", 0.0)))):.2f}',
                bool(p.get("used_volume_fallback", False)),
                f'{float(p.get("reference_price", 0.0)):.2f}',
                str(p.get("reference_price_source", "")),
                f'{float(p.get("reference_price_average", 0.0)):.2f}',
                f'{float(p.get("reference_price_adjusted", 0.0)):.2f}',
                f'{float(p.get("jita_split_price", 0.0)):.2f}',
                f'{float(p.get("buy_discount_vs_ref", 0.0)):.4f}',
                f'{float(p.get("sell_markup_vs_ref", 0.0)):.4f}',
                f'{float(p.get("reference_price_penalty", 0.0)):.4f}',
                f'{float(p.get("strict_confidence_score", 0.0)):.4f}',
                bool(p.get("strict_mode_enabled", False)),
                str(p.get("buy_at", "")),
                str(p.get("sell_at", "")),
                int(p.get("route_hops", 1)),
                int(p.get("carried_through_legs", p.get("route_hops", 1))),
                int(p.get("route_src_index", 0)),
                int(p.get("route_dst_index", 0)),
                f'{float(p.get("extra_leg_penalty", 0.0)):.4f}',
                bool(p.get("route_wide_selected", False)),
                f'{float(p.get("route_adjusted_score", 0.0)):.6f}',
                f'{float(p.get("estimated_transport_cost", p.get("transport_cost", 0.0))):.2f}',
                str(p.get("transport_confidence", "")),
                int(p.get("release_leg_index", -1)),
            ]
            assert len(header) == len(row), f"CSV mismatch: {len(header)} vs {len(row)}"
            w.writerow(row)


def write_top_candidate_dump(path: str, candidates: list[TradeCandidate], label: str, filters_used: dict, explain: dict | None = None) -> None:
    from datetime import datetime

    lines = []
    lines.append(f"CANDIDATE DIAGNOSTICS - {label}")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Route: {label}")
    lines.append(f"Mode: {str(filters_used.get('mode', 'instant')).lower()}")
    lines.append(f"strict_mode_enabled: {bool(filters_used.get('strict_mode_enabled', False))}")
    lines.append(f"ranking_metric: {str(filters_used.get('ranking_metric', 'profit_per_m3_per_day')).lower()}")
    lines.append(f"Total candidates: {len(candidates)}")
    lines.append("Filters:")
    lines.append(json.dumps(filters_used, ensure_ascii=False, sort_keys=True))
    lines.append("")

    def section(title: str, ranked: list[TradeCandidate]) -> None:
        lines.append(title)
        lines.append("-" * len(title))
        for c in ranked[:10]:
            ensure_record_explainability(c, max_liq_days=float(filters_used.get("max_expected_days_to_sell", 90.0) or 90.0))
            display_name = getattr(c, "name", f"type_{getattr(c, 'type_id', 0)}")
            full_sell = float(getattr(c, "gross_profit_if_full_sell", getattr(c, "profit_per_unit", 0.0) * getattr(c, "max_units", 0)))
            expected_realized = float(getattr(c, "expected_realized_profit_90d", getattr(c, "expected_profit_90d", 0.0)))
            lines.append(
                f"{display_name} (type_id {c.type_id}) | full_sell={fmt_isk(full_sell)} "
                f"| expected_realized={fmt_isk(expected_realized)} | profit_pct={c.profit_pct*100:.2f}% "
                f"| isk_per_m3={c.profit_per_m3:.2f} | exp_days={float(getattr(c, 'expected_days_to_sell', 0.0)):.1f} "
                f"| exit_conf={float(getattr(c, 'exit_confidence', 0.0)):.3f} "
                f"| liq_conf={float(getattr(c, 'liquidity_confidence', 0.0)):.3f} "
                f"| raw={float(getattr(c, 'raw_confidence', getattr(c, 'overall_confidence', getattr(c, 'strict_confidence_score', 0.0)))):.3f} "
                f"| calibrated={float(getattr(c, 'calibrated_confidence', getattr(c, 'raw_confidence', getattr(c, 'overall_confidence', getattr(c, 'strict_confidence_score', 0.0))))):.3f} "
                f"| plaus={float(getattr(c, 'market_plausibility_score', 1.0)):.3f} "
                f"| manip={float(getattr(c, 'manipulation_risk_score', 0.0)):.3f} "
                f"| queue={int(getattr(c, 'queue_ahead_units', 0))} | buy_at={getattr(c, 'route_src_label', '')} "
                f"| sell_at={getattr(c, 'route_dst_label', '')}"
            )
            pos_digest = format_reason_digest(list(getattr(c, "positive_reasons", []) or []), limit=3)
            neg_digest = format_reason_digest(list(getattr(c, "negative_reasons", []) or []), limit=3)
            warn_digest = format_reason_digest(list(getattr(c, "warnings", []) or []), limit=2)
            if pos_digest:
                lines.append(f"  positive: {pos_digest}")
            if neg_digest:
                lines.append(f"  negative: {neg_digest}")
            if warn_digest:
                lines.append(f"  warnings: {warn_digest}")
        lines.append("")

    section("Top 10 by Expected Realized Profit", sorted(candidates, key=lambda c: float(getattr(c, "expected_realized_profit_90d", 0.0)), reverse=True))
    section("Top 10 by Full Sell Profit", sorted(candidates, key=lambda c: float(getattr(c, "gross_profit_if_full_sell", 0.0)), reverse=True))
    section("Top 10 by Expected Profit per m3", sorted(candidates, key=lambda c: float(getattr(c, "expected_realized_profit_per_m3_90d", 0.0)), reverse=True))
    if explain:
        lines.append("WHY_OUT Summary")
        lines.append("-" * len("WHY_OUT Summary"))
        reason_counts = explain.get("reason_counts", {})
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
            lines.append(f"{reason}: {count}")
        lines.append("")
        rejected = build_rejected_candidate_table(explain, limit=10)
        if rejected:
            lines.append("Top 10 Rejected by Nominal Profit Proxy")
            lines.append("-" * len("Top 10 Rejected by Nominal Profit Proxy"))
            for entry in rejected:
                lines.append(
                    f"{entry.get('name', '')} (type_id {int(entry.get('type_id', 0))}) | "
                    f"proxy={fmt_isk(entry.get('nominal_profit_proxy', 0.0))} | "
                    f"{entry.get('reason_code', '')} | {entry.get('reason_text', '')}"
                )
            lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_enhanced_summary(
    path: str,
    forward_picks: list[dict],
    forward_cost: float,
    forward_profit: float,
    return_picks: list[dict],
    return_cost: float,
    return_profit: float,
    cargo_m3: float,
    budget_isk: float,
    forward_funnel: FilterFunnel = None,
    return_funnel: FilterFunnel = None,
    run_uuid: str = "",
) -> None:
    from datetime import datetime

    lines = []
    lines.append("=" * 70)
    lines.append("ROUNDTRIP TRADING PLAN - ENHANCED REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if run_uuid:
        lines.append(f"Run UUID: {run_uuid}")
    lines.append("")
    lines.append("PARAMETERS:")
    lines.append(f"  Cargo available: {cargo_m3:.2f} m3")
    lines.append(f"  Trading budget: {fmt_isk(budget_isk)}")
    lines.append("")
    lines.append("FORWARD ROUTE (O4T -> CJ6):")
    lines.append(f"  Selected items: {len(forward_picks)}")
    lines.append(f"  Total cost: {fmt_isk(forward_cost)}")
    lines.append(f"  Total profit: {fmt_isk(forward_profit)}")
    if forward_picks:
        lines.append("  Top 5 picks:")
        for p in forward_picks[:5]:
            lines.append(f"    - {p['name']} x{p['qty']}: {fmt_isk(p['profit'])} profit")
    lines.append("")
    if forward_funnel:
        lines.extend(forward_funnel.get_summary_lines())
    lines.append("RETURN ROUTE (CJ6 -> O4T):")
    lines.append(f"  Selected items: {len(return_picks)}")
    lines.append(f"  Total cost: {fmt_isk(return_cost)}")
    lines.append(f"  Total profit: {fmt_isk(return_profit)}")
    if return_picks:
        lines.append("  Top 5 picks:")
        for p in return_picks[:5]:
            lines.append(f"    - {p['name']} x{p['qty']}: {fmt_isk(p['profit'])} profit")
    lines.append("")
    if return_funnel:
        lines.extend(return_funnel.get_summary_lines())
    lines.append("=" * 70)
    lines.append(f"TOTAL PROFIT: {fmt_isk(forward_profit + return_profit)}")
    lines.append(
        f"Total margin: {((forward_profit + return_profit) / (forward_cost + return_cost) * 100) if (forward_cost + return_cost) > 0 else 0:.2f}%"
    )
    lines.append("=" * 70)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_chain_summary(path: str, chain_label: str, timestamp: str, leg_results: list[dict]) -> None:
    def fmt_isk_exact(x: float) -> str:
        return f"{float(x):,.2f} ISK"

    def format_trade_instruction(leg: dict, pick: dict, idx: int) -> list[str]:
        src = str(pick.get("buy_at") or leg.get("source_label", "SOURCE"))
        dst = str(pick.get("sell_at") or leg.get("dest_label", "DEST"))
        qty = int(pick.get("qty", 0))
        buy_unit = float(pick.get("buy_avg", 0.0))
        sell_unit = float(pick.get("target_sell_price", 0.0) or pick.get("sell_avg", 0.0))
        buy_total = buy_unit * qty
        sell_total = sell_unit * qty
        instant = bool(pick.get("instant", True))
        duration_days = int(float(pick.get("order_duration_days", 0) or 0))
        expected_days = float(pick.get("expected_days_to_sell", 0.0) or 0.0)
        fill_prob = float(pick.get("fill_probability", 0.0) or 0.0)
        profit = float(pick.get("profit", 0.0) or 0.0)
        pick_m3 = float(pick.get("unit_volume", 0.0) or 0.0) * float(qty)
        route_hops = int(pick.get("route_hops", 1))
        lines_local = [f"  {idx}. {pick.get('name', '')} (type_id {pick.get('type_id', 0)})"]
        lines_local.append(
            f"     BUY  in {src}: qty={qty} @ {fmt_isk_exact(buy_unit)} pro Stk "
            f"(Gesamt {fmt_isk_exact(buy_total)})"
        )
        if instant:
            lines_local.append(
                f"     SELL in {dst}: SOFORTVERKAUF/Buy-Order @ {fmt_isk_exact(sell_unit)} pro Stk "
                f"(Gesamt {fmt_isk_exact(sell_total)})"
            )
        else:
            lines_local.append(
                f"     SELL in {dst}: SELL-ORDER @ {fmt_isk_exact(sell_unit)} pro Stk "
                f"(Gesamt {fmt_isk_exact(sell_total)}) | Laufzeit: {duration_days}d"
            )
            lines_local.append(
                f"     Erwartete Verkaufsdauer: {expected_days:.1f}d | Fill-Wahrscheinlichkeit: {fill_prob*100:.1f}%"
            )
        lines_local.append(f"     Erwarteter Profit: {fmt_isk_exact(profit)}")
        lines_local.append(f"     Cargo fuer diesen Pick: {pick_m3:.2f} m3")
        lines_local.append(f"     Route-Hops: {route_hops}")
        return lines_local

    lines = ["=" * 70, f"{chain_label.upper()} CHAIN SUMMARY", "=" * 70, f"Timestamp: {timestamp}", ""]
    if not leg_results:
        lines.append("Keine Legs ausgefuehrt.")
        lines.append("")
    for leg in leg_results:
        lines.append(f"Route: {leg['route_label']}")
        lines.append(f"leg_disabled: {bool(leg.get('leg_disabled', False))} ({leg.get('leg_disabled_reason', '')})")
        lines.append(f"Mode: {leg['mode']} (selected: {leg['selected_mode']})")
        lines.append(f"strict_mode_enabled: {bool(leg['filters_used'].get('strict_mode_enabled', False))}")
        lines.append(f"Ranking Metric: {str(leg['filters_used'].get('ranking_metric', 'profit_per_m3_per_day'))}")
        lines.append(f"Filters: {json.dumps(leg['filters_used'], ensure_ascii=False, sort_keys=True)}")
        lines.append(f"Total candidates: {leg['total_candidates']}")
        lines.append(f"passed_all_filters: {leg['passed_all_filters']}")
        lines.append("WHY_OUT Summary (top 10):")
        reason_counts = leg.get("why_out_summary", {})
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"  {reason}: {count}")
        lines.append("Portfolio:")
        lines.append(f"  items_count: {leg['items_count']}")
        lines.append(f"  m3_used/cargo_total: {leg['m3_used']:.2f}/{leg['cargo_total']:.2f} ({leg['cargo_util_pct']:.2f}%)")
        lines.append(f"  isk_used/budget_total: {fmt_isk(leg['isk_used'])}/{fmt_isk(leg['budget_total'])} ({leg['budget_util_pct']:.2f}%)")
        lines.append(f"  profit_total: {fmt_isk(leg['profit_total'])}")
        if "capital_available_before" in leg:
            lines.append("CAPITAL FLOW:")
            lines.append(f"  available_before: {fmt_isk(float(leg.get('capital_available_before', 0.0)))}")
            lines.append(f"  committed_this_leg: {fmt_isk(float(leg.get('capital_committed', 0.0)))}")
            lines.append(f"  released_this_leg: {fmt_isk(float(leg.get('capital_released', 0.0)))}")
            lines.append(f"  available_after: {fmt_isk(float(leg.get('capital_available_after', 0.0)))}")
            lines.append(f"  release_rule: {str(leg.get('capital_release_rule', 'none'))}")
        cargo_total = float(leg.get("cargo_total", 0.0))
        cargo_used = float(leg.get("m3_used", 0.0))
        cargo_free = max(0.0, cargo_total - cargo_used)
        cargo_util_pct = (cargo_used / cargo_total * 100.0) if cargo_total > 0 else 0.0
        lines.append("CARGO:")
        lines.append(f"  used_m3: {cargo_used:.2f}")
        lines.append(f"  free_m3: {cargo_free:.2f}")
        lines.append(f"  total_m3: {cargo_total:.2f}")
        lines.append(f"  util_pct: {cargo_util_pct:.2f}%")
        picks = leg.get("picks", [])
        lines.append("Top 10 Picks by Profit:")
        for p in sorted(picks, key=lambda x: x.get("profit", 0.0), reverse=True)[:10]:
            pick_qty = int(p.get("qty", 0))
            pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(pick_qty)
            lines.append(
                f"  {p.get('name', '')} | qty={pick_qty} | m3={pick_m3:.2f} | "
                f"profit={fmt_isk(p.get('profit', 0.0))} | raw={float(p.get('raw_confidence', p.get('overall_confidence', p.get('strict_confidence_score', 0.0)))):.3f}"
                f" | calibrated={float(p.get('calibrated_confidence', p.get('raw_confidence', p.get('overall_confidence', p.get('strict_confidence_score', 0.0))))):.3f}"
                f" | buy_at={str(p.get('buy_at', ''))} | sell_at={str(p.get('sell_at', ''))} | hops={int(p.get('route_hops', 1))}"
            )
        lines.append("HANDELSPLAN (menschenlesbar):")
        if not picks:
            lines.append("  Keine Picks fuer dieses Leg.")
        else:
            for i, p in enumerate(sorted(picks, key=lambda x: x.get("profit", 0.0), reverse=True), start=1):
                lines.extend(format_trade_instruction(leg, p, i))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_execution_plan_chain(
    path: str,
    timestamp: str,
    forward_leg_results: list[dict],
    return_leg_results: list[dict] | None = None,
    detail_mode: bool = False,
) -> None:
    lines: list[str] = ["=" * 70, "EXECUTION PLAN (CHAIN)", "=" * 70, f"Timestamp: {timestamp}"]
    plan_id = ""
    for leg in list(forward_leg_results or []) + list(return_leg_results or []):
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

    def append_section(title: str, leg_results: list[dict]) -> tuple[float, float, float, float, float]:
        section_cost = 0.0
        section_revenue = 0.0
        section_profit = 0.0
        section_fees_taxes = 0.0
        section_route_costs = 0.0
        section_leg_num = 0
        lines.append(title)
        lines.append("-" * len(title))
        lines.append("")
        for leg in leg_results:
            if bool(leg.get("leg_disabled", False)):
                continue
            picks = leg.get("picks", []) or []
            if not picks:
                continue
            route_summary = summarize_route_for_ranking(leg)
            section_leg_num += 1
            lines.append(f"LEG: LEG {section_leg_num}")
            lines.append(f"Route: {leg.get('route_label', '')}")
            route_id = str(leg.get("route_id", leg.get("route_tag", "")) or "")
            if route_id:
                lines.append(f"Route ID: {route_id}")
            leg_cargo_total = float(leg.get("cargo_total", 0.0))
            leg_cargo_used = float(leg.get("m3_used", 0.0))
            leg_cargo_free = max(0.0, leg_cargo_total - leg_cargo_used)
            leg_cargo_util = (leg_cargo_used / leg_cargo_total * 100.0) if leg_cargo_total > 0 else 0.0
            lines.append(
                f"Cargo: used {leg_cargo_used:.2f} m3 | free {leg_cargo_free:.2f} m3 | "
                f"total {leg_cargo_total:.2f} m3 | util {leg_cargo_util:.2f}%"
            )
            route_pos = format_reason_digest(list(route_summary.get("positive_reasons", []) or []), limit=3)
            route_neg = format_reason_digest(list(route_summary.get("negative_reasons", []) or []), limit=3)
            route_warn = format_reason_digest(list(route_summary.get("warnings", []) or []), limit=2)
            if route_pos:
                lines.append(f"Route Reasons+: {route_pos}")
            if route_neg:
                lines.append(f"Route Reasons-: {route_neg}")
            if route_warn:
                lines.append(f"Route Warnings: {route_warn}")
            if detail_mode:
                lines.append("Route Score Breakdown:")
                for contributor in list(route_summary.get("score_contributors", []) or []):
                    lines.append(
                        f"  - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.2f} "
                        f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                    )
            lines.append("")
            ordered = sorted(picks, key=lambda x: float(x.get("profit", 0.0)), reverse=True)
            for idx, p in enumerate(ordered, start=1):
                ensure_record_explainability(p, max_liq_days=float(leg.get("filters_used", {}).get("max_expected_days_to_sell", 90.0) if isinstance(leg.get("filters_used", {}), dict) else 90.0))
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
                lines.append(f"{idx}. {p.get('name', '')} (type_id {int(p.get('type_id', 0))})")
                pick_id = str(p.get("pick_id", p.get("journal_entry_id", "")) or "")
                if pick_id:
                    lines.append(f"   Pick ID: {pick_id}")
                lines.append(
                    f"   BUY  [{p.get('buy_at') or leg.get('source_label', 'SOURCE')}] qty={qty} @ {_fmt_isk_de(buy_avg)} "
                    f"(Total {_fmt_isk_de(buy_total)})"
                )
                if is_instant:
                    lines.append(
                        f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SOFORTVERKAUF/Buy-Order @ {_fmt_isk_de(sell_unit)} "
                        f"(Total {_fmt_isk_de(sell_total)}) | SOFORT"
                    )
                else:
                    lines.append(
                        f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SELL-ORDER @ {_fmt_isk_de(sell_unit)} "
                        f"(Total {_fmt_isk_de(sell_total)}) | Laufzeit {duration}d"
                    )
                lines.append(f"   Erwartet: {exp_days:.1f}d bis Verkauf | Fill {fill_prob:.1f}%")
                lines.append(f"   Erwarteter Profit: {_fmt_isk_de(profit)}")
                pos_digest = format_reason_digest(list(p.get("positive_reasons", []) or []), limit=3)
                neg_digest = format_reason_digest(list(p.get("negative_reasons", []) or []), limit=3)
                warn_digest = format_reason_digest(list(p.get("warnings", []) or []), limit=2)
                if pos_digest:
                    lines.append(f"   Reasons+: {pos_digest}")
                if neg_digest:
                    lines.append(f"   Reasons-: {neg_digest}")
                if warn_digest:
                    lines.append(f"   Warnings: {warn_digest}")
                if detail_mode:
                    lines.append("   Score Breakdown:")
                    for contributor in list(p.get("score_contributors", []) or []):
                        lines.append(
                            f"   - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.2f} "
                            f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
                        )
                lines.append(f"   Cargo fuer diesen Pick: {pick_m3:.2f} m3")
                lines.append(f"   Route-Hops: {int(p.get('route_hops', 1))}")
                lines.append("")
            leg_cost = float(leg.get("isk_used", 0.0))
            leg_revenue = sum(float(p.get("revenue_net", 0.0)) for p in ordered)
            leg_profit = float(leg.get("profit_total", 0.0))
            leg_fees_taxes = sum(pick_total_fees_taxes(p) for p in ordered)
            leg_route_cost = float(leg.get("total_transport_cost", 0.0))
            leg_shipping_cost = float(leg.get("total_shipping_cost", 0.0))
            section_cost += leg_cost
            section_revenue += leg_revenue
            section_profit += leg_profit
            section_fees_taxes += leg_fees_taxes
            section_route_costs += leg_route_cost
            lines.append(f"Leg Total Cost: {_fmt_isk_de(leg_cost)}")
            lines.append(f"Leg Total Net Revenue: {_fmt_isk_de(leg_revenue)}")
            lines.append(f"Leg Total Profit: {_fmt_isk_de(leg_profit)}")
            lines.append(f"Leg Fees+Taxes: {_fmt_isk_de(leg_fees_taxes)}")
            lines.append(f"Leg Route Costs: {_fmt_isk_de(leg_route_cost)}")
            if leg_shipping_cost > 0.0:
                lines.append(f"Leg Shipping Cost: {_fmt_isk_de(leg_shipping_cost)}")
                lines.append(f"shipping_cost_total: {_fmt_isk_de(leg_shipping_cost)}")
            lines.append("")
        if section_leg_num == 0:
            lines.append("Keine aktiven Legs mit Picks.")
            lines.append("")
        return section_cost, section_revenue, section_profit, section_fees_taxes, section_route_costs

    f_cost, f_revenue, f_profit, f_fees_taxes, f_route_costs = append_section("FORWARD", forward_leg_results)
    total_cost += f_cost
    total_revenue += f_revenue
    total_profit += f_profit
    total_fees_taxes += f_fees_taxes
    total_shipping_cost += sum(float(leg.get("total_shipping_cost", 0.0)) for leg in forward_leg_results)
    total_route_costs += f_route_costs
    if return_leg_results is not None:
        r_cost, r_revenue, r_profit, r_fees_taxes, r_route_costs = append_section("RETURN", return_leg_results)
        total_cost += r_cost
        total_revenue += r_revenue
        total_profit += r_profit
        total_fees_taxes += r_fees_taxes
        total_shipping_cost += sum(float(leg.get("total_shipping_cost", 0.0)) for leg in return_leg_results)
        total_route_costs += r_route_costs

    lines.append("=" * 70)
    lines.append(f"TOTAL COST: {_fmt_isk_de(total_cost)}")
    lines.append(f"TOTAL NET REVENUE: {_fmt_isk_de(total_revenue)}")
    lines.append(f"TOTAL EXPECTED PROFIT: {_fmt_isk_de(total_profit)}")
    lines.append(f"TOTAL FEES AND TAXES: {_fmt_isk_de(total_fees_taxes)}")
    if total_shipping_cost > 0.0:
        lines.append(f"TOTAL SHIPPING COST: {_fmt_isk_de(total_shipping_cost)}")
        lines.append(f"shipping_cost_total: {_fmt_isk_de(total_shipping_cost)}")
    lines.append(f"TOTAL ROUTE COSTS: {_fmt_isk_de(total_route_costs)}")
    lines.append("=" * 70)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


__all__ = [
    "fmt_isk",
    "pick_total_fees_taxes",
    "write_csv",
    "write_top_candidate_dump",
    "write_enhanced_summary",
    "write_chain_summary",
    "write_execution_plan_chain",
]
