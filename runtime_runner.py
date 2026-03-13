from __future__ import annotations

import json
import os
import sys
import time

from candidate_engine import _route_adjusted_candidate_score, compute_candidates, compute_route_wide_candidates_for_source
from character_profile import (
    apply_character_fee_overrides,
    attach_character_context_to_result,
    build_character_context_summary,
    character_status_lines,
    requested_character_scopes,
    resolve_character_context,
    resolve_character_context_cfg,
    sync_character_profile,
)
from confidence_calibration import (
    apply_calibration_to_record,
    apply_personal_history_to_record,
    build_confidence_calibration,
    build_personal_history_layer_state,
    build_personal_calibration_summary,
    calibrate_confidence_value,
    personal_history_layer_status_lines,
    summarize_personal_history_effect,
    resolve_confidence_calibration_cfg,
)
from explainability import build_rejected_candidate_table
from config_loader import (
    _prepare_trade_filters,
    _resolve_strict_mode_cfg,
    _resolve_structure_region_map,
    ensure_dirs,
    fail_on_invalid_config,
    load_config,
    load_json,
    save_json,
    validate_config,
)
from execution_plan import write_execution_plan_profiles, write_route_leaderboard
from journal_cli import run_journal_cli
from journal_models import attach_plan_metadata, build_trade_plan_manifest, make_run_id, utc_now_iso
from journal_store import fetch_journal_entries
from location_utils import label_to_slug, normalize_location_label
from market_fetch import _fetch_orders_for_node
from market_normalization import make_snapshot_payload, normalize_replay_snapshot
from models import FilterFunnel, TradeCandidate
from portfolio_builder import (
    build_portfolio,
    choose_portfolio_for_route,
    sort_picks_for_output,
    try_cargo_fill,
)
from route_search import _resolve_route_search_cfg, build_route_search_profiles
from shipping import apply_route_costs_and_prune, build_jita_split_price_map, build_route_context
from startup_helpers import (
    _build_structure_context,
    _node_source_dest_info,
    _normalize_route_mode,
    _resolve_chain_runtime,
    _resolve_node_catalog,
    _resolve_primary_structure_ids,
)

from runtime_clients import ESIClient, ReplayESIClient
from runtime_common import (
    CONFIG_PATH,
    HTTP_CACHE_PATH,
    JOURNAL_DB_PATH,
    TYPE_CACHE_PATH,
    _has_live_esi_credentials,
    die,
    input_with_default,
    parse_cli_args,
    parse_isk,
)
from runtime_reports import (
    fmt_isk,
    pick_total_fees_taxes,
    write_chain_summary,
    write_csv,
    write_enhanced_summary,
    write_execution_plan_chain,
    write_top_candidate_dump,
)
from eve_sso import EveSSOAuth


def run_snapshot_only(cfg: dict, structure_ids: list[int], snapshot_out: str | None = None) -> None:
    if not _has_live_esi_credentials(cfg):
        die("Fehlende ESI-Credentials. Setze ESI_CLIENT_ID/ESI_CLIENT_SECRET oder nutze config.local.json.")
    esi = ESIClient(cfg)
    wanted = [int(s) for s in structure_ids]
    print("Snapshot-Only Modus aktiv.")
    print("Fuehre ESI-Preflight durch...")
    for sid in wanted:
        esi.preflight_structure_request(int(sid))
    structure_orders_by_id: dict[int, list[dict]] = {}
    print("Lade Marktorders...")
    for sid in wanted:
        print(f"  -> Lade Structure ({sid})...")
        orders = esi.fetch_structure_orders(int(sid))
        structure_orders_by_id[int(sid)] = orders if isinstance(orders, list) else []
        print(f"    {len(structure_orders_by_id[int(sid)])} Orders geladen")

    merged_type_cache = {}
    cached_types_from_disk = load_json(TYPE_CACHE_PATH, {})
    live_type_cache = getattr(esi, "type_cache", {})
    if isinstance(cached_types_from_disk, dict):
        merged_type_cache.update(cached_types_from_disk)
    if isinstance(live_type_cache, dict):
        merged_type_cache.update(live_type_cache)

    payload = make_snapshot_payload(structure_orders_by_id, merged_type_cache)
    out_dir = os.path.dirname(__file__)
    if snapshot_out:
        out_path = snapshot_out
        if not os.path.isabs(out_path):
            out_path = os.path.join(out_dir, out_path)
    else:
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        out_path = os.path.join(out_dir, f"snapshot_{ts}.json")
    save_json(out_path, payload)
    print(f"Snapshot geschrieben: {out_path}")


def evaluate_leg_disabled(leg_result: dict, budget_util_min_pct: float) -> tuple[bool, str]:
    if int(leg_result.get("items_count", 0)) <= 0:
        return True, "no_items"
    if float(leg_result.get("budget_util_pct", 0.0)) < float(budget_util_min_pct):
        return True, f"low_budget_util<{budget_util_min_pct:.2f}%"
    return False, ""


def _stable_plan_timestamp(snapshot_payload: dict | None, fallback_timestamp: str) -> str:
    meta = snapshot_payload.get("meta", {}) if isinstance(snapshot_payload, dict) else {}
    try:
        snapshot_ts = int(meta.get("timestamp", 0) or 0)
    except Exception:
        snapshot_ts = 0
    if snapshot_ts <= 0:
        return str(fallback_timestamp)
    from datetime import datetime

    return datetime.fromtimestamp(snapshot_ts).strftime("%Y-%m-%d_%H-%M-%S")


def _build_plan_id_seed(
    *,
    snapshot_payload: dict | None,
    budget_isk: float,
    cargo_m3: float,
    active_profile_name: str,
    route_mode: str,
    forward_mode: str,
    return_mode: str,
    route_search_cfg: dict,
    route_profiles: list[dict],
    chain_enabled: bool,
) -> str:
    identity = {
        "snapshot": snapshot_payload if isinstance(snapshot_payload, dict) else {},
        "budget_isk": float(budget_isk),
        "cargo_m3": float(cargo_m3),
        "profile": str(active_profile_name or ""),
        "route_mode": str(route_mode or ""),
        "forward_mode": str(forward_mode or ""),
        "return_mode": str(return_mode or ""),
        "route_search": dict(route_search_cfg or {}),
        "route_profiles": list(route_profiles or []),
        "chain_enabled": bool(chain_enabled),
    }
    return json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _resolve_capital_flow_cfg(cfg: dict) -> dict:
    cap = cfg.get("capital_flow", {})
    if not isinstance(cap, dict):
        cap = {}
    strict_cfg = cfg.get("strict_mode", {})
    strict_enabled = isinstance(strict_cfg, dict) and bool(strict_cfg.get("enabled", False))
    strict_release_fast = bool(strict_cfg.get("fast_sell_allowed_for_capital_release", False)) if strict_enabled else None
    release_fast_default = bool(cap.get("release_on_fast_sell", False))
    release_fast = strict_release_fast if strict_release_fast is not None else release_fast_default
    return {
        "enabled": bool(cap.get("enabled", False)),
        "release_on_instant": bool(cap.get("release_on_instant", True)),
        "release_on_fast_sell": bool(release_fast),
        "fast_sell_release_ratio": max(0.0, min(1.0, float(cap.get("fast_sell_release_ratio", 1.0)))),
    }


def _resolve_budget_split_cfg(port_cfg: dict) -> dict:
    if "instant_budget_ratio" in port_cfg or "planned_budget_ratio" in port_cfg:
        inst = float(port_cfg.get("instant_budget_ratio", 1.0) or 1.0)
        planned = float(port_cfg.get("planned_budget_ratio", 0.0) or 0.0)
        total = inst + planned
        if total <= 0:
            return {"instant": 1.0, "planned_sell": 0.0, "enabled": False}
        if abs(total - 1.0) > 1e-6:
            inst = inst / total
            planned = planned / total
        return {"instant": max(0.0, inst), "planned_sell": max(0.0, planned), "enabled": True}

    raw = port_cfg.get("instant_planned_budget_split", {})
    if not isinstance(raw, dict):
        raw = {}
    inst = float(raw.get("instant", 1.0) or 1.0)
    planned = float(raw.get("planned_sell", 0.0) or 0.0)
    total = inst + planned
    if total <= 0:
        return {"instant": 1.0, "planned_sell": 0.0, "enabled": False}
    if abs(total - 1.0) > 1e-6:
        inst = inst / total
        planned = planned / total
    enabled = bool(raw.get("enabled", False))
    return {"instant": max(0.0, inst), "planned_sell": max(0.0, planned), "enabled": enabled}


def _compute_chain_leg_budget(
    capital_available: float,
    start_budget_isk: float,
    cap_cfg: dict,
    strict_cfg: dict,
) -> tuple[float, bool]:
    base_budget = float(capital_available) if bool(cap_cfg.get("enabled", False)) else float(start_budget_isk)
    strict_enabled = bool(strict_cfg.get("enabled", False))
    max_share = float(strict_cfg.get("chain_leg_max_budget_share", 1.0)) if strict_enabled else 1.0
    if strict_enabled and 0.0 < max_share < 1.0:
        cap_budget = float(capital_available) * max_share if bool(cap_cfg.get("enabled", False)) else float(start_budget_isk) * max_share
        capped_budget = min(base_budget, cap_budget)
        return float(max(0.0, capped_budget)), bool(capped_budget + 1e-6 < base_budget)
    return float(max(0.0, base_budget)), False


def _apply_capital_flow_to_leg(
    leg: dict,
    mode: str,
    capital_before: float,
    cap_cfg: dict,
    current_leg_index: int | None = None,
    pending_releases: dict[int, float] | None = None,
) -> float:
    enabled = bool(cap_cfg.get("enabled", False))
    spent = float(leg.get("isk_used", 0.0))
    released = 0.0
    release_rule = "none"
    if enabled:
        picks = leg.get("picks", []) or []
        release_instant = bool(cap_cfg.get("release_on_instant", True))
        release_fast = bool(cap_cfg.get("release_on_fast_sell", False))
        fast_ratio = float(cap_cfg.get("fast_sell_release_ratio", 1.0))

        if pending_releases is not None and current_leg_index is not None:
            for p in picks:
                p_mode = str(p.get("mode", "")).strip().lower()
                if not p_mode:
                    p_mode = "instant" if bool(p.get("instant", False)) else str(mode).lower()
                rev = float(p.get("revenue_net", 0.0) or 0.0)
                if p_mode == "instant" and release_instant:
                    ridx = int(p.get("release_leg_index", current_leg_index))
                    pending_releases[ridx] = float(pending_releases.get(ridx, 0.0)) + rev
                elif p_mode == "fast_sell" and release_fast:
                    ridx = int(p.get("release_leg_index", current_leg_index))
                    pending_releases[ridx] = float(pending_releases.get(ridx, 0.0)) + (rev * fast_ratio)
            released = float(pending_releases.pop(int(current_leg_index), 0.0))
            if released > 0.0:
                release_rule = "route_exit_schedule"
        else:
            for p in picks:
                p_mode = str(p.get("mode", "")).strip().lower()
                if not p_mode:
                    p_mode = "instant" if bool(p.get("instant", False)) else str(mode).lower()
                rev = float(p.get("revenue_net", 0.0) or 0.0)
                if p_mode == "instant" and release_instant:
                    released += rev
                elif p_mode == "fast_sell" and release_fast:
                    released += rev * fast_ratio
            if released > 0.0:
                parts = []
                if release_instant:
                    parts.append("instant_revenue_net")
                if release_fast:
                    parts.append(f"fast_sell_revenue_net_x{fast_ratio:.2f}")
                release_rule = "+".join(parts) if parts else "none"
        capital_after = max(0.0, float(capital_before) - spent + released)
    else:
        capital_after = float(capital_before)

    leg["capital_flow_enabled"] = bool(enabled)
    leg["capital_available_before"] = float(capital_before)
    leg["capital_committed"] = float(spent)
    leg["capital_released"] = float(released)
    leg["capital_available_after"] = float(capital_after)
    leg["capital_release_rule"] = release_rule
    if pending_releases is not None:
        leg["capital_locked_future_release"] = float(sum(float(v) for v in pending_releases.values()))
    return float(capital_after)


def build_adjacent_pairs(chain_nodes: list[dict], reverse: bool = False) -> list[tuple[dict, dict]]:
    nodes = list(chain_nodes)
    if reverse:
        nodes = list(reversed(nodes))
    return [(nodes[i], nodes[i + 1]) for i in range(max(0, len(nodes) - 1))]


def build_route_wide_pairs(chain_nodes: list[dict], reverse: bool = False, max_hops: int = 99) -> list[dict]:
    nodes = list(chain_nodes)
    if reverse:
        nodes = list(reversed(nodes))
    out: list[dict] = []
    n = len(nodes)
    hop_cap = max(1, int(max_hops))
    for src_idx in range(n - 1):
        src = nodes[src_idx]
        for dst_idx in range(src_idx + 1, n):
            dst = nodes[dst_idx]
            hop_count = int(dst_idx - src_idx)
            if hop_count > hop_cap:
                break
            out.append(
                {
                    "src_idx": int(src_idx),
                    "dst_idx": int(dst_idx),
                    "src_id": int(src["id"]),
                    "dst_id": int(dst["id"]),
                    "src_label": str(src["label"]),
                    "dst_label": str(dst["label"]),
                    "hop_count": int(hop_count),
                }
            )
    return out


def _resolve_route_profiles_cfg(cfg: dict) -> dict:
    raw = cfg.get("route_profiles", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "include_forward_pairs": bool(raw.get("include_forward_pairs", True)),
        "include_reverse_pairs": bool(raw.get("include_reverse_pairs", True)),
        "max_hops": int(raw.get("max_hops", 99)),
        "routes": list(raw.get("routes", [])) if isinstance(raw.get("routes", []), list) else [],
    }


def build_route_profiles(chain_nodes: list[dict], cfg: dict) -> list[dict]:
    rp_cfg = _resolve_route_profiles_cfg(cfg)
    if not bool(rp_cfg.get("enabled", True)):
        return []
    explicit = rp_cfg.get("routes", [])
    profiles: list[dict] = []
    if explicit:
        for i, route in enumerate(explicit, start=1):
            if not isinstance(route, dict):
                continue
            src_raw = str(route.get("from", "")).strip()
            dst_raw = str(route.get("to", "")).strip()
            if not src_raw or not dst_raw:
                continue
            profiles.append(
                {
                    "id": str(route.get("id", f"profile_{i}")),
                    "from": src_raw,
                    "to": dst_raw,
                    "mode": str(route.get("mode", "") or ""),
                    "shipping_lane_id": str(route.get("shipping_lane_id", route.get("shipping_lane", "")) or ""),
                }
            )
        return profiles

    nodes = list(chain_nodes or [])
    if len(nodes) < 2:
        return profiles
    max_hops = max(1, int(rp_cfg.get("max_hops", 99)))
    include_fwd = bool(rp_cfg.get("include_forward_pairs", True))
    include_rev = bool(rp_cfg.get("include_reverse_pairs", True))
    for i in range(len(nodes) - 1):
        src = nodes[i]
        for j in range(i + 1, len(nodes)):
            hop_count = int(j - i)
            if hop_count > max_hops:
                break
            dst = nodes[j]
            if include_fwd:
                profiles.append(
                    {
                        "id": f"{label_to_slug(str(src['label']))}_to_{label_to_slug(str(dst['label']))}",
                        "from": str(src["label"]),
                        "to": str(dst["label"]),
                        "mode": "",
                        "shipping_lane_id": "",
                    }
                )
            if include_rev:
                profiles.append(
                    {
                        "id": f"{label_to_slug(str(dst['label']))}_to_{label_to_slug(str(src['label']))}",
                        "from": str(dst["label"]),
                        "to": str(src["label"]),
                        "mode": "",
                        "shipping_lane_id": "",
                    }
                )
    seen = set()
    out: list[dict] = []
    for p in profiles:
        key = (normalize_location_label(p.get("from", "")), normalize_location_label(p.get("to", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def enforce_route_destination(picks: list[dict], expected_dest_label: str) -> list[dict]:
    expected = normalize_location_label(expected_dest_label)
    out: list[dict] = []
    for p in list(picks or []):
        sell_at_raw = str(p.get("sell_at", "") or "").strip()
        if not sell_at_raw:
            out.append(p)
            continue
        if normalize_location_label(sell_at_raw) == expected:
            out.append(p)
    return out


def _resolve_route_wide_scan_cfg(cfg: dict) -> dict:
    rw = cfg.get("route_wide_scan", {})
    if not isinstance(rw, dict):
        rw = {}
    return {
        "enabled": bool(rw.get("enabled", False)),
        "max_hops_forward": int(rw.get("max_hops_forward", 99)),
        "max_hops_return": int(rw.get("max_hops_return", 99)),
        "prefer_nearer_exit_if_profit_close_pct": float(rw.get("prefer_nearer_exit_if_profit_close_pct", 0.10)),
        "cargo_penalty_per_extra_leg": float(rw.get("cargo_penalty_per_extra_leg", 0.05)),
        "capital_lock_penalty_per_extra_leg": float(rw.get("capital_lock_penalty_per_extra_leg", 0.07)),
        "allow_mixed_destinations_within_leg": bool(rw.get("allow_mixed_destinations_within_leg", True)),
        "score_weight_density": float(rw.get("score_weight_density", 0.36)),
        "score_weight_margin": float(rw.get("score_weight_margin", 0.27)),
        "score_weight_absolute": float(rw.get("score_weight_absolute", 0.17)),
        "score_weight_liquidity": float(rw.get("score_weight_liquidity", 0.12)),
        "score_weight_plausibility": float(rw.get("score_weight_plausibility", 0.08)),
    }


def _build_confidence_calibration_runtime(cfg: dict) -> dict:
    cal_cfg = resolve_confidence_calibration_cfg(cfg)
    runtime = {"config": cal_cfg, "model": None, "db_path": "", "warning": ""}
    if not isinstance(cfg, dict):
        return runtime
    if not bool(cal_cfg.get("enabled", False)):
        cfg["_confidence_calibration_runtime"] = runtime
        return runtime
    db_path = str(cal_cfg.get("journal_db_path", "") or JOURNAL_DB_PATH)
    runtime["db_path"] = db_path
    try:
        entries = fetch_journal_entries(db_path)
    except Exception as exc:
        runtime["warning"] = f"confidence calibration disabled: {exc}"
        cfg["_confidence_calibration_runtime"] = runtime
        return runtime
    runtime["model"] = build_confidence_calibration(entries, {"confidence_calibration": cal_cfg})
    if runtime["model"] is not None and list(runtime["model"].get("warnings", []) or []):
        runtime["warning"] = "; ".join(str(w) for w in list(runtime["model"].get("warnings", []) or []))
    cfg["_confidence_calibration_runtime"] = runtime
    return runtime


def _confidence_calibration_runtime(cfg: dict) -> dict:
    existing = cfg.get("_confidence_calibration_runtime")
    if isinstance(existing, dict):
        return existing
    return _build_confidence_calibration_runtime(cfg)


def _build_personal_calibration_runtime(cfg: dict) -> dict:
    cal_cfg = resolve_confidence_calibration_cfg(cfg)
    runtime = {"config": cal_cfg, "summary": None, "layer": {}, "db_path": "", "warning": ""}
    if not isinstance(cfg, dict):
        return runtime
    db_path = str(cal_cfg.get("journal_db_path", "") or JOURNAL_DB_PATH)
    runtime["db_path"] = db_path
    try:
        entries = fetch_journal_entries(db_path)
        runtime["summary"] = build_personal_calibration_summary(entries, {"confidence_calibration": cal_cfg})
    except Exception as exc:
        runtime["warning"] = f"personal history unavailable: {exc}"
        summary = build_personal_calibration_summary([], {"confidence_calibration": cal_cfg})
        summary = dict(summary)
        policy = dict(summary.get("policy", {}) or {})
        policy["fallback_to_generic"] = True
        if not str(policy.get("reason", "") or "").strip():
            policy["reason"] = "personal history unavailable"
        summary["policy"] = policy
        warnings = [runtime["warning"], *list(summary.get("warnings", []) or [])]
        summary["warnings"] = list(dict.fromkeys(str(item).strip() for item in warnings if str(item).strip()))
        runtime["summary"] = summary
    runtime["layer"] = build_personal_history_layer_state(runtime.get("summary"), cfg)
    cfg["_personal_calibration_runtime"] = runtime
    return runtime


def _personal_calibration_runtime(cfg: dict) -> dict:
    existing = cfg.get("_personal_calibration_runtime")
    if isinstance(existing, dict):
        return existing
    return _build_personal_calibration_runtime(cfg)


def _attach_runtime_advisories_to_result(result: dict, character_context: dict, personal_runtime: dict, *, budget_isk: int) -> dict:
    attach_character_context_to_result(result, character_context, budget_isk=budget_isk)
    summary = personal_runtime.get("summary")
    if isinstance(summary, dict) and summary:
        result["_personal_calibration_summary"] = dict(summary)
    layer = personal_runtime.get("layer")
    if isinstance(layer, dict) and layer:
        result["_personal_history_layer"] = dict(layer)
        effect_summary = summarize_personal_history_effect(list(result.get("picks", []) or []), layer)
        result["_personal_history_effect_summary"] = dict(effect_summary)
        result["personal_history_effect_applied"] = bool(effect_summary.get("applied", False))
        result["personal_history_effect_scope"] = str(effect_summary.get("scope", "") or "")
        result["personal_history_effect_reason"] = str(effect_summary.get("reason", "") or "")
        result["personal_history_effect_value"] = float(effect_summary.get("effect_value", 0.0) or 0.0)
    warning = str(personal_runtime.get("warning", "") or "").strip()
    if warning:
        result["_personal_calibration_warning"] = warning
    return result


def _apply_confidence_calibration_to_candidates(
    candidates: list[TradeCandidate],
    cfg: dict,
    *,
    route_id: str,
    source_market: str,
    target_market: str,
    scan_cfg: dict | None = None,
) -> None:
    runtime = _confidence_calibration_runtime(cfg)
    model = runtime.get("model")
    personal_runtime = _personal_calibration_runtime(cfg)
    for candidate in list(candidates or []):
        apply_calibration_to_record(
            candidate,
            model,
            route_id=route_id,
            source_market=source_market,
            target_market=target_market,
            exit_type=str(getattr(candidate, "exit_type", "")),
            transport_confidence=1.0,
        )
        apply_personal_history_to_record(
            candidate,
            personal_runtime.get("summary"),
            personal_runtime.get("layer"),
            route_id=route_id,
            source_market=source_market,
            target_market=target_market,
            exit_type=str(getattr(candidate, "exit_type", "")),
        )
        if scan_cfg is not None and bool(getattr(candidate, "route_wide_selected", False)):
            hop_count = int(getattr(candidate, "dest_hop_count", 1) or 1)
            candidate.route_adjusted_score = _route_adjusted_candidate_score(candidate, hop_count, scan_cfg)


def _apply_confidence_calibration_to_picks(
    picks: list[dict],
    cfg: dict,
    *,
    route_id: str,
    source_market: str,
    target_market: str,
    transport_confidence: object,
) -> None:
    runtime = _confidence_calibration_runtime(cfg)
    model = runtime.get("model")
    personal_runtime = _personal_calibration_runtime(cfg)
    for pick in list(picks or []):
        apply_calibration_to_record(
            pick,
            model,
            route_id=route_id,
            source_market=source_market,
            target_market=str(pick.get("sell_at", target_market) or target_market),
            exit_type=str(pick.get("exit_type", "") or ""),
            transport_confidence=transport_confidence,
        )
        apply_personal_history_to_record(
            pick,
            personal_runtime.get("summary"),
            personal_runtime.get("layer"),
            route_id=route_id,
            source_market=source_market,
            target_market=str(pick.get("sell_at", target_market) or target_market),
            exit_type=str(pick.get("exit_type", "") or ""),
        )


def _apply_confidence_calibration_to_route_result(result: dict, cfg: dict) -> dict:
    runtime = _confidence_calibration_runtime(cfg)
    cal_cfg = runtime.get("config", {})
    model = runtime.get("model")
    raw_transport_conf = str(result.get("cost_model_confidence", "normal") or "normal")
    transport_info = calibrate_confidence_value(
        raw_confidence=float(result.get("raw_transport_confidence", 0.0) or 0.0) if "raw_transport_confidence" in result else 0.0,
        calibration=model,
        dimension="transport",
        route_id=str(result.get("route_id", result.get("route_tag", "")) or ""),
        source_market=str(result.get("source_label", "") or ""),
        target_market=str(result.get("dest_label", "") or ""),
        exit_type="route",
    )
    if "raw_transport_confidence" not in result:
        from confidence_calibration import transport_confidence_to_score

        transport_info = calibrate_confidence_value(
            transport_confidence_to_score(raw_transport_conf),
            model,
            dimension="transport",
            route_id=str(result.get("route_id", result.get("route_tag", "")) or ""),
            source_market=str(result.get("source_label", "") or ""),
            target_market=str(result.get("dest_label", "") or ""),
            exit_type="route",
        )
    result["raw_transport_confidence"] = float(transport_info.get("raw_confidence", 0.0) or 0.0)
    result["calibrated_transport_confidence"] = float(transport_info.get("calibrated_confidence", result["raw_transport_confidence"]) or result["raw_transport_confidence"])
    result["transport_confidence_for_decision"] = (
        float(result["calibrated_transport_confidence"])
        if bool(cal_cfg.get("apply_to_decisions", True))
        else float(result["raw_transport_confidence"])
    )
    pick_warnings = [str(p.get("calibration_warning", "") or "") for p in list(result.get("picks", []) or []) if str(p.get("calibration_warning", "") or "")]
    route_warning = str(transport_info.get("warning", "") or "")
    if pick_warnings:
        route_warning = "; ".join(dict.fromkeys([route_warning] + pick_warnings if route_warning else pick_warnings))
    if str(runtime.get("warning", "") or ""):
        route_warning = "; ".join(dict.fromkeys([route_warning, str(runtime.get("warning", ""))] if route_warning else [str(runtime.get("warning", ""))]))
    result["calibration_warning"] = route_warning
    return result


def make_skipped_chain_leg(
    src_label: str,
    dst_label: str,
    reason: str,
    mode: str,
    filters_used: dict,
    budget_isk: float,
    cargo_m3: float,
) -> dict:
    return {
        "route_label": f"{src_label} -> {dst_label}",
        "leg_disabled": True,
        "leg_disabled_reason": reason,
        "mode": mode,
        "selected_mode": "skipped",
        "filters_used": filters_used,
        "total_candidates": 0,
        "passed_all_filters": 0,
        "why_out_summary": {},
        "items_count": 0,
        "m3_used": 0.0,
        "cargo_total": cargo_m3,
        "cargo_util_pct": 0.0,
        "isk_used": 0.0,
        "budget_total": budget_isk,
        "budget_util_pct": 0.0,
        "profit_total": 0.0,
        "picks": [],
    }


def _merge_reason_counts(dst: dict, src: dict) -> None:
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return
    for key, value in src.items():
        try:
            count = int(value or 0)
        except Exception:
            continue
        if count == 0:
            continue
        reason = str(key or "").strip()
        if not reason:
            continue
        dst[reason] = int(dst.get(reason, 0) or 0) + count


def _profile_rejection_metrics(pick: dict, filters_used: dict, budget_isk: float) -> dict:
    cost = float(pick.get("cost", 0.0) or 0.0)
    budget_total = float(budget_isk or 0.0)
    return {
        "expected_realized_profit_90d": float(
            pick.get("expected_realized_profit_90d", pick.get("expected_profit_90d", pick.get("profit", 0.0))) or 0.0
        ),
        "expected_realized_profit_per_m3_90d": float(
            pick.get("expected_realized_profit_per_m3_90d", pick.get("expected_profit_per_m3_90d", pick.get("profit_per_m3", 0.0))) or 0.0
        ),
        "decision_overall_confidence": float(
            pick.get("decision_overall_confidence", pick.get("calibrated_overall_confidence", pick.get("overall_confidence", 0.0))) or 0.0
        ),
        "profile_min_expected_profit_isk": float(filters_used.get("_profile_min_expected_profit_isk", 0.0) or 0.0),
        "profile_min_profit_per_m3": float(
            filters_used.get("_profile_min_profit_density_isk_per_m3", filters_used.get("_profile_min_profit_per_m3", 0.0)) or 0.0
        ),
        "profile_min_confidence": float(filters_used.get("_profile_min_confidence", 0.0) or 0.0),
        "profile_max_item_share_of_budget": float(filters_used.get("_profile_max_item_share_of_budget", 0.0) or 0.0),
        "budget_share": (cost / budget_total) if budget_total > 0.0 else 0.0,
    }


def _append_profile_rejections_to_explain(
    explain: dict,
    rejected_picks: list[dict],
    filters_used: dict,
    budget_isk: float,
) -> None:
    if not isinstance(explain, dict) or not rejected_picks:
        return
    reason_counts = explain.get("reason_counts", {})
    if not isinstance(reason_counts, dict):
        reason_counts = {}
        explain["reason_counts"] = reason_counts
    rejected_entries = explain.get("rejected", [])
    if not isinstance(rejected_entries, list):
        rejected_entries = []
        explain["rejected"] = rejected_entries

    for pick in list(rejected_picks or []):
        codes = [str(code or "").strip() for code in list(pick.get("_profile_rejection_codes", []) or []) if str(code or "").strip()]
        if not codes:
            continue
        for code in codes:
            reason_counts[code] = int(reason_counts.get(code, 0) or 0) + 1
        rejected_entries.append(
            {
                "type_id": int(pick.get("type_id", 0) or 0),
                "name": str(pick.get("name", "") or ""),
                "reason": codes[0],
                "reason_code": codes[0],
                "metrics": _profile_rejection_metrics(pick, filters_used, budget_isk),
            }
        )


def _apply_post_build_profile_filters(
    picks: list[dict],
    filters_used: dict,
    *,
    explain: dict,
    budget_isk: float,
    route_label: str,
) -> list[dict]:
    from risk_profiles import filter_picks_by_profile

    kept, rejected = filter_picks_by_profile(picks, filters_used, budget_isk=budget_isk)
    if not rejected:
        return list(kept)

    _append_profile_rejections_to_explain(explain, rejected, filters_used, budget_isk)
    profile_name = str(filters_used.get("_profile_name", "") or "")
    print(f"    [Profile:{profile_name}] {len(rejected)} Pick(s) nach finalen Profilregeln entfernt ({route_label}).")
    return list(kept)


def _prune_reason_bucket(reason: str) -> str:
    key = str(reason or "").strip().lower()
    if not key:
        return ""
    if key in {
        "no_candidates",
        "candidates_below_profit_floor",
        "candidates_failed_confidence",
        "candidates_failed_budget_rule",
        "candidates_failed_fill_probability",
        "candidates_failed_sell_time",
        "candidates_invalid_volume",
        "no_picks_after_portfolio_constraints",
        "internal_route_profit_below_operational_floor",
    }:
        return key
    if key in {
        "expected_profit_too_low",
        "expected_profit_too_low_after_shipping",
        "min_profit_pct",
        "min_profit_pct_after_shipping",
        "non_positive_profit",
        "non_positive_profit_90d",
        "profit_threshold",
        "orderbook_min_source_sell_price",
        "profile_min_expected_profit_isk",
        "profile_min_profit_per_m3",
    }:
        return "candidates_below_profit_floor"
    if key in {"profile_min_confidence", "planned_low_confidence"}:
        return "candidates_failed_confidence"
    if key in {"profile_max_item_share_of_budget"}:
        return "candidates_failed_budget_rule"
    if key in {
        "fill_probability",
        "dest_buy_depth_units",
        "min_depth_units",
        "orderbook_window_units_too_low",
    }:
        return "candidates_failed_fill_probability"
    if key in {
        "expected_days_too_high",
        "strict_expected_days_too_high",
        "sell_through_too_low",
        "strict_sell_through_too_low",
        "avg_daily_volume_too_low",
        "strict_avg_daily_volume_7d_too_low",
        "planned_queue_ahead_too_heavy",
        "planned_demand_cap_zero",
        "planned_demand_cap_too_low",
        "planned_structure_micro_liquidity",
        "planned_history_order_count",
        "no_history_volume",
        "strict_no_fallback_volume",
    }:
        return "candidates_failed_sell_time"
    if key in {"invalid_volume"}:
        return "candidates_invalid_volume"
    return ""


def _derive_route_prune_reason(result: dict) -> str:
    current_reason = str(result.get("route_prune_reason", "") or "").strip()
    if bool(result.get("route_blocked_due_to_transport", False)):
        return current_reason or "missing_transport_cost_model"
    if list(result.get("picks", []) or []):
        return current_reason if current_reason not in {"", "no_picks"} else ""
    if current_reason and current_reason != "no_picks":
        return current_reason

    reason_counts = result.get("why_out_summary", {})
    if not isinstance(reason_counts, dict):
        reason_counts = {}
    bucket_counts: dict[str, int] = {}
    for reason, count in reason_counts.items():
        bucket = _prune_reason_bucket(reason)
        if not bucket:
            continue
        try:
            n = int(count or 0)
        except Exception:
            n = 0
        if n <= 0:
            continue
        bucket_counts[bucket] = int(bucket_counts.get(bucket, 0) or 0) + n
    if bucket_counts:
        return max(bucket_counts.items(), key=lambda item: (item[1], item[0]))[0]

    total_candidates = int(result.get("total_candidates", 0) or 0)
    passed_all = int(result.get("passed_all_filters", 0) or 0)
    if passed_all > 0:
        return "no_picks_after_portfolio_constraints"
    if total_candidates <= 0:
        return "no_candidates"
    return current_reason or "no_picks"


def _refresh_route_result_from_current_picks(result: dict) -> dict:
    picks = list(result.get("picks", []) or [])
    budget_total = float(result.get("budget_total", 0.0) or 0.0)
    cargo_total = float(result.get("cargo_total", result.get("cargo_m3", 0.0)) or 0.0)

    total_cost = sum(float(p.get("cost", 0.0) or 0.0) for p in picks)
    total_revenue = sum(float(p.get("revenue_net", 0.0) or 0.0) for p in picks)
    total_profit = sum(float(p.get("profit", 0.0) or 0.0) for p in picks)
    total_fees_taxes = sum(pick_total_fees_taxes(p) for p in picks)
    total_m3 = sum(float(p.get("unit_volume", 0.0) or 0.0) * float(p.get("qty", 0) or 0.0) for p in picks)
    total_shipping_cost = sum(float(p.get("shipping_cost", 0.0) or 0.0) for p in picks)
    total_route_cost = sum(float(p.get("route_cost", 0.0) or 0.0) for p in picks)
    total_transport_cost = sum(float(p.get("transport_cost", 0.0) or 0.0) for p in picks)
    expected_realized_total = sum(
        float(p.get("expected_realized_profit_90d", p.get("expected_profit_90d", p.get("profit", 0.0))) or 0.0)
        for p in picks
    )
    full_sell_total = sum(float(p.get("gross_profit_if_full_sell", p.get("profit", 0.0)) or 0.0) for p in picks)

    result["items_count"] = int(len(picks))
    result["isk_used"] = float(total_cost)
    result["net_revenue_total"] = float(total_revenue)
    result["profit_total"] = float(total_profit)
    result["total_fees_taxes"] = float(total_fees_taxes)
    result["m3_used"] = float(total_m3)
    result["cargo_total"] = float(cargo_total)
    result["total_route_m3"] = float(total_m3)
    result["cargo_util_pct"] = (float(total_m3) / cargo_total * 100.0) if cargo_total > 0.0 else 0.0
    result["budget_total"] = float(budget_total)
    result["budget_util_pct"] = (float(total_cost) / budget_total * 100.0) if budget_total > 0.0 else 0.0
    result["expected_realized_profit_total"] = float(expected_realized_total)
    result["full_sell_profit_total"] = float(full_sell_total)
    result["total_shipping_cost"] = float(total_shipping_cost)
    result["shipping_cost_total"] = float(total_shipping_cost)
    result["total_route_cost"] = float(total_route_cost)
    result["total_transport_cost"] = float(total_transport_cost)
    result["route_actionable"] = bool(picks and not bool(result.get("route_blocked_due_to_transport", False)))
    result["budget_left_reason"] = (
        "Keine weiteren Picks erfuellen Profit-Floors nach Gebuehren und Routenkosten."
        if budget_total > 0.0 and (budget_total - total_cost) / budget_total >= 0.05
        else ""
    )
    result["route_prune_reason"] = _derive_route_prune_reason(result)

    csv_path = str(result.get("csv_path", "") or "").strip()
    if csv_path:
        write_csv(csv_path, picks)
    return result


def _resolve_internal_route_operational_profit_floor(cfg: dict, filters_used: dict) -> float:
    route_search_cfg = cfg.get("route_search", {}) if isinstance(cfg, dict) else {}
    if not isinstance(route_search_cfg, dict):
        route_search_cfg = {}
    explicit_floor = float(route_search_cfg.get("internal_self_haul_min_expected_profit_isk", 0.0) or 0.0)
    if explicit_floor > 0.0:
        return float(explicit_floor)
    strict_floor = float(_resolve_strict_mode_cfg(cfg).get("planned_profit_floor_isk", 0.0) or 0.0)
    profile_floor = float(filters_used.get("_profile_min_expected_profit_isk", 0.0) or 0.0)
    return float(max(strict_floor, profile_floor, 0.0))


def _apply_internal_self_haul_operational_filter(result: dict, cfg: dict) -> dict:
    transport_mode = str(result.get("transport_mode", "") or "").strip().lower()
    filters_used = result.get("filters_used", {})
    if not isinstance(filters_used, dict):
        filters_used = {}
    floor = _resolve_internal_route_operational_profit_floor(cfg, filters_used)
    result["operational_profit_floor_isk"] = float(floor)
    if transport_mode != "internal_self_haul" or floor <= 0.0:
        return result

    result["operational_filter_note"] = (
        f"Internal nullsec routes require at least {floor / 1_000_000:.1f}m ISK expected realized profit."
    )
    if not bool(result.get("route_actionable", False)):
        result["operational_filter_applied"] = False
        return result

    expected_profit = float(result.get("expected_realized_profit_total", 0.0) or 0.0)
    if expected_profit + 1e-6 >= floor:
        result["operational_filter_applied"] = False
        return result

    result["operational_filter_applied"] = True
    result["operational_filter_reason"] = "internal_route_profit_below_operational_floor"
    result["suppressed_expected_realized_profit_total"] = float(expected_profit)
    result["suppressed_full_sell_profit_total"] = float(result.get("full_sell_profit_total", result.get("profit_total", 0.0)) or 0.0)
    result["suppressed_isk_used"] = float(result.get("isk_used", 0.0) or 0.0)
    result["picks"] = []
    result["route_prune_reason"] = "internal_route_profit_below_operational_floor"
    return _refresh_route_result_from_current_picks(result)


def _finalize_route_result_runtime_state(result: dict, cfg: dict) -> dict:
    _refresh_route_result_from_current_picks(result)
    return _apply_internal_self_haul_operational_filter(result, cfg)


def _choose_portfolio_from_candidates_only(
    route_label: str,
    candidates: list[TradeCandidate],
    filters_used: dict,
    budget_isk: float,
    cargo_m3: float,
    fees: dict,
    port_cfg: dict,
    cfg: dict,
) -> tuple[list[dict], float, float, float, str]:
    def build_from_candidates(cands, f_used):
        inst = [c for c in cands if bool(getattr(c, "instant", False))]
        if inst:
            p, c, pr, m = build_portfolio(inst, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            md = "instant"
        else:
            p, c, pr, m = build_portfolio(cands, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            md = "fallback"
        p.sort(key=lambda x: x["profit"], reverse=True)
        return p, c, pr, m, md

    picks, cost, profit, m3, mode = build_from_candidates(candidates, filters_used)
    cargo_fill_enabled = bool(port_cfg.get("cargo_fill_enabled", False))
    cargo_fill_trigger_gap = float(port_cfg.get("cargo_fill_trigger_gap", 0.20))
    cargo_fill_profit_floor_ratio = float(port_cfg.get("cargo_fill_profit_floor_ratio", 0.90))
    target_cargo_util = float(port_cfg.get("target_cargo_utilization", 0.0))
    cargo_util = (m3 / cargo_m3) if cargo_m3 > 0 else 1.0
    cargo_gap = target_cargo_util - cargo_util
    if (
        cargo_fill_enabled
        and target_cargo_util > 0.0
        and cargo_m3 > 0.0
        and cargo_gap >= cargo_fill_trigger_gap
        and cost < budget_isk
        and m3 < cargo_m3
    ):
        print(
            f"    Hinweis: {route_label} nutzt nur {cargo_util*100:.1f}% Cargo "
            f"(Ziel {target_cargo_util*100:.1f}%), starte Cargo-Fill..."
        )
        f_picks, f_cost, f_profit, f_m3, added = try_cargo_fill(
            picks, candidates, budget_isk, cargo_m3, fees, filters_used, port_cfg
        )
        min_allowed_profit = float(profit) * max(0.0, cargo_fill_profit_floor_ratio)
        if added > 0 and f_m3 > (m3 + 1e-6) and f_profit >= min_allowed_profit:
            print("    Cargo-Fill uebernommen.")
            picks, cost, profit, m3 = f_picks, f_cost, f_profit, f_m3
        else:
            print("    Cargo-Fill verworfen.")
    return picks, cost, profit, m3, mode


def _finalize_route_result(
    *,
    route_tag: str,
    route_label: str,
    source_id: int,
    dest_id: int,
    source_label: str,
    dest_label: str,
    filters_used: dict,
    mode: str,
    selected_mode: str,
    candidates: list[TradeCandidate],
    picks: list[dict],
    budget_isk: float,
    cargo_m3: float,
    transport_summary: dict,
    timestamp: str,
    out_dir: str,
    explain: dict,
    source_node_meta: dict | None = None,
    dest_node_meta: dict | None = None,
    funnel: FilterFunnel | None = None,
    ) -> dict:
    warn_msg = str(transport_summary.get("cost_model_warning", "") or "")
    if bool(transport_summary.get("route_blocked_due_to_transport", False)):
        if warn_msg:
            print(f"    BLOCKED: {route_label}: {warn_msg}")
    elif str(transport_summary.get("transport_mode", "") or "").strip().lower() == "internal_self_haul":
        info_msg = str(transport_summary.get("transport_mode_note", "") or "")
        if info_msg:
            print(f"    INFO: {route_label}: {info_msg}")
    elif bool(transport_summary.get("transport_cost_assumed_zero", False)) and warn_msg:
        print(f"    WARN: {route_label}: {warn_msg}")

    total_cost = sum(float(p.get("cost", 0.0)) for p in picks)
    total_revenue = sum(float(p.get("revenue_net", 0.0)) for p in picks)
    total_profit = sum(float(p.get("profit", 0.0)) for p in picks)
    total_fees_taxes = sum(pick_total_fees_taxes(p) for p in picks)
    total_m3 = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in picks)
    sort_picks_for_output(picks, filters_used)

    csv_name = f"{label_to_slug(source_label)}_to_{label_to_slug(dest_label)}_{timestamp}.csv"
    csv_path = os.path.join(out_dir, csv_name)
    write_csv(csv_path, picks)

    dump_name = f"{route_tag}_top_candidates_{timestamp}.txt"
    dump_path = os.path.join(out_dir, dump_name)
    write_top_candidate_dump(dump_path, candidates, route_label, filters_used, explain)

    reason_counts = dict(explain.get("reason_counts", {}))
    reason_code_counts = dict(explain.get("reason_code_counts", {}))
    top_rejected_candidates = build_rejected_candidate_table(explain, limit=10)
    passed_all = int(reason_counts.get("passed_all_filters", 0))
    budget_util_pct = (float(total_cost) / float(budget_isk) * 100.0) if float(budget_isk) > 0 else 0.0
    cargo_util_pct = (float(total_m3) / float(cargo_m3) * 100.0) if float(cargo_m3) > 0 else 0.0
    budget_left_reason = ""
    if float(budget_isk) > 0 and (float(budget_isk) - float(total_cost)) / float(budget_isk) >= 0.05:
        budget_left_reason = "Keine weiteren Picks erfuellen Profit-Floors nach Gebuehren und Routenkosten."

    expected_realized_total = sum(
        float(p.get("expected_realized_profit_90d", p.get("expected_profit_90d", 0.0)) or 0.0) for p in picks
    )
    full_sell_total = sum(float(p.get("gross_profit_if_full_sell", p.get("profit", 0.0)) or 0.0) for p in picks)
    route_blocked_due_to_transport = bool(transport_summary.get("route_blocked_due_to_transport", False))
    route_actionable = bool(not route_blocked_due_to_transport and picks)
    route_prune_reason = str(transport_summary.get("route_prune_reason", "")) or ("no_picks" if not picks else "")
    return {
        "route_tag": route_tag,
        "route_label": route_label,
        "source_structure_id": int(source_id),
        "dest_structure_id": int(dest_id),
        "source_node_info": _node_source_dest_info(
            source_node_meta or {"label": source_label, "id": int(source_id), "kind": "structure", "structure_id": int(source_id)}
        ),
        "dest_node_info": _node_source_dest_info(
            dest_node_meta or {"label": dest_label, "id": int(dest_id), "kind": "structure", "structure_id": int(dest_id)}
        ),
        "source_label": source_label,
        "dest_label": dest_label,
        "filters_used": filters_used,
        "mode": mode,
        "selected_mode": selected_mode,
        "candidates": candidates,
        "picks": picks,
        "csv_path": csv_path,
        "dump_path": dump_path,
        "items_count": len(picks),
        "m3_used": float(total_m3),
        "cargo_total": float(cargo_m3),
        "cargo_util_pct": float(cargo_util_pct),
        "isk_used": float(total_cost),
        "net_revenue_total": float(total_revenue),
        "total_fees_taxes": float(total_fees_taxes),
        "budget_total": float(budget_isk),
        "budget_util_pct": float(budget_util_pct),
        "budget_left_reason": budget_left_reason,
        "profit_total": float(total_profit),
        "expected_realized_profit_total": float(expected_realized_total),
        "full_sell_profit_total": float(full_sell_total),
        "total_shipping_cost": float(transport_summary.get("total_shipping_cost", 0.0)),
        "shipping_cost_total": float(transport_summary.get("total_shipping_cost", 0.0)),
        "total_route_cost": float(transport_summary.get("total_route_cost", 0.0)),
        "total_transport_cost": float(transport_summary.get("total_transport_cost", 0.0)),
        "shipping_lane_id": str(transport_summary.get("shipping_lane_id", "")),
        "shipping_pricing_model": str(transport_summary.get("shipping_pricing_model", "")),
        "shipping_provider": str(transport_summary.get("shipping_provider", "")),
        "shipping_contracts_used": int(transport_summary.get("shipping_contracts_used", 0) or 0),
        "shipping_split_reason": str(transport_summary.get("shipping_split_reason", "")),
        "estimated_collateral_isk": float(transport_summary.get("estimated_collateral_isk", 0.0)),
        "shipping_lane_params": dict(transport_summary.get("shipping_lane_params", {})),
        "total_route_m3": float(transport_summary.get("total_route_m3", total_m3)),
        "transport_mode": str(transport_summary.get("transport_mode", "")),
        "transport_mode_note": str(transport_summary.get("transport_mode_note", "")),
        "route_cost_is_explicit": bool(transport_summary.get("route_cost_is_explicit", False)),
        "cost_model_status": str(transport_summary.get("cost_model_status", "configured")),
        "cost_model_confidence": str(transport_summary.get("cost_model_confidence", "normal")),
        "transport_cost_assumed_zero": bool(transport_summary.get("transport_cost_assumed_zero", False)),
        "cost_model_warning": str(transport_summary.get("cost_model_warning", "")),
        "zero_transport_exception": bool(transport_summary.get("zero_transport_exception", False)),
        "route_blocked_due_to_transport": bool(route_blocked_due_to_transport),
        "route_actionable": bool(route_actionable),
        "route_prune_reason": str(route_prune_reason),
        "total_candidates": len(candidates),
        "why_out_summary": reason_counts,
        "why_out_reason_codes": reason_code_counts,
        "passed_all_filters": passed_all,
        "funnel": funnel or FilterFunnel(),
        "explain": explain,
        "top_rejected_candidates": top_rejected_candidates,
    }


def _write_trade_plan_artifact(
    route_results: list[dict],
    *,
    plan_id: str,
    created_at: str,
    runtime_mode: str,
    primary_output_path: str,
    out_dir: str,
) -> str:
    plan_payload = build_trade_plan_manifest(
        route_results=route_results,
        plan_id=plan_id,
        created_at=created_at,
        runtime_mode=runtime_mode,
        primary_output_path=primary_output_path,
    )
    plan_path = os.path.join(out_dir, f"trade_plan_{plan_id}.json")
    save_json(plan_path, plan_payload)
    return plan_path


def run_route_wide_leg(
    esi,
    route_tag: str,
    source_node: dict,
    immediate_dest_node: dict,
    source_index: int,
    chain_nodes_ordered: list[dict],
    max_hops: int,
    scan_cfg: dict,
    structure_orders_by_id: dict[int, list[dict]],
    filters: dict,
    portfolio_cfg: dict,
    fees: dict,
    mode: str,
    budget_isk: float,
    cargo_m3: float,
    cfg: dict,
    timestamp: str,
    out_dir: str,
) -> dict:
    route_label = f"{source_node['label']} -> {immediate_dest_node['label']}"
    print(f"Berechne {route_label} (route-wide)...")
    filters_used = dict(filters)
    filters_used["mode"] = mode

    destination_nodes: list[dict] = []
    max_hops_i = max(1, int(max_hops))
    for j in range(source_index + 1, len(chain_nodes_ordered)):
        hop_count = int(j - source_index)
        if hop_count > max_hops_i:
            break
        n = dict(chain_nodes_ordered[j])
        n["route_index"] = int(j)
        n["hop_count"] = int(hop_count)
        destination_nodes.append(n)

    candidates: list[TradeCandidate] = []
    explain: dict = {"reason_counts": {}}
    if str(mode).lower() == "instant_first":
        budget_split = _resolve_budget_split_cfg(portfolio_cfg)
        instant_budget = float(budget_isk)
        planned_budget_cap = float(budget_isk)
        if bool(budget_split.get("enabled", False)):
            instant_budget = min(float(budget_isk), float(budget_isk) * float(budget_split.get("instant", 1.0)))
            planned_budget_cap = max(0.0, float(budget_isk) * float(budget_split.get("planned_sell", 0.0)))
        instant_filters = dict(filters_used)
        instant_filters["mode"] = "instant"
        instant_candidates, instant_explain = compute_route_wide_candidates_for_source(
            esi=esi,
            source_node=source_node,
            source_index=source_index,
            destination_nodes=destination_nodes,
            chain_nodes_ordered=chain_nodes_ordered,
            structure_orders_by_id=structure_orders_by_id,
            fees=fees,
            filters=instant_filters,
            scan_cfg=scan_cfg,
            cfg=cfg,
        )
        _apply_confidence_calibration_to_candidates(
            instant_candidates,
            cfg,
            route_id=str(route_tag),
            source_market=str(source_node["label"]),
            target_market="",
            scan_cfg=scan_cfg,
        )
        for k, v in dict(instant_explain.get("reason_counts", {})).items():
            explain["reason_counts"][k] = int(explain["reason_counts"].get(k, 0)) + int(v)
        candidates.extend(instant_candidates)

        remaining_budget = float(budget_isk)
        remaining_cargo = float(cargo_m3)
        picks, total_cost, total_profit, total_m3, selected_mode = _choose_portfolio_from_candidates_only(
            route_label=route_label,
            candidates=instant_candidates,
            filters_used=instant_filters,
            budget_isk=instant_budget,
            cargo_m3=remaining_cargo,
            fees=fees,
            port_cfg=portfolio_cfg,
            cfg=cfg,
        )
        remaining_budget = max(0.0, remaining_budget - float(total_cost))
        remaining_cargo = max(0.0, remaining_cargo - float(total_m3))

        planned_filters = dict(filters_used)
        planned_filters["mode"] = "planned_sell"
        planned_candidates, planned_explain = compute_route_wide_candidates_for_source(
            esi=esi,
            source_node=source_node,
            source_index=source_index,
            destination_nodes=destination_nodes,
            chain_nodes_ordered=chain_nodes_ordered,
            structure_orders_by_id=structure_orders_by_id,
            fees=fees,
            filters=planned_filters,
            scan_cfg=scan_cfg,
            cfg=cfg,
        )
        _apply_confidence_calibration_to_candidates(
            planned_candidates,
            cfg,
            route_id=str(route_tag),
            source_market=str(source_node["label"]),
            target_market="",
            scan_cfg=scan_cfg,
        )
        for k, v in dict(planned_explain.get("reason_counts", {})).items():
            explain["reason_counts"][k] = int(explain["reason_counts"].get(k, 0)) + int(v)
        picked_ids = {int(p.get("type_id", 0)) for p in picks}
        planned_candidates = [c for c in planned_candidates if int(c.type_id) not in picked_ids]
        candidates.extend(planned_candidates)
        if planned_candidates and remaining_budget > 1e-6 and remaining_cargo > 1e-6:
            planned_budget = remaining_budget
            if bool(budget_split.get("enabled", False)):
                planned_budget = min(planned_budget, planned_budget_cap)
            p2, c2, pr2, m2, _ = _choose_portfolio_from_candidates_only(
                route_label=route_label,
                candidates=planned_candidates,
                filters_used=planned_filters,
                budget_isk=planned_budget,
                cargo_m3=remaining_cargo,
                fees=fees,
                port_cfg=portfolio_cfg,
                cfg=cfg,
            )
            if p2:
                picks.extend(p2)
                total_cost += float(c2)
                total_profit += float(pr2)
                total_m3 += float(m2)
                selected_mode = "instant_first/mixed"
    else:
        candidates, explain = compute_route_wide_candidates_for_source(
            esi=esi,
            source_node=source_node,
            source_index=source_index,
            destination_nodes=destination_nodes,
            chain_nodes_ordered=chain_nodes_ordered,
            structure_orders_by_id=structure_orders_by_id,
            fees=fees,
            filters=filters_used,
            scan_cfg=scan_cfg,
            cfg=cfg,
        )
        _apply_confidence_calibration_to_candidates(
            candidates,
            cfg,
            route_id=str(route_tag),
            source_market=str(source_node["label"]),
            target_market="",
            scan_cfg=scan_cfg,
        )
        picks, total_cost, total_profit, total_m3, selected_mode = _choose_portfolio_from_candidates_only(
            route_label=route_label,
            candidates=candidates,
            filters_used=filters_used,
            budget_isk=budget_isk,
            cargo_m3=cargo_m3,
            fees=fees,
            port_cfg=portfolio_cfg,
            cfg=cfg,
        )

    for p in picks:
        if not p.get("buy_at"):
            p["buy_at"] = str(source_node["label"])
        if not p.get("sell_at"):
            p["sell_at"] = str(immediate_dest_node["label"])
        p["route_hops"] = int(p.get("route_hops", max(1, int(p.get("route_dst_index", source_index + 1)) - int(source_index))))
        p["carried_through_legs"] = int(p.get("carried_through_legs", p["route_hops"]))
        if "release_leg_index" not in p:
            dst_idx = int(p.get("route_dst_index", source_index + 1))
            p["release_leg_index"] = max(0, dst_idx - 1)

    if not bool(scan_cfg.get("allow_mixed_destinations_within_leg", True)) and picks:
        by_sell: dict[str, float] = {}
        for p in picks:
            dst = str(p.get("sell_at", ""))
            by_sell[dst] = float(by_sell.get(dst, 0.0)) + float(p.get("profit", 0.0))
        dominant_sell = max(by_sell.items(), key=lambda x: x[1])[0] if by_sell else ""
        picks = [p for p in picks if str(p.get("sell_at", "")) == dominant_sell]

    route_context = build_route_context(
        cfg,
        route_tag,
        str(source_node["label"]),
        str(immediate_dest_node["label"]),
        source_id=int(source_node.get("id", 0) or 0),
        dest_id=int(immediate_dest_node.get("id", 0) or 0),
    )
    picks, transport_summary = apply_route_costs_and_prune(picks, route_context, filters_used)
    _apply_confidence_calibration_to_picks(
        picks,
        cfg,
        route_id=str(route_tag),
        source_market=str(source_node["label"]),
        target_market=str(immediate_dest_node["label"]),
        transport_confidence=transport_summary.get("cost_model_confidence", "normal"),
    )
    pre_profile_pick_count = len(picks)
    picks = _apply_post_build_profile_filters(
        picks,
        filters_used,
        explain=explain,
        budget_isk=float(budget_isk),
        route_label=route_label,
    )
    if len(picks) != pre_profile_pick_count:
        if picks:
            picks, transport_summary = apply_route_costs_and_prune(picks, route_context, filters_used)
        else:
            transport_summary = dict(transport_summary)
            transport_summary["total_shipping_cost"] = 0.0
            transport_summary["total_route_cost"] = 0.0
            transport_summary["total_transport_cost"] = 0.0
            transport_summary["total_route_m3"] = 0.0
    result = _finalize_route_result(
        route_tag=route_tag,
        route_label=route_label,
        source_id=int(source_node["id"]),
        dest_id=int(immediate_dest_node["id"]),
        source_label=str(source_node["label"]),
        dest_label=str(immediate_dest_node["label"]),
        filters_used=filters_used,
        mode=mode,
        selected_mode=selected_mode,
        candidates=candidates,
        picks=picks,
        budget_isk=budget_isk,
        cargo_m3=cargo_m3,
        transport_summary=transport_summary,
        timestamp=timestamp,
        out_dir=out_dir,
        explain=explain,
        funnel=FilterFunnel(),
    )
    result = _apply_confidence_calibration_to_route_result(result, cfg)
    return _finalize_route_result_runtime_state(result, cfg)


def run_route(
    esi,
    source_structure_id: int,
    dest_structure_id: int,
    route_tag: str,
    source_label: str,
    dest_label: str,
    filters: dict,
    portfolio_cfg: dict,
    fees: dict,
    mode: str,
    replay_cfg: dict,
    replay_snapshot: dict | None,
    structure_orders_by_id: dict[int, list[dict]],
    budget_isk: float,
    cargo_m3: float,
    cfg: dict,
    timestamp: str,
    out_dir: str,
    source_node_meta: dict | None = None,
    dest_node_meta: dict | None = None,
    preferred_shipping_lane_id: str | None = None,
) -> dict:
    filters_used = dict(filters)
    filters_used["mode"] = mode
    source_orders = structure_orders_by_id.get(int(source_structure_id), [])
    dest_orders = structure_orders_by_id.get(int(dest_structure_id), [])
    route_context = build_route_context(
        cfg,
        route_tag,
        source_label,
        dest_label,
        source_id=int(source_structure_id),
        dest_id=int(dest_structure_id),
        preferred_shipping_lane_id=preferred_shipping_lane_id,
    )
    src_norm = normalize_location_label(source_label)
    dst_norm = normalize_location_label(dest_label)
    jita_orders_for_split: list[dict] = []
    if src_norm == "jita":
        jita_orders_for_split = source_orders
    elif dst_norm == "jita":
        jita_orders_for_split = dest_orders
    route_context["jita_split_prices"] = build_jita_split_price_map(jita_orders_for_split)

    funnel = FilterFunnel()
    explain = {}
    route_label = f"{source_label} -> {dest_label}"
    print(f"Berechne {route_label}...")
    candidates: list[TradeCandidate] = []
    picks: list[dict] = []
    selected_mode = "fallback"

    if str(mode).lower() == "instant_first":
        def merge_reason_counts(dst: dict, src: dict) -> None:
            for k, v in src.items():
                dst[k] = int(dst.get(k, 0)) + int(v)

        combined_reason_counts: dict[str, int] = {}
        budget_split = _resolve_budget_split_cfg(portfolio_cfg)
        instant_budget = float(budget_isk)
        planned_budget_cap = float(budget_isk)
        if bool(budget_split.get("enabled", False)):
            instant_budget = min(float(budget_isk), float(budget_isk) * float(budget_split.get("instant", 1.0)))
            planned_budget_cap = max(0.0, float(budget_isk) * float(budget_split.get("planned_sell", 0.0)))

        instant_filters = dict(filters_used)
        instant_filters["mode"] = "instant"
        instant_funnel = FilterFunnel()
        instant_explain = {}
        instant_candidates = compute_candidates(
            esi,
            source_orders,
            dest_orders,
            fees,
            instant_filters,
            dest_structure_id=dest_structure_id,
            route_context=route_context,
            funnel=instant_funnel,
            explain=instant_explain,
        )
        _apply_confidence_calibration_to_candidates(
            instant_candidates,
            cfg,
            route_id=str(route_tag),
            source_market=source_label,
            target_market=dest_label,
        )
        merge_reason_counts(combined_reason_counts, dict(instant_explain.get("reason_counts", {})))
        print(f"Baue {route_label} Portfolio (Instant-Phase)...")
        instant_picks, total_cost, total_profit, total_m3, instant_selected = choose_portfolio_for_route(
            esi,
            route_label,
            source_orders,
            dest_orders,
            instant_candidates,
            instant_filters,
            dest_structure_id,
            instant_budget,
            cargo_m3,
            fees,
            portfolio_cfg,
            cfg,
        )
        candidates.extend(instant_candidates)
        picks = list(instant_picks)
        selected_mode = f"instant_first/instant:{instant_selected}"

        remaining_budget = max(0.0, float(budget_isk) - total_cost)
        remaining_cargo = max(0.0, float(cargo_m3) - total_m3)
        _allow_planned = bool(filters_used.get("_profile_allow_planned_sell", True))
        if remaining_budget > 1e-6 and remaining_cargo > 1e-6 and _allow_planned:
            planned_filters = dict(filters_used)
            planned_filters["mode"] = "planned_sell"
            planned_funnel = FilterFunnel()
            planned_explain = {}
            planned_candidates = compute_candidates(
                esi,
                source_orders,
                dest_orders,
                fees,
                planned_filters,
                dest_structure_id=dest_structure_id,
                route_context=route_context,
                funnel=planned_funnel,
                explain=planned_explain,
            )
            _apply_confidence_calibration_to_candidates(
                planned_candidates,
                cfg,
                route_id=str(route_tag),
                source_market=source_label,
                target_market=dest_label,
            )
            merge_reason_counts(combined_reason_counts, dict(planned_explain.get("reason_counts", {})))
            instant_type_ids = {int(p.get("type_id")) for p in picks if p.get("type_id") is not None}
            planned_candidates_filtered = [c for c in planned_candidates if int(c.type_id) not in instant_type_ids]
            candidates.extend(planned_candidates_filtered)
            if planned_candidates_filtered:
                print(f"Baue {route_label} Portfolio (Planned-Sell-Ergaenzung)...")
                planned_budget = remaining_budget
                if bool(budget_split.get("enabled", False)):
                    planned_budget = min(planned_budget, planned_budget_cap)
                planned_picks, planned_cost, planned_profit, planned_m3, planned_selected = choose_portfolio_for_route(
                    esi,
                    route_label,
                    source_orders,
                    dest_orders,
                    planned_candidates_filtered,
                    planned_filters,
                    dest_structure_id,
                    planned_budget,
                    remaining_cargo,
                    fees,
                    portfolio_cfg,
                    cfg,
                )
                if planned_picks:
                    picks.extend(planned_picks)
                    selected_mode = f"instant_first/mixed:{planned_selected}"
            for k, v in planned_funnel.stage_stats.items():
                if k in instant_funnel.stage_stats:
                    instant_funnel.stage_stats[k] += int(v)
            instant_funnel.rejections.extend(planned_funnel.rejections)
        explain = {"reason_counts": combined_reason_counts}
        funnel = instant_funnel
    else:
        candidates = compute_candidates(
            esi,
            source_orders,
            dest_orders,
            fees,
            filters_used,
            dest_structure_id=dest_structure_id,
            route_context=route_context,
            funnel=funnel,
            explain=explain,
        )
        _apply_confidence_calibration_to_candidates(
            candidates,
            cfg,
            route_id=str(route_tag),
            source_market=source_label,
            target_market=dest_label,
        )
        print(f"Baue {route_label} Portfolio...")
        picks, _, _, _, selected_mode = choose_portfolio_for_route(
            esi,
            route_label,
            source_orders,
            dest_orders,
            candidates,
            filters_used,
            dest_structure_id,
            budget_isk,
            cargo_m3,
            fees,
            portfolio_cfg,
            cfg,
        )
    if selected_mode == "fallback":
        print("    * Hinweis: es wurden keine passenden Kaufauftraege gefunden, Vorschlaege basieren auf Verkaufsorder-Preisen.")

    picks, transport_summary = apply_route_costs_and_prune(picks, route_context, filters_used)
    _apply_confidence_calibration_to_picks(
        picks,
        cfg,
        route_id=str(route_tag),
        source_market=source_label,
        target_market=dest_label,
        transport_confidence=transport_summary.get("cost_model_confidence", "normal"),
    )

    # --- Profile post-build filters (applied after calibration so confidence is final) ---
    # Gap 1: min_profit_per_m3 gate (set by apply_profile_to_filters as _profile_min_profit_per_m3)
    pre_profile_pick_count = len(picks)
    picks = _apply_post_build_profile_filters(
        picks,
        filters_used,
        explain=explain,
        budget_isk=float(budget_isk),
        route_label=route_label,
    )
    if len(picks) != pre_profile_pick_count:
        if picks:
            picks, transport_summary = apply_route_costs_and_prune(picks, route_context, filters_used)
        else:
            transport_summary = dict(transport_summary)
            transport_summary["total_shipping_cost"] = 0.0
            transport_summary["total_route_cost"] = 0.0
            transport_summary["total_transport_cost"] = 0.0
            transport_summary["total_route_m3"] = 0.0

    # ---------------------------------------------------------------------------------

    result = _finalize_route_result(
        route_tag=route_tag,
        route_label=route_label,
        source_id=int(source_structure_id),
        dest_id=int(dest_structure_id),
        source_label=source_label,
        dest_label=dest_label,
        filters_used=filters_used,
        mode=mode,
        selected_mode=selected_mode,
        candidates=candidates,
        picks=picks,
        budget_isk=budget_isk,
        cargo_m3=cargo_m3,
        transport_summary=transport_summary,
        timestamp=timestamp,
        out_dir=out_dir,
        explain=explain,
        source_node_meta=source_node_meta,
        dest_node_meta=dest_node_meta,
        funnel=funnel,
    )
    result = _apply_confidence_calibration_to_route_result(result, cfg)
    return _finalize_route_result_runtime_state(result, cfg)


def _cfg_with_enabled_character_context(cfg: dict) -> dict:
    out = dict(cfg or {})
    char_cfg = out.get("character_context", {})
    if not isinstance(char_cfg, dict):
        char_cfg = {}
    char_cfg = dict(char_cfg)
    char_cfg["enabled"] = True
    out["character_context"] = char_cfg
    return out


def _run_auth_command(cfg: dict, action: str) -> None:
    cfg_for_auth = _cfg_with_enabled_character_context(cfg)
    char_cfg = resolve_character_context_cfg(cfg_for_auth)
    esi_cfg = cfg_for_auth.get("esi", {}) if isinstance(cfg_for_auth, dict) else {}
    if not isinstance(esi_cfg, dict):
        esi_cfg = {}
    client_id = str(esi_cfg.get("client_id", "") or "").strip()
    if not client_id:
        die("ESI client_id fehlt. Lege ihn lokal in config.local.json oder via ESI_CLIENT_ID an.")
    sso = EveSSOAuth(
        client_id=client_id,
        client_secret=str(esi_cfg.get("client_secret", "") or ""),
        callback_url=str(esi_cfg.get("callback_url", "http://localhost:12563/callback") or "http://localhost:12563/callback"),
        user_agent=str(esi_cfg.get("user_agent", "NullsecTrader/1.0") or "NullsecTrader/1.0"),
        token_path=str(char_cfg.get("token_path", "") or ""),
        metadata_path=str(char_cfg.get("metadata_path", "") or ""),
    )
    act = str(action or "status").strip().lower()
    if act in ("login", "authorize", "sync"):
        sso.ensure_token(requested_character_scopes(cfg_for_auth), allow_login=True)
    elif act not in ("status", "info"):
        die("Unbekannte auth-Aktion. Nutze 'login' oder 'status'.")
    status = sso.describe_token_status()
    print("EVE SSO")
    print(f"  Token Path: {status.get('token_path', '')}")
    print(f"  Token Present: {'yes' if bool(status.get('has_token', False)) else 'no'}")
    print(f"  Valid: {'yes' if bool(status.get('valid', False)) else 'no'}")
    if int(status.get("character_id", 0) or 0) > 0:
        print(f"  Character: {status.get('character_name', '')} ({int(status.get('character_id', 0) or 0)})")
    scopes = list(status.get("scopes", []) or [])
    if scopes:
        print(f"  Scopes: {' '.join(scopes)}")
    expires_at = int(status.get("expires_at", 0) or 0)
    if expires_at > 0:
        print(f"  Expires At (unix): {expires_at}")


def _run_character_command(cfg: dict, action: str) -> None:
    cfg_for_char = _cfg_with_enabled_character_context(cfg)
    act = str(action or "status").strip().lower()
    if act in ("sync", "refresh"):
        context = sync_character_profile(cfg_for_char, allow_login=True)
    elif act in ("status", "info"):
        context = resolve_character_context(cfg_for_char, replay_enabled=False, allow_live=False)
    else:
        die("Unbekannte character-Aktion. Nutze 'sync' oder 'status'.")
    for line in character_status_lines(context):
        print(line)


def run_cli() -> None:
    ensure_dirs()
    cli = parse_cli_args(sys.argv[1:])
    command = str(cli.get("command", "run") or "run").strip().lower()
    if command == "journal":
        run_journal_cli(list(cli.get("journal_argv", []) or []))
        return
    cfg = load_config(CONFIG_PATH)
    if not cfg:
        die("config.json fehlt oder ist unlesbar.")
    validation_result = validate_config(cfg)
    fail_on_invalid_config(validation_result)
    if command == "auth":
        _run_auth_command(cfg, str(cli.get("auth_action", "") or "status"))
        return
    if command == "character":
        _run_character_command(cfg, str(cli.get("character_action", "") or "status"))
        return

    # --- Risk Profile resolution ---
    from risk_profiles import (
        BUILTIN_PROFILES,
        apply_profile_to_portfolio_cfg,
        apply_profile_to_route_result,
        profile_header_lines,
        resolve_active_profile,
    )
    cli_profile = cli.get("profile") or None
    if cli_profile:
        cfg["_cli_risk_profile"] = str(cli_profile).strip().lower()
    active_profile_name, active_profile_params = resolve_active_profile(cfg)
    cfg["_active_risk_profile_name"] = active_profile_name
    cfg["_active_risk_profile_params"] = active_profile_params
    print("")
    for line in profile_header_lines(active_profile_name, active_profile_params):
        print(line)
    print("")
    # --------------------------------

    calibration_runtime = _build_confidence_calibration_runtime(cfg)
    if str(calibration_runtime.get("warning", "") or ""):
        print(f"Kalibrierung: {calibration_runtime['warning']}")
    personal_calibration_runtime = _personal_calibration_runtime(cfg)

    replay_cfg = cfg.get("replay", {})
    replay_enabled = bool(replay_cfg.get("enabled", False))
    character_context = resolve_character_context(cfg, replay_enabled=replay_enabled)
    cfg["_character_context"] = character_context
    if bool(character_context.get("enabled", False)) or bool(character_context.get("available", False)):
        print("")
        for line in character_status_lines(character_context):
            print(line)
        print("")
    personal_history_lines = personal_history_layer_status_lines(
        personal_calibration_runtime.get("summary"),
        personal_calibration_runtime.get("layer"),
    )
    if personal_history_lines:
        print("")
        for line in personal_history_lines:
            print(line)
        print("")

    o4t_id, cj6_id = _resolve_primary_structure_ids(cfg)
    route_mode = _normalize_route_mode(cfg.get("route_mode", "roundtrip"))
    chain_runtime = _resolve_chain_runtime(cfg, o4t_id, cj6_id)
    chain_enabled = bool(chain_runtime["chain_enabled"])
    chain_nodes = list(chain_runtime["chain_nodes"])
    fallback_to_non_chain_on_middle_failure = bool(chain_runtime["fallback_to_non_chain_on_middle_failure"])
    chain_leg_budget_util_min_pct = float(chain_runtime["chain_leg_budget_util_min_pct"])
    chain_return_mode = str(chain_runtime["chain_return_mode"])
    chain_return_overrides = dict(chain_runtime["chain_return_overrides"])

    if cli.get("snapshot_only"):
        snap_structs = cli.get("structures")
        if snap_structs is None:
            snap_structs = [int(o4t_id), int(cj6_id)]
            if chain_enabled:
                snap_structs = [int(n["id"]) for n in chain_nodes]
        run_snapshot_only(cfg, snap_structs, snapshot_out=cli.get("snapshot_out"))
        return

    if not replay_enabled and not _has_live_esi_credentials(cfg):
        die("Fehlende ESI-Credentials. Setze ESI_CLIENT_ID/ESI_CLIENT_SECRET oder nutze config.local.json.")

    defaults = cfg["defaults"]
    cargo_default = str(defaults["cargo_m3"])
    budget_default = fmt_isk(defaults["budget_isk"])

    cargo_cli = cli.get("cargo_m3", None)
    budget_cli = cli.get("budget_isk", None)
    if cargo_cli is None:
        cargo_s = input_with_default("Gib freien Cargo in m3 ein", cargo_default)
        try:
            cargo_m3 = float(cargo_s)
        except Exception:
            die("Eingabe ungueltig. Beispiel Cargo 10000 und Budget 500m oder 2.5b")
    else:
        cargo_m3 = float(cargo_cli)

    if budget_cli is None:
        budget_s = input_with_default("Gib Trading Budget in ISK ein", budget_default)
        try:
            budget_isk = parse_isk(budget_s)
        except Exception:
            die("Eingabe ungueltig. Beispiel Cargo 10000 und Budget 500m oder 2.5b")
    else:
        budget_isk = int(budget_cli)

    if cargo_m3 <= 0 or budget_isk <= 0:
        die("Cargo und Budget muessen positiv sein.")

    character_summary = build_character_context_summary(character_context, budget_isk=budget_isk)
    cfg["_character_context_summary"] = character_summary
    if bool(character_summary.get("budget_exceeds_wallet", False)):
        print(
            "WARN: Budget liegt ueber Wallet-Balance um "
            f"{fmt_isk(float(character_summary.get('budget_gap_isk', 0.0) or 0.0))}."
        )

    structure_labels, required_structure_ids = _build_structure_context(o4t_id, cj6_id, chain_enabled, chain_nodes)
    node_catalog = _resolve_node_catalog(cfg, chain_nodes)
    route_search_cfg = _resolve_route_search_cfg(cfg)
    route_profiles_cfg = _resolve_route_profiles_cfg(cfg)
    if bool(route_search_cfg.get("enabled", False)):
        route_profiles = build_route_search_profiles(node_catalog, cfg)
    else:
        route_profiles = build_route_profiles(chain_nodes, cfg) if bool(route_profiles_cfg.get("enabled", True)) else []

    default_replay_path = os.path.join(os.path.dirname(__file__), "replay_snapshot.json")
    replay_snapshot = None
    plan_snapshot_payload: dict | None = None
    structure_orders_by_id: dict[int, list[dict]] = {}
    replay_structs: dict | None = None
    if replay_enabled:
        replay_path = str(replay_cfg.get("snapshot_path", default_replay_path))
        replay_raw = load_json(replay_path, None)
        if not isinstance(replay_raw, dict):
            die(f"Replay aktiviert, aber Snapshot fehlt/ungueltig: {replay_path}")
        replay_snapshot = normalize_replay_snapshot(replay_raw, o4t_id, cj6_id)
        replay_type_cache = replay_snapshot.get("type_cache", {})
        if not isinstance(replay_type_cache, dict) or not replay_type_cache:
            replay_type_cache = load_json(TYPE_CACHE_PATH, {})
        esi = ReplayESIClient(replay_type_cache if isinstance(replay_type_cache, dict) else {})
        print(f"Replay-Mode aktiv. Nutze Snapshot: {replay_path}")
        snap_structs = replay_snapshot.get("structures", {})
        replay_structs = snap_structs if isinstance(snap_structs, dict) else {}
        plan_snapshot_payload = replay_snapshot
        if chain_enabled:
            missing_chain_nodes = []
            for n in chain_nodes:
                sid = int(n["id"])
                entry = snap_structs.get(str(sid), {})
                orders = entry.get("orders", []) if isinstance(entry, dict) else []
                if not (isinstance(orders, list) and len(orders) > 0):
                    missing_chain_nodes.append((sid, str(n["label"])))
            if missing_chain_nodes:
                missing_msg = ", ".join(f"{lbl} ({sid})" for sid, lbl in missing_chain_nodes)
                msg = f"Replay-Snapshot enthaelt keine Orders fuer Chain-Station(en): {missing_msg}"
                if fallback_to_non_chain_on_middle_failure:
                    print(f"WARN: {msg}. Fallback auf non-chain (O4T <-> CJ6).")
                    chain_enabled = False
                    chain_nodes = []
                    structure_labels, required_structure_ids = _build_structure_context(o4t_id, cj6_id, chain_enabled, chain_nodes)
                else:
                    die(msg)
        for sid in required_structure_ids:
            entry = snap_structs.get(str(int(sid)), {})
            orders = entry.get("orders", []) if isinstance(entry, dict) else []
            if not isinstance(orders, list):
                orders = []
            structure_orders_by_id[int(sid)] = orders
            print(f"  -> {structure_labels.get(int(sid), f'SID_{sid}')} Orders aus Snapshot: {len(orders)}")
        missing = [sid for sid in required_structure_ids if not structure_orders_by_id.get(int(sid))]
        if missing:
            missing_s = ", ".join(str(x) for x in sorted(missing))
            die(f"Replay-Snapshot enthaelt keine Orders fuer benoetigte Strukturen: {missing_s}")
    else:
        esi = ESIClient(cfg)
        print("Fuehre ESI-Preflight durch...")
        try:
            for sid in sorted(required_structure_ids):
                esi.preflight_structure_request(int(sid))
        except SystemExit:
            if chain_enabled and fallback_to_non_chain_on_middle_failure:
                print("WARN: Kein Zugriff auf mindestens eine Chain-Structure. Fallback auf non-chain (O4T <-> CJ6).")
                chain_enabled = False
                chain_nodes = []
                structure_labels, required_structure_ids = _build_structure_context(o4t_id, cj6_id, chain_enabled, chain_nodes)
                for sid in sorted(required_structure_ids):
                    esi.preflight_structure_request(int(sid))
            else:
                raise

        print("Lade Marktorders. Das kann beim ersten Mal etwas dauern.")
        for sid in sorted(required_structure_ids):
            lbl = structure_labels.get(int(sid), f"SID_{sid}")
            print(f"  -> Lade {lbl} Structure ({sid})...")
            orders = esi.fetch_structure_orders(int(sid))
            structure_orders_by_id[int(sid)] = orders if isinstance(orders, list) else []
            print(f"    {len(structure_orders_by_id[int(sid)])} Orders geladen")

    if route_profiles:
        used_labels = set()
        for p in route_profiles:
            used_labels.add(normalize_location_label(str(p.get("from", ""))))
            used_labels.add(normalize_location_label(str(p.get("to", ""))))
        for lbl in sorted(used_labels):
            node = node_catalog.get(lbl)
            if not isinstance(node, dict):
                continue
            nid = int(node.get("id", 0) or 0)
            if nid <= 0 or nid in structure_orders_by_id:
                continue
            orders = _fetch_orders_for_node(esi=esi, node=node, replay_enabled=replay_enabled, replay_structs=replay_structs)
            structure_orders_by_id[nid] = orders if isinstance(orders, list) else []
            kind = str(node.get("kind", "structure"))
            if kind == "location":
                print(
                    f"  -> Lade {node.get('label', 'location')} "
                    f"(location_id {nid}, region {int(node.get('region_id', 0) or 0)}): "
                    f"{len(structure_orders_by_id[nid])} Orders"
                )
            else:
                print(f"  -> Lade {node.get('label', 'structure')} Structure ({nid}): {len(structure_orders_by_id[nid])} Orders")

    snapshot = {
        "timestamp": int(time.time()),
        "structures": {str(int(sid)): {"orders_count": len(structure_orders_by_id.get(int(sid), []))} for sid in sorted(required_structure_ids)},
    }
    save_json(os.path.join(os.path.dirname(__file__), "market_snapshot.json"), snapshot)
    if not replay_enabled:
        cached_types_from_disk = load_json(TYPE_CACHE_PATH, {})
        live_type_cache = getattr(esi, "type_cache", {})
        merged_type_cache = {}
        if isinstance(cached_types_from_disk, dict):
            merged_type_cache.update(cached_types_from_disk)
        if isinstance(live_type_cache, dict):
            merged_type_cache.update(live_type_cache)
        plan_snapshot_payload = make_snapshot_payload(structure_orders_by_id, merged_type_cache)
    if not replay_enabled and bool(replay_cfg.get("write_snapshot_after_fetch", True)):
        replay_path = str(replay_cfg.get("snapshot_path", default_replay_path))
        replay_payload = plan_snapshot_payload if isinstance(plan_snapshot_payload, dict) else make_snapshot_payload(structure_orders_by_id, {})
        save_json(replay_path, replay_payload)
        print(f"Replay-Snapshot geschrieben: {replay_path}")

    if bool(resolve_character_context_cfg(cfg).get("apply_skill_fee_overrides", True)):
        fees, fee_override_meta = apply_character_fee_overrides(cfg["fees"], character_context)
    else:
        fees, fee_override_meta = dict(cfg["fees"]), {"applied": False, "source": str(character_context.get("source", "default") or "default"), "skills": {}}
    cfg["_character_fee_override_meta"] = fee_override_meta
    if bool(fee_override_meta.get("applied", False)):
        print(
            "Character Fee Override aktiv: "
            f"{fee_override_meta['skills']}"
        )
    # Apply active risk profile to portfolio config (tighten-only)
    port_cfg = apply_profile_to_portfolio_cfg(active_profile_params, dict(cfg["portfolio"]))
    capital_flow_cfg = _resolve_capital_flow_cfg(cfg)
    strict_mode_cfg = _resolve_strict_mode_cfg(cfg)
    route_wide_scan_cfg = _resolve_route_wide_scan_cfg(cfg)
    forward_filters, return_filters, forward_mode, return_mode = _prepare_trade_filters(cfg)

    # Block planned_sell phase if profile disallows it
    _profile_allows_planned = bool(active_profile_params.get("allow_planned_sell", True))
    if not _profile_allows_planned:
        if str(forward_mode).lower() in ("planned_sell",):
            forward_mode = "instant"
        if str(return_mode).lower() in ("planned_sell",):
            return_mode = "instant"
    structure_region_map = _resolve_structure_region_map(cfg, emit_info=True)
    if structure_region_map and hasattr(esi, "type_cache") and isinstance(getattr(esi, "type_cache", None), dict):
        esi.type_cache["_structure_region_map"] = {str(int(k)): int(v) for k, v in structure_region_map.items()}
        for sid, rid in structure_region_map.items():
            esi.type_cache[f"_sid_region_{int(sid)}"] = int(rid)
    if hasattr(esi, "structure_region_map"):
        try:
            esi.structure_region_map = {int(k): int(v) for k, v in structure_region_map.items()}
        except Exception:
            pass

    print("")
    print("=== BERECHNE TRADE-KANDIDATEN ===")
    out_dir = os.path.dirname(__file__)
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    plan_timestamp = _stable_plan_timestamp(plan_snapshot_payload, timestamp)
    plan_id = make_run_id(
        plan_timestamp,
        stable_suffix_source=_build_plan_id_seed(
            snapshot_payload=plan_snapshot_payload,
            budget_isk=float(budget_isk),
            cargo_m3=float(cargo_m3),
            active_profile_name=active_profile_name,
            route_mode=route_mode,
            forward_mode=str(forward_mode or ""),
            return_mode=str(return_mode or ""),
            route_search_cfg=route_search_cfg,
            route_profiles=route_profiles,
            chain_enabled=chain_enabled,
        ),
    )
    plan_created_at = utc_now_iso()
    created_files = []
    route_profiles_active = False

    if route_profiles:
        route_results: list[dict] = []
        for i, profile in enumerate(route_profiles, start=1):
            src_norm = normalize_location_label(profile.get("from", ""))
            dst_norm = normalize_location_label(profile.get("to", ""))
            src_node = node_catalog.get(src_norm)
            dst_node = node_catalog.get(dst_norm)
            if not src_node or not dst_node:
                continue
            p_mode = str(profile.get("mode", "")).strip().lower()
            active_mode = p_mode if p_mode in ("instant", "fast_sell", "planned_sell", "instant_first") else forward_mode
            route_id = str(profile.get("id", f"profile_{i}"))
            result = run_route(
                esi=esi,
                source_structure_id=int(src_node["id"]),
                dest_structure_id=int(dst_node["id"]),
                route_tag=route_id,
                source_label=str(src_node["label"]),
                dest_label=str(dst_node["label"]),
                filters=forward_filters,
                portfolio_cfg=port_cfg,
                fees=fees,
                mode=active_mode,
                replay_cfg=replay_cfg,
                replay_snapshot=replay_snapshot,
                structure_orders_by_id=structure_orders_by_id,
                budget_isk=float(budget_isk),
                cargo_m3=float(cargo_m3),
                cfg=cfg,
                timestamp=timestamp,
                out_dir=out_dir,
                source_node_meta=src_node,
                dest_node_meta=dst_node,
                preferred_shipping_lane_id=str(profile.get("shipping_lane_id", "") or ""),
            )
            filtered_picks = enforce_route_destination(list(result.get("picks", [])), str(dst_node.get("label", "")))
            if len(filtered_picks) != len(list(result.get("picks", []))):
                result["picks"] = filtered_picks
                _refresh_route_result_from_current_picks(result)
                _apply_internal_self_haul_operational_filter(result, cfg)
            # Apply profile-adjusted route score for leaderboard ranking
            apply_profile_to_route_result(active_profile_name, active_profile_params, result)
            result["_active_risk_profile"] = active_profile_name
            result["_active_risk_profile_params"] = dict(active_profile_params)
            _attach_runtime_advisories_to_result(result, character_context, personal_calibration_runtime, budget_isk=budget_isk)
            route_results.append(result)
            if "csv_path" in result:
                created_files.append(result["csv_path"])
            if "dump_path" in result:
                created_files.append(result["dump_path"])

        if route_results:
            route_profiles_active = True
            attach_plan_metadata(route_results, plan_id=plan_id, created_at=plan_created_at)

            # --- Do Not Trade evaluation ---
            from no_trade import evaluate_no_trade
            from execution_plan import write_no_trade_report
            from risk_profiles import BUILTIN_PROFILES as _ALL_PROFILES
            _no_trade_result = evaluate_no_trade(
                route_results,
                active_profile_name,
                active_profile_params,
                all_profiles=_ALL_PROFILES,
            )
            if not _no_trade_result["should_trade"]:
                _no_trade_path = os.path.join(out_dir, f"no_trade_{timestamp}.txt")
                write_no_trade_report(
                    _no_trade_path, timestamp,
                    _no_trade_result, active_profile_name, active_profile_params,
                )
                created_files.append(_no_trade_path)
                _rc_summary = ", ".join(r["code"] for r in _no_trade_result["reason_codes"][:3])
                print(f"  [DO NOT TRADE] Gründe: {_rc_summary}")
                print(f"  [DO NOT TRADE] Bericht: {_no_trade_path}")
            # --------------------------------

            execution_plan_path = os.path.join(out_dir, f"execution_plan_{timestamp}.txt")
            write_execution_plan_profiles(execution_plan_path, timestamp, route_results, detail_mode=bool(cli.get("detail", False)), compact_mode=bool(cli.get("compact", False)))
            created_files.append(execution_plan_path)
            plan_path = _write_trade_plan_artifact(
                route_results,
                plan_id=plan_id,
                created_at=plan_created_at,
                runtime_mode="route_profiles",
                primary_output_path=execution_plan_path,
                out_dir=out_dir,
            )
            created_files.append(plan_path)
            if bool(route_search_cfg.get("enabled", False)):
                leaderboard_path = os.path.join(out_dir, f"route_leaderboard_{timestamp}.txt")
                write_route_leaderboard(
                    path=leaderboard_path,
                    timestamp=timestamp,
                    route_results=route_results,
                    ranking_metric=str(route_search_cfg.get("ranking_metric", "risk_adjusted_expected_profit")),
                    max_routes=int(route_search_cfg.get("max_routes", 10)),
                    detail_mode=bool(cli.get("detail", False)),
                )
                created_files.append(leaderboard_path)

    if route_profiles_active:
        pass
    elif chain_enabled:
        forward_pairs = build_adjacent_pairs(chain_nodes, reverse=False)
        return_pairs = build_adjacent_pairs(chain_nodes, reverse=True)
        ordered_forward_nodes = list(chain_nodes)
        ordered_return_nodes = list(reversed(chain_nodes))
        forward_legs_for_summary: list[dict] = []
        emitted_legs: list[dict] = []
        capital_available = float(budget_isk)
        pending_releases_forward: dict[int, float] = {}
        pending_releases_return: dict[int, float] = {}
        route_wide_enabled = bool(route_wide_scan_cfg.get("enabled", False))

        for idx, (src_node, dst_node) in enumerate(forward_pairs, start=1):
            leg_idx0 = idx - 1
            leg_budget_isk, leg_budget_capped = _compute_chain_leg_budget(capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg)
            if route_wide_enabled:
                leg = run_route_wide_leg(
                    esi=esi,
                    route_tag=f"forward_leg{idx}",
                    source_node=src_node,
                    immediate_dest_node=dst_node,
                    source_index=leg_idx0,
                    chain_nodes_ordered=ordered_forward_nodes,
                    max_hops=int(route_wide_scan_cfg.get("max_hops_forward", 99)),
                    scan_cfg=route_wide_scan_cfg,
                    structure_orders_by_id=structure_orders_by_id,
                    filters=forward_filters,
                    portfolio_cfg=port_cfg,
                    fees=fees,
                    mode=forward_mode,
                    budget_isk=leg_budget_isk,
                    cargo_m3=cargo_m3,
                    cfg=cfg,
                    timestamp=timestamp,
                    out_dir=out_dir,
                )
            else:
                leg = run_route(
                    esi,
                    int(src_node["id"]),
                    int(dst_node["id"]),
                    f"forward_leg{idx}",
                    str(src_node["label"]),
                    str(dst_node["label"]),
                    forward_filters,
                    port_cfg,
                    fees,
                    forward_mode,
                    replay_cfg,
                    replay_snapshot,
                    structure_orders_by_id,
                    leg_budget_isk,
                    cargo_m3,
                    cfg,
                    timestamp,
                    out_dir,
                )
            if leg_budget_capped:
                why = leg.setdefault("why_out_summary", {})
                why["strict_leg_budget_cap"] = int(why.get("strict_leg_budget_cap", 0)) + 1
            capital_available = _apply_capital_flow_to_leg(
                leg,
                forward_mode,
                capital_available,
                capital_flow_cfg,
                current_leg_index=leg_idx0 if route_wide_enabled else None,
                pending_releases=pending_releases_forward if route_wide_enabled else None,
            )
            disabled, reason = evaluate_leg_disabled(leg, chain_leg_budget_util_min_pct)
            leg["leg_disabled"] = disabled
            leg["leg_disabled_reason"] = reason
            _attach_runtime_advisories_to_result(leg, character_context, personal_calibration_runtime, budget_isk=budget_isk)
            forward_legs_for_summary.append(leg)
            emitted_legs.append(leg)

        forward_active = any(not bool(leg.get("leg_disabled", False)) for leg in forward_legs_for_summary)
        attach_plan_metadata(forward_legs_for_summary, plan_id=plan_id, created_at=plan_created_at)
        forward_chain_summary = os.path.join(out_dir, f"forward_chain_summary_{timestamp}.txt")
        return_chain_summary = os.path.join(out_dir, f"return_chain_summary_{timestamp}.txt")
        write_chain_summary(forward_chain_summary, "Forward", timestamp, forward_legs_for_summary)

        chain_return_filters = dict(return_filters)
        chain_return_filters.update(chain_return_overrides)
        chain_return_filters["mode"] = chain_return_mode
        return_legs_for_summary: list[dict] = []

        if route_mode == "forward_only":
            print("route_mode=forward_only -> Return-Legs werden im Chain-Mode uebersprungen.")
            skip_reason = "route_mode_forward_only"
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, _ = _compute_chain_leg_budget(capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg)
                skipped = make_skipped_chain_leg(str(src_node["label"]), str(dst_node["label"]), skip_reason, chain_return_mode, chain_return_filters, leg_budget_isk, cargo_m3)
                capital_available = _apply_capital_flow_to_leg(
                    skipped,
                    chain_return_mode,
                    capital_available,
                    capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None,
                )
                return_legs_for_summary.append(skipped)
        elif chain_return_mode == "off":
            print("chain_return_mode=off -> Return-Legs werden im Chain-Mode uebersprungen.")
            skip_reason = "chain_return_mode_off"
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, _ = _compute_chain_leg_budget(capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg)
                skipped = make_skipped_chain_leg(str(src_node["label"]), str(dst_node["label"]), skip_reason, chain_return_mode, chain_return_filters, leg_budget_isk, cargo_m3)
                capital_available = _apply_capital_flow_to_leg(
                    skipped,
                    chain_return_mode,
                    capital_available,
                    capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None,
                )
                return_legs_for_summary.append(skipped)
        elif not forward_active:
            print("Keine aktive Forward-Leg -> Return-Legs werden im Chain-Mode uebersprungen.")
            skip_reason = "no_active_forward_leg"
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, _ = _compute_chain_leg_budget(capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg)
                skipped = make_skipped_chain_leg(str(src_node["label"]), str(dst_node["label"]), skip_reason, chain_return_mode, chain_return_filters, leg_budget_isk, cargo_m3)
                capital_available = _apply_capital_flow_to_leg(
                    skipped,
                    chain_return_mode,
                    capital_available,
                    capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None,
                )
                return_legs_for_summary.append(skipped)
        else:
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, leg_budget_capped = _compute_chain_leg_budget(capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg)
                if route_wide_enabled:
                    leg = run_route_wide_leg(
                        esi=esi,
                        route_tag=f"return_leg{idx}",
                        source_node=src_node,
                        immediate_dest_node=dst_node,
                        source_index=leg_idx0,
                        chain_nodes_ordered=ordered_return_nodes,
                        max_hops=int(route_wide_scan_cfg.get("max_hops_return", 99)),
                        scan_cfg=route_wide_scan_cfg,
                        structure_orders_by_id=structure_orders_by_id,
                        filters=chain_return_filters,
                        portfolio_cfg=port_cfg,
                        fees=fees,
                        mode=chain_return_mode,
                        budget_isk=leg_budget_isk,
                        cargo_m3=cargo_m3,
                        cfg=cfg,
                        timestamp=timestamp,
                        out_dir=out_dir,
                    )
                else:
                    leg = run_route(
                        esi,
                        int(src_node["id"]),
                        int(dst_node["id"]),
                        f"return_leg{idx}",
                        str(src_node["label"]),
                        str(dst_node["label"]),
                        chain_return_filters,
                        port_cfg,
                        fees,
                        chain_return_mode,
                        replay_cfg,
                        replay_snapshot,
                        structure_orders_by_id,
                        leg_budget_isk,
                        cargo_m3,
                        cfg,
                        timestamp,
                        out_dir,
                    )
                if leg_budget_capped:
                    why = leg.setdefault("why_out_summary", {})
                    why["strict_leg_budget_cap"] = int(why.get("strict_leg_budget_cap", 0)) + 1
                capital_available = _apply_capital_flow_to_leg(
                    leg,
                    chain_return_mode,
                    capital_available,
                    capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None,
                )
                disabled, reason = evaluate_leg_disabled(leg, chain_leg_budget_util_min_pct)
                leg["leg_disabled"] = disabled
                leg["leg_disabled_reason"] = reason
                _attach_runtime_advisories_to_result(leg, character_context, personal_calibration_runtime, budget_isk=budget_isk)
                return_legs_for_summary.append(leg)
                emitted_legs.append(leg)

        attach_plan_metadata(return_legs_for_summary, plan_id=plan_id, created_at=plan_created_at)
        write_chain_summary(return_chain_summary, "Return", timestamp, return_legs_for_summary)
        execution_plan_path = os.path.join(out_dir, f"execution_plan_{timestamp}.txt")
        write_execution_plan_chain(
            execution_plan_path,
            timestamp,
            forward_legs_for_summary,
            return_legs_for_summary,
            detail_mode=bool(cli.get("detail", False)),
        )
        plan_path = _write_trade_plan_artifact(
            forward_legs_for_summary + return_legs_for_summary,
            plan_id=plan_id,
            created_at=plan_created_at,
            runtime_mode="chain",
            primary_output_path=execution_plan_path,
            out_dir=out_dir,
        )
        for leg in emitted_legs:
            if "csv_path" in leg:
                created_files.append(leg["csv_path"])
            if "dump_path" in leg:
                created_files.append(leg["dump_path"])
        created_files.extend([forward_chain_summary, return_chain_summary, execution_plan_path, plan_path])
    else:
        capital_available = float(budget_isk)
        forward_budget_isk = capital_available if bool(capital_flow_cfg.get("enabled", False)) else float(budget_isk)
        forward_result = run_route(
            esi,
            o4t_id,
            cj6_id,
            "forward",
            structure_labels[o4t_id],
            structure_labels[cj6_id],
            forward_filters,
            port_cfg,
            fees,
            forward_mode,
            replay_cfg,
            replay_snapshot,
            structure_orders_by_id,
            forward_budget_isk,
            cargo_m3,
            cfg,
            timestamp,
            out_dir,
        )
        _attach_runtime_advisories_to_result(forward_result, character_context, personal_calibration_runtime, budget_isk=budget_isk)
        capital_available = _apply_capital_flow_to_leg(forward_result, forward_mode, capital_available, capital_flow_cfg)
        if route_mode == "forward_only":
            print("route_mode=forward_only -> Return-Route wird uebersprungen.")
            return_result = {"picks": [], "isk_used": 0.0, "profit_total": 0.0, "funnel": None}
        else:
            return_budget_isk = capital_available if bool(capital_flow_cfg.get("enabled", False)) else float(budget_isk)
            return_result = run_route(
                esi,
                cj6_id,
                o4t_id,
                "return",
                structure_labels[cj6_id],
                structure_labels[o4t_id],
                return_filters,
                port_cfg,
                fees,
                return_mode,
                replay_cfg,
                replay_snapshot,
                structure_orders_by_id,
                return_budget_isk,
                cargo_m3,
                cfg,
                timestamp,
                out_dir,
            )
            _attach_runtime_advisories_to_result(return_result, character_context, personal_calibration_runtime, budget_isk=budget_isk)
            capital_available = _apply_capital_flow_to_leg(return_result, return_mode, capital_available, capital_flow_cfg)

        attach_plan_metadata([forward_result, return_result], plan_id=plan_id, created_at=plan_created_at)
        summary_path = os.path.join(out_dir, f"roundtrip_plan_{timestamp}.txt")
        write_enhanced_summary(
            summary_path,
            forward_result["picks"],
            float(forward_result["isk_used"]),
            float(forward_result["profit_total"]),
            return_result["picks"],
            float(return_result["isk_used"]),
            float(return_result["profit_total"]),
            cargo_m3,
            budget_isk,
            forward_funnel=forward_result.get("funnel"),
            return_funnel=return_result.get("funnel"),
            run_uuid=plan_id,
        )
        plan_path = _write_trade_plan_artifact(
            [forward_result, return_result],
            plan_id=plan_id,
            created_at=plan_created_at,
            runtime_mode="roundtrip",
            primary_output_path=summary_path,
            out_dir=out_dir,
        )
        created_files.append(summary_path)
        created_files.append(plan_path)
        created_files.append(forward_result["csv_path"])
        created_files.append(forward_result["dump_path"])
        if route_mode != "forward_only":
            created_files.append(return_result["csv_path"])
            created_files.append(return_result["dump_path"])

    if hasattr(esi, "_type_cache_dirty") and int(getattr(esi, "_type_cache_dirty", 0)) > 0:
        try:
            save_json(TYPE_CACHE_PATH, getattr(esi, "type_cache", {}))
            save_json(HTTP_CACHE_PATH, getattr(esi, "_http_cache", {}))
            setattr(esi, "_type_cache_dirty", 0)
        except Exception:
            pass

    print("")
    if hasattr(esi, "get_performance_summary_lines"):
        try:
            for l in esi.get_performance_summary_lines():
                print(l)
        except Exception:
            pass
        print("")
    print(f"Plan ID: {plan_id}")
    print("Fertig!")
    print("=== ERSTELLTE DATEIEN ===")
    for p in created_files:
        print(p)
    print("market_snapshot.json erstellt.")
    print("")


def main() -> None:
    run_cli()


__all__ = [name for name in globals() if not name.startswith("__")]
