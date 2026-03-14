"""Tests for the Do Not Trade decision engine (no_trade.py).

Covers:
- Empty route list → always DNT
- No actionable routes → DNT with NO_ACTIONABLE_ROUTES
- Candidates existed but profile rejected them → PROFILE_REJECTED_AVAILABLE_TRADES
- All speculative picks → NO_STRONG_EXITS (critical)
- Excessive speculation → EXCESSIVE_SPECULATION (high)
- Low route confidence → LOW_ROUTE_CONFIDENCE (high)
- Low transport confidence → SHIPPING_UNCERTAIN (high)
- High capital lock → CAPITAL_LOCK_TOO_HIGH (medium)
- Profit below minimum → PROFIT_NOT_ACTIONABLE (medium)
- Calibration warning → DATA_QUALITY_TOO_WEAK (medium)
- Too few strong picks for conservative → TOO_FEW_HIGH_QUALITY_PICKS (high)
- Clean route with good picks → should_trade=True
- Two high-severity issues → DNT even if no critical
- Profile comparison accuracy
- near_misses from non-actionable routes
- write_no_trade_report produces readable output
"""
from __future__ import annotations

import os
import tempfile

import pytest

from no_trade import evaluate_no_trade, REASON_CODES
from execution_plan import write_no_trade_report
from risk_profiles import BUILTIN_PROFILES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _balanced() -> tuple[str, dict]:
    return "balanced", dict(BUILTIN_PROFILES["balanced"])


def _conservative() -> tuple[str, dict]:
    return "conservative", dict(BUILTIN_PROFILES["conservative"])


def _aggressive() -> tuple[str, dict]:
    return "aggressive", dict(BUILTIN_PROFILES["aggressive"])


def _route(
    *,
    actionable: bool = True,
    picks: list[dict] | None = None,
    route_confidence: float = 0.80,
    transport_confidence: float = 0.85,
    capital_lock_risk: float = 0.10,
    total_expected_realized_profit: float = 50_000_000.0,
    total_candidates: int = 20,
    calibration_warning: str = "",
    prune_reason: str = "",
    blocked_transport: bool = False,
) -> dict:
    """Build a minimal route result dict that summarize_route_for_ranking can consume."""
    p_list = picks if picks is not None else [_mandatory_pick(), _optional_pick()]
    return {
        "route_label": "Jita -> Perimeter",
        "source_label": "Jita IV-4",
        "dest_label": "Perimeter TTT",
        "picks": p_list,
        "route_actionable": actionable,
        "route_prune_reason": prune_reason,
        "route_blocked_due_to_transport": blocked_transport,
        "total_candidates": total_candidates,
        "calibration_warning": calibration_warning,
        # Fields consumed by summarize_route_for_ranking via route_search
        "profit_total": total_expected_realized_profit,
        "isk_used": 200_000_000.0,
        "m3_used": 5_000.0,
        # Pre-computed summary fields so summarize_route_for_ranking can use them
        "_test_route_confidence": route_confidence,
        "_test_transport_confidence": transport_confidence,
        "_test_capital_lock_risk": capital_lock_risk,
        "_test_total_expected_realized_profit": total_expected_realized_profit,
    }


def _mandatory_pick(**kwargs) -> dict:
    base = {
        "name": "Tritanium",
        "type_id": 34,
        "qty": 1000,
        "buy_avg": 4.5,
        "profit": 500_000.0,
        "expected_realized_profit_90d": 480_000.0,
        "instant": True,
        "mode": "instant",
        "exit_type": "instant",
        "fill_probability": 0.92,
        "liquidity_confidence": 0.92,
        "overall_confidence": 0.88,
        "expected_days_to_sell": 0.3,
        "market_plausibility_score": 0.95,
        "manipulation_risk_score": 0.02,
    }
    base.update(kwargs)
    return base


def _optional_pick(**kwargs) -> dict:
    base = {
        "name": "Zydrine",
        "type_id": 39,
        "qty": 50,
        "buy_avg": 1200.0,
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
        "manipulation_risk_score": 0.05,
    }
    base.update(kwargs)
    return base


def _speculative_pick(**kwargs) -> dict:
    base = {
        "name": "Dark Glitter",
        "type_id": 46678,
        "qty": 5,
        "buy_avg": 5_000_000.0,
        "profit": 10_000_000.0,
        "expected_realized_profit_90d": 1_000_000.0,
        "instant": False,
        "mode": "planned_sell",
        "exit_type": "speculative",
        "fill_probability": 0.15,
        "liquidity_confidence": 0.15,
        "overall_confidence": 0.20,   # < 0.40 → speculative
        "expected_days_to_sell": 80.0,
        "market_plausibility_score": 0.40,
        "manipulation_risk_score": 0.65,
    }
    base.update(kwargs)
    return base


# Monkeypatch summarize_route_for_ranking to use the test fields
import route_search as _rs_module  # noqa: E402

_original_summarize = _rs_module.summarize_route_for_ranking


def _mock_summarize(route: dict) -> dict:
    """Return a summary dict using _test_* sentinel fields if present."""
    if "_test_route_confidence" in route:
        return {
            "actionable": bool(route.get("route_actionable", False)) and bool(route.get("picks")),
            "route_confidence": route["_test_route_confidence"],
            "transport_confidence": route["_test_transport_confidence"],
            "capital_lock_risk": route["_test_capital_lock_risk"],
            "total_expected_realized_profit": route["_test_total_expected_realized_profit"],
            "total_full_sell_profit": route["_test_total_expected_realized_profit"] * 1.2,
            "stale_market_penalty": 0.0,
            "speculative_penalty": 0.0,
            "concentration_penalty": 0.0,
            "risk_adjusted_score": route["_test_total_expected_realized_profit"] * route["_test_route_confidence"],
        }
    return _original_summarize(route)


@pytest.fixture(autouse=True)
def patch_summarize(monkeypatch):
    monkeypatch.setattr(_rs_module, "summarize_route_for_ranking", _mock_summarize)


# ---------------------------------------------------------------------------
# Tests: no routes
# ---------------------------------------------------------------------------

class TestNoRoutes:
    def test_empty_route_list_is_dnt(self):
        name, params = _balanced()
        result = evaluate_no_trade([], name, params)
        assert result["should_trade"] is False

    def test_empty_route_list_has_no_actionable_routes_code(self):
        name, params = _balanced()
        result = evaluate_no_trade([], name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "NO_ACTIONABLE_ROUTES" in codes

    def test_empty_route_list_counts_are_zero(self):
        name, params = _balanced()
        result = evaluate_no_trade([], name, params)
        assert result["actionable_route_count"] == 0
        assert result["total_route_count"] == 0
        assert result["best_route_summary"] is None


# ---------------------------------------------------------------------------
# Tests: no actionable routes
# ---------------------------------------------------------------------------

class TestNoActionableRoutes:
    def test_non_actionable_routes_trigger_dnt(self):
        name, params = _balanced()
        routes = [_route(actionable=False, picks=[])]
        result = evaluate_no_trade(routes, name, params)
        assert result["should_trade"] is False

    def test_no_actionable_routes_code_present(self):
        name, params = _balanced()
        routes = [_route(actionable=False, picks=[])]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "NO_ACTIONABLE_ROUTES" in codes

    def test_candidates_did_not_survive_code_when_candidates_existed(self):
        name, params = _conservative()
        routes = [_route(actionable=False, picks=[], total_candidates=15)]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "CANDIDATES_DID_NOT_SURVIVE_FILTERS" in codes

    def test_near_misses_built_from_non_actionable(self):
        name, params = _balanced()
        routes = [_route(actionable=False, picks=[], prune_reason="no_picks")]
        result = evaluate_no_trade(routes, name, params)
        assert len(result["near_misses"]) == 1
        assert result["near_misses"][0]["prune_reason"] == "no_picks"

    def test_near_miss_blocked_transport_flag(self):
        name, params = _balanced()
        routes = [_route(actionable=False, picks=[], blocked_transport=True)]
        result = evaluate_no_trade(routes, name, params)
        assert result["near_misses"][0]["transport_blocked"] is True


# ---------------------------------------------------------------------------
# Tests: actionable routes — quality checks
# ---------------------------------------------------------------------------

class TestQualityChecks:
    def test_all_speculative_picks_triggers_no_strong_exits(self):
        name, params = _balanced()
        routes = [_route(picks=[_speculative_pick(), _speculative_pick()])]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "NO_STRONG_EXITS" in codes

    def test_no_strong_exits_is_critical(self):
        name, params = _balanced()
        routes = [_route(picks=[_speculative_pick()])]
        result = evaluate_no_trade(routes, name, params)
        sev = {r["code"]: r["severity"] for r in result["reason_codes"]}
        assert sev.get("NO_STRONG_EXITS") == "critical"

    def test_all_speculative_triggers_dnt(self):
        name, params = _balanced()
        routes = [_route(picks=[_speculative_pick()])]
        result = evaluate_no_trade(routes, name, params)
        assert result["should_trade"] is False

    def test_excessive_speculation_high_severity(self):
        # 3 speculative, 1 mandatory — 75% spec share > balanced max (0.70)
        name, params = _balanced()
        routes = [_route(picks=[_mandatory_pick()] + [_speculative_pick(name=f"S{i}") for i in range(3)])]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "EXCESSIVE_SPECULATION" in codes

    def test_low_route_confidence_high_severity(self):
        name, params = _balanced()
        routes = [_route(route_confidence=0.20)]  # below balanced min 0.50
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "LOW_ROUTE_CONFIDENCE" in codes

    def test_low_transport_confidence_shipping_uncertain(self):
        name, params = _balanced()
        # balanced min_transport = 0.50 * 0.70 = 0.35; give 0.20
        routes = [_route(transport_confidence=0.20)]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "SHIPPING_UNCERTAIN" in codes

    def test_high_capital_lock_medium_severity(self):
        name, params = _balanced()
        routes = [_route(capital_lock_risk=0.80)]  # above balanced ceiling 0.65
        result = evaluate_no_trade(routes, name, params)
        sev = {r["code"]: r["severity"] for r in result["reason_codes"]}
        assert sev.get("CAPITAL_LOCK_TOO_HIGH") == "medium"

    def test_profit_below_minimum_code_present(self):
        name, params = _conservative()  # min_profit=5M ISK
        routes = [_route(total_expected_realized_profit=100_000.0)]  # 0.1M < 5M
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "PROFIT_NOT_ACTIONABLE" in codes

    def test_calibration_warning_surfaces_data_quality_code(self):
        name, params = _balanced()
        routes = [_route(calibration_warning="thin historical data for this type")]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "DATA_QUALITY_TOO_WEAK" in codes

    def test_too_few_strong_picks_conservative(self):
        # Conservative needs ≥2 mandatory/optional — give only 1 mandatory
        name, params = _conservative()
        routes = [_route(picks=[_mandatory_pick(), _speculative_pick()])]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "TOO_FEW_HIGH_QUALITY_PICKS" in codes

    def test_too_few_strong_picks_not_triggered_for_balanced_with_one(self):
        # Balanced needs ≥1 mandatory/optional — 1 mandatory is enough
        name, params = _balanced()
        routes = [_route(picks=[_mandatory_pick(), _speculative_pick()])]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        # EXCESSIVE_SPECULATION may fire but NOT TOO_FEW_HIGH_QUALITY_PICKS
        assert "TOO_FEW_HIGH_QUALITY_PICKS" not in codes


# ---------------------------------------------------------------------------
# Tests: clean routes — should_trade=True
# ---------------------------------------------------------------------------

class TestCleanRoute:
    def test_clean_balanced_route_should_trade(self):
        name, params = _balanced()
        routes = [_route()]  # default: good confidence, 2 strong picks
        result = evaluate_no_trade(routes, name, params)
        assert result["should_trade"] is True

    def test_clean_route_no_reason_codes(self):
        name, params = _balanced()
        routes = [_route()]
        result = evaluate_no_trade(routes, name, params)
        assert result["reason_codes"] == []

    def test_clean_route_has_best_route_summary(self):
        name, params = _balanced()
        routes = [_route()]
        result = evaluate_no_trade(routes, name, params)
        assert result["best_route_summary"] is not None
        assert result["best_route_summary"]["mandatory_picks"] >= 1

    def test_clean_route_actionable_count(self):
        name, params = _balanced()
        routes = [_route(), _route(actionable=False, picks=[])]
        result = evaluate_no_trade(routes, name, params)
        assert result["actionable_route_count"] == 1
        assert result["total_route_count"] == 2


# ---------------------------------------------------------------------------
# Tests: DNT decision threshold
# ---------------------------------------------------------------------------

class TestDntThreshold:
    def test_two_high_severity_triggers_dnt(self):
        """LOW_ROUTE_CONFIDENCE + SHIPPING_UNCERTAIN = 2 high → DNT."""
        name, params = _balanced()
        routes = [_route(route_confidence=0.20, transport_confidence=0.10)]
        result = evaluate_no_trade(routes, name, params)
        assert result["should_trade"] is False

    def test_one_medium_severity_does_not_trigger_dnt(self):
        name, params = _balanced()
        routes = [_route(capital_lock_risk=0.80)]  # only capital lock (medium)
        result = evaluate_no_trade(routes, name, params)
        # Capital lock alone (medium) should not trigger DNT
        assert result["should_trade"] is True

    def test_critical_alone_triggers_dnt(self):
        name, params = _balanced()
        routes = [_route(picks=[_speculative_pick()])]  # NO_STRONG_EXITS = critical
        assert evaluate_no_trade(routes, name, params)["should_trade"] is False

    def test_aggressive_tolerates_speculative_share(self):
        """Aggressive profile: spec_penalty_weight=0.30 → max_spec_share=0.90.
        3 speculative + 2 mandatory = 60% spec → should not trigger EXCESSIVE_SPECULATION."""
        name, params = _aggressive()
        picks = [_mandatory_pick(name="M1"), _mandatory_pick(name="M2")] + [
            _speculative_pick(name=f"S{i}") for i in range(3)
        ]
        routes = [_route(picks=picks)]
        result = evaluate_no_trade(routes, name, params)
        codes = [r["code"] for r in result["reason_codes"]]
        assert "EXCESSIVE_SPECULATION" not in codes


# ---------------------------------------------------------------------------
# Tests: profile comparison
# ---------------------------------------------------------------------------

class TestProfileComparison:
    def test_comparison_returned_for_other_profiles(self):
        name, params = _conservative()
        routes = [_route(route_confidence=0.40, picks=[_mandatory_pick()])]
        result = evaluate_no_trade(routes, name, params, all_profiles=BUILTIN_PROFILES)
        # conservative is excluded from comparison; others should be there
        assert "balanced" in result["profile_comparison"]
        assert "aggressive" in result["profile_comparison"]
        assert "conservative" not in result["profile_comparison"]

    def test_aggressive_would_trade_when_conservative_rejects(self):
        # conservative min_conf=0.70; route_conf=0.40 → conservative DNTs
        # aggressive min_conf=0.20 → would trade
        name, params = _conservative()
        routes = [_route(route_confidence=0.40)]
        result = evaluate_no_trade(routes, name, params, all_profiles=BUILTIN_PROFILES)
        assert result["profile_comparison"].get("aggressive") is True

    def test_no_comparison_without_all_profiles(self):
        name, params = _balanced()
        routes = [_route()]
        result = evaluate_no_trade(routes, name, params)  # no all_profiles
        assert result["profile_comparison"] == {}


# ---------------------------------------------------------------------------
# Tests: write_no_trade_report
# ---------------------------------------------------------------------------

class TestWriteNoTradeReport:
    def _dnt_result(self) -> dict:
        name, params = _conservative()
        routes = [_route(actionable=False, picks=[], total_candidates=10)]
        return evaluate_no_trade(routes, name, params, all_profiles=BUILTIN_PROFILES)

    def _write_and_read(self, result: dict, profile_name: str, profile_params: dict) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            path = f.name
        try:
            write_no_trade_report(path, "2026-03-07T00:00:00", result, profile_name, profile_params)
            with open(path, encoding="utf-8") as f:
                return f.read()
        finally:
            os.unlink(path)

    def test_report_contains_do_not_trade_header(self):
        result = self._dnt_result()
        content = self._write_and_read(result, "conservative", BUILTIN_PROFILES["conservative"])
        assert "DO NOT TRADE" in content

    def test_report_contains_reason_codes(self):
        result = self._dnt_result()
        content = self._write_and_read(result, "conservative", BUILTIN_PROFILES["conservative"])
        assert "NO_ACTIONABLE_ROUTES" in content

    def test_report_contains_profile_comparison(self):
        result = self._dnt_result()
        content = self._write_and_read(result, "conservative", BUILTIN_PROFILES["conservative"])
        assert "PROFIL-VERGLEICH" in content or "profile_comparison" in content.lower() or "balanced" in content

    def test_report_contains_near_miss_section_when_present(self):
        result = self._dnt_result()
        if result["near_misses"]:
            content = self._write_and_read(result, "conservative", BUILTIN_PROFILES["conservative"])
            assert "BEINAHE" in content or "FAST GUT" in content or "near" in content.lower()

    def test_report_surfaces_internal_route_floor_for_near_miss(self):
        name, params = _balanced()
        route = _route(
            actionable=False,
            picks=[],
            total_candidates=6,
            prune_reason="internal_route_profit_below_operational_floor",
        )
        route["operational_profit_floor_isk"] = 2_000_000.0
        route["suppressed_expected_realized_profit_total"] = 1_300_000.0
        route["operational_filter_note"] = "Internal nullsec routes require at least 2.0m ISK expected realized profit."
        result = evaluate_no_trade([route], name, params, all_profiles=BUILTIN_PROFILES)
        content = self._write_and_read(result, name, params)
        assert "internal_route_profit_below_operational_floor" in content
        assert "Internal Route Floor" in content
        assert "Suppressed Expected Profit" in content

    def test_report_contains_profile_name(self):
        result = self._dnt_result()
        content = self._write_and_read(result, "conservative", BUILTIN_PROFILES["conservative"])
        assert "CONSERVATIVE" in content

    def test_report_ends_with_recommendation(self):
        result = self._dnt_result()
        content = self._write_and_read(result, "conservative", BUILTIN_PROFILES["conservative"])
        assert "Empfehlung" in content or "nicht handeln" in content
