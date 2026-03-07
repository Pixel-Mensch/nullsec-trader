"""Explainability tests."""

from tests.shared import *  # noqa: F401,F403


def test_reason_code_mapping_uses_stable_codes() -> None:
    assert str(nst.reason_code_for_internal_reason("planned_queue_ahead_too_heavy")) == "THIN_SELL_WALL"
    assert str(nst.reason_code_for_internal_reason("missing_transport_cost_model")) == "NO_SHIPPING_MODEL"
    assert str(nst.reason_code_for_internal_reason("planned_low_confidence")) == "WEAK_EXIT_CONFIDENCE"


def test_candidate_explainability_collects_reasons_and_breakdown() -> None:
    candidate = nst.TradeCandidate(
        type_id=55,
        name="Thin Planned",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=180.0,
        max_units=80,
        profit_per_unit=80.0,
        profit_pct=0.80,
        instant=False,
        mode="planned_sell",
        exit_type="planned",
        gross_profit_if_full_sell=6_400_000.0,
        expected_units_sold_90d=30.0,
        expected_units_unsold_90d=50.0,
        expected_realized_profit_90d=4_000_000.0,
        expected_realized_profit_per_m3_90d=30_000.0,
        expected_days_to_sell=42.0,
        liquidity_confidence=0.35,
        exit_confidence=0.40,
        overall_confidence=0.40,
        raw_confidence=0.82,
        calibrated_confidence=0.56,
        decision_overall_confidence=0.56,
        raw_transport_confidence=1.0,
        target_price_confidence=0.35,
        queue_ahead_units=120,
        used_volume_fallback=True,
        buy_discount_vs_ref=0.08,
    )
    nst.ensure_record_explainability(candidate, max_liq_days=30.0)

    positive_codes = {entry["code"] for entry in list(candidate.positive_reasons)}
    negative_codes = {entry["code"] for entry in list(candidate.negative_reasons)}
    warning_codes = {entry["code"] for entry in list(candidate.warnings)}
    score_keys = {entry["key"] for entry in list(candidate.score_contributors)}

    assert "STRONG_EXPECTED_PROFIT" in positive_codes
    assert "SOLID_JITA_BUY" in positive_codes
    assert "LOW_LIQUIDITY" in negative_codes
    assert "THIN_SELL_WALL" in negative_codes
    assert "WEAK_EXIT_CONFIDENCE" in negative_codes
    assert "CAPITAL_LOCK_RISK" in negative_codes
    assert "HISTORY_ONLY_SIGNAL" in warning_codes
    assert "CONFIDENCE_DOWNGRADED" in warning_codes
    assert {
        "base_profit_score",
        "liquidity_adjustment",
        "transport_adjustment",
        "concentration_penalty",
        "stale_market_penalty",
        "confidence_penalty",
        "speculative_penalty",
    }.issubset(score_keys)


def test_route_summary_exposes_pruned_reason_code_for_blocked_route() -> None:
    route = {
        "route_label": "A -> B",
        "source_label": "A",
        "dest_label": "B",
        "route_blocked_due_to_transport": True,
        "route_prune_reason": "missing_transport_cost_model",
        "cost_model_confidence": "blocked",
        "picks": [],
    }
    summary = nst.summarize_route_for_ranking(route)
    assert str(summary["pruned_reason"]["code"]) == "NO_SHIPPING_MODEL"
    assert str(summary["gating_failures"][0]["code"]) == "NO_SHIPPING_MODEL"


def test_route_summary_contains_reason_codes_and_score_breakdown() -> None:
    route = {
        "route_label": "jita_44 -> o4t",
        "source_label": "jita_44",
        "dest_label": "o4t",
        "cost_model_confidence": "normal",
        "raw_transport_confidence": 0.80,
        "calibrated_transport_confidence": 0.75,
        "transport_confidence_for_decision": 0.75,
        "m3_used": 20.0,
        "picks": [
            {
                "expected_realized_profit_90d": 20_000_000.0,
                    "expected_days_to_sell": 40.0,
                "raw_confidence": 0.78,
                "calibrated_confidence": 0.60,
                "decision_overall_confidence": 0.60,
                "exit_type": "planned",
                "used_volume_fallback": True,
            },
            {
                "expected_realized_profit_90d": 2_000_000.0,
                    "expected_days_to_sell": 20.0,
                "raw_confidence": 0.55,
                "calibrated_confidence": 0.50,
                "decision_overall_confidence": 0.50,
                "exit_type": "speculative",
            },
        ],
    }
    summary = nst.summarize_route_for_ranking(route)
    negative_codes = {entry["code"] for entry in list(summary["negative_reasons"])}
    warning_codes = {entry["code"] for entry in list(summary["warnings"])}
    score_keys = {entry["key"] for entry in list(summary["score_contributors"])}

    assert "SLOW_ROUTE_LIQUIDATION" in negative_codes
    assert "TOO_MANY_SPECULATIVE_PICKS" in negative_codes
    assert "STALE_MARKET_SIGNAL" in warning_codes
    assert {
        "base_profit_score",
        "liquidity_adjustment",
        "transport_adjustment",
        "concentration_penalty",
        "stale_market_penalty",
        "confidence_penalty",
        "speculative_penalty",
    }.issubset(score_keys)


def test_execution_plan_detail_mode_shows_explanations_and_rejections() -> None:
    route_results = [{
        "route_label": "A -> B",
        "route_id": "a_to_b",
        "source_label": "A",
        "dest_label": "B",
        "source_node_info": {"node_label": "A", "node_kind": "structure", "structure_id": 1, "node_id": 1},
        "dest_node_info": {"node_label": "B", "node_kind": "structure", "structure_id": 2, "node_id": 2},
        "isk_used": 10_000_000.0,
        "budget_total": 20_000_000.0,
        "profit_total": 4_000_000.0,
        "expected_realized_profit_total": 4_000_000.0,
        "full_sell_profit_total": 5_000_000.0,
        "m3_used": 10.0,
        "total_route_cost": 500_000.0,
        "total_transport_cost": 500_000.0,
        "route_actionable": True,
        "cost_model_confidence": "normal",
        "raw_transport_confidence": 1.0,
        "calibrated_transport_confidence": 0.9,
        "transport_confidence_for_decision": 0.9,
        "top_rejected_candidates": [
            {
                "type_id": 99,
                "name": "Thin Reject",
                "reason_code": "THIN_SELL_WALL",
                "reason_text": "Queue/Wall vor dem Exit ist zu schwer.",
                "nominal_profit_proxy": 9_000_000.0,
            }
        ],
        "picks": [{
            "type_id": 34,
            "name": "Tritanium",
            "qty": 10,
            "buy_avg": 100.0,
            "target_sell_price": 160.0,
            "sell_avg": 160.0,
            "instant": False,
            "mode": "planned_sell",
            "exit_type": "planned",
            "fill_probability": 0.8,
            "expected_days_to_sell": 12.0,
            "gross_profit_if_full_sell": 600.0,
            "expected_realized_profit_90d": 500.0,
            "expected_units_sold_90d": 8.0,
            "expected_units_unsold_90d": 2.0,
            "liquidity_confidence": 0.7,
            "overall_confidence": 0.7,
            "raw_confidence": 0.78,
            "calibrated_confidence": 0.65,
            "decision_overall_confidence": 0.65,
            "raw_transport_confidence": 0.9,
            "calibrated_transport_confidence": 0.9,
            "profit": 500.0,
            "revenue_net": 1500.0,
            "unit_volume": 1.0,
            "buy_at": "A",
            "sell_at": "B",
            "cost": 1000.0,
        }],
        "explain": {
            "rejected": [{"type_id": 99, "name": "Thin Reject", "reason": "planned_queue_ahead_too_heavy", "metrics": {"queue_ahead_units": 100}}],
            "reason_counts": {"planned_queue_ahead_too_heavy": 1},
        },
    }]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_detail.txt")
        nst.write_execution_plan_profiles(out_path, "2026-03-07_12-00-00", route_results, detail_mode=True)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "route_score_breakdown:" in content
    assert "score_breakdown:" in content
    assert "Top Rejected Candidates:" in content
    assert "THIN_SELL_WALL" in content
