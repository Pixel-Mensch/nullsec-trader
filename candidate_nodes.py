from __future__ import annotations

from location_utils import normalize_location_label

CANDIDATE_NODE_KINDS = (
    "station_candidate",
    "market_candidate",
    "corridor_checkpoint",
)

_ROLE_ORDER = {
    "start": 0,
    "end": 1,
    "corridor": 2,
}


def _normalized_tokens(raw_label: str, raw_aliases: list[str] | None = None) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in [raw_label, *list(raw_aliases or [])]:
        txt = str(raw or "").strip()
        if not txt:
            continue
        token = normalize_location_label(txt)
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def resolve_candidate_nodes_cfg(cfg: dict) -> dict:
    raw_cfg = cfg.get("candidate_nodes", {}) if isinstance(cfg, dict) else {}
    if not isinstance(raw_cfg, dict):
        raw_cfg = {}
    raw_nodes = raw_cfg.get("nodes", [])
    nodes: list[dict] = []
    if isinstance(raw_nodes, list):
        for idx, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, dict):
                continue
            label = str(raw_node.get("label", raw_node.get("system", "")) or "").strip()
            kind = str(raw_node.get("kind", raw_node.get("node_type", "")) or "").strip().lower()
            aliases_raw = raw_node.get("aliases", [])
            aliases = [str(alias or "").strip() for alias in list(aliases_raw or []) if str(alias or "").strip()] if isinstance(aliases_raw, list) else []
            tokens = _normalized_tokens(label, aliases)
            if not label or kind not in CANDIDATE_NODE_KINDS or not tokens:
                continue
            nodes.append(
                {
                    "label": label,
                    "kind": kind,
                    "enabled": bool(raw_node.get("enabled", True)),
                    "aliases": aliases,
                    "note": str(raw_node.get("note", "") or "").strip(),
                    "sort_order": int(raw_node.get("sort_order", idx) or idx),
                    "match_tokens": tokens,
                }
            )
    return {
        "enabled": bool(raw_cfg.get("enabled", False)),
        "nodes": [node for node in nodes if bool(node.get("enabled", False))],
    }


def _route_token_sets(route: dict) -> tuple[set[str], set[str], set[str]]:
    start_tokens: set[str] = set()
    end_tokens: set[str] = set()
    corridor_tokens: set[str] = set()

    for raw in (
        route.get("source_label", ""),
        route.get("source_market", ""),
        route.get("travel_source_system", ""),
    ):
        token = normalize_location_label(str(raw or "").strip())
        if token:
            start_tokens.add(token)

    for raw in (
        route.get("dest_label", ""),
        route.get("target_market", ""),
        route.get("travel_dest_system", ""),
    ):
        token = normalize_location_label(str(raw or "").strip())
        if token:
            end_tokens.add(token)

    travel_legs = route.get("travel_path_legs", [])
    if isinstance(travel_legs, list):
        for leg in travel_legs:
            if not isinstance(leg, dict):
                continue
            for raw in (leg.get("from_system", ""), leg.get("to_system", "")):
                token = normalize_location_label(str(raw or "").strip())
                if token:
                    corridor_tokens.add(token)

    corridor_tokens.difference_update(start_tokens)
    corridor_tokens.difference_update(end_tokens)
    return start_tokens, end_tokens, corridor_tokens


def _candidate_hit_summary(hit: dict) -> str:
    role = str(hit.get("match_role", "") or "").strip()
    label = str(hit.get("label", "") or "").strip()
    kind = str(hit.get("kind", "") or "").strip()
    if not role or not label or not kind:
        return ""
    return f"{role} {label} [{kind}]"


def annotate_route_candidate_nodes(route: dict, cfg: dict) -> dict:
    resolved = resolve_candidate_nodes_cfg(cfg)
    if not bool(resolved.get("enabled", False)):
        return {"candidate_nodes": [], "candidate_node_summary": ""}

    start_tokens, end_tokens, corridor_tokens = _route_token_sets(route)
    hits: list[dict] = []
    for node in list(resolved.get("nodes", []) or []):
        if not isinstance(node, dict):
            continue
        tokens = set(str(token or "").strip() for token in list(node.get("match_tokens", []) or []) if str(token or "").strip())
        if not tokens:
            continue
        roles: list[str] = []
        if start_tokens & tokens:
            roles.append("start")
        if end_tokens & tokens:
            roles.append("end")
        if corridor_tokens & tokens:
            roles.append("corridor")
        for role in roles:
            hits.append(
                {
                    "label": str(node.get("label", "") or ""),
                    "kind": str(node.get("kind", "") or ""),
                    "match_role": role,
                    "note": str(node.get("note", "") or ""),
                    "sort_order": int(node.get("sort_order", 0) or 0),
                }
            )

    hits.sort(key=lambda item: (_ROLE_ORDER.get(str(item.get("match_role", "") or ""), 99), int(item.get("sort_order", 0) or 0), str(item.get("label", "") or "").lower()))
    summary = " | ".join(part for part in (_candidate_hit_summary(hit) for hit in hits) if part)
    sanitized_hits = [
        {
            "label": str(hit.get("label", "") or ""),
            "kind": str(hit.get("kind", "") or ""),
            "match_role": str(hit.get("match_role", "") or ""),
            "note": str(hit.get("note", "") or ""),
        }
        for hit in hits
    ]
    return {
        "candidate_nodes": sanitized_hits,
        "candidate_node_summary": summary,
    }


__all__ = [
    "CANDIDATE_NODE_KINDS",
    "annotate_route_candidate_nodes",
    "resolve_candidate_nodes_cfg",
]
