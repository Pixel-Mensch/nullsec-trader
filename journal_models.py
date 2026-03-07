from __future__ import annotations

from datetime import datetime, timezone
import hashlib


JOURNAL_ALLOWED_STATUSES = (
    "planned",
    "bought",
    "partially_sold",
    "sold",
    "abandoned",
    "invalidated",
)
JOURNAL_OPEN_STATUSES = ("planned", "bought", "partially_sold")
JOURNAL_CLOSED_STATUSES = ("sold", "abandoned", "invalidated")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_journal_timestamp(value: str | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return utc_now_iso()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(float(denominator)) <= 1e-12:
        return float(default)
    return float(numerator) / float(denominator)


def make_run_id(timestamp: str | None = None) -> str:
    base = str(timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")).strip() or "run"
    safe_base = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in base)
    digest = hashlib.sha1(f"{safe_base}|{utc_now_iso()}".encode("utf-8")).hexdigest()[:8]
    return f"plan_{safe_base}_{digest}"


def _make_pick_id(plan_id: str, route_id: str, type_id: int, occurrence: int, sell_at: str, exit_type: str) -> str:
    payload = f"{plan_id}|{route_id}|{int(type_id)}|{int(occurrence)}|{sell_at}|{exit_type}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"pick_{digest}"


def _node_location_id(node_info: object) -> int:
    if not isinstance(node_info, dict):
        return 0
    for key in ("node_id", "structure_id", "location_id", "id"):
        try:
            value = int(node_info.get(key, 0) or 0)
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def attach_plan_metadata(route_results: list[dict], plan_id: str, created_at: str) -> list[dict]:
    created_at_norm = normalize_journal_timestamp(created_at)
    for route_index, route in enumerate(list(route_results or []), start=1):
        if not isinstance(route, dict):
            continue
        route_id = str(route.get("route_id", route.get("route_tag", "")) or "").strip()
        if not route_id:
            route_id = f"route_{route_index}"
        route["plan_id"] = str(plan_id)
        route["source_run_id"] = str(plan_id)
        route["plan_created_at"] = created_at_norm
        route["route_id"] = route_id
        route["route_profile"] = str(route.get("route_profile", route_id) or route_id)
        route["route_sequence"] = int(route.get("route_sequence", route_index) or route_index)
        seen_keys: dict[str, int] = {}
        for pick in list(route.get("picks", []) or []):
            if not isinstance(pick, dict):
                continue
            type_id = int(pick.get("type_id", 0) or 0)
            sell_at = str(pick.get("sell_at", route.get("dest_label", "")) or route.get("dest_label", "")).strip()
            exit_type = str(
                pick.get(
                    "exit_type",
                    "instant" if bool(pick.get("instant", False)) or str(pick.get("mode", "")).lower() == "instant" else "speculative",
                )
                or "speculative"
            ).strip()
            key = f"{type_id}|{sell_at}|{exit_type}"
            occurrence = int(seen_keys.get(key, 0)) + 1
            seen_keys[key] = occurrence
            pick_id = str(pick.get("pick_id", "") or "").strip()
            if not pick_id:
                pick_id = _make_pick_id(str(plan_id), route_id, type_id, occurrence, sell_at, exit_type)
            pick["pick_id"] = pick_id
            pick["journal_entry_id"] = str(pick.get("journal_entry_id", "") or pick_id)
            pick["plan_id"] = str(plan_id)
            pick["source_run_id"] = str(plan_id)
            pick["route_id"] = route_id
            pick["route_profile"] = str(route.get("route_profile", route_id) or route_id)
            pick["route_label"] = str(route.get("route_label", ""))
            pick["source_market"] = str(route.get("source_label", pick.get("buy_at", "")) or pick.get("buy_at", ""))
            pick["target_market"] = str(route.get("dest_label", pick.get("sell_at", "")) or pick.get("sell_at", ""))
            pick["proposed_created_at"] = created_at_norm
            pick["raw_exit_confidence"] = float(
                pick.get("raw_exit_confidence", pick.get("exit_confidence", pick.get("strict_confidence_score", 0.0))) or 0.0
            )
            pick["raw_liquidity_confidence"] = float(
                pick.get("raw_liquidity_confidence", pick.get("liquidity_confidence", pick.get("fill_probability", 0.0))) or 0.0
            )
            pick["raw_transport_confidence"] = float(
                pick.get("raw_transport_confidence", pick.get("transport_confidence", 1.0)) or 1.0
            )
            pick["raw_overall_confidence"] = float(
                pick.get(
                    "raw_overall_confidence",
                    pick.get("raw_confidence", pick.get("overall_confidence", pick.get("strict_confidence_score", pick.get("fill_probability", 0.0)))),
                )
                or 0.0
            )
            pick["calibrated_exit_confidence"] = float(
                pick.get("calibrated_exit_confidence", pick.get("raw_exit_confidence", pick.get("exit_confidence", 0.0))) or 0.0
            )
            pick["calibrated_liquidity_confidence"] = float(
                pick.get("calibrated_liquidity_confidence", pick.get("raw_liquidity_confidence", pick.get("liquidity_confidence", 0.0))) or 0.0
            )
            pick["calibrated_transport_confidence"] = float(
                pick.get("calibrated_transport_confidence", pick.get("raw_transport_confidence", 1.0)) or 1.0
            )
            pick["calibrated_overall_confidence"] = float(
                pick.get("calibrated_overall_confidence", pick.get("calibrated_confidence", pick.get("raw_overall_confidence", 0.0))) or 0.0
            )
            pick["raw_confidence"] = float(
                pick.get("raw_confidence", pick.get("raw_overall_confidence", pick.get("overall_confidence", 0.0))) or 0.0
            )
            pick["calibrated_confidence"] = float(
                pick.get("calibrated_confidence", pick.get("calibrated_overall_confidence", pick.get("raw_confidence", 0.0))) or 0.0
            )
            pick["proposed_confidence"] = float(
                pick.get(
                    "proposed_confidence",
                    pick.get("raw_overall_confidence", pick.get("overall_confidence", pick.get("strict_confidence_score", pick.get("fill_probability", 0.0)))),
                )
                or 0.0
            )
    return route_results


def build_trade_plan_manifest(
    route_results: list[dict],
    plan_id: str,
    created_at: str,
    runtime_mode: str,
    primary_output_path: str = "",
) -> dict:
    created_at_norm = normalize_journal_timestamp(created_at)
    routes_out: list[dict] = []
    total_picks = 0
    for route in list(route_results or []):
        if not isinstance(route, dict):
            continue
        source_location_id = _node_location_id(route.get("source_node_info"))
        target_location_id = _node_location_id(route.get("dest_node_info"))
        character_summary = route.get("_character_context_summary", {})
        if not isinstance(character_summary, dict):
            character_summary = {}
        picks_out: list[dict] = []
        for pick in list(route.get("picks", []) or []):
            if not isinstance(pick, dict):
                continue
            picks_out.append(
                {
                    "journal_entry_id": str(pick.get("journal_entry_id", pick.get("pick_id", "")) or ""),
                    "pick_id": str(pick.get("pick_id", "") or ""),
                    "item_type_id": int(pick.get("type_id", 0) or 0),
                    "item_name": str(pick.get("name", "") or ""),
                    "proposed_qty": float(pick.get("qty", 0.0) or 0.0),
                    "proposed_buy_price": float(pick.get("buy_avg", 0.0) or 0.0),
                    "proposed_sell_price": float(pick.get("target_sell_price", pick.get("sell_avg", 0.0)) or 0.0),
                    "proposed_full_sell_profit": float(pick.get("gross_profit_if_full_sell", pick.get("profit", 0.0)) or 0.0),
                    "proposed_expected_profit": float(
                        pick.get("expected_realized_profit_90d", pick.get("expected_profit_90d", pick.get("profit", 0.0))) or 0.0
                    ),
                    "proposed_expected_days_to_sell": float(pick.get("expected_days_to_sell", 0.0) or 0.0),
                    "proposed_exit_type": str(
                        pick.get(
                            "exit_type",
                            "instant" if bool(pick.get("instant", False)) or str(pick.get("mode", "")).lower() == "instant" else "speculative",
                        )
                        or "speculative"
                    ),
                    "proposed_confidence": float(
                        pick.get("proposed_confidence", pick.get("raw_overall_confidence", pick.get("overall_confidence", pick.get("fill_probability", 0.0))))
                        or 0.0
                    ),
                    "proposed_exit_confidence_raw": float(
                        pick.get("raw_exit_confidence", pick.get("exit_confidence", pick.get("strict_confidence_score", 0.0))) or 0.0
                    ),
                    "proposed_liquidity_confidence_raw": float(
                        pick.get("raw_liquidity_confidence", pick.get("liquidity_confidence", pick.get("fill_probability", 0.0))) or 0.0
                    ),
                    "proposed_transport_confidence_raw": float(
                        pick.get("raw_transport_confidence", pick.get("transport_confidence", 1.0)) or 1.0
                    ),
                    "proposed_overall_confidence_raw": float(
                        pick.get("raw_overall_confidence", pick.get("raw_confidence", pick.get("overall_confidence", 0.0))) or 0.0
                    ),
                    "proposed_exit_confidence_calibrated": float(
                        pick.get("calibrated_exit_confidence", pick.get("raw_exit_confidence", pick.get("exit_confidence", 0.0))) or 0.0
                    ),
                    "proposed_liquidity_confidence_calibrated": float(
                        pick.get("calibrated_liquidity_confidence", pick.get("raw_liquidity_confidence", pick.get("liquidity_confidence", 0.0))) or 0.0
                    ),
                    "proposed_transport_confidence_calibrated": float(
                        pick.get("calibrated_transport_confidence", pick.get("raw_transport_confidence", 1.0)) or 1.0
                    ),
                    "proposed_overall_confidence_calibrated": float(
                        pick.get("calibrated_overall_confidence", pick.get("calibrated_confidence", pick.get("raw_overall_confidence", 0.0))) or 0.0
                    ),
                    "calibration_warning": str(pick.get("calibration_warning", "") or ""),
                    "proposed_expected_units_sold": float(pick.get("expected_units_sold_90d", 0.0) or 0.0),
                    "proposed_expected_units_unsold": float(pick.get("expected_units_unsold_90d", 0.0) or 0.0),
                    "source_market": str(pick.get("source_market", route.get("source_label", "")) or route.get("source_label", "")),
                    "target_market": str(pick.get("target_market", route.get("dest_label", "")) or route.get("dest_label", "")),
                    "source_location_id": int(pick.get("source_location_id", source_location_id) or source_location_id or 0),
                    "target_location_id": int(pick.get("target_location_id", target_location_id) or target_location_id or 0),
                    "route_id": str(pick.get("route_id", route.get("route_id", route.get("route_tag", ""))) or ""),
                    "route_profile": str(pick.get("route_profile", route.get("route_profile", route.get("route_tag", ""))) or ""),
                    "character_id": int(pick.get("character_id", character_summary.get("character_id", 0)) or 0),
                    "character_open_orders": int(pick.get("character_open_orders", 0) or 0),
                    "character_open_buy_orders": int(pick.get("character_open_buy_orders", 0) or 0),
                    "character_open_sell_orders": int(pick.get("character_open_sell_orders", 0) or 0),
                    "character_open_buy_isk_committed": float(pick.get("character_open_buy_isk_committed", 0.0) or 0.0),
                    "character_open_sell_units": float(pick.get("character_open_sell_units", 0.0) or 0.0),
                    "open_order_warning_tier": str(pick.get("open_order_warning_tier", "") or ""),
                    "open_order_warning_text": str(pick.get("open_order_warning_text", "") or ""),
                }
            )
        total_picks += len(picks_out)
        routes_out.append(
            {
                "route_id": str(route.get("route_id", route.get("route_tag", "")) or ""),
                "route_profile": str(route.get("route_profile", route.get("route_tag", "")) or ""),
                "route_label": str(route.get("route_label", "") or ""),
                "source_market": str(route.get("source_label", "") or ""),
                "target_market": str(route.get("dest_label", "") or ""),
                "route_confidence": float(route.get("route_confidence", 0.0) or 0.0),
                "raw_route_confidence": float(route.get("raw_route_confidence", route.get("route_confidence", 0.0)) or 0.0),
                "calibrated_route_confidence": float(
                    route.get("calibrated_route_confidence", route.get("route_confidence", 0.0)) or 0.0
                ),
                "transport_confidence": float(route.get("transport_confidence", 0.0) or 0.0),
                "raw_transport_confidence": float(
                    route.get("raw_transport_confidence", route.get("transport_confidence", 0.0)) or 0.0
                ),
                "calibrated_transport_confidence": float(
                    route.get("calibrated_transport_confidence", route.get("transport_confidence", 0.0)) or 0.0
                ),
                "capital_lock_risk": float(route.get("capital_lock_risk", 0.0) or 0.0),
                "calibration_warning": str(route.get("calibration_warning", "") or ""),
                "actionable": bool(route.get("route_actionable", False)),
                "route_prune_reason": str(route.get("route_prune_reason", "") or ""),
                "picks": picks_out,
            }
        )
    return {
        "schema_version": 2,
        "plan_id": str(plan_id),
        "source_run_id": str(plan_id),
        "created_at": created_at_norm,
        "runtime_mode": str(runtime_mode or ""),
        "primary_output_path": str(primary_output_path or ""),
        "route_count": len(routes_out),
        "pick_count": int(total_picks),
        "routes": routes_out,
    }


def compute_actual_days_to_sell(entry: dict) -> float | None:
    first_buy_at = str(entry.get("first_buy_at", "") or "").strip()
    last_sell_at = str(entry.get("last_sell_at", "") or "").strip()
    if not first_buy_at or not last_sell_at:
        return None
    try:
        start = datetime.fromisoformat(first_buy_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(last_sell_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    delta = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    return max(0.0, delta.total_seconds() / 86400.0)


def compute_realized_outcome_score(entry: dict) -> float:
    proposed_expected_profit = float(entry.get("proposed_expected_profit", 0.0) or 0.0)
    proposed_qty = float(entry.get("proposed_qty", 0.0) or 0.0)
    proposed_days = float(entry.get("proposed_expected_days_to_sell", 0.0) or 0.0)
    actual_profit = float(entry.get("actual_profit_net", 0.0) or 0.0)
    actual_sell_qty = float(entry.get("actual_sell_qty", 0.0) or 0.0)
    actual_days = compute_actual_days_to_sell(entry)
    profit_score = _clamp01(_safe_ratio(actual_profit, proposed_expected_profit, 0.0 if proposed_expected_profit > 0.0 else 1.0))
    qty_score = _clamp01(_safe_ratio(actual_sell_qty, proposed_qty, 0.0 if proposed_qty > 0.0 else 1.0))
    if actual_days is None or proposed_days <= 0.0:
        duration_score = 1.0 if actual_days is not None and actual_days <= 0.0 else 0.0
    else:
        duration_score = _clamp01(_safe_ratio(proposed_days, actual_days, 1.0))
    return _clamp01((profit_score * 0.60) + (qty_score * 0.25) + (duration_score * 0.15))


def entry_profit_delta(entry: dict) -> float:
    return float(entry.get("actual_profit_net", 0.0) or 0.0) - float(entry.get("proposed_expected_profit", 0.0) or 0.0)


__all__ = [
    "JOURNAL_ALLOWED_STATUSES",
    "JOURNAL_CLOSED_STATUSES",
    "JOURNAL_OPEN_STATUSES",
    "attach_plan_metadata",
    "build_trade_plan_manifest",
    "compute_actual_days_to_sell",
    "compute_realized_outcome_score",
    "entry_profit_delta",
    "make_run_id",
    "normalize_journal_timestamp",
    "utc_now_iso",
]
