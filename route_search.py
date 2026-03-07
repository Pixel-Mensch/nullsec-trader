from confidence_calibration import transport_confidence_to_score
from explainability import build_route_explainability
from shipping import (
    _policy_provider_for_route,
    resolve_shipping_lane_cfg,
)
from location_utils import label_to_slug, normalize_location_label


def _confidence_to_score(label: str) -> float:
    return float(transport_confidence_to_score(label))


def _pick_raw_confidence(pick: dict) -> float:
    return max(
        0.0,
        min(
            1.0,
            float(
                pick.get(
                    "raw_overall_confidence",
                    pick.get("raw_confidence", pick.get("overall_confidence", pick.get("strict_confidence_score", pick.get("fill_probability", 0.0)))),
                )
                or 0.0
            ),
        ),
    )


def _pick_calibrated_confidence(pick: dict) -> float:
    return max(
        0.0,
        min(
            1.0,
            float(
                pick.get(
                    "calibrated_overall_confidence",
                    pick.get("calibrated_confidence", pick.get("raw_overall_confidence", pick.get("overall_confidence", pick.get("strict_confidence_score", pick.get("fill_probability", 0.0))))),
                )
                or 0.0
            ),
        ),
    )


def _pick_decision_confidence(pick: dict) -> float:
    return max(
        0.0,
        min(
            1.0,
            float(
                pick.get(
                    "decision_overall_confidence",
                    pick.get("calibrated_overall_confidence", pick.get("overall_confidence", pick.get("strict_confidence_score", pick.get("fill_probability", 0.0)))),
                )
                or 0.0
            ),
        ),
    )


def _route_pick_expected_profit(pick: dict) -> float:
    return float(pick.get("expected_realized_profit_90d", pick.get("expected_profit_90d", pick.get("profit", 0.0))) or 0.0)


def summarize_route_for_ranking(route: dict) -> dict:
    picks = list(route.get("picks", []) or [])
    expected_realized_profit = float(route.get("expected_realized_profit_total", 0.0) or 0.0)
    if expected_realized_profit <= 0.0 and picks:
        expected_realized_profit = sum(_route_pick_expected_profit(p) for p in picks)
    full_sell_profit = float(route.get("full_sell_profit_total", route.get("profit_total", 0.0)) or 0.0)
    expected_days = [
        float(p.get("expected_days_to_sell", 0.0) or 0.0)
        for p in picks
        if float(p.get("expected_days_to_sell", 0.0) or 0.0) > 0.0
    ]
    avg_days = (sum(expected_days) / len(expected_days)) if expected_days else 0.0
    raw_pick_confidences = [_pick_raw_confidence(p) for p in picks]
    calibrated_pick_confidences = [_pick_calibrated_confidence(p) for p in picks]
    decision_pick_confidences = [_pick_decision_confidence(p) for p in picks]
    avg_pick_raw_conf = (sum(raw_pick_confidences) / len(raw_pick_confidences)) if raw_pick_confidences else 0.0
    avg_pick_calibrated_conf = (sum(calibrated_pick_confidences) / len(calibrated_pick_confidences)) if calibrated_pick_confidences else avg_pick_raw_conf
    avg_pick_conf = (sum(decision_pick_confidences) / len(decision_pick_confidences)) if decision_pick_confidences else avg_pick_calibrated_conf
    raw_transport_conf = transport_confidence_to_score(
        route.get("raw_transport_confidence", route.get("cost_model_confidence", "normal"))
    )
    calibrated_transport_conf = transport_confidence_to_score(
        route.get("calibrated_transport_confidence", raw_transport_conf)
    )
    transport_conf = transport_confidence_to_score(
        route.get("transport_confidence_for_decision", calibrated_transport_conf)
    )
    route_blocked = bool(route.get("route_blocked_due_to_transport", False))
    prune_reason = str(route.get("route_prune_reason", "") or "")
    actionable = bool(not route_blocked and picks)
    profits = sorted([max(0.0, _route_pick_expected_profit(p)) for p in picks], reverse=True)
    total_expected = max(1e-9, float(expected_realized_profit))
    top_share = (profits[0] / total_expected) if profits else 0.0
    concentration_penalty = max(0.0, top_share - 0.40)
    liquidation_speed = 1.0 / (1.0 + (avg_days / 45.0)) if avg_days > 0.0 else 1.0
    stale_market_penalty = 0.0
    if picks:
        stale_hits = sum(1 for p in picks if bool(p.get("used_volume_fallback", False)))
        stale_market_penalty = min(0.30, (float(stale_hits) / float(len(picks))) * 0.20)
    planned_count = sum(1 for p in picks if str(p.get("exit_type", p.get("mode", "instant")) or "").strip().lower() in {"planned", "planned_sell"})
    speculative_count = sum(1 for p in picks if str(p.get("exit_type", p.get("mode", "instant")) or "").strip().lower() == "speculative")
    speculative_penalty = 0.0
    if picks:
        speculative_penalty = min(0.35, ((float(planned_count) / float(len(picks))) * 0.08) + ((float(speculative_count) / float(len(picks))) * 0.22))
    raw_route_confidence = max(0.0, min(1.0, min(avg_pick_raw_conf if picks else 0.0, raw_transport_conf)))
    calibrated_route_confidence = max(0.0, min(1.0, min(avg_pick_calibrated_conf if picks else 0.0, calibrated_transport_conf)))
    route_confidence = max(
        0.0,
        min(
            1.0,
            float(
                route.get(
                    "route_confidence_for_decision",
                    min(avg_pick_conf if picks else 0.0, transport_conf),
                )
                or 0.0
            ),
        ),
    )
    capital_lock_risk = max(0.0, min(1.0, (avg_days / 90.0) + concentration_penalty))
    risk_adjusted_score = (
        float(expected_realized_profit)
        * max(0.0, route_confidence)
        * max(0.0, liquidation_speed)
        * max(0.0, 1.0 - (concentration_penalty * 0.75))
        * max(0.0, 1.0 - stale_market_penalty)
        * max(0.0, 1.0 - speculative_penalty)
        * max(0.0, transport_conf)
    )
    if route_blocked:
        risk_adjusted_score = -1.0
    summary = {
        "actionable": bool(actionable),
        "route_confidence": float(route_confidence),
        "raw_route_confidence": float(raw_route_confidence),
        "calibrated_route_confidence": float(calibrated_route_confidence),
        "transport_confidence": float(transport_conf),
        "raw_transport_confidence": float(raw_transport_conf),
        "calibrated_transport_confidence": float(calibrated_transport_conf),
        "raw_pick_confidence": float(avg_pick_raw_conf),
        "calibrated_pick_confidence": float(avg_pick_calibrated_conf),
        "total_expected_realized_profit": float(expected_realized_profit),
        "total_full_sell_profit": float(full_sell_profit),
        "average_expected_days_to_sell": float(avg_days),
        "capital_lock_risk": float(capital_lock_risk),
        "concentration_penalty": float(concentration_penalty),
        "stale_market_penalty": float(stale_market_penalty),
        "speculative_penalty": float(speculative_penalty),
        "risk_adjusted_score": float(risk_adjusted_score),
        "route_prune_reason": prune_reason,
        "calibration_warning": str(route.get("calibration_warning", "") or ""),
    }
    summary.update(
        build_route_explainability(
            route,
            base_profit_score=float(expected_realized_profit),
            route_confidence=float(route_confidence),
            liquidation_speed=float(liquidation_speed),
            transport_confidence=float(transport_conf),
            concentration_penalty=float(concentration_penalty),
            stale_market_penalty=float(stale_market_penalty),
            speculative_penalty=float(speculative_penalty),
            risk_adjusted_score=float(risk_adjusted_score),
            average_expected_days_to_sell=float(avg_days),
            capital_lock_risk=float(capital_lock_risk),
            prune_reason=prune_reason,
        )
    )
    return summary


def route_ranking_value(route: dict, metric: str) -> float:
    m = str(metric or "risk_adjusted_expected_profit").strip().lower()
    # For the default metric, use the pre-computed profile-adjusted score when available.
    # This lets runtime_runner store a profile-weighted score without re-running the summary.
    if m not in ("profit_total", "full_sell_profit", "expected_profit", "expected_realized_profit",
                 "expected_realized_profit_90d", "confidence", "route_confidence",
                 "liquidation_speed", "speed"):
        pre = route.get("_profile_risk_adjusted_score")
        if pre is not None:
            return float(pre)
    summary = summarize_route_for_ranking(route)
    if m in ("profit_total", "full_sell_profit"):
        return float(summary["total_full_sell_profit"])
    if m in ("expected_profit", "expected_realized_profit", "expected_realized_profit_90d"):
        return float(summary["total_expected_realized_profit"])
    if m in ("confidence", "route_confidence"):
        return float(summary["route_confidence"])
    if m in ("liquidation_speed", "speed"):
        return 1.0 / max(1e-9, 1.0 + float(summary["average_expected_days_to_sell"]))
    return float(summary["risk_adjusted_score"])


def _resolve_route_search_cfg(cfg: dict) -> dict:
    raw = cfg.get("route_search", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "max_routes": max(1, int(raw.get("max_routes", 10) or 10)),
        "ranking_metric": str(raw.get("ranking_metric", "risk_adjusted_expected_profit") or "risk_adjusted_expected_profit").strip().lower(),
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
