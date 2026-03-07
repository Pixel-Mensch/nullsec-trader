from __future__ import annotations

from confidence_calibration import apply_calibration_to_record
from explainability import build_pick_score_breakdown, ensure_record_explainability
from fee_engine import FeeEngine
from models import TradeCandidate
from candidate_engine import compute_candidates
from scoring import apply_strategy_mode


def fmt_isk(x: float) -> str:
    value = float(x or 0.0)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}b"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}m"
    if value >= 1_000:
        return f"{value / 1_000:.2f}k"
    return f"{value:.2f}"


def _candidate_expected_realized_profit(c) -> float:
    return float(
        getattr(
            c,
            "expected_realized_profit_90d",
            c.get("expected_realized_profit_90d", c.get("expected_profit_90d", c.get("profit", 0.0)))
            if isinstance(c, dict)
            else getattr(c, "expected_profit_90d", 0.0),
        )
        or 0.0
    )


def _candidate_expected_realized_profit_per_m3(c) -> float:
    return float(
        getattr(
            c,
            "expected_realized_profit_per_m3_90d",
            c.get(
                "expected_realized_profit_per_m3_90d",
                c.get("expected_profit_per_m3_90d", c.get("profit_per_m3", 0.0)),
            )
            if isinstance(c, dict)
            else getattr(c, "expected_profit_per_m3_90d", 0.0),
        )
        or 0.0
    )


def _candidate_confidence(c) -> float:
    raw = getattr(
        c,
        "decision_overall_confidence",
        c.get(
            "decision_overall_confidence",
            c.get("calibrated_overall_confidence", c.get("overall_confidence", c.get("strict_confidence_score", c.get("fill_probability", 0.0))))
        )
        if isinstance(c, dict)
        else getattr(c, "calibrated_overall_confidence", getattr(c, "strict_confidence_score", getattr(c, "fill_probability", 0.0))),
    )
    return max(0.0, min(1.0, float(raw or 0.0)))


def _candidate_raw_confidence(c) -> float:
    raw = getattr(
        c,
        "raw_overall_confidence",
        c.get("raw_overall_confidence", c.get("raw_confidence", c.get("overall_confidence", c.get("strict_confidence_score", c.get("fill_probability", 0.0)))))
        if isinstance(c, dict)
        else getattr(c, "overall_confidence", getattr(c, "strict_confidence_score", getattr(c, "fill_probability", 0.0))),
    )
    return max(0.0, min(1.0, float(raw or 0.0)))


def _candidate_calibrated_confidence(c) -> float:
    raw = getattr(
        c,
        "calibrated_overall_confidence",
        c.get("calibrated_overall_confidence", c.get("calibrated_confidence", c.get("raw_overall_confidence", c.get("overall_confidence", 0.0))))
        if isinstance(c, dict)
        else getattr(c, "raw_overall_confidence", getattr(c, "overall_confidence", 0.0)),
    )
    return max(0.0, min(1.0, float(raw or 0.0)))


def _candidate_transport_confidence(c) -> float:
    raw = getattr(
        c,
        "raw_transport_confidence",
        c.get("raw_transport_confidence", c.get("transport_confidence", 1.0))
        if isinstance(c, dict)
        else getattr(c, "transport_confidence", 1.0),
    )
    return max(0.0, min(1.0, float(raw or 0.0)))


def _candidate_calibration_warning(c) -> str:
    raw = getattr(
        c,
        "calibration_warning",
        c.get("calibration_warning", "")
        if isinstance(c, dict)
        else "",
    )
    return str(raw or "")


def _candidate_confidence_payload(c) -> dict[str, object]:
    raw_exit = max(
        0.0,
        min(
            1.0,
            float(
                getattr(
                    c,
                    "raw_exit_confidence",
                    c.get("raw_exit_confidence", c.get("exit_confidence", 0.0))
                    if isinstance(c, dict)
                    else getattr(c, "exit_confidence", 0.0),
                )
                or 0.0
            ),
        ),
    )
    raw_liquidity = max(
        0.0,
        min(
            1.0,
            float(
                getattr(
                    c,
                    "raw_liquidity_confidence",
                    c.get("raw_liquidity_confidence", c.get("liquidity_confidence", 0.0))
                    if isinstance(c, dict)
                    else getattr(c, "liquidity_confidence", 0.0),
                )
                or 0.0
            ),
        ),
    )
    raw_transport = _candidate_transport_confidence(c)
    raw_overall = _candidate_raw_confidence(c)
    calibrated_exit = max(
        0.0,
        min(
            1.0,
            float(
                getattr(
                    c,
                    "calibrated_exit_confidence",
                    c.get("calibrated_exit_confidence", raw_exit)
                    if isinstance(c, dict)
                    else raw_exit,
                )
                or 0.0
            ),
        ),
    )
    calibrated_liquidity = max(
        0.0,
        min(
            1.0,
            float(
                getattr(
                    c,
                    "calibrated_liquidity_confidence",
                    c.get("calibrated_liquidity_confidence", raw_liquidity)
                    if isinstance(c, dict)
                    else raw_liquidity,
                )
                or 0.0
            ),
        ),
    )
    calibrated_transport = max(
        0.0,
        min(
            1.0,
            float(
                getattr(
                    c,
                    "calibrated_transport_confidence",
                    c.get("calibrated_transport_confidence", raw_transport)
                    if isinstance(c, dict)
                    else raw_transport,
                )
                or 0.0
            ),
        ),
    )
    calibrated_overall = _candidate_calibrated_confidence(c)
    decision_overall = _candidate_confidence(c)
    return {
        "transport_confidence": raw_transport,
        "raw_exit_confidence": raw_exit,
        "raw_liquidity_confidence": raw_liquidity,
        "raw_transport_confidence": raw_transport,
        "raw_overall_confidence": raw_overall,
        "calibrated_exit_confidence": calibrated_exit,
        "calibrated_liquidity_confidence": calibrated_liquidity,
        "calibrated_transport_confidence": calibrated_transport,
        "calibrated_overall_confidence": calibrated_overall,
        "raw_confidence": raw_overall,
        "calibrated_confidence": calibrated_overall,
        "decision_overall_confidence": decision_overall,
        "calibration_warning": _candidate_calibration_warning(c),
    }


def _confidence_calibration_model(cfg: dict | None) -> dict | None:
    if not isinstance(cfg, dict):
        return None
    runtime = cfg.get("_confidence_calibration_runtime", {})
    if not isinstance(runtime, dict):
        return None
    return runtime.get("model")


def _candidate_expected_days(c) -> float:
    return float(
        getattr(
            c,
            "expected_days_to_sell",
            c.get("expected_days_to_sell", 0.0) if isinstance(c, dict) else 0.0,
        )
        or 0.0
    )


def _candidate_estimated_sellable_units(c) -> float:
    return float(
        getattr(
            c,
            "estimated_sellable_units_90d",
            c.get("estimated_sellable_units_90d", c.get("expected_units_sold_90d", c.get("max_units", 0)))
            if isinstance(c, dict)
            else getattr(c, "expected_units_sold_90d", 0.0),
        )
        or 0.0
    )


def _candidate_max_qty_by_demand(c, demand_share_cap: float) -> int:
    max_units = int(getattr(c, "max_units", c.get("max_units", 0) if isinstance(c, dict) else 0) or 0)
    sellable_units = _candidate_estimated_sellable_units(c)
    if sellable_units <= 0.0:
        return max_units
    capped = int(sellable_units * max(0.0, float(demand_share_cap)))
    if capped <= 0:
        capped = 1
    return min(max_units, capped)


def _candidate_scale_ratio(c, qty: int) -> float:
    max_units = float(getattr(c, "max_units", c.get("max_units", 0) if isinstance(c, dict) else 0) or 0.0)
    if max_units <= 0.0:
        return 0.0
    return max(0.0, min(1.0, float(qty) / max_units))


def _candidate_scaled_expected_days(c, qty: int) -> float:
    expected_days = _candidate_expected_days(c)
    if expected_days <= 0.0 or int(qty) <= 0:
        return 0.0
    max_units = float(getattr(c, "max_units", c.get("max_units", 0) if isinstance(c, dict) else 0) or 0.0)
    if max_units <= 0.0:
        return float(expected_days)
    queue_ahead_units = max(
        0.0,
        float(getattr(c, "queue_ahead_units", c.get("queue_ahead_units", 0) if isinstance(c, dict) else 0) or 0.0),
    )
    scaled_qty = max(0.0, min(float(qty), max_units))
    denom = queue_ahead_units + max_units
    if denom <= 0.0:
        return float(expected_days)
    return float(expected_days) * ((queue_ahead_units + scaled_qty) / denom)


def _portfolio_expected_realized_profit(picks: list[dict]) -> float:
    return sum(float(p.get("expected_realized_profit_90d", p.get("expected_profit_90d", p.get("profit", 0.0))) or 0.0) for p in picks)


def _portfolio_objective(picks: list[dict], budget_isk: float, portfolio_cfg: dict) -> float:
    total_expected = _portfolio_expected_realized_profit(picks)
    if not picks:
        return total_expected
    max_share = max(0.0, float(portfolio_cfg.get("max_item_share_of_budget", 1.0)))
    concentration_penalty = 0.0
    liquidity_penalty = 0.0
    for p in picks:
        cost = float(p.get("cost", 0.0) or 0.0)
        share = (cost / max(1e-9, float(budget_isk))) if float(budget_isk) > 0 else 0.0
        over = max(0.0, share - (max_share * 0.70))
        concentration_penalty += over * max(0.0, float(p.get("expected_realized_profit_90d", p.get("profit", 0.0)) or 0.0))
        # Penalty proportional to expected profit: 0.5% of realized profit per extra day over 30d.
        # Flat-ISK (1000/day) was ~0.06% of a typical position — functionally zero vs million-ISK profits.
        extra_days = max(0.0, float(p.get("expected_days_to_sell", 0.0) or 0.0) - 30.0)
        pick_expected = max(0.0, float(p.get("expected_realized_profit_90d", p.get("profit", 0.0)) or 0.0))
        liquidity_penalty += extra_days * pick_expected * 0.005
    return float(total_expected) - float(concentration_penalty * 0.25) - float(liquidity_penalty)


def _candidate_selection_score(c, max_liq_days: float) -> float:
    score, _ = build_pick_score_breakdown(c, max_liq_days=float(max_liq_days))
    return float(score)


def portfolio_stats(picks: list[dict]) -> tuple[float, float, float, dict]:
    total_cost = sum(p["cost"] for p in picks)
    total_profit = sum(
        float(p.get("expected_realized_profit_90d", p.get("expected_profit_90d", p.get("profit", 0.0))) or 0.0)
        for p in picks
    )
    total_m3 = sum(p["unit_volume"] * p["qty"] for p in picks)
    spent_by_type: dict = {}
    for p in picks:
        spent_by_type[p["type_id"]] = spent_by_type.get(p["type_id"], 0) + p["cost"]
    return total_cost, total_profit, total_m3, spent_by_type


def validate_portfolio(
    picks: list[dict],
    budget_isk: float,
    cargo_m3: float,
    portfolio_cfg: dict
) -> bool:
    if not picks:
        return True
    total_cost, _, total_m3, _ = portfolio_stats(picks)
    if total_cost > budget_isk + 1e-6 or total_m3 > cargo_m3 + 1e-6:
        return False
    if len(picks) > int(portfolio_cfg.get("max_items", len(picks))):
        return False
    max_share = float(portfolio_cfg.get("max_item_share_of_budget", 1.0))
    max_liq_days = float(portfolio_cfg.get("max_liquidation_days_per_position", 99999.0))
    demand_share_cap = float(portfolio_cfg.get("max_share_of_estimated_demand_per_position", 1.0))
    for p in picks:
        if p["cost"] > budget_isk * max_share + 1e-6:
            return False
        if float(p.get("expected_days_to_sell", 0.0) or 0.0) > max_liq_days + 1e-6:
            return False
        est_sellable = float(p.get("estimated_sellable_units_90d", p.get("expected_units_sold_90d", 0.0)) or 0.0)
        if est_sellable > 0.0 and float(p.get("qty", 0) or 0) > (est_sellable * demand_share_cap) + 1e-6:
            return False
    return True


def local_search_optimize(
    initial: list[dict],
    candidates: list[dict],
    budget_isk: float,
    cargo_m3: float,
    portfolio_cfg: dict
) -> list[dict]:
    import time

    start_time = time.time()
    max_time_secs = 10
    if not initial or not candidates:
        return initial
    best = list(initial)
    best_score = _portfolio_objective(best, budget_isk, portfolio_cfg)
    top_k = 50
    sorted_cands = sorted(
        candidates,
        key=lambda c: (
            float(c.get("expected_realized_profit_90d", c.get("expected_profit_90d", c.get("profit", 0.0))) or 0.0),
            _candidate_confidence(c),
        ),
        reverse=True,
    )[:top_k]
    picked_type_ids = {p["type_id"] for p in best}
    improved = True
    while improved and time.time() - start_time < max_time_secs:
        improved = False
        for i, old_pick in enumerate(best):
            for new_cand in sorted_cands:
                if new_cand["type_id"] in picked_type_ids and new_cand["type_id"] != old_pick["type_id"]:
                    continue
                trial = best[:i] + [new_cand] + best[i + 1:]
                if not validate_portfolio(trial, budget_isk, cargo_m3, portfolio_cfg):
                    continue
                trial_score = _portfolio_objective(trial, budget_isk, portfolio_cfg)
                if trial_score > best_score + 1e-6:
                    best = trial
                    picked_type_ids = {p["type_id"] for p in best}
                    best_score = trial_score
                    improved = True
                    break
            if improved:
                break
    return best


def sort_picks_for_output(picks: list[dict], filters_used: dict) -> None:
    ranking_metric = str(filters_used.get("ranking_metric", "expected_profit_per_m3_90d")).lower()
    if ranking_metric == "expected_profit_per_m3_90d":
        picks.sort(
            key=lambda x: (
                x.get("expected_realized_profit_per_m3_90d", x.get("expected_profit_per_m3_90d", 0.0)),
                x.get("expected_realized_profit_90d", x.get("expected_profit_90d", 0.0)),
                x.get("decision_overall_confidence", x.get("calibrated_overall_confidence", x.get("overall_confidence", x.get("strict_confidence_score", 0.0)))),
                -x.get("expected_days_to_sell", 0.0),
            ),
            reverse=True
        )
    elif ranking_metric == "profit":
        picks.sort(key=lambda x: x.get("profit", 0.0), reverse=True)
    elif ranking_metric == "profit_per_m3":
        picks.sort(key=lambda x: x.get("profit_per_m3", 0.0), reverse=True)
    else:
        picks.sort(key=lambda x: x.get("profit_per_m3_per_day", 0.0), reverse=True)

def _sort_candidates_for_cargo_fill(candidates: list[TradeCandidate], ranking_metric: str) -> list[TradeCandidate]:
    metric = str(ranking_metric or "expected_profit_per_m3_90d").lower()
    if metric in ("hybrid", "profit_per_m3_and_isk", "profit_per_m3_plus_isk"):
        def hybrid_score(c: TradeCandidate) -> float:
            density = max(0.0, float(getattr(c, "profit_per_m3", 0.0)))
            cap_eff = max(0.0, float(getattr(c, "profit_pct", 0.0)))
            return (density * 0.7) + (cap_eff * 1000.0 * 0.3)
        return sorted(
            candidates,
            key=lambda c: (
                hybrid_score(c),
                float(getattr(c, "profit_per_m3_per_day", 0.0)),
                float(getattr(c, "profit_pct", 0.0))
            ),
            reverse=True
        )
    if metric == "expected_profit_per_m3_90d":
        return sorted(
            candidates,
            key=lambda c: (
                float(getattr(c, "expected_realized_profit_per_m3_90d", getattr(c, "expected_profit_per_m3_90d", 0.0))),
                float(getattr(c, "expected_realized_profit_90d", getattr(c, "expected_profit_90d", 0.0))),
                _candidate_confidence(c),
                -float(getattr(c, "expected_days_to_sell", 0.0)),
                -float(getattr(c, "risk_score", 0.0))
            ),
            reverse=True
        )
    if metric == "profit":
        return sorted(
            candidates,
            key=lambda c: float(getattr(c, "profit_per_unit", 0.0)) * float(getattr(c, "max_units", 0)),
            reverse=True
        )
    if metric == "profit_per_m3":
        return sorted(candidates, key=lambda c: float(getattr(c, "profit_per_m3", 0.0)), reverse=True)
    # Cargo fill default: prioritize dense and liquid picks.
    return sorted(
        candidates,
        key=lambda c: (
            float(getattr(c, "profit_per_m3_per_day", 0.0)),
            float(getattr(c, "profit_per_m3", 0.0)),
            float(getattr(c, "sell_through_ratio_90d", 0.0)),
            -float(getattr(c, "risk_score", 0.0)),
            float(getattr(c, "profit_pct", 0.0))
        ),
        reverse=True
    )

def try_cargo_fill(
    base_picks: list[dict],
    candidates: list[TradeCandidate],
    budget_isk: float,
    cargo_m3: float,
    fees: dict,
    filters_used: dict,
    port_cfg: dict
) -> tuple[list[dict], float, float, float, int]:
    buy_broker = float(fees["buy_broker_fee"])
    max_turnover_factor = float(filters_used.get("max_turnover_factor", 3.0))
    min_instant_fill_ratio = float(filters_used.get("min_instant_fill_ratio", 0.0))
    base_max_share = float(port_cfg.get("max_item_share_of_budget", 1.0))
    max_share = float(port_cfg.get("cargo_fill_max_item_share_of_budget", base_max_share))
    max_items = int(port_cfg.get("max_items", 50))
    order_duration = int(filters_used.get("order_duration_days", 90))
    relist_budget_pct = float(filters_used.get("relist_budget_pct", fees.get("relist_budget_pct", 0.0)))
    relist_budget_isk = float(filters_used.get("relist_budget_isk", fees.get("relist_budget_isk", 0.0)))
    fill_metric = str(port_cfg.get("cargo_fill_ranking_metric", "profit_per_m3_per_day")).lower()
    cargo_fill_stop_util = float(port_cfg.get("cargo_fill_stop_util", 0.98))
    cargo_fill_min_profit_per_m3_ratio = float(port_cfg.get("cargo_fill_min_profit_per_m3_ratio", 0.75))
    cargo_fill_min_profit_pct = float(port_cfg.get("cargo_fill_min_profit_pct", 0.0))
    cargo_fill_min_profit_abs_isk = float(port_cfg.get("cargo_fill_min_profit_abs_isk", 0.0))
    max_extra_items = int(port_cfg.get("cargo_fill_max_extra_items", 8))
    allow_topup_existing = bool(port_cfg.get("cargo_fill_allow_topup_existing", False))
    max_liq_days = float(port_cfg.get("max_liquidation_days_per_position", 99999.0))
    demand_share_cap = float(port_cfg.get("max_share_of_estimated_demand_per_position", 1.0))

    if max_extra_items <= 0:
        total_cost, total_profit, total_m3, _ = portfolio_stats(base_picks)
        return list(base_picks), total_cost, total_profit, total_m3, 0

    total_cost, total_profit, total_m3, spent_by_type = portfolio_stats(base_picks)
    remaining_budget = max(0.0, float(budget_isk) - float(total_cost))
    remaining_cargo = max(0.0, float(cargo_m3) - float(total_m3))
    if remaining_budget <= 1e-6 or remaining_cargo <= 1e-6:
        return list(base_picks), total_cost, total_profit, total_m3, 0

    picked_type_ids = {int(p.get("type_id", 0)) for p in base_picks}
    if allow_topup_existing:
        fill_pool = list(candidates)
    else:
        fill_pool = [c for c in candidates if int(getattr(c, "type_id", 0)) not in picked_type_ids]
    if not fill_pool:
        return list(base_picks), total_cost, total_profit, total_m3, 0
    sorted_fill_pool = _sort_candidates_for_cargo_fill(fill_pool, fill_metric)

    picks = list(base_picks)
    picks_by_type: dict[int, dict] = {int(p.get("type_id", 0)): p for p in picks}
    max_new_slots = min(max_extra_items, max(0, max_items - len(picks)))
    if max_new_slots <= 0 and not allow_topup_existing:
        return picks, total_cost, total_profit, total_m3, 0

    added = 0
    added_new_types = 0
    base_total_m3 = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in base_picks)
    # Use expected_realized_profit_90d (risk-adjusted) if available, otherwise fall back to gross profit.
    # Gross `profit` field overstates the baseline for planned_sell routes where sell-through < 100%.
    base_total_profit = sum(
        float(p.get("expected_realized_profit_90d", p.get("profit", 0.0)) or 0.0)
        for p in base_picks
    )
    base_profit_per_m3 = (base_total_profit / base_total_m3) if base_total_m3 > 0 else 0.0
    for c in sorted_fill_pool:
        if remaining_budget <= 1e-6 or remaining_cargo <= 1e-6:
            break
        projected_util = (total_m3 / max(1e-9, float(cargo_m3))) if float(cargo_m3) > 0 else 1.0
        if projected_util >= max(0.0, min(1.0, cargo_fill_stop_util)):
            break
        tid = int(getattr(c, "type_id", 0))
        existing_pick = picks_by_type.get(tid)
        is_existing = existing_pick is not None
        if not is_existing and (added_new_types >= max_new_slots or len(picks) >= max_items):
            if not allow_topup_existing:
                break
            continue
        if float(getattr(c, "expected_days_to_sell", 0.0)) > max_liq_days:
            continue

        unit_cost = float(getattr(c, "buy_avg", 0.0)) * (1.0 + buy_broker)
        unit_vol = float(getattr(c, "unit_volume", 0.0))
        if unit_cost <= 0.0 or unit_vol <= 0.0:
            continue

        max_budget_for_item = float(budget_isk) * max_share
        already_for_item = float(spent_by_type.get(tid, 0.0))
        existing_qty = int(existing_pick.get("qty", 0)) if is_existing else 0
        max_candidate_units = _candidate_max_qty_by_demand(c, demand_share_cap)
        max_candidate_remaining = max_candidate_units - existing_qty if is_existing else max_candidate_units
        if max_candidate_remaining <= 0:
            continue
        max_by_budget = int(remaining_budget // unit_cost)
        max_by_share = int((max_budget_for_item - already_for_item) // unit_cost)
        max_by_cargo = int(remaining_cargo // unit_vol)
        qty = min(max_candidate_remaining, max_by_budget, max_by_share, max_by_cargo)
        if qty <= 0:
            continue

        total_qty_after = existing_qty + qty
        scale_ratio = _candidate_scale_ratio(c, qty)
        scaled_expected_realized_profit = _candidate_expected_realized_profit(c) * float(scale_ratio or 1.0)
        if bool(getattr(c, "instant", True)):
            instant_fill_ratio_after = min(1.0, float(getattr(c, "dest_buy_depth_units", 0)) / max(1.0, float(total_qty_after)))
            if instant_fill_ratio_after < min_instant_fill_ratio:
                continue
            turnover_factor_after = min(max_turnover_factor, max(0.0, instant_fill_ratio_after))
            fill_probability_after = instant_fill_ratio_after
        else:
            instant_fill_ratio_after = 1.0
            turnover_factor_after = float(getattr(c, "turnover_factor", 0.0))
            fill_probability_after = float(getattr(c, "fill_probability", 0.0))

        mode_str = str(getattr(c, "mode", "instant"))
        execution = "instant_instant" if mode_str.lower() == "instant" else "instant_listed"
        breakdown = FeeEngine(fees).compute(
            buy_price=float(getattr(c, "buy_avg", 0.0)),
            sell_price=float(getattr(c, "sell_avg", 0.0)),
            qty=qty,
            execution=execution,
            relist_budget_pct=relist_budget_pct if execution == "instant_listed" else 0.0,
            relist_budget_isk=(relist_budget_isk if mode_str.lower() == "planned_sell" else 0.0),
        )
        cost = float(breakdown.cost_net)
        revenue_net = float(breakdown.revenue_net)
        profit = float(breakdown.profit)
        if profit <= 0:
            continue
        cost_for_ratio = max(1e-9, cost)
        profit_pct = float(profit) / cost_for_ratio
        if profit_pct < max(0.0, cargo_fill_min_profit_pct):
            continue
        if float(profit) < max(0.0, cargo_fill_min_profit_abs_isk):
            continue
        candidate_profit_per_m3 = float(scaled_expected_realized_profit) / max(1e-9, unit_vol * qty)
        if base_profit_per_m3 > 0 and candidate_profit_per_m3 < (base_profit_per_m3 * max(0.0, cargo_fill_min_profit_per_m3_ratio)):
            continue

        if is_existing:
            confidence_payload = _candidate_confidence_payload(c)
            scaled_expected_days_total = _candidate_scaled_expected_days(c, total_qty_after)
            existing_pick["qty"] = int(existing_pick.get("qty", 0)) + qty
            existing_pick["cost"] = float(existing_pick.get("cost", 0.0)) + cost
            existing_pick["revenue_net"] = float(existing_pick.get("revenue_net", 0.0)) + revenue_net
            existing_pick["profit"] = float(existing_pick.get("profit", 0.0)) + profit
            existing_pick["buy_broker_fee_total"] = float(existing_pick.get("buy_broker_fee_total", 0.0)) + float(breakdown.buy_broker_fee_total)
            existing_pick["sell_broker_fee_total"] = float(existing_pick.get("sell_broker_fee_total", 0.0)) + float(breakdown.sell_broker_fee_total)
            existing_pick["sales_tax_total"] = float(existing_pick.get("sales_tax_total", 0.0)) + float(breakdown.sales_tax_total)
            existing_pick["scc_surcharge_total"] = float(existing_pick.get("scc_surcharge_total", 0.0)) + float(breakdown.scc_surcharge_total)
            existing_pick["relist_budget_total"] = float(existing_pick.get("relist_budget_total", 0.0)) + float(breakdown.relist_budget_total)
            existing_pick["sales_tax_isk"] = float(existing_pick.get("sales_tax_isk", 0.0)) + float(breakdown.sales_tax_isk)
            existing_pick["broker_fee_isk"] = float(existing_pick.get("broker_fee_isk", 0.0)) + float(breakdown.broker_fee_isk)
            existing_pick["scc_surcharge_isk"] = float(existing_pick.get("scc_surcharge_isk", 0.0)) + float(breakdown.scc_surcharge_isk)
            existing_pick["relist_fee_isk"] = float(existing_pick.get("relist_fee_isk", 0.0)) + float(breakdown.relist_fee_isk)
            existing_pick["instant_fill_ratio"] = float(instant_fill_ratio_after)
            existing_pick["turnover_factor"] = float(turnover_factor_after)
            existing_pick["fill_probability"] = float(fill_probability_after)
            existing_pick["dest_buy_depth_units"] = int(getattr(c, "dest_buy_depth_units", existing_pick.get("dest_buy_depth_units", 0)))
            existing_pick["order_duration_days"] = order_duration
            existing_pick["gross_profit_if_full_sell"] = float(existing_pick.get("gross_profit_if_full_sell", 0.0)) + (
                float(getattr(c, "gross_profit_if_full_sell", float(profit))) * float(scale_ratio)
            )
            existing_pick["expected_days_to_sell"] = max(
                float(existing_pick.get("expected_days_to_sell", 0.0) or 0.0),
                float(scaled_expected_days_total),
            )
            existing_pick["expected_units_sold_90d"] = float(existing_pick.get("expected_units_sold_90d", 0.0)) + (
                float(getattr(c, "expected_units_sold_90d", float(qty) * float(fill_probability_after))) * float(scale_ratio or 1.0)
            )
            existing_pick["expected_units_unsold_90d"] = float(existing_pick.get("expected_units_unsold_90d", 0.0)) + (
                float(getattr(c, "expected_units_unsold_90d", 0.0)) * float(scale_ratio)
            )
            existing_pick["expected_realized_profit_90d"] = float(existing_pick.get("expected_realized_profit_90d", 0.0)) + (
                float(scaled_expected_realized_profit)
            )
            existing_pick["estimated_sellable_units_90d"] = max(
                float(existing_pick.get("estimated_sellable_units_90d", 0.0)),
                float(getattr(c, "estimated_sellable_units_90d", float(total_qty_after))),
            )
            existing_pick["exit_confidence"] = float(
                min(
                    float(existing_pick.get("exit_confidence", 1.0)),
                    float(getattr(c, "exit_confidence", fill_probability_after)),
                )
            )
            existing_pick["liquidity_confidence"] = float(
                min(
                    float(existing_pick.get("liquidity_confidence", 1.0)),
                    float(getattr(c, "liquidity_confidence", fill_probability_after)),
                )
            )
            existing_pick["overall_confidence"] = float(
                min(
                    float(existing_pick.get("overall_confidence", 1.0)),
                    float(getattr(c, "overall_confidence", getattr(c, "strict_confidence_score", fill_probability_after))),
                )
            )
            existing_pick["transport_confidence"] = float(
                min(float(existing_pick.get("transport_confidence", 1.0)), float(confidence_payload["transport_confidence"]))
            )
            existing_pick["raw_exit_confidence"] = float(
                min(float(existing_pick.get("raw_exit_confidence", 1.0)), float(confidence_payload["raw_exit_confidence"]))
            )
            existing_pick["raw_liquidity_confidence"] = float(
                min(float(existing_pick.get("raw_liquidity_confidence", 1.0)), float(confidence_payload["raw_liquidity_confidence"]))
            )
            existing_pick["raw_transport_confidence"] = float(
                min(float(existing_pick.get("raw_transport_confidence", 1.0)), float(confidence_payload["raw_transport_confidence"]))
            )
            existing_pick["raw_overall_confidence"] = float(
                min(float(existing_pick.get("raw_overall_confidence", 1.0)), float(confidence_payload["raw_overall_confidence"]))
            )
            existing_pick["calibrated_exit_confidence"] = float(
                min(float(existing_pick.get("calibrated_exit_confidence", 1.0)), float(confidence_payload["calibrated_exit_confidence"]))
            )
            existing_pick["calibrated_liquidity_confidence"] = float(
                min(float(existing_pick.get("calibrated_liquidity_confidence", 1.0)), float(confidence_payload["calibrated_liquidity_confidence"]))
            )
            existing_pick["calibrated_transport_confidence"] = float(
                min(float(existing_pick.get("calibrated_transport_confidence", 1.0)), float(confidence_payload["calibrated_transport_confidence"]))
            )
            existing_pick["calibrated_overall_confidence"] = float(
                min(float(existing_pick.get("calibrated_overall_confidence", 1.0)), float(confidence_payload["calibrated_overall_confidence"]))
            )
            existing_pick["raw_confidence"] = float(existing_pick.get("raw_overall_confidence", confidence_payload["raw_overall_confidence"]))
            existing_pick["calibrated_confidence"] = float(
                existing_pick.get("calibrated_overall_confidence", confidence_payload["calibrated_overall_confidence"])
            )
            existing_pick["decision_overall_confidence"] = float(
                min(float(existing_pick.get("decision_overall_confidence", 1.0)), float(confidence_payload["decision_overall_confidence"]))
            )
            if str(confidence_payload["calibration_warning"]):
                existing_pick["calibration_warning"] = str(confidence_payload["calibration_warning"])
            existing_pick["market_plausibility_score"] = float(
                min(float(existing_pick.get("market_plausibility_score", 1.0)), float(getattr(c, "market_plausibility_score", 1.0)))
            )
            existing_pick["manipulation_risk_score"] = float(
                max(float(existing_pick.get("manipulation_risk_score", 0.0)), float(getattr(c, "manipulation_risk_score", 0.0)))
            )
            existing_pick["profit_at_top_of_book"] = float(existing_pick.get("profit_at_top_of_book", 0.0)) + (
                float(getattr(c, "profit_at_top_of_book", float(profit))) * float(scale_ratio or 1.0)
            )
            existing_pick["profit_at_usable_depth"] = float(existing_pick.get("profit_at_usable_depth", 0.0)) + (
                float(getattr(c, "profit_at_usable_depth", float(profit))) * float(scale_ratio or 1.0)
            )
            existing_pick["profit_at_conservative_executable_price"] = float(
                existing_pick.get("profit_at_conservative_executable_price", 0.0)
            ) + (float(getattr(c, "profit_at_conservative_executable_price", float(profit))) * float(scale_ratio or 1.0))
            if isinstance(getattr(c, "market_plausibility", {}), dict) and getattr(c, "market_plausibility", {}):
                existing_pick["market_plausibility"] = dict(getattr(c, "market_plausibility", {}))
            existing_pick["expected_profit_90d"] = float(existing_pick.get("expected_realized_profit_90d", 0.0))
            if "buy_at" not in existing_pick:
                existing_pick["buy_at"] = str(getattr(c, "route_src_label", ""))
            if "sell_at" not in existing_pick:
                existing_pick["sell_at"] = str(getattr(c, "route_dst_label", ""))
            if "route_hops" not in existing_pick:
                existing_pick["route_hops"] = int(getattr(c, "dest_hop_count", 1))
            if "carried_through_legs" not in existing_pick:
                existing_pick["carried_through_legs"] = int(getattr(c, "carried_through_legs", getattr(c, "dest_hop_count", 1)))
            if "route_src_index" not in existing_pick:
                existing_pick["route_src_index"] = int(getattr(c, "route_src_index", 0))
            if "route_dst_index" not in existing_pick:
                existing_pick["route_dst_index"] = int(getattr(c, "route_dst_index", 0))
            if "release_leg_index" not in existing_pick:
                existing_pick["release_leg_index"] = int(getattr(c, "route_dst_index", 0) - 1) if int(getattr(c, "route_dst_index", 0)) > 0 else int(existing_pick.get("release_leg_index", -1))
            total_pick_cost = float(existing_pick.get("cost", 0.0))
            total_pick_profit = float(existing_pick.get("profit", 0.0))
            total_pick_m3 = float(existing_pick.get("unit_volume", unit_vol)) * float(existing_pick.get("qty", 0))
            existing_pick["profit_pct"] = (total_pick_profit / total_pick_cost) if total_pick_cost > 0 else 0.0
            existing_pick["profit_per_m3"] = (total_pick_profit / total_pick_m3) if total_pick_m3 > 0 else 0.0
            existing_pick["profit_per_m3_per_day"] = float(existing_pick["profit_per_m3"]) * float(turnover_factor_after)
            existing_pick["expected_realized_profit_per_m3_90d"] = (
                float(existing_pick.get("expected_realized_profit_90d", 0.0)) / total_pick_m3
            ) if total_pick_m3 > 0 else 0.0
            existing_pick["expected_profit_per_m3_90d"] = float(existing_pick["expected_realized_profit_per_m3_90d"])
            ensure_record_explainability(existing_pick, max_liq_days=float(max_liq_days))
        else:
            confidence_payload = _candidate_confidence_payload(c)
            pick_profit_per_m3 = (float(profit) / float(qty) / unit_vol)
            pick_profit_per_m3_per_day = pick_profit_per_m3 * turnover_factor_after
            scaled_expected_days = _candidate_scaled_expected_days(c, qty)
            new_pick = {
                "type_id": c.type_id,
                "name": c.name,
                "qty": qty,
                "unit_volume": unit_vol,
                "buy_avg": c.buy_avg,
                "sell_avg": c.sell_avg,
                "cost": cost,
                "revenue_net": revenue_net,
                "profit": profit,
                "profit_pct": profit / cost if cost > 0 else 0.0,
                "buy_broker_fee_total": float(breakdown.buy_broker_fee_total),
                "sell_broker_fee_total": float(breakdown.sell_broker_fee_total),
                "sales_tax_total": float(breakdown.sales_tax_total),
                "scc_surcharge_total": float(breakdown.scc_surcharge_total),
                "relist_budget_total": float(breakdown.relist_budget_total),
                "sales_tax_isk": float(breakdown.sales_tax_isk),
                "broker_fee_isk": float(breakdown.broker_fee_isk),
                "scc_surcharge_isk": float(breakdown.scc_surcharge_isk),
                "relist_fee_isk": float(breakdown.relist_fee_isk),
                "instant": c.instant,
                "suggested_sell_price": c.suggested_sell_price,
                "order_duration_days": order_duration,
                "liquidity_score": c.liquidity_score,
                "history_volume_30d": c.history_volume_30d,
                "daily_volume": c.daily_volume,
                "dest_buy_depth_units": c.dest_buy_depth_units,
                "instant_fill_ratio": instant_fill_ratio_after,
                "competition_price_levels_near_best": c.competition_price_levels_near_best,
                "queue_ahead_units": c.queue_ahead_units,
                "fill_probability": fill_probability_after,
                "turnover_factor": turnover_factor_after,
                "profit_per_m3": pick_profit_per_m3,
                "profit_per_m3_per_day": pick_profit_per_m3_per_day,
                "mode": getattr(c, "mode", "instant"),
                "target_sell_price": float(getattr(c, "target_sell_price", 0.0)),
                "avg_daily_volume_30d": float(getattr(c, "avg_daily_volume_30d", 0.0)),
                "avg_daily_volume_7d": float(getattr(c, "avg_daily_volume_7d", 0.0)),
                "expected_days_to_sell": float(scaled_expected_days),
                "sell_through_ratio_90d": float(getattr(c, "sell_through_ratio_90d", 0.0)),
                "risk_score": float(getattr(c, "risk_score", 0.0)),
                "gross_profit_if_full_sell": float(getattr(c, "gross_profit_if_full_sell", float(profit))) * float(scale_ratio or 1.0),
                "expected_units_sold_90d": float(getattr(c, "expected_units_sold_90d", float(qty) * float(fill_probability_after))) * float(scale_ratio or 1.0),
                "expected_units_unsold_90d": float(getattr(c, "expected_units_unsold_90d", 0.0)) * float(scale_ratio or 1.0),
                "expected_realized_profit_90d": float(scaled_expected_realized_profit),
                "expected_realized_profit_per_m3_90d": float(
                    float(scaled_expected_realized_profit)
                ) / max(1e-9, float(qty) * float(unit_vol)),
                "estimated_sellable_units_90d": float(getattr(c, "estimated_sellable_units_90d", float(qty))),
                "exit_confidence": float(getattr(c, "exit_confidence", fill_probability_after)),
                "liquidity_confidence": float(getattr(c, "liquidity_confidence", fill_probability_after)),
                "overall_confidence": float(getattr(c, "overall_confidence", getattr(c, "strict_confidence_score", fill_probability_after))),
                "market_plausibility": dict(getattr(c, "market_plausibility", {})),
                "market_plausibility_score": float(getattr(c, "market_plausibility_score", 1.0)),
                "manipulation_risk_score": float(getattr(c, "manipulation_risk_score", 0.0)),
                "profit_at_top_of_book": float(getattr(c, "profit_at_top_of_book", float(profit))) * float(scale_ratio or 1.0),
                "profit_at_usable_depth": float(getattr(c, "profit_at_usable_depth", float(profit))) * float(scale_ratio or 1.0),
                "profit_at_conservative_executable_price": float(
                    getattr(c, "profit_at_conservative_executable_price", float(profit))
                ) * float(scale_ratio or 1.0),
                **confidence_payload,
                "expected_profit_90d": float(scaled_expected_realized_profit),
                "expected_profit_per_m3_90d": float(
                    float(scaled_expected_realized_profit)
                    / max(1e-9, float(qty) * float(unit_vol))
                ),
                "used_volume_fallback": bool(getattr(c, "used_volume_fallback", False)),
                "reference_price": float(getattr(c, "reference_price", 0.0)),
                "reference_price_average": float(getattr(c, "reference_price_average", 0.0)),
                "reference_price_adjusted": float(getattr(c, "reference_price_adjusted", 0.0)),
                "jita_split_price": float(getattr(c, "jita_split_price", 0.0)),
                "reference_price_source": str(getattr(c, "reference_price_source", "")),
                "buy_discount_vs_ref": float(getattr(c, "buy_discount_vs_ref", 0.0)),
                "sell_markup_vs_ref": float(getattr(c, "sell_markup_vs_ref", 0.0)),
                "reference_price_penalty": float(getattr(c, "reference_price_penalty", 0.0)),
                "strict_confidence_score": float(getattr(c, "strict_confidence_score", 0.0)),
                "strict_mode_enabled": bool(getattr(c, "strict_mode_enabled", False)),
                "exit_type": str(getattr(c, "exit_type", "instant" if bool(getattr(c, "instant", True)) else "speculative")),
                "target_price_basis": str(getattr(c, "target_price_basis", "")),
                "target_price_confidence": float(getattr(c, "target_price_confidence", 0.0)),
                "estimated_transport_cost": float(getattr(c, "estimated_transport_cost", 0.0)),
                "buy_at": str(getattr(c, "route_src_label", "")),
                "sell_at": str(getattr(c, "route_dst_label", "")),
                "route_hops": int(getattr(c, "dest_hop_count", 1)),
                "carried_through_legs": int(getattr(c, "carried_through_legs", getattr(c, "dest_hop_count", 1))),
                "route_src_index": int(getattr(c, "route_src_index", 0)),
                "route_dst_index": int(getattr(c, "route_dst_index", 0)),
                "extra_leg_penalty": float(getattr(c, "extra_leg_penalty", 0.0)),
                "route_wide_selected": bool(getattr(c, "route_wide_selected", False)),
                "route_adjusted_score": float(getattr(c, "route_adjusted_score", 0.0)),
                "release_leg_index": int(getattr(c, "route_dst_index", 0) - 1) if int(getattr(c, "route_dst_index", 0)) > 0 else -1
            }
            ensure_record_explainability(new_pick, max_liq_days=float(max_liq_days))
            picks.append(new_pick)
            picks_by_type[tid] = new_pick
            added_new_types += 1

        total_cost += cost
        total_profit += float(scaled_expected_realized_profit)
        total_m3 += (unit_vol * qty)
        remaining_budget -= cost
        remaining_cargo -= (unit_vol * qty)
        spent_by_type[tid] = already_for_item + cost
        added += 1

    return picks, total_cost, total_profit, total_m3, added

def build_portfolio(
    candidates: list[TradeCandidate],
    budget_isk: int,
    cargo_m3: float,
    fees: dict,
    filters: dict,
    portfolio_cfg: dict,
    cfg: dict | None = None
):
    buy_broker = float(fees["buy_broker_fee"])
    max_turnover_factor = float(filters.get("max_turnover_factor", 3.0))
    min_instant_fill_ratio = float(filters.get("min_instant_fill_ratio", 0.0))
    max_share = float(portfolio_cfg["max_item_share_of_budget"])
    max_items = int(portfolio_cfg["max_items"])
    max_liq_days = float(
        portfolio_cfg.get(
            "max_liquidation_days_per_position",
            filters.get("max_expected_days_to_sell", 99999.0),
        )
    )
    demand_share_cap = float(
        portfolio_cfg.get(
            "max_share_of_estimated_demand_per_position",
            filters.get("max_share_of_estimated_demand_per_position", 1.0),
        )
    )
    order_duration = int(filters.get("order_duration_days", 90))
    relist_budget_pct = float(filters.get("relist_budget_pct", fees.get("relist_budget_pct", 0.0)))
    relist_budget_isk = float(filters.get("relist_budget_isk", fees.get("relist_budget_isk", 0.0)))

    remaining_budget = float(budget_isk)
    remaining_cargo = float(cargo_m3)

    picks = []
    spent_by_type = {}

    def run_candidates_loop():
        """Build portfolio from the provided candidate list."""
        nonlocal remaining_budget, remaining_cargo, picks
        remaining_budget = float(budget_isk)
        remaining_cargo = float(cargo_m3)
        picks = []
        spent_by_type.clear()

        ordered_candidates = sorted(
            list(candidates),
            key=lambda c: (
                _candidate_selection_score(c, max_liq_days),
                _candidate_expected_realized_profit(c),
                _candidate_confidence(c),
            ),
            reverse=True,
        )[: max_items * 8]

        for c in ordered_candidates:
            if remaining_budget <= 0 or remaining_cargo <= 0:
                break
            if _candidate_expected_days(c) > max_liq_days:
                continue

            max_budget_for_item = budget_isk * max_share
            already_for_item = spent_by_type.get(c.type_id, 0.0)
            unit_cost = c.buy_avg * (1.0 + buy_broker)
            if unit_cost <= 0:
                continue

            max_by_budget = int(remaining_budget // unit_cost)
            max_by_share = int((max_budget_for_item - already_for_item) // unit_cost)
            max_by_cargo = int(remaining_cargo // c.unit_volume)
            max_by_demand = _candidate_max_qty_by_demand(c, demand_share_cap)
            qty = min(max_by_demand, max_by_budget, max_by_share, max_by_cargo)

            if qty <= 0:
                continue

            mode_str = str(getattr(c, "mode", "instant"))
            execution = "instant_instant" if mode_str.lower() == "instant" else "instant_listed"
            breakdown = FeeEngine(fees).compute(
                buy_price=c.buy_avg,
                sell_price=c.sell_avg,
                qty=qty,
                execution=execution,
                relist_budget_pct=relist_budget_pct if execution == "instant_listed" else 0.0,
                relist_budget_isk=(relist_budget_isk if mode_str.lower() == "planned_sell" else 0.0),
            )
            cost = float(breakdown.cost_net)
            revenue_net = float(breakdown.revenue_net)
            profit = float(breakdown.profit)

            if profit <= 0:
                continue

            scale_ratio = _candidate_scale_ratio(c, qty)
            scaled_expected_days = _candidate_scaled_expected_days(c, qty)
            if scaled_expected_days > max_liq_days:
                continue

            pick_profit_per_m3 = (float(profit) / float(qty) / float(c.unit_volume)) if qty > 0 and c.unit_volume > 0 else 0.0
            if c.instant:
                instant_fill_ratio = min(1.0, float(c.dest_buy_depth_units) / max(1.0, float(qty)))
                if instant_fill_ratio < min_instant_fill_ratio:
                    continue
                turnover_factor = min(max_turnover_factor, max(0.0, instant_fill_ratio))
                fill_probability = instant_fill_ratio
            else:
                instant_fill_ratio = 0.0  # not applicable for planned/listed sells
                turnover_factor = float(c.turnover_factor)
                fill_probability = float(c.fill_probability)
            pick_profit_per_m3_per_day = pick_profit_per_m3 * turnover_factor
            expected_realized_profit = float(getattr(c, "expected_realized_profit_90d", getattr(c, "expected_profit_90d", profit))) * float(scale_ratio or 1.0)
            expected_units_sold = float(getattr(c, "expected_units_sold_90d", float(qty) * float(fill_probability))) * float(scale_ratio or 1.0)
            expected_units_unsold = float(getattr(c, "expected_units_unsold_90d", 0.0)) * float(scale_ratio or 1.0)
            confidence_payload = _candidate_confidence_payload(c)
            new_pick = {
                "type_id": c.type_id,
                "name": c.name,
                "qty": qty,
                "unit_volume": c.unit_volume,
                "buy_avg": c.buy_avg,
                "sell_avg": c.sell_avg,
                "cost": cost,
                "revenue_net": revenue_net,
                "profit": profit,
                "profit_pct": profit / cost if cost > 0 else 0.0,
                "buy_broker_fee_total": float(breakdown.buy_broker_fee_total),
                "sell_broker_fee_total": float(breakdown.sell_broker_fee_total),
                "sales_tax_total": float(breakdown.sales_tax_total),
                "scc_surcharge_total": float(breakdown.scc_surcharge_total),
                "relist_budget_total": float(breakdown.relist_budget_total),
                "sales_tax_isk": float(breakdown.sales_tax_isk),
                "broker_fee_isk": float(breakdown.broker_fee_isk),
                "scc_surcharge_isk": float(breakdown.scc_surcharge_isk),
                "relist_fee_isk": float(breakdown.relist_fee_isk),
                "instant": c.instant,
                "suggested_sell_price": c.suggested_sell_price,
                "order_duration_days": order_duration,
                "liquidity_score": c.liquidity_score,
                "history_volume_30d": c.history_volume_30d,
                "history_order_count_30d": c.history_order_count_30d,
                "daily_volume": c.daily_volume,
                "dest_buy_depth_units": c.dest_buy_depth_units,
                "instant_fill_ratio": instant_fill_ratio,
                "competition_price_levels_near_best": c.competition_price_levels_near_best,
                "queue_ahead_units": c.queue_ahead_units,
                "spread_pct": float(getattr(c, "spread_pct", 0.0)),
                "depth_within_2pct_buy": int(getattr(c, "depth_within_2pct_buy", 0)),
                "depth_within_2pct_sell": int(getattr(c, "depth_within_2pct_sell", 0)),
                "orderbook_imbalance": float(getattr(c, "orderbook_imbalance", 0.0)),
                "competition_density_near_best": int(getattr(c, "competition_density_near_best", 0)),
                "fill_probability": fill_probability,
                "turnover_factor": turnover_factor,
                "profit_per_m3": pick_profit_per_m3,
                "profit_per_m3_per_day": pick_profit_per_m3_per_day,
                "mode": getattr(c, "mode", "instant"),
                "exit_type": str(getattr(c, "exit_type", "instant" if bool(getattr(c, "instant", True)) else "speculative")),
                "target_sell_price": float(getattr(c, "target_sell_price", 0.0)),
                "target_price_basis": str(getattr(c, "target_price_basis", "")),
                "target_price_confidence": float(getattr(c, "target_price_confidence", 0.0)),
                "avg_daily_volume_30d": float(getattr(c, "avg_daily_volume_30d", 0.0)),
                "avg_daily_volume_7d": float(getattr(c, "avg_daily_volume_7d", 0.0)),
                "expected_days_to_sell": float(scaled_expected_days),
                "sell_through_ratio_90d": float(getattr(c, "sell_through_ratio_90d", 0.0)),
                "risk_score": float(getattr(c, "risk_score", 0.0)),
                "gross_profit_if_full_sell": float(getattr(c, "gross_profit_if_full_sell", profit)) * float(scale_ratio or 1.0),
                "expected_units_sold_90d": float(expected_units_sold),
                "expected_units_unsold_90d": float(expected_units_unsold),
                "expected_realized_profit_90d": float(expected_realized_profit),
                "expected_realized_profit_per_m3_90d": float(expected_realized_profit / max(1e-9, float(qty) * float(c.unit_volume))),
                "estimated_sellable_units_90d": float(getattr(c, "estimated_sellable_units_90d", float(qty))),
                "exit_confidence": float(getattr(c, "exit_confidence", fill_probability)),
                "liquidity_confidence": float(getattr(c, "liquidity_confidence", fill_probability)),
                "overall_confidence": float(getattr(c, "overall_confidence", getattr(c, "strict_confidence_score", fill_probability))),
                "market_plausibility": dict(getattr(c, "market_plausibility", {})),
                "market_plausibility_score": float(getattr(c, "market_plausibility_score", 1.0)),
                "manipulation_risk_score": float(getattr(c, "manipulation_risk_score", 0.0)),
                "profit_at_top_of_book": float(getattr(c, "profit_at_top_of_book", float(profit))) * float(scale_ratio or 1.0),
                "profit_at_usable_depth": float(getattr(c, "profit_at_usable_depth", float(profit))) * float(scale_ratio or 1.0),
                "profit_at_conservative_executable_price": float(
                    getattr(c, "profit_at_conservative_executable_price", float(profit))
                ) * float(scale_ratio or 1.0),
                **confidence_payload,
                "expected_profit_90d": float(expected_realized_profit),
                "expected_profit_per_m3_90d": float(expected_realized_profit / max(1e-9, float(qty) * float(c.unit_volume))),
                "used_volume_fallback": bool(getattr(c, "used_volume_fallback", False)),
                "reference_price": float(getattr(c, "reference_price", 0.0)),
                "reference_price_average": float(getattr(c, "reference_price_average", 0.0)),
                "reference_price_adjusted": float(getattr(c, "reference_price_adjusted", 0.0)),
                "jita_split_price": float(getattr(c, "jita_split_price", 0.0)),
                "reference_price_source": str(getattr(c, "reference_price_source", "")),
                "buy_discount_vs_ref": float(getattr(c, "buy_discount_vs_ref", 0.0)),
                "sell_markup_vs_ref": float(getattr(c, "sell_markup_vs_ref", 0.0)),
                "reference_price_penalty": float(getattr(c, "reference_price_penalty", 0.0)),
                "strict_confidence_score": float(getattr(c, "strict_confidence_score", 0.0)),
                "strict_mode_enabled": bool(getattr(c, "strict_mode_enabled", False)),
                "estimated_transport_cost": float(getattr(c, "estimated_transport_cost", 0.0)) * float(scale_ratio or 1.0),
                "buy_at": str(getattr(c, "route_src_label", "")),
                "sell_at": str(getattr(c, "route_dst_label", "")),
                "route_hops": int(getattr(c, "dest_hop_count", 1)),
                "carried_through_legs": int(getattr(c, "carried_through_legs", getattr(c, "dest_hop_count", 1))),
                "route_src_index": int(getattr(c, "route_src_index", 0)),
                "route_dst_index": int(getattr(c, "route_dst_index", 0)),
                "extra_leg_penalty": float(getattr(c, "extra_leg_penalty", 0.0)),
                "route_wide_selected": bool(getattr(c, "route_wide_selected", False)),
                "route_adjusted_score": float(getattr(c, "route_adjusted_score", 0.0)),
                "release_leg_index": int(getattr(c, "route_dst_index", 0) - 1) if int(getattr(c, "route_dst_index", 0)) > 0 else -1
            }
            ensure_record_explainability(new_pick, max_liq_days=float(max_liq_days))
            if not validate_portfolio(picks + [new_pick], budget_isk, cargo_m3, portfolio_cfg):
                continue

            picks.append(new_pick)

            remaining_budget -= cost
            remaining_cargo -= c.unit_volume * qty
            spent_by_type[c.type_id] = already_for_item + cost

            if len(picks) >= max_items:
                break

    # initial pass
    run_candidates_loop()

    total_cost = sum(p["cost"] for p in picks)
    total_profit = _portfolio_expected_realized_profit(picks)
    total_m3 = sum(p["unit_volume"] * p["qty"] for p in picks)

    # attempt local search to improve the portfolio
    # convert candidate objects to pick-like dicts so local_search works on the
    # same data shape as `picks` (some callers may pass TradeCandidate objects)
    candidate_dicts = []
    for c in candidates:
        try:
            # if c is a TradeCandidate dataclass-like object
            type_id = getattr(c, 'type_id', None) or c.get('type_id')
            name = getattr(c, 'name', None) or c.get('name', '')
            unit_volume = float(getattr(c, 'unit_volume', None) or c.get('unit_volume', 0.0))
            buy_avg = float(getattr(c, 'buy_avg', None) or c.get('buy_avg', 0.0))
            sell_avg = float(getattr(c, 'sell_avg', None) or c.get('sell_avg', 0.0))
            max_units = int(getattr(c, 'max_units', None) or c.get('max_units', 0))
        except Exception:
            continue
        # guess a reasonable qty for the prototype (bounded by max_units)
        unit_cost = buy_avg * (1.0 + buy_broker) if buy_avg > 0 else 0.0
        max_units = min(max_units, _candidate_max_qty_by_demand(c, demand_share_cap))
        if _candidate_expected_days(c) > max_liq_days:
            continue
        if unit_cost > 0:
            proto_qty = max(1, min(max_units, int(budget_isk // unit_cost)))
        else:
            proto_qty = min(1, max_units)
        cost = unit_cost * proto_qty
        instant_flag = getattr(c, 'instant', c.get('instant', True) if isinstance(c, dict) else True)
        mode_value = getattr(c, "mode", None)
        if mode_value is None and isinstance(c, dict):
            mode_value = c.get("mode", "instant")
        mode_str = str(mode_value or "instant")
        execution = "instant_instant" if mode_str.lower() == "instant" else "instant_listed"
        breakdown = FeeEngine(fees).compute(
            buy_price=buy_avg,
            sell_price=sell_avg,
            qty=proto_qty,
            execution=execution,
            relist_budget_pct=relist_budget_pct if execution == "instant_listed" else 0.0,
            relist_budget_isk=(relist_budget_isk if mode_str.lower() == "planned_sell" else 0.0),
        )
        revenue_net = float(breakdown.revenue_net)
        profit = float(breakdown.profit)
        scale_ratio = _candidate_scale_ratio(c, proto_qty)
        expected_realized_profit = _candidate_expected_realized_profit(c) * float(scale_ratio or 1.0)
        confidence_payload = _candidate_confidence_payload(c)
        candidate_dict = {
            'type_id': int(type_id), 'name': name, 'qty': proto_qty,
            'unit_volume': unit_volume, 'buy_avg': buy_avg, 'sell_avg': sell_avg,
            'cost': cost, 'revenue_net': revenue_net, 'profit': profit,
            'profit_pct': profit / cost if cost > 0 else 0.0,
            "buy_broker_fee_total": float(breakdown.buy_broker_fee_total),
            "sell_broker_fee_total": float(breakdown.sell_broker_fee_total),
            "sales_tax_total": float(breakdown.sales_tax_total),
            "scc_surcharge_total": float(breakdown.scc_surcharge_total),
            "relist_budget_total": float(breakdown.relist_budget_total),
            "sales_tax_isk": float(breakdown.sales_tax_isk),
            "broker_fee_isk": float(breakdown.broker_fee_isk),
            "scc_surcharge_isk": float(breakdown.scc_surcharge_isk),
            "relist_fee_isk": float(breakdown.relist_fee_isk),
            'instant': instant_flag,
            'suggested_sell_price': getattr(c, 'suggested_sell_price', c.get('suggested_sell_price', None) if isinstance(c, dict) else None),
            'order_duration_days': order_duration,
            'liquidity_score': getattr(c, 'liquidity_score', c.get('liquidity_score', 0) if isinstance(c, dict) else 0),
            'history_volume_30d': getattr(c, 'history_volume_30d', c.get('history_volume_30d', 0) if isinstance(c, dict) else 0),
            'daily_volume': getattr(c, 'daily_volume', c.get('daily_volume', 0.0) if isinstance(c, dict) else 0.0),
            'dest_buy_depth_units': getattr(c, 'dest_buy_depth_units', c.get('dest_buy_depth_units', 0) if isinstance(c, dict) else 0),
            'instant_fill_ratio': getattr(c, 'instant_fill_ratio', c.get('instant_fill_ratio', 1.0) if isinstance(c, dict) else 1.0),
            'competition_price_levels_near_best': getattr(c, 'competition_price_levels_near_best', c.get('competition_price_levels_near_best', 0) if isinstance(c, dict) else 0),
            'queue_ahead_units': getattr(c, 'queue_ahead_units', c.get('queue_ahead_units', 0) if isinstance(c, dict) else 0),
            'fill_probability': getattr(c, 'fill_probability', c.get('fill_probability', 0.0) if isinstance(c, dict) else 0.0),
            'turnover_factor': getattr(c, 'turnover_factor', c.get('turnover_factor', 0.0) if isinstance(c, dict) else 0.0),
            'profit_per_m3': getattr(c, 'profit_per_m3', c.get('profit_per_m3', 0.0) if isinstance(c, dict) else 0.0),
            'profit_per_m3_per_day': getattr(c, 'profit_per_m3_per_day', c.get('profit_per_m3_per_day', 0.0) if isinstance(c, dict) else 0.0),
            'mode': getattr(c, 'mode', c.get('mode', 'instant') if isinstance(c, dict) else 'instant'),
            'target_sell_price': getattr(c, 'target_sell_price', c.get('target_sell_price', 0.0) if isinstance(c, dict) else 0.0),
            'avg_daily_volume_30d': getattr(c, 'avg_daily_volume_30d', c.get('avg_daily_volume_30d', 0.0) if isinstance(c, dict) else 0.0),
            'avg_daily_volume_7d': getattr(c, 'avg_daily_volume_7d', c.get('avg_daily_volume_7d', 0.0) if isinstance(c, dict) else 0.0),
            'expected_days_to_sell': getattr(c, 'expected_days_to_sell', c.get('expected_days_to_sell', 0.0) if isinstance(c, dict) else 0.0),
            'sell_through_ratio_90d': getattr(c, 'sell_through_ratio_90d', c.get('sell_through_ratio_90d', 0.0) if isinstance(c, dict) else 0.0),
            'risk_score': getattr(c, 'risk_score', c.get('risk_score', 0.0) if isinstance(c, dict) else 0.0),
            'gross_profit_if_full_sell': getattr(c, 'gross_profit_if_full_sell', c.get('gross_profit_if_full_sell', profit) if isinstance(c, dict) else profit) * float(scale_ratio or 1.0),
            'expected_units_sold_90d': getattr(c, 'expected_units_sold_90d', c.get('expected_units_sold_90d', proto_qty) if isinstance(c, dict) else proto_qty) * float(scale_ratio or 1.0),
            'expected_units_unsold_90d': getattr(c, 'expected_units_unsold_90d', c.get('expected_units_unsold_90d', 0.0) if isinstance(c, dict) else 0.0) * float(scale_ratio or 1.0),
            'expected_realized_profit_90d': expected_realized_profit,
            'expected_realized_profit_per_m3_90d': expected_realized_profit / max(1e-9, unit_volume * proto_qty),
            'estimated_sellable_units_90d': getattr(c, 'estimated_sellable_units_90d', c.get('estimated_sellable_units_90d', proto_qty) if isinstance(c, dict) else proto_qty),
            'exit_confidence': getattr(c, 'exit_confidence', c.get('exit_confidence', 0.0) if isinstance(c, dict) else 0.0),
            'liquidity_confidence': getattr(c, 'liquidity_confidence', c.get('liquidity_confidence', 0.0) if isinstance(c, dict) else 0.0),
            'overall_confidence': getattr(c, 'overall_confidence', c.get('overall_confidence', 0.0) if isinstance(c, dict) else 0.0),
            'market_plausibility': dict(getattr(c, 'market_plausibility', c.get('market_plausibility', {}) if isinstance(c, dict) else {})),
            'market_plausibility_score': getattr(c, 'market_plausibility_score', c.get('market_plausibility_score', 1.0) if isinstance(c, dict) else 1.0),
            'manipulation_risk_score': getattr(c, 'manipulation_risk_score', c.get('manipulation_risk_score', 0.0) if isinstance(c, dict) else 0.0),
            'profit_at_top_of_book': getattr(c, 'profit_at_top_of_book', c.get('profit_at_top_of_book', profit) if isinstance(c, dict) else profit),
            'profit_at_usable_depth': getattr(c, 'profit_at_usable_depth', c.get('profit_at_usable_depth', profit) if isinstance(c, dict) else profit),
            'profit_at_conservative_executable_price': getattr(c, 'profit_at_conservative_executable_price', c.get('profit_at_conservative_executable_price', profit) if isinstance(c, dict) else profit),
            **confidence_payload,
            'expected_profit_90d': expected_realized_profit,
            'expected_profit_per_m3_90d': expected_realized_profit / max(1e-9, unit_volume * proto_qty),
            'used_volume_fallback': getattr(c, 'used_volume_fallback', c.get('used_volume_fallback', False) if isinstance(c, dict) else False),
            'reference_price': getattr(c, 'reference_price', c.get('reference_price', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_average': getattr(c, 'reference_price_average', c.get('reference_price_average', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_adjusted': getattr(c, 'reference_price_adjusted', c.get('reference_price_adjusted', 0.0) if isinstance(c, dict) else 0.0),
            'jita_split_price': getattr(c, 'jita_split_price', c.get('jita_split_price', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_source': getattr(c, 'reference_price_source', c.get('reference_price_source', "") if isinstance(c, dict) else ""),
            'buy_discount_vs_ref': getattr(c, 'buy_discount_vs_ref', c.get('buy_discount_vs_ref', 0.0) if isinstance(c, dict) else 0.0),
            'sell_markup_vs_ref': getattr(c, 'sell_markup_vs_ref', c.get('sell_markup_vs_ref', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_penalty': getattr(c, 'reference_price_penalty', c.get('reference_price_penalty', 0.0) if isinstance(c, dict) else 0.0),
            'strict_confidence_score': getattr(c, 'strict_confidence_score', c.get('strict_confidence_score', 0.0) if isinstance(c, dict) else 0.0),
            'strict_mode_enabled': getattr(c, 'strict_mode_enabled', c.get('strict_mode_enabled', False) if isinstance(c, dict) else False),
            'exit_type': getattr(c, 'exit_type', c.get('exit_type', 'instant') if isinstance(c, dict) else 'instant'),
            'target_price_basis': getattr(c, 'target_price_basis', c.get('target_price_basis', '') if isinstance(c, dict) else ''),
            'target_price_confidence': getattr(c, 'target_price_confidence', c.get('target_price_confidence', 0.0) if isinstance(c, dict) else 0.0),
            'estimated_transport_cost': getattr(c, 'estimated_transport_cost', c.get('estimated_transport_cost', 0.0) if isinstance(c, dict) else 0.0) * float(scale_ratio or 1.0),
            'buy_at': getattr(c, 'route_src_label', c.get('buy_at', "") if isinstance(c, dict) else ""),
            'sell_at': getattr(c, 'route_dst_label', c.get('sell_at', "") if isinstance(c, dict) else ""),
            'route_hops': getattr(c, 'dest_hop_count', c.get('route_hops', 1) if isinstance(c, dict) else 1),
            'carried_through_legs': getattr(c, 'carried_through_legs', c.get('carried_through_legs', 1) if isinstance(c, dict) else 1),
            'route_src_index': getattr(c, 'route_src_index', c.get('route_src_index', 0) if isinstance(c, dict) else 0),
            'route_dst_index': getattr(c, 'route_dst_index', c.get('route_dst_index', 0) if isinstance(c, dict) else 0),
            'extra_leg_penalty': getattr(c, 'extra_leg_penalty', c.get('extra_leg_penalty', 0.0) if isinstance(c, dict) else 0.0),
            'route_wide_selected': getattr(c, 'route_wide_selected', c.get('route_wide_selected', False) if isinstance(c, dict) else False),
            'route_adjusted_score': getattr(c, 'route_adjusted_score', c.get('route_adjusted_score', 0.0) if isinstance(c, dict) else 0.0)
        }
        ensure_record_explainability(candidate_dict, max_liq_days=float(max_liq_days))
        candidate_dicts.append(candidate_dict)

    optimized = local_search_optimize(picks, candidate_dicts, budget_isk, cargo_m3, portfolio_cfg)
    if optimized is not picks:
        opt_cost, opt_profit, opt_m3, _ = portfolio_stats(optimized)
        if _portfolio_objective(optimized, budget_isk, portfolio_cfg) > _portfolio_objective(picks, budget_isk, portfolio_cfg) + 1e-6:
            picks = optimized
            total_cost = opt_cost
            total_profit = opt_profit
            total_m3 = opt_m3
            print(f"  Portfolio improved by local search: {fmt_isk(total_profit)} profit")

    # Apply strategy mode if cfg provided
    if cfg:
        apply_strategy_mode(cfg, filters, picks)

    print(f"  Portfolio built: {len(picks)} items, {fmt_isk(total_profit)} profit")
    return picks, total_cost, total_profit, total_m3

def choose_portfolio_for_route(
    esi,
    route_label: str,
    source_orders: list[dict],
    dest_orders: list[dict],
    candidates: list[TradeCandidate],
    filters_used: dict,
    dest_structure_id: int,
    budget_isk: float,
    cargo_m3: float,
    fees: dict,
    port_cfg: dict,
    cfg: dict
) -> tuple[list[dict], float, float, float, str]:
    def build_from_candidates(cands, f_used):
        inst = [c for c in cands if c.instant]
        all_p, all_c, all_pr, all_m = build_portfolio(cands, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
        p, c, pr, m, md = all_p, all_c, all_pr, all_m, ("mixed" if len(inst) != len(cands) else "fallback")
        if inst and len(inst) != len(cands):
            inst_p, inst_c, inst_pr, inst_m = build_portfolio(inst, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            if _portfolio_objective(inst_p, budget_isk, port_cfg) >= _portfolio_objective(all_p, budget_isk, port_cfg):
                p, c, pr, m, md = inst_p, inst_c, inst_pr, inst_m, "instant"
        p.sort(
            key=lambda x: (
                float(x.get("expected_realized_profit_90d", x.get("expected_profit_90d", x.get("profit", 0.0))) or 0.0),
                float(x.get("decision_overall_confidence", x.get("calibrated_overall_confidence", x.get("overall_confidence", x.get("strict_confidence_score", 0.0)))) or 0.0),
                -float(x.get("expected_days_to_sell", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return p, c, pr, m, md

    picks, cost, profit, m3, mode = build_from_candidates(candidates, filters_used)
    target_util = float(port_cfg.get("target_budget_utilization", 0.0))
    util = (cost / budget_isk) if budget_isk > 0 else 1.0
    strict_active = bool(filters_used.get("strict_mode_enabled", False))
    if (not strict_active) and target_util > 0 and util < (target_util - 0.05):
        relaxed = dict(filters_used)
        relaxed["min_profit_pct"] = max(0.0, float(filters_used.get("min_profit_pct", 0.0)) - 0.01)
        relaxed["min_profit_isk_total"] = max(0.0, float(filters_used.get("min_profit_isk_total", 0.0)) * 0.5)
        print(
            f"    Hinweis: {route_label} nutzt nur {util*100:.1f}% Budget "
            f"(Ziel {target_util*100:.1f}%), berechne mit gelockerten Schwellwerten..."
        )
        relaxed_candidates = compute_candidates(
            esi, source_orders, dest_orders, fees, relaxed, dest_structure_id=dest_structure_id
        )
        calibration_model = _confidence_calibration_model(cfg)
        src_label, _, dst_label = route_label.partition("->")
        for candidate in list(relaxed_candidates or []):
            apply_calibration_to_record(
                candidate,
                calibration_model,
                route_id=str(route_label),
                source_market=str(src_label).strip(),
                target_market=str(dst_label).strip(),
                exit_type=str(getattr(candidate, "exit_type", "") or ""),
                transport_confidence=1.0,
            )
        r_picks, r_cost, r_profit, r_m3, r_mode = build_from_candidates(relaxed_candidates, relaxed)
        if r_cost > cost and r_profit >= (profit * 0.95):
            print("    Gelockerte Schwellwerte liefern bessere Auslastung, Portfolio wurde aktualisiert.")
            picks, cost, profit, m3, mode = r_picks, r_cost, r_profit, r_m3, r_mode

    cargo_fill_enabled = bool(port_cfg.get("cargo_fill_enabled", False))
    cargo_fill_trigger_gap = float(port_cfg.get("cargo_fill_trigger_gap", 0.20))
    cargo_fill_profit_floor_ratio = float(port_cfg.get("cargo_fill_profit_floor_ratio", 0.90))
    target_cargo_util = float(port_cfg.get("target_cargo_utilization", 0.0))
    cargo_util = (m3 / cargo_m3) if cargo_m3 > 0 else 1.0
    cargo_gap = target_cargo_util - cargo_util
    if (
        cargo_fill_enabled
        and target_cargo_util > 0.0
        and cargo_m3 > 0.0
        and cargo_gap >= cargo_fill_trigger_gap
        and cost < budget_isk
        and m3 < cargo_m3
    ):
        print(
            f"    Hinweis: {route_label} nutzt nur {cargo_util*100:.1f}% Cargo "
            f"(Ziel {target_cargo_util*100:.1f}%), starte Cargo-Fill..."
        )
        f_picks, f_cost, f_profit, f_m3, added = try_cargo_fill(
            picks, candidates, budget_isk, cargo_m3, fees, filters_used, port_cfg
        )
        min_allowed_profit = float(profit) * max(0.0, cargo_fill_profit_floor_ratio)
        if added > 0 and f_m3 > (m3 + 1e-6) and f_profit >= min_allowed_profit:
            print(
                "    Cargo-Fill verbessert Auslastung bei ausreichender Profitqualitaet, "
                "Portfolio wurde aktualisiert."
            )
            picks, cost, profit, m3 = f_picks, f_cost, f_profit, f_m3
        else:
            print("    Cargo-Fill verworfen (kein ausreichender Cargo-Gewinn oder Profitfloor unterschritten).")
    return picks, cost, profit, m3, mode


__all__ = [
    'portfolio_stats',
    'validate_portfolio',
    'local_search_optimize',
    'sort_picks_for_output',
    '_sort_candidates_for_cargo_fill',
    'try_cargo_fill',
    'build_portfolio',
    'choose_portfolio_for_route',
]
