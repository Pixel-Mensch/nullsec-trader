"""Targeted tests for shared runtime_runner post-processing helpers."""

from tests.shared import *  # noqa: F401,F403
from route_search import summarize_route_for_ranking


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


def _scored_pick(
    *,
    type_id: int,
    name: str,
    expected_profit: float,
    overall_confidence: float,
    market_quality_score: float,
    manipulation_risk_score: float = 0.10,
) -> dict:
    cost = 10_000_000.0
    return {
        "type_id": int(type_id),
        "name": str(name),
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
        "instant": True,
        "exit_type": "instant",
        "overall_confidence": float(overall_confidence),
        "decision_overall_confidence": float(overall_confidence),
        "raw_overall_confidence": float(overall_confidence),
        "calibrated_overall_confidence": float(overall_confidence),
        "liquidity_confidence": float(overall_confidence),
        "raw_liquidity_confidence": float(overall_confidence),
        "calibrated_liquidity_confidence": float(overall_confidence),
        "exit_confidence": float(overall_confidence),
        "raw_exit_confidence": float(overall_confidence),
        "calibrated_exit_confidence": float(overall_confidence),
        "market_plausibility_score": float(max(market_quality_score, 0.50)),
        "market_quality_score": float(market_quality_score),
        "manipulation_risk_score": float(manipulation_risk_score),
        "profit_at_top_of_book": float(expected_profit),
        "profit_at_conservative_executable_price": float(expected_profit * 0.95),
        "profit_retention_ratio": 0.95,
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


def test_route_mix_cleanup_removes_weak_optional_pick_when_quality_tradeoff_is_bad() -> None:
    result = _route_result(
        picks=[
            _scored_pick(type_id=1, name="Strong A", expected_profit=90_000_000.0, overall_confidence=0.82, market_quality_score=0.82),
            _scored_pick(type_id=2, name="Strong B", expected_profit=60_000_000.0, overall_confidence=0.80, market_quality_score=0.80),
            _scored_pick(type_id=3, name="Weak Optional", expected_profit=6_000_000.0, overall_confidence=0.56, market_quality_score=0.58, manipulation_risk_score=0.40),
        ]
    )
    result["transport_mode"] = "shipping_lane"
    nst._refresh_route_result_from_current_picks(result)
    before = summarize_route_for_ranking(result)

    out = nst._apply_post_selection_route_mix_cleanup(result, {})
    after = summarize_route_for_ranking(out)

    assert [p["name"] for p in out["picks"]] == ["Strong A", "Strong B"]
    assert out["route_mix_cleanup_applied"] is True
    assert int(out["route_mix_cleanup_removed_count"]) == 1
    assert "Weak Optional" in str(out["route_mix_cleanup_notes"][0])
    assert float(after["route_confidence"]) > float(before["route_confidence"])
    assert float(after["market_quality_factor"]) > float(before["market_quality_factor"])
    assert float(after["risk_adjusted_score"]) > float(before["risk_adjusted_score"])


def test_route_mix_cleanup_keeps_optional_pick_when_profile_needs_second_strong_pick() -> None:
    result = _route_result(
        picks=[
            _scored_pick(type_id=1, name="Strong A", expected_profit=120_000_000.0, overall_confidence=0.82, market_quality_score=0.82),
            _scored_pick(type_id=2, name="Weak Optional", expected_profit=6_000_000.0, overall_confidence=0.56, market_quality_score=0.58, manipulation_risk_score=0.40),
        ]
    )
    result["transport_mode"] = "shipping_lane"
    result["filters_used"] = {"_profile_name": "conservative"}
    nst._refresh_route_result_from_current_picks(result)

    out = nst._apply_post_selection_route_mix_cleanup(result, {})

    assert out["route_mix_cleanup_applied"] is False
    assert [p["name"] for p in out["picks"]] == ["Strong A", "Weak Optional"]


def test_route_mix_cleanup_removes_weak_speculative_price_sensitive_tail_pick() -> None:
    tail = _scored_pick(
        type_id=3,
        name="Weak Spec Tail",
        expected_profit=8_000_000.0,
        overall_confidence=0.52,
        market_quality_score=0.61,
        manipulation_risk_score=0.36,
    )
    tail["instant"] = False
    tail["mode"] = "planned_sell"
    tail["exit_type"] = "speculative"
    tail["profit_at_top_of_book"] = 8_000_000.0
    tail["profit_at_conservative_executable_price"] = 4_600_000.0
    tail["profit_retention_ratio"] = 0.575

    result = _route_result(
        picks=[
            _scored_pick(type_id=1, name="Strong A", expected_profit=90_000_000.0, overall_confidence=0.82, market_quality_score=0.82),
            _scored_pick(type_id=2, name="Strong B", expected_profit=60_000_000.0, overall_confidence=0.80, market_quality_score=0.80),
            tail,
        ]
    )
    result["transport_mode"] = "shipping_lane"
    nst._refresh_route_result_from_current_picks(result)

    out = nst._apply_post_selection_route_mix_cleanup(result, {})

    assert [p["name"] for p in out["picks"]] == ["Strong A", "Strong B"]
    assert out["route_mix_cleanup_applied"] is True
    assert "Weak Spec Tail" in str(out["route_mix_cleanup_notes"][0])
    assert "price-sensitive" in str(out["route_mix_cleanup_notes"][0])
