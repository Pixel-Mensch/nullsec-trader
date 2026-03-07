from __future__ import annotations

from location_utils import normalize_location_label


def _normalize_route_mode(route_mode_raw: str) -> str:
    route_mode = str(route_mode_raw or "roundtrip").lower()
    if route_mode not in ("roundtrip", "forward_only"):
        return "roundtrip"
    return route_mode


def _resolve_chain_runtime(cfg: dict, o4t_id: int, cj6_id: int) -> dict:
    chain_cfg = cfg.get("route_chain", {})
    chain_enabled = bool(chain_cfg.get("enabled", False))
    chain_nodes: list[dict] = []

    legs_cfg = chain_cfg.get("legs", [])
    if isinstance(legs_cfg, list) and legs_cfg:
        seen_chain_ids: set[int] = set()
        invalid_reason = ""
        for idx, n in enumerate(legs_cfg):
            if not isinstance(n, dict):
                invalid_reason = f"route_chain.legs[{idx}] ist kein Objekt"
                break
            sid_raw = n.get("id", 0)
            label_raw = n.get("label", f"SID_{sid_raw}")
            region_raw = n.get("region_id", 0)
            try:
                sid = int(sid_raw)
            except Exception:
                sid = 0
            try:
                rid = int(region_raw or 0)
            except Exception:
                rid = 0
            label = str(label_raw).strip()
            if sid <= 0:
                invalid_reason = f"route_chain.legs[{idx}].id ist ungueltig"
                break
            if sid in seen_chain_ids:
                invalid_reason = f"route_chain.legs[{idx}].id ist doppelt ({sid})"
                break
            if not label:
                invalid_reason = f"route_chain.legs[{idx}].label fehlt"
                break
            seen_chain_ids.add(sid)
            node = {"id": sid, "label": label}
            if rid > 0:
                node["region_id"] = rid
            chain_nodes.append(node)
        if invalid_reason:
            print(f"WARN: {invalid_reason}. Fallback auf non-chain.")
            chain_enabled = False
            chain_nodes = []
        elif len(chain_nodes) < 2:
            print("WARN: route_chain.legs braucht mindestens 2 Stationen. Fallback auf non-chain.")
            chain_enabled = False
            chain_nodes = []
    elif chain_enabled:
        middle_id = int(chain_cfg.get("middle_structure_id", 0) or 0)
        middle_label = str(chain_cfg.get("middle_label", "R-ARKN"))
        if middle_id > 0:
            chain_nodes = [
                {"id": int(o4t_id), "label": "O4T"},
                {"id": int(middle_id), "label": middle_label},
                {"id": int(cj6_id), "label": "CJ6"},
            ]
        else:
            print("WARN: route_chain.enabled=true aber weder legs noch middle_structure_id gueltig. Fallback auf non-chain.")
            chain_enabled = False
            chain_nodes = []

    fallback_to_non_chain_on_middle_failure = bool(chain_cfg.get("fallback_to_non_chain_on_middle_failure", False))
    fallback_to_non_chain_on_invalid_route = bool(chain_cfg.get("fallback_to_non_chain_on_invalid_route", False))
    chain_leg_budget_util_min_pct = float(cfg.get("chain_leg_budget_util_min_pct", chain_cfg.get("chain_leg_budget_util_min_pct", 0.5)))
    chain_return_mode = str(cfg.get("chain_return_mode", chain_cfg.get("chain_return_mode", "off"))).lower()
    if chain_return_mode not in ("off", "instant", "fast_sell"):
        chain_return_mode = "off"
    chain_return_overrides = cfg.get("filters_chain_return", {})
    if not isinstance(chain_return_overrides, dict):
        chain_return_overrides = {}

    if chain_enabled and len(chain_nodes) < 2:
        print("WARN: Chain-Route ungueltig. Fallback auf non-chain.")
        chain_enabled = False

    return {
        "chain_enabled": chain_enabled,
        "chain_nodes": chain_nodes,
        "fallback_to_non_chain_on_middle_failure": fallback_to_non_chain_on_middle_failure,
        "fallback_to_non_chain_on_invalid_route": fallback_to_non_chain_on_invalid_route,
        "chain_leg_budget_util_min_pct": chain_leg_budget_util_min_pct,
        "chain_return_mode": chain_return_mode,
        "chain_return_overrides": chain_return_overrides,
    }


def _build_structure_context(o4t_id: int, cj6_id: int, chain_enabled: bool, chain_nodes: list[dict]) -> tuple[dict[int, str], set[int]]:
    structure_labels: dict[int, str] = {
        int(o4t_id): "O4T",
        int(cj6_id): "CJ6",
    }
    if chain_enabled:
        for n in chain_nodes:
            structure_labels[int(n["id"])] = str(n["label"])

    required_structure_ids: set[int] = {int(o4t_id), int(cj6_id)}
    if chain_enabled:
        required_structure_ids = {int(n["id"]) for n in chain_nodes}
    return structure_labels, required_structure_ids


def _resolve_location_nodes(cfg: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    out["jita_44"] = {
        "label": "jita_44",
        "id": 60003760,
        "kind": "location",
        "location_id": 60003760,
        "region_id": 10000002,
    }
    loc_cfg = cfg.get("locations", {})
    if not isinstance(loc_cfg, dict):
        return out
    for label_raw, raw in loc_cfg.items():
        label = str(label_raw).strip()
        if not label:
            continue
        rid = 0
        lid = 0
        if isinstance(raw, dict):
            try:
                lid = int(raw.get("location_id", 0) or 0)
            except Exception:
                lid = 0
            try:
                rid = int(raw.get("region_id", 0) or 0)
            except Exception:
                rid = 0
        else:
            try:
                lid = int(raw)
            except Exception:
                lid = 0
        if lid <= 0:
            continue
        out[str(label)] = {
            "label": str(label),
            "id": int(lid),
            "kind": "location",
            "location_id": int(lid),
            "region_id": int(rid),
        }
    return out


def _resolve_node_catalog(cfg: dict, chain_nodes: list[dict]) -> dict[str, dict]:
    by_label: dict[str, dict] = {}
    structures_cfg = cfg.get("structures", {})
    if isinstance(structures_cfg, dict):
        for label_raw, raw in structures_cfg.items():
            label = str(label_raw).strip()
            if not label:
                continue
            sid = 0
            rid = 0
            if isinstance(raw, dict):
                try:
                    sid = int(raw.get("id", 0) or 0)
                except Exception:
                    sid = 0
                try:
                    rid = int(raw.get("region_id", 0) or 0)
                except Exception:
                    rid = 0
            else:
                try:
                    sid = int(raw)
                except Exception:
                    sid = 0
            if sid <= 0:
                continue
            by_label[normalize_location_label(label)] = {
                "label": label,
                "id": sid,
                "kind": "structure",
                "structure_id": sid,
                "region_id": rid,
            }
    for n in chain_nodes:
        label = str(n.get("label", "")).strip()
        if not label:
            continue
        sid = int(n.get("id", 0) or 0)
        node = {
            "label": label,
            "id": sid,
            "kind": "structure",
            "structure_id": sid,
            "region_id": int(n.get("region_id", 0) or 0),
        }
        by_label[normalize_location_label(label)] = node
    for label, raw in _resolve_location_nodes(cfg).items():
        by_label[normalize_location_label(label)] = dict(raw)
    return by_label


def _node_source_dest_info(node: dict | None) -> dict:
    if not isinstance(node, dict):
        return {}
    kind = str(node.get("kind", "structure"))
    info = {
        "node_label": str(node.get("label", "")),
        "node_kind": kind,
        "node_id": int(node.get("id", 0) or 0),
        "node_region_id": int(node.get("region_id", 0) or 0),
    }
    if kind == "location":
        info["location_id"] = int(node.get("location_id", node.get("id", 0)) or 0)
    else:
        info["structure_id"] = int(node.get("structure_id", node.get("id", 0)) or 0)
    return info


def _resolve_primary_structure_ids(cfg: dict) -> tuple[int, int]:
    structures = cfg.get("structures", {})
    if not isinstance(structures, dict):
        raise SystemExit("config.structures fehlt oder ist ungueltig.")

    def _read_sid(v, key_name: str) -> int:
        if isinstance(v, dict):
            raw = v.get("id", 0)
        else:
            raw = v
        try:
            sid = int(raw)
        except Exception:
            sid = 0
        if sid <= 0:
            raise SystemExit(f"config.structures.{key_name} ist ungueltig.")
        return sid

    if "o4t" not in structures or "cj6" not in structures:
        raise SystemExit("config.structures muss mindestens o4t und cj6 enthalten.")

    return _read_sid(structures["o4t"], "o4t"), _read_sid(structures["cj6"], "cj6")


__all__ = [
    "_normalize_route_mode",
    "_resolve_chain_runtime",
    "_build_structure_context",
    "_resolve_location_nodes",
    "_resolve_node_catalog",
    "_node_source_dest_info",
    "_resolve_primary_structure_ids",
]
