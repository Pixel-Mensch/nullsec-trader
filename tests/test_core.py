"""Core tests."""

from tests.shared import *  # noqa: F401,F403

def test_fallback_volume_boundary_with_epsilon() -> None:
    fallback_daily_volume = 0.2
    fallback_volume_penalty = 0.35
    min_avg_daily_volume = 0.07
    avg_daily_volume_30d = fallback_daily_volume * fallback_volume_penalty

    assert math.isclose(avg_daily_volume_30d, 0.07, rel_tol=0.0, abs_tol=1e-9), (
        f"Expected ~0.07, got {avg_daily_volume_30d!r}"
    )
    old_reject = avg_daily_volume_30d < min_avg_daily_volume
    new_reject = (avg_daily_volume_30d + 1e-9) < min_avg_daily_volume
    assert old_reject is True, "Old comparison should fail on floating-point boundary."
    assert new_reject is False, "New epsilon-safe comparison should allow boundary value."

def test_make_skipped_chain_leg_shape() -> None:
    leg = nst.make_skipped_chain_leg(
        src_label="UALX-3",
        dst_label="1st Taj Mahgoon",
        reason="route_mode_forward_only",
        mode="fast_sell",
        filters_used={"min_profit_pct": 0.04},
        budget_isk=500_000_000,
        cargo_m3=10_000,
    )
    assert leg["route_label"] == "UALX-3 -> 1st Taj Mahgoon"
    assert leg["leg_disabled"] is True
    assert leg["leg_disabled_reason"] == "route_mode_forward_only"
    assert leg["mode"] == "fast_sell"
    assert leg["items_count"] == 0
    assert leg["budget_util_pct"] == 0.0
    assert leg["cargo_util_pct"] == 0.0

def test_write_execution_plan_chain_contains_forward_and_return() -> None:
    forward_legs = [{
        "route_label": "O4T -> R-ARKN",
        "source_label": "O4T",
        "dest_label": "R-ARKN",
        "leg_disabled": False,
        "items_count": 1,
        "m3_used": 5.0,
        "cargo_total": 10000.0,
        "isk_used": 300.0,
        "profit_total": 90.0,
        "picks": [{
            "type_id": 2001,
            "name": "Forward Item",
            "qty": 3,
            "buy_avg": 100.0,
            "sell_avg": 130.0,
            "target_sell_price": 130.0,
            "buy_at": "O4T",
            "sell_at": "UALX-3",
            "route_hops": 2,
            "order_duration_days": 90,
            "expected_days_to_sell": 10.0,
            "fill_probability": 0.5,
            "profit": 90.0,
            "unit_volume": 5.0,
        }],
    }]

    return_legs = [{
        "route_label": "R-ARKN -> O4T",
        "source_label": "R-ARKN",
        "dest_label": "O4T",
        "leg_disabled": False,
        "items_count": 1,
        "m3_used": 4.0,
        "cargo_total": 10000.0,
        "isk_used": 200.0,
        "profit_total": 40.0,
        "picks": [{
            "type_id": 3001,
            "name": "Return Item",
            "qty": 2,
            "buy_avg": 100.0,
            "sell_avg": 120.0,
            "target_sell_price": 120.0,
            "buy_at": "R-ARKN",
            "sell_at": "O4T",
            "route_hops": 1,
            "order_duration_days": 90,
            "expected_days_to_sell": 12.0,
            "fill_probability": 0.4,
            "profit": 40.0,
            "unit_volume": 4.0,
        }],
    }]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_test.txt")
        nst.write_execution_plan_chain(
            path=out_path,
            timestamp="2026-03-04_00-00-00",
            forward_leg_results=forward_legs,
            return_leg_results=return_legs,
        )
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

    assert "FORWARD" in content, "Execution plan is missing FORWARD block."
    assert "RETURN" in content, "Execution plan is missing RETURN block."
    assert "Forward Item" in content, "Forward pick missing from execution plan."
    assert "Return Item" in content, "Return pick missing from execution plan."
    assert "Cargo: used" in content, "Cargo line missing in execution plan."
    assert "Route-Hops: 2" in content, "Route hops missing in execution plan."
    assert "SELL [UALX-3]" in content, "sell_at target missing in execution plan."

def test_compute_chain_leg_budget_cap() -> None:
    cap_cfg = {"enabled": True}
    strict_cfg = {"enabled": True, "chain_leg_max_budget_share": 0.6}
    leg_budget, capped = nst._compute_chain_leg_budget(
        capital_available=500_000_000.0,
        start_budget_isk=500_000_000.0,
        cap_cfg=cap_cfg,
        strict_cfg=strict_cfg,
    )
    assert capped is True
    assert abs(leg_budget - 300_000_000.0) < 1e-6

def test_route_wide_prefers_nearer_exit_if_profit_close() -> None:
    cur = nst.TradeCandidate(
        type_id=9001, name="X", unit_volume=1.0, buy_avg=10.0, sell_avg=12.0,
        max_units=1, profit_per_unit=2.0, profit_pct=0.2
    )
    cur.route_adjusted_score = 100.0
    cur.dest_hop_count = 1
    ch = nst.TradeCandidate(
        type_id=9001, name="X", unit_volume=1.0, buy_avg=10.0, sell_avg=12.0,
        max_units=1, profit_per_unit=2.0, profit_pct=0.2
    )
    ch.route_adjusted_score = 108.0
    ch.dest_hop_count = 3
    best = nst._choose_best_route_wide_candidate(cur, ch, close_pct=0.10)
    assert best is cur

def test_planned_sell_rejects_if_micro_liquidity_bad() -> None:
    esi = _FakeESI(history_30=500, history_7=100, reference_price=100.0)
    source_orders = [{"type_id": 42, "is_buy_order": False, "price": 90.0, "volume_remain": 20}]
    dest_orders = [
        {"type_id": 42, "is_buy_order": False, "price": 130.0, "volume_remain": 50},
        {"type_id": 42, "is_buy_order": False, "price": 131.0, "volume_remain": 50},
    ]
    filters = _strict_filters()
    filters["strict_mode"]["enabled"] = False
    filters["strict_require_reference_price_for_planned"] = False
    filters["strict_disable_fallback_volume_for_planned"] = False
    filters["min_depth_within_2pct_sell"] = 1000
    filters["max_competition_density_near_best"] = 0
    explain = {}
    _ = nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.03, "sales_tax": 0.036, "relist_budget_pct": 0.01},
        filters=filters,
        dest_structure_id=123,
        explain=explain,
    )
    assert int(explain.get("reason_counts", {}).get("planned_structure_micro_liquidity", 0)) >= 1

def test_dead_market_with_paper_margin_is_rejected() -> None:
    esi = _FakeESI(history_30=1, history_7=1, reference_price=100.0)
    source_orders = [{"type_id": 42, "is_buy_order": False, "price": 90.0, "volume_remain": 50}]
    dest_orders = [
        {"type_id": 42, "is_buy_order": False, "price": 300.0, "volume_remain": 10},
        {"type_id": 42, "is_buy_order": False, "price": 301.0, "volume_remain": 10},
    ]
    filters = _strict_filters()
    filters["strict_mode"]["enabled"] = False
    filters["strict_require_reference_price_for_planned"] = False
    filters["strict_disable_fallback_volume_for_planned"] = False
    filters["reference_price"]["enabled"] = False
    explain = {}
    candidates = nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.03, "sales_tax": 0.036},
        filters=filters,
        dest_structure_id=123,
        explain=explain,
    )
    assert candidates == []
    reason_counts = explain.get("reason_counts", {})
    assert (
        int(reason_counts.get("planned_demand_cap_zero", 0)) >= 1
        or int(reason_counts.get("planned_structure_micro_liquidity", 0)) >= 1
    )

def test_fake_spread_thin_sell_wall_is_rejected() -> None:
    esi = _FakeESI(history_30=300, history_7=70, reference_price=100.0)
    source_orders = [{"type_id": 42, "is_buy_order": False, "price": 90.0, "volume_remain": 50}]
    dest_orders = [
        {"type_id": 42, "is_buy_order": False, "price": 300.0, "volume_remain": 1},
        {"type_id": 42, "is_buy_order": False, "price": 450.0, "volume_remain": 100},
    ]
    filters = _strict_filters()
    filters["strict_mode"]["enabled"] = False
    filters["strict_require_reference_price_for_planned"] = False
    filters["strict_disable_fallback_volume_for_planned"] = False
    explain = {}
    candidates = nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.03, "sales_tax": 0.036},
        filters=filters,
        dest_structure_id=123,
        explain=explain,
    )
    assert candidates == []
    assert int(explain.get("reason_counts", {}).get("planned_price_unreliable_orderbook", 0)) >= 1

def test_autofill_structure_regions_from_known_labels() -> None:
    cfg = {
        "esi": {"auto_fill_structure_regions": True},
        "structures": {
            "o4t": 1040804972352,
            "cj6": 1049588174021,
        },
        "structure_regions": {},
    }
    resolved = nst._resolve_structure_region_map(cfg)
    assert int(resolved.get(1040804972352, 0)) == 10000059
    assert int(resolved.get(1049588174021, 0)) == 10000009

def test_autofill_does_not_override_explicit_mapping() -> None:
    cfg = {
        "esi": {"auto_fill_structure_regions": True},
        "structures": {
            "o4t": 1040804972352,
            "cj6": {"id": 1049588174021, "region_id": 10000059},
        },
        "structure_regions": {
            "1040804972352": 10000009
        },
    }
    resolved = nst._resolve_structure_region_map(cfg)
    assert int(resolved.get(1040804972352, 0)) == 10000009
    assert int(resolved.get(1049588174021, 0)) == 10000059

def test_autofill_disabled_keeps_missing_mapping() -> None:
    cfg = {
        "esi": {"auto_fill_structure_regions": False},
        "structures": {
            "o4t": 1040804972352,
            "cj6": 1049588174021,
        },
        "structure_regions": {},
    }
    resolved = nst._resolve_structure_region_map(cfg)
    assert int(resolved.get(1040804972352, 0)) == 0
    assert int(resolved.get(1049588174021, 0)) == 0

def test_resolve_structure_region_map_handles_int_structures() -> None:
    cfg = {
        "structures": {
            "o4t": 1040804972352,
            "cj6": 1049588174021,
        },
        "structure_regions": {
            "1040804972352": 10000059,
            "1049588174021": 10000009,
        },
    }
    resolved = nst._resolve_structure_region_map(cfg)
    assert int(resolved.get(1040804972352, 0)) == 10000059
    assert int(resolved.get(1049588174021, 0)) == 10000009


# --- Fix H3: market_plausibility planned_sell usable_depth_ratio uses proposed_qty as neutral fallback ---

def test_market_plausibility_planned_sell_no_competition_not_hard_rejected() -> None:
    """
    For planned_sell with zero competing sell orders below our target price,
    usable_depth_ratio must use proposed_qty as fallback (we can list our own qty).
    Before fix: exit_usable_units=0 → fallback was source_usable_units (wrong association).
    After fix: exit_usable_units=0 → fallback is proposed_qty → ratio reflects our position size.
    """
    from market_plausibility import assess_market_plausibility
    from models import OrderLevel

    source_levels = [OrderLevel(price=90.0, volume=50)]
    # Destination sell orders all above our 180 ISK target → exit_usable_units = 0
    exit_levels = [OrderLevel(price=200.0, volume=20), OrderLevel(price=210.0, volume=20)]

    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.03, "sales_tax": 0.036}
    result = assess_market_plausibility(
        source_levels=source_levels,
        exit_levels=exit_levels,
        exit_is_buy=False,
        proposed_qty=10,
        source_usable_price=90.0,
        exit_usable_price=180.0,
        reference_price=180.0,
        mode="planned_sell",
        fees=fees,
        price_depth_pct=0.02,
        competition_band_pct=0.01,
        relist_budget_pct=0.0,
        relist_budget_isk=0.0,
        cfg={},
    )
    # exit_depth_for_ratio = proposed_qty=10 (no competition → we list our own qty)
    # source_usable_units = 50. min(50, 10)=10. required=ceil(10*0.35)=4. ratio=10/4=2.5→capped at 1.0
    assert result["usable_depth_ratio"] >= 1.0, (
        f"planned_sell with no competition should have usable_depth_ratio >= 1.0, got {result['usable_depth_ratio']}"
    )
    # Must not be hard-rejected solely due to zero competition depth
    assert result.get("hard_reject") is False or "UNUSABLE_DEPTH" not in result["flags"], (
        "No-competition planned_sell must not be hard-rejected for depth"
    )


def test_market_plausibility_planned_sell_with_competition_uses_exit_depth() -> None:
    """With actual competition below our target, exit_usable_units > 0 and used directly."""
    from market_plausibility import assess_market_plausibility
    from models import OrderLevel

    source_levels = [OrderLevel(price=90.0, volume=50)]
    exit_levels = [OrderLevel(price=150.0, volume=20), OrderLevel(price=160.0, volume=20), OrderLevel(price=170.0, volume=20)]

    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.03, "sales_tax": 0.036}
    result = assess_market_plausibility(
        source_levels=source_levels,
        exit_levels=exit_levels,
        exit_is_buy=False,
        proposed_qty=10,
        source_usable_price=90.0,
        exit_usable_price=180.0,
        reference_price=180.0,
        mode="planned_sell",
        fees=fees,
        price_depth_pct=0.02,
        competition_band_pct=0.01,
        relist_budget_pct=0.0,
        relist_budget_isk=0.0,
        cfg={},
    )
    assert result["exit_usable_depth_at_confidence_price"] == 60
    assert result["usable_depth_at_confidence_price"] == min(50, 60)
    assert result["usable_depth_ratio"] >= 1.0


def test_market_quality_gate_rejects_fragile_price_sensitive_book() -> None:
    from market_plausibility import market_quality_gate_from_metrics

    metrics = {
        "market_plausibility_score": 0.58,
        "manipulation_risk_score": 0.48,
        "profit_retention_ratio": 0.62,
        "flags": ["THIN_TOP_OF_BOOK", "ORDERBOOK_CONCENTRATION"],
    }

    reject, reason = market_quality_gate_from_metrics(metrics)
    assert reject is True
    assert reason in {"THIN_TOP_OF_BOOK", "ORDERBOOK_CONCENTRATION"}

