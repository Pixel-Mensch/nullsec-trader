"""Focused tests for the optional ansiblex corridor layer."""

from tests.shared import *  # noqa: F401,F403


def _ansiblex_cfg(tmpdir: str, raw_lines: list[str]) -> dict:
    file_path = os.path.join(tmpdir, "Ansis.txt")
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(raw_lines))
        handle.write("\n")
    cfg = _minimal_valid_config()
    cfg["structures"] = {"o4t": 1, "cj6": 3}
    cfg["structure_regions"] = {"1": 10000059, "3": 10000009}
    cfg["route_chain"] = {
        "enabled": True,
        "legs": [
            {"id": 1, "label": "A", "system": "A"},
            {"id": 2, "label": "B", "system": "B"},
            {"id": 3, "label": "C", "system": "C"},
        ],
    }
    cfg["ansiblex"] = {
        "enabled": True,
        "file_path": file_path,
        "ship_mass_kg": 200_000_000.0,
        "liquid_ozone_price_isk": 1_000.0,
        "toll_mode": "none",
        "toll_isk_per_ozone": 0.0,
        "fixed_toll_isk_per_jump": 0.0,
    }
    return cfg


def test_parse_ansiblex_line_supports_comments_and_spacing() -> None:
    edge = nst.parse_ansiblex_edge_line("  O4T-Z5  ->  G-M4GK   # outbound bridge  ")
    assert edge is not None
    assert edge["from_system"] == "O4T-Z5"
    assert edge["to_system"] == "G-M4GK"


def test_load_ansiblex_edges_ignores_blank_lines_and_keeps_direction() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _ansiblex_cfg(
            tmpdir,
            [
                "# comment only",
                "",
                "A -> C",
                "  ",
                "C -> B // inline comment",
            ],
        )
        edges = nst.load_ansiblex_edges(cfg["ansiblex"]["file_path"])
    assert [(edge["from_system"], edge["to_system"]) for edge in edges] == [("A", "C"), ("C", "B")]
    assert ("C", "A") not in {(edge["from_system"], edge["to_system"]) for edge in edges}


def test_compute_ansiblex_jump_cost_supports_per_ozone_and_fixed_toll() -> None:
    per_ozone = nst.compute_ansiblex_jump_cost(
        ship_mass_kg=200_000_000.0,
        liquid_ozone_price_isk=1_000.0,
        distance_ly=1.0,
        toll_mode="per_ozone",
        toll_isk_per_ozone=20.0,
    )
    fixed = nst.compute_ansiblex_jump_cost(
        ship_mass_kg=200_000_000.0,
        liquid_ozone_price_isk=1_000.0,
        distance_ly=1.0,
        toll_mode="fixed_per_jump",
        fixed_toll_isk_per_jump=15_000.0,
    )
    assert abs(float(per_ozone["fuel_ozone"]) - 650.0) < 1e-9
    assert abs(float(per_ozone["ansiblex_logistics_cost_isk"]) - 663_000.0) < 1e-9
    assert abs(float(fixed["ansiblex_logistics_cost_isk"]) - 665_000.0) < 1e-9


def test_route_travel_details_prefers_shorter_ansiblex_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _ansiblex_cfg(tmpdir, ["A -> C"])
        details = nst.resolve_route_travel_details(cfg, "A", "C")
    assert details["path_found"] is True
    assert details["used_ansiblex"] is True
    assert int(details["gate_leg_count"]) == 0
    assert int(details["ansiblex_leg_count"]) == 1
    assert str(details["travel_path_legs"][0]["mode"]) == "ansiblex"
    assert "ansiblex leg" in str(details["travel_summary"])


def test_route_travel_details_does_not_infer_reverse_ansiblex_edge() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _ansiblex_cfg(tmpdir, ["A -> C"])
        details = nst.resolve_route_travel_details(cfg, "C", "A")
    assert details["path_found"] is True
    assert details["used_ansiblex"] is False
    assert int(details["gate_leg_count"]) == 2
    assert int(details["ansiblex_leg_count"]) == 0
    assert str(details["travel_summary"]).startswith("Pure gate route")


def test_apply_route_costs_carries_ansiblex_route_metadata_and_cost() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _ansiblex_cfg(tmpdir, ["A -> C"])
        route_context = nst.build_route_context(cfg, "route_a_to_c", "A", "C", source_id=1, dest_id=3)
        picks = [
            {
                "name": "RoutePick",
                "qty": 1,
                "unit_volume": 10.0,
                "cost": 10_000_000.0,
                "revenue_net": 15_000_000.0,
                "profit": 5_000_000.0,
                "gross_profit_if_full_sell": 5_000_000.0,
                "expected_realized_profit_90d": 5_000_000.0,
                "expected_profit_90d": 5_000_000.0,
                "turnover_factor": 1.0,
            }
        ]
        summary = nst.apply_route_costs_to_picks(picks, route_context)
    assert int(summary["gate_leg_count"]) == 0
    assert int(summary["ansiblex_leg_count"]) == 1
    assert bool(summary["used_ansiblex"]) is True
    assert float(summary["ansiblex_logistics_cost_isk"]) > 0.0
    assert abs(float(summary["total_transport_cost"]) - float(summary["ansiblex_logistics_cost_isk"])) < 1e-6
    assert str(summary["travel_path_legs"][0]["mode"]) == "ansiblex"
    assert float(picks[0]["ansiblex_logistics_cost"]) > 0.0
