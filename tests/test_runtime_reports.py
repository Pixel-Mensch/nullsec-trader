import os
import tempfile

import nullsectrader as nst


def _pick(
    *,
    name: str,
    type_id: int,
    qty: int,
    buy_avg: float,
    sell_avg: float,
    profit: float,
    unit_volume: float,
    buy_at: str,
    sell_at: str,
    route_hops: int,
    expected_days_to_sell: float = 5.0,
) -> dict:
    return {
        "name": name,
        "type_id": type_id,
        "qty": qty,
        "buy_avg": buy_avg,
        "sell_avg": sell_avg,
        "target_sell_price": sell_avg,
        "buy_at": buy_at,
        "sell_at": sell_at,
        "route_hops": route_hops,
        "order_duration_days": 90,
        "expected_days_to_sell": expected_days_to_sell,
        "fill_probability": 0.60,
        "profit": profit,
        "expected_realized_profit_90d": profit,
        "unit_volume": unit_volume,
        "overall_confidence": 0.82,
        "raw_confidence": 0.82,
        "calibrated_confidence": 0.82,
        "decision_overall_confidence": 0.82,
        "revenue_net": float((sell_avg * qty) - 5.0),
    }


def _actionable_leg(
    *,
    route_label: str,
    source_label: str,
    dest_label: str,
    isk_used: float,
    profit_total: float,
    capital_committed: float | None = None,
) -> dict:
    pick = _pick(
        name=f"{route_label} Item",
        type_id=1001,
        qty=3,
        buy_avg=100.0,
        sell_avg=130.0,
        profit=profit_total,
        unit_volume=5.0,
        buy_at=source_label,
        sell_at=dest_label,
        route_hops=2,
    )
    return {
        "route_label": route_label,
        "route_id": route_label.lower().replace(" ", "_"),
        "source_label": source_label,
        "dest_label": dest_label,
        "mode": "instant",
        "selected_mode": "instant",
        "filters_used": {"ranking_metric": "risk_adjusted_expected_profit", "strict_mode_enabled": False},
        "leg_disabled": False,
        "leg_disabled_reason": "",
        "total_candidates": 4,
        "passed_all_filters": 1,
        "items_count": 1,
        "m3_used": 15.0,
        "cargo_total": 10000.0,
        "cargo_util_pct": 0.15,
        "isk_used": isk_used,
        "budget_total": 500_000_000.0,
        "budget_util_pct": (isk_used / 500_000_000.0) * 100.0,
        "profit_total": profit_total,
        "net_revenue_total": isk_used + profit_total,
        "total_transport_cost": 250_000.0,
        "total_shipping_cost": 250_000.0,
        "route_actionable": True,
        "capital_available_before": 500_000_000.0,
        "capital_committed": capital_committed if capital_committed is not None else isk_used,
        "capital_released": 0.0,
        "capital_available_after": 500_000_000.0 - float(capital_committed if capital_committed is not None else isk_used),
        "capital_release_rule": "instant",
        "picks": [pick],
    }


def _suppressed_internal_leg(route_label: str) -> dict:
    return {
        "route_label": route_label,
        "route_id": route_label.lower().replace(" ", "_"),
        "source_label": "UALX-3",
        "dest_label": "C-J6MT",
        "mode": "instant",
        "selected_mode": "instant",
        "filters_used": {"ranking_metric": "risk_adjusted_expected_profit", "strict_mode_enabled": False},
        "leg_disabled": False,
        "leg_disabled_reason": "",
        "total_candidates": 3,
        "passed_all_filters": 0,
        "items_count": 0,
        "m3_used": 0.0,
        "cargo_total": 10000.0,
        "cargo_util_pct": 0.0,
        "isk_used": 0.0,
        "budget_total": 500_000_000.0,
        "budget_util_pct": 0.0,
        "profit_total": 0.0,
        "net_revenue_total": 0.0,
        "total_transport_cost": 0.0,
        "total_shipping_cost": 0.0,
        "route_actionable": False,
        "route_prune_reason": "internal_route_profit_below_operational_floor",
        "operational_profit_floor_isk": 2_000_000.0,
        "suppressed_expected_realized_profit_total": 1_300_000.0,
        "operational_filter_note": "Internal nullsec routes require at least 2.0m ISK expected realized profit.",
        "why_out_summary": {"profile_min_expected_profit_isk": 1},
        "capital_available_before": 500_000_000.0,
        "capital_committed": 0.0,
        "capital_released": 0.0,
        "capital_available_after": 500_000_000.0,
        "capital_release_rule": "instant",
        "picks": [],
    }


def test_write_execution_plan_chain_marks_sequential_aggregate_not_simultaneous() -> None:
    forward_legs = [
        _actionable_leg(
            route_label="O4T -> R-ARKN",
            source_label="O4T",
            dest_label="R-ARKN",
            isk_used=300_000_000.0,
            profit_total=12_000_000.0,
            capital_committed=300_000_000.0,
        )
    ]
    return_legs = [
        _actionable_leg(
            route_label="R-ARKN -> O4T",
            source_label="R-ARKN",
            dest_label="O4T",
            isk_used=240_000_000.0,
            profit_total=9_500_000.0,
            capital_committed=240_000_000.0,
        )
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_chain.txt")
        nst.write_execution_plan_chain(out_path, "2026-03-13_18-00-00", forward_legs, return_legs)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

    assert "BEST ACTIONABLE LEG" in content
    assert "AGGREGATE ACROSS SEQUENTIAL CHAIN LEGS" in content
    assert "NOT a simultaneous capital requirement" in content
    assert "Peak Capital Committed In One Leg" in content
    assert "Aggregate Expected Profit Across Legs" in content


def test_write_execution_plan_chain_shows_suppressed_internal_leg_details() -> None:
    forward_legs = [_suppressed_internal_leg("UALX-3 -> C-J6MT")]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_chain.txt")
        nst.write_execution_plan_chain(out_path, "2026-03-13_18-00-00", forward_legs, None)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

    assert "UALX-3 -> C-J6MT" in content
    assert "Status: NOT ACTIONABLE" in content
    assert "route_prune_reason: internal_route_profit_below_operational_floor" in content
    assert "Internal Route Floor" in content
    assert "Suppressed Expected Profit" in content


def test_write_enhanced_summary_marks_roundtrip_as_sequential_and_surfaces_floor() -> None:
    forward_result = _actionable_leg(
        route_label="O4T -> CJ6",
        source_label="O4T",
        dest_label="CJ6",
        isk_used=280_000_000.0,
        profit_total=11_000_000.0,
        capital_committed=280_000_000.0,
    )
    return_result = _suppressed_internal_leg("CJ6 -> O4T")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "roundtrip_plan.txt")
        nst.write_enhanced_summary(
            out_path,
            forward_result["picks"],
            float(forward_result["isk_used"]),
            float(forward_result["profit_total"]),
            return_result["picks"],
            float(return_result["isk_used"]),
            float(return_result["profit_total"]),
            cargo_m3=10000.0,
            budget_isk=500_000_000.0,
            forward_result=forward_result,
            return_result=return_result,
        )
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

    assert "BEST ACTIONABLE LEG" in content
    assert "AGGREGATE ACROSS SEQUENTIAL ROUNDTRIP LEGS" in content
    assert "NOT a simultaneous capital requirement" in content
    assert "Peak Single-Leg Capital" in content
    assert "Status: NOT ACTIONABLE" in content
    assert "Internal Route Floor" in content
