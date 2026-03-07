"""Confidence calibration tests."""

from tests.shared import *  # noqa: F401,F403


def _entry(
    *,
    entry_id: str,
    raw_conf: float,
    status: str = "sold",
    proposed_qty: float = 10.0,
    actual_buy_qty: float = 10.0,
    actual_sell_qty: float = 10.0,
    expected_profit: float = 100.0,
    actual_profit: float = 100.0,
    expected_days: float = 10.0,
    actual_days: float = 8.0,
    route_id: str = "route_jita_o4t",
    source_market: str = "jita_44",
    target_market: str = "o4t",
    exit_type: str = "planned",
) -> dict:
    start = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=float(actual_days))
    return {
        "journal_entry_id": entry_id,
        "route_id": route_id,
        "route_label": route_id,
        "source_market": source_market,
        "target_market": target_market,
        "proposed_exit_type": exit_type,
        "status": status,
        "created_at": start.isoformat(timespec="seconds"),
        "first_buy_at": start.isoformat(timespec="seconds"),
        "last_sell_at": end.isoformat(timespec="seconds") if status == "sold" else "",
        "proposed_qty": proposed_qty,
        "proposed_expected_profit": expected_profit,
        "proposed_expected_days_to_sell": expected_days,
        "actual_buy_qty": actual_buy_qty,
        "actual_sell_qty": actual_sell_qty,
        "actual_profit_net": actual_profit,
        "proposed_confidence": raw_conf,
        "proposed_overall_confidence_raw": raw_conf,
        "proposed_exit_confidence_raw": raw_conf,
        "proposed_liquidity_confidence_raw": raw_conf,
        "proposed_transport_confidence_raw": 1.0,
        "proposed_overall_confidence_calibrated": raw_conf,
        "proposed_exit_confidence_calibrated": raw_conf,
        "proposed_liquidity_confidence_calibrated": raw_conf,
        "proposed_transport_confidence_calibrated": 1.0,
    }


def test_classify_trade_outcome_marks_stale_partial_position_as_stuck() -> None:
    entry = _entry(
        entry_id="entry_partial",
        raw_conf=0.75,
        status="partially_sold",
        actual_buy_qty=10.0,
        actual_sell_qty=4.0,
        actual_profit=20.0,
        expected_days=7.0,
        actual_days=12.0,
    )
    now = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    outcome = nst.classify_trade_outcome(
        entry,
        {
            "enabled": True,
            "min_samples": 2,
            "stale_open_position_days": 5.0,
            "open_position_horizon_factor": 1.0,
        },
        now=now,
    )
    assert bool(outcome["eligible"]) is True
    assert bool(outcome["fully_sold"]) is False
    assert bool(outcome["position_stuck"]) is True
    assert float(outcome["qty_realization_ratio"]) < 0.5


def test_build_confidence_calibration_buckets_and_report() -> None:
    entries = [
        _entry(entry_id="low_bad", raw_conf=0.15, actual_profit=-10.0, expected_profit=100.0, actual_days=18.0),
        _entry(entry_id="mid_ok", raw_conf=0.45, actual_profit=85.0, expected_profit=100.0, actual_days=9.0),
        _entry(entry_id="high_bad", raw_conf=0.85, actual_profit=20.0, expected_profit=100.0, actual_days=20.0),
        _entry(entry_id="high_good", raw_conf=0.90, actual_profit=105.0, expected_profit=100.0, actual_days=7.0),
    ]
    calibration = nst.build_confidence_calibration(
        entries,
        {
            "enabled": True,
            "min_samples": 2,
            "min_samples_per_bucket": 1,
            "buckets": [0.2, 0.4, 0.6, 0.8, 1.0],
        },
    )
    overall = calibration["dimensions"]["overall"]["global"]
    bucket_rows = {row["label"]: row for row in overall["buckets"]}
    assert int(calibration["eligible_entries"]) == 4
    assert int(bucket_rows["0.8-1.0"]["sample_count"]) == 2
    assert float(bucket_rows["0.8-1.0"]["avg_raw_confidence"]) > 0.8
    report = nst.format_confidence_calibration_report(calibration, limit=3)
    assert "CONFIDENCE CALIBRATION REPORT" in report
    assert "Overall confidence buckets:" in report
    assert "0.8-1.0" in report


def test_apply_calibration_to_record_sets_raw_and_calibrated_confidence() -> None:
    calibration = nst.build_confidence_calibration(
        [
            _entry(entry_id="h1", raw_conf=0.85, actual_profit=20.0, expected_profit=100.0, actual_days=20.0),
            _entry(entry_id="h2", raw_conf=0.88, actual_profit=30.0, expected_profit=100.0, actual_days=18.0),
            _entry(entry_id="l1", raw_conf=0.25, actual_profit=60.0, expected_profit=100.0, actual_days=8.0),
            _entry(entry_id="l2", raw_conf=0.28, actual_profit=70.0, expected_profit=100.0, actual_days=9.0),
        ],
        {
            "enabled": True,
            "apply_to_decisions": True,
            "min_samples": 2,
            "min_samples_per_bucket": 1,
            "buckets": [0.3, 0.6, 1.0],
        },
    )
    candidate = {
        "route_id": "route_jita_o4t",
        "source_market": "jita_44",
        "target_market": "o4t",
        "exit_type": "planned",
        "exit_confidence": 0.86,
        "liquidity_confidence": 0.82,
        "overall_confidence": 0.82,
    }
    nst.apply_calibration_to_record(candidate, calibration, route_id="route_jita_o4t", source_market="jita_44", target_market="o4t", exit_type="planned", transport_confidence=1.0)
    assert abs(float(candidate["raw_confidence"]) - 0.82) < 1e-9
    assert float(candidate["calibrated_confidence"]) <= float(candidate["raw_confidence"])
    assert abs(float(candidate["decision_overall_confidence"]) - float(candidate["calibrated_confidence"])) < 1e-9


def test_calibration_with_too_few_data_returns_raw_confidence() -> None:
    calibration = nst.build_confidence_calibration(
        [_entry(entry_id="only_one", raw_conf=0.9)],
        {"enabled": True, "min_samples": 5, "min_samples_per_bucket": 2},
    )
    info = nst.calibrate_confidence_value(0.9, calibration, dimension="overall", target_market="o4t")
    assert "insufficient journal data" in str(info["warning"])
    assert abs(float(info["raw_confidence"]) - float(info["calibrated_confidence"])) < 1e-9


def test_route_summary_prefers_decision_confidence_when_present() -> None:
    route = {
        "route_label": "jita_44 -> o4t",
        "source_label": "jita_44",
        "dest_label": "o4t",
        "cost_model_confidence": "normal",
        "raw_transport_confidence": 1.0,
        "calibrated_transport_confidence": 0.90,
        "transport_confidence_for_decision": 0.90,
        "picks": [
            {
                "expected_realized_profit_90d": 10_000_000.0,
                "expected_days_to_sell": 12.0,
                "raw_confidence": 0.85,
                "calibrated_confidence": 0.55,
                "decision_overall_confidence": 0.55,
            }
        ],
    }
    summary = nst.summarize_route_for_ranking(route)
    assert abs(float(summary["raw_route_confidence"]) - 0.85) < 1e-9
    assert abs(float(summary["route_confidence"]) - 0.55) < 1e-9
    assert abs(float(summary["calibrated_transport_confidence"]) - 0.90) < 1e-9
