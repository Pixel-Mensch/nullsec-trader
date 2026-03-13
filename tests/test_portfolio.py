"""Portfolio tests."""

from tests.shared import *  # noqa: F401,F403

def test_try_cargo_fill_topup_existing_pick() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    port_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 10,
        "cargo_fill_max_extra_items": 8,
        "cargo_fill_ranking_metric": "profit_per_m3",
        "cargo_fill_allow_topup_existing": True,
    }

    base_picks = [{
        "type_id": 1001,
        "name": "Test Item",
        "qty": 2,
        "unit_volume": 5.0,
        "buy_avg": 10.0,
        "sell_avg": 20.0,
        "cost": 20.0,
        "revenue_net": 40.0,
        "profit": 20.0,
        "profit_pct": 1.0,
        "instant": True,
        "suggested_sell_price": 20.0,
        "order_duration_days": 90,
        "liquidity_score": 1.0,
        "history_volume_30d": 100.0,
        "daily_volume": 10.0,
        "dest_buy_depth_units": 50,
        "instant_fill_ratio": 1.0,
        "competition_price_levels_near_best": 0,
        "queue_ahead_units": 0,
        "fill_probability": 1.0,
        "turnover_factor": 1.0,
        "profit_per_m3": 2.0,
        "profit_per_m3_per_day": 2.0,
        "mode": "instant",
        "target_sell_price": 20.0,
        "avg_daily_volume_30d": 10.0,
        "expected_days_to_sell": 1.0,
        "sell_through_ratio_90d": 1.0,
        "risk_score": 0.0,
        "expected_profit_90d": 20.0,
        "expected_profit_per_m3_90d": 2.0,
        "used_volume_fallback": False,
        "reference_price": 0.0,
        "reference_price_average": 0.0,
        "reference_price_adjusted": 0.0,
        "reference_price_source": "",
        "buy_discount_vs_ref": 0.0,
        "sell_markup_vs_ref": 0.0,
        "reference_price_penalty": 0.0,
    }]

    candidate = nst.TradeCandidate(
        type_id=1001,
        name="Test Item",
        unit_volume=5.0,
        buy_avg=10.0,
        sell_avg=20.0,
        max_units=10,
        profit_per_unit=10.0,
        profit_pct=1.0,
        instant=True,
        suggested_sell_price=20.0,
        liquidity_score=1,
        history_volume_30d=100,
        daily_volume=10.0,
        dest_buy_depth_units=50,
        instant_fill_ratio=1.0,
        fill_probability=1.0,
        turnover_factor=1.0,
        profit_per_m3=2.0,
        profit_per_m3_per_day=2.0,
        mode="instant",
        target_sell_price=20.0,
        avg_daily_volume_30d=10.0,
        expected_days_to_sell=1.0,
        sell_through_ratio_90d=1.0,
        risk_score=0.0,
        expected_profit_90d=100.0,
        expected_profit_per_m3_90d=2.0,
        used_volume_fallback=False,
    )

    picks, total_cost, total_profit, total_m3, added = nst.try_cargo_fill(
        base_picks=base_picks,
        candidates=[candidate],
        budget_isk=1_000.0,
        cargo_m3=1_000.0,
        fees=fees,
        filters_used=filters_used,
        port_cfg=port_cfg,
    )

    assert len(picks) == 1, f"Expected top-up in existing line, got {len(picks)} pick lines."
    assert picks[0]["type_id"] == 1001
    assert picks[0]["qty"] > 2, f"Expected qty to increase, got {picks[0]['qty']}"
    assert total_cost > 20.0
    assert total_profit > 20.0
    assert total_m3 > 10.0
    assert added > 0
    assert "sales_tax_isk" in picks[0]
    assert "broker_fee_isk" in picks[0]
    assert "scc_surcharge_isk" in picks[0]
    assert "relist_fee_isk" in picks[0]


def test_build_portfolio_prefers_cleaner_market_quality_pick() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    portfolio_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 1,
        "max_liquidation_days_per_position": 30.0,
        "max_share_of_estimated_demand_per_position": 1.0,
    }
    clean = nst.TradeCandidate(
        type_id=2001,
        name="Clean Book",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=140.0,
        max_units=1,
        profit_per_unit=40.0,
        profit_pct=0.40,
        instant=True,
        fill_probability=0.90,
        turnover_factor=1.0,
        expected_days_to_sell=1.0,
        expected_realized_profit_90d=40.0,
        expected_realized_profit_per_m3_90d=40.0,
        overall_confidence=0.80,
        liquidity_confidence=0.85,
        exit_confidence=0.85,
        market_plausibility_score=0.92,
        market_quality_score=0.90,
        manipulation_risk_score=0.05,
        profit_at_top_of_book=40.0,
        profit_at_conservative_executable_price=38.0,
        profit_retention_ratio=0.95,
    )
    fragile = nst.TradeCandidate(
        type_id=2002,
        name="Fragile Book",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=145.0,
        max_units=1,
        profit_per_unit=45.0,
        profit_pct=0.45,
        instant=True,
        fill_probability=0.90,
        turnover_factor=1.0,
        expected_days_to_sell=1.0,
        expected_realized_profit_90d=45.0,
        expected_realized_profit_per_m3_90d=45.0,
        overall_confidence=0.80,
        liquidity_confidence=0.85,
        exit_confidence=0.85,
        market_plausibility_score=0.78,
        market_quality_score=0.58,
        manipulation_risk_score=0.35,
        profit_at_top_of_book=90.0,
        profit_at_conservative_executable_price=61.0,
        profit_retention_ratio=0.68,
        market_plausibility={"flags": ["THIN_TOP_OF_BOOK"]},
    )

    picks, _, _, _ = nst.build_portfolio([fragile, clean], 500.0, 100.0, fees, filters, portfolio_cfg)
    assert len(picks) == 1
    assert picks[0]["type_id"] == 2001


def test_try_cargo_fill_skips_market_quality_gate_rejects() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    port_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 10,
        "cargo_fill_max_extra_items": 8,
        "cargo_fill_ranking_metric": "profit_per_m3",
        "cargo_fill_allow_topup_existing": False,
    }
    base_picks = [{
        "type_id": 3001,
        "name": "Base Item",
        "qty": 1,
        "unit_volume": 1.0,
        "buy_avg": 50.0,
        "sell_avg": 60.0,
        "cost": 50.0,
        "revenue_net": 60.0,
        "profit": 10.0,
        "profit_pct": 0.20,
        "instant": True,
        "suggested_sell_price": 60.0,
        "order_duration_days": 90,
        "liquidity_score": 1.0,
        "history_volume_30d": 100.0,
        "daily_volume": 10.0,
        "dest_buy_depth_units": 20,
        "instant_fill_ratio": 1.0,
        "competition_price_levels_near_best": 0,
        "queue_ahead_units": 0,
        "fill_probability": 1.0,
        "turnover_factor": 1.0,
        "profit_per_m3": 10.0,
        "profit_per_m3_per_day": 10.0,
        "mode": "instant",
        "target_sell_price": 60.0,
        "avg_daily_volume_30d": 10.0,
        "expected_days_to_sell": 1.0,
        "sell_through_ratio_90d": 1.0,
        "risk_score": 0.0,
        "expected_profit_90d": 10.0,
        "expected_realized_profit_90d": 10.0,
        "expected_profit_per_m3_90d": 10.0,
    }]
    fragile = nst.TradeCandidate(
        type_id=3002,
        name="Fragile Fill",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=170.0,
        max_units=1,
        profit_per_unit=70.0,
        profit_pct=0.70,
        instant=True,
        fill_probability=1.0,
        turnover_factor=1.0,
        expected_days_to_sell=1.0,
        expected_realized_profit_90d=70.0,
        expected_realized_profit_per_m3_90d=70.0,
        overall_confidence=0.80,
        liquidity_confidence=0.80,
        exit_confidence=0.80,
        market_plausibility_score=0.58,
        market_quality_score=0.44,
        manipulation_risk_score=0.46,
        profit_at_top_of_book=140.0,
        profit_at_conservative_executable_price=84.0,
        profit_retention_ratio=0.60,
        market_plausibility={"flags": ["THIN_TOP_OF_BOOK", "ORDERBOOK_CONCENTRATION"]},
    )

    picks, _, _, _, added = nst.try_cargo_fill(
        base_picks=base_picks,
        candidates=[fragile],
        budget_isk=1_000.0,
        cargo_m3=1_000.0,
        fees=fees,
        filters_used=filters_used,
        port_cfg=port_cfg,
    )

    assert len(picks) == 1
    assert picks[0]["type_id"] == 3001
    assert added == 0

def test_candidate_scaled_expected_days_keeps_queue_component() -> None:
    from portfolio_builder import _candidate_scaled_expected_days

    candidate = {
        "expected_days_to_sell": 20.0,
        "max_units": 10,
        "queue_ahead_units": 90,
    }

    scaled_days = _candidate_scaled_expected_days(candidate, 1)
    assert abs(scaled_days - 18.2) < 1e-9

def test_build_portfolio_pick_expected_days_respects_queue_ahead_units() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    portfolio_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 1,
        "max_liquidation_days_per_position": 30.0,
        "max_share_of_estimated_demand_per_position": 1.0,
    }
    planned = nst.TradeCandidate(
        type_id=9101,
        name="queued-planned",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=160.0,
        max_units=10,
        profit_per_unit=60.0,
        profit_pct=0.60,
        instant=False,
        mode="planned_sell",
        queue_ahead_units=90,
        expected_days_to_sell=20.0,
        expected_units_sold_90d=5.0,
        expected_units_unsold_90d=5.0,
        expected_realized_profit_90d=300.0,
        expected_realized_profit_per_m3_90d=30.0,
        estimated_sellable_units_90d=20.0,
        fill_probability=0.5,
        turnover_factor=0.5,
        overall_confidence=0.7,
        exit_confidence=0.7,
        liquidity_confidence=0.7,
    )

    picks, _, _, _ = nst.build_portfolio([planned], 150.0, 100.0, fees, filters, portfolio_cfg)
    assert len(picks) == 1
    assert abs(float(picks[0]["expected_days_to_sell"]) - 18.2) < 1e-9

def test_strict_rejects_fallback_volume() -> None:
    esi = _FakeESI(history_30=0, history_7=0, reference_price=100.0)
    source_orders, dest_orders = _simple_orders(dest_price=130.0)
    explain = {}
    nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0},
        filters=_strict_filters(),
        dest_structure_id=123,
        explain=explain,
    )
    assert int(explain.get("reason_counts", {}).get("strict_no_fallback_volume", 0)) >= 1

def test_strict_rejects_missing_reference_price() -> None:
    esi = _FakeESI(history_30=100, history_7=20, reference_price=0.0)
    source_orders, dest_orders = _simple_orders(dest_price=130.0)
    explain = {}
    nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0},
        filters=_strict_filters(),
        dest_structure_id=123,
        explain=explain,
    )
    assert int(explain.get("reason_counts", {}).get("strict_missing_reference_price", 0)) >= 1

def test_strict_rejects_hard_reference_markup() -> None:
    esi = _FakeESI(history_30=100, history_7=20, reference_price=100.0)
    source_orders, dest_orders = _simple_orders(dest_price=300.0)
    explain = {}
    nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0},
        filters=_strict_filters(),
        dest_structure_id=123,
        explain=explain,
    )
    assert int(explain.get("reason_counts", {}).get("strict_reference_price_hard_sell_markup", 0)) >= 1

def test_strict_keeps_instant_capital_release_behavior() -> None:
    leg = {
        "isk_used": 100.0,
        "picks": [{"mode": "instant", "revenue_net": 130.0}],
    }
    cap_cfg = {"enabled": True, "release_on_instant": True, "release_on_fast_sell": False, "fast_sell_release_ratio": 1.0}
    after = nst._apply_capital_flow_to_leg(leg, "instant", 500.0, cap_cfg)
    assert abs(after - 530.0) < 1e-6
    assert float(leg.get("capital_released", 0.0)) == 130.0

def test_capital_release_happens_on_exit_leg_index() -> None:
    pending = {}
    cap_cfg = {"enabled": True, "release_on_instant": True, "release_on_fast_sell": False, "fast_sell_release_ratio": 1.0}
    leg0 = {
        "isk_used": 100.0,
        "picks": [{"mode": "instant", "revenue_net": 130.0, "release_leg_index": 1}],
    }
    after0 = nst._apply_capital_flow_to_leg(leg0, "instant", 500.0, cap_cfg, current_leg_index=0, pending_releases=pending)
    assert abs(after0 - 400.0) < 1e-6
    assert abs(float(pending.get(1, 0.0)) - 130.0) < 1e-6
    leg1 = {"isk_used": 0.0, "picks": []}
    after1 = nst._apply_capital_flow_to_leg(leg1, "instant", after0, cap_cfg, current_leg_index=1, pending_releases=pending)
    assert abs(after1 - 530.0) < 1e-6
    assert abs(float(pending.get(1, 0.0))) < 1e-6

def test_fee_engine_instant_sell_applies_only_sales_tax() -> None:
    engine = FeeEngine({
        "buy_broker_fee": 0.0,
        "sell_broker_fee": 0.03,
        "sales_tax": 0.075,
        "scc_surcharge": 0.005,
        "sell_market_type": "upwell",
        "skills": {"accounting": 3, "broker_relations": 3, "advanced_broker_relations": 3},
    })
    breakdown = engine.compute(100.0, 200.0, 10, execution="instant_instant")
    assert abs(breakdown.sales_tax_isk - 150.0) < 1e-6
    assert abs(breakdown.broker_fee_isk) < 1e-9
    assert abs(breakdown.scc_surcharge_isk) < 1e-9
    assert abs(breakdown.relist_fee_isk) < 1e-9
    assert abs(breakdown.revenue_net - 1850.0) < 1e-6


def test_fee_engine_sell_order_includes_broker_scc_and_sales_tax() -> None:
    engine = FeeEngine({
        "buy_broker_fee": 0.0,
        "sell_broker_fee": 0.03,
        "sales_tax": 0.075,
        "scc_surcharge": 0.005,
        "sell_market_type": "upwell",
        "skills": {"accounting": 3, "broker_relations": 3, "advanced_broker_relations": 3},
    })
    breakdown = engine.compute(
        100.0,
        200.0,
        10,
        execution="instant_listed",
        relist_budget_pct=0.01,
        relist_budget_isk=20.0,
    )
    assert abs(breakdown.sales_tax_isk - 150.0) < 1e-6
    assert abs(breakdown.broker_fee_isk - 60.0) < 1e-6
    assert abs(breakdown.scc_surcharge_isk - 10.0) < 1e-6
    assert abs(breakdown.relist_fee_isk - 40.0) < 1e-6
    assert abs(breakdown.revenue_net - 1740.0) < 1e-6


def test_fee_engine_broker_relations_depends_on_market_type() -> None:
    upwell = FeeEngine({
        "sell_broker_fee": 0.03,
        "sales_tax": 0.075,
        "scc_surcharge": 0.005,
        "sell_market_type": "upwell",
        "broker_relations_delta_per_level": 0.002,
        "skills": {"accounting": 3, "broker_relations": 5, "advanced_broker_relations": 3},
    }).compute(10.0, 100.0, 1, execution="instant_listed")
    npc = FeeEngine({
        "sell_broker_fee": 0.03,
        "sales_tax": 0.075,
        "scc_surcharge": 0.005,
        "sell_market_type": "npc",
        "broker_relations_delta_per_level": 0.002,
        "skills": {"accounting": 3, "broker_relations": 5, "advanced_broker_relations": 3},
    }).compute(10.0, 100.0, 1, execution="instant_listed")
    assert abs(upwell.broker_fee_isk - 3.0) < 1e-6
    assert abs(npc.broker_fee_isk - 2.6) < 1e-6


def test_fee_engine_advanced_broker_relations_reduces_relist_fees() -> None:
    level3 = FeeEngine({
        "sell_broker_fee": 0.03,
        "sales_tax": 0.075,
        "scc_surcharge": 0.005,
        "advanced_broker_relations_relist_discount_per_level": 0.10,
        "skills": {"accounting": 3, "broker_relations": 3, "advanced_broker_relations": 3},
    }).compute(10.0, 100.0, 1, execution="instant_listed", relist_budget_pct=0.10)
    level5 = FeeEngine({
        "sell_broker_fee": 0.03,
        "sales_tax": 0.075,
        "scc_surcharge": 0.005,
        "advanced_broker_relations_relist_discount_per_level": 0.10,
        "skills": {"accounting": 3, "broker_relations": 3, "advanced_broker_relations": 5},
    }).compute(10.0, 100.0, 1, execution="instant_listed", relist_budget_pct=0.10)
    assert abs(level3.relist_fee_isk - 10.0) < 1e-6
    assert abs(level5.relist_fee_isk - 8.0) < 1e-6

def test_route_wide_score_not_pure_cargo_density() -> None:
    scan_cfg = nst._resolve_route_wide_scan_cfg({
        "route_wide_scan": {
            "enabled": True,
            "cargo_penalty_per_extra_leg": 0.05,
            "capital_lock_penalty_per_extra_leg": 0.07
        }
    })
    c_low_margin = nst.TradeCandidate(
        type_id=1, name="low_margin", unit_volume=10.0, buy_avg=100.0, sell_avg=101.0,
        max_units=1000, profit_per_unit=1.0, profit_pct=0.01, fill_probability=1.0,
        instant_fill_ratio=1.0, mode="instant", profit_per_m3_per_day=20000.0
    )
    c_high_margin = nst.TradeCandidate(
        type_id=2, name="high_margin", unit_volume=10.0, buy_avg=100.0, sell_avg=160.0,
        max_units=200, profit_per_unit=60.0, profit_pct=0.60, fill_probability=1.0,
        instant_fill_ratio=1.0, mode="instant", profit_per_m3_per_day=8000.0
    )
    s1 = nst._route_adjusted_candidate_score(c_low_margin, hop_count=1, scan_cfg=scan_cfg)
    s2 = nst._route_adjusted_candidate_score(c_high_margin, hop_count=1, scan_cfg=scan_cfg)
    assert s2 > s1

def test_planned_sell_rejects_when_queue_ahead_is_too_heavy() -> None:
    esi = _FakeESI(history_30=30, history_7=10, reference_price=100.0)
    source_orders = [{"type_id": 42, "is_buy_order": False, "price": 90.0, "volume_remain": 500}]
    dest_orders = [
        {"type_id": 42, "is_buy_order": False, "price": 130.0, "volume_remain": 500},
        {"type_id": 42, "is_buy_order": False, "price": 130.1, "volume_remain": 500},
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
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0},
        filters=filters,
        dest_structure_id=123,
        explain=explain,
    )
    assert candidates == []
    assert int(explain.get("reason_counts", {}).get("planned_queue_ahead_too_heavy", 0)) >= 1

def test_build_portfolio_can_choose_planned_over_weaker_instant() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    portfolio_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 1,
        "max_liquidation_days_per_position": 45.0,
        "max_share_of_estimated_demand_per_position": 0.5,
    }
    instant = nst.TradeCandidate(
        type_id=1,
        name="instant",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=110.0,
        max_units=1,
        profit_per_unit=10.0,
        profit_pct=0.10,
        instant=True,
        dest_buy_depth_units=10,
        fill_probability=1.0,
        expected_realized_profit_90d=10.0,
        expected_realized_profit_per_m3_90d=10.0,
        overall_confidence=1.0,
    )
    planned = nst.TradeCandidate(
        type_id=2,
        name="planned",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=220.0,
        max_units=1,
        profit_per_unit=120.0,
        profit_pct=1.20,
        instant=False,
        mode="planned_sell",
        expected_days_to_sell=10.0,
        expected_units_sold_90d=0.8,
        expected_units_unsold_90d=0.2,
        expected_realized_profit_90d=96.0,
        expected_realized_profit_per_m3_90d=96.0,
        estimated_sellable_units_90d=10.0,
        exit_confidence=0.8,
        liquidity_confidence=0.8,
        overall_confidence=0.8,
    )
    picks, _, _, _ = nst.build_portfolio([instant, planned], 1_000.0, 100.0, fees, filters, portfolio_cfg)
    assert len(picks) == 1
    assert int(picks[0]["type_id"]) == 2

def test_build_portfolio_caps_single_position_by_estimated_demand() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    portfolio_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 3,
        "max_liquidation_days_per_position": 45.0,
        "max_share_of_estimated_demand_per_position": 0.5,
    }
    thin_candidate = nst.TradeCandidate(
        type_id=3,
        name="thin-demand",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=180.0,
        max_units=100,
        profit_per_unit=80.0,
        profit_pct=0.80,
        instant=False,
        mode="planned_sell",
        expected_days_to_sell=20.0,
        expected_units_sold_90d=4.0,
        expected_units_unsold_90d=1.0,
        expected_realized_profit_90d=320.0,
        expected_realized_profit_per_m3_90d=64.0,
        estimated_sellable_units_90d=10.0,
        exit_confidence=0.7,
        liquidity_confidence=0.7,
        overall_confidence=0.7,
    )
    picks, _, _, _ = nst.build_portfolio([thin_candidate], 1_000_000.0, 100_000.0, fees, filters, portfolio_cfg)
    assert len(picks) == 1
    assert int(picks[0]["qty"]) <= 5


# --- Fix K1: _portfolio_objective liquidity penalty is meaningful ---

def test_portfolio_objective_penalizes_long_hold_proportionally() -> None:
    """Long-hold picks must incur a penalty significant enough to affect optimizer decisions."""
    from portfolio_builder import _portfolio_objective

    base_pick = {
        "type_id": 1,
        "cost": 50_000_000.0,
        "expected_realized_profit_90d": 5_000_000.0,
        "profit": 5_000_000.0,
    }
    short_pick = dict(base_pick, expected_days_to_sell=10.0)
    long_pick = dict(base_pick, expected_days_to_sell=90.0)

    cfg = {"max_item_share_of_budget": 1.0}
    budget = 100_000_000.0

    score_short = _portfolio_objective([short_pick], budget, cfg)
    score_long = _portfolio_objective([long_pick], budget, cfg)

    # Short-hold must score strictly higher than long-hold.
    assert score_short > score_long, (
        f"Expected short-hold (score={score_short}) > long-hold (score={score_long})"
    )
    # Penalty must be at least 1% of expected profit (60 extra days * 5M * 0.005 = 1.5M).
    penalty = score_short - score_long
    assert penalty >= 1_000_000.0, f"Penalty {penalty:,.0f} too small — liquidity cost not meaningful"


def test_portfolio_objective_no_penalty_within_30d() -> None:
    """Picks held ≤ 30 days should receive zero liquidity penalty."""
    from portfolio_builder import _portfolio_objective

    pick_30 = {"type_id": 1, "cost": 10_000_000.0, "expected_realized_profit_90d": 2_000_000.0, "profit": 2_000_000.0, "expected_days_to_sell": 30.0}
    pick_1 = dict(pick_30, expected_days_to_sell=1.0)

    cfg = {"max_item_share_of_budget": 1.0}
    score_30 = _portfolio_objective([pick_30], 50_000_000.0, cfg)
    score_1 = _portfolio_objective([pick_1], 50_000_000.0, cfg)
    assert score_30 == score_1


# --- Fix H1: try_cargo_fill base_profit_per_m3 uses expected_realized, not gross profit ---

def test_cargo_fill_base_profit_uses_expected_realized() -> None:
    """
    Base picks with low expected_realized (high unsold ratio) must not set an
    overly generous base_profit_per_m3 threshold that lets low-quality cargo fill through.
    """
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    # cargo_fill_min_profit_per_m3_ratio=1.0 means fill must match base profit density exactly
    port_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 10,
        "cargo_fill_max_extra_items": 5,
        "cargo_fill_ranking_metric": "profit_per_m3",
        "cargo_fill_min_profit_per_m3_ratio": 1.0,
        "cargo_fill_allow_topup_existing": False,
    }

    # Base pick: gross profit=1000, but expected_realized=200 (80% unsold)
    base_picks = [{
        "type_id": 2001, "name": "Base", "qty": 1, "unit_volume": 10.0,
        "buy_avg": 100.0, "sell_avg": 1100.0, "cost": 100.0,
        "revenue_net": 1100.0, "profit": 1000.0,
        "expected_realized_profit_90d": 200.0,
        "instant": False, "mode": "planned_sell",
        "suggested_sell_price": 1100.0, "order_duration_days": 90,
        "fill_probability": 0.2, "turnover_factor": 0.2,
        "profit_per_m3": 100.0, "profit_per_m3_per_day": 20.0,
        "expected_days_to_sell": 5.0, "sell_through_ratio_90d": 0.2,
    }]

    # Fill candidate: gross profit density = 250/10=25/m3, which is > expected_realized base (200/10=20/m3)
    # If base uses gross profit (1000/10=100/m3), candidate (25/m3) would be rejected.
    # If base uses expected_realized (200/10=20/m3), candidate (25/m3) should pass.
    fill_candidate = nst.TradeCandidate(
        type_id=3001, name="Fill", unit_volume=10.0,
        buy_avg=50.0, sell_avg=300.0, max_units=5,
        profit_per_unit=250.0, profit_pct=5.0, instant=True,
        dest_buy_depth_units=50, fill_probability=1.0,
        profit_per_m3=25.0, profit_per_m3_per_day=25.0,
        expected_realized_profit_90d=1250.0,
    )

    _, _, _, _, n_added = nst.try_cargo_fill(
        base_picks=base_picks,
        candidates=[fill_candidate],
        budget_isk=100_000.0,
        cargo_m3=10_000.0,
        fees=fees,
        filters_used=filters_used,
        port_cfg=port_cfg,
    )
    # With expected_realized base (20/m3) and ratio=1.0, candidate at 25/m3 must pass.
    assert n_added >= 1, "Fill candidate should have been accepted when base uses expected_realized profit"


def test_cargo_fill_candidate_profit_gate_uses_expected_realized_for_planned_fill() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    port_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 10,
        "cargo_fill_max_extra_items": 5,
        "cargo_fill_ranking_metric": "profit_per_m3",
        "cargo_fill_min_profit_per_m3_ratio": 1.0,
        "cargo_fill_allow_topup_existing": False,
    }

    base_picks = [{
        "type_id": 2001, "name": "Base", "qty": 1, "unit_volume": 10.0,
        "buy_avg": 100.0, "sell_avg": 1100.0, "cost": 100.0,
        "revenue_net": 1100.0, "profit": 1000.0,
        "expected_realized_profit_90d": 200.0,
        "instant": False, "mode": "planned_sell",
        "suggested_sell_price": 1100.0, "order_duration_days": 90,
        "fill_probability": 0.2, "turnover_factor": 0.2,
        "profit_per_m3": 100.0, "profit_per_m3_per_day": 20.0,
        "expected_days_to_sell": 5.0, "sell_through_ratio_90d": 0.2,
    }]

    fill_candidate = nst.TradeCandidate(
        type_id=3002, name="PlannedFill", unit_volume=10.0,
        buy_avg=50.0, sell_avg=300.0, max_units=1,
        profit_per_unit=250.0, profit_pct=5.0,
        instant=False, mode="planned_sell",
        fill_probability=0.2,
        turnover_factor=0.2,
        expected_days_to_sell=10.0,
        expected_realized_profit_90d=50.0,
        expected_realized_profit_per_m3_90d=5.0,
        overall_confidence=0.5,
        exit_confidence=0.5,
        liquidity_confidence=0.5,
    )

    _, _, _, _, n_added = nst.try_cargo_fill(
        base_picks=base_picks,
        candidates=[fill_candidate],
        budget_isk=100_000.0,
        cargo_m3=10_000.0,
        fees=fees,
        filters_used=filters_used,
        port_cfg=port_cfg,
    )
    assert n_added == 0, "Planned cargo-fill candidate should be rejected when expected realized profit density is below the base threshold"


# --- Fix H2: instant_fill_ratio = 0.0 for planned_sell picks ---

def test_planned_sell_pick_has_zero_instant_fill_ratio() -> None:
    """planned_sell picks must not carry instant_fill_ratio=1.0 in their output dict."""
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.03, "sales_tax": 0.036, "scc_surcharge": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    portfolio_cfg = {"max_item_share_of_budget": 1.0, "max_items": 10, "max_liquidation_days_per_position": 99.0, "max_share_of_estimated_demand_per_position": 1.0}

    planned = nst.TradeCandidate(
        type_id=5001, name="planned_item", unit_volume=1.0,
        buy_avg=100.0, sell_avg=200.0, max_units=3,
        profit_per_unit=100.0, profit_pct=1.0,
        instant=False, mode="planned_sell",
        dest_buy_depth_units=0,
        fill_probability=0.6,
        expected_days_to_sell=30.0,
        expected_units_sold_90d=2.0,
        expected_realized_profit_90d=200.0,
        expected_realized_profit_per_m3_90d=200.0,
        estimated_sellable_units_90d=5.0,
        overall_confidence=0.6,
    )
    picks, _, _, _ = nst.build_portfolio([planned], 10_000.0, 100.0, fees, filters_used, portfolio_cfg)
    assert len(picks) == 1
    ratio = float(picks[0].get("instant_fill_ratio", 1.0))
    assert ratio == 0.0, f"planned_sell pick should have instant_fill_ratio=0.0, got {ratio}"


def test_build_portfolio_rejects_pick_below_min_expected_profit() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters_used = {
        "max_turnover_factor": 3.0,
        "min_instant_fill_ratio": 0.0,
        "order_duration_days": 90,
        "min_expected_profit_isk": 500.0,
    }
    portfolio_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 10,
        "max_liquidation_days_per_position": 99.0,
        "max_share_of_estimated_demand_per_position": 1.0,
    }
    low_profit = nst.TradeCandidate(
        type_id=7001,
        name="too_small",
        unit_volume=1.0,
        buy_avg=100.0,
        sell_avg=140.0,
        max_units=1,
        profit_per_unit=40.0,
        profit_pct=0.40,
        instant=True,
        fill_probability=1.0,
        expected_realized_profit_90d=40.0,
        expected_realized_profit_per_m3_90d=40.0,
        overall_confidence=1.0,
    )
    picks, _, _, _ = nst.build_portfolio([low_profit], 10_000.0, 100.0, fees, filters_used, portfolio_cfg)
    assert picks == []


def test_build_portfolio_skips_zero_volume_candidate() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0, "scc_surcharge": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    portfolio_cfg = {
        "max_item_share_of_budget": 1.0,
        "max_items": 10,
        "max_liquidation_days_per_position": 99.0,
        "max_share_of_estimated_demand_per_position": 1.0,
    }
    bad_volume = nst.TradeCandidate(
        type_id=7002,
        name="bad_volume",
        unit_volume=0.0,
        buy_avg=100.0,
        sell_avg=200.0,
        max_units=5,
        profit_per_unit=100.0,
        profit_pct=1.0,
        instant=True,
        fill_probability=1.0,
        expected_realized_profit_90d=500.0,
        expected_realized_profit_per_m3_90d=0.0,
        overall_confidence=1.0,
    )
    picks, _, _, _ = nst.build_portfolio([bad_volume], 10_000.0, 100.0, fees, filters_used, portfolio_cfg)
    assert picks == []


def test_compute_candidates_marks_invalid_volume_data() -> None:
    class _ZeroVolumeESI(_FakeESI):
        def resolve_type_volume(self, tid):
            return 0.0

    esi = _ZeroVolumeESI(history_30=100, history_7=20, reference_price=100.0)
    source_orders, dest_orders = _simple_orders(dest_price=160.0)
    explain = {}
    candidates = nst.compute_candidates(
        esi=esi,
        source_orders=source_orders,
        dest_orders=dest_orders,
        fees={"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0},
        filters=_strict_filters(),
        dest_structure_id=123,
        explain=explain,
    )
    assert candidates == []
    assert int(explain.get("reason_counts", {}).get("invalid_volume", 0)) >= 1


def test_cargo_fill_respects_profile_item_budget_cap() -> None:
    fees = {"buy_broker_fee": 0.0, "sell_broker_fee": 0.0, "sales_tax": 0.0}
    filters_used = {"max_turnover_factor": 3.0, "min_instant_fill_ratio": 0.0, "order_duration_days": 90}
    port_cfg = nst.apply_profile_to_portfolio_cfg(
        nst.BUILTIN_PROFILES["balanced"],
        {
            "max_item_share_of_budget": 1.0,
            "cargo_fill_max_item_share_of_budget": 0.75,
            "max_items": 10,
            "cargo_fill_max_extra_items": 4,
            "cargo_fill_ranking_metric": "profit_per_m3",
            "cargo_fill_allow_topup_existing": False,
        },
    )
    base_picks = [{
        "type_id": 8001,
        "name": "Base",
        "qty": 1,
        "unit_volume": 5.0,
        "buy_avg": 50_000_000.0,
        "sell_avg": 60_000_000.0,
        "cost": 50_000_000.0,
        "revenue_net": 60_000_000.0,
        "profit": 10_000_000.0,
        "expected_realized_profit_90d": 10_000_000.0,
        "instant": True,
        "mode": "instant",
        "target_sell_price": 60_000_000.0,
        "fill_probability": 1.0,
        "turnover_factor": 1.0,
        "profit_per_m3": 2_000_000.0,
        "profit_per_m3_per_day": 2_000_000.0,
        "expected_days_to_sell": 1.0,
        "sell_through_ratio_90d": 1.0,
    }]
    overweight_fill = nst.TradeCandidate(
        type_id=8002,
        name="TooBigFill",
        unit_volume=5.0,
        buy_avg=225_000_000.0,
        sell_avg=255_000_000.0,
        max_units=1,
        profit_per_unit=30_000_000.0,
        profit_pct=0.1333,
        instant=True,
        fill_probability=1.0,
        turnover_factor=1.0,
        profit_per_m3=6_000_000.0,
        profit_per_m3_per_day=6_000_000.0,
        expected_realized_profit_90d=30_000_000.0,
        expected_realized_profit_per_m3_90d=6_000_000.0,
    )

    picks, _, _, _, added = nst.try_cargo_fill(
        base_picks=base_picks,
        candidates=[overweight_fill],
        budget_isk=500_000_000.0,
        cargo_m3=10_000.0,
        fees=fees,
        filters_used=filters_used,
        port_cfg=port_cfg,
    )
    assert added == 0
    assert [p["type_id"] for p in picks] == [8001]

