"""Public facade for the Nullsec Trader Tool.

This module has one narrow responsibility: provide the stable top-level import
surface used by tests and local tooling, and delegate CLI execution to
`runtime_runner.run_cli()`.

It intentionally contains no business logic.
"""

from __future__ import annotations

import candidate_engine as _candidate_engine
import config_loader as _config_loader
import execution_plan as _execution_plan
import fees as _fees
import location_utils as _location_utils
import market_fetch as _market_fetch
import market_normalization as _market_normalization
import models as _models
import portfolio_builder as _portfolio_builder
import route_search as _route_search
import runtime_clients as _runtime_clients
import runtime_common as _runtime_common
import runtime_reports as _runtime_reports
import runtime_runner as _runtime_runner
import scoring as _scoring
import shipping as _shipping
import startup_helpers as _startup_helpers


_EXPORTS = {
    "_choose_best_route_wide_candidate": _candidate_engine._choose_best_route_wide_candidate,
    "_route_adjusted_candidate_score": _candidate_engine._route_adjusted_candidate_score,
    "apply_strategy_filters": _candidate_engine.apply_strategy_filters,
    "build_levels": _candidate_engine.build_levels,
    "compute_candidates": _candidate_engine.compute_candidates,
    "compute_route_wide_candidates_for_source": _candidate_engine.compute_route_wide_candidates_for_source,
    "depth_slice": _candidate_engine.depth_slice,
    "get_structure_micro_liquidity": _candidate_engine.get_structure_micro_liquidity,
    "_build_fix_hint": _config_loader._build_fix_hint,
    "_collect_required_structure_ids": _config_loader._collect_required_structure_ids,
    "_prepare_trade_filters": _config_loader._prepare_trade_filters,
    "_resolve_strict_mode_cfg": _config_loader._resolve_strict_mode_cfg,
    "_resolve_structure_region_map": _config_loader._resolve_structure_region_map,
    "_validate_structure_region_mapping": _config_loader._validate_structure_region_mapping,
    "ensure_dirs": _config_loader.ensure_dirs,
    "fail_on_invalid_config": _config_loader.fail_on_invalid_config,
    "load_config": _config_loader.load_config,
    "load_json": _config_loader.load_json,
    "save_json": _config_loader.save_json,
    "validate_config": _config_loader.validate_config,
    "write_execution_plan_profiles": _execution_plan.write_execution_plan_profiles,
    "write_route_leaderboard": _execution_plan.write_route_leaderboard,
    "compute_trade_financials": _fees.compute_trade_financials,
    "label_to_slug": _location_utils.label_to_slug,
    "normalize_location_label": _location_utils.normalize_location_label,
    "_fetch_orders_for_node": _market_fetch._fetch_orders_for_node,
    "make_snapshot_payload": _market_normalization.make_snapshot_payload,
    "normalize_replay_snapshot": _market_normalization.normalize_replay_snapshot,
    "FilterFunnel": _models.FilterFunnel,
    "OrderLevel": _models.OrderLevel,
    "TradeCandidate": _models.TradeCandidate,
    "_sort_candidates_for_cargo_fill": _portfolio_builder._sort_candidates_for_cargo_fill,
    "build_portfolio": _portfolio_builder.build_portfolio,
    "choose_portfolio_for_route": _portfolio_builder.choose_portfolio_for_route,
    "local_search_optimize": _portfolio_builder.local_search_optimize,
    "portfolio_stats": _portfolio_builder.portfolio_stats,
    "sort_picks_for_output": _portfolio_builder.sort_picks_for_output,
    "try_cargo_fill": _portfolio_builder.try_cargo_fill,
    "validate_portfolio": _portfolio_builder.validate_portfolio,
    "_parse_route_pair_token": _route_search._parse_route_pair_token,
    "_resolve_allowed_route_pair_lane_overrides": _route_search._resolve_allowed_route_pair_lane_overrides,
    "_resolve_allowed_route_pairs": _route_search._resolve_allowed_route_pairs,
    "_resolve_route_search_cfg": _route_search._resolve_route_search_cfg,
    "build_route_search_profiles": _route_search.build_route_search_profiles,
    "CallbackState": _runtime_clients.CallbackState,
    "CachedResponse": _runtime_clients.CachedResponse,
    "ESIClient": _runtime_clients.ESIClient,
    "OAuthHandler": _runtime_clients.OAuthHandler,
    "ReplayESIClient": _runtime_clients.ReplayESIClient,
    "BASE_DIR": _runtime_common.BASE_DIR,
    "CACHE_DIR": _runtime_common.CACHE_DIR,
    "CONFIG_PATH": _runtime_common.CONFIG_PATH,
    "HTTP_CACHE_PATH": _runtime_common.HTTP_CACHE_PATH,
    "TOKEN_PATH": _runtime_common.TOKEN_PATH,
    "TYPE_CACHE_PATH": _runtime_common.TYPE_CACHE_PATH,
    "_has_live_esi_credentials": _runtime_common._has_live_esi_credentials,
    "b64url": _runtime_common.b64url,
    "die": _runtime_common.die,
    "input_with_default": _runtime_common.input_with_default,
    "make_basic_auth": _runtime_common.make_basic_auth,
    "parse_cli_args": _runtime_common.parse_cli_args,
    "parse_isk": _runtime_common.parse_isk,
    "fmt_isk": _runtime_reports.fmt_isk,
    "pick_total_fees_taxes": _runtime_reports.pick_total_fees_taxes,
    "write_chain_summary": _runtime_reports.write_chain_summary,
    "write_csv": _runtime_reports.write_csv,
    "write_enhanced_summary": _runtime_reports.write_enhanced_summary,
    "write_execution_plan_chain": _runtime_reports.write_execution_plan_chain,
    "write_top_candidate_dump": _runtime_reports.write_top_candidate_dump,
    "_apply_capital_flow_to_leg": _runtime_runner._apply_capital_flow_to_leg,
    "_compute_chain_leg_budget": _runtime_runner._compute_chain_leg_budget,
    "_resolve_budget_split_cfg": _runtime_runner._resolve_budget_split_cfg,
    "_resolve_capital_flow_cfg": _runtime_runner._resolve_capital_flow_cfg,
    "_resolve_route_profiles_cfg": _runtime_runner._resolve_route_profiles_cfg,
    "_resolve_route_wide_scan_cfg": _runtime_runner._resolve_route_wide_scan_cfg,
    "build_adjacent_pairs": _runtime_runner.build_adjacent_pairs,
    "build_route_profiles": _runtime_runner.build_route_profiles,
    "build_route_wide_pairs": _runtime_runner.build_route_wide_pairs,
    "enforce_route_destination": _runtime_runner.enforce_route_destination,
    "evaluate_leg_disabled": _runtime_runner.evaluate_leg_disabled,
    "main": _runtime_runner.main,
    "run_cli": _runtime_runner.run_cli,
    "make_skipped_chain_leg": _runtime_runner.make_skipped_chain_leg,
    "run_route": _runtime_runner.run_route,
    "run_route_wide_leg": _runtime_runner.run_route_wide_leg,
    "run_snapshot_only": _runtime_runner.run_snapshot_only,
    "apply_strategy_mode": _scoring.apply_strategy_mode,
    "compute_volatility_score": _scoring.compute_volatility_score,
    "_extract_shipping_lane_params": _shipping._extract_shipping_lane_params,
    "_lane_has_complete_pricing_params": _shipping._lane_has_complete_pricing_params,
    "_lane_provider_from_cfg": _shipping._lane_provider_from_cfg,
    "_match_shipping_lanes": _shipping._match_shipping_lanes,
    "_pick_passes_profit_floors": _shipping._pick_passes_profit_floors,
    "_policy_provider_for_route": _shipping._policy_provider_for_route,
    "apply_route_costs_and_prune": _shipping.apply_route_costs_and_prune,
    "apply_route_costs_to_picks": _shipping.apply_route_costs_to_picks,
    "build_jita_split_price_map": _shipping.build_jita_split_price_map,
    "build_route_context": _shipping.build_route_context,
    "compute_jita_split_price": _shipping.compute_jita_split_price,
    "compute_shipping_lane_reward_cost": _shipping.compute_shipping_lane_reward_cost,
    "compute_shipping_lane_reward_cost_single": _shipping.compute_shipping_lane_reward_cost_single,
    "compute_shipping_lane_total_cost": _shipping.compute_shipping_lane_total_cost,
    "resolve_route_cost_cfg": _shipping.resolve_route_cost_cfg,
    "resolve_shipping_lane_cfg": _shipping.resolve_shipping_lane_cfg,
    "split_shipping_contracts": _shipping.split_shipping_contracts,
    "_build_structure_context": _startup_helpers._build_structure_context,
    "_node_source_dest_info": _startup_helpers._node_source_dest_info,
    "_normalize_route_mode": _startup_helpers._normalize_route_mode,
    "_resolve_chain_runtime": _startup_helpers._resolve_chain_runtime,
    "_resolve_location_nodes": _startup_helpers._resolve_location_nodes,
    "_resolve_node_catalog": _startup_helpers._resolve_node_catalog,
    "_resolve_primary_structure_ids": _startup_helpers._resolve_primary_structure_ids,
}

globals().update(_EXPORTS)

__all__ = list(_EXPORTS.keys())


if __name__ == "__main__":
    _runtime_runner.run_cli()
