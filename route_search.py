from shipping import (
    _policy_provider_for_route,
    resolve_shipping_lane_cfg,
)
from location_utils import label_to_slug, normalize_location_label


def _resolve_route_search_cfg(cfg: dict) -> dict:
    raw = cfg.get("route_search", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "max_routes": max(1, int(raw.get("max_routes", 10) or 10)),
        "ranking_metric": str(raw.get("ranking_metric", "profit_total") or "profit_total").strip().lower(),
        "allow_all_structures_internal": bool(raw.get("allow_all_structures_internal", True)),
        "allow_shipping_lanes": bool(raw.get("allow_shipping_lanes", True)),
        "allowed_pairs": list(raw.get("allowed_pairs", [])) if isinstance(raw.get("allowed_pairs", []), list) else [],
    }


def _parse_route_pair_token(token: str) -> tuple[str, str] | None:
    txt = str(token or "").strip()
    if not txt:
        return None
    sep = "->" if "->" in txt else (":" if ":" in txt else None)
    if sep is None:
        return None
    parts = [p.strip() for p in txt.split(sep, 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return normalize_location_label(parts[0]), normalize_location_label(parts[1])


def _resolve_allowed_route_pairs(cfg: dict) -> set[tuple[str, str]]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    raw_pairs = rs_cfg.get("allowed_pairs", [])
    out: set[tuple[str, str]] = set()
    for raw in raw_pairs:
        if isinstance(raw, str):
            parsed = _parse_route_pair_token(raw)
            if parsed is not None:
                out.add(parsed)
            continue
        if isinstance(raw, dict):
            src = normalize_location_label(str(raw.get("from", "")))
            dst = normalize_location_label(str(raw.get("to", "")))
            if src and dst:
                out.add((src, dst))
    return out


def _resolve_allowed_route_pair_lane_overrides(cfg: dict) -> dict[tuple[str, str], str]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    raw_pairs = rs_cfg.get("allowed_pairs", [])
    out: dict[tuple[str, str], str] = {}
    for raw in raw_pairs:
        if not isinstance(raw, dict):
            continue
        src = normalize_location_label(str(raw.get("from", "")))
        dst = normalize_location_label(str(raw.get("to", "")))
        lane_id = str(raw.get("shipping_lane_id", raw.get("shipping_lane", "")) or "").strip()
        if src and dst and lane_id:
            out[(src, dst)] = lane_id
    return out


def _normalize_node_for_search(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        nid = int(raw.get("id", 0) or 0)
    except Exception:
        nid = 0
    label = str(raw.get("label", "")).strip()
    if nid <= 0 or not label:
        return None
    node = dict(raw)
    node["id"] = int(nid)
    node["label"] = label
    node["kind"] = str(raw.get("kind", "structure") or "structure")
    node["_label_norm"] = normalize_location_label(label)
    return node


def _collect_preferred_label_tokens(cfg: dict) -> set[str]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    raw_pairs = rs_cfg.get("allowed_pairs", [])
    out: set[str] = set()
    for raw in raw_pairs:
        if isinstance(raw, str):
            parsed = _parse_route_pair_token(raw)
            if parsed is not None:
                out.add(str(parsed[0]))
                out.add(str(parsed[1]))
            continue
        if not isinstance(raw, dict):
            continue
        src = normalize_location_label(str(raw.get("from", "")))
        dst = normalize_location_label(str(raw.get("to", "")))
        if src:
            out.add(src)
        if dst:
            out.add(dst)
    return out


def _node_preference_key(node: dict, preferred_labels: set[str]) -> tuple:
    label = str(node.get("label", ""))
    norm = str(node.get("_label_norm", "") or "")
    kind = str(node.get("kind", "structure") or "structure").lower()
    return (
        0 if norm in preferred_labels else 1,
        0 if kind == "location" else 1,
        len(norm) if norm else len(label),
        len(label),
        label.lower(),
    )


def _build_label_to_node_ids(nodes: list[dict]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for n in nodes:
        norm = str(n.get("_label_norm", "") or "")
        nid = int(n.get("id", 0) or 0)
        if not norm or nid <= 0:
            continue
        bucket = out.setdefault(norm, set())
        bucket.add(nid)
    return out


def _expand_allowed_pairs_to_node_ids(
    allowed_pairs: set[tuple[str, str]],
    label_to_node_ids: dict[str, set[int]],
) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for src_norm, dst_norm in allowed_pairs:
        src_ids = set(label_to_node_ids.get(str(src_norm), set()))
        dst_ids = set(label_to_node_ids.get(str(dst_norm), set()))
        for sid in src_ids:
            for did in dst_ids:
                if sid > 0 and did > 0 and sid != did:
                    out.add((int(sid), int(did)))
    return out


def _expand_lane_overrides_to_node_ids(
    lane_overrides: dict[tuple[str, str], str],
    label_to_node_ids: dict[str, set[int]],
) -> dict[tuple[int, int], str]:
    out: dict[tuple[int, int], str] = {}
    for key, lane_id in lane_overrides.items():
        src_norm, dst_norm = key
        src_ids = set(label_to_node_ids.get(str(src_norm), set()))
        dst_ids = set(label_to_node_ids.get(str(dst_norm), set()))
        for sid in src_ids:
            for did in dst_ids:
                if sid > 0 and did > 0 and sid != did:
                    out[(int(sid), int(did))] = str(lane_id)
    return out


def _dedupe_nodes_by_id(nodes: list[dict], preferred_labels: set[str]) -> list[dict]:
    by_id: dict[int, dict] = {}
    aliases_by_id: dict[int, set[str]] = {}
    for node in nodes:
        nid = int(node.get("id", 0) or 0)
        if nid <= 0:
            continue
        aliases_by_id.setdefault(nid, set()).add(str(node.get("label", "")))
        prev = by_id.get(nid)
        if prev is None:
            by_id[nid] = dict(node)
            continue
        if _node_preference_key(node, preferred_labels) < _node_preference_key(prev, preferred_labels):
            by_id[nid] = dict(node)
    out: list[dict] = []
    for nid in sorted(by_id.keys()):
        chosen = dict(by_id[nid])
        aliases = sorted(a for a in aliases_by_id.get(nid, set()) if a)
        if aliases:
            chosen["aliases"] = aliases
        out.append(chosen)
    return out


def build_route_search_profiles(node_catalog: dict[str, dict], cfg: dict) -> list[dict]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    if not bool(rs_cfg.get("enabled", False)):
        return []
    raw_nodes: list[dict] = []
    for _, n in sorted(node_catalog.items(), key=lambda kv: kv[0]):
        node = _normalize_node_for_search(n)
        if node is not None:
            raw_nodes.append(node)
    preferred_labels = _collect_preferred_label_tokens(cfg)
    nodes = _dedupe_nodes_by_id(raw_nodes, preferred_labels)
    allowed_explicit = _resolve_allowed_route_pairs(cfg)
    allowed_lane_overrides = _resolve_allowed_route_pair_lane_overrides(cfg)
    label_to_node_ids = _build_label_to_node_ids(raw_nodes)
    allowed_explicit_ids = _expand_allowed_pairs_to_node_ids(allowed_explicit, label_to_node_ids)
    allowed_lane_overrides_ids = _expand_lane_overrides_to_node_ids(allowed_lane_overrides, label_to_node_ids)
    allow_struct_internal = bool(rs_cfg.get("allow_all_structures_internal", True))
    allow_shipping = bool(rs_cfg.get("allow_shipping_lanes", True))

    pairs: list[tuple[dict, dict, str]] = []
    seen: set[tuple[int, int]] = set()
    for src in nodes:
        for dst in nodes:
            src_norm = normalize_location_label(str(src.get("label", "")))
            dst_norm = normalize_location_label(str(dst.get("label", "")))
            if not src_norm or not dst_norm or src_norm == dst_norm:
                continue
            src_id = int(src.get("id", 0) or 0)
            dst_id = int(dst.get("id", 0) or 0)
            if src_id == dst_id:
                continue
            pair_key = (src_id, dst_id)
            if pair_key in seen:
                continue
            allowed = False
            selected_lane_id = str(allowed_lane_overrides_ids.get(pair_key, "") or "")
            lane_match = resolve_shipping_lane_cfg(
                cfg,
                str(src.get("label", "")),
                str(dst.get("label", "")),
                source_id=src_id,
                dest_id=dst_id,
                preferred_lane_id=selected_lane_id,
            )
            if allow_struct_internal and str(src.get("kind", "structure")) == "structure" and str(dst.get("kind", "structure")) == "structure":
                allowed = True
            if allow_shipping and _policy_provider_for_route(str(src.get("label", "")), str(dst.get("label", ""))) and lane_match is not None:
                allowed = True
            if pair_key in allowed_explicit_ids:
                allowed = True
            if not allowed:
                continue
            seen.add(pair_key)
            pairs.append((src, dst, str(lane_match[0]) if lane_match is not None else selected_lane_id))

    out: list[dict] = []
    for idx, (src, dst, lane_id) in enumerate(pairs, start=1):
        out.append({
            "id": f"search_{label_to_slug(str(src.get('label', '')))}_to_{label_to_slug(str(dst.get('label', '')))}_{idx}",
            "from": str(src.get("label", "")),
            "to": str(dst.get("label", "")),
            "mode": "",
            "shipping_lane_id": str(lane_id or ""),
            "search_generated": True,
        })
    return out
