"""Tests for the restructured execution plan output (Task 2).

Covers:
- Pick categorisation (_categorize_pick)
- Price-sensitivity detection (_is_price_sensitive)
- Pick warning generation (_pick_action_warnings)
- Route-level warning generation (_route_level_warnings)
- Shopping list output (_write_shopping_list)
- Route trip summary output (_write_route_trip_summary)
- Full write_execution_plan_profiles (normal, compact, detail modes)
- --compact / --detail flag parsing in runtime_common
"""
from __future__ import annotations

import os
import tempfile

import pytest

from execution_plan import (
    _CAT_MANDATORY,
    _CAT_OPTIONAL,
    _CAT_SPECULATIVE,
    _categorize_pick,
    _is_price_sensitive,
    _pick_action_warnings,
    _route_level_warnings,
    _write_shopping_list,
    _write_route_trip_summary,
    write_execution_plan_profiles,
)
from runtime_common import parse_cli_args


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _instant_pick(**kwargs) -> dict:
    base = {
        "name": "Tritanium",
        "type_id": 34,
        "qty": 1000,
        "buy_avg": 4.5,
        "sell_avg": 5.1,
        "target_sell_price": 5.1,
        "profit": 600.0,
        "expected_realized_profit_90d": 580.0,
        "instant": True,
        "mode": "instant",
        "exit_type": "instant",
        "fill_probability": 0.92,
        "liquidity_confidence": 0.92,
        "overall_confidence": 0.88,
        "expected_days_to_sell": 0.3,
        "market_plausibility_score": 0.95,
        "market_quality_score": 0.93,
        "manipulation_risk_score": 0.02,
        "unit_volume": 0.01,
        "order_duration_days": 0,
        "profit_at_top_of_book": 600.0,
        "profit_at_conservative_executable_price": 580.0,
        "profit_retention_ratio": 0.97,
    }
    base.update(kwargs)
    return base


def _planned_pick(**kwargs) -> dict:
    base = {
        "name": "Zydrine",
        "type_id": 39,
        "qty": 100,
        "buy_avg": 1200.0,
        "sell_avg": 1500.0,
        "target_sell_price": 1500.0,
        "profit": 30_000.0,
        "expected_realized_profit_90d": 20_000.0,
        "instant": False,
        "mode": "planned_sell",
        "exit_type": "planned_sell",
        "fill_probability": 0.55,
        "liquidity_confidence": 0.55,
        "overall_confidence": 0.55,
        "expected_days_to_sell": 20.0,
        "market_plausibility_score": 0.80,
        "market_quality_score": 0.78,
        "manipulation_risk_score": 0.05,
        "unit_volume": 1.0,
        "order_duration_days": 30,
        "profit_at_top_of_book": 30_000.0,
        "profit_at_conservative_executable_price": 20_000.0,
        "profit_retention_ratio": 0.67,
    }
    base.update(kwargs)
    return base


def _speculative_pick(**kwargs) -> dict:
    base = {
        "name": "Dark Glitter",
        "type_id": 46678,
        "qty": 10,
        "buy_avg": 5_000_000.0,
        "sell_avg": 6_000_000.0,
        "target_sell_price": 6_000_000.0,
        "profit": 10_000_000.0,
        "expected_realized_profit_90d": 2_000_000.0,
        "instant": False,
        "mode": "planned_sell",
        "exit_type": "speculative",
        "fill_probability": 0.20,
        "liquidity_confidence": 0.20,
        "overall_confidence": 0.25,  # below 0.40 → speculative
        "expected_days_to_sell": 80.0,
        "market_plausibility_score": 0.45,
        "manipulation_risk_score": 0.60,
        "unit_volume": 10.0,
        "order_duration_days": 90,
        "profit_at_top_of_book": 10_000_000.0,
        "profit_at_conservative_executable_price": 2_000_000.0,
    }
    base.update(kwargs)
    return base


def _route_summary(**kwargs) -> dict:
    base = {
        "actionable": True,
        "route_confidence": 0.80,
        "transport_confidence": 0.85,
        "capital_lock_risk": 0.10,
        "total_expected_realized_profit": 50_000.0,
        "total_full_sell_profit": 60_000.0,
        "stale_market_penalty": 0.0,
        "speculative_penalty": 0.0,
        "concentration_penalty": 0.0,
        "positive_reasons": [],
        "negative_reasons": [],
        "warnings": [],
        "score_contributors": [],
        "confidence_contributors": [],
    }
    base.update(kwargs)
    return base


def _leg(picks=None, **kwargs) -> dict:
    base = {
        "route_label": "Jita -> Perimeter",
        "source_label": "Jita IV-4",
        "dest_label": "Perimeter TTT",
        "isk_used": 200_000.0,
        "budget_total": 500_000.0,
        "cargo_m3": 10_000.0,
        "m3_used": 5_000.0,
        "total_route_m3": 5_000.0,
        "profit_total": 50_000.0,
        "total_transport_cost": 1_000.0,
        "total_shipping_cost": 0.0,
        "picks": picks or [],
        "_active_risk_profile": "balanced",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Test _categorize_pick
# ---------------------------------------------------------------------------

class TestCategorizePick:
    def test_instant_high_confidence_is_mandatory(self):
        p = _instant_pick(overall_confidence=0.85, liquidity_confidence=0.85)
        assert _categorize_pick(p) == _CAT_MANDATORY

    def test_instant_low_confidence_is_not_mandatory(self):
        p = _instant_pick(overall_confidence=0.30, liquidity_confidence=0.90)
        assert _categorize_pick(p) == _CAT_SPECULATIVE

    def test_instant_low_liquidity_not_mandatory(self):
        # overall_conf >= 0.60 but liquidity < 0.60 → optional
        p = _instant_pick(overall_confidence=0.75, liquidity_confidence=0.50)
        assert _categorize_pick(p) == _CAT_OPTIONAL

    def test_planned_moderate_confidence_is_optional(self):
        p = _planned_pick(overall_confidence=0.55, expected_days_to_sell=20.0)
        assert _categorize_pick(p) == _CAT_OPTIONAL

    def test_planned_very_long_wait_is_speculative(self):
        p = _planned_pick(overall_confidence=0.60, expected_days_to_sell=65.0)
        assert _categorize_pick(p) == _CAT_SPECULATIVE

    def test_low_overall_confidence_is_speculative(self):
        p = _planned_pick(overall_confidence=0.35)
        assert _categorize_pick(p) == _CAT_SPECULATIVE

    def test_low_plausibility_is_speculative(self):
        p = _planned_pick(overall_confidence=0.60, market_plausibility_score=0.40)
        assert _categorize_pick(p) == _CAT_SPECULATIVE

    def test_high_manipulation_risk_is_speculative(self):
        p = _instant_pick(overall_confidence=0.80, liquidity_confidence=0.80, manipulation_risk_score=0.60)
        assert _categorize_pick(p) == _CAT_SPECULATIVE

    def test_planned_sell_at_60d_boundary_optional(self):
        # exactly 60d is NOT > 60 → optional if other criteria met
        p = _planned_pick(overall_confidence=0.55, expected_days_to_sell=60.0)
        assert _categorize_pick(p) == _CAT_OPTIONAL

    def test_planned_sell_just_over_60d_speculative(self):
        p = _planned_pick(overall_confidence=0.55, expected_days_to_sell=60.1)
        assert _categorize_pick(p) == _CAT_SPECULATIVE

    def test_price_sensitive_instant_pick_is_not_mandatory(self):
        p = _instant_pick(
            overall_confidence=0.82,
            liquidity_confidence=0.82,
            market_quality_score=0.80,
            profit_at_top_of_book=1_000_000.0,
            profit_at_conservative_executable_price=600_000.0,
            profit_retention_ratio=0.60,
        )
        assert _categorize_pick(p) == _CAT_OPTIONAL

    def test_fragile_market_quality_is_speculative_even_if_plausibility_looks_ok(self):
        p = _instant_pick(
            overall_confidence=0.82,
            liquidity_confidence=0.82,
            market_plausibility_score=0.78,
            market_quality_score=0.48,
            manipulation_risk_score=0.42,
        )
        assert _categorize_pick(p) == _CAT_SPECULATIVE


# ---------------------------------------------------------------------------
# Test _is_price_sensitive
# ---------------------------------------------------------------------------

class TestIsPriceSensitive:
    def test_not_sensitive_when_profits_close(self):
        p = _instant_pick(
            profit_at_top_of_book=600.0,
            profit_at_conservative_executable_price=550.0,  # 92% retained
        )
        assert not _is_price_sensitive(p)

    def test_sensitive_when_large_drop(self):
        p = _instant_pick(
            profit_at_top_of_book=1_000_000.0,
            profit_at_conservative_executable_price=500_000.0,  # 50% retained → sensitive
        )
        assert _is_price_sensitive(p)

    def test_not_sensitive_at_boundary(self):
        # 65% retained → not sensitive (threshold is < 65%)
        p = _instant_pick(
            profit_at_top_of_book=1_000.0,
            profit_at_conservative_executable_price=650.0,
        )
        assert not _is_price_sensitive(p)

    def test_sensitive_just_below_boundary(self):
        p = _instant_pick(
            profit_at_top_of_book=1_000.0,
            profit_at_conservative_executable_price=649.0,
        )
        assert _is_price_sensitive(p)

    def test_not_sensitive_when_book_profit_zero(self):
        p = _instant_pick(profit_at_top_of_book=0.0, profit_at_conservative_executable_price=0.0)
        assert not _is_price_sensitive(p)


# ---------------------------------------------------------------------------
# Test _pick_action_warnings
# ---------------------------------------------------------------------------

class TestPickActionWarnings:
    def test_no_warnings_for_clean_instant(self):
        p = _instant_pick()
        assert _pick_action_warnings(p) == []

    def test_thin_market_warning(self):
        p = _instant_pick(liquidity_confidence=0.30)
        warns = _pick_action_warnings(p)
        assert any("Thin market" in w for w in warns)

    def test_manipulation_warning(self):
        p = _instant_pick(manipulation_risk_score=0.50)
        warns = _pick_action_warnings(p)
        assert any("Manipulation" in w for w in warns)

    def test_low_plausibility_warning(self):
        p = _instant_pick(market_plausibility_score=0.50)
        warns = _pick_action_warnings(p)
        assert any("plausibility" in w for w in warns)

    def test_long_capital_lock_warning_for_planned(self):
        p = _planned_pick(expected_days_to_sell=50.0)
        warns = _pick_action_warnings(p)
        assert any("capital lock" in w.lower() for w in warns)

    def test_no_long_lock_warning_for_instant(self):
        # instant pick with expected_days > 45 should not warn (it's instant)
        p = _instant_pick(expected_days_to_sell=50.0)
        warns = _pick_action_warnings(p)
        assert not any("capital lock" in w.lower() for w in warns)

    def test_price_sensitive_warning(self):
        p = _instant_pick(
            profit_at_top_of_book=1_000_000.0,
            profit_at_conservative_executable_price=400_000.0,
        )
        warns = _pick_action_warnings(p)
        assert any("Price-sensitive" in w for w in warns)

    def test_multiple_warnings(self):
        p = _planned_pick(
            liquidity_confidence=0.25,
            manipulation_risk_score=0.55,
            expected_days_to_sell=60.0,
        )
        warns = _pick_action_warnings(p)
        assert len(warns) >= 2


# ---------------------------------------------------------------------------
# Test _route_level_warnings
# ---------------------------------------------------------------------------

class TestRouteLevelWarnings:
    def test_no_warnings_clean_route(self):
        # Use a high total_profit so the picks don't trigger capital dominance (top3 < 60%)
        picks = [_instant_pick(profit=10_000.0), _planned_pick(profit=10_000.0)]
        summary = _route_summary(
            route_confidence=0.85,
            capital_lock_risk=0.10,
            total_expected_realized_profit=200_000.0,
        )
        warns = _route_level_warnings(picks, summary)
        assert warns == []

    def test_low_route_confidence_warning(self):
        picks = [_instant_pick()]
        summary = _route_summary(route_confidence=0.40)
        warns = _route_level_warnings(picks, summary)
        assert any("Low route confidence" in w for w in warns)

    def test_high_capital_lock_warning(self):
        picks = [_instant_pick()]
        summary = _route_summary(capital_lock_risk=0.70)
        warns = _route_level_warnings(picks, summary)
        assert any("concentration" in w.lower() for w in warns)

    def test_speculative_picks_warning(self):
        picks = [_speculative_pick()]
        summary = _route_summary()
        warns = _route_level_warnings(picks, summary)
        assert any("speculative" in w.lower() for w in warns)

    def test_capital_dominance_warning(self):
        # 3 picks where first pick has 80% of expected_realized_profit_90d
        p1 = _instant_pick(name="P1", profit=8_000.0, expected_realized_profit_90d=8_000.0)
        p2 = _instant_pick(name="P2", profit=1_000.0, expected_realized_profit_90d=1_000.0)
        p3 = _instant_pick(name="P3", profit=1_000.0, expected_realized_profit_90d=1_000.0)
        summary = _route_summary(total_expected_realized_profit=10_000.0)
        warns = _route_level_warnings([p1, p2, p3], summary)
        assert any("dominance" in w.lower() for w in warns)

    def test_no_dominance_warning_when_balanced(self):
        picks = [_instant_pick(name=f"P{i}", profit=1_000.0, expected_realized_profit_90d=1_000.0) for i in range(10)]
        summary = _route_summary(total_expected_realized_profit=10_000.0)
        warns = _route_level_warnings(picks, summary)
        assert not any("dominance" in w.lower() for w in warns)

    def test_calibration_warning_surfaced(self):
        picks = [_instant_pick()]
        summary = _route_summary(calibration_warning="thin historical data")
        warns = _route_level_warnings(picks, summary)
        assert any("Calibration" in w for w in warns)


# ---------------------------------------------------------------------------
# Test _write_shopping_list
# ---------------------------------------------------------------------------

class TestWriteShoppingList:
    def _fmt(self, x):
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    def test_shopping_list_header_present(self):
        lines: list[str] = []
        categorized = {_CAT_MANDATORY: [_instant_pick()], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: []}
        _write_shopping_list(lines, categorized, self._fmt)
        assert any("SHOPPING LIST" in l for l in lines)

    def test_mandatory_label_present(self):
        lines: list[str] = []
        categorized = {_CAT_MANDATORY: [_instant_pick()], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: []}
        _write_shopping_list(lines, categorized, self._fmt)
        assert any("Mandatory" in l for l in lines)

    def test_speculative_label_present_when_speculative_picks(self):
        lines: list[str] = []
        categorized = {_CAT_MANDATORY: [], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: [_speculative_pick()]}
        _write_shopping_list(lines, categorized, self._fmt)
        assert any("Speculative" in l for l in lines)

    def test_pick_name_in_shopping_list(self):
        lines: list[str] = []
        categorized = {_CAT_MANDATORY: [_instant_pick(name="Tritanium")], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: []}
        _write_shopping_list(lines, categorized, self._fmt)
        assert any("Tritanium" in l for l in lines)

    def test_price_sensitive_marker_shown(self):
        p = _instant_pick(
            profit_at_top_of_book=1_000_000.0,
            profit_at_conservative_executable_price=300_000.0,
        )
        lines: list[str] = []
        categorized = {_CAT_MANDATORY: [p], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: []}
        _write_shopping_list(lines, categorized, self._fmt)
        assert any("PRICE-SENS" in l for l in lines)

    def test_no_speculative_section_when_no_spec_picks(self):
        lines: list[str] = []
        categorized = {_CAT_MANDATORY: [_instant_pick()], _CAT_OPTIONAL: [], _CAT_SPECULATIVE: []}
        _write_shopping_list(lines, categorized, self._fmt)
        assert not any("Speculative" in l for l in lines)

    def test_global_index_increments_across_categories(self):
        lines: list[str] = []
        categorized = {
            _CAT_MANDATORY: [_instant_pick(name="A")],
            _CAT_OPTIONAL: [_planned_pick(name="B")],
            _CAT_SPECULATIVE: [],
        }
        _write_shopping_list(lines, categorized, self._fmt)
        pick_lines = [l for l in lines if l.strip().startswith("1.") or l.strip().startswith("2.")]
        assert len(pick_lines) == 2


# ---------------------------------------------------------------------------
# Test write_execution_plan_profiles (file output)
# ---------------------------------------------------------------------------

def _make_route_result(picks=None) -> dict:
    p_list = [_instant_pick(), _planned_pick()] if picks is None else picks
    return {
        "route_label": "Jita -> Perimeter",
        "source_label": "Jita IV-4",
        "dest_label": "Perimeter TTT",
        "isk_used": sum(float(p.get("buy_avg", 0)) * int(p.get("qty", 0)) for p in p_list),
        "budget_total": 10_000_000.0,
        "cargo_m3": 10_000.0,
        "m3_used": 2_000.0,
        "total_route_m3": 2_000.0,
        "profit_total": sum(float(p.get("profit", 0)) for p in p_list),
        "total_transport_cost": 100_000.0,
        "total_shipping_cost": 0.0,
        "picks": p_list,
        "_active_risk_profile": "balanced",
        "plan_id": "test-plan-001",
    }


class TestWriteExecutionPlanProfiles:
    def _write_and_read(self, route_results, detail_mode=False, compact_mode=False) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            path = f.name
        try:
            write_execution_plan_profiles(path, "2026-03-07T00:00:00", route_results, detail_mode=detail_mode, compact_mode=compact_mode)
            with open(path, encoding="utf-8") as f:
                return f.read()
        finally:
            os.unlink(path)

    def test_header_present(self):
        content = self._write_and_read([_make_route_result()])
        assert "EXECUTION PLAN" in content

    def test_shopping_list_present(self):
        content = self._write_and_read([_make_route_result()])
        assert "SHOPPING LIST" in content

    def test_route_summary_present(self):
        content = self._write_and_read([_make_route_result()])
        assert "ROUTE SUMMARY" in content

    def test_mandatory_section_present_when_instant_picks_exist(self):
        result = _make_route_result(picks=[_instant_pick(), _instant_pick(name="Isogen", type_id=35)])
        content = self._write_and_read([result])
        assert "MANDATORY" in content

    def test_speculative_section_present(self):
        result = _make_route_result(picks=[_speculative_pick()])
        content = self._write_and_read([result])
        assert "SPECULATIVE" in content

    def test_compact_mode_omits_pick_blocks(self):
        result = _make_route_result(picks=[_instant_pick()])
        content = self._write_and_read([result], compact_mode=True)
        # In compact mode: shopping list present, detailed pick blocks absent
        assert "SHOPPING LIST" in content
        assert "MANDATORY - instant exits" not in content

    def test_compact_mode_header_note(self):
        result = _make_route_result()
        content = self._write_and_read([result], compact_mode=True)
        assert "COMPACT" in content

    def test_detail_mode_shows_confidence_fields(self):
        result = _make_route_result()
        content = self._write_and_read([result], detail_mode=True)
        assert "route_confidence:" in content

    def test_speculative_warning_shown_when_spec_pick_present(self):
        result = _make_route_result(picks=[_speculative_pick()])
        content = self._write_and_read([result])
        assert "speculative" in content.lower()

    def test_totals_block_present(self):
        content = self._write_and_read([_make_route_result()])
        assert "BEST ACTIONABLE ROUTE" in content
        assert "AGGREGATE ACROSS DISPLAYED ROUTE ALTERNATIVES" in content
        assert "NOT a combined executable plan" in content

    def test_profile_shown_in_header(self):
        result = _make_route_result()
        result["_active_risk_profile"] = "conservative"
        content = self._write_and_read([result])
        assert "CONSERVATIVE" in content

    def test_profile_header_uses_resolved_profile_params(self):
        result = _make_route_result()
        result["_active_risk_profile"] = "balanced"
        result["_active_risk_profile_params"] = {
            "description": "Resolved runtime override",
            "min_expected_profit_isk": 2_500_000.0,
            "max_item_share_of_budget": 0.30,
        }
        content = self._write_and_read([result])
        assert "Resolved runtime override" in content

    def test_character_summary_shown_in_header(self):
        result = _make_route_result()
        result["_character_context_summary"] = {
            "available": True,
            "source": "cache",
            "character_name": "Trader One",
            "character_id": 90000001,
            "wallet_balance": 125_000_000.0,
            "open_orders_count": 4,
            "fee_skills": {"accounting": 5, "broker_relations": 4, "advanced_broker_relations": 3},
            "budget_exceeds_wallet": False,
            "warnings": [],
        }
        content = self._write_and_read([result])
        assert "Character: CACHE" in content
        assert "Trader One" in content
        assert "Open Orders 4" in content

    def test_internal_route_operational_floor_is_visible(self):
        result = _make_route_result(picks=[_instant_pick()])
        result["transport_mode"] = "internal_self_haul"
        result["operational_profit_floor_isk"] = 2_000_000.0
        result["suppressed_expected_realized_profit_total"] = 1_300_000.0
        result["operational_filter_note"] = "Internal nullsec routes require at least 2.0m ISK expected realized profit."
        content = self._write_and_read([result])
        assert "Internal Route Floor" in content
        assert "Suppressed Profit" in content

    def test_personal_history_warning_shown_in_header(self):
        result = _make_route_result()
        result["_personal_calibration_summary"] = {
            "quality_level": "low",
            "sample_size": {
                "eligible_entries": 4,
                "wallet_backed_entries": 4,
                "reliable_entries": 1,
            },
            "policy": {
                "fallback_to_generic": True,
                "reason": "unreliable personal history",
            },
            "warnings": ["unreliable personal history"],
            "diagnostics": {"overall": {}},
        }
        result["_personal_history_layer"] = {
            "mode": "advisory",
            "quality_level": "low",
            "active": False,
            "reason": "weak personal history quality",
        }
        content = self._write_and_read([result])
        assert "Personal Layer: ADVISORY | quality LOW | generic only" in content
        assert "Personal Basis: sample 4 | wallet-backed 4 | reliable 1" in content

    def test_personal_history_good_basis_shown_in_header(self):
        result = _make_route_result()
        result["_personal_calibration_summary"] = {
            "quality_level": "good",
            "sample_size": {
                "eligible_entries": 12,
                "wallet_backed_entries": 10,
                "reliable_entries": 9,
            },
            "policy": {
                "fallback_to_generic": False,
                "reason": "",
            },
            "warnings": [],
            "diagnostics": {
                "overall": {
                    "diagnosis": "well_aligned",
                    "actual_success_rate": 0.83,
                    "optimism_gap": -0.04,
                }
            },
        }
        result["_personal_history_layer"] = {
            "mode": "soft",
            "quality_level": "good",
            "active": True,
            "reason": "personal decision layer active",
            "max_positive_adjustment": 0.025,
            "max_negative_adjustment": 0.040,
        }
        result["_personal_history_effect_summary"] = {
            "applied": True,
            "effect_value": -0.03,
            "scope": "target_market+exit_type",
            "reason": "target_market=o4t (n=8, gap=-0.14)",
        }
        content = self._write_and_read([result])
        assert "Personal Layer: SOFT | quality GOOD | active" in content
        assert "Personal Basis: sample 12 | wallet-backed 10 | reliable 9" in content
        assert "Policy: scoped confidence adjustments enabled" in content
        assert "Applied: -0.030 confidence | target_market+exit_type" in content

    def test_character_order_overlap_shown_in_pick_block(self):
        pick = _planned_pick(
            character_open_orders=2,
            character_open_buy_orders=1,
            character_open_sell_orders=1,
            character_open_buy_isk_committed=5_000_000.0,
            character_open_sell_units=150,
        )
        result = _make_route_result(picks=[pick])
        content = self._write_and_read([result])
        assert "Character Exposure: 2 open orders" in content
        assert "Character Buy Capital Bound" in content
        assert "Character Listed Units: 150" in content

    def test_not_actionable_label_shown(self):
        result = _make_route_result(picks=[])
        content = self._write_and_read([result])
        assert "NOT ACTIONABLE" in content or "Keine Picks" in content

    def test_plan_id_shown(self):
        result = _make_route_result()
        content = self._write_and_read([result])
        assert "test-plan-001" in content

    def test_multiple_routes_produce_multiple_plan_headers(self):
        r1 = _make_route_result()
        r2 = _make_route_result()
        r2["route_label"] = "Amarr -> Ashab"
        content = self._write_and_read([r1, r2])
        assert "PLAN 1:" in content
        assert "PLAN 2:" in content


# ---------------------------------------------------------------------------
# Test --compact flag in parse_cli_args
# ---------------------------------------------------------------------------

class TestCompactFlag:
    def test_compact_flag_parsed(self):
        args = parse_cli_args(["--compact", "--cargo-m3", "10000", "--budget-isk", "500m"])
        assert args.get("compact") is True

    def test_compact_mode_alias_parsed(self):
        args = parse_cli_args(["--compact-mode", "--cargo-m3", "10000", "--budget-isk", "500m"])
        assert args.get("compact") is True

    def test_compact_false_by_default(self):
        args = parse_cli_args(["--cargo-m3", "10000", "--budget-isk", "500m"])
        assert args.get("compact") is False

    def test_compact_and_detail_can_coexist(self):
        args = parse_cli_args(["--compact", "--detail", "--cargo-m3", "10000", "--budget-isk", "500m"])
        assert args.get("compact") is True
        assert args.get("detail") is True
