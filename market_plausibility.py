from __future__ import annotations

import math

from fees import compute_trade_financials
from models import OrderLevel


DEFAULT_MARKET_PLAUSIBILITY_CFG = {
    "enabled": True,
    "visible_levels": 6,
    "min_usable_units": 5,
    "min_usable_ratio": 0.35,
    "thin_top_of_book_ratio": 0.08,
    "price_gap_after_top_levels_pct": 0.08,
    "depth_decay_floor": 0.35,
    "order_concentration_ratio": 0.75,
    "extreme_reference_deviation": 0.60,
    "fake_spread_profit_ratio": 0.55,
    "hard_reject_manipulation_risk": 0.80,
    "warn_manipulation_risk": 0.45,
    "hard_reject_on_unusable_depth": True,
    "hard_reject_on_extreme_reference_deviation": True,
    "reference_soft_cap_markup": 0.25,
}

_FRAGILE_BOOK_FLAGS = {
    "THIN_TOP_OF_BOOK",
    "UNUSABLE_DEPTH",
    "DEPTH_COLLAPSE",
    "ORDERBOOK_CONCENTRATION",
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value or 0.0)))


def _metric_get(metrics: object, key: str, default: float | list[str] | None = None):
    if isinstance(metrics, dict):
        return metrics.get(key, default)
    return getattr(metrics, key, default)


def _metric_has(metrics: object, key: str) -> bool:
    if isinstance(metrics, dict):
        return key in metrics
    return hasattr(metrics, key)


def _metric_flags(metrics: object) -> set[str]:
    raw_flags = _metric_get(metrics, "flags", None)
    if raw_flags is None:
        nested = _metric_get(metrics, "market_plausibility", {})
        if isinstance(nested, dict):
            raw_flags = nested.get("flags", [])
    return {str(flag).strip().upper() for flag in list(raw_flags or []) if str(flag).strip()}


def _primary_reason_from_flags(flags: set[str]) -> str:
    reason_priority = [
        "FAKE_SPREAD_RISK",
        "UNUSABLE_DEPTH",
        "THIN_TOP_OF_BOOK",
        "DEPTH_COLLAPSE",
        "EXTREME_REFERENCE_DEVIATION",
        "ORDERBOOK_CONCENTRATION",
    ]
    return next((code for code in reason_priority if code in flags), "")


def resolve_market_plausibility_cfg(filters: dict) -> dict:
    cfg = dict(DEFAULT_MARKET_PLAUSIBILITY_CFG)
    raw = filters.get("market_plausibility", {}) if isinstance(filters, dict) else {}
    if isinstance(raw, dict):
        cfg.update(raw)
    return cfg


def profit_retention_ratio_from_values(
    top_profit_total: float,
    usable_profit_total: float | None = None,
    conservative_profit_total: float | None = None,
) -> float:
    top_profit = float(top_profit_total or 0.0)
    if top_profit <= 0.0:
        return 1.0
    effective_profits = [float(top_profit)]
    if usable_profit_total is not None:
        effective_profits.append(float(usable_profit_total))
    if conservative_profit_total is not None:
        effective_profits.append(float(conservative_profit_total))
    retained = min(effective_profits)
    return _clamp01(retained / max(1.0, top_profit))


def market_quality_score_from_metrics(metrics: object) -> float:
    if _metric_has(metrics, "market_quality_score"):
        raw_quality = _metric_get(metrics, "market_quality_score", None)
        if raw_quality is not None:
            try:
                parsed_quality = _clamp01(float(raw_quality))
                if parsed_quality < 0.999:
                    return parsed_quality
            except (TypeError, ValueError):
                pass
    plausibility_score = _clamp01(float(_metric_get(metrics, "market_plausibility_score", 1.0) or 1.0))
    manipulation_risk = _clamp01(
        float(_metric_get(metrics, "manipulation_risk_score", max(0.0, 1.0 - plausibility_score)) or 0.0)
    )
    profit_retention_ratio = _clamp01(
        float(
            _metric_get(
                metrics,
                "profit_retention_ratio",
                profit_retention_ratio_from_values(
                    float(_metric_get(metrics, "profit_at_top_of_book", 0.0) or 0.0),
                    float(_metric_get(metrics, "profit_at_usable_depth", 0.0) or 0.0),
                    float(_metric_get(metrics, "profit_at_conservative_executable_price", 0.0) or 0.0),
                ),
            )
            or 0.0
        )
    )
    flags = _metric_flags(metrics)
    quality_score = min(plausibility_score, max(0.0, 1.0 - manipulation_risk), profit_retention_ratio)
    if "THIN_TOP_OF_BOOK" in flags:
        quality_score *= 0.92
    if "UNUSABLE_DEPTH" in flags:
        quality_score *= 0.88
    if "DEPTH_COLLAPSE" in flags:
        quality_score *= 0.95
    if "ORDERBOOK_CONCENTRATION" in flags:
        quality_score *= 0.96
    if "FAKE_SPREAD_RISK" in flags:
        quality_score *= 0.85
    return _clamp01(quality_score)


def market_quality_gate_from_metrics(metrics: object, *, cfg: dict | None = None) -> tuple[bool, str]:
    settings = dict(DEFAULT_MARKET_PLAUSIBILITY_CFG)
    if isinstance(cfg, dict):
        settings.update(cfg)
    flags = _metric_flags(metrics)
    fragile_flags = flags & _FRAGILE_BOOK_FLAGS
    manipulation_risk = _clamp01(float(_metric_get(metrics, "manipulation_risk_score", 0.0) or 0.0))
    profit_retention_ratio = _clamp01(
        float(
            _metric_get(
                metrics,
                "profit_retention_ratio",
                profit_retention_ratio_from_values(
                    float(_metric_get(metrics, "profit_at_top_of_book", 0.0) or 0.0),
                    float(_metric_get(metrics, "profit_at_usable_depth", 0.0) or 0.0),
                    float(_metric_get(metrics, "profit_at_conservative_executable_price", 0.0) or 0.0),
                ),
            )
            or 0.0
        )
    )
    market_quality_score = market_quality_score_from_metrics(metrics)
    warn_manipulation_risk = max(0.0, float(settings.get("warn_manipulation_risk", 0.45) or 0.45))
    price_sensitive_retention_floor = max(0.65, float(settings.get("fake_spread_profit_ratio", 0.55) or 0.55))
    reason = _primary_reason_from_flags(flags) or "FAKE_SPREAD_RISK"

    if market_quality_score < 0.40 and (fragile_flags or "FAKE_SPREAD_RISK" in flags):
        return True, reason
    if profit_retention_ratio < 0.70 and manipulation_risk >= warn_manipulation_risk and fragile_flags:
        return True, reason
    if profit_retention_ratio < price_sensitive_retention_floor and (
        "THIN_TOP_OF_BOOK" in flags or "DEPTH_COLLAPSE" in flags or "FAKE_SPREAD_RISK" in flags
    ):
        return True, reason
    return False, ""


def top_of_book_volume_ratio(levels: list[OrderLevel], visible_levels: int = 5) -> float:
    visible = list(levels[: max(1, int(visible_levels or 1))])
    if not visible:
        return 0.0
    total = float(sum(max(0, int(lv.volume)) for lv in visible))
    if total <= 0.0:
        return 0.0
    return _clamp01(float(max(0, int(visible[0].volume))) / total)


def depth_decay(levels: list[OrderLevel], top_levels: int = 1, tail_levels: int = 3) -> float:
    if not levels:
        return 0.0
    top = float(sum(max(0, int(lv.volume)) for lv in levels[: max(1, int(top_levels or 1))]))
    tail_start = max(1, int(top_levels or 1))
    tail_end = tail_start + max(1, int(tail_levels or 1))
    tail = float(sum(max(0, int(lv.volume)) for lv in levels[tail_start:tail_end]))
    if top <= 0.0:
        return 0.0
    return max(0.0, tail / top)


def price_gap_after_top_levels(levels: list[OrderLevel], *, is_buy: bool, top_levels: int = 1) -> float:
    idx = max(1, int(top_levels or 1)) - 1
    if len(levels) <= idx + 1:
        return 1.0
    top_price = float(levels[idx].price)
    next_price = float(levels[idx + 1].price)
    if top_price <= 0.0 or next_price <= 0.0:
        return 1.0
    if is_buy:
        return max(0.0, (top_price - next_price) / top_price)
    return max(0.0, (next_price - top_price) / top_price)


def order_concentration_ratio(levels: list[OrderLevel], top_levels: int = 1, visible_levels: int = 5) -> float:
    visible = list(levels[: max(1, int(visible_levels or 1))])
    if not visible:
        return 0.0
    top = float(sum(max(0, int(lv.volume)) for lv in visible[: max(1, int(top_levels or 1))]))
    total = float(sum(max(0, int(lv.volume)) for lv in visible))
    if total <= 0.0:
        return 0.0
    return _clamp01(top / total)


def usable_depth_at_confidence_price(levels: list[OrderLevel], *, is_buy: bool, confidence_price: float) -> int:
    if not levels or confidence_price <= 0.0:
        return 0
    if is_buy:
        return int(sum(max(0, int(lv.volume)) for lv in levels if float(lv.price) >= confidence_price))
    return int(sum(max(0, int(lv.volume)) for lv in levels if float(lv.price) <= confidence_price))


def reference_price_deviation(price: float, reference_price: float) -> float:
    if reference_price <= 0.0 or price <= 0.0:
        return 0.0
    return max(0.0, abs(float(price) - float(reference_price)) / float(reference_price))


def weighted_price_for_units(levels: list[OrderLevel], qty: int) -> tuple[float, int]:
    remaining = max(0, int(qty or 0))
    if not levels or remaining <= 0:
        return 0.0, 0
    weighted = 0.0
    filled = 0
    for lv in levels:
        take = min(max(0, int(lv.volume)), remaining)
        if take <= 0:
            continue
        weighted += float(lv.price) * float(take)
        filled += int(take)
        remaining -= int(take)
        if remaining <= 0:
            break
    if filled <= 0:
        return 0.0, 0
    return float(weighted / float(filled)), int(filled)


def effective_spread_after_depth(source_sell_levels: list[OrderLevel], dest_buy_levels: list[OrderLevel], qty: int) -> float:
    buy_avg, buy_filled = weighted_price_for_units(source_sell_levels, qty)
    sell_avg, sell_filled = weighted_price_for_units(dest_buy_levels, qty)
    filled = min(int(buy_filled), int(sell_filled))
    if filled <= 0 or buy_avg <= 0.0 or sell_avg <= 0.0:
        return -1.0
    return float((sell_avg - buy_avg) / max(1e-9, buy_avg))


def _price_cap_from_reference(reference_price: float, cfg: dict) -> float:
    soft_cap = max(0.0, float(cfg.get("reference_soft_cap_markup", 0.25) or 0.0))
    if reference_price <= 0.0:
        return 0.0
    return float(reference_price) * (1.0 + soft_cap)


def assess_market_plausibility(
    *,
    source_levels: list[OrderLevel],
    exit_levels: list[OrderLevel],
    exit_is_buy: bool,
    proposed_qty: int,
    source_usable_price: float,
    exit_usable_price: float,
    reference_price: float,
    mode: str,
    fees: dict,
    price_depth_pct: float,
    competition_band_pct: float,
    relist_budget_pct: float,
    relist_budget_isk: float,
    cfg: dict,
) -> dict:
    settings = dict(DEFAULT_MARKET_PLAUSIBILITY_CFG)
    if isinstance(cfg, dict):
        settings.update(cfg)
    visible_levels = max(2, int(settings.get("visible_levels", 6) or 6))
    min_usable_units = max(1, int(settings.get("min_usable_units", 5) or 5))
    min_usable_ratio = max(0.01, float(settings.get("min_usable_ratio", 0.35) or 0.35))
    thin_top_ratio_threshold = max(0.0, float(settings.get("thin_top_of_book_ratio", 0.08) or 0.08))
    gap_threshold = max(0.0, float(settings.get("price_gap_after_top_levels_pct", 0.08) or 0.08))
    depth_decay_floor = max(0.0, float(settings.get("depth_decay_floor", 0.35) or 0.35))
    concentration_threshold = max(0.0, float(settings.get("order_concentration_ratio", 0.75) or 0.75))
    reference_deviation_threshold = max(0.0, float(settings.get("extreme_reference_deviation", 0.60) or 0.60))
    fake_spread_profit_ratio = max(0.0, float(settings.get("fake_spread_profit_ratio", 0.55) or 0.55))

    proposed_qty = max(1, int(proposed_qty or 1))
    required_usable_units = max(min_usable_units, int(math.ceil(float(proposed_qty) * float(min_usable_ratio))))

    source_top_price = float(source_levels[0].price) if source_levels else 0.0
    exit_top_price = float(exit_levels[0].price) if exit_levels else 0.0
    source_top_ratio = top_of_book_volume_ratio(source_levels, visible_levels=visible_levels)
    exit_top_ratio = top_of_book_volume_ratio(exit_levels, visible_levels=visible_levels)
    source_depth_decay = depth_decay(source_levels, top_levels=1, tail_levels=max(2, visible_levels - 1))
    exit_depth_decay = depth_decay(exit_levels, top_levels=1, tail_levels=max(2, visible_levels - 1))
    source_gap = price_gap_after_top_levels(source_levels, is_buy=False, top_levels=1)
    exit_gap = price_gap_after_top_levels(exit_levels, is_buy=bool(exit_is_buy), top_levels=1)
    source_concentration = order_concentration_ratio(source_levels, top_levels=1, visible_levels=visible_levels)
    exit_concentration = order_concentration_ratio(exit_levels, top_levels=1, visible_levels=visible_levels)

    source_conf_price = max(source_top_price, float(source_usable_price or 0.0))
    if exit_is_buy:
        exit_conf_price = min(exit_top_price if exit_top_price > 0.0 else float(exit_usable_price or 0.0), float(exit_usable_price or exit_top_price or 0.0))
        if exit_conf_price <= 0.0 and exit_top_price > 0.0:
            exit_conf_price = exit_top_price * (1.0 - max(0.0, float(price_depth_pct or 0.0)))
    else:
        exit_conf_price = max(float(exit_usable_price or 0.0), exit_top_price)
        if exit_conf_price <= 0.0 and exit_top_price > 0.0:
            exit_conf_price = exit_top_price * (1.0 + max(0.0, float(competition_band_pct or 0.0)))

    source_usable_units = usable_depth_at_confidence_price(source_levels, is_buy=False, confidence_price=source_conf_price)
    exit_usable_units = usable_depth_at_confidence_price(exit_levels, is_buy=bool(exit_is_buy), confidence_price=exit_conf_price)

    conservative_qty = min(proposed_qty, max(1, source_usable_units))
    if exit_is_buy:
        conservative_qty = min(conservative_qty, max(1, exit_usable_units))
    else:
        conservative_qty = min(conservative_qty, max(1, exit_usable_units if exit_usable_units > 0 else proposed_qty))
    conservative_qty = max(1, int(conservative_qty))

    source_weighted_price, source_weighted_filled = weighted_price_for_units(source_levels, conservative_qty)
    if exit_is_buy:
        exit_weighted_price, exit_weighted_filled = weighted_price_for_units(exit_levels, conservative_qty)
        conservative_qty = min(conservative_qty, max(1, int(source_weighted_filled)), max(1, int(exit_weighted_filled)))
    else:
        exit_weighted_price = max(float(exit_usable_price or 0.0), exit_top_price)
        exit_weighted_filled = int(conservative_qty)

    if source_weighted_price <= 0.0:
        source_weighted_price = float(source_usable_price or source_top_price or 0.0)
    if exit_weighted_price <= 0.0:
        exit_weighted_price = float(exit_usable_price or exit_top_price or 0.0)

    reference_cap_price = _price_cap_from_reference(float(reference_price or 0.0), settings)
    conservative_exit_price = float(exit_weighted_price)
    if not exit_is_buy and reference_cap_price > 0.0:
        conservative_exit_price = min(conservative_exit_price, reference_cap_price)
    conservative_source_price = float(source_weighted_price or source_usable_price or source_top_price or 0.0)

    top_buy_price = float(source_top_price or source_usable_price or 0.0)
    top_sell_price = float(exit_top_price or exit_usable_price or 0.0)
    usable_buy_price = float(source_usable_price or source_weighted_price or top_buy_price or 0.0)
    usable_sell_price = float(exit_usable_price or exit_weighted_price or top_sell_price or 0.0)

    qty_for_profit = max(1, int(proposed_qty))
    conservative_profit_qty = max(1, int(conservative_qty))
    _, _, profit_top, _ = compute_trade_financials(
        top_buy_price,
        top_sell_price,
        qty_for_profit,
        fees,
        bool(exit_is_buy),
        execution_mode=mode,
        relist_budget_pct=relist_budget_pct,
        relist_budget_isk=relist_budget_isk,
    )
    _, _, profit_usable, _ = compute_trade_financials(
        usable_buy_price,
        usable_sell_price,
        qty_for_profit,
        fees,
        bool(exit_is_buy),
        execution_mode=mode,
        relist_budget_pct=relist_budget_pct,
        relist_budget_isk=relist_budget_isk,
    )
    _, _, profit_conservative, _ = compute_trade_financials(
        conservative_source_price,
        conservative_exit_price,
        conservative_profit_qty,
        fees,
        bool(exit_is_buy),
        execution_mode=mode,
        relist_budget_pct=relist_budget_pct,
        relist_budget_isk=relist_budget_isk,
    )

    top_profit_total = float(profit_top)
    usable_profit_total = float(profit_usable)
    conservative_profit_total = float(profit_conservative)

    if exit_is_buy:
        effective_spread = effective_spread_after_depth(source_levels, exit_levels, conservative_profit_qty)
    else:
        if conservative_source_price > 0.0 and conservative_exit_price > 0.0:
            effective_spread = float((conservative_exit_price - conservative_source_price) / max(1e-9, conservative_source_price))
        else:
            effective_spread = -1.0

    if exit_is_buy:
        reference_anchor_price = top_sell_price if top_sell_price > 0.0 else usable_sell_price
    else:
        reference_anchor_price = max(usable_sell_price, top_sell_price)
    ref_deviation = reference_price_deviation(reference_anchor_price, float(reference_price or 0.0))

    # For instant (exit_is_buy=True): both source and exit must have depth — use min of both.
    # For planned_sell (exit_is_buy=False): exit_usable_units = sell competition at/below our target price.
    # When exit_usable_units=0, we are the cheapest/only seller — that is fine for a listing.
    # Use proposed_qty as neutral exit depth for planned_sell (we can always list our own qty).
    # Previously used `exit_usable_units or source_usable_units` which incorrectly rewarded
    # "no competition" trades with source-side depth, masking genuinely thin destination markets.
    exit_depth_for_ratio = exit_usable_units if exit_is_buy else (exit_usable_units if exit_usable_units > 0 else proposed_qty)
    usable_depth_ratio = min(
        1.0,
        float(min(source_usable_units, exit_depth_for_ratio)) / float(max(1, required_usable_units)),
    )
    flags: list[str] = []

    thin_top = (
        (source_top_ratio <= thin_top_ratio_threshold and source_gap >= gap_threshold)
        or (exit_top_ratio <= thin_top_ratio_threshold and exit_gap >= gap_threshold)
    )
    if thin_top:
        flags.append("THIN_TOP_OF_BOOK")

    if usable_depth_ratio < 1.0:
        flags.append("UNUSABLE_DEPTH")

    if min(source_depth_decay, exit_depth_decay if exit_is_buy else exit_depth_decay) < depth_decay_floor:
        flags.append("DEPTH_COLLAPSE")

    if max(source_concentration, exit_concentration) >= concentration_threshold:
        flags.append("ORDERBOOK_CONCENTRATION")

    if ref_deviation >= reference_deviation_threshold:
        flags.append("EXTREME_REFERENCE_DEVIATION")

    profit_ratio = profit_retention_ratio_from_values(
        top_profit_total,
        usable_profit_total,
        conservative_profit_total,
    )
    if top_profit_total > 0.0 and profit_ratio < fake_spread_profit_ratio:
        flags.append("FAKE_SPREAD_RISK")

    risk = 0.0
    risk += max(0.0, (thin_top_ratio_threshold - min(source_top_ratio, exit_top_ratio)) / max(1e-9, thin_top_ratio_threshold)) * 0.15
    risk += max(0.0, max(source_gap, exit_gap) - gap_threshold) / max(1e-9, 1.0 - gap_threshold) * 0.10
    risk += max(0.0, 1.0 - usable_depth_ratio) * 0.28
    risk += max(0.0, depth_decay_floor - min(source_depth_decay, exit_depth_decay)) / max(1e-9, depth_decay_floor) * 0.14
    risk += max(0.0, max(source_concentration, exit_concentration) - concentration_threshold) / max(1e-9, 1.0 - concentration_threshold) * 0.12
    risk += max(0.0, ref_deviation - reference_deviation_threshold) / max(1e-9, 1.0 - reference_deviation_threshold) * 0.16
    if "FAKE_SPREAD_RISK" in flags:
        risk += 0.20
    if "THIN_TOP_OF_BOOK" in flags and "FAKE_SPREAD_RISK" in flags:
        risk += 0.12
    if "UNUSABLE_DEPTH" in flags:
        risk += 0.10
    risk = _clamp01(risk)
    plausibility_score = _clamp01(1.0 - risk)
    flags_set = set(flags)
    primary_reason = _primary_reason_from_flags(flags_set)
    market_quality_score = market_quality_score_from_metrics(
        {
            "market_plausibility_score": float(plausibility_score),
            "manipulation_risk_score": float(risk),
            "profit_retention_ratio": float(profit_ratio),
            "flags": list(flags),
            "profit_at_top_of_book": float(top_profit_total),
            "profit_at_usable_depth": float(usable_profit_total),
            "profit_at_conservative_executable_price": float(conservative_profit_total),
        }
    )
    quality_gate_reject, quality_gate_reason = market_quality_gate_from_metrics(
        {
            "market_plausibility_score": float(plausibility_score),
            "manipulation_risk_score": float(risk),
            "profit_retention_ratio": float(profit_ratio),
            "flags": list(flags),
            "profit_at_top_of_book": float(top_profit_total),
            "profit_at_usable_depth": float(usable_profit_total),
            "profit_at_conservative_executable_price": float(conservative_profit_total),
        },
        cfg=settings,
    )

    hard_reject = False
    if bool(settings.get("hard_reject_on_unusable_depth", True)) and usable_depth_ratio < 0.55:
        hard_reject = True
    if bool(settings.get("hard_reject_on_extreme_reference_deviation", True)) and ref_deviation >= (reference_deviation_threshold * 1.35):
        hard_reject = True
    if risk >= max(0.0, float(settings.get("hard_reject_manipulation_risk", 0.80) or 0.80)):
        hard_reject = True
    if "FAKE_SPREAD_RISK" in flags and "THIN_TOP_OF_BOOK" in flags:
        hard_reject = True
    if not primary_reason and quality_gate_reason:
        primary_reason = str(quality_gate_reason)

    return {
        "top_of_book_volume_ratio": float(min(source_top_ratio, exit_top_ratio)),
        "source_top_of_book_volume_ratio": float(source_top_ratio),
        "exit_top_of_book_volume_ratio": float(exit_top_ratio),
        "depth_decay": float(min(source_depth_decay, exit_depth_decay)),
        "source_depth_decay": float(source_depth_decay),
        "exit_depth_decay": float(exit_depth_decay),
        "price_gap_after_top_levels": float(max(source_gap, exit_gap)),
        "source_price_gap_after_top_levels": float(source_gap),
        "exit_price_gap_after_top_levels": float(exit_gap),
        "order_concentration_ratio": float(max(source_concentration, exit_concentration)),
        "source_order_concentration_ratio": float(source_concentration),
        "exit_order_concentration_ratio": float(exit_concentration),
        "usable_depth_at_confidence_price": int(min(source_usable_units, exit_depth_for_ratio)),
        "source_usable_depth_at_confidence_price": int(source_usable_units),
        "exit_usable_depth_at_confidence_price": int(exit_usable_units),
        "usable_depth_ratio": float(usable_depth_ratio),
        "reference_price_deviation": float(ref_deviation),
        "effective_spread_after_depth": float(effective_spread),
        "profit_at_top_of_book": float(top_profit_total),
        "profit_at_usable_depth": float(usable_profit_total),
        "profit_at_conservative_executable_price": float(conservative_profit_total),
        "conservative_executable_qty": int(conservative_profit_qty),
        "profit_retention_ratio": float(profit_ratio),
        "flags": list(flags),
        "primary_reason": str(primary_reason),
        "hard_reject": bool(hard_reject),
        "quality_gate_reject": bool(quality_gate_reject),
        "quality_gate_reason": str(quality_gate_reason),
        "manipulation_risk_score": float(risk),
        "market_plausibility_score": float(plausibility_score),
        "market_quality_score": float(market_quality_score),
    }


__all__ = [
    "DEFAULT_MARKET_PLAUSIBILITY_CFG",
    "resolve_market_plausibility_cfg",
    "profit_retention_ratio_from_values",
    "market_quality_score_from_metrics",
    "market_quality_gate_from_metrics",
    "top_of_book_volume_ratio",
    "depth_decay",
    "price_gap_after_top_levels",
    "order_concentration_ratio",
    "usable_depth_at_confidence_price",
    "reference_price_deviation",
    "weighted_price_for_units",
    "effective_spread_after_depth",
    "assess_market_plausibility",
]
