from __future__ import annotations

from pathlib import Path

import nullsectrader as nst


def test_resolve_candidate_nodes_cfg_and_route_annotation_keep_roles_separate() -> None:
    cfg = {
        "candidate_nodes": {
            "enabled": True,
            "nodes": [
                {"label": "1DQ1-A", "kind": "market_candidate", "enabled": True},
                {"label": "RE-C26", "kind": "corridor_checkpoint", "enabled": True},
                {"label": "FWST-8", "kind": "station_candidate", "enabled": False},
            ],
        }
    }
    resolved = nst.resolve_candidate_nodes_cfg(cfg)
    assert bool(resolved.get("enabled", False)) is True
    assert [str(node.get("label", "")) for node in list(resolved.get("nodes", []) or [])] == ["1DQ1-A", "RE-C26"]

    route = {
        "source_label": "1DQ1-A",
        "dest_label": "C-J6MT",
        "travel_source_system": "1DQ1-A",
        "travel_dest_system": "C-J6MT",
        "travel_path_legs": [
            {"from_system": "1DQ1-A", "to_system": "RE-C26", "mode": "gate"},
            {"from_system": "RE-C26", "to_system": "C-J6MT", "mode": "gate"},
        ],
    }
    annotation = nst.annotate_route_candidate_nodes(route, cfg)
    hits = list(annotation.get("candidate_nodes", []) or [])
    assert hits == [
        {"label": "1DQ1-A", "kind": "market_candidate", "match_role": "start", "note": ""},
        {"label": "RE-C26", "kind": "corridor_checkpoint", "match_role": "corridor", "note": ""},
    ]
    assert str(annotation.get("candidate_node_summary", "") or "") == "start 1DQ1-A [market_candidate] | corridor RE-C26 [corridor_checkpoint]"


def test_repo_default_candidate_nodes_keep_re_c26_out_of_station_candidates() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = nst.load_json(str(repo_root / "config.json"), {})
    resolved = nst.resolve_candidate_nodes_cfg(cfg)
    nodes = [node for node in list(resolved.get("nodes", []) or []) if str(node.get("label", "") or "") == "RE-C26"]
    assert len(nodes) == 1
    assert str(nodes[0].get("kind", "") or "") == "corridor_checkpoint"
    assert str(nodes[0].get("kind", "") or "") != "station_candidate"
