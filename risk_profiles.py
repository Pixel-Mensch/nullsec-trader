"""Risk profiles for the Nullsec Trader Tool.

Each profile defines concrete parameter overrides that affect:
  - Candidate selection (filter tightening or relaxing)
  - Portfolio construction (item count, budget concentration caps)
  - Route ranking (score multipliers based on risk tolerance)

Profile selection priority:
  1. Environment variable NULLSEC_RISK_PROFILE
  2. CLI argument --profile (stored as cfg["_cli_risk_profile"])
  3. config.json / config.local.json key  "risk_profile": {"name": "..."}
  4. Default: "balanced"
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Built-in profile definitions
# ---------------------------------------------------------------------------

# Parameter reference (all keys optional – None / 0 means "use config default"):
#
#  Candidate filter overrides
#  --------------------------
#  min_confidence                  float  0-1    decision_overall_confidence gate
#  min_fill_probability            float  0-1    fill_probability gate (instant proxy)
#  max_expected_days_to_sell       float  days   hard ceiling on sell duration
#  allow_planned_sell              bool          whether planned_sell mode is permitted
#  planned_min_liquidity_confidence float 0-1   planned-sell liquidity gate
#  min_expected_profit_isk         float  ISK    minimum expected realized profit
#  min_profit_per_m3               float  ISK/m3 minimum profit density (post-build filter)
#
#  Portfolio config overrides
#  --------------------------
#  max_item_share_of_budget        float  0-1    single-item budget cap
#  max_items                       int           portfolio item count cap
#  max_liquidation_days_per_position float days  per-pick liquidation ceiling
#
#  Route ranking modifiers  (multipliers > 1 = harder penalty on that dimension)
#  -----------------------
#  route_stale_penalty_weight      float         stale market penalty weight
#  route_speculative_penalty_weight float        speculative exit penalty weight
#  route_concentration_penalty_weight float      concentration penalty weight
#  route_capital_lock_weight       float         capital lock risk weight

BUILTIN_PROFILES: dict[str, dict] = {
    "conservative": {
        "description": (
            "Konservativ: Nur hochliquide Instant-Exits, enge Confidence-Schwellen, "
            "kurze Kapitalbindung und kleines Einzelpositions-Limit."
        ),
        # Candidate filters
        "min_confidence": 0.70,
        "min_fill_probability": 0.70,
        "max_expected_days_to_sell": 14.0,
        "allow_planned_sell": False,
        "planned_min_liquidity_confidence": 0.80,
        "min_expected_profit_isk": 5_000_000.0,
        "min_profit_per_m3": 2_000.0,
        # Portfolio
        "max_item_share_of_budget": 0.20,
        "max_items": 20,
        "max_liquidation_days_per_position": 14.0,
        # Route ranking: harder penalties on all risk dimensions
        "route_stale_penalty_weight": 2.0,
        "route_speculative_penalty_weight": 2.5,
        "route_concentration_penalty_weight": 1.5,
        "route_capital_lock_weight": 2.0,
    },
    "balanced": {
        "description": (
            "Ausgewogen: Standardverhalten – gemischte Exits, moderate Diversifikation, "
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
        # Soft penalties only – aggressive tolerates all route risk
        "route_stale_penalty_weight": 0.30,
        "route_speculative_penalty_weight": 0.30,
        "route_concentration_penalty_weight": 0.50,
        "route_capital_lock_weight": 0.30,
    },
    "instant_only": {
        "description": (
            "Instant Only: planned_sell vollstaendig blockiert – nur direkt realisierbare "
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
        # Hard penalty on speculative and slow routes
        "route_stale_penalty_weight": 1.5,
        "route_speculative_penalty_weight": 3.0,
        "route_concentration_penalty_weight": 1.0,
        "route_capital_lock_weight": 3.0,
    },
    "high_liquidity": {
        "description": (
            "High Liquidity: Exit-Qualitaet vor Marge – duenne Maerkte werden hart "
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
        # Very hard stale-market penalty
        "route_stale_penalty_weight": 2.5,
        "route_speculative_penalty_weight": 2.0,
        "route_concentration_penalty_weight": 1.5,
        "route_capital_lock_weight": 1.5,
    },
    "low_maintenance": {
        "description": (
            "Low Maintenance: Stressarme Trades – weniger Items, klare Instant-Exits, "
            "minimales Repricing-Risiko und schnell abarbeitbare Plaene."
        ),
        "min_confidence": 0.55,
        "min_fill_probability": 0.60,
        "max_expected_days_to_sell": 21.0,
        "allow_planned_sell": False,
        "planned_min_liquidity_confidence": 0.70,
        "min_expected_profit_isk": 2_000_000.0,
        "min_profit_per_m3": 500.0,
        # KEY: strict item cap reduces open positions and repricing work
        "max_item_share_of_budget": 0.35,
        "max_items": 12,
        "max_liquidation_days_per_position": 21.0,
        # Hard penalty on speculative routes, moderate stale penalty
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
    """Return (profile_name, profile_params) for the current run.

    Priority: env var > CLI (cfg['_cli_risk_profile']) > config section > default.
    Config's 'risk_profile' section can also contain per-key overrides applied on
    top of the selected built-in profile.
    """
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

    # Allow per-key overrides from config's risk_profile section
    cfg_section = cfg.get("risk_profile", {})
    if isinstance(cfg_section, dict):
        for k, v in cfg_section.items():
            if k != "name" and v is not None:
                profile[k] = v

    return name, profile


# ---------------------------------------------------------------------------
# Filter / portfolio application
# ---------------------------------------------------------------------------

def apply_profile_to_filters(profile_name: str, profile: dict, filters: dict) -> dict:
    """Merge profile constraints into the candidate filter dict.

    Only tightens filters (never relaxes a stricter config value).
    Stores _profile_* keys so downstream code can show profile context.
    """
    out = dict(filters)

    # min_fill_probability (instant proxy for confidence)
    min_fill = float(profile.get("min_fill_probability", 0.0) or 0.0)
    if min_fill > 0.0:
        out["min_fill_probability"] = max(float(out.get("min_fill_probability", 0.0) or 0.0), min_fill)

    # max_expected_days_to_sell
    max_days = float(profile.get("max_expected_days_to_sell", 0.0) or 0.0)
    if max_days > 0.0:
        out["max_expected_days_to_sell"] = min(
            float(out.get("max_expected_days_to_sell", 99_999.0) or 99_999.0),
            max_days,
        )

    # planned_min_liquidity_confidence
    min_liq_conf = float(profile.get("planned_min_liquidity_confidence", 0.0) or 0.0)
    if min_liq_conf > 0.0:
        out["planned_min_liquidity_confidence"] = max(
            float(out.get("planned_min_liquidity_confidence", 0.0) or 0.0),
            min_liq_conf,
        )

    # min_expected_profit_isk
    min_profit = float(profile.get("min_expected_profit_isk", 0.0) or 0.0)
    if min_profit > 0.0:
        out["min_expected_profit_isk"] = max(
            float(out.get("min_expected_profit_isk", 0.0) or 0.0),
            min_profit,
        )

    # min_profit_per_m3 – stored as profile gate, applied as post-build filter
    min_p_m3 = float(profile.get("min_profit_per_m3", 0.0) or 0.0)
    if min_p_m3 > 0.0:
        out["_profile_min_profit_per_m3"] = float(min_p_m3)

    # allow_planned_sell flag
    out["_profile_allow_planned_sell"] = bool(profile.get("allow_planned_sell", True))

    # min_confidence – stored for post-compute explainability
    out["_profile_min_confidence"] = float(profile.get("min_confidence", 0.0) or 0.0)

    # Metadata
    out["_profile_name"] = str(profile_name)

    return out


def apply_profile_to_portfolio_cfg(profile: dict, port_cfg: dict) -> dict:
    """Merge profile portfolio constraints into the portfolio config dict.

    Only tightens existing limits (never relaxes a stricter config value).
    """
    out = dict(port_cfg)

    max_share = float(profile.get("max_item_share_of_budget", 0.0) or 0.0)
    if max_share > 0.0:
        out["max_item_share_of_budget"] = min(
            float(out.get("max_item_share_of_budget", 1.0) or 1.0),
            max_share,
        )

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


# ---------------------------------------------------------------------------
# Route ranking
# ---------------------------------------------------------------------------

def compute_profile_route_score_multiplier(profile: dict, route_summary: dict) -> float:
    """Return a score multiplier (0-1) reflecting the profile's penalty preferences.

    Profile weights > 1.0 amplify the existing penalty; < 1.0 soften it.
    """
    stale_w = float(profile.get("route_stale_penalty_weight", 1.0) or 1.0)
    spec_w  = float(profile.get("route_speculative_penalty_weight", 1.0) or 1.0)
    conc_w  = float(profile.get("route_concentration_penalty_weight", 1.0) or 1.0)
    lock_w  = float(profile.get("route_capital_lock_weight", 1.0) or 1.0)

    stale   = float(route_summary.get("stale_market_penalty", 0.0) or 0.0)
    spec    = float(route_summary.get("speculative_penalty", 0.0) or 0.0)
    conc    = float(route_summary.get("concentration_penalty", 0.0) or 0.0)
    lock    = float(route_summary.get("capital_lock_risk", 0.0) or 0.0)

    # Extra penalty = original * (weight - 1), so weight=1 → no change
    extra = (
        stale * (stale_w - 1.0)
        + spec  * (spec_w  - 1.0)
        + conc  * (conc_w  - 1.0)
        + lock  * (lock_w  - 1.0) * 0.20   # capital lock is 0-1 range; partial contribution
    )
    return float(max(0.0, min(1.0, 1.0 - extra)))


def apply_profile_to_route_result(profile_name: str, profile: dict, route_result: dict) -> None:
    """Compute and store a profile-adjusted risk score in the route result dict (in-place).

    Stores '_profile_risk_adjusted_score' so route_ranking_value can pick it up
    without re-running summarize_route_for_ranking.
    """
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
# Post-build candidate filter (min_profit_per_m3)
# ---------------------------------------------------------------------------

def filter_picks_by_profile(picks: list[dict], filters_used: dict) -> tuple[list[dict], list[dict]]:
    """Apply profile gates that can only be checked after portfolio build.

    Returns (kept, rejected) where rejected items have a '_profile_rejection_reason'.
    """
    min_p_m3 = float(filters_used.get("_profile_min_profit_per_m3", 0.0) or 0.0)
    profile_name = str(filters_used.get("_profile_name", "") or "")

    if min_p_m3 <= 0.0:
        return list(picks), []

    kept: list[dict] = []
    rejected: list[dict] = []
    for p in picks:
        p_m3 = float(p.get("expected_realized_profit_per_m3_90d", p.get("profit_per_m3", 0.0)) or 0.0)
        if p_m3 >= min_p_m3:
            kept.append(p)
        else:
            p = dict(p)
            p["_profile_rejection_reason"] = (
                f"[profile:{profile_name}] profit/m3 {p_m3:.0f} < {min_p_m3:.0f}"
            )
            rejected.append(p)
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
    "resolve_active_profile",
]
