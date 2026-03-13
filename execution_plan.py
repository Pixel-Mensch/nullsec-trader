from confidence_calibration import personal_history_layer_status_lines
from explainability import (
    build_rejected_candidate_table,
    ensure_record_explainability,
    format_reason_digest,
)
from route_search import route_ranking_value, summarize_route_for_ranking

# ---------------------------------------------------------------------------
# Pick categorisation constants
# ---------------------------------------------------------------------------

_CAT_MANDATORY = "mandatory"
_CAT_OPTIONAL = "optional"
_CAT_SPECULATIVE = "speculative"


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


# ---------------------------------------------------------------------------
# Pick classification helpers
# ---------------------------------------------------------------------------

def _pick_overall_confidence(p: dict) -> float:
    return float(
        p.get("overall_confidence",
              p.get("strict_confidence_score",
                    p.get("fill_probability", 0.0))) or 0.0
    )


def _pick_liquidity_confidence(p: dict) -> float:
    return float(p.get("liquidity_confidence", p.get("fill_probability", 0.0)) or 0.0)


def _pick_is_instant(p: dict) -> bool:
    return bool(p.get("instant", False)) or str(p.get("mode", "")).lower() == "instant"


def _pick_expected_days(p: dict) -> float:
    return float(p.get("expected_days_to_sell", 0.0) or 0.0)


def _pick_plausibility(p: dict) -> float:
    return float(p.get("market_plausibility_score", 1.0) or 1.0)


def _pick_manipulation_risk(p: dict) -> float:
    return float(p.get("manipulation_risk_score", 0.0) or 0.0)


def _pick_market_quality(p: dict) -> float:
    return float(p.get("market_quality_score", p.get("market_plausibility_score", 1.0)) or 1.0)


def _categorize_pick(p: dict) -> str:
    """Return _CAT_MANDATORY, _CAT_OPTIONAL, or _CAT_SPECULATIVE for a pick."""
    is_instant = _pick_is_instant(p)
    overall_conf = _pick_overall_confidence(p)
    liq_conf = _pick_liquidity_confidence(p)
    exp_days = _pick_expected_days(p)
    plausibility = _pick_plausibility(p)
    market_quality = _pick_market_quality(p)
    manip_risk = _pick_manipulation_risk(p)
    price_sensitive = _is_price_sensitive(p)

    # SPECULATIVE: low confidence, thin/suspicious market, or very long wait
    if overall_conf < 0.40:
        return _CAT_SPECULATIVE
    if not is_instant and exp_days > 60.0:
        return _CAT_SPECULATIVE
    if plausibility < 0.55:
        return _CAT_SPECULATIVE
    if market_quality < 0.50:
        return _CAT_SPECULATIVE
    if manip_risk > 0.50:
        return _CAT_SPECULATIVE
    if price_sensitive and (market_quality < 0.65 or manip_risk >= 0.35 or overall_conf < 0.55):
        return _CAT_SPECULATIVE

    # MANDATORY: instant exit with solid confidence and liquidity
    if (
        is_instant
        and overall_conf >= 0.60
        and liq_conf >= 0.60
        and market_quality >= 0.72
        and manip_risk < 0.35
        and not price_sensitive
    ):
        return _CAT_MANDATORY

    return _CAT_OPTIONAL


def _is_price_sensitive(p: dict) -> bool:
    """Return True if repricing to book-top erodes profit by >35%."""
    profit_book = float(p.get("profit_at_top_of_book", 0.0) or 0.0)
    profit_cons = float(
        p.get("profit_at_conservative_executable_price",
              p.get("expected_realized_profit_90d",
                    p.get("profit", 0.0))) or 0.0
    )
    if profit_book <= 0.0:
        return False
    return profit_cons < 0.65 * profit_book


def _pick_action_warnings(p: dict) -> list[str]:
    """Return human-readable warning strings for a single pick."""
    warnings: list[str] = []
    liq_conf = _pick_liquidity_confidence(p)
    manip = _pick_manipulation_risk(p)
    plaus = _pick_plausibility(p)
    market_quality = _pick_market_quality(p)
    exp_days = _pick_expected_days(p)
    is_instant = _pick_is_instant(p)

    if liq_conf < 0.40:
        warnings.append(f"Thin market - fill probability {liq_conf:.0%}")
    if manip > 0.40:
        warnings.append(f"Manipulation risk {manip:.0%} - verify order book")
    if plaus < 0.65:
        warnings.append(f"Low market plausibility {plaus:.2f} - check price history")
    if market_quality < 0.60:
        warnings.append(f"Fragile market quality {market_quality:.2f} - edge may depend on thin book conditions")
    if not is_instant and exp_days > 45.0:
        warnings.append(f"Long capital lock - expected {exp_days:.0f}d to sell")
    if _is_price_sensitive(p):
        profit_book = float(p.get("profit_at_top_of_book", 0.0) or 0.0)
        profit_cons = float(
            p.get("profit_at_conservative_executable_price",
                  p.get("expected_realized_profit_90d", p.get("profit", 0.0))) or 0.0
        )
        drop_pct = max(0.0, (1.0 - profit_cons / profit_book) * 100.0) if profit_book > 0 else 0.0
        warnings.append(f"Price-sensitive - profit drops ~{drop_pct:.0f}% if repriced to best offer")
    return warnings


def _route_level_warnings(picks: list[dict], route_summary: dict) -> list[str]:
    """Collect route-level warnings based on picks and route summary."""
    warnings: list[str] = []

    route_conf = float(route_summary.get("route_confidence", 0.0))
    if route_conf < 0.55:
        warnings.append(f"Low route confidence ({route_conf:.2f}) - consider skipping this route")

    lock_risk = float(route_summary.get("capital_lock_risk", 0.0))
    if lock_risk > 0.50:
        instant_picks = sum(1 for p in picks if _pick_is_instant(p))
        instant_share = (float(instant_picks) / float(len(picks))) if picks else 0.0
        avg_days = float(route_summary.get("average_expected_days_to_sell", 0.0) or 0.0)
        if picks and (instant_share >= 0.67 or avg_days <= 3.0):
            warnings.append(
                f"High capital concentration risk ({lock_risk:.2f}) - route is fast to exit, but profit is concentrated in few picks"
            )
        else:
            warnings.append(f"High capital lock risk ({lock_risk:.2f}) - planned exits may tie up budget for weeks")

    spec_picks = [p for p in picks if _categorize_pick(p) == _CAT_SPECULATIVE]
    if spec_picks:
        names = ", ".join(str(p.get("name", "?")) for p in spec_picks[:3])
        suffix = f" (+{len(spec_picks) - 3} more)" if len(spec_picks) > 3 else ""
        warnings.append(f"{len(spec_picks)} speculative pick(s) - verify market depth: {names}{suffix}")

    profits = sorted(
        [max(0.0, float(p.get("expected_realized_profit_90d", p.get("profit", 0.0)) or 0.0)) for p in picks],
        reverse=True,
    )
    total_profit = float(route_summary.get("total_expected_realized_profit", sum(profits) if profits else 0.0))
    if total_profit > 0 and profits:
        top3 = sum(profits[:3]) / total_profit
        if top3 > 0.60:
            top3_names = [
                str(p.get("name", "?"))
                for p in sorted(picks, key=lambda x: float(x.get("expected_realized_profit_90d", x.get("profit", 0.0)) or 0.0), reverse=True)[:3]
            ]
            warnings.append(
                f"Capital dominance: top 3 picks = {top3:.0%} of profit ({', '.join(top3_names)})"
            )

    cal_warn = str(route_summary.get("calibration_warning", "") or "")
    if cal_warn:
        warnings.append(f"Calibration: {cal_warn}")

    return warnings


def _fmt_item_name(name: str, width: int = 30) -> str:
    if len(name) > width:
        return name[: width - 2] + ".."
    return name.ljust(width)


def _write_shopping_list(lines: list[str], categorized: dict, fmt_isk_de) -> None:
    """Write a compact shopping list grouped by category."""
    lines.append("SHOPPING LIST")
    lines.append("-" * 42)
    cat_labels = [
        (_CAT_MANDATORY, "Mandatory - buy these first:"),
        (_CAT_OPTIONAL, "Optional - lower priority or slower exits:"),
        (_CAT_SPECULATIVE, "Speculative - verify market depth first:"),
    ]
    global_idx = 1
    any_picks = False
    for cat, label in cat_labels:
        picks_in_cat = categorized.get(cat, [])
        if not picks_in_cat:
            continue
        any_picks = True
        lines.append(f"  {label}")
        for p in picks_in_cat:
            name = str(p.get("name", "?"))
            qty = int(p.get("qty", 0))
            buy_avg = float(p.get("buy_avg", 0.0))
            total = buy_avg * qty
            price_str = fmt_isk_de(buy_avg).replace(" ISK", "")
            total_str = fmt_isk_de(total)
            ps_marker = " [!PRICE-SENS]" if _is_price_sensitive(p) else ""
            lines.append(
                f"    {global_idx:2}. {_fmt_item_name(name)}  "
                f"qty={qty:>8,}  @ {price_str:>16}  (total {total_str}){ps_marker}"
            )
            global_idx += 1
    if not any_picks:
        lines.append("  Keine Picks.")
    lines.append("")


def _write_route_trip_summary(
    lines: list[str],
    leg: dict,
    route_summary: dict,
    fmt_isk_de,
    active_profile: str,
    categorized: dict,
) -> None:
    """Write a one-block route trip summary (budget/cargo/profit/picks breakdown)."""
    budget_total = float(leg.get("budget_total", 0.0))
    budget_used = float(leg.get("isk_used", 0.0))
    budget_left = max(0.0, budget_total - budget_used)
    cargo_total = float(leg.get("cargo_total", leg.get("cargo_m3", leg.get("cargo_capacity_m3", 0.0))) or 0.0)
    m3_used = float(leg.get("total_route_m3", leg.get("m3_used", 0.0)) or 0.0)
    profit = float(route_summary.get("total_expected_realized_profit", leg.get("profit_total", 0.0)))
    route_conf = float(route_summary.get("route_confidence", 0.0))
    transport_conf = float(route_summary.get("transport_confidence", 0.0))

    n_mandatory = len(categorized.get(_CAT_MANDATORY, []))
    n_optional = len(categorized.get(_CAT_OPTIONAL, []))
    n_speculative = len(categorized.get(_CAT_SPECULATIVE, []))
    n_total = n_mandatory + n_optional + n_speculative

    budget_pct = (budget_used / budget_total * 100.0) if budget_total > 0 else 0.0
    cargo_pct = (m3_used / cargo_total * 100.0) if cargo_total > 0 else 0.0

    lines.append("ROUTE SUMMARY")
    if budget_total > 0:
        lines.append(
            f"  Budget:    {fmt_isk_de(budget_used)} / {fmt_isk_de(budget_total)} ({budget_pct:.1f}%)  "
            f"|  Remaining: {fmt_isk_de(budget_left)}"
        )
    if cargo_total > 0:
        lines.append(f"  Cargo:     {m3_used:.1f} m3 / {cargo_total:.1f} m3 ({cargo_pct:.1f}%)")
    lines.append(
        f"  Profit:    {fmt_isk_de(profit)}  "
        f"|  Route Confidence: {route_conf:.2f}  "
        f"|  Transport Confidence: {transport_conf:.2f}"
    )
    lines.append(
        f"  Picks:     {n_total} total - "
        f"{n_mandatory} MANDATORY, {n_optional} OPTIONAL, {n_speculative} SPECULATIVE"
    )
    transport_mode = str(leg.get("transport_mode", "") or "").strip()
    transport_note = str(leg.get("transport_mode_note", "") or "").strip()
    if transport_mode:
        lines.append(
            f"  Transport: {transport_mode}  "
            f"|  Cost: {fmt_isk_de(float(leg.get('total_transport_cost', 0.0) or 0.0))}"
        )
        if transport_note:
            lines.append(f"  Transport Note: {transport_note}")
    leg_shipping_costs = float(leg.get("total_shipping_cost", 0.0) or 0.0)
    if leg_shipping_costs > 0.0:
        lines.append(f"  Shipping:  {fmt_isk_de(leg_shipping_costs)} (transport cost)")
    operational_floor = float(leg.get("operational_profit_floor_isk", 0.0) or 0.0)
    if operational_floor > 0.0:
        lines.append(f"  Internal Route Floor: {fmt_isk_de(operational_floor)}")
        suppressed_profit = float(leg.get("suppressed_expected_realized_profit_total", 0.0) or 0.0)
        if suppressed_profit > 0.0:
            lines.append(f"  Suppressed Profit:    {fmt_isk_de(suppressed_profit)}")
        operational_note = str(leg.get("operational_filter_note", "") or "").strip()
        if operational_note:
            lines.append(f"  Internal Route Note: {operational_note}")
    if active_profile:
        lines.append(f"  Profile:   {active_profile.upper()}")
    removed_count = int(leg.get("route_mix_cleanup_removed_count", 0) or 0)
    if removed_count > 0:
        lines.append(f"  Route Mix Cleanup: removed {removed_count} weak add-on pick(s)")
    lines.append("")


def _write_pick_block(
    lines: list[str],
    p_i: int,
    p: dict,
    leg: dict,
    route_summary: dict,
    fmt_isk_de,
    category: str,
    detail_mode: bool,
) -> None:
    """Write a single pick block in the categorised picks section."""
    ensure_record_explainability(p, max_liq_days=_detail_max_liq_days(leg))

    qty = int(p.get("qty", 0))
    buy_avg = float(p.get("buy_avg", 0.0))
    buy_total = buy_avg * qty
    sell_unit = float(p.get("target_sell_price", 0.0) or p.get("sell_avg", 0.0))
    sell_total = sell_unit * qty
    duration = int(float(p.get("order_duration_days", 0) or 0))
    is_instant = _pick_is_instant(p)
    exit_type = str(p.get("exit_type", "instant" if is_instant else "speculative") or "speculative")
    exp_days = _pick_expected_days(p)
    fill_prob = _pick_liquidity_confidence(p) * 100.0
    overall_conf = _pick_overall_confidence(p)
    profit = float(
        p.get("expected_realized_profit_90d", p.get("expected_profit_90d", p.get("profit", 0.0))) or 0.0
    )
    pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(qty)
    unit_m3 = float(p.get("unit_volume", 0.0) or 0.0)

    cat_label = {"mandatory": "MANDATORY", "optional": "OPTIONAL", "speculative": "SPECULATIVE"}.get(category, category.upper())
    ps_tag = " | PRICE-SENS" if _is_price_sensitive(p) else ""
    exit_tag = "INSTANT" if is_instant else exit_type.upper()

    lines.append(
        f"  {p_i}. {p.get('name', '')} (type_id {int(p.get('type_id', 0))})"
        f"  [{cat_label} | {exit_tag}{ps_tag}]"
    )
    pick_id = str(p.get("pick_id", p.get("journal_entry_id", "")) or "")
    if pick_id:
        lines.append(f"     Pick ID: {pick_id}")
    lines.append(
        f"     BUY  [{p.get('buy_at') or leg.get('source_label', 'SOURCE')}]"
        f"  qty={qty:,}  @  {fmt_isk_de(buy_avg)}  (total {fmt_isk_de(buy_total)})"
    )
    # Price action threshold: alert if buy price would erode profitability
    if buy_avg > 0:
        lines.append(
            f"     >>> MAX BUY: {fmt_isk_de(buy_avg)}/unit - skip if market asks more"
        )
    if is_instant:
        lines.append(
            f"     SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}]"
            f"  SOFORTVERKAUF  @  {fmt_isk_de(sell_unit)}  (total {fmt_isk_de(sell_total)}) | SOFORT"
        )
    else:
        lines.append(
            f"     SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}]"
            f"  SELL-ORDER  @  {fmt_isk_de(sell_unit)}  (total {fmt_isk_de(sell_total)}) | Laufzeit {duration}d"
        )
        # Minimum viable sell price for planned orders
        if sell_unit > 0:
            lines.append(
                f"     >>> MIN SELL: {fmt_isk_de(sell_unit)}/unit - skip if market collapsed below this"
            )
    lines.append(
        f"     Expected: {exp_days:.1f}d  | Fill {fill_prob:.0f}%  | Confidence {overall_conf:.2f}"
        f"  |  Profit: {fmt_isk_de(profit)}"
    )
    fee_components = _pick_fee_components(p)
    lines.append(f"     Fees+Taxes: {fmt_isk_de(_pick_total_fees_taxes(p))}  |  m3: {pick_m3:.1f} (unit {unit_m3:.2f}m3)")
    lines.append(f"     sales_tax_isk: {fmt_isk_de(fee_components['sales_tax_isk'])}")
    lines.append(f"     broker_fee_isk: {fmt_isk_de(fee_components['broker_fee_isk'])}")
    lines.append(f"     scc_surcharge_isk: {fmt_isk_de(fee_components['scc_surcharge_isk'])}")
    lines.append(f"     relist_fee_isk: {fmt_isk_de(fee_components['relist_fee_isk'])}")
    lines.append(f"     Route/Shipping Cost: {fmt_isk_de(float(p.get('transport_cost', 0.0)))}")
    if int(p.get("character_open_orders", 0) or 0) > 0:
        lines.append(
            f"     Character Exposure: {int(p.get('character_open_orders', 0) or 0)} open orders "
            f"(buy {int(p.get('character_open_buy_orders', 0) or 0)} / "
            f"sell {int(p.get('character_open_sell_orders', 0) or 0)})"
        )
        if float(p.get("character_open_buy_isk_committed", 0.0) or 0.0) > 0.0:
            lines.append(
                f"     Character Buy Capital Bound: "
                f"{fmt_isk_de(float(p.get('character_open_buy_isk_committed', 0.0) or 0.0))}"
            )
        if int(p.get("character_open_sell_units", 0) or 0) > 0:
            lines.append(
                f"     Character Listed Units: {int(p.get('character_open_sell_units', 0) or 0)}"
            )
        warning_tier = str(p.get("open_order_warning_tier", "") or "").strip().upper()
        warning_text = str(p.get("open_order_warning_text", "") or "").strip()
        if warning_tier and warning_text:
            lines.append(f"     [WARN][ORDER-{warning_tier}] {warning_text}")

    # Inline warnings
    for w in _pick_action_warnings(p):
        lines.append(f"     [WARN] {w}")

    if detail_mode:
        full_sell_profit = float(p.get("gross_profit_if_full_sell", p.get("profit", 0.0)) or 0.0)
        lines.append(f"     Full Sell Profit: {fmt_isk_de(full_sell_profit)}")
        lines.append(f"     Expected Units Sold: {float(p.get('expected_units_sold_90d', 0.0) or 0.0):.2f}")
        lines.append(f"     Expected Units Unsold: {float(p.get('expected_units_unsold_90d', 0.0) or 0.0):.2f}")
        lines.append(f"     market_plausibility_score: {float(p.get('market_plausibility_score', 1.0) or 1.0):.2f}")
        lines.append(f"     market_quality_score: {float(p.get('market_quality_score', p.get('market_plausibility_score', 1.0)) or 1.0):.2f}")
        lines.append(f"     manipulation_risk_score: {float(p.get('manipulation_risk_score', 0.0) or 0.0):.2f}")
        lines.append(f"     profit_retention_ratio: {float(p.get('profit_retention_ratio', 1.0) or 1.0):.2f}")
        lines.append(f"     profit_at_top_of_book: {fmt_isk_de(float(p.get('profit_at_top_of_book', p.get('profit', 0.0)) or 0.0))}")
        lines.append(
            f"     profit_at_conservative_executable_price: "
            f"{fmt_isk_de(float(p.get('profit_at_conservative_executable_price', p.get('expected_realized_profit_90d', p.get('profit', 0.0))) or 0.0))}"
        )
        lines.append(f"     liquidity_confidence: {float(p.get('liquidity_confidence', p.get('fill_probability', 0.0)) or 0.0):.2f}")
        lines.append(f"     overall_confidence: {float(p.get('overall_confidence', p.get('strict_confidence_score', p.get('fill_probability', 0.0))) or 0.0):.2f}")
        lines.append(f"     raw_confidence: {float(p.get('raw_confidence', p.get('raw_overall_confidence', p.get('overall_confidence', 0.0))) or 0.0):.2f}")
        lines.append(f"     calibrated_confidence: {float(p.get('calibrated_confidence', p.get('calibrated_overall_confidence', p.get('overall_confidence', 0.0))) or 0.0):.2f}")
        lines.append(f"     transport_cost_model: {str(p.get('transport_cost_confidence', 'normal') or 'normal')}")
        pick_warning = str(p.get("calibration_warning", "") or "")
        if pick_warning:
            lines.append(f"     calibration_warning: {pick_warning}")
        _append_reason_lines(lines, "     ", list(p.get("positive_reasons", []) or []), "positive_reasons", detail_mode=True)
        _append_reason_lines(lines, "     ", list(p.get("negative_reasons", []) or []), "negative_reasons", detail_mode=True)
        _append_reason_lines(lines, "     ", list(p.get("warnings", []) or []), "warnings", detail_mode=True)
        pruned_reason = p.get("pruned_reason")
        if isinstance(pruned_reason, dict) and pruned_reason:
            lines.append(f"     pruned_reason: {pruned_reason.get('code', '')} - {pruned_reason.get('text', '')}")
        lines.append("     score_breakdown:")
        for contributor in list(p.get("score_contributors", []) or []):
            lines.append(
                f"     - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.2f} "
                f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
            )
        lines.append("     confidence_breakdown:")
        for contributor in list(p.get("confidence_contributors", []) or []):
            lines.append(
                f"     - {contributor.get('key', '')}: effect={float(contributor.get('effect', 0.0)):.4f} "
                f"value={float(contributor.get('value', 0.0)):.4f} | {contributor.get('text', '')}"
            )

    lines.append("")


def write_execution_plan_profiles(path: str, timestamp: str, route_results: list[dict], detail_mode: bool = False, compact_mode: bool = False) -> None:
    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    SEP = "=" * 70
    lines.append(SEP)
    lines.append("EXECUTION PLAN (ROUTE PROFILES)")
    lines.append(SEP)
    lines.append(f"Timestamp: {timestamp}")
    plan_id = ""
    for leg in list(route_results or []):
        plan_id = str(leg.get("plan_id", "") or "").strip()
        if plan_id:
            break
    if plan_id:
        lines.append(f"Plan ID: {plan_id}")
    active_profile = ""
    active_profile_params: dict = {}
    for leg in list(route_results or []):
        active_profile = str(leg.get("_active_risk_profile", "") or "")
        if active_profile:
            raw_params = leg.get("_active_risk_profile_params", {})
            if isinstance(raw_params, dict) and raw_params:
                active_profile_params = dict(raw_params)
            break
    if active_profile:
        from risk_profiles import BUILTIN_PROFILES, profile_restrictions_summary
        profile_params = active_profile_params or BUILTIN_PROFILES.get(active_profile, {})
        lines.append(f"Profile:   {active_profile.upper()}  -  {profile_params.get('description', '')}")
        lines.append(f"           {profile_restrictions_summary(active_profile, profile_params)}")
    character_summary = {}
    for leg in list(route_results or []):
        raw_summary = leg.get("_character_context_summary", {})
        if isinstance(raw_summary, dict) and raw_summary:
            character_summary = dict(raw_summary)
            break
    if character_summary:
        status = str(character_summary.get("source", "default") or "default").upper()
        if bool(character_summary.get("available", False)):
            lines.append(
                f"Character: {status}  -  {character_summary.get('character_name', '')} "
                f"({int(character_summary.get('character_id', 0) or 0)})"
            )
            lines.append(
                f"           Wallet {fmt_isk_de(float(character_summary.get('wallet_balance', 0.0) or 0.0))}  |  "
                f"Open Orders {int(character_summary.get('open_orders_count', 0) or 0)}"
            )
            if int(character_summary.get("overlapping_pick_count", 0) or 0) > 0:
                lines.append(
                    f"           Order Overlap {int(character_summary.get('overlapping_pick_count', 0) or 0)} picks"
                    f"  |  High Tier {int(character_summary.get('high_overlap_pick_count', 0) or 0)}"
                )
            fee_skills = dict(character_summary.get("fee_skills", {}) or {})
            if fee_skills:
                lines.append(
                    "           Fee Skills "
                    f"A={int(fee_skills.get('accounting', 0) or 0)} / "
                    f"BR={int(fee_skills.get('broker_relations', 0) or 0)} / "
                    f"ABR={int(fee_skills.get('advanced_broker_relations', 0) or 0)}"
                )
            if bool(character_summary.get("budget_exceeds_wallet", False)):
                lines.append(
                    f"           [WARN] Budget exceeds wallet by "
                    f"{fmt_isk_de(float(character_summary.get('budget_gap_isk', 0.0) or 0.0))}"
                )
        else:
            lines.append(f"Character: {status}  -  no private character data")
        for warning in list(character_summary.get("warnings", []) or []):
            lines.append(f"           [WARN] {warning}")
    personal_summary = {}
    personal_layer = {}
    for leg in list(route_results or []):
        raw_summary = leg.get("_personal_calibration_summary", {})
        if isinstance(raw_summary, dict) and raw_summary:
            personal_summary = dict(raw_summary)
            break
    for leg in list(route_results or []):
        raw_layer = leg.get("_personal_history_layer", {})
        if isinstance(raw_layer, dict) and raw_layer:
            personal_layer = dict(raw_layer)
            break
    if personal_summary:
        for idx, line in enumerate(personal_history_layer_status_lines(personal_summary, personal_layer)):
            lines.append(line if idx == 0 else f"                  {line}")
    if compact_mode:
        lines.append("Mode:      COMPACT (shopping list only - use --detail for full breakdown)")
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

        # Categorise all picks for this leg
        categorized: dict = {_CAT_MANDATORY: [], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: []}
        ordered_by_profit = sorted(picks, key=lambda x: float(x.get("expected_realized_profit_90d", x.get("profit", 0.0)) or 0.0), reverse=True)
        for p in ordered_by_profit:
            categorized[_categorize_pick(p)].append(p)

        # ── Plan header ──────────────────────────────────────────────────────
        plan_title = f"PLAN {idx}: {leg.get('route_label', '')}"
        if not actionable:
            plan_title += "  [NOT ACTIONABLE]"
        lines.append(plan_title)
        lines.append("-" * max(8, len(plan_title)))

        # Source / dest location block
        src_info = leg.get("source_node_info", {}) if isinstance(leg.get("source_node_info", {}), dict) else {}
        dst_info = leg.get("dest_node_info", {}) if isinstance(leg.get("dest_node_info", {}), dict) else {}
        route_id = str(leg.get("route_id", leg.get("route_tag", "")) or "")
        if route_id:
            lines.append(f"Route ID: {route_id}")
        personal_effect = dict(leg.get("_personal_history_effect_summary", {}) or {})
        if personal_summary and personal_layer and (
            bool(personal_layer.get("active", False)) or bool(personal_effect.get("applied", False))
        ):
            effect_lines = personal_history_layer_status_lines(personal_summary, personal_layer, personal_effect)
            if len(effect_lines) >= 3:
                lines.append(effect_lines[2])
        if src_info:
            if str(src_info.get("node_kind", "")) == "location":
                lines.append(
                    f"Source:   {src_info.get('node_label', leg.get('source_label', ''))} "
                    f"(location_id {int(src_info.get('location_id', src_info.get('node_id', 0)) or 0)}, "
                    f"region {int(src_info.get('node_region_id', 0) or 0)})"
                )
            else:
                lines.append(
                    f"Source:   {src_info.get('node_label', leg.get('source_label', ''))} "
                    f"(structure_id {int(src_info.get('structure_id', src_info.get('node_id', 0)) or 0)})"
                )
        if dst_info:
            if str(dst_info.get("node_kind", "")) == "location":
                lines.append(
                    f"Dest:     {dst_info.get('node_label', leg.get('dest_label', ''))} "
                    f"(location_id {int(dst_info.get('location_id', dst_info.get('node_id', 0)) or 0)}, "
                    f"region {int(dst_info.get('node_region_id', 0) or 0)})"
                )
            else:
                lines.append(
                    f"Dest:     {dst_info.get('node_label', leg.get('dest_label', ''))} "
                    f"(structure_id {int(dst_info.get('structure_id', dst_info.get('node_id', 0)) or 0)})"
                )

        # Shipping lane (always relevant for the trip)
        shipping_lane_id = str(leg.get("shipping_lane_id", "") or "")
        transport_mode = str(leg.get("transport_mode", "") or "")
        transport_note = str(leg.get("transport_mode_note", "") or "")
        if transport_mode:
            lines.append(f"Transport Mode: {transport_mode}")
            lines.append(f"  transport_cost_total: {fmt_isk_de(float(leg.get('total_transport_cost', 0.0) or 0.0))}")
            if transport_note:
                lines.append(f"  note: {transport_note}")
        if shipping_lane_id:
            lines.append(f"Shipping Lane: {shipping_lane_id}")
            provider = str(leg.get("shipping_provider", "") or "")
            if provider:
                lines.append(f"  provider: {provider}")
            pricing_model = str(leg.get("shipping_pricing_model", "") or "")
            if pricing_model:
                lines.append(f"  pricing_model: {pricing_model}")
            contracts_used = int(leg.get("shipping_contracts_used", 0) or 0)
            if contracts_used > 0:
                lines.append(f"  contracts_used: {contracts_used}")
            split_reason = str(leg.get("shipping_split_reason", "") or "")
            if split_reason:
                lines.append(f"  split_reason: {split_reason}")
            est_collateral = float(leg.get("estimated_collateral_isk", 0.0) or 0.0)
            if est_collateral > 0.0:
                lines.append(f"  estimated_collateral: {fmt_isk_de(est_collateral)}")
            lane_params = leg.get("shipping_lane_params", {})
            if isinstance(lane_params, dict) and lane_params:
                for key in (
                    "per_m3_rate", "minimum_reward", "full_load_reward",
                    "collateral_rate", "additional_collateral_rate",
                    "max_volume_per_contract_m3", "max_collateral_per_contract_isk",
                    "max_value", "collateral_basis",
                ):
                    if key in lane_params:
                        lines.append(f"  {key}: {lane_params.get(key)}")
        cost_model_confidence = str(leg.get("cost_model_confidence", "normal") or "normal")
        if cost_model_confidence != "normal":
            lines.append(f"[WARN] transport_cost_confidence: {cost_model_confidence}")
            warn_msg = str(leg.get("cost_model_warning", "") or "")
            if warn_msg:
                lines.append(f"[WARN] transport_cost: {warn_msg}")
        route_prune_reason = str(leg.get("route_prune_reason", route_summary.get("route_prune_reason", "")) or "")
        if route_prune_reason:
            lines.append(f"route_prune_reason: {route_prune_reason}")

        lines.append("")

        # ── Leg financial totals ─────────────────────────────────────────────
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

        # ── Route summary block (budget/cargo/confidence) ────────────────────
        _write_route_trip_summary(lines, leg, route_summary, fmt_isk_de, active_profile, categorized)

        # Detail-mode: route confidence breakdown
        if detail_mode:
            lines.append(f"route_confidence:             {float(route_summary.get('route_confidence', 0.0)):.4f}")
            lines.append(f"raw_route_confidence:         {float(route_summary.get('raw_route_confidence', route_summary.get('route_confidence', 0.0))):.4f}")
            lines.append(f"calibrated_route_confidence:  {float(route_summary.get('calibrated_route_confidence', route_summary.get('route_confidence', 0.0))):.4f}")
            lines.append(f"transport_confidence:         {float(route_summary.get('transport_confidence', 0.0)):.4f}")
            lines.append(f"raw_transport_confidence:     {float(route_summary.get('raw_transport_confidence', route_summary.get('transport_confidence', 0.0))):.4f}")
            lines.append(f"calibrated_transport_conf:    {float(route_summary.get('calibrated_transport_confidence', route_summary.get('transport_confidence', 0.0))):.4f}")
            lines.append(f"capital_lock_risk:            {float(route_summary.get('capital_lock_risk', 0.0)):.4f}")
            lines.append(f"Total Cost:                   {fmt_isk_de(leg_cost)}")
            lines.append(f"Total Net Revenue:            {fmt_isk_de(leg_revenue)}")
            lines.append(f"Total Full Sell Profit:       {fmt_isk_de(leg_full_sell_profit)}")
            lines.append(f"Total Fees and Taxes:         {fmt_isk_de(leg_fees_taxes)}")
            lines.append(f"Total Route Costs:            {fmt_isk_de(leg_route_costs)}")
            lines.append(f"total_route_m3:               {float(leg.get('total_route_m3', leg.get('m3_used', 0.0)) or 0.0):.2f} m3")
            if leg_shipping_costs > 0.0:
                lines.append(f"Shipping Cost Total:          {fmt_isk_de(leg_shipping_costs)}")
            calibration_warning = str(route_summary.get("calibration_warning", leg.get("calibration_warning", "")) or "")
            if calibration_warning:
                lines.append(f"calibration_warning: {calibration_warning}")
            _append_reason_lines(lines, "", list(route_summary.get("positive_reasons", []) or []), "route_positive_reasons", detail_mode=True)
            _append_reason_lines(lines, "", list(route_summary.get("negative_reasons", []) or []), "route_negative_reasons", detail_mode=True)
            _append_reason_lines(lines, "", list(route_summary.get("warnings", []) or []), "route_warnings", detail_mode=True)
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
            lines.append("")

        # Budget remainder note
        budget_total_val = float(leg.get("budget_total", 0.0))
        budget_used_val = float(leg.get("isk_used", 0.0))
        budget_left_val = max(0.0, budget_total_val - budget_used_val)
        if picks and budget_total_val > 0 and (budget_left_val / budget_total_val) >= 0.05:
            lines.append(
                f"  Budget Rest: {fmt_isk_de(budget_left_val)} - "
                "no further picks met profit floors after fees and route costs."
            )
            lines.append("")

        # ── Route-level warnings block ────────────────────────────────────────
        route_warns = _route_level_warnings(picks, route_summary)
        for note in list(leg.get("route_mix_cleanup_notes", []) or []):
            text = str(note or "").strip()
            if text:
                route_warns.append(text)
        if route_warns:
            lines.append("WARNINGS")
            for w in route_warns:
                lines.append(f"  [WARN] {w}")
            lines.append("")

        # ── Shopping list ────────────────────────────────────────────────────
        if picks:
            _write_shopping_list(lines, categorized, fmt_isk_de)

        # ── Categorised picks (skipped in compact_mode) ──────────────────────
        if not compact_mode:
            if not picks:
                lines.append("Keine Picks fuer diese Route. Route ist nicht actionable.")
                lines.append("")
            else:
                cat_sections = [
                    (_CAT_MANDATORY, "MANDATORY - instant exits, high confidence (execute first)"),
                    (_CAT_OPTIONAL, "OPTIONAL - lower priority or slower exits"),
                    (_CAT_SPECULATIVE, "SPECULATIVE - verify market depth before buying!"),
                ]
                global_pick_idx = 1
                for cat, section_label in cat_sections:
                    picks_in_cat = categorized.get(cat, [])
                    if not picks_in_cat:
                        continue
                    lines.append(f"=== {section_label} ===")
                    lines.append("")
                    if cat == _CAT_SPECULATIVE:
                        lines.append(
                            "  [WARN] These picks have low confidence or thin markets. "
                            "Consider skipping if route confidence is weak."
                        )
                        lines.append("")
                    for p in picks_in_cat:
                        _write_pick_block(lines, global_pick_idx, p, leg, route_summary, fmt_isk_de, cat, detail_mode)
                        global_pick_idx += 1

                if detail_mode:
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

        lines.append(SEP)
        lines.append("")

    actionable_entries = [
        (leg, summarize_route_for_ranking(leg))
        for leg in list(route_results or [])
        if bool(summarize_route_for_ranking(leg).get("actionable", False))
    ]
    lines.append(SEP)
    lines.append("BEST ACTIONABLE ROUTE")
    lines.append(SEP)
    if actionable_entries:
        best_leg, best_summary = max(
            actionable_entries,
            key=lambda entry: (
                _route_ranking_value(entry[0], "risk_adjusted_expected_profit"),
                float(entry[1].get("total_expected_realized_profit", 0.0) or 0.0),
            ),
        )
        lines.append(f"Route:                         {best_leg.get('route_label', '')}")
        lines.append(f"Budget Used:                   {fmt_isk_de(float(best_leg.get('isk_used', 0.0) or 0.0))}")
        lines.append(
            f"Expected Realized Profit:      "
            f"{fmt_isk_de(float(best_summary.get('total_expected_realized_profit', 0.0) or 0.0))}"
        )
        lines.append(f"Route Confidence:              {float(best_summary.get('route_confidence', 0.0) or 0.0):.2f}")
        lines.append(f"Capital Lock Risk:             {float(best_summary.get('capital_lock_risk', 0.0) or 0.0):.2f}")
    else:
        lines.append("No actionable route under the current filters.")
    lines.append("")
    lines.append("AGGREGATE ACROSS DISPLAYED ROUTE ALTERNATIVES")
    lines.append("This is NOT a combined executable plan. These totals sum alternative routes and can exceed your budget.")
    lines.append(f"Aggregate Cost Across Routes:  {fmt_isk_de(total_cost)}")
    lines.append(f"Aggregate Net Revenue:         {fmt_isk_de(total_revenue)}")
    lines.append(f"Aggregate Expected Profit:     {fmt_isk_de(total_profit)}")
    lines.append(f"Aggregate Fees and Taxes:      {fmt_isk_de(total_fees_taxes)}")
    if total_shipping_cost > 0.0:
        lines.append(f"Aggregate Shipping Cost:       {fmt_isk_de(total_shipping_cost)}")
    lines.append(f"Aggregate Route Costs:         {fmt_isk_de(total_route_costs)}")
    lines.append(SEP)
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
        transport_mode = str(r.get("transport_mode", "") or "")
        if transport_mode:
            lines.append(f"   transport_mode: {transport_mode}")
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
        for note in list(r.get("route_mix_cleanup_notes", []) or []):
            text = str(note or "").strip()
            if text:
                lines.append(f"   route_mix_cleanup: {text}")
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
        lines.append(f"   Total Transport Cost: {fmt_isk_de(float(r.get('total_transport_cost', 0.0) or 0.0))}")
        transport_note = str(r.get("transport_mode_note", "") or "")
        if transport_note:
            lines.append(f"   transport_note: {transport_note}")
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
            operational_floor = float(r.get("operational_profit_floor_isk", 0.0) or 0.0)
            if operational_floor > 0.0:
                lines.append(f"  internal_route_floor: {fmt_isk_de(operational_floor)}")
            suppressed_profit = float(r.get("suppressed_expected_realized_profit_total", 0.0) or 0.0)
            if suppressed_profit > 0.0:
                lines.append(f"  suppressed_expected_profit: {fmt_isk_de(suppressed_profit)}")
            operational_note = str(r.get("operational_filter_note", "") or "")
            if operational_note:
                lines.append(f"  internal_route_note: {operational_note}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_no_trade_report(
    path: str,
    timestamp: str,
    no_trade_result: dict,
    active_profile_name: str,
    active_profile_params: dict,
) -> None:
    """Write a structured DO NOT TRADE report file."""

    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    SEP = "=" * 70
    lines: list[str] = []
    lines.append(SEP)
    lines.append("DO NOT TRADE")
    lines.append(SEP)
    lines.append(f"Timestamp:  {timestamp}")
    lines.append(f"Profile:    {active_profile_name.upper()}")
    lines.append(
        f"Routes:     {no_trade_result.get('actionable_route_count', 0)} actionable "
        f"/ {no_trade_result.get('total_route_count', 0)} total"
    )
    lines.append("")

    # Reason codes
    reason_codes = list(no_trade_result.get("reason_codes", []) or [])
    if reason_codes:
        lines.append("GRUENDE / REASONS")
        lines.append("-" * 40)
        for r in reason_codes:
            sev = str(r.get("severity", "")).upper()
            lines.append(f"  [{sev}]  {r.get('code', '')}  -  {r.get('text', '')}")
            detail = str(r.get("detail", "") or "")
            if detail:
                lines.append(f"           {detail}")
        lines.append("")

    # Best route summary if available
    best = no_trade_result.get("best_route_summary")
    if best:
        lines.append("BESTE ROUTE (NICHT FREIGEGEBEN)")
        lines.append("-" * 40)
        lines.append(f"  Route:             {best.get('route_label', '')}")
        lines.append(f"  Route Confidence:  {float(best.get('route_confidence', 0.0)):.2f}")
        lines.append(f"  Transport Conf:    {float(best.get('transport_confidence', 0.0)):.2f}")
        lines.append(f"  Capital Lock:      {float(best.get('capital_lock_risk', 0.0)):.2f}")
        lines.append(f"  Expected Profit:   {fmt_isk_de(float(best.get('total_expected_profit', 0.0)))}")
        lines.append(
            f"  Picks:             {int(best.get('mandatory_picks', 0))} MANDATORY  "
            f"{int(best.get('optional_picks', 0))} OPTIONAL  "
            f"{int(best.get('speculative_picks', 0))} SPECULATIVE"
        )
        lines.append("  Status: BEOBACHTEN - nicht jetzt handeln")
        lines.append("")

    # Near-misses
    near_misses = list(no_trade_result.get("near_misses", []) or [])
    if near_misses:
        lines.append("BEINAHE BRAUCHBARE ROUTEN (FAST GUT)")
        lines.append("-" * 40)
        for nm in near_misses:
            label = str(nm.get("route_label", "") or "-")
            reason = str(nm.get("prune_reason", "") or "no_picks")
            candidates = int(nm.get("total_candidates", 0) or 0)
            blocked = bool(nm.get("transport_blocked", False))
            lines.append(f"  {label}")
            lines.append(f"    Grund: {reason}  |  Kandidaten geprueft: {candidates}")
            if blocked:
                lines.append("    [Transport blockiert - keine Shipping Lane verfuegbar]")
            operational_floor = float(nm.get("operational_profit_floor_isk", 0.0) or 0.0)
            if operational_floor > 0.0:
                lines.append(f"    Internal Route Floor: {fmt_isk_de(operational_floor)}")
            suppressed_profit = float(nm.get("suppressed_expected_realized_profit_total", 0.0) or 0.0)
            if suppressed_profit > 0.0:
                lines.append(f"    Suppressed Expected Profit: {fmt_isk_de(suppressed_profit)}")
            operational_note = str(nm.get("operational_filter_note", "") or "")
            if operational_note:
                lines.append(f"    Internal Route Note: {operational_note}")
            why = dict(nm.get("why_out_summary", {}) or {})
            if why:
                top_why = sorted(why.items(), key=lambda kv: kv[1], reverse=True)[:3]
                why_str = "  ".join(f"{k}={v}" for k, v in top_why)
                lines.append(f"    Ablehnungsgruende: {why_str}")
        lines.append("")

    # Profile comparison
    comparison = dict(no_trade_result.get("profile_comparison", {}) or {})
    if comparison:
        lines.append("PROFIL-VERGLEICH")
        lines.append("-" * 40)
        lines.append("  Wuerde ein anderes Profil hier handeln?")
        for pname, would_trade in sorted(comparison.items()):
            verdict = "JA - wuerde handeln" if would_trade else "NEIN - wuerde ebenfalls ablehnen"
            lines.append(f"    {pname:<20} {verdict}")
        lines.append("")

    lines.append(SEP)
    lines.append("Empfehlung: Heute nicht handeln.")
    lines.append("Daten, Markt oder Profil rechtfertigen keinen Plan.")
    lines.append(SEP)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
