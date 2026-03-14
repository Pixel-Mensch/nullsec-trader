"""Risk profiles for the Nullsec Trader Tool.

Each profile defines concrete parameter overrides that affect:
  - Candidate selection (filter tightening or relaxing)
  - Portfolio construction (item count, budget concentration caps)
  - Route ranking (score multipliers based on risk tolerance)

Profile selection priority:
  1. Environment variable NULLSEC_RISK_PROFILE
  2. CLI argument --profile (stored as cfg["_cli_risk_profile"])
  3. config.json / config.local.json key "risk_profile": {"name": "..."}
  4. Default: "balanced"
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Built-in profile definitions
# ---------------------------------------------------------------------------

# Parameter reference (all keys optional - None / 0 means "use config default"):
#
#  Candidate filter overrides
#  --------------------------
#  min_confidence                   float  0-1    decision_overall_confidence gate
#  min_fill_probability             float  0-1    fill_probability gate (instant proxy)
#  max_expected_days_to_sell        float  days   hard ceiling on sell duration
#  min_liquidity_confidence         float  0-1    final pick liquidity gate
#  min_market_quality_score         float  0-1    final pick market-quality gate
#  max_manipulation_risk_score      float  0-1    final pick manipulation-risk ceiling
#  min_profit_to_cost_ratio         float  0-1    expected profit / spend floor
#  allow_planned_sell               bool          whether planned_sell mode is permitted
#  planned_min_liquidity_confidence float  0-1    planned-sell liquidity gate
#  min_expected_profit_isk          float  ISK    minimum expected realized profit
#  min_profit_per_m3                float  ISK/m3 minimum profit density
#
#  Portfolio config overrides
#  --------------------------
#  max_item_share_of_budget         float  0-1    single-item budget cap
#  max_items                        int           portfolio item count cap
#  max_liquidation_days_per_position float days   per-pick liquidation ceiling
#  reserve_budget_ratio             float  0-1    keep this share liquid
#  reserve_budget_isk               float  ISK    preferred absolute reserve when budget allows
#  safe_buy_today_limit             int           compact summary item cap
#
#  Route ranking modifiers (multipliers > 1 = harder penalty on that dimension)
#  ---------------------------------------------------------------------------
#  route_stale_penalty_weight       float         stale market penalty weight
#  route_speculative_penalty_weight float         speculative exit penalty weight
#  route_concentration_penalty_weight float       concentration penalty weight
#  route_capital_lock_weight        float         capital lock risk weight

BUILTIN_PROFILES: dict[str, dict] = {
    "conservative": {
        "description": (
            "Konservativ: Nur hochliquide Instant-Exits, enge Confidence-Schwellen, "
            "kurze Kapitalbindung und kleines Einzelpositions-Limit."
        ),
        "min_confidence": 0.70,
        "min_fill_probability": 0.70,
        "max_expected_days_to_sell": 14.0,
        "allow_planned_sell": False,
        "planned_min_liquidity_confidence": 0.80,
        "min_expected_profit_isk": 5_000_000.0,
        "min_profit_per_m3": 2_000.0,
        "max_item_share_of_budget": 0.20,
        "max_items": 20,
        "max_liquidation_days_per_position": 14.0,
        "route_stale_penalty_weight": 2.0,
        "route_speculative_penalty_weight": 2.5,
        "route_concentration_penalty_weight": 1.5,
        "route_capital_lock_weight": 2.0,
    },
    "small_wallet_hub_safe": {
        "description": (
            "Small Wallet / Hub Safe: direkter Exit vor Papierprofit, Reserve-Liquiditaet "
            "bleibt geschuetzt, duenne Buecher und langsame Trades werden hart verworfen."
        ),
        "min_confidence": 0.78,
        "min_fill_probability": 0.82,
        "max_expected_days_to_sell": 7.0,
        "min_liquidity_confidence": 0.78,
        "min_market_quality_score": 0.72,
        "max_manipulation_risk_score": 0.22,
        "min_profit_to_cost_ratio": 0.035,
        "allow_planned_sell": False,
        "planned_min_liquidity_confidence": 0.88,
        "min_expected_profit_isk": 2_500_000.0,
        "min_profit_per_m3": 2_500.0,
        "max_item_share_of_budget": 0.15,
        "max_items": 8,
        "max_liquidation_days_per_position": 7.0,
        "reserve_budget_ratio": 0.25,
        "reserve_budget_isk": 150_000_000.0,
        "safe_buy_today_limit": 5,
        "route_stale_penalty_weight": 2.8,
        "route_speculative_penalty_weight": 3.0,
        "route_concentration_penalty_weight": 2.0,
        "route_capital_lock_weight": 2.8,
    },
    "balanced": {
        "description": (
            "Ausgewogen: Standardverhalten - gemischte Exits, moderate Diversifikation, "
            "normale Confidence-Schwellen."
        ),
        "min_confidence": 0.50,
        "min_fill_probability": 0.30,
        "max_expected_days_to_sell": 45.0,
        "allow_planned_sell": True,
        "planned_min_liquidity_confidence": 0.45,
        "min_expected_profit_isk": 500_000.0,
        "min_profit_per_m3": 200.0,
        "max_item_share_of_budget": 0.40,
        "max_items": 40,
        "max_liquidation_days_per_position": 45.0,
        "route_stale_penalty_weight": 1.0,
        "route_speculative_penalty_weight": 1.0,
        "route_concentration_penalty_weight": 1.0,
        "route_capital_lock_weight": 1.0,
    },
    "aggressive": {
        "description": (
            "Aggressiv: Maximaler Papierprofit, hohe Toleranz fuer duenne Maerkte, "
            "lange Kapitalbindung und speculative Exits erlaubt."
        ),
        "min_confidence": 0.20,
        "min_fill_probability": 0.10,
        "max_expected_days_to_sell": 90.0,
        "allow_planned_sell": True,
        "planned_min_liquidity_confidence": 0.20,
        "min_expected_profit_isk": 0.0,
        "min_profit_per_m3": 0.0,
        "max_item_share_of_budget": 0.70,
        "max_items": 100,
        "max_liquidation_days_per_position": 90.0,
        "route_stale_penalty_weight": 0.30,
        "route_speculative_penalty_weight": 0.30,
        "route_concentration_penalty_weight": 0.50,
        "route_capital_lock_weight": 0.30,
    },
    "instant_only": {
        "description": (
            "Instant Only: planned_sell vollstaendig blockiert - nur direkt realisierbare "
            "Buy-Order-Exits. Kurze Kapitalbindung, klarer Plan."
        ),
        "min_confidence": 0.40,
        "min_fill_probability": 0.50,
        "max_expected_days_to_sell": 1.0,
        "allow_planned_sell": False,
        "planned_min_liquidity_confidence": 0.90,
        "min_expected_profit_isk": 0.0,
        "min_profit_per_m3": 0.0,
        "max_item_share_of_budget": 0.50,
        "max_items": 50,
        "max_liquidation_days_per_position": 1.0,
        "route_stale_penalty_weight": 1.5,
        "route_speculative_penalty_weight": 3.0,
        "route_concentration_penalty_weight": 1.0,
        "route_capital_lock_weight": 3.0,
    },
    "high_liquidity": {
        "description": (
            "High Liquidity: Exit-Qualitaet vor Marge - duenne Maerkte werden hart "
            "bestraft, nur Positionen mit starker Nachfrage."
        ),
        "min_confidence": 0.60,
        "min_fill_probability": 0.60,
        "max_expected_days_to_sell": 21.0,
        "allow_planned_sell": True,
        "planned_min_liquidity_confidence": 0.70,
        "min_expected_profit_isk": 1_000_000.0,
        "min_profit_per_m3": 500.0,
        "max_item_share_of_budget": 0.30,
        "max_items": 30,
        "max_liquidation_days_per_position": 21.0,
        "route_stale_penalty_weight": 2.5,
        "route_speculative_penalty_weight": 2.0,
        "route_concentration_penalty_weight": 1.5,
        "route_capital_lock_weight": 1.5,
    },
    "low_maintenance": {
        "description": (
            "Low Maintenance: Stressarme Trades - weniger Items, klare Instant-Exits, "
            "minimales Repricing-Risiko und schnell abarbeitbare Plaene."
        ),
        "min_confidence": 0.55,
        "min_fill_probability": 0.60,
        "max_expected_days_to_sell": 21.0,
        "allow_planned_sell": False,
        "planned_min_liquidity_confidence": 0.70,
        "min_expected_profit_isk": 2_000_000.0,
        "min_profit_per_m3": 500.0,
        "max_item_share_of_budget": 0.35,
        "max_items": 12,
        "max_liquidation_days_per_position": 21.0,
        "route_stale_penalty_weight": 1.5,
        "route_speculative_penalty_weight": 2.5,
        "route_concentration_penalty_weight": 0.80,
        "route_capital_lock_weight": 2.0,
    },
}

DEFAULT_PROFILE = "balanced"
ENV_PROFILE_VAR = "NULLSEC_RISK_PROFILE"


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------

def resolve_active_profile(cfg: dict) -> tuple[str, dict]:
    """Return (profile_name, profile_params) for the current run."""
    import os

    env_val = str(os.environ.get(ENV_PROFILE_VAR, "") or "").strip().lower()
    if env_val and env_val in BUILTIN_PROFILES:
        name = env_val
    else:
        cli_val = str(cfg.get("_cli_risk_profile", "") or "").strip().lower()
        if cli_val and cli_val in BUILTIN_PROFILES:
            name = cli_val
        else:
            cfg_section = cfg.get("risk_profile", {})
            if isinstance(cfg_section, str):
                name = cfg_section.strip().lower()
            elif isinstance(cfg_section, dict):
                name = str(cfg_section.get("name", DEFAULT_PROFILE) or DEFAULT_PROFILE).strip().lower()
            else:
                name = DEFAULT_PROFILE
            if name not in BUILTIN_PROFILES:
                name = DEFAULT_PROFILE

    profile = dict(BUILTIN_PROFILES[name])
    cfg_section = cfg.get("risk_profile", {})
    if isinstance(cfg_section, dict):
        for key, value in cfg_section.items():
            if key != "name" and value is not None:
                profile[key] = value

    return name, profile


# ---------------------------------------------------------------------------
# Filter / portfolio application
# ---------------------------------------------------------------------------

def apply_profile_to_filters(profile_name: str, profile: dict, filters: dict) -> dict:
    """Merge profile constraints into the candidate filter dict."""
    out = dict(filters)

    min_fill = float(profile.get("min_fill_probability", 0.0) or 0.0)
    if min_fill > 0.0:
        out["min_fill_probability"] = max(float(out.get("min_fill_probability", 0.0) or 0.0), min_fill)

    max_days = float(profile.get("max_expected_days_to_sell", 0.0) or 0.0)
    if max_days > 0.0:
        out["max_expected_days_to_sell"] = min(
            float(out.get("max_expected_days_to_sell", 99_999.0) or 99_999.0),
            max_days,
        )
        out["_profile_max_expected_days_to_sell"] = float(max_days)

    min_liq_conf = float(profile.get("planned_min_liquidity_confidence", 0.0) or 0.0)
    if min_liq_conf > 0.0:
        out["planned_min_liquidity_confidence"] = max(
            float(out.get("planned_min_liquidity_confidence", 0.0) or 0.0),
            min_liq_conf,
        )

    final_min_liq_conf = float(profile.get("min_liquidity_confidence", 0.0) or 0.0)
    if final_min_liq_conf > 0.0:
        out["_profile_min_liquidity_confidence"] = float(final_min_liq_conf)

    min_market_quality = float(profile.get("min_market_quality_score", 0.0) or 0.0)
    if min_market_quality > 0.0:
        out["_profile_min_market_quality_score"] = float(min_market_quality)

    max_manip_risk = float(profile.get("max_manipulation_risk_score", 0.0) or 0.0)
    if max_manip_risk > 0.0:
        out["_profile_max_manipulation_risk_score"] = float(max_manip_risk)

    min_profit_to_cost = float(profile.get("min_profit_to_cost_ratio", 0.0) or 0.0)
    if min_profit_to_cost > 0.0:
        out["_profile_min_profit_to_cost_ratio"] = float(min_profit_to_cost)

    min_profit = float(profile.get("min_expected_profit_isk", 0.0) or 0.0)
    if min_profit > 0.0:
        out["min_expected_profit_isk"] = max(
            float(out.get("min_expected_profit_isk", 0.0) or 0.0),
            min_profit,
        )
        out["_profile_min_expected_profit_isk"] = float(min_profit)

    min_p_m3 = float(profile.get("min_profit_per_m3", 0.0) or 0.0)
    if min_p_m3 > 0.0:
        out["_profile_min_profit_per_m3"] = float(min_p_m3)
        out["_profile_min_profit_density_isk_per_m3"] = float(min_p_m3)

    max_share = float(profile.get("max_item_share_of_budget", 0.0) or 0.0)
    if max_share > 0.0:
        out["_profile_max_item_share_of_budget"] = float(max_share)

    out["_profile_allow_planned_sell"] = bool(profile.get("allow_planned_sell", True))
    out["_profile_min_confidence"] = float(profile.get("min_confidence", 0.0) or 0.0)
    out["_profile_reserve_budget_ratio"] = float(profile.get("reserve_budget_ratio", 0.0) or 0.0)
    out["_profile_reserve_budget_isk"] = float(profile.get("reserve_budget_isk", 0.0) or 0.0)
    out["_profile_safe_buy_today_limit"] = int(profile.get("safe_buy_today_limit", 0) or 0)
    out["_profile_name"] = str(profile_name)

    return out


def apply_profile_to_portfolio_cfg(profile: dict, port_cfg: dict) -> dict:
    """Merge profile portfolio constraints into the portfolio config dict."""
    out = dict(port_cfg)

    max_share = float(profile.get("max_item_share_of_budget", 0.0) or 0.0)
    if max_share > 0.0:
        out["max_item_share_of_budget"] = min(
            float(out.get("max_item_share_of_budget", 1.0) or 1.0),
            max_share,
        )

    effective_max_share = float(out.get("max_item_share_of_budget", 1.0) or 1.0)
    cargo_fill_max_share = float(out.get("cargo_fill_max_item_share_of_budget", effective_max_share) or effective_max_share)
    out["cargo_fill_max_item_share_of_budget"] = min(cargo_fill_max_share, effective_max_share)

    max_items = int(profile.get("max_items", 0) or 0)
    if max_items > 0:
        out["max_items"] = min(int(out.get("max_items", 9_999) or 9_999), max_items)

    max_liq = float(profile.get("max_liquidation_days_per_position", 0.0) or 0.0)
    if max_liq > 0.0:
        out["max_liquidation_days_per_position"] = min(
            float(out.get("max_liquidation_days_per_position", 99_999.0) or 99_999.0),
            max_liq,
        )

    return out


def resolve_profile_budget_window(profile: dict, budget_isk: float) -> tuple[float, float]:
    """Return (spendable_budget, reserved_budget) for the active profile.

    The absolute reserve floor is intentionally soft-capped at 50 % of the
    available budget so very small wallets still keep some capital deployable.
    """
    total_budget = max(0.0, float(budget_isk or 0.0))
    if total_budget <= 0.0:
        return 0.0, 0.0

    reserve_ratio = max(0.0, float(profile.get("reserve_budget_ratio", 0.0) or 0.0))
    reserve_floor = max(0.0, float(profile.get("reserve_budget_isk", 0.0) or 0.0))
    reserve_from_ratio = total_budget * reserve_ratio
    reserve_floor_capped = min(reserve_floor, total_budget * 0.50) if reserve_floor > 0.0 else 0.0
    reserved_budget = min(total_budget, max(reserve_from_ratio, reserve_floor_capped))
    spendable_budget = max(0.0, total_budget - reserved_budget)
    return float(spendable_budget), float(reserved_budget)


# ---------------------------------------------------------------------------
# Route ranking
# ---------------------------------------------------------------------------

def compute_profile_route_score_multiplier(profile: dict, route_summary: dict) -> float:
    """Return a score multiplier (0-1) reflecting the profile's penalty preferences."""
    stale_w = float(profile.get("route_stale_penalty_weight", 1.0) or 1.0)
    spec_w = float(profile.get("route_speculative_penalty_weight", 1.0) or 1.0)
    conc_w = float(profile.get("route_concentration_penalty_weight", 1.0) or 1.0)
    lock_w = float(profile.get("route_capital_lock_weight", 1.0) or 1.0)

    stale = float(route_summary.get("stale_market_penalty", 0.0) or 0.0)
    spec = float(route_summary.get("speculative_penalty", 0.0) or 0.0)
    conc = float(route_summary.get("concentration_penalty", 0.0) or 0.0)
    lock = float(route_summary.get("capital_lock_risk", 0.0) or 0.0)

    extra = (
        stale * (stale_w - 1.0)
        + spec * (spec_w - 1.0)
        + conc * (conc_w - 1.0)
        + lock * (lock_w - 1.0) * 0.20
    )
    return float(max(0.0, min(1.0, 1.0 - extra)))


def apply_profile_to_route_result(profile_name: str, profile: dict, route_result: dict) -> None:
    """Compute and store a profile-adjusted risk score in the route result dict."""
    from route_search import summarize_route_for_ranking

    summary = summarize_route_for_ranking(route_result)
    base_score = float(summary.get("risk_adjusted_score", 0.0) or 0.0)

    if base_score <= 0.0:
        route_result["_profile_risk_adjusted_score"] = float(base_score)
        route_result["_profile_score_multiplier"] = 1.0
        route_result["_active_risk_profile"] = str(profile_name)
        return

    multiplier = compute_profile_route_score_multiplier(profile, summary)
    route_result["_profile_risk_adjusted_score"] = float(base_score * multiplier)
    route_result["_profile_score_multiplier"] = float(multiplier)
    route_result["_active_risk_profile"] = str(profile_name)


# ---------------------------------------------------------------------------
# Post-build candidate filter (profile pick gates)
# ---------------------------------------------------------------------------

def _pick_expected_profit(pick: dict) -> float:
    return float(
        pick.get(
            "expected_realized_profit_90d",
            pick.get("expected_profit_90d", pick.get("profit", 0.0)),
        )
        or 0.0
    )


def _pick_profit_per_m3(pick: dict) -> float:
    return float(
        pick.get(
            "expected_realized_profit_per_m3_90d",
            pick.get("expected_profit_per_m3_90d", pick.get("profit_per_m3", 0.0)),
        )
        or 0.0
    )


def _pick_confidence(pick: dict) -> float:
    return float(
        pick.get(
            "decision_overall_confidence",
            pick.get(
                "calibrated_overall_confidence",
                pick.get("overall_confidence", pick.get("strict_confidence_score", 0.0)),
            ),
        )
        or 0.0
    )


def _pick_expected_days(pick: dict) -> float:
    return float(pick.get("expected_days_to_sell", pick.get("order_duration_days", 0.0)) or 0.0)


def _pick_liquidity_confidence(pick: dict) -> float:
    return float(pick.get("liquidity_confidence", pick.get("fill_probability", 0.0)) or 0.0)


def _pick_market_quality_score(pick: dict) -> float:
    return float(pick.get("market_quality_score", pick.get("market_plausibility_score", 1.0)) or 1.0)


def _pick_manipulation_risk_score(pick: dict) -> float:
    return float(pick.get("manipulation_risk_score", 0.0) or 0.0)


def _pick_profit_to_cost_ratio(pick: dict) -> float:
    expected_profit = _pick_expected_profit(pick)
    cost = float(pick.get("cost", 0.0) or 0.0)
    if cost <= 0.0:
        return 999.0 if expected_profit > 0.0 else 0.0
    return float(expected_profit / cost)


def filter_picks_by_profile(
    picks: list[dict],
    filters_used: dict,
    *,
    budget_isk: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply profile gates that can only be checked after portfolio build."""
    min_profit_isk = float(filters_used.get("_profile_min_expected_profit_isk", 0.0) or 0.0)
    min_p_m3 = float(
        filters_used.get(
            "_profile_min_profit_density_isk_per_m3",
            filters_used.get("_profile_min_profit_per_m3", 0.0),
        )
        or 0.0
    )
    min_conf = float(filters_used.get("_profile_min_confidence", 0.0) or 0.0)
    max_days = float(filters_used.get("_profile_max_expected_days_to_sell", 0.0) or 0.0)
    min_liq_conf = float(filters_used.get("_profile_min_liquidity_confidence", 0.0) or 0.0)
    min_market_quality = float(filters_used.get("_profile_min_market_quality_score", 0.0) or 0.0)
    max_manip_risk = float(filters_used.get("_profile_max_manipulation_risk_score", 0.0) or 0.0)
    min_profit_to_cost = float(filters_used.get("_profile_min_profit_to_cost_ratio", 0.0) or 0.0)
    max_share = float(filters_used.get("_profile_max_item_share_of_budget", 0.0) or 0.0)
    profile_name = str(filters_used.get("_profile_name", "") or "")

    if (
        min_profit_isk <= 0.0
        and min_p_m3 <= 0.0
        and min_conf <= 0.0
        and max_days <= 0.0
        and min_liq_conf <= 0.0
        and min_market_quality <= 0.0
        and max_manip_risk <= 0.0
        and min_profit_to_cost <= 0.0
        and max_share <= 0.0
    ):
        return list(picks), []

    kept: list[dict] = []
    rejected: list[dict] = []
    for pick in picks:
        reasons: list[str] = []
        reason_codes: list[str] = []
        expected_profit = _pick_expected_profit(pick)
        profit_per_m3 = _pick_profit_per_m3(pick)
        confidence = _pick_confidence(pick)
        expected_days = _pick_expected_days(pick)
        liquidity_confidence = _pick_liquidity_confidence(pick)
        market_quality = _pick_market_quality_score(pick)
        manipulation_risk = _pick_manipulation_risk_score(pick)
        profit_to_cost = _pick_profit_to_cost_ratio(pick)
        cost = float(pick.get("cost", 0.0) or 0.0)

        if min_profit_isk > 0.0 and expected_profit + 1e-6 < min_profit_isk:
            reason_codes.append("profile_min_expected_profit_isk")
            reasons.append(
                f"[profile:{profile_name}] expected profit {expected_profit:.0f} < {min_profit_isk:.0f}"
            )
        if min_p_m3 > 0.0 and profit_per_m3 + 1e-6 < min_p_m3:
            reason_codes.append("profile_min_profit_per_m3")
            reasons.append(
                f"[profile:{profile_name}] profit/m3 {profit_per_m3:.0f} < {min_p_m3:.0f}"
            )
        if min_conf > 0.0 and confidence + 1e-6 < min_conf:
            reason_codes.append("profile_min_confidence")
            reasons.append(
                f"[profile:{profile_name}] confidence {confidence:.2f} < {min_conf:.2f}"
            )
        if max_days > 0.0 and expected_days - 1e-6 > max_days:
            reason_codes.append("profile_max_expected_days_to_sell")
            reasons.append(
                f"[profile:{profile_name}] expected days {expected_days:.1f} > {max_days:.1f}"
            )
        if min_liq_conf > 0.0 and liquidity_confidence + 1e-6 < min_liq_conf:
            reason_codes.append("profile_min_liquidity_confidence")
            reasons.append(
                f"[profile:{profile_name}] liquidity {liquidity_confidence:.2f} < {min_liq_conf:.2f}"
            )
        if min_market_quality > 0.0 and market_quality + 1e-6 < min_market_quality:
            reason_codes.append("profile_min_market_quality_score")
            reasons.append(
                f"[profile:{profile_name}] market quality {market_quality:.2f} < {min_market_quality:.2f}"
            )
        if max_manip_risk > 0.0 and manipulation_risk - 1e-6 > max_manip_risk:
            reason_codes.append("profile_max_manipulation_risk_score")
            reasons.append(
                f"[profile:{profile_name}] manipulation risk {manipulation_risk:.2f} > {max_manip_risk:.2f}"
            )
        if min_profit_to_cost > 0.0 and profit_to_cost + 1e-6 < min_profit_to_cost:
            reason_codes.append("profile_min_profit_to_cost_ratio")
            reasons.append(
                f"[profile:{profile_name}] profit/spend {profit_to_cost:.1%} < {min_profit_to_cost:.1%}"
            )
        if (
            max_share > 0.0
            and budget_isk is not None
            and float(budget_isk) > 0.0
            and cost > (float(budget_isk) * max_share) + 1e-6
        ):
            share = cost / max(1e-9, float(budget_isk))
            reason_codes.append("profile_max_item_share_of_budget")
            reasons.append(
                f"[profile:{profile_name}] budget share {share:.1%} > {max_share:.1%}"
            )

        if not reasons:
            kept.append(pick)
            continue

        rejected_pick = dict(pick)
        rejected_pick["_profile_rejection_reason"] = "; ".join(reasons)
        rejected_pick["_profile_rejection_codes"] = list(reason_codes)
        rejected.append(rejected_pick)

    return kept, rejected


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def profile_header_lines(profile_name: str, profile: dict) -> list[str]:
    """Return human-readable lines describing the active profile for output headers."""
    lines: list[str] = []
    lines.append(f"Active Risk Profile : {profile_name.upper()}")
    lines.append(f"  {profile.get('description', '')}")
    lines.append("")

    allow_planned = bool(profile.get("allow_planned_sell", True))
    lines.append(f"  Planned Sell      : {'allowed' if allow_planned else 'BLOCKED (instant-only exits)'}")

    min_conf = float(profile.get("min_confidence", 0.0) or 0.0)
    if min_conf > 0.0:
        lines.append(f"  Min Confidence    : {min_conf:.0%}")

    max_days = float(profile.get("max_expected_days_to_sell", 0.0) or 0.0)
    if max_days > 0.0:
        lines.append(f"  Max Days to Sell  : {max_days:.0f}d")

    max_share = float(profile.get("max_item_share_of_budget", 0.0) or 0.0)
    if max_share > 0.0:
        lines.append(f"  Max Budget/Item   : {max_share:.0%}")

    max_items = int(profile.get("max_items", 0) or 0)
    if max_items > 0:
        lines.append(f"  Max Items         : {max_items}")

    min_profit_isk = float(profile.get("min_expected_profit_isk", 0.0) or 0.0)
    if min_profit_isk > 0.0:
        lines.append(f"  Min Profit        : {min_profit_isk / 1_000_000:.1f}m ISK")

    min_pm3 = float(profile.get("min_profit_per_m3", 0.0) or 0.0)
    if min_pm3 > 0.0:
        lines.append(f"  Min Profit/m3     : {min_pm3:,.0f} ISK/m3")

    min_fill = float(profile.get("min_fill_probability", 0.0) or 0.0)
    if min_fill > 0.0:
        lines.append(f"  Min Fill Prob     : {min_fill:.0%}")

    min_liq = float(profile.get("min_liquidity_confidence", 0.0) or 0.0)
    if min_liq > 0.0:
        lines.append(f"  Min Liquidity     : {min_liq:.0%}")

    min_quality = float(profile.get("min_market_quality_score", 0.0) or 0.0)
    if min_quality > 0.0:
        lines.append(f"  Min Market Qual   : {min_quality:.2f}")

    min_roi = float(profile.get("min_profit_to_cost_ratio", 0.0) or 0.0)
    if min_roi > 0.0:
        lines.append(f"  Min ROI/Spend     : {min_roi:.1%}")

    reserve_ratio = float(profile.get("reserve_budget_ratio", 0.0) or 0.0)
    reserve_isk = float(profile.get("reserve_budget_isk", 0.0) or 0.0)
    if reserve_ratio > 0.0 or reserve_isk > 0.0:
        reserve_parts: list[str] = []
        if reserve_ratio > 0.0:
            reserve_parts.append(f"{reserve_ratio:.0%}")
        if reserve_isk > 0.0:
            reserve_parts.append(f"{reserve_isk / 1_000_000:.0f}m ISK floor")
        lines.append(f"  Reserve Liquidity : keep {' + '.join(reserve_parts)} liquid")

    return lines


def profile_restrictions_summary(profile_name: str, profile: dict) -> str:
    """Return a compact one-line summary of key profile restrictions."""
    parts: list[str] = [f"Profile={profile_name.upper()}"]

    allow_planned = bool(profile.get("allow_planned_sell", True))
    if not allow_planned:
        parts.append("planned_sell=BLOCKED")

    max_days = float(profile.get("max_expected_days_to_sell", 0.0) or 0.0)
    if max_days > 0.0:
        parts.append(f"max_days={max_days:.0f}")

    min_conf = float(profile.get("min_confidence", 0.0) or 0.0)
    if min_conf > 0.0:
        parts.append(f"min_conf={min_conf:.0%}")

    max_items = int(profile.get("max_items", 0) or 0)
    if max_items > 0:
        parts.append(f"max_items={max_items}")

    min_roi = float(profile.get("min_profit_to_cost_ratio", 0.0) or 0.0)
    if min_roi > 0.0:
        parts.append(f"min_roi={min_roi:.1%}")

    reserve_ratio = float(profile.get("reserve_budget_ratio", 0.0) or 0.0)
    reserve_isk = float(profile.get("reserve_budget_isk", 0.0) or 0.0)
    if reserve_ratio > 0.0 or reserve_isk > 0.0:
        reserve_bits: list[str] = []
        if reserve_ratio > 0.0:
            reserve_bits.append(f"{reserve_ratio:.0%}")
        if reserve_isk > 0.0:
            reserve_bits.append(f"{reserve_isk / 1_000_000:.0f}m")
        parts.append(f"reserve={'/'.join(reserve_bits)}")

    return "  ".join(parts)


__all__ = [
    "BUILTIN_PROFILES",
    "DEFAULT_PROFILE",
    "ENV_PROFILE_VAR",
    "apply_profile_to_filters",
    "apply_profile_to_portfolio_cfg",
    "apply_profile_to_route_result",
    "compute_profile_route_score_multiplier",
    "filter_picks_by_profile",
    "profile_header_lines",
    "profile_restrictions_summary",
    "resolve_profile_budget_window",
    "resolve_active_profile",
]
