"""Shipping tests."""

from tests.shared import *  # noqa: F401,F403

def test_itl_cost_model_collateral_dominant() -> None:
    lane = {
        "per_m3_rate": 100.0,
        "full_load_flat_rate": 2_000_000.0,
        "collateral_rate": 0.01,
    }
    # volume component = min(2,000,000; 1,000*100) = 100,000
    # collateral component = 0.01*50,000,000 = 500,000
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=1000.0, collateral_isk=50_000_000.0)
    assert abs(cost - 500_000.0) < 1e-6

def test_itl_cost_model_volume_dominant() -> None:
    lane = {
        "per_m3_rate": 150.0,
        "full_load_flat_rate": 2_000_000.0,
        "collateral_rate": 0.002,
    }
    # volume component = min(2,000,000; 2,000*150) = 300,000
    # collateral component = 0.002*10,000,000 = 20,000
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=2000.0, collateral_isk=10_000_000.0)
    assert abs(cost - 300_000.0) < 1e-6

def test_itl_cost_model_full_load_cap_dominant() -> None:
    lane = {
        "per_m3_rate": 1000.0,
        "full_load_flat_rate": 1_000_000.0,
        "collateral_rate": None,
    }
    # volume raw = 5,000,000 but full-load cap limits to 1,000,000
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=5000.0, collateral_isk=0.0)
    assert abs(cost - 1_000_000.0) < 1e-6

def test_itl_cost_model_missing_parameters() -> None:
    lane = {
        "per_m3_rate": None,
        "full_load_flat_rate": None,
        "collateral_rate": None,
        "min_reward": 200_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=100.0, collateral_isk=1_000_000.0)
    assert abs(cost - 200_000.0) < 1e-6

def test_itl_cost_model_minimum_reward_dominant() -> None:
    lane = {
        "per_m3_rate": 10.0,
        "minimum_reward": 150_000.0,
        "full_load_reward": 1_000_000.0,
        "collateral_rate": None,
    }
    # volume raw = 100*10=1,000, min reward dominates => 150,000
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=100.0, collateral_isk=0.0)
    assert abs(cost - 150_000.0) < 1e-6

def test_itl_cost_model_volume_rate_only_ignores_collateral() -> None:
    lane = {
        "per_m3_rate": 200.0,
        "minimum_reward": 0.0,
        "full_load_reward": 2_000_000.0,
        "collateral_rate": None,  # volume-rate-only
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=1000.0, collateral_isk=1_000_000_000.0)
    assert abs(cost - 200_000.0) < 1e-6

def test_itl_jita_to_1st_volume_rate_only() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1200.0,
        "full_load_reward": 415_000_000.0,
        "minimum_reward": 5_000_000.0,
        "collateral_rate": 0.0,
        "max_volume_per_contract_m3": 350_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=20_000.0, collateral_isk=3_000_000_000.0)
    assert abs(cost - 24_000_000.0) < 1e-6

def test_itl_1st_to_jita_collateral_rate_005() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1200.0,
        "full_load_reward": 415_000_000.0,
        "minimum_reward": 5_000_000.0,
        "collateral_rate": 0.005,
        "max_volume_per_contract_m3": 350_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=1_000.0, collateral_isk=10_000_000_000.0)
    assert abs(cost - 50_000_000.0) < 1e-6

def test_itl_jita_to_ualx_rate() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1100.0,
        "full_load_reward": 380_000_000.0,
        "minimum_reward": 5_000_000.0,
        "collateral_rate": 0.0,
        "max_volume_per_contract_m3": 350_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=10_000.0, collateral_isk=0.0)
    assert abs(cost - 11_000_000.0) < 1e-6

def test_itl_ualx_to_jita_collateral_rate() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1100.0,
        "full_load_reward": 380_000_000.0,
        "minimum_reward": 5_000_000.0,
        "collateral_rate": 0.005,
        "max_volume_per_contract_m3": 350_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=10_000.0, collateral_isk=4_000_000_000.0)
    assert abs(cost - 20_000_000.0) < 1e-6

def test_itl_jita_to_c_j6mt_rate() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1200.0,
        "full_load_reward": 415_000_000.0,
        "minimum_reward": 5_000_000.0,
        "collateral_rate": 0.0,
        "max_volume_per_contract_m3": 350_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=15_000.0, collateral_isk=0.0)
    assert abs(cost - 18_000_000.0) < 1e-6

def test_itl_c_j6mt_to_jita_collateral_rate() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1200.0,
        "full_load_reward": 415_000_000.0,
        "minimum_reward": 5_000_000.0,
        "collateral_rate": 0.005,
        "max_volume_per_contract_m3": 350_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=15_000.0, collateral_isk=6_000_000_000.0)
    assert abs(cost - 30_000_000.0) < 1e-6

def test_jita_split_price_map_uses_best_buy_and_best_sell_mid() -> None:
    orders = [
        {"type_id": 34, "is_buy_order": True, "price": 95.0},
        {"type_id": 34, "is_buy_order": True, "price": 97.0},
        {"type_id": 34, "is_buy_order": False, "price": 110.0},
        {"type_id": 34, "is_buy_order": False, "price": 103.0},
    ]
    out = nst.build_jita_split_price_map(orders)
    assert abs(float(out[34]) - 100.0) < 1e-6

def test_itl_contract_splitting_by_max_volume() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 10.0,
        "minimum_reward": 0.0,
        "max_volume_per_contract_m3": 350_000.0,
    }
    summary = nst.compute_shipping_lane_total_cost(lane, total_volume_m3=800_000.0, total_collateral_isk=0.0)
    assert int(summary["contracts_used"]) == 3
    assert "max_volume_per_contract_m3" in str(summary["split_reason"])
    assert abs(float(summary["total_cost"]) - 8_000_000.0) < 1e-4

def test_itl_minimum_reward_floor_single_contract_never_below_minimum() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1.0,
        "minimum_reward": 5_000_000.0,
        "full_load_reward": 213_370_000.0,
        "collateral_rate": 0.0,
        "max_volume_per_contract_m3": 350_000.0,
    }
    summary = nst.compute_shipping_lane_total_cost(lane, total_volume_m3=1000.0, total_collateral_isk=0.0)
    assert int(summary["contracts_used"]) == 1
    assert float(summary["total_cost"]) >= 5_000_000.0
    assert abs(float(summary["total_cost"]) - 5_000_000.0) < 1e-6

def test_itl_split_applies_minimum_reward_per_contract() -> None:
    lane = {
        "pricing_model": "itl_max",
        "per_m3_rate": 1.0,
        "minimum_reward": 5_000_000.0,
        "full_load_reward": 213_370_000.0,
        "collateral_rate": 0.0,
        "max_volume_per_contract_m3": 350_000.0,
    }
    summary = nst.compute_shipping_lane_total_cost(lane, total_volume_m3=900_000.0, total_collateral_isk=0.0)
    assert int(summary["contracts_used"]) == 3
    assert "max_volume_per_contract_m3" in str(summary["split_reason"])
    contract_costs = [float(c["shipping_cost"]) for c in list(summary["contracts"])]
    assert all(c >= 5_000_000.0 for c in contract_costs)
    assert abs(float(summary["total_cost"]) - 15_000_000.0) < 1e-6

def test_hwl_formula_volume_plus_value_with_minimum() -> None:
    lane = {
        "pricing_model": "hwl_volume_plus_value",
        "per_m3_rate": 100.0,
        "additional_collateral_rate": 0.01,
        "minimum_reward": 5_000.0,
    }
    # volume + value = 10*100 + 100000*0.01 = 2000 -> min reward should dominate.
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=10.0, collateral_isk=100_000.0)
    assert abs(cost - 5_000.0) < 1e-6

def test_hwl_contract_splitting_by_collateral_cap() -> None:
    lane = {
        "pricing_model": "hwl_volume_plus_value",
        "per_m3_rate": 0.0,
        "additional_collateral_rate": 0.1,
        "minimum_reward": 0.0,
        "max_collateral_per_contract_isk": 100_000.0,
    }
    summary = nst.compute_shipping_lane_total_cost(lane, total_volume_m3=90.0, total_collateral_isk=250_000.0)
    assert int(summary["contracts_used"]) == 3
    assert "max_collateral_per_contract_isk" in str(summary["split_reason"])
    assert abs(float(summary["total_cost"]) - 25_000.0) < 1e-4

def test_hwl_jita_to_o4t_values() -> None:
    lane = {
        "pricing_model": "hwl_volume_plus_value",
        "per_m3_rate": 1250.0,
        "additional_collateral_rate": 0.01,
        "minimum_reward": 5_000_000.0,
        "max_value": 340_000_000_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=100_000.0, collateral_isk=8_000_000_000.0)
    assert abs(cost - 205_000_000.0) < 1e-6

def test_hwl_o4t_to_jita_values() -> None:
    lane = {
        "pricing_model": "hwl_volume_plus_value",
        "per_m3_rate": 1250.0,
        "additional_collateral_rate": 0.01,
        "minimum_reward": 5_000_000.0,
        "max_value": 60_000_000_000.0,
    }
    cost = nst.compute_shipping_lane_reward_cost(lane, volume_m3=1_000.0, collateral_isk=100_000_000.0)
    assert abs(cost - 5_000_000.0) < 1e-6

def test_hwl_max_value_split_greift_korrekt() -> None:
    lane = {
        "pricing_model": "hwl_volume_plus_value",
        "per_m3_rate": 0.0,
        "additional_collateral_rate": 0.01,
        "minimum_reward": 5_000_000.0,
        "max_value": 60_000_000_000.0,
    }
    summary = nst.compute_shipping_lane_total_cost(lane, total_volume_m3=1.0, total_collateral_isk=180_000_000_000.0)
    assert int(summary["contracts_used"]) == 3
    assert "max_collateral_per_contract_isk" in str(summary["split_reason"])
    assert abs(float(summary["total_cost"]) - 1_800_000_000.0) < 1e-6

def test_apply_route_costs_subtracts_shipping_from_profit() -> None:
    picks = [{
        "type_id": 1,
        "name": "Test",
        "qty": 2,
        "unit_volume": 5.0,
        "cost": 20_000.0,
        "revenue_net": 25_000.0,
        "profit": 5_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "shipping_lane_id": "itl_jita_1st",
        "shipping_lane_cfg": {
            "per_m3_rate": 100.0,
            "full_load_flat_rate": None,
            "collateral_rate": None,
        },
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    # 10 m3 * 100 ISK = 1,000 shipping cost
    assert abs(float(summary["total_shipping_cost"]) - 1000.0) < 1e-6
    assert abs(float(picks[0]["profit"]) - 4000.0) < 1e-6
    assert abs(float(picks[0]["transport_cost"]) - 1000.0) < 1e-6

def test_apply_route_costs_subtracts_ansiplex_route_cost() -> None:
    picks = [{
        "type_id": 1,
        "name": "Test",
        "qty": 10,
        "unit_volume": 10.0,
        "cost": 100_000.0,
        "revenue_net": 120_000.0,
        "profit": 20_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "shipping_lane_id": "",
        "shipping_lane_cfg": None,
        "route_cost_cfg": {"fixed_isk": 5_000.0, "isk_per_m3": 10.0},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    # total volume = 100 m3 => route cost = 5,000 + 1,000 = 6,000
    assert abs(float(summary["total_route_cost"]) - 6000.0) < 1e-6
    assert abs(float(picks[0]["profit"]) - 14000.0) < 1e-6

def test_apply_route_costs_blocks_missing_cost_model_by_default() -> None:
    picks = [{
        "type_id": 1,
        "name": "X",
        "qty": 5,
        "unit_volume": 2.0,
        "cost": 50_000.0,
        "revenue_net": 65_000.0,
        "profit": 15_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "source_label": "A",
        "dest_label": "B",
        "shipping_lane_id": "",
        "shipping_lane_cfg": None,
        "shipping_lane_candidates": [],
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0, "is_explicit": False},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    assert bool(summary.get("transport_cost_assumed_zero", False)) is True
    assert str(summary.get("cost_model_confidence", "")) == "blocked"
    assert bool(summary.get("route_blocked_due_to_transport", False)) is True
    assert "route is blocked" in str(summary.get("cost_model_warning", ""))

def test_apply_route_costs_explicit_zero_route_cost_is_not_low_confidence() -> None:
    picks = [{
        "type_id": 1,
        "name": "Y",
        "qty": 5,
        "unit_volume": 2.0,
        "cost": 50_000.0,
        "revenue_net": 65_000.0,
        "profit": 15_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "source_label": "A",
        "dest_label": "B",
        "shipping_lane_id": "",
        "shipping_lane_cfg": None,
        "shipping_lane_candidates": [],
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0, "is_explicit": True},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    assert bool(summary.get("transport_cost_assumed_zero", False)) is False
    assert str(summary.get("cost_model_confidence", "")) == "normal"

def test_apply_route_costs_allowlisted_zero_transport_route_remains_actionable() -> None:
    picks = [{
        "type_id": 1,
        "name": "X",
        "qty": 5,
        "unit_volume": 2.0,
        "cost": 50_000.0,
        "revenue_net": 65_000.0,
        "profit": 15_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "route_id": "a->b",
        "source_label": "A",
        "dest_label": "B",
        "shipping_lane_id": "",
        "shipping_lane_cfg": None,
        "shipping_lane_candidates": [],
        "allow_zero_transport_cost_for_routes": ["a->b"],
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0, "is_explicit": False},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    assert bool(summary.get("route_blocked_due_to_transport", False)) is False
    assert bool(summary.get("route_actionable", False)) is True
    assert str(summary.get("cost_model_confidence", "")) == "exception"

def test_pick_level_shipping_allocation_sums_to_route_total() -> None:
    picks = [
        {
            "type_id": 1,
            "name": "A",
            "qty": 1,
            "unit_volume": 1.25,
            "cost": 1000.0,
            "revenue_net": 2000.0,
            "profit": 1000.0,
            "turnover_factor": 1.0,
        },
        {
            "type_id": 2,
            "name": "B",
            "qty": 1,
            "unit_volume": 2.75,
            "cost": 2000.0,
            "revenue_net": 3500.0,
            "profit": 1500.0,
            "turnover_factor": 1.0,
        },
    ]
    ctx = {
        "shipping_lane_id": "itl_jita_1st",
        "shipping_lane_cfg": {
            "pricing_model": "itl_max",
            "per_m3_rate": 1234.5,
            "minimum_reward": 0.0,
            "collateral_rate": 0.0,
        },
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    pick_shipping_sum = sum(float(p.get("shipping_cost", 0.0)) for p in picks)
    assert abs(pick_shipping_sum - float(summary["total_shipping_cost"])) < 1e-6

def test_shipping_lane_selection_honors_policy_lane_selection() -> None:
    picks = [{
        "type_id": 1,
        "name": "A",
        "qty": 100,
        "unit_volume": 1.0,
        "cost": 1_000_000.0,
        "revenue_net": 2_000_000.0,
        "profit": 1_000_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "source_label": "jita_44",
        "dest_label": "o4t",
        "shipping_lane_id": "hwl_lane",
        "shipping_lane_cfg": {"pricing_model": "hwl_volume_plus_value", "per_m3_rate": 50_000.0, "minimum_reward": 1_000_000.0},
        "shipping_lane_candidates": [
            {"id": "hwl_lane", "cfg": {"pricing_model": "hwl_volume_plus_value", "per_m3_rate": 50_000.0, "minimum_reward": 1_000_000.0}},
            {"id": "itl_lane_cheaper", "cfg": {"pricing_model": "itl_max", "per_m3_rate": 1.0, "minimum_reward": 1_000.0}},
        ],
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0},
        "shipping_defaults": {"collateral_buffer_pct": 0.0},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    assert str(summary["shipping_lane_id"]) == "hwl_lane"

def test_shipping_lane_selection_honors_explicit_preferred_lane() -> None:
    picks = [{
        "type_id": 1,
        "name": "A",
        "qty": 100,
        "unit_volume": 1.0,
        "cost": 1_000_000.0,
        "revenue_net": 2_000_000.0,
        "profit": 1_000_000.0,
        "turnover_factor": 1.0,
    }]
    ctx = {
        "shipping_lane_id": "cheap",
        "shipping_lane_cfg": {"pricing_model": "itl_max", "per_m3_rate": 100.0, "minimum_reward": 1_000.0},
        "shipping_lane_candidates": [
            {"id": "expensive", "cfg": {"pricing_model": "itl_max", "per_m3_rate": 10_000.0, "minimum_reward": 10_000_000.0}},
            {"id": "cheap", "cfg": {"pricing_model": "itl_max", "per_m3_rate": 100.0, "minimum_reward": 1_000.0}},
        ],
        "preferred_shipping_lane_id": "expensive",
        "route_cost_cfg": {"fixed_isk": 0.0, "isk_per_m3": 0.0},
        "shipping_defaults": {"collateral_buffer_pct": 0.0},
    }
    summary = nst.apply_route_costs_to_picks(picks, ctx)
    assert str(summary["shipping_lane_id"]) == "expensive"
    assert abs(float(summary["total_shipping_cost"]) - 10_000_000.0) < 1e-6

def test_execution_plan_shipping_total_matches_route_result_field() -> None:
    route_results = [{
        "route_label": "A -> B",
        "source_label": "A",
        "dest_label": "B",
        "source_node_info": {"node_label": "A", "node_kind": "structure", "structure_id": 1, "node_id": 1},
        "dest_node_info": {"node_label": "B", "node_kind": "structure", "structure_id": 2, "node_id": 2},
        "shipping_lane_id": "itl_a_b",
        "shipping_pricing_model": "itl_max",
        "shipping_provider": "ITL",
        "shipping_contracts_used": 1,
        "shipping_lane_params": {
            "per_m3_rate": 1200.0,
            "minimum_reward": 5_000_000.0,
            "full_load_reward": 415_000_000.0,
            "collateral_rate": 0.005,
            "additional_collateral_rate": None,
            "max_volume_per_contract_m3": 350_000,
            "max_collateral_per_contract_isk": None,
            "max_value": None,
            "collateral_basis": "jita_split",
        },
        "estimated_collateral_isk": 100_000_000.0,
        "isk_used": 10_000_000.0,
        "profit_total": 1_000_000.0,
        "budget_total": 20_000_000.0,
        "total_shipping_cost": 5_000_000.0,
        "shipping_cost_total": 5_000_000.0,
        "total_transport_cost": 5_000_000.0,
        "total_route_m3": 1.0,
        "picks": [{
            "type_id": 34,
            "name": "Tritanium",
            "qty": 1,
            "buy_avg": 10_000_000.0,
            "target_sell_price": 16_000_000.0,
            "sell_avg": 16_000_000.0,
            "instant": True,
            "fill_probability": 1.0,
            "expected_days_to_sell": 0.0,
            "profit": 1_000_000.0,
            "revenue_net": 11_000_000.0,
            "transport_cost": 5_000_000.0,
            "buy_broker_fee_total": 0.0,
            "sell_broker_fee_total": 0.0,
            "sales_tax_total": 0.0,
            "relist_budget_total": 0.0,
            "unit_volume": 1.0,
            "buy_at": "A",
            "sell_at": "B",
        }],
    }]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_test.txt")
        nst.write_execution_plan_profiles(out_path, "2026-03-05_00-00-00", route_results)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "Shipping Cost Total: 5.000.000,00 ISK" in content
    assert "shipping_cost_total: 5.000.000,00 ISK" in content
    assert "provider: ITL" in content
    assert "per_m3_rate: 1200.0" in content
    assert "minimum_reward: 5000000.0" in content
    assert "collateral_basis: jita_split" in content
    assert "total_route_m3: 1.00 m3" in content
    assert "unit_volume: 1.00 m3 | total_m3: 1.00 m3" in content
    assert "sales_tax_isk:" in content
    assert "broker_fee_isk:" in content
    assert "scc_surcharge_isk:" in content
    assert "relist_fee_isk:" in content

def test_execution_plan_marks_zero_pick_route_as_not_actionable() -> None:
    route_results = [{
        "route_label": "A -> B",
        "source_label": "A",
        "dest_label": "B",
        "route_blocked_due_to_transport": True,
        "route_prune_reason": "missing_transport_cost_model",
        "cost_model_confidence": "blocked",
        "cost_model_warning": "No shipping lane or explicit route_costs matched this route; route is blocked until transport cost is modeled.",
        "profit_total": 0.0,
        "picks": [],
    }]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_test.txt")
        nst.write_execution_plan_profiles(out_path, "2026-03-05_00-00-00", route_results)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "[NOT ACTIONABLE]" in content
    assert "route_prune_reason: missing_transport_cost_model" in content
    assert "Route ist nicht actionable" in content

def test_route_search_allowed_pairs_can_pin_shipping_lane_id() -> None:
    node_catalog = {
        "o4t": {"label": "o4t", "id": 1, "kind": "structure"},
        "jita_44": {"label": "jita_44", "id": 60003760, "kind": "location", "location_id": 60003760, "region_id": 10000002},
    }
    cfg = {
        "route_search": {
            "enabled": True,
            "allow_all_structures_internal": False,
            "allow_shipping_lanes": False,
            "allowed_pairs": [{"from": "jita_44", "to": "o4t", "shipping_lane_id": "hwl_jita_o4t"}],
        },
        "shipping_lanes": {},
    }
    profiles = nst.build_route_search_profiles(node_catalog, cfg)
    assert len(profiles) == 1
    assert str(profiles[0].get("shipping_lane_id", "")) == "hwl_jita_o4t"

def test_resolve_shipping_lane_cfg_prefers_policy_provider() -> None:
    cfg = {
        "shipping_lanes": {
            "hwl_jita_ualx": {
                "enabled": True,
                "from": "jita_44",
                "to": "ualx-3",
                "pricing_model": "hwl_volume_plus_value",
                "per_m3_rate": 1250.0,
                "minimum_reward": 5_000_000.0,
                "additional_collateral_rate": 0.01,
                "max_value": 60_000_000_000.0,
            },
            "itl_jita_ualx": {
                "enabled": True,
                "from": "jita_44",
                "to": "ualx-3",
                "pricing_model": "itl_max",
                "per_m3_rate": 1100.0,
                "minimum_reward": 5_000_000.0,
                "full_load_reward": 380_000_000.0,
                "collateral_rate": 0.0,
                "max_volume_per_contract_m3": 350_000.0,
            },
        }
    }
    resolved = nst.resolve_shipping_lane_cfg(cfg, "jita_44", "ualx-3")
    assert resolved is not None
    assert str(resolved[0]) == "itl_jita_ualx"

