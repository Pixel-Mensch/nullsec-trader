"""Route Search tests."""

from tests.shared import *  # noqa: F401,F403
from route_search import summarize_route_for_ranking

def test_build_adjacent_pairs_forward() -> None:
    chain_nodes = [
        {"id": 1, "label": "O4T"},
        {"id": 2, "label": "R-ARKN"},
        {"id": 3, "label": "UALX-3"},
        {"id": 4, "label": "1st Taj Mahgoon"},
    ]
    pairs = nst.build_adjacent_pairs(chain_nodes, reverse=False)
    labels = [(src["label"], dst["label"]) for src, dst in pairs]
    assert labels == [
        ("O4T", "R-ARKN"),
        ("R-ARKN", "UALX-3"),
        ("UALX-3", "1st Taj Mahgoon"),
    ], f"Unexpected forward pairs: {labels}"

def test_build_adjacent_pairs_reverse() -> None:
    chain_nodes = [
        {"id": 1, "label": "O4T"},
        {"id": 2, "label": "R-ARKN"},
        {"id": 3, "label": "UALX-3"},
        {"id": 4, "label": "1st Taj Mahgoon"},
    ]
    pairs = nst.build_adjacent_pairs(chain_nodes, reverse=True)
    labels = [(src["label"], dst["label"]) for src, dst in pairs]
    assert labels == [
        ("1st Taj Mahgoon", "UALX-3"),
        ("UALX-3", "R-ARKN"),
        ("R-ARKN", "O4T"),
    ], f"Unexpected reverse pairs: {labels}"

def test_build_route_wide_pairs_forward() -> None:
    chain_nodes = [
        {"id": 1, "label": "O4T"},
        {"id": 2, "label": "R-ARKN"},
        {"id": 3, "label": "UALX-3"},
        {"id": 4, "label": "1st Taj Mahgoon"},
    ]
    pairs = nst.build_route_wide_pairs(chain_nodes, reverse=False, max_hops=99)
    labels = [(p["src_label"], p["dst_label"], p["hop_count"]) for p in pairs]
    assert labels == [
        ("O4T", "R-ARKN", 1),
        ("O4T", "UALX-3", 2),
        ("O4T", "1st Taj Mahgoon", 3),
        ("R-ARKN", "UALX-3", 1),
        ("R-ARKN", "1st Taj Mahgoon", 2),
        ("UALX-3", "1st Taj Mahgoon", 1),
    ]

def test_build_route_profiles_generates_separate_routes() -> None:
    chain_nodes = [
        {"id": 1, "label": "O4T"},
        {"id": 2, "label": "R-ARKN"},
        {"id": 3, "label": "UALX-3"},
    ]
    cfg = {
        "route_profiles": {
            "enabled": True,
            "include_forward_pairs": True,
            "include_reverse_pairs": True,
            "max_hops": 99,
        }
    }
    profiles = nst.build_route_profiles(chain_nodes, cfg)
    pairs = {(p["from"], p["to"]) for p in profiles}
    assert ("O4T", "UALX-3") in pairs
    assert ("UALX-3", "O4T") in pairs
    assert ("O4T", "R-ARKN") in pairs
    assert ("R-ARKN", "UALX-3") in pairs

def test_enforce_route_destination_filters_cross_destination_picks() -> None:
    picks = [
        {"type_id": 1, "sell_at": "UALX-3"},
        {"type_id": 2, "sell_at": "1st Taj Mahgoon"},
        {"type_id": 3, "sell_at": "UALX-3"},
    ]
    out = nst.enforce_route_destination(picks, "UALX-3")
    assert [int(p["type_id"]) for p in out] == [1, 3]

def test_route_search_pair_generation_respects_policy() -> None:
    node_catalog = {
        "o4t": {"label": "o4t", "id": 1, "kind": "structure"},
        "ra": {"label": "ra", "id": 2, "kind": "structure"},
        "jita_44": {"label": "jita_44", "id": 60003760, "kind": "location", "location_id": 60003760, "region_id": 10000002},
    }
    cfg = {
        "route_search": {
            "enabled": True,
            "allow_all_structures_internal": True,
            "allow_shipping_lanes": True,
            "allowed_pairs": [],
        },
        "shipping_lanes": {
            "hwl_jita_o4t": {
                "enabled": True,
                "from_location_id": 60003760,
                "to_structure_id": 1,
                "from": "jita_44",
                "to": "o4t",
                "pricing_model": "hwl_volume_plus_value",
                "per_m3_rate": 1000.0,
                "additional_collateral_rate": 0.01,
                "minimum_reward": 1_000_000.0,
            },
            "itl_jita_ra": {
                "enabled": True,
                "from_location_id": 60003760,
                "to_structure_id": 2,
                "from": "jita_44",
                "to": "ra",
                "pricing_model": "itl_max",
                "per_m3_rate": 100.0,
                "minimum_reward": 1_000_000.0,
                "full_load_reward": 100_000_000.0,
            },
        }
    }
    profiles = nst.build_route_search_profiles(node_catalog, cfg)
    pairs = {(p["from"], p["to"]) for p in profiles}
    assert ("jita_44", "o4t") in pairs
    assert ("jita_44", "ra") not in pairs
    assert ("o4t", "ra") in pairs

def test_route_search_allowed_pairs_can_whitelist_non_policy_pair() -> None:
    node_catalog = {
        "o4t": {"label": "o4t", "id": 1, "kind": "structure"},
        "jita_44": {"label": "jita_44", "id": 60003760, "kind": "location", "location_id": 60003760, "region_id": 10000002},
    }
    cfg = {
        "route_search": {
            "enabled": True,
            "allow_all_structures_internal": False,
            "allow_shipping_lanes": False,
            "allowed_pairs": ["jita_44->o4t"],
        },
        "shipping_lanes": {},
    }
    profiles = nst.build_route_search_profiles(node_catalog, cfg)
    pairs = {(p["from"], p["to"]) for p in profiles}
    assert pairs == {("jita_44", "o4t")}

def test_route_search_skips_pairs_with_same_node_id() -> None:
    node_catalog = {
        "a": {"label": "A", "id": 111, "kind": "structure"},
        "a_alias": {"label": "A Alias", "id": 111, "kind": "structure"},
        "b": {"label": "B", "id": 222, "kind": "structure"},
    }
    cfg = {
        "route_search": {
            "enabled": True,
            "allow_all_structures_internal": True,
            "allow_shipping_lanes": False,
            "allowed_pairs": [],
        },
        "shipping_lanes": {},
    }
    profiles = nst.build_route_search_profiles(node_catalog, cfg)
    pairs = {(p["from"], p["to"]) for p in profiles}
    assert ("A", "A Alias") not in pairs
    assert ("A Alias", "A") not in pairs
    assert ("A", "B") in pairs
    assert ("A Alias", "B") not in pairs
    assert ("B", "A") in pairs

def test_route_search_prefers_allowed_pair_alias_for_deduped_node() -> None:
    node_catalog = {
        "a": {"label": "A", "id": 111, "kind": "structure"},
        "a_alias": {"label": "A Alias", "id": 111, "kind": "structure"},
        "b": {"label": "B", "id": 222, "kind": "structure"},
    }
    cfg = {
        "route_search": {
            "enabled": True,
            "allow_all_structures_internal": False,
            "allow_shipping_lanes": False,
            "allowed_pairs": [{"from": "A Alias", "to": "B"}],
        },
        "shipping_lanes": {},
    }
    profiles = nst.build_route_search_profiles(node_catalog, cfg)
    pairs = {(p["from"], p["to"]) for p in profiles}
    assert pairs == {("A Alias", "B")}


def test_route_summary_confidence_is_capped_by_pick_market_quality() -> None:
    route = {
        "route_label": "A->B",
        "picks": [
            {
                "expected_realized_profit_90d": 10_000_000.0,
                "decision_overall_confidence": 0.88,
                "overall_confidence": 0.88,
                "expected_days_to_sell": 2.0,
                "market_quality_score": 0.46,
            }
        ],
        "cost_model_confidence": "normal",
    }

    summary = summarize_route_for_ranking(route)
    assert abs(float(summary["market_quality_factor"]) - 0.46) < 1e-9
    assert abs(float(summary["route_confidence"]) - 0.46) < 1e-9


def test_route_summary_keeps_healthy_market_quality_routes_actionable() -> None:
    route = {
        "route_label": "A->B",
        "picks": [
            {
                "expected_realized_profit_90d": 12_000_000.0,
                "decision_overall_confidence": 0.86,
                "overall_confidence": 0.86,
                "expected_days_to_sell": 1.5,
                "market_quality_score": 0.77,
            }
        ],
        "cost_model_confidence": "high",
    }

    summary = summarize_route_for_ranking(route)
    assert abs(float(summary["market_quality_factor"]) - 0.77) < 1e-9
    assert abs(float(summary["route_confidence"]) - 0.77) < 1e-9
    assert bool(summary["actionable"]) is True

def test_route_leaderboard_top_n_sorted() -> None:
    routes = [
        {"route_label": "A->B", "source_label": "A", "dest_label": "B", "shipping_provider": "ITL", "profit_total": 10_000_000.0, "isk_used": 50_000_000.0, "m3_used": 1000.0, "net_revenue_total": 60_000_000.0, "total_fees_taxes": 1_000_000.0, "total_route_cost": 500_000.0, "shipping_cost_total": 200_000.0, "items_count": 3, "budget_util_pct": 50.0, "cargo_util_pct": 20.0, "picks": [{"profit": 6_500_000.0}, {"profit": 2_000_000.0}, {"profit": 1_500_000.0}]},
        {"route_label": "C->D", "source_label": "C", "dest_label": "D", "shipping_provider": "HWL", "profit_total": 30_000_000.0, "isk_used": 60_000_000.0, "m3_used": 2000.0, "net_revenue_total": 90_000_000.0, "total_fees_taxes": 2_000_000.0, "total_route_cost": 700_000.0, "shipping_cost_total": 400_000.0, "items_count": 4, "budget_util_pct": 60.0, "cargo_util_pct": 40.0, "picks": [{"profit": 12_000_000.0}, {"profit": 9_000_000.0}, {"profit": 6_000_000.0}, {"profit": 3_000_000.0}]},
        {"route_label": "E->F", "source_label": "E", "dest_label": "F", "shipping_provider": "ITL", "profit_total": 20_000_000.0, "isk_used": 40_000_000.0, "m3_used": 1500.0, "net_revenue_total": 70_000_000.0, "total_fees_taxes": 1_500_000.0, "total_route_cost": 600_000.0, "shipping_cost_total": 300_000.0, "items_count": 2, "budget_util_pct": 40.0, "cargo_util_pct": 30.0, "picks": [{"profit": 14_000_000.0}, {"profit": 6_000_000.0}]},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "route_leaderboard_test.txt")
        nst.write_route_leaderboard(out_path, "2026-03-05_00-00-00", routes, ranking_metric="profit_total", max_routes=2)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "C->D" in content
    assert "E->F" in content
    assert "A->B" not in content
    assert "provider: HWL" in content
    assert "Top3 Profit Share" in content
    assert "Dominance Flag (>60%): YES" in content


def test_route_leaderboard_shows_route_mix_cleanup_note() -> None:
    routes = [
        {
            "route_label": "A->B",
            "source_label": "A",
            "dest_label": "B",
            "shipping_provider": "ITL",
            "profit_total": 10_000_000.0,
            "isk_used": 50_000_000.0,
            "m3_used": 1000.0,
            "net_revenue_total": 60_000_000.0,
            "total_fees_taxes": 1_000_000.0,
            "total_route_cost": 500_000.0,
            "shipping_cost_total": 200_000.0,
            "items_count": 2,
            "budget_util_pct": 50.0,
            "cargo_util_pct": 20.0,
            "route_mix_cleanup_notes": [
                "Removed weak optional add-on pick Noise-5 'Needlejack' Filament: +0.06 route confidence, +0.07 market quality, -3.7% expected profit share."
            ],
            "picks": [
                {"profit": 6_500_000.0, "expected_realized_profit_90d": 6_500_000.0, "decision_overall_confidence": 0.80, "overall_confidence": 0.80, "market_quality_score": 0.80},
                {"profit": 3_500_000.0, "expected_realized_profit_90d": 3_500_000.0, "decision_overall_confidence": 0.78, "overall_confidence": 0.78, "market_quality_score": 0.78},
            ],
            "cost_model_confidence": "normal",
        }
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "route_leaderboard_test.txt")
        nst.write_route_leaderboard(out_path, "2026-03-05_00-00-00", routes, ranking_metric="profit_total", max_routes=1)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "route_mix_cleanup:" in content
    assert "Noise-5 'Needlejack' Filament" in content

def test_route_leaderboard_prunes_blocked_route_from_ranked_section() -> None:
    routes = [
        {
            "route_label": "GOOD",
            "source_label": "A",
            "dest_label": "B",
            "shipping_provider": "ITL",
            "expected_realized_profit_total": 10_000_000.0,
            "full_sell_profit_total": 12_000_000.0,
            "isk_used": 50_000_000.0,
            "m3_used": 1000.0,
            "picks": [{"expected_realized_profit_90d": 10_000_000.0, "overall_confidence": 0.8, "expected_days_to_sell": 10.0}],
            "cost_model_confidence": "normal",
        },
        {
            "route_label": "BLOCKED",
            "source_label": "C",
            "dest_label": "D",
            "route_blocked_due_to_transport": True,
            "route_prune_reason": "missing_transport_cost_model",
            "cost_model_confidence": "blocked",
            "picks": [],
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "route_leaderboard_test.txt")
        nst.write_route_leaderboard(out_path, "2026-03-05_00-00-00", routes, ranking_metric="risk_adjusted_expected_profit", max_routes=5)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "GOOD" in content
    assert "PRUNED / NOT ACTIONABLE" in content
    assert "- BLOCKED: missing_transport_cost_model" in content


def test_route_leaderboard_shows_internal_route_floor_for_suppressed_route() -> None:
    routes = [
        {
            "route_label": "GOOD",
            "source_label": "A",
            "dest_label": "B",
            "shipping_provider": "ITL",
            "expected_realized_profit_total": 10_000_000.0,
            "full_sell_profit_total": 12_000_000.0,
            "isk_used": 50_000_000.0,
            "m3_used": 1000.0,
            "picks": [{"expected_realized_profit_90d": 10_000_000.0, "overall_confidence": 0.8, "expected_days_to_sell": 10.0}],
            "cost_model_confidence": "normal",
        },
        {
            "route_label": "WEAK INTERNAL",
            "source_label": "UALX-3",
            "dest_label": "C-J6MT",
            "transport_mode": "internal_self_haul",
            "route_prune_reason": "internal_route_profit_below_operational_floor",
            "operational_profit_floor_isk": 2_000_000.0,
            "suppressed_expected_realized_profit_total": 1_300_000.0,
            "operational_filter_note": "Internal nullsec routes require at least 2.0m ISK expected realized profit.",
            "picks": [],
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "route_leaderboard_test.txt")
        nst.write_route_leaderboard(out_path, "2026-03-13_00-00-00", routes, ranking_metric="risk_adjusted_expected_profit", max_routes=5)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "WEAK INTERNAL" in content
    assert "internal_route_floor" in content
    assert "suppressed_expected_profit" in content

