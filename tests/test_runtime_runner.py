"""Targeted tests for shared runtime_runner post-processing helpers."""

from tests.shared import *  # noqa: F401,F403


def _route_pick(*, expected_profit: float, cost: float = 10_000_000.0) -> dict:
    return {
        "type_id": 42,
        "name": "RoutePick",
        "qty": 1,
        "unit_volume": 5.0,
        "cost": cost,
        "revenue_net": cost + expected_profit,
        "profit": expected_profit,
        "gross_profit_if_full_sell": expected_profit,
        "expected_realized_profit_90d": expected_profit,
        "transport_cost": 0.0,
        "shipping_cost": 0.0,
        "route_cost": 0.0,
    }


def _route_result(*, picks=None) -> dict:
    return {
        "route_label": "O4T -> UALX-3",
        "transport_mode": "internal_self_haul",
        "route_blocked_due_to_transport": False,
        "route_actionable": bool(picks),
        "route_prune_reason": "",
        "filters_used": {"_profile_min_expected_profit_isk": 500_000.0},
        "why_out_summary": {},
        "total_candidates": 0,
        "passed_all_filters": 0,
        "budget_total": 500_000_000.0,
        "cargo_total": 10_000.0,
        "picks": list(picks or []),
    }


def test_prune_reason_bucket_maps_budget_rule() -> None:
    assert nst._prune_reason_bucket("profile_max_item_share_of_budget") == "candidates_failed_budget_rule"


def test_derive_route_prune_reason_prefers_invalid_volume_bucket() -> None:
    result = {
        "picks": [],
        "route_blocked_due_to_transport": False,
        "route_prune_reason": "",
        "why_out_summary": {"invalid_volume": 3},
        "total_candidates": 0,
        "passed_all_filters": 0,
    }
    assert nst._derive_route_prune_reason(result) == "candidates_invalid_volume"


def test_internal_self_haul_operational_filter_suppresses_low_profit_route() -> None:
    result = _route_result(picks=[_route_pick(expected_profit=1_300_000.0)])
    nst._refresh_route_result_from_current_picks(result)
    out = nst._apply_internal_self_haul_operational_filter(
        result,
        {"route_search": {"internal_self_haul_min_expected_profit_isk": 2_000_000.0}},
    )
    assert out["route_actionable"] is False
    assert out["route_prune_reason"] == "internal_route_profit_below_operational_floor"
    assert out["operational_filter_applied"] is True
    assert float(out["suppressed_expected_realized_profit_total"]) == 1_300_000.0
    assert out["picks"] == []


def test_internal_self_haul_operational_filter_keeps_strong_route() -> None:
    result = _route_result(picks=[_route_pick(expected_profit=3_000_000.0)])
    nst._refresh_route_result_from_current_picks(result)
    out = nst._apply_internal_self_haul_operational_filter(
        result,
        {"route_search": {"internal_self_haul_min_expected_profit_isk": 2_000_000.0}},
    )
    assert out["route_actionable"] is True
    assert out["route_prune_reason"] == ""
    assert out["operational_filter_applied"] is False
    assert len(out["picks"]) == 1
