"""No-trade decision engine for the Nullsec Trader Tool.

Evaluates whether trading is advisable given current route results and the
active risk profile. Returns structured reason codes, near-miss info, and a
cross-profile comparison instead of just printing an empty plan.

Usage in runtime_runner.py:
    from no_trade import evaluate_no_trade
    from execution_plan import write_no_trade_report
    from risk_profiles import BUILTIN_PROFILES

    result = evaluate_no_trade(
        route_results, active_profile_name, active_profile_params,
        all_profiles=BUILTIN_PROFILES,
    )
    if not result["should_trade"]:
        write_no_trade_report(path, timestamp, result, active_profile_name, active_profile_params)
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Reason code registry
# ---------------------------------------------------------------------------

REASON_CODES: dict[str, str] = {
    "NO_ACTIONABLE_ROUTES": "No actionable routes found",
    "NO_STRONG_EXITS": "No mandatory or optional picks - only speculative positions",
    "EXCESSIVE_SPECULATION": "Speculative pick share exceeds acceptable threshold",
    "LOW_ROUTE_CONFIDENCE": "Best route confidence below profile minimum",
    "SHIPPING_UNCERTAIN": "Transport confidence too low for reliable execution",
    "CAPITAL_LOCK_TOO_HIGH": "Capital lock risk exceeds acceptable threshold",
    "PROFIT_NOT_ACTIONABLE": "Expected profit too small to justify execution costs",
    "DATA_QUALITY_TOO_WEAK": "Calibration data too thin - outcomes unverifiable",
    "TOO_FEW_HIGH_QUALITY_PICKS": "Too few mandatory or optional picks for a viable plan",
    "CANDIDATES_DID_NOT_SURVIVE_FILTERS": "Candidates existed but none passed all active filters",
}

_SEVERITY_CRITICAL = "critical"
_SEVERITY_HIGH = "high"
_SEVERITY_MEDIUM = "medium"


# ---------------------------------------------------------------------------
# Profile threshold helpers
# ---------------------------------------------------------------------------

def _profile_min_route_conf(profile: dict) -> float:
    """Return minimum acceptable route_confidence for this profile.

    Note: profiles store ``min_confidence`` as a per-pick candidate gate
    (enforced against each pick's ``decision_overall_confidence``).
    ``route_confidence`` from ``summarize_route_for_ranking`` is a different,
    route-level aggregate.  In the absence of an explicit route-level threshold
    parameter, ``min_confidence`` is used here as a conservative proxy — it is
    the strictest single-metric bar the profile already enforces, so using it as
    a floor for the aggregate is safe (it may fire more often than strictly
    necessary, never less).
    """
    return float(profile.get("min_confidence", 0.30) or 0.30)


def _profile_max_capital_lock(profile: dict) -> float:
    """Return max capital-lock-risk fraction acceptable for this profile.

    No explicit capital-lock threshold exists in profile params; this function
    derives a heuristic ceiling from ``route_capital_lock_weight``, which is a
    multiplicative ranking penalty (range 0.30–3.0), not a threshold.  The
    mapping below is a deliberate approximation:
      weight ≥ 2.0 → conservative profile → max lock 30 %
      weight ≥ 1.5 → cautious           → max lock 45 %
      weight ≥ 1.0 → balanced           → max lock 65 %
      weight  < 1.0 → aggressive        → max lock 85 %
    If explicit thresholds are added to risk_profiles.py in future, this
    function should be replaced with a direct param lookup.
    """
    weight = float(profile.get("route_capital_lock_weight", 1.0) or 1.0)
    if weight >= 2.0:
        return 0.30
    if weight >= 1.5:
        return 0.45
    if weight >= 1.0:
        return 0.65
    return 0.85  # aggressive profiles with weight < 1.0 tolerate high lock


def _profile_max_speculative_share(profile: dict) -> float:
    """Return max acceptable speculative-pick fraction for this profile.

    Derived from ``route_speculative_penalty_weight`` (a ranking penalty, range
    0.30–3.0), not an explicit threshold.  Same approximation caveat as
    ``_profile_max_capital_lock`` — replace with a direct lookup if explicit
    params are added.
    """
    weight = float(profile.get("route_speculative_penalty_weight", 1.0) or 1.0)
    if weight >= 2.5:
        return 0.20
    if weight >= 1.5:
        return 0.40
    if weight >= 1.0:
        return 0.70
    return 0.90  # aggressive


def _profile_min_transport_conf(profile: dict) -> float:
    """Return minimum transport confidence acceptable for this profile.

    Derived as 70 % of the profile's ``min_confidence`` pick gate, floored at
    0.25.  Transport confidence is a separate metric (shipping lane model
    quality), so this is an approximation rather than a direct threshold.
    """
    min_conf = float(profile.get("min_confidence", 0.30) or 0.30)
    return max(0.25, min_conf * 0.70)


def _profile_min_strong_picks(profile_name: str) -> int:
    """Minimum number of mandatory+optional picks required by this profile."""
    if profile_name in ("conservative", "high_liquidity", "low_maintenance"):
        return 2
    return 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_route_summary(route: dict) -> dict:
    from route_search import summarize_route_for_ranking
    return summarize_route_for_ranking(route)


def _categorize_pick(p: dict) -> str:
    from execution_plan import _categorize_pick as _ep_cat
    return _ep_cat(p)


def _is_actionable(route: dict) -> bool:
    picks = list(route.get("picks", []) or [])
    return bool(route.get("route_actionable", False)) and bool(picks)


def _build_near_misses(non_actionable: list[dict]) -> list[dict]:
    """Build near-miss summaries from non-actionable routes (up to 5)."""
    near_misses: list[dict] = []
    for r in non_actionable[:5]:
        near_misses.append({
            "route_label": str(r.get("route_label", "") or ""),
            "prune_reason": str(r.get("route_prune_reason", "") or "no_picks"),
            "total_candidates": int(r.get("total_candidates", 0) or 0),
            "why_out_summary": dict(r.get("why_out_summary", {}) or {}),
            "transport_blocked": bool(r.get("route_blocked_due_to_transport", False)),
            "operational_profit_floor_isk": float(r.get("operational_profit_floor_isk", 0.0) or 0.0),
            "suppressed_expected_realized_profit_total": float(r.get("suppressed_expected_realized_profit_total", 0.0) or 0.0),
            "operational_filter_note": str(r.get("operational_filter_note", "") or ""),
        })
    return near_misses


def _build_profile_comparison(
    route_results: list[dict],
    all_profiles: dict | None,
    active_profile_name: str,
) -> dict[str, bool]:
    """Check which other profiles would trade given the same route data.

    A profile 'would trade' if:
    - its min_confidence is <= best route's route_confidence, AND
    - it allows planned_sell OR the routes only have instant picks.

    Returns {profile_name: bool}.
    """
    if not all_profiles or not route_results:
        return {}

    actionable = [r for r in route_results if _is_actionable(r)]
    if not actionable:
        best_conf = 0.0
        has_planned_sell = False
    else:
        def _profit(r: dict) -> float:
            s = _get_route_summary(r)
            return float(s.get("total_expected_realized_profit", 0.0) or 0.0)

        best = max(actionable, key=_profit)
        s = _get_route_summary(best)
        best_conf = float(s.get("route_confidence", 0.0) or 0.0)
        best_picks = list(best.get("picks", []) or [])
        has_planned_sell = any(not bool(p.get("instant", False)) for p in best_picks)

    comparison: dict[str, bool] = {}
    for pname, pparams in all_profiles.items():
        if pname == active_profile_name:
            continue
        p_min_conf = float(pparams.get("min_confidence", 0.0) or 0.0)
        p_allow_planned = bool(pparams.get("allow_planned_sell", True))
        would_accept_conf = best_conf >= p_min_conf
        would_accept_mode = (not has_planned_sell) or p_allow_planned
        comparison[pname] = would_accept_conf and would_accept_mode

    return comparison


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_no_trade(
    route_results: list[dict],
    active_profile_name: str,
    active_profile_params: dict,
    *,
    all_profiles: dict | None = None,
) -> dict:
    """Evaluate whether trading is advisable given current route results.

    Args:
        route_results: all route result dicts from the runtime
        active_profile_name: e.g. "balanced"
        active_profile_params: profile dict from risk_profiles.BUILTIN_PROFILES
        all_profiles: BUILTIN_PROFILES for cross-profile comparison (optional)

    Returns a dict with:
        should_trade:           bool — True means execute the plan
        reason_codes:           list[dict]  — [{code, text, severity, detail}]
        near_misses:            list[dict]  — almost-good routes
        profile_comparison:     dict[str, bool]
        actionable_route_count: int
        total_route_count:      int
        best_route_summary:     dict | None
    """
    from execution_plan import _CAT_MANDATORY, _CAT_OPTIONAL, _CAT_SPECULATIVE

    total_routes = len(list(route_results or []))

    # No routes evaluated at all
    if total_routes == 0:
        return {
            "should_trade": False,
            "reason_codes": [{
                "code": "NO_ACTIONABLE_ROUTES",
                "text": REASON_CODES["NO_ACTIONABLE_ROUTES"],
                "severity": _SEVERITY_CRITICAL,
                "detail": "No routes were evaluated - check config and market data.",
            }],
            "near_misses": [],
            "profile_comparison": {},
            "actionable_route_count": 0,
            "total_route_count": 0,
            "best_route_summary": None,
        }

    # Split into actionable / non-actionable
    actionable_routes = [r for r in route_results if _is_actionable(r)]
    non_actionable_routes = [r for r in route_results if not _is_actionable(r)]
    reason_codes: list[dict] = []

    # === Case 1: No actionable routes ===
    if not actionable_routes:
        reason_codes.append({
            "code": "NO_ACTIONABLE_ROUTES",
            "text": REASON_CODES["NO_ACTIONABLE_ROUTES"],
            "severity": _SEVERITY_CRITICAL,
            "detail": (
                f"{total_routes} route(s) evaluated, none produced actionable picks. "
                "Either market is empty, transport is blocked, or all candidates were rejected."
            ),
        })

        # Diagnose if candidates existed but none survived the full filter chain
        total_candidates = sum(int(r.get("total_candidates", 0) or 0) for r in route_results)
        if total_candidates > 0:
            reason_codes.append({
                "code": "CANDIDATES_DID_NOT_SURVIVE_FILTERS",
                "text": REASON_CODES["CANDIDATES_DID_NOT_SURVIVE_FILTERS"],
                "severity": _SEVERITY_HIGH,
                "detail": (
                    f"{total_candidates} candidate(s) existed but none reached an actionable pick. "
                    "Possible causes: base config gates (min_profit_per_m3, plausibility), "
                    f"or profile '{active_profile_name}' gates: "
                    f"min_confidence={active_profile_params.get('min_confidence', 0):.0%}, "
                    f"allow_planned_sell={active_profile_params.get('allow_planned_sell', True)}, "
                    f"min_fill_probability={active_profile_params.get('min_fill_probability', 0):.0%}."
                ),
            })

        return {
            "should_trade": False,
            "reason_codes": reason_codes,
            "near_misses": _build_near_misses(non_actionable_routes),
            "profile_comparison": _build_profile_comparison(route_results, all_profiles, active_profile_name),
            "actionable_route_count": 0,
            "total_route_count": total_routes,
            "best_route_summary": None,
        }

    # === Case 2: Actionable routes exist — check quality of the best one ===
    def _profit_key(r: dict) -> float:
        s = _get_route_summary(r)
        return float(s.get("total_expected_realized_profit", 0.0) or 0.0)

    best_route = max(actionable_routes, key=_profit_key)
    best_summary = _get_route_summary(best_route)
    best_picks = list(best_route.get("picks", []) or [])

    # Categorize picks
    mandatory = [p for p in best_picks if _categorize_pick(p) == _CAT_MANDATORY]
    optional = [p for p in best_picks if _categorize_pick(p) == _CAT_OPTIONAL]
    speculative = [p for p in best_picks if _categorize_pick(p) == _CAT_SPECULATIVE]
    strong_picks = mandatory + optional
    total_picks = len(best_picks)

    # Pull thresholds from profile
    min_route_conf = _profile_min_route_conf(active_profile_params)
    max_cap_lock = _profile_max_capital_lock(active_profile_params)
    max_spec_share = _profile_max_speculative_share(active_profile_params)
    min_transport_conf = _profile_min_transport_conf(active_profile_params)
    min_profit_isk = float(active_profile_params.get("min_expected_profit_isk", 0.0) or 0.0)
    min_strong = _profile_min_strong_picks(active_profile_name)

    route_conf = float(best_summary.get("route_confidence", 0.0) or 0.0)
    transport_conf = float(best_summary.get("transport_confidence", 0.0) or 0.0)
    cap_lock = float(best_summary.get("capital_lock_risk", 0.0) or 0.0)
    total_profit = float(best_summary.get("total_expected_realized_profit", 0.0) or 0.0)
    cal_warning = str(
        best_route.get("calibration_warning", best_summary.get("calibration_warning", "")) or ""
    )
    spec_share = len(speculative) / max(1, total_picks) if total_picks > 0 else 0.0

    # Check: no strong exits at all
    if total_picks > 0 and not strong_picks:
        reason_codes.append({
            "code": "NO_STRONG_EXITS",
            "text": REASON_CODES["NO_STRONG_EXITS"],
            "severity": _SEVERITY_CRITICAL,
            "detail": (
                f"All {total_picks} pick(s) are speculative - no instant or solid "
                "planned-sell exits available. Verify order book depth."
            ),
        })
    # Check: excessive speculation (only if we have some strong picks too)
    elif total_picks > 0 and spec_share > max_spec_share:
        reason_codes.append({
            "code": "EXCESSIVE_SPECULATION",
            "text": REASON_CODES["EXCESSIVE_SPECULATION"],
            "severity": _SEVERITY_HIGH,
            "detail": (
                f"{len(speculative)}/{total_picks} picks are speculative ({spec_share:.0%}), "
                f"profile '{active_profile_name}' tolerates at most {max_spec_share:.0%}."
            ),
        })

    # Check: route confidence
    if route_conf < min_route_conf:
        reason_codes.append({
            "code": "LOW_ROUTE_CONFIDENCE",
            "text": REASON_CODES["LOW_ROUTE_CONFIDENCE"],
            "severity": _SEVERITY_HIGH,
            "detail": (
                f"Route confidence {route_conf:.2f} < profile minimum {min_route_conf:.2f}. "
                "Market signals are too uncertain for this profile."
            ),
        })

    # Check: transport confidence
    if transport_conf < min_transport_conf:
        reason_codes.append({
            "code": "SHIPPING_UNCERTAIN",
            "text": REASON_CODES["SHIPPING_UNCERTAIN"],
            "severity": _SEVERITY_HIGH,
            "detail": (
                f"Transport confidence {transport_conf:.2f} < {min_transport_conf:.2f}. "
                "Hauling cost model is too uncertain to plan against."
            ),
        })

    # Check: capital lock risk
    if cap_lock > max_cap_lock:
        reason_codes.append({
            "code": "CAPITAL_LOCK_TOO_HIGH",
            "text": REASON_CODES["CAPITAL_LOCK_TOO_HIGH"],
            "severity": _SEVERITY_MEDIUM,
            "detail": (
                f"Capital lock risk {cap_lock:.2f} exceeds profile ceiling {max_cap_lock:.2f}. "
                "Too much budget may be frozen in slow-moving positions."
            ),
        })

    # Check: minimum profit floor
    if min_profit_isk > 0.0 and total_profit < min_profit_isk:
        reason_codes.append({
            "code": "PROFIT_NOT_ACTIONABLE",
            "text": REASON_CODES["PROFIT_NOT_ACTIONABLE"],
            "severity": _SEVERITY_MEDIUM,
            "detail": (
                f"Expected profit {total_profit / 1_000_000:.1f}m ISK < "
                f"profile minimum {min_profit_isk / 1_000_000:.1f}m ISK. "
                "Execution costs and risk are not justified."
            ),
        })

    # Check: data quality
    if cal_warning:
        reason_codes.append({
            "code": "DATA_QUALITY_TOO_WEAK",
            "text": REASON_CODES["DATA_QUALITY_TOO_WEAK"],
            "severity": _SEVERITY_MEDIUM,
            "detail": f"Calibration warning: {cal_warning}",
        })

    # Check: too few high-quality picks
    if total_picks > 0 and len(strong_picks) < min_strong:
        reason_codes.append({
            "code": "TOO_FEW_HIGH_QUALITY_PICKS",
            "text": REASON_CODES["TOO_FEW_HIGH_QUALITY_PICKS"],
            "severity": _SEVERITY_HIGH,
            "detail": (
                f"Only {len(strong_picks)} mandatory/optional pick(s), "
                f"profile '{active_profile_name}' requires at least {min_strong}. "
                "The plan is too thin to be worth executing."
            ),
        })

    # Decision rule: DNT if any critical issue OR ≥2 high-severity issues
    critical_count = sum(1 for r in reason_codes if r["severity"] == _SEVERITY_CRITICAL)
    high_count = sum(1 for r in reason_codes if r["severity"] == _SEVERITY_HIGH)
    should_trade = (critical_count == 0) and (high_count < 2)

    return {
        "should_trade": should_trade,
        "reason_codes": reason_codes,
        "near_misses": _build_near_misses(non_actionable_routes),
        "profile_comparison": _build_profile_comparison(
            route_results, all_profiles, active_profile_name
        ),
        "actionable_route_count": len(actionable_routes),
        "total_route_count": total_routes,
        "best_route_summary": {
            "route_label": str(best_route.get("route_label", "") or ""),
            "route_confidence": route_conf,
            "transport_confidence": transport_conf,
            "capital_lock_risk": cap_lock,
            "total_expected_profit": total_profit,
            "mandatory_picks": len(mandatory),
            "optional_picks": len(optional),
            "speculative_picks": len(speculative),
        },
    }


__all__ = [
    "REASON_CODES",
    "evaluate_no_trade",
]
