"""Tests for risk profiles.

Covers:
- conservative vs aggressive filter differences
- instant_only blocks planned_sell
- high_liquidity prefers liquid candidates
- low_maintenance reduces item count
- profiles influence route ranking scores
- profiles influence portfolio selection via portfolio_cfg
- profile resolution (env var, CLI, config)
"""
from __future__ import annotations

import os

import pytest

from risk_profiles import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE,
    apply_profile_to_filters,
    apply_profile_to_portfolio_cfg,
    apply_profile_to_route_result,
    compute_profile_route_score_multiplier,
    filter_picks_by_profile,
    profile_header_lines,
    profile_restrictions_summary,
    resolve_active_profile,
)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

def _base_filters() -> dict:
    return {
        "mode": "instant",
        "price_depth_pct": 0.10,
        "min_depth_units": 1,
        "min_profit_pct": 0.02,
        "min_profit_isk_total": 0.0,
        "min_fill_probability": 0.0,
        "max_expected_days_to_sell": 99_999.0,
        "planned_min_liquidity_confidence": 0.0,
        "min_expected_profit_isk": 0.0,
    }


def _base_portfolio_cfg() -> dict:
    return {
        "max_item_share_of_budget": 1.0,
        "max_items": 999,
        "max_liquidation_days_per_position": 99_999.0,
    }


def _route_summary(
    stale: float = 0.0,
    speculative: float = 0.0,
    concentration: float = 0.0,
    capital_lock: float = 0.0,
    risk_adjusted_score: float = 1_000_000.0,
) -> dict:
    return {
        "stale_market_penalty": stale,
        "speculative_penalty": speculative,
        "concentration_penalty": concentration,
        "capital_lock_risk": capital_lock,
        "risk_adjusted_score": risk_adjusted_score,
        "actionable": True,
        "total_expected_realized_profit": risk_adjusted_score,
        "total_full_sell_profit": risk_adjusted_score,
        "average_expected_days_to_sell": 0.0,
        "route_confidence": 0.8,
        "transport_confidence": 1.0,
    }


# ---------------------------------------------------------------------------
# 1. conservative vs aggressive – filter tightening
# ---------------------------------------------------------------------------

class TestConservativeVsAggressive:
    def test_conservative_tightens_fill_probability(self):
        filters = _base_filters()
        out = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], filters)
        assert out["min_fill_probability"] >= BUILTIN_PROFILES["conservative"]["min_fill_probability"]
        assert out["min_fill_probability"] > filters["min_fill_probability"]

    def test_aggressive_does_not_raise_fill_probability_above_config(self):
        # aggressive has low min_fill_probability; should not tighten above base 0.0
        filters = _base_filters()
        out_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], filters)
        out_con = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], filters)
        assert out_agg["min_fill_probability"] <= out_con["min_fill_probability"]

    def test_conservative_max_days_stricter_than_aggressive(self):
        filters = _base_filters()
        out_con = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], filters)
        out_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], filters)
        assert out_con["max_expected_days_to_sell"] < out_agg["max_expected_days_to_sell"]

    def test_conservative_min_profit_isk_stricter(self):
        filters = _base_filters()
        out_con = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], filters)
        out_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], filters)
        assert out_con["min_expected_profit_isk"] > out_agg["min_expected_profit_isk"]

    def test_profile_name_stored_in_filters(self):
        filters = _base_filters()
        out = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], filters)
        assert out.get("_profile_name") == "conservative"

    def test_aggressive_portfolio_allows_more_items(self):
        cfg_con = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["conservative"], _base_portfolio_cfg())
        cfg_agg = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["aggressive"], _base_portfolio_cfg())
        assert cfg_con["max_items"] < cfg_agg["max_items"]

    def test_conservative_portfolio_tighter_budget_share(self):
        cfg_con = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["conservative"], _base_portfolio_cfg())
        cfg_agg = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["aggressive"], _base_portfolio_cfg())
        assert cfg_con["max_item_share_of_budget"] < cfg_agg["max_item_share_of_budget"]

    def test_conservative_portfolio_shorter_liquidation_days(self):
        cfg_con = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["conservative"], _base_portfolio_cfg())
        cfg_agg = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["aggressive"], _base_portfolio_cfg())
        assert cfg_con["max_liquidation_days_per_position"] < cfg_agg["max_liquidation_days_per_position"]


# ---------------------------------------------------------------------------
# 2. instant_only blocks planned_sell
# ---------------------------------------------------------------------------

class TestInstantOnly:
    def test_instant_only_disallows_planned_sell(self):
        filters = _base_filters()
        out = apply_profile_to_filters("instant_only", BUILTIN_PROFILES["instant_only"], filters)
        assert out["_profile_allow_planned_sell"] is False

    def test_balanced_allows_planned_sell(self):
        filters = _base_filters()
        out = apply_profile_to_filters("balanced", BUILTIN_PROFILES["balanced"], filters)
        assert out["_profile_allow_planned_sell"] is True

    def test_aggressive_allows_planned_sell(self):
        filters = _base_filters()
        out = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], filters)
        assert out["_profile_allow_planned_sell"] is True

    def test_conservative_disallows_planned_sell(self):
        filters = _base_filters()
        out = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], filters)
        assert out["_profile_allow_planned_sell"] is False

    def test_low_maintenance_disallows_planned_sell(self):
        filters = _base_filters()
        out = apply_profile_to_filters("low_maintenance", BUILTIN_PROFILES["low_maintenance"], filters)
        assert out["_profile_allow_planned_sell"] is False

    def test_instant_only_very_short_max_days(self):
        filters = _base_filters()
        out = apply_profile_to_filters("instant_only", BUILTIN_PROFILES["instant_only"], filters)
        assert out["max_expected_days_to_sell"] <= 1.0


# ---------------------------------------------------------------------------
# 3. high_liquidity prefers liquid markets
# ---------------------------------------------------------------------------

class TestHighLiquidity:
    def test_high_liquidity_tighter_fill_probability_than_aggressive(self):
        filters = _base_filters()
        out_hl = apply_profile_to_filters("high_liquidity", BUILTIN_PROFILES["high_liquidity"], filters)
        out_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], filters)
        assert out_hl["min_fill_probability"] > out_agg["min_fill_probability"]

    def test_high_liquidity_tighter_liquidity_confidence(self):
        filters = _base_filters()
        out_hl = apply_profile_to_filters("high_liquidity", BUILTIN_PROFILES["high_liquidity"], filters)
        out_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], filters)
        assert out_hl["planned_min_liquidity_confidence"] > out_agg["planned_min_liquidity_confidence"]

    def test_high_liquidity_heavier_stale_penalty_than_aggressive(self):
        summary = _route_summary(stale=0.20)
        mult_hl = compute_profile_route_score_multiplier(BUILTIN_PROFILES["high_liquidity"], summary)
        mult_agg = compute_profile_route_score_multiplier(BUILTIN_PROFILES["aggressive"], summary)
        # high_liquidity penalizes stale routes harder → lower multiplier
        assert mult_hl < mult_agg

    def test_high_liquidity_min_profit_per_m3_stored(self):
        filters = _base_filters()
        out = apply_profile_to_filters("high_liquidity", BUILTIN_PROFILES["high_liquidity"], filters)
        assert out.get("_profile_min_profit_per_m3", 0.0) > 0.0


# ---------------------------------------------------------------------------
# 4. low_maintenance reduces item count and speculative picks
# ---------------------------------------------------------------------------

class TestLowMaintenance:
    def test_low_maintenance_max_items_lower_than_balanced(self):
        cfg_lm = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["low_maintenance"], _base_portfolio_cfg())
        cfg_bal = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["balanced"], _base_portfolio_cfg())
        assert cfg_lm["max_items"] < cfg_bal["max_items"]

    def test_low_maintenance_max_items_at_most_12(self):
        cfg = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["low_maintenance"], _base_portfolio_cfg())
        assert cfg["max_items"] <= 12

    def test_low_maintenance_disallows_planned_sell(self):
        filters = _base_filters()
        out = apply_profile_to_filters("low_maintenance", BUILTIN_PROFILES["low_maintenance"], filters)
        assert out["_profile_allow_planned_sell"] is False

    def test_low_maintenance_higher_speculative_penalty_than_balanced(self):
        summary = _route_summary(speculative=0.25)
        mult_lm = compute_profile_route_score_multiplier(BUILTIN_PROFILES["low_maintenance"], summary)
        mult_bal = compute_profile_route_score_multiplier(BUILTIN_PROFILES["balanced"], summary)
        # low_maintenance penalizes speculative harder
        assert mult_lm < mult_bal

    def test_low_maintenance_min_profit_isk_set(self):
        filters = _base_filters()
        out = apply_profile_to_filters("low_maintenance", BUILTIN_PROFILES["low_maintenance"], filters)
        assert out["min_expected_profit_isk"] >= BUILTIN_PROFILES["low_maintenance"]["min_expected_profit_isk"]


# ---------------------------------------------------------------------------
# 5. Route ranking: profiles influence score
# ---------------------------------------------------------------------------

class TestRouteRanking:
    def test_clean_route_multiplier_is_one_for_balanced(self):
        summary = _route_summary()  # no penalties
        mult = compute_profile_route_score_multiplier(BUILTIN_PROFILES["balanced"], summary)
        assert mult == pytest.approx(1.0)

    def test_stale_route_penalized_harder_by_conservative(self):
        summary = _route_summary(stale=0.20)
        mult_con = compute_profile_route_score_multiplier(BUILTIN_PROFILES["conservative"], summary)
        mult_bal = compute_profile_route_score_multiplier(BUILTIN_PROFILES["balanced"], summary)
        assert mult_con < mult_bal

    def test_speculative_route_penalized_harder_by_instant_only(self):
        summary = _route_summary(speculative=0.30)
        mult_io = compute_profile_route_score_multiplier(BUILTIN_PROFILES["instant_only"], summary)
        mult_bal = compute_profile_route_score_multiplier(BUILTIN_PROFILES["balanced"], summary)
        assert mult_io < mult_bal

    def test_aggressive_softens_all_penalties(self):
        summary = _route_summary(stale=0.15, speculative=0.15, concentration=0.20, capital_lock=0.50)
        mult_agg = compute_profile_route_score_multiplier(BUILTIN_PROFILES["aggressive"], summary)
        mult_con = compute_profile_route_score_multiplier(BUILTIN_PROFILES["conservative"], summary)
        assert mult_agg > mult_con

    def test_apply_profile_to_route_result_stores_score(self):
        route = {
            "picks": [],
            "expected_realized_profit_total": 10_000_000.0,
            "full_sell_profit_total": 12_000_000.0,
            "route_blocked_due_to_transport": False,
            "stale_market_penalty": 0.0,
            "speculative_penalty": 0.0,
        }
        apply_profile_to_route_result("balanced", BUILTIN_PROFILES["balanced"], route)
        assert "_profile_risk_adjusted_score" in route
        assert "_profile_score_multiplier" in route
        assert route["_active_risk_profile"] == "balanced"

    def test_apply_profile_to_route_result_conservative_lower_than_aggressive_on_risky_route(self):
        """Same risky route data → conservative scores it lower than aggressive."""
        picks = [
            {
                "exit_type": "planned",
                "used_volume_fallback": True,
                "expected_realized_profit_90d": 5_000_000.0,
                "expected_days_to_sell": 60.0,
                "decision_overall_confidence": 0.4,
                "raw_overall_confidence": 0.4,
                "calibrated_overall_confidence": 0.4,
                "raw_exit_confidence": 0.4,
                "raw_liquidity_confidence": 0.4,
                "raw_transport_confidence": 1.0,
                "fill_probability": 0.4,
            }
        ]
        route_base = {
            "picks": picks,
            "expected_realized_profit_total": 5_000_000.0,
            "full_sell_profit_total": 8_000_000.0,
            "route_blocked_due_to_transport": False,
            "cost_model_confidence": "normal",
            "transport_confidence_for_decision": 1.0,
        }
        import copy
        route_con = copy.deepcopy(route_base)
        route_agg = copy.deepcopy(route_base)
        apply_profile_to_route_result("conservative", BUILTIN_PROFILES["conservative"], route_con)
        apply_profile_to_route_result("aggressive", BUILTIN_PROFILES["aggressive"], route_agg)
        # Conservative should score the risky route lower (or equal)
        assert route_con["_profile_risk_adjusted_score"] <= route_agg["_profile_risk_adjusted_score"]


# ---------------------------------------------------------------------------
# 6. Portfolio selection: profiles restrict choices
# ---------------------------------------------------------------------------

class TestPortfolioProfile:
    def test_profile_does_not_relax_existing_strict_portfolio_limit(self):
        """Profile should never exceed a stricter existing config value."""
        cfg_strict = {"max_item_share_of_budget": 0.10, "max_items": 5, "max_liquidation_days_per_position": 7.0}
        # balanced profile has higher max_items (40) but strict config is 5
        out = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["balanced"], cfg_strict)
        assert out["max_items"] == 5  # profile cannot relax this
        assert out["max_item_share_of_budget"] == pytest.approx(0.10)

    def test_profile_tightens_loose_portfolio_limits(self):
        """Profile should tighten when config is more permissive."""
        cfg_loose = {"max_item_share_of_budget": 1.0, "max_items": 9_999, "max_liquidation_days_per_position": 99_999.0}
        out = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["conservative"], cfg_loose)
        assert out["max_items"] == BUILTIN_PROFILES["conservative"]["max_items"]
        assert out["max_item_share_of_budget"] == pytest.approx(BUILTIN_PROFILES["conservative"]["max_item_share_of_budget"])


# ---------------------------------------------------------------------------
# 7. filter_picks_by_profile (post-build min_profit_per_m3)
# ---------------------------------------------------------------------------

class TestFilterPicksByProfile:
    def test_no_filter_when_no_min_profit_per_m3(self):
        picks = [{"expected_realized_profit_per_m3_90d": 100.0}, {"expected_realized_profit_per_m3_90d": 5.0}]
        filters_used = {"_profile_min_profit_per_m3": 0.0}
        kept, rejected = filter_picks_by_profile(picks, filters_used)
        assert len(kept) == 2
        assert len(rejected) == 0

    def test_picks_below_threshold_rejected(self):
        picks = [
            {"name": "Good Item", "expected_realized_profit_per_m3_90d": 1_500.0},
            {"name": "Weak Item", "expected_realized_profit_per_m3_90d": 100.0},
        ]
        filters_used = {"_profile_min_profit_per_m3": 1_000.0, "_profile_name": "conservative"}
        kept, rejected = filter_picks_by_profile(picks, filters_used)
        assert len(kept) == 1
        assert len(rejected) == 1
        assert "profile_rejection_reason" in rejected[0] or "_profile_rejection_reason" in rejected[0]


# ---------------------------------------------------------------------------
# 8. Profile resolution
# ---------------------------------------------------------------------------

class TestProfileResolution:
    def test_default_profile_is_balanced(self):
        name, _ = resolve_active_profile({})
        assert name == DEFAULT_PROFILE

    def test_cli_profile_overrides_default(self):
        cfg = {"_cli_risk_profile": "conservative"}
        name, _ = resolve_active_profile(cfg)
        assert name == "conservative"

    def test_config_section_name_used(self):
        cfg = {"risk_profile": {"name": "aggressive"}}
        name, _ = resolve_active_profile(cfg)
        assert name == "aggressive"

    def test_invalid_profile_name_falls_back_to_default(self):
        cfg = {"_cli_risk_profile": "does_not_exist"}
        name, _ = resolve_active_profile(cfg)
        assert name == DEFAULT_PROFILE

    def test_env_var_overrides_cli(self, monkeypatch):
        monkeypatch.setenv("NULLSEC_RISK_PROFILE", "instant_only")
        cfg = {"_cli_risk_profile": "aggressive"}
        name, _ = resolve_active_profile(cfg)
        assert name == "instant_only"

    def test_env_var_ignored_if_invalid(self, monkeypatch):
        monkeypatch.setenv("NULLSEC_RISK_PROFILE", "not_a_profile")
        cfg = {"_cli_risk_profile": "conservative"}
        name, _ = resolve_active_profile(cfg)
        assert name == "conservative"

    def test_config_overrides_applied_on_top_of_builtin(self):
        cfg = {"risk_profile": {"name": "balanced", "min_fill_probability": 0.99}}
        _, params = resolve_active_profile(cfg)
        assert params["min_fill_probability"] == pytest.approx(0.99)

    def test_all_builtin_profiles_exist(self):
        for name in ("conservative", "balanced", "aggressive", "instant_only", "high_liquidity", "low_maintenance"):
            assert name in BUILTIN_PROFILES, f"Missing profile: {name}"


# ---------------------------------------------------------------------------
# 9. Output helpers
# ---------------------------------------------------------------------------

class TestOutputHelpers:
    def test_profile_header_lines_contains_profile_name(self):
        lines = profile_header_lines("conservative", BUILTIN_PROFILES["conservative"])
        combined = "\n".join(lines)
        assert "CONSERVATIVE" in combined

    def test_profile_header_shows_planned_sell_blocked_for_instant_only(self):
        lines = profile_header_lines("instant_only", BUILTIN_PROFILES["instant_only"])
        combined = "\n".join(lines)
        assert "BLOCKED" in combined

    def test_profile_header_shows_planned_sell_allowed_for_aggressive(self):
        lines = profile_header_lines("aggressive", BUILTIN_PROFILES["aggressive"])
        combined = "\n".join(lines)
        assert "allowed" in combined

    def test_profile_restrictions_summary_contains_profile_name(self):
        summary = profile_restrictions_summary("balanced", BUILTIN_PROFILES["balanced"])
        assert "BALANCED" in summary

    def test_profile_restrictions_summary_instant_only_shows_blocked(self):
        summary = profile_restrictions_summary("instant_only", BUILTIN_PROFILES["instant_only"])
        assert "BLOCKED" in summary


# ---------------------------------------------------------------------------
# 10. End-to-end integration: profiles produce different outcomes on same data
# ---------------------------------------------------------------------------

def _make_pick(
    type_id: int,
    name: str,
    *,
    overall_confidence: float = 0.50,
    decision_overall_confidence: float | None = None,
    expected_realized_profit_per_m3_90d: float = 1_000.0,
    expected_realized_profit_90d: float = 5_000_000.0,
    mode: str = "instant",
    instant: bool = True,
) -> dict:
    return {
        "type_id": type_id,
        "name": name,
        "qty": 1,
        "unit_volume": 5.0,
        "cost": 10_000_000.0,
        "revenue_net": 15_000_000.0,
        "profit": 5_000_000.0,
        "profit_per_m3": expected_realized_profit_per_m3_90d,
        "instant": instant,
        "mode": mode,
        "overall_confidence": overall_confidence,
        "decision_overall_confidence": decision_overall_confidence if decision_overall_confidence is not None else overall_confidence,
        "calibrated_overall_confidence": overall_confidence,
        "expected_realized_profit_90d": expected_realized_profit_90d,
        "expected_realized_profit_per_m3_90d": expected_realized_profit_per_m3_90d,
        "expected_days_to_sell": 5.0,
    }


class TestProfileEndToEnd:
    """Verify that profiles produce different outcomes when applied to the same set of picks."""

    def test_conservative_removes_low_profit_per_m3_picks(self):
        """conservative min_profit_per_m3=2000 should remove a pick at 100 ISK/m3."""
        picks = [
            _make_pick(1, "Dense Item", expected_realized_profit_per_m3_90d=5_000.0),
            _make_pick(2, "Thin Item", expected_realized_profit_per_m3_90d=100.0),
        ]
        filters_con = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], _base_filters())
        kept, rejected = filter_picks_by_profile(picks, filters_con)
        assert len(kept) == 1
        assert kept[0]["name"] == "Dense Item"
        assert len(rejected) == 1

    def test_aggressive_keeps_all_picks_regardless_of_profit_density(self):
        """aggressive has min_profit_per_m3=0 → no picks removed by profit/m3 gate."""
        picks = [
            _make_pick(1, "Dense", expected_realized_profit_per_m3_90d=5_000.0),
            _make_pick(2, "Thin", expected_realized_profit_per_m3_90d=50.0),
        ]
        filters_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], _base_filters())
        kept, rejected = filter_picks_by_profile(picks, filters_agg)
        assert len(kept) == 2
        assert len(rejected) == 0

    def test_conservative_confidence_gate_removes_low_confidence_pick(self):
        """
        conservative min_confidence=0.70 should remove picks with
        decision_overall_confidence < 0.70.
        """
        # Simulate the post-calibration confidence gate (Gap 2 fix in runtime_runner).
        filters_con = apply_profile_to_filters("conservative", BUILTIN_PROFILES["conservative"], _base_filters())
        min_conf = float(filters_con.get("_profile_min_confidence", 0.0))
        assert min_conf >= 0.70, "conservative must set min_confidence >= 0.70"

        picks = [
            _make_pick(1, "HighConf", decision_overall_confidence=0.85),
            _make_pick(2, "LowConf", decision_overall_confidence=0.45),
        ]
        kept = [
            p for p in picks
            if float(p.get("decision_overall_confidence", 0.0)) >= min_conf
        ]
        assert len(kept) == 1
        assert kept[0]["name"] == "HighConf"

    def test_aggressive_confidence_gate_keeps_low_confidence_pick(self):
        """aggressive min_confidence=0.20 — low-confidence picks survive."""
        filters_agg = apply_profile_to_filters("aggressive", BUILTIN_PROFILES["aggressive"], _base_filters())
        min_conf = float(filters_agg.get("_profile_min_confidence", 0.0))
        assert min_conf <= 0.25

        picks = [
            _make_pick(1, "HighConf", decision_overall_confidence=0.85),
            _make_pick(2, "LowConf", decision_overall_confidence=0.25),
        ]
        kept = [
            p for p in picks
            if float(p.get("decision_overall_confidence", 0.0)) >= min_conf
        ]
        assert len(kept) == 2

    def test_instant_only_filters_planned_sell_candidates_at_mode_level(self):
        """instant_only must block planned_sell at the filter level."""
        filters_io = apply_profile_to_filters("instant_only", BUILTIN_PROFILES["instant_only"], _base_filters())
        assert filters_io["_profile_allow_planned_sell"] is False
        assert float(filters_io["max_expected_days_to_sell"]) <= 1.0

    def test_high_liquidity_vs_aggressive_route_score_with_stale_market(self):
        """Same stale route: high_liquidity penalizes harder than aggressive."""
        summary = _route_summary(stale=0.30, capital_lock=0.40)
        mult_hl = compute_profile_route_score_multiplier(BUILTIN_PROFILES["high_liquidity"], summary)
        mult_agg = compute_profile_route_score_multiplier(BUILTIN_PROFILES["aggressive"], summary)
        assert mult_hl < mult_agg, (
            f"high_liquidity ({mult_hl:.3f}) must penalize stale route more than aggressive ({mult_agg:.3f})"
        )

    def test_low_maintenance_max_items_caps_portfolio(self):
        """low_maintenance max_items=12 must restrict portfolio regardless of base config."""
        cfg_loose = _base_portfolio_cfg()  # max_items=999
        out = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["low_maintenance"], cfg_loose)
        assert out["max_items"] <= 12

    def test_balanced_vs_conservative_same_candidates_different_portfolio_size(self):
        """
        Conservative's tighter item cap means smaller allowed portfolio than balanced.
        """
        import copy
        cfg_bal = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["balanced"], _base_portfolio_cfg())
        cfg_con = apply_profile_to_portfolio_cfg(BUILTIN_PROFILES["conservative"], _base_portfolio_cfg())
        assert cfg_con["max_items"] < cfg_bal["max_items"]
        assert cfg_con["max_item_share_of_budget"] < cfg_bal["max_item_share_of_budget"]

    def test_filter_picks_by_profile_adds_rejection_reason(self):
        """Rejected picks must carry _profile_rejection_reason for explainability."""
        picks = [_make_pick(1, "PoorDensity", expected_realized_profit_per_m3_90d=10.0)]
        filters_used = {"_profile_min_profit_per_m3": 500.0, "_profile_name": "high_liquidity"}
        _, rejected = filter_picks_by_profile(picks, filters_used)
        assert len(rejected) == 1
        assert "_profile_rejection_reason" in rejected[0]
        assert "high_liquidity" in rejected[0]["_profile_rejection_reason"]

    def test_profile_applied_to_route_result_shows_profile_name(self):
        """apply_profile_to_route_result must stamp _active_risk_profile on the result."""
        route = {
            "picks": [],
            "expected_realized_profit_total": 1_000_000.0,
            "full_sell_profit_total": 1_200_000.0,
            "route_blocked_due_to_transport": False,
        }
        apply_profile_to_route_result("low_maintenance", BUILTIN_PROFILES["low_maintenance"], route)
        assert route.get("_active_risk_profile") == "low_maintenance"
        assert "_profile_risk_adjusted_score" in route
