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


def _reconciled_entry(
    *,
    entry_id: str,
    raw_conf: float,
    expected_profit: float = 100.0,
    realized_profit: float = 95.0,
    expected_days: float = 10.0,
    actual_days: float = 8.0,
    matched_buy_qty: float = 10.0,
    matched_sell_qty: float = 10.0,
    reconciliation_status: str = "fully_sold",
    fee_match_quality: str = "exact",
    wallet_data_freshness: str = "fresh",
    wallet_history_truncated: bool = False,
) -> dict:
    entry = _entry(
        entry_id=entry_id,
        raw_conf=raw_conf,
        status="planned",
        actual_buy_qty=0.0,
        actual_sell_qty=0.0,
        expected_profit=expected_profit,
        actual_profit=0.0,
        expected_days=expected_days,
        actual_days=actual_days,
    )
    entry["first_buy_at"] = ""
    entry["last_sell_at"] = ""
    entry["reconciliation_status"] = reconciliation_status
    entry["matched_buy_qty"] = matched_buy_qty
    entry["matched_sell_qty"] = matched_sell_qty
    entry["realized_profit_net"] = realized_profit
    entry["first_matched_buy_at"] = "2026-03-01T10:00:00+00:00"
    entry["last_matched_sell_at"] = "2026-03-09T10:00:00+00:00" if matched_sell_qty > 0.0 else ""
    entry["fee_match_quality"] = fee_match_quality
    entry["wallet_data_freshness"] = wallet_data_freshness
    entry["wallet_history_truncated"] = bool(wallet_history_truncated)
    entry["wallet_history_quality"] = "truncated" if wallet_history_truncated else "good"
    return entry


def _policy_cfg(mode: str = "soft", **overrides) -> dict:
    cfg = {
        "confidence_calibration": {
            "enabled": True,
            "min_samples": 4,
            "min_samples_per_bucket": 2,
            "buckets": [0.2, 0.4, 0.6, 0.8, 1.0],
        },
        "personal_history_policy": {
            "enabled": True,
            "mode": mode,
            "min_quality": "usable",
            "max_negative_adjustment": 0.08,
            "max_positive_adjustment": 0.05,
            "require_wallet_backed_min": 4,
            "require_reliable_min": 4,
        },
    }
    cfg["personal_history_policy"].update(overrides)
    return cfg


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


def test_personal_calibration_summary_falls_back_without_history() -> None:
    summary = nst.build_personal_calibration_summary([], {"enabled": True, "min_samples": 4})
    assert summary["quality_level"] == "none"
    assert bool(summary["usable_for_calibration"]) is False
    assert bool(summary["policy"]["fallback_to_generic"]) is True
    assert "insufficient personal history" in summary["warnings"]
    report = nst.format_personal_calibration_summary(summary)
    assert "PERSONAL CALIBRATION BASIS" in report
    assert "fallback_generic" in report
    status_lines = nst.personal_calibration_status_lines(summary)
    assert any("Personal History: NONE" in line for line in status_lines)
    assert any("fallback to generic" in line for line in status_lines)
    assert any("Warning: insufficient personal history" in line for line in status_lines)


def test_personal_calibration_uses_reconciled_outcomes_without_touching_generic_model() -> None:
    entry = _reconciled_entry(entry_id="wallet_only", raw_conf=0.82, realized_profit=110.0)
    cfg = {"enabled": True, "min_samples": 4, "min_samples_per_bucket": 1}
    generic = nst.build_confidence_calibration([entry], cfg)
    personal = nst.build_personal_calibration_summary([entry], cfg)
    info = nst.calibrate_confidence_value(0.82, generic, dimension="overall", target_market="o4t")
    assert int(generic["eligible_entries"]) == 0
    assert int(personal["sample_size"]["eligible_entries"]) == 1
    assert personal["quality_level"] == "very_low"
    assert bool(personal["policy"]["fallback_to_generic"]) is True
    assert abs(float(info["raw_confidence"]) - float(info["calibrated_confidence"])) < 1e-9


def test_personal_calibration_marks_unreliable_history_when_matches_are_weak() -> None:
    entries = [
        _reconciled_entry(
            entry_id=f"weak_{idx}",
            raw_conf=0.70,
            realized_profit=20.0 + idx,
            reconciliation_status="sold_match_uncertain",
            fee_match_quality="uncertain",
            wallet_data_freshness="stale",
            wallet_history_truncated=True,
        )
        for idx in range(4)
    ]
    summary = nst.build_personal_calibration_summary(
        entries,
        {"enabled": True, "min_samples": 4, "min_samples_per_bucket": 1},
    )
    assert summary["quality_level"] == "low"
    assert bool(summary["policy"]["fallback_to_generic"]) is True
    assert "unreliable personal history" in summary["warnings"]
    assert "wallet history is truncated" in summary["warnings"]


def test_personal_calibration_summary_reports_good_quality_for_consistent_wallet_backed_history() -> None:
    entries = [
        _reconciled_entry(
            entry_id=f"good_{idx}",
            raw_conf=0.55 + (idx % 4) * 0.08,
            realized_profit=90.0 + idx,
            expected_profit=100.0,
            expected_days=10.0,
            actual_days=7.0 + (idx % 3),
        )
        for idx in range(12)
    ]
    summary = nst.build_personal_calibration_summary(
        entries,
        {"enabled": True, "min_samples": 4, "min_samples_per_bucket": 2},
    )
    assert summary["quality_level"] == "good"
    assert bool(summary["usable_for_calibration"]) is True
    assert bool(summary["policy"]["fallback_to_generic"]) is False
    assert int(summary["sample_size"]["wallet_backed_entries"]) == 12
    assert int(summary["diagnostics"]["overall"]["sample_count"]) == 12
    report = nst.format_personal_calibration_summary(summary, limit=3)
    assert "Quality: good" in report
    status_lines = nst.personal_calibration_status_lines(summary)
    assert any("Personal History: GOOD" in line for line in status_lines)
    assert any("sample 12" in line for line in status_lines)
    assert any("wallet-backed 12" in line for line in status_lines)
    assert any("advisory only" in line for line in status_lines)
    assert "Personal outcome buckets:" in report


def test_personal_history_policy_cfg_defaults_to_advisory() -> None:
    cfg = nst.resolve_personal_history_policy_cfg({})
    assert cfg["enabled"] is True
    assert cfg["mode"] == "advisory"
    assert cfg["min_quality"] == "usable"


def test_personal_history_layer_stays_inactive_for_low_quality() -> None:
    summary = nst.build_personal_calibration_summary(
        [_reconciled_entry(entry_id="only_one", raw_conf=0.70, realized_profit=90.0)],
        _policy_cfg("soft"),
    )
    layer = nst.build_personal_history_layer_state(summary, _policy_cfg("soft"))
    candidate = {"decision_overall_confidence": 0.60, "route_id": "route_jita_o4t", "target_market": "o4t", "exit_type": "planned"}
    nst.apply_personal_history_to_record(candidate, summary, layer, route_id="route_jita_o4t", target_market="o4t", exit_type="planned")
    assert layer["active"] is False
    assert candidate["personal_history_effect_applied"] is False
    assert abs(float(candidate["decision_overall_confidence"]) - 0.60) < 1e-9


def test_personal_history_layer_requires_wallet_backed_and_reliable_minimums() -> None:
    entries = [
        _reconciled_entry(entry_id=f"good_{idx}", raw_conf=0.55 + (idx % 3) * 0.1, realized_profit=95.0 + idx)
        for idx in range(8)
    ]
    cfg = _policy_cfg("soft", require_wallet_backed_min=10, require_reliable_min=10)
    summary = nst.build_personal_calibration_summary(entries, cfg)
    layer = nst.build_personal_history_layer_state(summary, cfg)
    candidate = {"decision_overall_confidence": 0.60, "route_id": "route_jita_o4t", "target_market": "o4t", "exit_type": "planned"}
    nst.apply_personal_history_to_record(candidate, summary, layer, route_id="route_jita_o4t", target_market="o4t", exit_type="planned")
    assert layer["active"] is False
    assert "insufficient wallet-backed sample" in str(layer["reason"])
    assert candidate["personal_history_effect_applied"] is False
    assert abs(float(candidate["decision_overall_confidence"]) - 0.60) < 1e-9


def test_personal_history_off_and_advisory_modes_do_not_change_scores() -> None:
    entries = [
        _reconciled_entry(entry_id=f"good_{idx}", raw_conf=0.45 + (idx % 4) * 0.05, realized_profit=100.0 + idx)
        for idx in range(12)
    ]
    for mode in ("off", "advisory"):
        cfg = _policy_cfg(mode)
        summary = nst.build_personal_calibration_summary(entries, cfg)
        layer = nst.build_personal_history_layer_state(summary, cfg)
        candidate = {"decision_overall_confidence": 0.60, "route_id": "route_jita_o4t", "target_market": "o4t", "exit_type": "planned"}
        nst.apply_personal_history_to_record(candidate, summary, layer, route_id="route_jita_o4t", target_market="o4t", exit_type="planned")
        assert layer["active"] is False
        assert candidate["personal_history_effect_applied"] is False
        assert abs(float(candidate["decision_overall_confidence"]) - 0.60) < 1e-9


def test_personal_history_soft_mode_applies_small_capped_bonus_only_with_good_history() -> None:
    entries = [
        _reconciled_entry(
            entry_id=f"good_{idx}",
            raw_conf=0.30 + (idx % 4) * 0.05,
            realized_profit=110.0 + idx,
            expected_profit=100.0,
            actual_days=7.0,
        )
        for idx in range(12)
    ]
    cfg = _policy_cfg("soft")
    summary = nst.build_personal_calibration_summary(entries, cfg)
    layer = nst.build_personal_history_layer_state(summary, cfg)
    candidate = {"decision_overall_confidence": 0.60, "route_id": "route_jita_o4t", "target_market": "o4t", "exit_type": "planned"}
    nst.apply_personal_history_to_record(candidate, summary, layer, route_id="route_jita_o4t", target_market="o4t", exit_type="planned")
    assert layer["active"] is True
    assert candidate["personal_history_effect_applied"] is True
    assert float(candidate["personal_history_effect_value"]) > 0.0
    assert float(candidate["personal_history_effect_value"]) <= 0.025 + 1e-9
    assert float(candidate["decision_overall_confidence"]) > 0.60
    assert float(candidate["decision_overall_confidence"]) <= 0.625 + 1e-9


def test_personal_history_strict_mode_allows_stronger_but_capped_effect_than_soft() -> None:
    entries = [
        _reconciled_entry(
            entry_id=f"good_{idx}",
            raw_conf=0.30 + (idx % 4) * 0.05,
            realized_profit=110.0 + idx,
            expected_profit=100.0,
            actual_days=7.0,
        )
        for idx in range(12)
    ]
    summary_soft = nst.build_personal_calibration_summary(entries, _policy_cfg("soft"))
    layer_soft = nst.build_personal_history_layer_state(summary_soft, _policy_cfg("soft"))
    candidate_soft = {"decision_overall_confidence": 0.60, "route_id": "route_jita_o4t", "target_market": "o4t", "exit_type": "planned"}
    nst.apply_personal_history_to_record(candidate_soft, summary_soft, layer_soft, route_id="route_jita_o4t", target_market="o4t", exit_type="planned")

    summary_strict = nst.build_personal_calibration_summary(entries, _policy_cfg("strict"))
    layer_strict = nst.build_personal_history_layer_state(summary_strict, _policy_cfg("strict"))
    candidate_strict = {"decision_overall_confidence": 0.60, "route_id": "route_jita_o4t", "target_market": "o4t", "exit_type": "planned"}
    nst.apply_personal_history_to_record(candidate_strict, summary_strict, layer_strict, route_id="route_jita_o4t", target_market="o4t", exit_type="planned")

    assert float(candidate_soft["personal_history_effect_value"]) > 0.0
    assert float(candidate_strict["personal_history_effect_value"]) >= float(candidate_soft["personal_history_effect_value"])
    assert float(candidate_strict["personal_history_effect_value"]) <= 0.05 + 1e-9
    assert float(candidate_strict["decision_overall_confidence"]) >= float(candidate_soft["decision_overall_confidence"])


def test_personal_history_layer_status_lines_show_active_and_fallback_states() -> None:
    good_entries = [
        _reconciled_entry(entry_id=f"good_{idx}", raw_conf=0.35 + (idx % 4) * 0.05, realized_profit=110.0 + idx)
        for idx in range(12)
    ]
    good_cfg = _policy_cfg("soft")
    good_summary = nst.build_personal_calibration_summary(good_entries, good_cfg)
    good_layer = nst.build_personal_history_layer_state(good_summary, good_cfg)
    good_lines = nst.personal_history_layer_status_lines(good_summary, good_layer)
    assert any("Personal Layer: SOFT" in line for line in good_lines)
    assert any("active" in line for line in good_lines)

    weak_summary = nst.build_personal_calibration_summary([], _policy_cfg("soft"))
    weak_layer = nst.build_personal_history_layer_state(weak_summary, _policy_cfg("soft"))
    weak_lines = nst.personal_history_layer_status_lines(weak_summary, weak_layer)
    assert any("generic only" in line for line in weak_lines)
    assert any("Fallback: generic only" in line for line in weak_lines)


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
