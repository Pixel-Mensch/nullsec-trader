from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from journal_models import (
    compute_actual_days_to_sell,
    effective_entry_days_to_sell,
    effective_entry_first_buy_at,
    effective_entry_profit_net,
    effective_entry_qty,
    effective_entry_status,
    effective_entry_trade_history_source,
    utc_now_iso,
)


CONFIDENCE_DEFINITIONS = {
    "exit_confidence": "Confidence that the chosen exit mechanic and target price can be executed at the destination market.",
    "liquidity_confidence": "Confidence that the target market can absorb the proposed position size inside the selling horizon.",
    "transport_confidence": "Confidence that the route's transport-cost model is usable and conservative enough for real hauling.",
    "overall_confidence": "Conservative combined confidence across exit, liquidity and transport. This is the confidence that should drive ranking decisions.",
}

CONFIDENCE_DIMENSIONS = ("overall", "exit", "liquidity", "transport")
DEFAULT_CONFIDENCE_BUCKETS = (0.2, 0.4, 0.6, 0.8, 1.0)
PERSONAL_HISTORY_QUALITY_LEVELS = ("none", "very_low", "low", "usable", "good")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_confidence_calibration_cfg(cfg: dict | None) -> dict:
    root = cfg if isinstance(cfg, dict) else {}
    raw = root.get("confidence_calibration", root)
    if not isinstance(raw, dict):
        raw = {}
    buckets = []
    for value in list(raw.get("buckets", DEFAULT_CONFIDENCE_BUCKETS) or DEFAULT_CONFIDENCE_BUCKETS):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed <= 0.0:
            continue
        buckets.append(_clamp01(parsed))
    buckets = sorted(set(buckets))
    if not buckets or buckets[-1] < 1.0:
        buckets.append(1.0)
    scope = str(raw.get("scope", "global") or "global").strip().lower()
    if scope not in ("global", "target_market", "route_id", "market_pair", "exit_type"):
        scope = "global"
    return {
        "enabled": bool(raw.get("enabled", False)),
        "apply_to_decisions": bool(raw.get("apply_to_decisions", True)),
        "journal_db_path": str(raw.get("journal_db_path", "") or ""),
        "min_samples": max(1, int(raw.get("min_samples", 8) or 8)),
        "min_samples_per_bucket": max(1, int(raw.get("min_samples_per_bucket", 3) or 3)),
        "buckets": buckets,
        "scope": scope,
        "scope_fallback_to_global": bool(raw.get("scope_fallback_to_global", True)),
        "profit_close_ratio": max(0.0, float(raw.get("profit_close_ratio", 0.80) or 0.80)),
        "profit_close_tolerance_isk": max(0.0, float(raw.get("profit_close_tolerance_isk", 0.0) or 0.0)),
        "open_position_horizon_factor": max(0.0, float(raw.get("open_position_horizon_factor", 1.0) or 1.0)),
        "stale_open_position_days": max(0.0, float(raw.get("stale_open_position_days", 14.0) or 14.0)),
        "optimism_gap_warn": max(0.0, float(raw.get("optimism_gap_warn", 0.10) or 0.10)),
    }


def transport_confidence_to_score(value: object) -> float:
    if isinstance(value, (int, float)):
        return _clamp01(float(value))
    txt = str(value or "").strip().lower()
    if txt in ("blocked", "none"):
        return 0.0
    if txt in ("exception",):
        return 0.55
    if txt in ("low",):
        return 0.35
    return 1.0 if txt else 1.0


def overall_raw_confidence_from_components(
    exit_confidence: float,
    liquidity_confidence: float,
    transport_confidence: float,
    explicit_overall: float | None = None,
) -> float:
    base = min(_clamp01(exit_confidence), _clamp01(liquidity_confidence))
    if explicit_overall is not None:
        base = min(base, _clamp01(float(explicit_overall)))
    return _clamp01(min(base, _clamp01(transport_confidence)))


def _open_days(entry: dict, now: datetime | None = None) -> float:
    current_now = now or datetime.now(timezone.utc)
    first_buy = _parse_dt(str(entry.get("first_buy_at", "") or ""))
    if first_buy is None:
        first_buy = _parse_dt(str(entry.get("created_at", "") or ""))
    if first_buy is None:
        return 0.0
    return max(0.0, (current_now - first_buy).total_seconds() / 86400.0)


def _effective_open_days(entry: dict, now: datetime | None = None) -> float:
    current_now = now or datetime.now(timezone.utc)
    first_buy = _parse_dt(effective_entry_first_buy_at(entry))
    if first_buy is None:
        return 0.0
    return max(0.0, (current_now - first_buy).total_seconds() / 86400.0)


def classify_trade_outcome(entry: dict, cfg: dict, now: datetime | None = None) -> dict:
    cal_cfg = resolve_confidence_calibration_cfg(cfg)
    status = str(entry.get("status", "") or "").strip().lower()
    proposed_qty = max(0.0, _as_float(entry.get("proposed_qty", 0.0)))
    expected_profit = _as_float(entry.get("proposed_expected_profit", 0.0))
    expected_days = max(0.0, _as_float(entry.get("proposed_expected_days_to_sell", 0.0)))
    actual_buy_qty = max(0.0, _as_float(entry.get("actual_buy_qty", 0.0)))
    actual_sell_qty = max(0.0, _as_float(entry.get("actual_sell_qty", 0.0)))
    actual_profit = _as_float(entry.get("actual_profit_net", 0.0))
    actual_days = compute_actual_days_to_sell(entry)
    open_days = _open_days(entry, now=now)
    stale_open_threshold = max(
        cal_cfg["stale_open_position_days"],
        expected_days * cal_cfg["open_position_horizon_factor"],
    )
    closed_status = status in ("sold", "abandoned", "invalidated")
    stale_open_position = status in ("planned", "bought", "partially_sold") and open_days >= stale_open_threshold
    eligible = bool(closed_status or stale_open_position)
    fully_sold = bool(actual_buy_qty > 0.0 and actual_sell_qty + 1e-9 >= actual_buy_qty)
    sold_within_horizon = bool(fully_sold and actual_days is not None and expected_days > 0.0 and actual_days <= expected_days + 1e-9)
    profit_positive = bool(actual_profit > 0.0)
    profit_threshold = float(expected_profit) * float(cal_cfg["profit_close_ratio"])
    profit_close = bool(
        actual_profit >= (profit_threshold - float(cal_cfg["profit_close_tolerance_isk"]))
        if expected_profit > 0.0
        else actual_profit > 0.0
    )
    remaining_qty = max(0.0, actual_buy_qty - actual_sell_qty)
    position_stuck = bool(
        status in ("abandoned", "invalidated")
        or (stale_open_position and remaining_qty > 1e-9)
        or (closed_status and not fully_sold and actual_buy_qty > 0.0)
    )
    qty_realization_ratio = (actual_sell_qty / proposed_qty) if proposed_qty > 1e-9 else (1.0 if actual_sell_qty <= 1e-9 else 0.0)
    profit_delta = actual_profit - expected_profit
    sell_duration_delta = (actual_days - expected_days) if actual_days is not None and expected_days > 0.0 else None
    success_score = _clamp01(
        (0.35 if fully_sold else 0.0)
        + (0.20 if sold_within_horizon else 0.0)
        + (0.20 if profit_positive else 0.0)
        + (0.15 if profit_close else 0.0)
        + (0.10 if not position_stuck else 0.0)
    )
    return {
        "eligible": eligible,
        "status": status,
        "fully_sold": fully_sold,
        "sold_within_horizon": sold_within_horizon,
        "profit_positive": profit_positive,
        "profit_close": profit_close,
        "position_stuck": position_stuck,
        "qty_realization_ratio": qty_realization_ratio,
        "profit_delta": profit_delta,
        "sell_duration_delta": sell_duration_delta,
        "success_score": success_score,
        "actual_days_to_sell": actual_days,
        "open_days": open_days,
    }


def classify_personal_trade_outcome(entry: dict, cfg: dict | None, now: datetime | None = None) -> dict:
    cal_cfg = resolve_confidence_calibration_cfg(cfg)
    status = effective_entry_status(entry)
    proposed_qty = max(0.0, _as_float(entry.get("proposed_qty", 0.0)))
    expected_profit = _as_float(entry.get("proposed_expected_profit", 0.0))
    expected_days = max(0.0, _as_float(entry.get("proposed_expected_days_to_sell", 0.0)))
    actual_buy_qty = max(0.0, effective_entry_qty(entry, "buy"))
    actual_sell_qty = max(0.0, effective_entry_qty(entry, "sell"))
    actual_profit = effective_entry_profit_net(entry)
    actual_days = effective_entry_days_to_sell(entry)
    open_days = _effective_open_days(entry, now=now)
    stale_open_threshold = max(
        cal_cfg["stale_open_position_days"],
        expected_days * cal_cfg["open_position_horizon_factor"],
    )
    closed_status = status in ("sold", "abandoned", "invalidated")
    stale_open_position = status in ("planned", "bought", "partially_sold") and open_days >= stale_open_threshold
    eligible = bool(closed_status or stale_open_position)
    fully_sold = bool(actual_buy_qty > 0.0 and actual_sell_qty + 1e-9 >= actual_buy_qty)
    sold_within_horizon = bool(fully_sold and actual_days is not None and expected_days > 0.0 and actual_days <= expected_days + 1e-9)
    profit_positive = bool(actual_profit > 0.0)
    profit_threshold = float(expected_profit) * float(cal_cfg["profit_close_ratio"])
    profit_close = bool(
        actual_profit >= (profit_threshold - float(cal_cfg["profit_close_tolerance_isk"]))
        if expected_profit > 0.0
        else actual_profit > 0.0
    )
    remaining_qty = max(0.0, actual_buy_qty - actual_sell_qty)
    position_stuck = bool(
        status in ("abandoned", "invalidated")
        or (stale_open_position and remaining_qty > 1e-9)
        or (closed_status and not fully_sold and actual_buy_qty > 0.0)
    )
    qty_realization_ratio = (actual_sell_qty / proposed_qty) if proposed_qty > 1e-9 else (1.0 if actual_sell_qty <= 1e-9 else 0.0)
    profit_delta = actual_profit - expected_profit
    sell_duration_delta = (actual_days - expected_days) if actual_days is not None and expected_days > 0.0 else None
    reconciliation_status = str(entry.get("reconciliation_status", "") or "").strip().lower()
    fee_match_quality = str(entry.get("fee_match_quality", "") or "").strip().lower()
    wallet_data_freshness = str(entry.get("wallet_data_freshness", "") or "").strip().lower()
    wallet_history_quality = str(entry.get("wallet_history_quality", "") or "").strip().lower()
    history_source = effective_entry_trade_history_source(entry)
    uncertain_match = "uncertain" in reconciliation_status
    wallet_unmatched = reconciliation_status == "wallet_unmatched"
    stale_basis = wallet_data_freshness == "stale"
    truncated_basis = bool(entry.get("wallet_history_truncated", False)) or wallet_history_quality == "truncated"
    reliable_outcome = bool(eligible and not uncertain_match and not wallet_unmatched and fee_match_quality != "uncertain")
    success_score = _clamp01(
        (0.35 if fully_sold else 0.0)
        + (0.20 if sold_within_horizon else 0.0)
        + (0.20 if profit_positive else 0.0)
        + (0.15 if profit_close else 0.0)
        + (0.10 if not position_stuck else 0.0)
    )
    return {
        "eligible": eligible,
        "status": status,
        "fully_sold": fully_sold,
        "sold_within_horizon": sold_within_horizon,
        "profit_positive": profit_positive,
        "profit_close": profit_close,
        "position_stuck": position_stuck,
        "qty_realization_ratio": qty_realization_ratio,
        "profit_delta": profit_delta,
        "sell_duration_delta": sell_duration_delta,
        "success_score": success_score,
        "actual_days_to_sell": actual_days,
        "open_days": open_days,
        "history_source": history_source,
        "uncertain_match": uncertain_match,
        "wallet_unmatched": wallet_unmatched,
        "stale_basis": stale_basis,
        "truncated_basis": truncated_basis,
        "fee_match_quality": fee_match_quality or "none",
        "reliable_outcome": reliable_outcome,
    }


def _bucket_bounds(buckets: list[float]) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    lower = 0.0
    for upper in list(buckets or DEFAULT_CONFIDENCE_BUCKETS):
        hi = _clamp01(float(upper))
        if hi <= lower:
            continue
        out.append((lower, hi, f"{lower:.1f}-{hi:.1f}"))
        lower = hi
    if not out or out[-1][1] < 1.0:
        out.append((lower, 1.0, f"{lower:.1f}-1.0"))
    return out


def _bucket_label(value: float, buckets: list[float]) -> str:
    raw = _clamp01(value)
    for lower, upper, label in _bucket_bounds(buckets):
        if raw <= upper + 1e-12:
            return label
    return _bucket_bounds(buckets)[-1][2]


def _dimension_raw_value(entry: dict, dimension: str) -> float | None:
    dim = str(dimension or "overall").strip().lower()
    if dim == "exit":
        keys = ("proposed_exit_confidence_raw", "raw_exit_confidence", "exit_confidence")
    elif dim == "liquidity":
        keys = ("proposed_liquidity_confidence_raw", "raw_liquidity_confidence", "liquidity_confidence")
    elif dim == "transport":
        keys = ("proposed_transport_confidence_raw", "raw_transport_confidence", "transport_confidence")
    else:
        keys = ("proposed_overall_confidence_raw", "raw_overall_confidence", "proposed_confidence", "overall_confidence")
    for key in keys:
        if key not in entry:
            continue
        raw = entry.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        value = transport_confidence_to_score(raw) if dim == "transport" else _clamp01(_as_float(raw))
        return value
    return None


def _scope_key(entry: dict, scope: str) -> str:
    if scope == "target_market":
        return str(entry.get("target_market", "") or "(leer)")
    if scope == "route_id":
        return str(entry.get("route_id", "") or "(leer)")
    if scope == "market_pair":
        src = str(entry.get("source_market", "") or "(leer)")
        dst = str(entry.get("target_market", "") or "(leer)")
        return f"{src} -> {dst}"
    if scope == "exit_type":
        return str(entry.get("proposed_exit_type", entry.get("exit_type", "")) or "(leer)")
    return "global"


def _summarize_bucket(entries: list[dict], dimension: str) -> dict:
    count = len(entries)
    if count <= 0:
        return {
            "sample_count": 0,
            "avg_raw_confidence": 0.0,
            "actual_success_rate": 0.0,
            "full_sell_rate": 0.0,
            "within_horizon_rate": 0.0,
            "profit_positive_rate": 0.0,
            "profit_close_rate": 0.0,
            "stuck_rate": 0.0,
            "avg_profit_delta": 0.0,
            "avg_days_delta": 0.0,
            "avg_qty_realization_ratio": 0.0,
            "optimism_gap": 0.0,
        }
    raw_values = [_dimension_raw_value(entry, dimension) for entry in entries]
    raw_values = [float(v) for v in raw_values if v is not None]
    success_values = [_as_float(entry.get("success_score", 0.0)) for entry in entries]
    avg_raw = sum(raw_values) / len(raw_values) if raw_values else 0.0
    avg_success = sum(success_values) / len(success_values) if success_values else 0.0
    day_values = [entry.get("sell_duration_delta") for entry in entries if entry.get("sell_duration_delta") is not None]
    return {
        "sample_count": count,
        "avg_raw_confidence": avg_raw,
        "actual_success_rate": avg_success,
        "full_sell_rate": sum(1.0 for entry in entries if bool(entry.get("fully_sold", False))) / float(count),
        "within_horizon_rate": sum(1.0 for entry in entries if bool(entry.get("sold_within_horizon", False))) / float(count),
        "profit_positive_rate": sum(1.0 for entry in entries if bool(entry.get("profit_positive", False))) / float(count),
        "profit_close_rate": sum(1.0 for entry in entries if bool(entry.get("profit_close", False))) / float(count),
        "stuck_rate": sum(1.0 for entry in entries if bool(entry.get("position_stuck", False))) / float(count),
        "avg_profit_delta": sum(_as_float(entry.get("profit_delta", 0.0)) for entry in entries) / float(count),
        "avg_days_delta": (sum(_as_float(v) for v in day_values) / float(len(day_values))) if day_values else 0.0,
        "avg_qty_realization_ratio": sum(_as_float(entry.get("qty_realization_ratio", 0.0)) for entry in entries) / float(count),
        "optimism_gap": avg_raw - avg_success,
    }


def _build_scope_model(entries: list[dict], dimension: str, cfg: dict, scope_kind: str, scope_key: str) -> dict:
    bounds = _bucket_bounds(list(cfg.get("buckets", DEFAULT_CONFIDENCE_BUCKETS)))
    buckets_out: list[dict] = []
    running_monotone = 0.0
    for lower, upper, label in bounds:
        bucket_entries = []
        for entry in entries:
            raw_value = _dimension_raw_value(entry, dimension)
            if raw_value is None:
                continue
            if lower - 1e-12 < raw_value <= upper + 1e-12 or (lower <= 1e-12 and raw_value <= upper + 1e-12):
                bucket_entries.append(entry)
        summary = _summarize_bucket(bucket_entries, dimension)
        monotone = running_monotone
        if summary["sample_count"] > 0:
            monotone = max(running_monotone, float(summary["actual_success_rate"]))
            running_monotone = monotone
        buckets_out.append(
            {
                "label": label,
                "range_min": lower,
                "range_max": upper,
                "monotone_success_rate": float(monotone),
                **summary,
            }
        )
    total_raw = [
        _dimension_raw_value(entry, dimension)
        for entry in entries
        if _dimension_raw_value(entry, dimension) is not None
    ]
    total_success = [_as_float(entry.get("success_score", 0.0)) for entry in entries]
    avg_raw = (sum(float(v) for v in total_raw) / len(total_raw)) if total_raw else 0.0
    avg_success = (sum(total_success) / len(total_success)) if total_success else 0.0
    optimism_gap = avg_raw - avg_success
    warn_gap = float(cfg.get("optimism_gap_warn", 0.10))
    if optimism_gap > warn_gap:
        diagnosis = "too_optimistic"
    elif optimism_gap < (-warn_gap):
        diagnosis = "too_pessimistic"
    else:
        diagnosis = "balanced"
    return {
        "scope_kind": scope_kind,
        "scope_key": scope_key,
        "sample_count": len(entries),
        "avg_raw_confidence": avg_raw,
        "actual_success_rate": avg_success,
        "optimism_gap": optimism_gap,
        "diagnosis": diagnosis,
        "buckets": buckets_out,
    }


def _segment_diagnostics(entries: list[dict], key_name: str, limit: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in list(entries or []):
        groups[str(entry.get(key_name, "") or "(leer)")].append(entry)
    rows = []
    for key, members in groups.items():
        count = len(members)
        if count <= 0:
            continue
        avg_raw = sum(_as_float(member.get("proposed_overall_confidence_raw", member.get("proposed_confidence", 0.0))) for member in members) / float(count)
        avg_success = sum(_as_float(member.get("success_score", 0.0)) for member in members) / float(count)
        avg_profit_delta = sum(_as_float(member.get("profit_delta", 0.0)) for member in members) / float(count)
        day_values = [member.get("sell_duration_delta") for member in members if member.get("sell_duration_delta") is not None]
        avg_days_delta = (sum(_as_float(v) for v in day_values) / float(len(day_values))) if day_values else 0.0
        rows.append(
            {
                "key": key,
                "sample_count": count,
                "avg_raw_confidence": avg_raw,
                "actual_success_rate": avg_success,
                "optimism_gap": avg_raw - avg_success,
                "avg_profit_delta": avg_profit_delta,
                "avg_days_delta": avg_days_delta,
            }
        )
    rows.sort(key=lambda row: (abs(float(row["optimism_gap"])), float(row["sample_count"])), reverse=True)
    return rows[: max(1, int(limit or 5))]


def _fee_quality_mix(entries: list[dict]) -> dict:
    counts = {"exact": 0, "partial": 0, "uncertain": 0, "none": 0}
    for entry in list(entries or []):
        key = str(entry.get("fee_match_quality", "none") or "none").strip().lower()
        if key not in counts:
            key = "none"
        counts[key] += 1
    return counts


def _resolve_personal_history_quality(prepared: list[dict], total_entries: int, min_samples: int) -> tuple[str, list[str], dict]:
    eligible_count = len(prepared)
    reliable_count = sum(1 for entry in prepared if bool(entry.get("reliable_outcome", False)))
    uncertain_count = sum(1 for entry in prepared if bool(entry.get("uncertain_match", False)))
    unmatched_count = sum(1 for entry in prepared if bool(entry.get("wallet_unmatched", False)))
    stale_count = sum(1 for entry in prepared if bool(entry.get("stale_basis", False)))
    truncated_count = sum(1 for entry in prepared if bool(entry.get("truncated_basis", False)))
    exact_fee_count = sum(1 for entry in prepared if str(entry.get("fee_match_quality", "") or "") == "exact")
    partial_fee_count = sum(1 for entry in prepared if str(entry.get("fee_match_quality", "") or "") == "partial")
    uncertain_fee_count = sum(1 for entry in prepared if str(entry.get("fee_match_quality", "") or "") == "uncertain")
    wallet_backed_count = sum(1 for entry in prepared if str(entry.get("history_source", "") or "") == "wallet")
    reliable_ratio = (reliable_count / float(eligible_count)) if eligible_count > 0 else 0.0
    weak_count = sum(
        1
        for entry in prepared
        if bool(entry.get("uncertain_match", False))
        or bool(entry.get("wallet_unmatched", False))
        or bool(entry.get("stale_basis", False))
        or bool(entry.get("truncated_basis", False))
        or str(entry.get("fee_match_quality", "") or "") == "uncertain"
    )
    weak_ratio = (weak_count / float(eligible_count)) if eligible_count > 0 else 1.0
    warnings: list[str] = []
    if eligible_count <= 0:
        warnings.append("insufficient personal history")
        return (
            "none",
            warnings,
            {
                "reliable_ratio": 0.0,
                "uncertain_match_ratio": 0.0,
                "wallet_unmatched_ratio": 0.0,
                "stale_basis_ratio": 0.0,
                "truncated_basis_ratio": 0.0,
                "wallet_backed_ratio": 0.0,
                "exact_fee_ratio": 0.0,
                "partial_fee_ratio": 0.0,
                "uncertain_fee_ratio": 0.0,
            },
        )
    if eligible_count < max(3, int(min_samples) // 2):
        warnings.append("very low personal sample size")
        level = "very_low"
    elif eligible_count < int(min_samples):
        warnings.append("low personal sample size")
        level = "low"
    else:
        level = "usable"
    if weak_ratio > 0.60 or reliable_ratio < 0.40:
        warnings.append("unreliable personal history")
        if level == "usable":
            level = "low"
    if stale_count > 0:
        warnings.append("stale wallet-backed basis present")
    if truncated_count > 0:
        warnings.append("wallet history is truncated")
    if uncertain_fee_count > 0 and exact_fee_count <= partial_fee_count:
        warnings.append("fee matching is only partially reliable")
    if (
        eligible_count >= max(int(min_samples) * 2, 12)
        and reliable_ratio >= 0.75
        and weak_ratio <= 0.25
        and wallet_backed_count >= max(4, int(min_samples))
    ):
        level = "good"
    elif level == "usable" and (reliable_ratio < 0.50 or weak_ratio > 0.50):
        level = "low"
    return (
        level,
        list(dict.fromkeys(warnings)),
        {
            "reliable_ratio": reliable_ratio,
            "uncertain_match_ratio": uncertain_count / float(eligible_count),
            "wallet_unmatched_ratio": unmatched_count / float(eligible_count),
            "stale_basis_ratio": stale_count / float(eligible_count),
            "truncated_basis_ratio": truncated_count / float(eligible_count),
            "wallet_backed_ratio": wallet_backed_count / float(eligible_count),
            "exact_fee_ratio": exact_fee_count / float(eligible_count),
            "partial_fee_ratio": partial_fee_count / float(eligible_count),
            "uncertain_fee_ratio": uncertain_fee_count / float(eligible_count),
        },
    )


def _build_personal_history_policy(quality_level: str, warnings: list[str]) -> dict:
    level = str(quality_level or "none").strip().lower()
    if level in ("none", "very_low", "low"):
        reason = "insufficient personal history"
        if "unreliable personal history" in warnings:
            reason = "unreliable personal history"
        return {
            "fallback_to_generic": True,
            "supplemental_only": True,
            "ranking_effect": "none",
            "reason": reason,
        }
    return {
        "fallback_to_generic": False,
        "supplemental_only": True,
        "ranking_effect": "none",
        "reason": "supplemental personal history available",
    }


def build_personal_calibration_summary(entries: list[dict], cfg: dict | None, now: datetime | None = None) -> dict:
    cal_cfg = resolve_confidence_calibration_cfg(cfg)
    prepared: list[dict] = []
    total_entries = 0
    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue
        total_entries += 1
        outcome = classify_personal_trade_outcome(entry, cal_cfg, now=now)
        merged = dict(entry)
        merged.update(outcome)
        if "proposed_overall_confidence_raw" not in merged:
            merged["proposed_overall_confidence_raw"] = _as_float(
                merged.get("proposed_confidence", merged.get("overall_confidence", 0.0))
            )
        if bool(outcome.get("eligible", False)):
            prepared.append(merged)

    min_samples = max(4, int(cal_cfg.get("min_samples", 8) or 8))
    quality_level, quality_warnings, quality_metrics = _resolve_personal_history_quality(prepared, total_entries, min_samples)
    overall_model = _build_scope_model(prepared, "overall", cal_cfg, "personal", "personal")
    reliable_buckets = [
        bucket
        for bucket in list(overall_model.get("buckets", []) or [])
        if int(bucket.get("sample_count", 0) or 0) >= int(cal_cfg.get("min_samples_per_bucket", 3) or 3)
    ]
    reliable_buckets.sort(
        key=lambda bucket: (
            abs(float(bucket.get("optimism_gap", 0.0))),
            -int(bucket.get("sample_count", 0) or 0),
        )
    )
    sample_size = {
        "entries_total": total_entries,
        "eligible_entries": len(prepared),
        "wallet_backed_entries": sum(1 for entry in prepared if str(entry.get("history_source", "") or "") == "wallet"),
        "manual_only_entries": sum(1 for entry in prepared if str(entry.get("history_source", "") or "") != "wallet"),
        "reliable_entries": sum(1 for entry in prepared if bool(entry.get("reliable_outcome", False))),
        "uncertain_entries": sum(1 for entry in prepared if bool(entry.get("uncertain_match", False))),
        "wallet_unmatched_entries": sum(1 for entry in prepared if bool(entry.get("wallet_unmatched", False))),
    }
    fee_quality_mix = _fee_quality_mix(prepared)
    warnings = list(quality_warnings)
    if sample_size["eligible_entries"] <= 0:
        warnings.append("no closed or stale personal outcomes yet")
    policy = _build_personal_history_policy(quality_level, warnings)
    diagnostics = {
        "overall": overall_model,
        "most_reliable_buckets": reliable_buckets[:3],
        "target_markets": _segment_diagnostics(prepared, "target_market", limit=5),
        "routes": _segment_diagnostics(prepared, "route_id", limit=5),
        "exit_types": _segment_diagnostics(prepared, "proposed_exit_type", limit=5),
    }
    return {
        "generated_at": utc_now_iso(),
        "config": cal_cfg,
        "quality_level": quality_level,
        "usable_for_calibration": quality_level in ("usable", "good"),
        "policy": policy,
        "sample_size": sample_size,
        "data_quality": {
            **quality_metrics,
            "fee_quality_mix": fee_quality_mix,
        },
        "diagnostics": diagnostics,
        "warnings": list(dict.fromkeys(warnings)),
    }


def format_personal_calibration_summary(summary: dict | None, limit: int = 5) -> str:
    if not isinstance(summary, dict):
        return "Keine persoenliche Kalibrierungsbasis vorhanden."
    sample_size = dict(summary.get("sample_size", {}) or {})
    policy = dict(summary.get("policy", {}) or {})
    overall = dict(summary.get("diagnostics", {}).get("overall", {}) or {})
    lines = [
        "=" * 70,
        "PERSONAL CALIBRATION BASIS",
        "=" * 70,
        (
            f"Quality: {summary.get('quality_level', 'none')} | "
            f"eligible={int(sample_size.get('eligible_entries', 0) or 0)} | "
            f"wallet_backed={int(sample_size.get('wallet_backed_entries', 0) or 0)} | "
            f"reliable={int(sample_size.get('reliable_entries', 0) or 0)}"
        ),
        (
            f"Policy: {'fallback_generic' if bool(policy.get('fallback_to_generic', True)) else 'supplemental_only'} | "
            f"ranking_effect={policy.get('ranking_effect', 'none')} | reason={policy.get('reason', '')}"
        ),
        (
            f"Overall diagnosis: {overall.get('diagnosis', 'n/a')} | "
            f"success={float(overall.get('actual_success_rate', 0.0)):.2f} | "
            f"gap={float(overall.get('optimism_gap', 0.0)):+.2f}"
        ),
    ]
    warnings = list(summary.get("warnings", []) or [])
    if warnings:
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")
    lines.append("Personal outcome buckets:")
    bucket_rows = [
        bucket for bucket in list(overall.get("buckets", []) or []) if int(bucket.get("sample_count", 0) or 0) > 0
    ]
    if bucket_rows:
        for bucket in bucket_rows[: max(1, int(limit))]:
            lines.append(
                (
                    f"- {bucket.get('label', '')} | n={int(bucket.get('sample_count', 0) or 0)} "
                    f"| raw={float(bucket.get('avg_raw_confidence', 0.0)):.2f} "
                    f"| success={float(bucket.get('actual_success_rate', 0.0)):.2f} "
                    f"| gap={float(bucket.get('optimism_gap', 0.0)):+.2f}"
                )
            )
    else:
        lines.append("- Keine belastbare persoenliche Outcome-Basis.")

    def _append_segment(title: str, rows: list[dict]) -> None:
        lines.append("")
        lines.append(title)
        if not rows:
            lines.append("- Keine ausreichenden persoenlichen Daten.")
            return
        for row in rows[: max(1, int(limit))]:
            lines.append(
                (
                    f"- {row.get('key', '')} | n={int(row.get('sample_count', 0) or 0)} "
                    f"| success={float(row.get('actual_success_rate', 0.0)):.2f} "
                    f"| gap={float(row.get('optimism_gap', 0.0)):+.2f}"
                )
            )

    diagnostics = summary.get("diagnostics", {})
    _append_segment("Exit types:", list(diagnostics.get("exit_types", []) or []))
    _append_segment("Target markets:", list(diagnostics.get("target_markets", []) or []))
    _append_segment("Routes:", list(diagnostics.get("routes", []) or []))
    return "\n".join(lines)


def build_confidence_calibration(entries: list[dict], cfg: dict | None, now: datetime | None = None) -> dict:
    cal_cfg = resolve_confidence_calibration_cfg(cfg)
    prepared: list[dict] = []
    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue
        outcome = classify_trade_outcome(entry, cal_cfg, now=now)
        merged = dict(entry)
        merged.update(outcome)
        if not bool(outcome.get("eligible", False)):
            continue
        if "proposed_overall_confidence_raw" not in merged:
            merged["proposed_overall_confidence_raw"] = _as_float(
                merged.get("proposed_confidence", merged.get("overall_confidence", 0.0))
            )
        prepared.append(merged)

    dimensions: dict[str, dict] = {}
    warnings: list[str] = []
    min_samples = int(cal_cfg["min_samples"])
    for dimension in CONFIDENCE_DIMENSIONS:
        dim_entries = [entry for entry in prepared if _dimension_raw_value(entry, dimension) is not None]
        enough_data = len(dim_entries) >= min_samples
        dimension_model = {
            "dimension": dimension,
            "definition": CONFIDENCE_DEFINITIONS[f"{dimension}_confidence"] if dimension != "overall" else CONFIDENCE_DEFINITIONS["overall_confidence"],
            "sample_count": len(dim_entries),
            "enough_data": enough_data,
            "global": _build_scope_model(dim_entries, dimension, cal_cfg, "global", "global"),
            "scopes": {},
        }
        if not enough_data:
            warnings.append(f"{dimension}: too few eligible journal samples ({len(dim_entries)}/{min_samples})")
        scope_name = str(cal_cfg.get("scope", "global"))
        if scope_name != "global":
            grouped: dict[str, list[dict]] = defaultdict(list)
            for entry in dim_entries:
                grouped[_scope_key(entry, scope_name)].append(entry)
            for key, members in grouped.items():
                if len(members) < min_samples:
                    continue
                dimension_model["scopes"][key] = _build_scope_model(members, dimension, cal_cfg, scope_name, key)
        dimensions[dimension] = dimension_model

    reliable_buckets = []
    overall_global = dimensions.get("overall", {}).get("global", {})
    for bucket in list(overall_global.get("buckets", []) or []):
        if int(bucket.get("sample_count", 0) or 0) < int(cal_cfg["min_samples_per_bucket"]):
            continue
        reliable_buckets.append(bucket)
    reliable_buckets.sort(
        key=lambda bucket: (
            abs(float(bucket.get("optimism_gap", 0.0))),
            -int(bucket.get("sample_count", 0) or 0),
        )
    )
    diagnostics = {
        "most_reliable_buckets": reliable_buckets[:3],
        "target_markets": _segment_diagnostics(prepared, "target_market", limit=5),
        "routes": _segment_diagnostics(prepared, "route_id", limit=5),
        "exit_types": _segment_diagnostics(prepared, "proposed_exit_type", limit=5),
    }
    return {
        "generated_at": utc_now_iso(),
        "config": cal_cfg,
        "eligible_entries": len(prepared),
        "dimensions": dimensions,
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def calibrate_confidence_value(
    raw_confidence: float,
    calibration: dict | None,
    *,
    dimension: str = "overall",
    route_id: str = "",
    source_market: str = "",
    target_market: str = "",
    exit_type: str = "",
) -> dict:
    raw = _clamp01(raw_confidence)
    dim = str(dimension or "overall").strip().lower()
    if not isinstance(calibration, dict):
        return {
            "raw_confidence": raw,
            "calibrated_confidence": raw,
            "warning": "",
            "scope_kind": "global",
            "scope_key": "global",
            "bucket_label": _bucket_label(raw, list(DEFAULT_CONFIDENCE_BUCKETS)),
            "sample_count": 0,
        }
    cfg = resolve_confidence_calibration_cfg(calibration.get("config", calibration))
    dimension_model = calibration.get("dimensions", {}).get(dim, {})
    scope_kind = str(cfg.get("scope", "global"))
    scope_key = "global"
    selected = dimension_model.get("global", {})
    warning_parts: list[str] = []
    if not cfg.get("enabled", False):
        return {
            "raw_confidence": raw,
            "calibrated_confidence": raw,
            "warning": "",
            "scope_kind": "global",
            "scope_key": "global",
            "bucket_label": _bucket_label(raw, list(cfg.get("buckets", DEFAULT_CONFIDENCE_BUCKETS))),
            "sample_count": 0,
        }
    if not bool(dimension_model.get("enough_data", False)):
        warning_parts.append("insufficient journal data")
    elif scope_kind != "global":
        scope_entry = {
            "route_id": route_id,
            "source_market": source_market,
            "target_market": target_market,
            "proposed_exit_type": exit_type,
        }
        scope_key = _scope_key(scope_entry, scope_kind)
        scoped = dimension_model.get("scopes", {}).get(scope_key)
        if isinstance(scoped, dict):
            selected = scoped
        elif bool(cfg.get("scope_fallback_to_global", True)):
            scope_key = "global"
            warning_parts.append(f"{scope_kind} fallback to global")
        else:
            warning_parts.append(f"missing {scope_kind} calibration")
    bucket_label = _bucket_label(raw, list(cfg.get("buckets", DEFAULT_CONFIDENCE_BUCKETS)))
    selected_bucket = None
    for bucket in list(selected.get("buckets", []) or []):
        if str(bucket.get("label", "")) == bucket_label:
            selected_bucket = bucket
            break
    if selected_bucket is None:
        warning_parts.append("missing bucket statistics")
        calibrated = raw
        bucket_samples = 0
    else:
        bucket_samples = int(selected_bucket.get("sample_count", 0) or 0)
        if bucket_samples < int(cfg.get("min_samples_per_bucket", 3)):
            warning_parts.append("bucket sample count too low")
            if scope_key != "global":
                global_buckets = list(dimension_model.get("global", {}).get("buckets", []) or [])
                for bucket in global_buckets:
                    if str(bucket.get("label", "")) == bucket_label and int(bucket.get("sample_count", 0) or 0) >= int(cfg.get("min_samples_per_bucket", 3)):
                        selected_bucket = bucket
                        bucket_samples = int(bucket.get("sample_count", 0) or 0)
                        scope_key = "global"
                        warning_parts.append("global bucket fallback")
                        break
        calibrated = raw
        if bucket_samples >= int(cfg.get("min_samples_per_bucket", 3)):
            calibrated = _clamp01(float(selected_bucket.get("monotone_success_rate", selected_bucket.get("actual_success_rate", raw)) or raw))
    return {
        "raw_confidence": raw,
        "calibrated_confidence": calibrated,
        "warning": "; ".join(dict.fromkeys(part for part in warning_parts if part)),
        "scope_kind": scope_kind,
        "scope_key": scope_key,
        "bucket_label": bucket_label,
        "sample_count": bucket_samples,
    }


def _read_value(target: object, key: str, default=None):
    if isinstance(target, dict):
        return target.get(key, default)
    return getattr(target, key, default)


def _write_value(target: object, key: str, value) -> None:
    if isinstance(target, dict):
        target[key] = value
        return
    setattr(target, key, value)


def apply_calibration_to_record(
    target: object,
    calibration: dict | None,
    *,
    route_id: str = "",
    source_market: str = "",
    target_market: str = "",
    exit_type: str = "",
    transport_confidence: object | None = None,
) -> object:
    raw_exit = _clamp01(_as_float(_read_value(target, "raw_exit_confidence", _read_value(target, "exit_confidence", 0.0))))
    raw_liquidity = _clamp01(_as_float(_read_value(target, "raw_liquidity_confidence", _read_value(target, "liquidity_confidence", 0.0))))
    raw_transport_value = _read_value(target, "raw_transport_confidence", transport_confidence)
    if raw_transport_value is None:
        raw_transport_value = _read_value(target, "transport_confidence", _read_value(target, "transport_cost_confidence", 1.0))
    raw_transport = transport_confidence_to_score(raw_transport_value)
    explicit_overall = _read_value(target, "raw_overall_confidence", _read_value(target, "overall_confidence", _read_value(target, "proposed_confidence", 0.0)))
    raw_overall = overall_raw_confidence_from_components(raw_exit, raw_liquidity, raw_transport, _as_float(explicit_overall))

    calibration_cfg = resolve_confidence_calibration_cfg(calibration.get("config", calibration) if isinstance(calibration, dict) else {})
    attrs = {
        "route_id": route_id or str(_read_value(target, "route_id", "") or ""),
        "source_market": source_market or str(_read_value(target, "source_market", _read_value(target, "buy_at", _read_value(target, "route_src_label", ""))) or ""),
        "target_market": target_market or str(_read_value(target, "target_market", _read_value(target, "sell_at", _read_value(target, "route_dst_label", ""))) or ""),
        "exit_type": exit_type or str(_read_value(target, "exit_type", _read_value(target, "proposed_exit_type", "")) or ""),
    }
    exit_info = calibrate_confidence_value(raw_exit, calibration, dimension="exit", **attrs)
    liquidity_info = calibrate_confidence_value(raw_liquidity, calibration, dimension="liquidity", **attrs)
    transport_info = calibrate_confidence_value(raw_transport, calibration, dimension="transport", **attrs)
    overall_info = calibrate_confidence_value(raw_overall, calibration, dimension="overall", **attrs)

    calibrated_exit = _clamp01(min(raw_exit, float(exit_info["calibrated_confidence"])))
    calibrated_liquidity = _clamp01(min(raw_liquidity, float(liquidity_info["calibrated_confidence"])))
    calibrated_transport = _clamp01(min(raw_transport, float(transport_info["calibrated_confidence"])))
    calibrated_overall = _clamp01(
        min(
            float(overall_info["calibrated_confidence"]),
            calibrated_exit,
            calibrated_liquidity,
            calibrated_transport,
        )
    )
    decision_overall = calibrated_overall if bool(calibration_cfg.get("apply_to_decisions", True)) else raw_overall
    warnings = [
        str(exit_info.get("warning", "") or ""),
        str(liquidity_info.get("warning", "") or ""),
        str(transport_info.get("warning", "") or ""),
        str(overall_info.get("warning", "") or ""),
    ]
    warning_text = "; ".join(dict.fromkeys(part for part in warnings if part))

    updates = {
        "raw_exit_confidence": raw_exit,
        "raw_liquidity_confidence": raw_liquidity,
        "raw_transport_confidence": raw_transport,
        "raw_overall_confidence": raw_overall,
        "calibrated_exit_confidence": calibrated_exit,
        "calibrated_liquidity_confidence": calibrated_liquidity,
        "calibrated_transport_confidence": calibrated_transport,
        "calibrated_overall_confidence": calibrated_overall,
        "raw_confidence": raw_overall,
        "calibrated_confidence": calibrated_overall,
        "decision_overall_confidence": decision_overall,
        "calibration_warning": warning_text,
        "confidence_calibration_scope": str(overall_info.get("scope_key", "global") or "global"),
        "confidence_calibration_bucket": str(overall_info.get("bucket_label", "") or ""),
    }
    for key, value in updates.items():
        _write_value(target, key, value)
    return target


def format_confidence_calibration_report(calibration: dict | None, limit: int = 5) -> str:
    if not isinstance(calibration, dict):
        return "Keine Kalibrierungsdaten vorhanden."
    overall = calibration.get("dimensions", {}).get("overall", {})
    overall_global = overall.get("global", {})
    lines = [
        "=" * 70,
        "CONFIDENCE CALIBRATION REPORT",
        "=" * 70,
        f"Generated: {calibration.get('generated_at', '')}",
        f"Eligible journal entries: {int(calibration.get('eligible_entries', 0) or 0)}",
        f"Overall samples: {int(overall.get('sample_count', 0) or 0)}",
        f"Overall diagnosis: {str(overall_global.get('diagnosis', 'n/a'))}",
    ]
    warnings = list(calibration.get("warnings", []) or [])
    if warnings:
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")
    lines.append("Overall confidence buckets:")
    for bucket in list(overall_global.get("buckets", []) or []):
        lines.append(
            (
                f"- {bucket.get('label', '')} | n={int(bucket.get('sample_count', 0) or 0)} "
                f"| raw={float(bucket.get('avg_raw_confidence', 0.0)):.2f} "
                f"| success={float(bucket.get('actual_success_rate', 0.0)):.2f} "
                f"| monotone={float(bucket.get('monotone_success_rate', 0.0)):.2f} "
                f"| gap={float(bucket.get('optimism_gap', 0.0)):+.2f} "
                f"| profit_delta={float(bucket.get('avg_profit_delta', 0.0)):+.0f} "
                f"| days_delta={float(bucket.get('avg_days_delta', 0.0)):+.1f}"
            )
        )
    lines.append("")
    lines.append("Reliable bands:")
    reliable = list(calibration.get("diagnostics", {}).get("most_reliable_buckets", []) or [])
    if reliable:
        for bucket in reliable[: max(1, int(limit))]:
            lines.append(
                f"- {bucket.get('label', '')} | n={int(bucket.get('sample_count', 0) or 0)} | gap={float(bucket.get('optimism_gap', 0.0)):+.2f}"
            )
    else:
        lines.append("- Keine belastbaren Buckets.")

    def _append_segment(title: str, rows: list[dict]) -> None:
        lines.append("")
        lines.append(title)
        if not rows:
            lines.append("- Keine ausreichenden Daten.")
            return
        for row in rows[: max(1, int(limit))]:
            lines.append(
                (
                    f"- {row.get('key', '')} | n={int(row.get('sample_count', 0) or 0)} "
                    f"| raw={float(row.get('avg_raw_confidence', 0.0)):.2f} "
                    f"| success={float(row.get('actual_success_rate', 0.0)):.2f} "
                    f"| gap={float(row.get('optimism_gap', 0.0)):+.2f} "
                    f"| profit_delta={float(row.get('avg_profit_delta', 0.0)):+.0f} "
                    f"| days_delta={float(row.get('avg_days_delta', 0.0)):+.1f}"
                )
            )

    diagnostics = calibration.get("diagnostics", {})
    _append_segment("Markets with largest calibration gap:", list(diagnostics.get("target_markets", []) or []))
    _append_segment("Routes with largest calibration gap:", list(diagnostics.get("routes", []) or []))
    _append_segment("Exit types with largest calibration gap:", list(diagnostics.get("exit_types", []) or []))
    return "\n".join(lines)


__all__ = [
    "CONFIDENCE_DEFINITIONS",
    "CONFIDENCE_DIMENSIONS",
    "DEFAULT_CONFIDENCE_BUCKETS",
    "PERSONAL_HISTORY_QUALITY_LEVELS",
    "apply_calibration_to_record",
    "build_confidence_calibration",
    "build_personal_calibration_summary",
    "calibrate_confidence_value",
    "classify_personal_trade_outcome",
    "classify_trade_outcome",
    "format_confidence_calibration_report",
    "format_personal_calibration_summary",
    "overall_raw_confidence_from_components",
    "resolve_confidence_calibration_cfg",
    "transport_confidence_to_score",
]
