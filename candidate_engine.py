from __future__ import annotations
from typing import Any

from models import OrderLevel, TradeCandidate
from fees import compute_trade_financials
from location_utils import normalize_location_label
from shipping import build_jita_split_price_map, build_route_context, compute_shipping_lane_total_cost

ESIClient = Any
ReplayESIClient = Any
FilterFunnel = Any


def build_levels(orders: list[dict], is_buy: bool) -> list[OrderLevel]:
    levels = {}
    for o in orders:
        if bool(o.get("is_buy_order")) != is_buy:
            continue
        price = float(o["price"])
        vol = int(o["volume_remain"])
        if vol <= 0:
            continue
        levels[price] = levels.get(price, 0) + vol

    if is_buy:
        prices = sorted(levels.keys(), reverse=True)
    else:
        prices = sorted(levels.keys())

    return [OrderLevel(p, levels[p]) for p in prices]

def get_structure_micro_liquidity(structure_orders: list[dict], type_id: int) -> dict:
    tid = int(type_id)
    buy_orders = [o for o in structure_orders if int(o.get("type_id", 0)) == tid and bool(o.get("is_buy_order"))]
    sell_orders = [o for o in structure_orders if int(o.get("type_id", 0)) == tid and not bool(o.get("is_buy_order"))]
    buy_levels = build_levels(buy_orders, is_buy=True)
    sell_levels = build_levels(sell_orders, is_buy=False)
    if not buy_levels and not sell_levels:
        return {
            "spread_pct": 1.0,
            "depth_within_2pct_buy": 0,
            "depth_within_2pct_sell": 0,
            "orderbook_imbalance": 0.0,
            "competition_density_near_best": 0,
        }

    best_bid = float(buy_levels[0].price) if buy_levels else 0.0
    best_ask = float(sell_levels[0].price) if sell_levels else 0.0

    spread_pct = 1.0
    if best_bid > 0 and best_ask > 0:
        mid = (best_bid + best_ask) / 2.0
        spread_pct = ((best_ask - best_bid) / mid) if mid > 0 else 1.0

    depth_within_2pct_buy = 0
    if best_bid > 0:
        cutoff_bid = best_bid * 0.98
        depth_within_2pct_buy = int(sum(int(lv.volume) for lv in buy_levels if float(lv.price) >= cutoff_bid))

    depth_within_2pct_sell = 0
    if best_ask > 0:
        cutoff_ask = best_ask * 1.02
        depth_within_2pct_sell = int(sum(int(lv.volume) for lv in sell_levels if float(lv.price) <= cutoff_ask))

    total_buy = int(sum(int(lv.volume) for lv in buy_levels))
    total_sell = int(sum(int(lv.volume) for lv in sell_levels))
    denom = max(1, total_buy + total_sell)
    orderbook_imbalance = float(total_buy - total_sell) / float(denom)

    competition_density_near_best = 0
    if best_ask > 0:
        near_best_cutoff = best_ask * 1.002
        competition_density_near_best = int(sum(1 for lv in sell_levels if float(lv.price) <= near_best_cutoff))

    return {
        "spread_pct": float(spread_pct),
        "depth_within_2pct_buy": int(depth_within_2pct_buy),
        "depth_within_2pct_sell": int(depth_within_2pct_sell),
        "orderbook_imbalance": float(orderbook_imbalance),
        "competition_density_near_best": int(competition_density_near_best),
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _derive_planned_sell_price(
    dst_sell_lv: list[OrderLevel],
    undercut_pct: float,
    competition_band_pct: float,
    min_top_level_units: int,
    min_supported_levels: int,
    max_isolated_top_gap_pct: float,
    reactive_queue_ratio: float,
) -> dict:
    import math

    if not dst_sell_lv:
        return {"valid": False, "reason": "planned_price_no_sell_levels"}

    best_level = dst_sell_lv[0]
    best_price = float(best_level.price)
    best_units = int(best_level.volume)
    second_price = float(dst_sell_lv[1].price) if len(dst_sell_lv) > 1 else 0.0
    band_pct = max(float(competition_band_pct), 0.002)
    band_cutoff = best_price * (1.0 + band_pct)
    band_levels = [lv for lv in dst_sell_lv if float(lv.price) <= band_cutoff]
    band_units = int(sum(int(lv.volume) for lv in band_levels))
    band_level_count = int(len(band_levels))
    top_gap_pct = ((second_price - best_price) / best_price) if best_price > 0.0 and second_price > 0.0 else 1.0

    min_supported = max(2, int(min_supported_levels))
    min_best_units = max(1, int(min_top_level_units))
    has_supported_top = (
        best_price > 0.0
        and best_units >= min_best_units
        and band_level_count >= min_supported
        and top_gap_pct <= max(0.0, float(max_isolated_top_gap_pct))
    )
    if not has_supported_top:
        return {
            "valid": False,
            "reason": "planned_price_unreliable_orderbook",
            "best_price": float(best_price),
            "best_level_units": int(best_units),
            "band_level_count": int(band_level_count),
            "band_units": int(band_units),
            "top_gap_pct": float(top_gap_pct),
        }

    undercut = max(0.0, float(undercut_pct))
    target_sell_price = best_price * (1.0 - undercut)
    target_sell_price = max(0.01, float(target_sell_price))
    queue_at_or_below_target = int(sum(int(lv.volume) for lv in dst_sell_lv if float(lv.price) <= target_sell_price + 1e-9))
    reactive_queue_units = max(0, band_units - queue_at_or_below_target)
    queue_shadow_units = int(math.ceil(float(reactive_queue_units) * max(0.0, float(reactive_queue_ratio))))
    queue_ahead_units = max(queue_at_or_below_target, queue_shadow_units)

    price_conf = 0.45
    price_conf += min(0.20, float(best_units) / max(1.0, float(min_best_units)) * 0.10)
    price_conf += min(0.20, float(band_level_count) / max(1.0, float(min_supported)) * 0.10)
    price_conf += min(0.15, (1.0 - _clamp01(top_gap_pct / max(1e-9, float(max_isolated_top_gap_pct)))) * 0.15)
    if queue_ahead_units <= 0:
        price_conf += 0.10

    return {
        "valid": True,
        "target_sell_price": float(target_sell_price),
        "price_basis": "best_ask_undercut" if undercut > 0.0 else "best_ask_match",
        "target_price_confidence": _clamp01(price_conf),
        "has_reliable_price_basis": True,
        "queue_ahead_units": int(queue_ahead_units),
        "competition_price_levels_near_best": int(band_level_count),
        "visible_band_units": int(band_units),
        "best_visible_sell_price": float(best_price),
        "best_level_units": int(best_units),
        "top_gap_pct": float(top_gap_pct),
    }


def _planned_structure_liquidity_confidence(
    depth_within_2pct_sell: int,
    min_depth_within_2pct_sell: int,
    competition_density_near_best: int,
    min_competition_density_near_best: int,
    max_competition_density_near_best: int,
    price_basis_confidence: float,
) -> float:
    depth_floor = max(1, int(min_depth_within_2pct_sell))
    min_density = max(1, int(min_competition_density_near_best))
    max_density = max(min_density, int(max_competition_density_near_best))
    depth_score = _clamp01(float(depth_within_2pct_sell) / float(depth_floor * 2))
    density_score = _clamp01(float(competition_density_near_best) / float(max(1, min_density + 1)))
    if competition_density_near_best > max_density:
        over = float(competition_density_near_best - max_density)
        density_score *= max(0.0, 1.0 - min(0.75, over / max(1.0, float(max_density))))
    return _clamp01((depth_score * 0.45) + (density_score * 0.35) + (_clamp01(price_basis_confidence) * 0.20))

def depth_slice(
    levels: list[OrderLevel],
    is_buy: bool,
    depth_pct: float,
    outlier_ratio: float = 0.25,
    outlier_window_levels: int = 5,
    min_top_level_units: int = 0
) -> tuple[float, int]:
    if not levels:
        return 0.0, 0

    # Robust top-of-book sanity:
    # - filter tiny top-levels
    # - compare best against median of next N levels (more stable than best-vs-second only)
    import statistics
    sanity_levels = list(levels)
    max_prunes = min(3, max(0, len(sanity_levels) - 1))
    for _ in range(max_prunes):
        if len(sanity_levels) < 2:
            break
        drop_best = False
        best_level = sanity_levels[0]
        if min_top_level_units > 0 and int(best_level.volume) < min_top_level_units:
            drop_best = True

        window_n = max(1, int(outlier_window_levels))
        next_window = sanity_levels[1:1 + window_n]
        if next_window:
            median_next = statistics.median([lv.price for lv in next_window])
            ratio = max(1e-6, float(outlier_ratio))
            if median_next > 0:
                if not is_buy and best_level.price < median_next * ratio:
                    drop_best = True
                elif is_buy and best_level.price > (median_next / ratio):
                    drop_best = True

        if drop_best:
            sanity_levels = sanity_levels[1:]
            continue
        break
    if not sanity_levels:
        sanity_levels = levels

    best = sanity_levels[0].price
    if is_buy:
        cutoff = best * (1.0 - depth_pct)
        selected = [lv for lv in sanity_levels if lv.price >= cutoff]
    else:
        cutoff = best * (1.0 + depth_pct)
        selected = [lv for lv in sanity_levels if lv.price <= cutoff]

    total_qty = sum(lv.volume for lv in selected)
    if total_qty <= 0:
        return 0.0, 0

    weighted = sum(lv.price * lv.volume for lv in selected)
    avg = weighted / total_qty
    return avg, total_qty

def apply_strategy_filters(cfg: dict, filters: dict) -> dict:
    """Merge strategy-mode constraints into route filters."""
    merged = dict(filters)
    strategy_cfg = cfg.get("strategy", {})
    mode = strategy_cfg.get("mode", "balanced")
    mode_params = strategy_cfg.get("strategy_modes", {}).get(mode, {})
    orderbook_cfg = cfg.get("orderbook", {})

    if "min_profit_pct" in mode_params:
        merged["min_profit_pct"] = max(float(merged.get("min_profit_pct", 0.0)), float(mode_params["min_profit_pct"]))
    if "min_profit_pct_boost" in mode_params:
        merged["min_profit_pct"] = float(merged.get("min_profit_pct", 0.0)) + float(mode_params["min_profit_pct_boost"])
    if "liquidity_min_score" in mode_params:
        merged["min_liquidity_score"] = max(
            int(merged.get("min_liquidity_score", 0)),
            int(mode_params["liquidity_min_score"])
        )
    if "min_history_volume" in mode_params:
        merged["min_market_history_volume"] = max(
            int(merged.get("min_market_history_volume", 0)),
            int(mode_params["min_history_volume"])
        )
    for k in (
        "outlier_ratio",
        "outlier_window_levels",
        "min_top_level_units",
        "min_source_sell_price_isk",
        "min_units_in_window",
        "window_levels_for_units"
    ):
        if k not in merged and k in orderbook_cfg:
            merged[k] = orderbook_cfg[k]
    return merged

def compute_candidates(
    esi: ESIClient | ReplayESIClient,
    source_orders: list[dict],
    dest_orders: list[dict],
    fees: dict,
    filters: dict,
    dest_structure_id: int | None = None,
    dest_region_id: int | None = None,
    route_context: dict | None = None,
    funnel: "FilterFunnel | None" = None,
    explain: dict | None = None
) -> list[TradeCandidate]:
    import math
    # support two modes: instant (sell to existing buy orders) and
    # fast_sell (create a sell order at destination, undercutting best price)
    mode = str(filters.get("mode", "instant")).lower()
    if mode not in ("instant", "fast_sell", "planned_sell"):
        mode = "instant"
    depth_pct = float(filters["price_depth_pct"])
    min_depth_units = int(filters["min_depth_units"])
    min_profit_pct = float(filters["min_profit_pct"])
    min_profit_total = float(filters["min_profit_isk_total"])
    undercut_pct = float(filters.get("undercut_pct", 0.001))
    outlier_ratio = float(filters.get("outlier_ratio", 0.25))
    outlier_window_levels = int(filters.get("outlier_window_levels", 5))
    min_top_level_units = int(filters.get("min_top_level_units", 0))
    min_source_sell_price_isk = float(filters.get("min_source_sell_price_isk", 0.0))
    min_units_in_window = int(filters.get("min_units_in_window", 0))
    window_levels_for_units = int(filters.get("window_levels_for_units", 5))
    competition_band_pct = float(filters.get("competition_band_pct", 0.02))
    max_turnover_factor = float(filters.get("max_turnover_factor", 3.0))
    min_fill_probability = float(filters.get("min_fill_probability", 0.0))
    min_instant_fill_ratio = float(filters.get("min_instant_fill_ratio", 0.0))
    min_dest_buy_depth_units = int(filters.get("min_dest_buy_depth_units", 0))
    fallback_daily_volume = float(filters.get("fallback_daily_volume", 0.1))
    explain_max_entries = int(filters.get("explain_max_entries", 2000))
    # optional duration for suggested sell orders (days)
    order_duration = int(filters.get("order_duration_days", 90))
    min_liquidity_score = int(filters.get("min_liquidity_score", 0))
    history_probe_enabled = bool(filters.get("history_probe_enabled", mode == "planned_sell"))
    horizon_days = int(filters.get("horizon_days", 90))
    history_days = int(filters.get("history_days", 30))
    min_expected_profit_isk = float(filters.get("min_expected_profit_isk", 0.0))
    max_expected_days_to_sell = float(filters.get("max_expected_days_to_sell", 99999.0))
    min_sell_through_ratio_90d = float(filters.get("min_sell_through_ratio_90d", 0.0))
    min_avg_daily_volume = float(filters.get("min_avg_daily_volume", 0.0))
    fallback_volume_penalty = float(filters.get("fallback_volume_penalty", 0.35))
    fallback_fill_probability_cap = float(filters.get("fallback_fill_probability_cap", 0.20))
    fallback_max_units_cap = int(filters.get("fallback_max_units_cap", 5))
    fallback_require_high_profit_pct = float(filters.get("fallback_require_high_profit_pct", 0.12))
    relist_budget_pct = float(filters.get("relist_budget_pct", fees.get("relist_budget_pct", 0.0)))
    relist_budget_isk = float(filters.get("relist_budget_isk", fees.get("relist_budget_isk", 0.0)))
    min_history_order_count = int(filters.get("min_market_history_order_count", 1))
    min_depth_within_2pct_sell = int(filters.get("min_depth_within_2pct_sell", 1))
    min_competition_density_near_best = int(filters.get("min_competition_density_near_best", 2))
    max_competition_density_near_best = int(filters.get("max_competition_density_near_best", 8))
    planned_min_supported_sell_levels = int(filters.get("planned_min_supported_sell_levels", 2))
    planned_max_isolated_top_gap_pct = float(
        filters.get("planned_max_isolated_top_gap_pct", max(competition_band_pct, 0.02))
    )
    planned_reactive_queue_ratio = float(filters.get("planned_reactive_queue_ratio", 0.50))
    planned_market_capture_pct = float(filters.get("planned_market_capture_pct", 0.35))
    planned_fallback_market_capture_pct = float(filters.get("planned_fallback_market_capture_pct", 0.10))
    planned_history_only_expectation_penalty = float(filters.get("planned_history_only_expectation_penalty", 0.75))
    planned_history_only_confidence_penalty = float(filters.get("planned_history_only_confidence_penalty", 0.20))
    planned_history_only_position_cap = float(filters.get("planned_history_only_position_cap", 0.35))
    planned_min_liquidity_confidence = float(filters.get("planned_min_liquidity_confidence", 0.45))
    planned_min_exit_confidence = float(filters.get("planned_min_exit_confidence", 0.40))
    planned_max_queue_to_demand_ratio = float(filters.get("planned_max_queue_to_demand_ratio", 1.25))
    planned_max_share_of_estimated_demand = float(
        filters.get(
            "max_share_of_estimated_demand_per_position",
            filters.get("planned_max_share_of_estimated_demand_per_position", 0.50),
        )
    )
    reference_cfg = filters.get("reference_price", {})
    if not isinstance(reference_cfg, dict):
        reference_cfg = {}
    ref_enabled = bool(reference_cfg.get("enabled", False))
    ref_prefer = str(reference_cfg.get("prefer", "average_price")).lower()
    ref_fallback_to_adjusted = bool(reference_cfg.get("fallback_to_adjusted", True))
    ref_soft_sell_markup = float(reference_cfg.get("soft_sell_markup_vs_ref_planned", 0.50))
    ref_max_sell_markup = float(reference_cfg.get("max_sell_markup_vs_ref_planned", 1.00))
    ref_hard_max_sell_markup_raw = reference_cfg.get("hard_max_sell_markup_vs_ref_planned", None)
    ref_hard_max_sell_markup = None
    if ref_hard_max_sell_markup_raw is not None:
        try:
            ref_hard_max_sell_markup = float(ref_hard_max_sell_markup_raw)
        except Exception:
            ref_hard_max_sell_markup = None
    ref_penalty_strength = float(reference_cfg.get("ranking_penalty_strength", 0.35))
    strict_cfg = filters.get("strict_mode", {})
    if not isinstance(strict_cfg, dict):
        strict_cfg = {}
    if not isinstance(route_context, dict):
        route_context = {}
    shipping_lane_cfg = route_context.get("shipping_lane_cfg") if isinstance(route_context.get("shipping_lane_cfg"), dict) else None
    jita_split_prices = route_context.get("jita_split_prices", {})
    if not isinstance(jita_split_prices, dict):
        jita_split_prices = {}
    strict_enabled = bool(strict_cfg.get("enabled", False))
    strict_require_ref_planned = bool(
        filters.get("strict_require_reference_price_for_planned", strict_cfg.get("require_reference_price_for_planned", False))
    )
    strict_disable_fallback_planned = bool(
        filters.get("strict_disable_fallback_volume_for_planned", strict_cfg.get("disable_fallback_volume_for_planned", False))
    )
    strict_min_avg_daily_volume_7d = float(
        filters.get("strict_require_avg_daily_volume_7d", strict_cfg.get("planned_min_avg_daily_volume_7d", 0.0))
    )
    strict_planned_max_units_cap = int(
        filters.get("strict_planned_max_units_cap", strict_cfg.get("planned_max_units_cap", 0))
    )
    resolved_dest_region_id = int(dest_region_id or 0)
    if resolved_dest_region_id <= 0 and dest_structure_id:
        region_map = filters.get("structure_region_map", {})
        if isinstance(region_map, dict):
            try:
                resolved_dest_region_id = int(
                    region_map.get(str(int(dest_structure_id)), region_map.get(int(dest_structure_id), 0)) or 0
                )
            except Exception:
                resolved_dest_region_id = 0
    if ref_enabled and hasattr(esi, "preload_market_prices"):
        try:
            esi.preload_market_prices()
        except Exception:
            pass

    source_sell_by_type: dict[int, list[dict]] = {}
    source_buy_by_type: dict[int, list[dict]] = {}
    for o in source_orders:
        tid = int(o["type_id"])
        if bool(o.get("is_buy_order")):
            source_buy_by_type.setdefault(tid, []).append(o)
        else:
            source_sell_by_type.setdefault(tid, []).append(o)
    dest_sell_by_type: dict[int, list[dict]] = {}
    dest_buy_by_type: dict[int, list[dict]] = {}
    for o in dest_orders:
        tid = int(o["type_id"])
        if bool(o.get("is_buy_order")):
            dest_buy_by_type.setdefault(tid, []).append(o)
        else:
            dest_sell_by_type.setdefault(tid, []).append(o)

    src_sell_types = set(source_sell_by_type.keys())
    dst_buy_types = set(dest_buy_by_type.keys())
    dst_sell_types = set(dest_sell_by_type.keys())
    if mode == "instant":
        type_ids = sorted(src_sell_types & dst_buy_types)
    elif mode == "planned_sell":
        type_ids = sorted(src_sell_types & dst_sell_types)
    else:
        type_ids = sorted(src_sell_types & dst_sell_types)
    if explain is not None:
        explain.setdefault("kept", [])
        explain.setdefault("rejected", [])
        explain.setdefault("reason_counts", {})
        explain.setdefault("_first_rejection_by_type", {})

    def record_explain(status: str, tid: int, type_name: str, reason: str, metrics: dict | None = None) -> None:
        if explain is None:
            return
        if status == "rejected":
            first_rej = explain.get("_first_rejection_by_type", {})
            if tid in first_rej:
                return
            first_rej[tid] = reason
        rc = explain["reason_counts"]
        rc[reason] = int(rc.get(reason, 0)) + 1
        bucket = explain.get(status, [])
        if len(bucket) >= explain_max_entries:
            return
        bucket.append({
            "type_id": int(tid),
            "name": type_name,
            "reason": reason,
            "metrics": metrics or {}
        })
    if funnel:
        funnel.record_stage("initial", len(type_ids))
    # remove explicitly excluded type IDs if configured
    excluded = set(int(tid) for tid in filters.get("exclude_type_ids", []))
    if excluded:
        before = len(type_ids)
        if funnel:
            for tid in type_ids:
                if tid in excluded:
                    record_explain("rejected", tid, f"type_{tid}", "excluded_type_id")
                    funnel.record_rejection(tid, f"type_{tid}", "excluded_type_id")
        type_ids = [tid for tid in type_ids if tid not in excluded]
        removed = before - len(type_ids)
        if removed:
            print(f"  {removed} Typen anhand exclude_type_ids ausgeschlossen")
    if funnel:
        funnel.record_stage("excluded_type_id", len(type_ids))
        funnel.record_stage("exclude_type_ids", len(type_ids))
    print(f"  Resolving {len(type_ids)} type names...")
    names = esi.resolve_type_names(type_ids)
    print("  Type names resolved")

    # filter out unwanted items early based on name keywords
    exclude_kw = [kw.lower() for kw in filters.get("exclude_name_keywords", [])]
    legacy_kw = [kw.lower() for kw in filters.get("exclude_keywords", [])]
    if legacy_kw:
        exclude_kw.extend(legacy_kw)
    if exclude_kw:
        # de-dup while preserving order
        seen_kw = set()
        normalized_kw = []
        for kw in exclude_kw:
            k = str(kw).strip()
            if not k or k in seen_kw:
                continue
            seen_kw.add(k)
            normalized_kw.append(k)
        exclude_kw = normalized_kw
    if exclude_kw:
        orig_count = len(type_ids)
        kept = []
        for tid in type_ids:
            item_name = names.get(tid, "").lower()
            if any(kw in item_name for kw in exclude_kw):
                record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "excluded_name_keyword")
                if funnel:
                    funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "excluded_name_keyword")
                continue
            kept.append(tid)
        type_ids = kept
        removed = orig_count - len(type_ids)
        if removed:
            print(f"  Ausgeschlossen wegen Name-Keywords: {removed} Typen")
    if funnel:
        funnel.record_stage("excluded_name_keyword", len(type_ids))
        funnel.record_stage("exclude_keywords", len(type_ids))

    # filter by market history volume / liquidity at destination if configured
    min_hist_vol = int(filters.get("min_market_history_volume", 0))
    history_scores: dict[int, int] = {}
    history_volume_30d: dict[int, int] = {}
    history_order_count_30d: dict[int, int] = {}
    if history_probe_enabled and (min_hist_vol > 0 or min_liquidity_score > 0) and resolved_dest_region_id > 0:
        orig_count = len(type_ids)
        print(
            f"  Ueberpruefe regionale Markthistorie fuer {len(type_ids)} Typen "
            f"(Region {resolved_dest_region_id}, min. {min_hist_vol} Einheiten/30d)..."
        )
        # Parallelize history checks with limited concurrency, using internal cache
        from concurrent.futures import ThreadPoolExecutor, as_completed
        filtered_type_ids = []
        # choose a modest worker count to avoid hitting rate limits
        max_workers = min(6, max(1, len(type_ids) // 200))
        max_workers = max(2, max_workers)
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for tid in type_ids:
                futures[ex.submit(esi.get_region_history_stats, resolved_dest_region_id, tid, 30)] = tid

            completed = 0
            for fut in as_completed(futures):
                tid = futures[fut]
                completed += 1
                if completed % 50 == 0:
                    print(f"    Markthistorie: {completed}/{len(type_ids)}...")
                try:
                    stats = fut.result()
                except Exception:
                    stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                if not isinstance(stats, dict):
                    try:
                        stats = {"volume": int(stats), "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                    except Exception:
                        stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                hist_vol = stats.get("volume", 0)
                hist_orders = int(stats.get("order_count", 0) or 0)
                days_with = int(stats.get("days_with_trades", 0) or 0)
                recent = bool(stats.get("recent_activity", False))
                vol_component = min(60.0, max(0.0, math.log10(max(float(hist_vol), 1.0)) * 15.0))
                days_component = min(30.0, float(days_with))
                recent_component = 10.0 if recent else 0.0
                liquidity_score = int(vol_component + days_component + recent_component)
                history_scores[tid] = liquidity_score
                history_volume_30d[tid] = int(hist_vol)
                history_order_count_30d[tid] = int(hist_orders)
                # depth will be computed later per-type; here we do a minimal filter
                # accept types that meet min_hist_vol and min_liquidity_score
                if hist_vol >= min_hist_vol and liquidity_score >= min_liquidity_score and hist_orders >= min_history_order_count:
                    filtered_type_ids.append(tid)
                elif funnel:
                    if hist_vol < min_hist_vol:
                        record_explain(
                            "rejected",
                            tid,
                            names.get(tid, f"type_{tid}"),
                            "market_history",
                            {"history_volume_30d": int(hist_vol), "min_market_history_volume": int(min_hist_vol)}
                        )
                        funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "market_history")
                    elif hist_orders < min_history_order_count:
                        record_explain(
                            "rejected",
                            tid,
                            names.get(tid, f"type_{tid}"),
                            "market_history_order_count",
                            {
                                "history_order_count_30d": int(hist_orders),
                                "min_market_history_order_count": int(min_history_order_count)
                            }
                        )
                        funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "market_history_order_count")
                    else:
                        record_explain(
                            "rejected",
                            tid,
                            names.get(tid, f"type_{tid}"),
                            "liquidity_score",
                            {"liquidity_score": int(liquidity_score), "min_liquidity_score": int(min_liquidity_score)}
                        )
                        funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "liquidity_score")
        type_ids = filtered_type_ids
        removed = orig_count - len(type_ids)
        if removed:
            print(f"  {removed} Typen wegen unzureichender Markthistorie ausgeschlossen (< {min_hist_vol} units/30d)")
    if funnel:
        funnel.record_stage("market_history", len(type_ids))
        funnel.record_stage("liquidity_score", len(type_ids))

    candidates: list[TradeCandidate] = []
    for idx, tid in enumerate(type_ids):
        if (idx + 1) % 100 == 0:
            print(f"  Verarbeite Typen: {idx + 1}/{len(type_ids)}...")
        src_lv = build_levels(source_sell_by_type.get(tid, []), is_buy=False)
        if src_lv and min_units_in_window > 0:
            window_units = int(sum(lv.volume for lv in src_lv[:max(1, window_levels_for_units)]))
            if window_units < min_units_in_window:
                record_explain(
                    "rejected",
                    tid,
                    names.get(tid, f"type_{tid}"),
                    "orderbook_window_units_too_low",
                    {
                        "window_units": int(window_units),
                        "min_units_in_window": int(min_units_in_window),
                        "window_levels_for_units": int(window_levels_for_units)
                    }
                )
                continue

        instant_flag = True
        sell_sugg = None

        target_sell_price = 0.0
        target_price_basis = ""
        target_price_confidence = 0.0
        has_reliable_price_basis = False
        queue_ahead_units = 0
        competition_price_levels_near_best = 0
        if mode == "instant":
            dst_lv = build_levels(dest_buy_by_type.get(tid, []), is_buy=True)
            if not src_lv or not dst_lv:
                # no buy orders available - try fast_sell fallback
                dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
                if not src_lv or not dst_sell_lv:
                    record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "no_orderbook")
                    continue
                buy_avg, buy_qty = depth_slice(src_lv, is_buy=False, depth_pct=depth_pct)
                best_sell_price = dst_sell_lv[0].price
                sell_avg = best_sell_price * (1.0 - undercut_pct)
                sell_qty = sum(lv.volume for lv in dst_sell_lv[:5])
                instant_flag = False
                sell_sugg = sell_avg
            else:
                buy_avg, buy_qty = depth_slice(
                    src_lv, is_buy=False, depth_pct=depth_pct,
                    outlier_ratio=outlier_ratio,
                    outlier_window_levels=outlier_window_levels,
                    min_top_level_units=min_top_level_units
                )
                sell_avg, sell_qty = depth_slice(
                    dst_lv, is_buy=True, depth_pct=depth_pct,
                    outlier_ratio=outlier_ratio,
                    outlier_window_levels=outlier_window_levels,
                    min_top_level_units=min_top_level_units
                )
        elif mode == "fast_sell":
            # fast_sell: use destination sell side and offer just under the best price
            dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
            if not src_lv or not dst_sell_lv:
                record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "no_orderbook")
                continue
            buy_avg, buy_qty = depth_slice(
                src_lv, is_buy=False, depth_pct=depth_pct,
                outlier_ratio=outlier_ratio,
                outlier_window_levels=outlier_window_levels,
                min_top_level_units=min_top_level_units
            )

            best_sell_price = dst_sell_lv[0].price
            sell_avg = best_sell_price * (1.0 - undercut_pct)
            sell_qty = sum(lv.volume for lv in dst_sell_lv[:5])
            instant_flag = False
            sell_sugg = sell_avg
        else:
            # planned_sell: buy at source now, list at destination sell side and evaluate
            # expected sell-through over horizon_days from market history.
            dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
            if not src_lv or not dst_sell_lv:
                record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "no_orderbook")
                continue
            buy_avg, buy_qty = depth_slice(
                src_lv, is_buy=False, depth_pct=depth_pct,
                outlier_ratio=outlier_ratio,
                outlier_window_levels=outlier_window_levels,
                min_top_level_units=min_top_level_units
            )
            price_eval = _derive_planned_sell_price(
                dst_sell_lv=dst_sell_lv,
                undercut_pct=undercut_pct,
                competition_band_pct=competition_band_pct,
                min_top_level_units=min_top_level_units,
                min_supported_levels=planned_min_supported_sell_levels,
                max_isolated_top_gap_pct=planned_max_isolated_top_gap_pct,
                reactive_queue_ratio=planned_reactive_queue_ratio,
            )
            if not bool(price_eval.get("valid", False)):
                record_explain(
                    "rejected",
                    tid,
                    names.get(tid, f"type_{tid}"),
                    str(price_eval.get("reason", "planned_price_unreliable_orderbook")),
                    {
                        "best_price": float(price_eval.get("best_price", 0.0) or 0.0),
                        "best_level_units": int(price_eval.get("best_level_units", 0) or 0),
                        "band_level_count": int(price_eval.get("band_level_count", 0) or 0),
                        "band_units": int(price_eval.get("band_units", 0) or 0),
                        "top_gap_pct": float(price_eval.get("top_gap_pct", 0.0) or 0.0),
                    }
                )
                continue
            target_sell_price = float(price_eval.get("target_sell_price", 0.0) or 0.0)
            sell_avg = target_sell_price
            sell_qty = int(buy_qty)
            instant_flag = False
            sell_sugg = target_sell_price
            target_price_basis = str(price_eval.get("price_basis", "") or "")
            target_price_confidence = float(price_eval.get("target_price_confidence", 0.0) or 0.0)
            has_reliable_price_basis = bool(price_eval.get("has_reliable_price_basis", False))
            queue_ahead_units = int(price_eval.get("queue_ahead_units", 0) or 0)
            competition_price_levels_near_best = int(price_eval.get("competition_price_levels_near_best", 0) or 0)

        max_units = min(buy_qty, sell_qty)
        if buy_avg < min_source_sell_price_isk:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "orderbook_min_source_sell_price",
                {
                    "buy_avg_price": float(buy_avg),
                    "min_source_sell_price_isk": float(min_source_sell_price_isk)
                }
            )
            continue
        if max_units < min_depth_units:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "min_depth_units",
                {"max_units": int(max_units), "min_depth_units": int(min_depth_units)}
            )
            continue

        unit_vol = esi.resolve_type_volume(tid)
        if unit_vol <= 0:
            unit_vol = 1.0

        cost_net, revenue_net, profit_per_unit, _ = compute_trade_financials(
            buy_avg,
            sell_avg,
            1,
            fees,
            instant_flag,
            execution_mode=mode,
            relist_budget_pct=relist_budget_pct,
            relist_budget_isk=(relist_budget_isk if mode == "planned_sell" else 0.0),
        )
        if profit_per_unit <= 0:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "non_positive_profit_90d" if mode == "planned_sell" else "non_positive_profit",
                {"profit_per_unit": float(profit_per_unit)}
            )
            continue

        profit_pct = profit_per_unit / cost_net if cost_net > 0 else 0.0
        if profit_pct < min_profit_pct:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "min_profit_pct",
                {"profit_pct": float(profit_pct), "min_profit_pct": float(min_profit_pct)}
            )
            continue

        name = names.get(tid, f"type_{tid}")
        hist_vol_30d = int(history_volume_30d.get(tid, 0))
        hist_orders_30d = int(history_order_count_30d.get(tid, 0))
        hist_vol_7d = 0
        used_volume_fallback = False
        reference_price = 0.0
        reference_price_average = 0.0
        reference_price_adjusted = 0.0
        reference_price_source = ""
        buy_discount_vs_ref = 0.0
        sell_markup_vs_ref = 0.0
        reference_price_penalty = 0.0
        strict_confidence_score = 0.0
        avg_daily_volume_7d = 0.0
        micro_liq = get_structure_micro_liquidity(dest_orders, tid)
        spread_pct = float(micro_liq.get("spread_pct", 1.0))
        depth_within_2pct_buy = int(micro_liq.get("depth_within_2pct_buy", 0))
        depth_within_2pct_sell = int(micro_liq.get("depth_within_2pct_sell", 0))
        orderbook_imbalance = float(micro_liq.get("orderbook_imbalance", 0.0))
        competition_density_near_best = int(micro_liq.get("competition_density_near_best", 0))
        if ref_enabled and hasattr(esi, "get_market_reference_price"):
            try:
                rp, rp_source, rp_avg, rp_adj = esi.get_market_reference_price(
                    tid, prefer=ref_prefer, fallback_to_adjusted=ref_fallback_to_adjusted
                )
            except Exception:
                rp, rp_source, rp_avg, rp_adj = 0.0, "", 0.0, 0.0
            reference_price = float(rp or 0.0)
            reference_price_source = str(rp_source or "")
            reference_price_average = float(rp_avg or 0.0)
            reference_price_adjusted = float(rp_adj or 0.0)
            if reference_price > 0:
                buy_discount_vs_ref = (reference_price - float(buy_avg)) / reference_price
                planned_price = float(target_sell_price if target_sell_price > 0 else sell_avg)
                sell_markup_vs_ref = (planned_price - reference_price) / reference_price
                if (
                    mode == "planned_sell"
                    and ref_hard_max_sell_markup is not None
                    and sell_markup_vs_ref > ref_hard_max_sell_markup
                ):
                    record_explain(
                        "rejected",
                        tid,
                        names.get(tid, f"type_{tid}"),
                        "strict_reference_price_hard_sell_markup" if strict_enabled else "reference_price_hard_sell_markup",
                        {
                            "sell_markup_vs_ref": float(sell_markup_vs_ref),
                            "hard_max_sell_markup_vs_ref_planned": float(ref_hard_max_sell_markup),
                            "reference_price": float(reference_price),
                            "planned_sell_price": float(planned_price)
                        }
                    )
                    continue
                if mode == "planned_sell" and sell_markup_vs_ref > ref_soft_sell_markup:
                    hard = max(ref_max_sell_markup, ref_soft_sell_markup + 1e-9)
                    ramp = (sell_markup_vs_ref - ref_soft_sell_markup) / max(1e-9, hard - ref_soft_sell_markup)
                    ramp = max(0.0, min(1.0, ramp))
                    reference_price_penalty = ramp * max(0.0, min(1.0, ref_penalty_strength))
        if mode == "planned_sell" and strict_enabled and strict_require_ref_planned and reference_price <= 0.0:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "strict_missing_reference_price"
            )
            continue
        if mode == "planned_sell" and ref_enabled and reference_price > 0.0 and sell_markup_vs_ref > ref_max_sell_markup:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "reference_price_plausibility",
                {
                    "sell_markup_vs_ref": float(sell_markup_vs_ref),
                    "max_sell_markup_vs_ref_planned": float(ref_max_sell_markup),
                    "reference_price": float(reference_price),
                    "target_sell_price": float(target_sell_price if target_sell_price > 0 else sell_avg),
                }
            )
            continue
        if mode == "planned_sell" and resolved_dest_region_id <= 0:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "missing_region_mapping"
            )
            continue
        if mode == "planned_sell" and resolved_dest_region_id > 0:
            hist_stats = esi.get_region_history_stats(resolved_dest_region_id, tid, history_days)
            hist_vol_30d = int((hist_stats or {}).get("volume", 0) if isinstance(hist_stats, dict) else 0)
            hist_orders_30d = int((hist_stats or {}).get("order_count", 0) if isinstance(hist_stats, dict) else 0)
            if strict_enabled and strict_min_avg_daily_volume_7d > 0:
                hist_stats_7d = esi.get_region_history_stats(resolved_dest_region_id, tid, 7)
                hist_vol_7d = int((hist_stats_7d or {}).get("volume", 0) if isinstance(hist_stats_7d, dict) else 0)
        if mode == "planned_sell":
            if hist_vol_30d > 0:
                avg_daily_volume_30d = float(hist_vol_30d) / max(1.0, float(history_days))
            else:
                avg_daily_volume_30d = float(fallback_daily_volume)
                used_volume_fallback = True
            if hist_vol_7d > 0:
                avg_daily_volume_7d = float(hist_vol_7d) / 7.0
            if used_volume_fallback:
                avg_daily_volume_30d *= fallback_volume_penalty
                if fallback_max_units_cap > 0:
                    max_units = min(max_units, fallback_max_units_cap)
            if strict_enabled and strict_planned_max_units_cap > 0:
                max_units = min(max_units, strict_planned_max_units_cap)
            daily_vol = avg_daily_volume_30d
        else:
            daily_vol = float(hist_vol_30d) / 30.0 if hist_vol_30d > 0 else 0.0
            avg_daily_volume_30d = daily_vol
            avg_daily_volume_7d = 0.0
        dest_buy_depth_units = int(sell_qty) if instant_flag else 0
        instant_fill_ratio = 1.0 if instant_flag else 1.0
        if instant_flag and dest_buy_depth_units < min_dest_buy_depth_units:
            record_explain(
                "rejected",
                tid,
                name,
                "dest_buy_depth_units",
                {"dest_buy_depth_units": int(dest_buy_depth_units), "min_dest_buy_depth_units": int(min_dest_buy_depth_units)}
            )
            continue
        fill_probability = 1.0 if instant_flag else 0.0
        gross_profit_if_full_sell = 0.0
        expected_units_sold_90d = 0.0
        expected_units_unsold_90d = 0.0
        expected_realized_profit_90d = 0.0
        expected_realized_profit_per_m3_90d = 0.0
        estimated_sellable_units_90d = 0.0
        liquidity_confidence = 0.0
        exit_confidence = 0.0
        overall_confidence = 0.0
        estimated_transport_cost = 0.0
        expected_days_to_sell = 0.0
        sell_through_ratio_90d = 0.0
        risk_score = 0.0
        expected_profit_90d = 0.0
        expected_profit_per_m3_90d = 0.0
        trade_profit_per_unit_before_transport = float(profit_per_unit)
        gross_profit_if_full_sell = float(trade_profit_per_unit_before_transport) * float(max_units)
        expected_profit_90d = 0.0
        expected_profit_per_m3_90d = 0.0
        split_px = 0.0
        if instant_flag:
            coverage = float(dest_buy_depth_units) / max(1.0, float(max_units))
            instant_fill_ratio = min(1.0, max(0.0, coverage))
            queue_ahead_units = 0
            if coverage >= 1.5 and queue_ahead_units <= 0:
                fill_probability = 1.0
            else:
                fill_probability = min(0.99, max(0.0, coverage))
            expected_units_sold_90d = float(max_units) * float(fill_probability)
            expected_units_unsold_90d = max(0.0, float(max_units) - float(expected_units_sold_90d))
            expected_realized_profit_90d = float(trade_profit_per_unit_before_transport) * float(expected_units_sold_90d)
            expected_realized_profit_per_m3_90d = (
                expected_realized_profit_90d / max(1.0, float(max_units) * float(unit_vol))
            ) if unit_vol > 0 else 0.0
            estimated_sellable_units_90d = float(dest_buy_depth_units)
            liquidity_confidence = _clamp01(0.50 + (float(fill_probability) * 0.50))
            exit_confidence = liquidity_confidence
            overall_confidence = liquidity_confidence
            expected_profit_90d = expected_realized_profit_90d
            expected_profit_per_m3_90d = expected_realized_profit_per_m3_90d
        elif mode == "planned_sell":
            if avg_daily_volume_30d <= 0:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "no_history_volume",
                    {"history_days": int(history_days), "fallback_daily_volume": float(fallback_daily_volume)}
                )
                continue
            if strict_enabled and strict_disable_fallback_planned and used_volume_fallback:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_no_fallback_volume",
                    {"used_volume_fallback": True}
                )
                continue
            if (avg_daily_volume_30d + 1e-9) < min_avg_daily_volume:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "avg_daily_volume_too_low",
                    {"avg_daily_volume_30d": float(avg_daily_volume_30d), "min_avg_daily_volume": float(min_avg_daily_volume)}
                )
                continue
            if strict_enabled and strict_min_avg_daily_volume_7d > 0.0 and (avg_daily_volume_7d + 1e-9) < strict_min_avg_daily_volume_7d:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_avg_daily_volume_7d_too_low",
                    {
                        "avg_daily_volume_7d": float(avg_daily_volume_7d),
                        "strict_min_avg_daily_volume_7d": float(strict_min_avg_daily_volume_7d)
                    }
                )
                continue
            if hist_orders_30d < min_history_order_count:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_history_order_count",
                    {
                        "history_order_count_30d": int(hist_orders_30d),
                        "min_market_history_order_count": int(min_history_order_count),
                    }
                )
                continue
            if used_volume_fallback and profit_pct < fallback_require_high_profit_pct:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "fallback_profit_pct_too_low",
                    {
                        "profit_pct": float(profit_pct),
                        "fallback_require_high_profit_pct": float(fallback_require_high_profit_pct)
                    }
                )
                continue
            depth_ok = depth_within_2pct_sell >= min_depth_within_2pct_sell
            density_ok = (
                competition_density_near_best >= min_competition_density_near_best
                and competition_density_near_best <= max_competition_density_near_best
            )
            if not (depth_ok and density_ok and has_reliable_price_basis):
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_structure_micro_liquidity",
                    {
                        "depth_within_2pct_sell": int(depth_within_2pct_sell),
                        "min_depth_within_2pct_sell": int(min_depth_within_2pct_sell),
                        "competition_density_near_best": int(competition_density_near_best),
                        "min_competition_density_near_best": int(min_competition_density_near_best),
                        "max_competition_density_near_best": int(max_competition_density_near_best),
                        "has_reliable_price_basis": bool(has_reliable_price_basis),
                        "target_price_confidence": float(target_price_confidence),
                    }
                )
                continue
            structure_confidence = _planned_structure_liquidity_confidence(
                depth_within_2pct_sell=depth_within_2pct_sell,
                min_depth_within_2pct_sell=min_depth_within_2pct_sell,
                competition_density_near_best=competition_density_near_best,
                min_competition_density_near_best=min_competition_density_near_best,
                max_competition_density_near_best=max_competition_density_near_best,
                price_basis_confidence=target_price_confidence,
            )
            history_confidence = 0.30 if used_volume_fallback else 0.55
            history_confidence += min(0.15, max(0.0, avg_daily_volume_30d) * 0.01)
            if strict_min_avg_daily_volume_7d > 0.0:
                history_confidence += min(
                    0.15,
                    max(0.0, avg_daily_volume_7d / max(1e-9, strict_min_avg_daily_volume_7d)) * 0.15,
                )
            elif avg_daily_volume_7d > 0.0:
                history_confidence += min(0.10, float(avg_daily_volume_7d) * 0.01)
            history_confidence = _clamp01(history_confidence - planned_history_only_confidence_penalty)

            conservative_market_capture_pct = planned_fallback_market_capture_pct if used_volume_fallback else planned_market_capture_pct
            effective_daily_sellable = float(avg_daily_volume_30d) * max(0.01, float(conservative_market_capture_pct))
            effective_daily_sellable *= max(0.35, float(structure_confidence))
            effective_daily_sellable *= max(0.35, float(target_price_confidence))
            effective_daily_sellable *= max(0.25, 1.0 - max(0.0, float(reference_price_penalty)))
            effective_daily_sellable *= max(0.25, float(planned_history_only_expectation_penalty))

            queue_to_demand_ratio = float(queue_ahead_units) / max(1.0, float(avg_daily_volume_30d) * float(horizon_days))
            if queue_to_demand_ratio > planned_max_queue_to_demand_ratio:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_queue_ahead_too_heavy",
                    {
                        "queue_ahead_units": int(queue_ahead_units),
                        "avg_daily_volume_30d": float(avg_daily_volume_30d),
                        "horizon_days": int(horizon_days),
                        "queue_to_demand_ratio": float(queue_to_demand_ratio),
                        "planned_max_queue_to_demand_ratio": float(planned_max_queue_to_demand_ratio),
                    }
                )
                continue

            estimated_sellable_units_90d = max(
                0.0,
                (float(effective_daily_sellable) * float(horizon_days)) - float(queue_ahead_units),
            )
            position_cap_share = min(
                max(0.05, float(planned_max_share_of_estimated_demand)),
                max(0.05, float(planned_history_only_position_cap)),
            )
            demand_limited_units = int(math.floor(float(estimated_sellable_units_90d) * float(position_cap_share)))
            if used_volume_fallback:
                demand_limited_units = min(
                    demand_limited_units if demand_limited_units > 0 else 0,
                    max(1, int(math.floor(float(fallback_max_units_cap) * 0.75))) if fallback_max_units_cap > 0 else 0,
                )
            if demand_limited_units <= 0:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_demand_cap_zero",
                    {
                        "estimated_sellable_units_90d": float(estimated_sellable_units_90d),
                        "position_cap_share": float(position_cap_share),
                    }
                )
                continue
            max_units = min(max_units, demand_limited_units)
            if strict_enabled and strict_planned_max_units_cap > 0:
                max_units = min(max_units, strict_planned_max_units_cap)
            if max_units < min_depth_units:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_demand_cap_too_low",
                    {
                        "max_units": int(max_units),
                        "min_depth_units": int(min_depth_units),
                        "estimated_sellable_units_90d": float(estimated_sellable_units_90d),
                    }
                )
                continue

            expected_days_to_sell = float(queue_ahead_units + max_units) / max(float(effective_daily_sellable), 1e-9)
            liquidity_confidence = _clamp01(
                (float(structure_confidence) * 0.40)
                + (float(history_confidence) * 0.30)
                + (_clamp01(float(estimated_sellable_units_90d) / max(1.0, float(max_units))) * 0.30)
            )
            exit_confidence = _clamp01(
                (float(target_price_confidence) * 0.45)
                + (float(liquidity_confidence) * 0.35)
                + ((1.0 - max(0.0, float(reference_price_penalty))) * 0.20)
                - float(planned_history_only_confidence_penalty)
            )
            overall_confidence = min(liquidity_confidence, exit_confidence)
            if liquidity_confidence < planned_min_liquidity_confidence or exit_confidence < planned_min_exit_confidence:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_low_confidence",
                    {
                        "liquidity_confidence": float(liquidity_confidence),
                        "planned_min_liquidity_confidence": float(planned_min_liquidity_confidence),
                        "exit_confidence": float(exit_confidence),
                        "planned_min_exit_confidence": float(planned_min_exit_confidence),
                    }
                )
                continue

            expected_sell_ratio = min(0.90, max(0.10, 0.20 + (float(overall_confidence) * 0.70)))
            if used_volume_fallback:
                expected_sell_ratio = min(expected_sell_ratio, fallback_fill_probability_cap)
            expected_units_sold_90d = float(max_units) * float(expected_sell_ratio)
            expected_units_unsold_90d = max(0.0, float(max_units) - float(expected_units_sold_90d))
            fill_probability = _clamp01(expected_sell_ratio)
            sell_through_ratio_90d = float(expected_units_sold_90d) / max(1.0, float(max_units))
            risk_score = _clamp01(1.0 - float(overall_confidence))
            expected_realized_profit_90d = float(trade_profit_per_unit_before_transport) * float(expected_units_sold_90d)
            expected_realized_profit_per_m3_90d = (
                expected_realized_profit_90d / max(1.0, float(max_units) * float(unit_vol))
            ) if unit_vol > 0 else 0.0
            expected_profit_90d = expected_realized_profit_90d
            expected_profit_per_m3_90d = expected_realized_profit_per_m3_90d
            if strict_enabled and expected_days_to_sell > max_expected_days_to_sell:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_expected_days_too_high",
                    {
                        "expected_days_to_sell": float(expected_days_to_sell),
                        "strict_max_expected_days_to_sell": float(max_expected_days_to_sell)
                    }
                )
                continue
            if expected_days_to_sell > max_expected_days_to_sell:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "expected_days_too_high",
                    {"expected_days_to_sell": float(expected_days_to_sell), "max_expected_days_to_sell": float(max_expected_days_to_sell)}
                )
                continue
            if strict_enabled and sell_through_ratio_90d < min_sell_through_ratio_90d:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_sell_through_too_low",
                    {
                        "sell_through_ratio_90d": float(sell_through_ratio_90d),
                        "strict_min_sell_through_ratio_90d": float(min_sell_through_ratio_90d)
                    }
                )
                continue
            if sell_through_ratio_90d < min_sell_through_ratio_90d:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "sell_through_too_low",
                    {"sell_through_ratio_90d": float(sell_through_ratio_90d), "min_sell_through_ratio_90d": float(min_sell_through_ratio_90d)}
                )
                continue
            if expected_realized_profit_90d < min_expected_profit_isk:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "expected_profit_too_low",
                    {
                        "expected_realized_profit_90d": float(expected_realized_profit_90d),
                        "min_expected_profit_isk": float(min_expected_profit_isk),
                    }
                )
                continue
        elif not instant_flag:
            dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
            if dst_sell_lv:
                best_sell = dst_sell_lv[0].price
                band_cutoff = best_sell * (1.0 + competition_band_pct)
                competition_price_levels_near_best = sum(1 for lv in dst_sell_lv if lv.price <= band_cutoff)
                queue_ahead_units = sum(lv.volume for lv in dst_sell_lv if lv.price <= band_cutoff)
                denom = max(1.0, float(queue_ahead_units + max_units))
                fill_probability = min(1.0, daily_vol / denom) if daily_vol > 0 else 0.0
            expected_units_sold_90d = float(max_units) * float(fill_probability)
            expected_units_unsold_90d = max(0.0, float(max_units) - float(expected_units_sold_90d))
            expected_realized_profit_90d = float(trade_profit_per_unit_before_transport) * float(expected_units_sold_90d)
            expected_realized_profit_per_m3_90d = (
                expected_realized_profit_90d / max(1.0, float(max_units) * float(unit_vol))
            ) if unit_vol > 0 else 0.0
            estimated_sellable_units_90d = float(daily_vol) * float(horizon_days)
            liquidity_confidence = _clamp01(float(fill_probability))
            exit_confidence = liquidity_confidence
            overall_confidence = liquidity_confidence
            expected_profit_90d = expected_realized_profit_90d
            expected_profit_per_m3_90d = expected_realized_profit_per_m3_90d

        if shipping_lane_cfg is not None and max_units > 0:
            ship_defaults = route_context.get("shipping_defaults", {})
            if not isinstance(ship_defaults, dict):
                ship_defaults = {}
            collateral_buffer_pct = max(0.0, float(ship_defaults.get("collateral_buffer_pct", 0.0) or 0.0))
            ref_for_collateral = float(reference_price_adjusted if reference_price_adjusted > 0 else reference_price)
            base_collateral = max(
                float(cost_net * float(max_units)),
                max(0.0, ref_for_collateral * float(max_units))
            )
            split_px = float(jita_split_prices.get(int(tid), 0.0) or 0.0)
            collateral_basis = str(shipping_lane_cfg.get("collateral_basis", "auto") or "auto").strip().lower()
            if collateral_basis in ("jita_split", "jita_mid"):
                if split_px > 0.0:
                    base_collateral = split_px * float(max_units)
            elif collateral_basis == "auto" and bool(route_context.get("jita_based_route", False)) and split_px > 0.0:
                base_collateral = split_px * float(max_units)
            conservative_collateral = max(0.0, base_collateral) * (1.0 + collateral_buffer_pct)
            est_shipping_total = float(compute_shipping_lane_total_cost(
                lane_cfg=shipping_lane_cfg,
                total_volume_m3=float(unit_vol) * float(max_units),
                total_collateral_isk=conservative_collateral
            ).get("total_cost", 0.0))
            estimated_transport_cost = float(est_shipping_total)
            est_shipping_per_unit = est_shipping_total / max(1.0, float(max_units))
            profit_per_unit -= est_shipping_per_unit
            gross_profit_if_full_sell = float(trade_profit_per_unit_before_transport) * float(max_units) - float(est_shipping_total)
            expected_realized_profit_90d = float(trade_profit_per_unit_before_transport) * float(expected_units_sold_90d) - float(est_shipping_total)
            expected_realized_profit_per_m3_90d = (
                expected_realized_profit_90d / max(1.0, float(max_units) * float(unit_vol))
            ) if unit_vol > 0 else 0.0
            expected_profit_90d = expected_realized_profit_90d
            expected_profit_per_m3_90d = expected_realized_profit_per_m3_90d
            if profit_per_unit <= 0.0:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "shipping_cost_non_positive_profit",
                    {"estimated_shipping_total": float(est_shipping_total)}
                )
                continue
            profit_pct = profit_per_unit / cost_net if cost_net > 0 else 0.0
            if profit_pct < min_profit_pct:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "min_profit_pct_after_shipping",
                    {"profit_pct": float(profit_pct), "min_profit_pct": float(min_profit_pct)}
                )
                continue
            if mode == "planned_sell" and expected_realized_profit_90d < min_expected_profit_isk:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "expected_profit_too_low_after_shipping",
                    {
                        "expected_realized_profit_90d": float(expected_realized_profit_90d),
                        "min_expected_profit_isk": float(min_expected_profit_isk),
                        "estimated_shipping_total": float(est_shipping_total),
                    }
                )
                continue
        if mode != "planned_sell" and fill_probability < min_fill_probability:
            record_explain(
                "rejected",
                tid,
                name,
                "fill_probability",
                {"fill_probability": float(fill_probability), "min_fill_probability": float(min_fill_probability)}
            )
            if funnel:
                funnel.record_rejection(tid, name, "fill_probability")
            continue

        if instant_flag:
            # Candidate-stage proxy for instant mode; true fill ratio is computed on final portfolio qty.
            turnover_factor = 1.0
        elif mode == "planned_sell":
            turnover_factor = min(max_turnover_factor, max(0.0, float(expected_units_sold_90d) / max(1.0, float(max_units))))
        else:
            effective_daily_vol = daily_vol if daily_vol > 0 else fallback_daily_volume
            turnover_factor = (effective_daily_vol / max(1.0, float(max_units))) if max_units > 0 else 0.0
            turnover_factor = min(max_turnover_factor, max(0.0, turnover_factor))
        profit_per_m3 = (profit_per_unit / unit_vol) if unit_vol > 0 else 0.0
        profit_per_m3_per_day = profit_per_m3 * turnover_factor
        if mode == "planned_sell":
            strict_confidence_score = _clamp01(float(overall_confidence))
        else:
            liquidity_confidence = max(liquidity_confidence, _clamp01(float(fill_probability)))
            exit_confidence = max(exit_confidence, liquidity_confidence)
            overall_confidence = max(overall_confidence, min(exit_confidence, liquidity_confidence))
            strict_confidence_score = _clamp01(float(overall_confidence if overall_confidence > 0.0 else fill_probability))

        if mode in ("fast_sell", "planned_sell"):
            print(f"    Hinweis: {name} (type_id {tid}) benoetigt Verkaufsauftrag @ {sell_sugg:.2f} fuer {order_duration}d")
        candidates.append(
            TradeCandidate(
                type_id=tid,
                name=name,
                unit_volume=unit_vol,
                buy_avg=buy_avg,
                sell_avg=sell_avg,
                max_units=max_units,
                profit_per_unit=profit_per_unit,
                profit_pct=profit_pct,
                instant=instant_flag,
                suggested_sell_price=sell_sugg,
                liquidity_score=history_scores.get(tid, 0),
                history_volume_30d=hist_vol_30d,
                history_order_count_30d=hist_orders_30d,
                daily_volume=daily_vol,
                dest_buy_depth_units=dest_buy_depth_units,
                instant_fill_ratio=instant_fill_ratio,
                competition_price_levels_near_best=competition_price_levels_near_best,
                queue_ahead_units=queue_ahead_units,
                spread_pct=float(spread_pct),
                depth_within_2pct_buy=int(depth_within_2pct_buy),
                depth_within_2pct_sell=int(depth_within_2pct_sell),
                orderbook_imbalance=float(orderbook_imbalance),
                competition_density_near_best=int(competition_density_near_best),
                fill_probability=fill_probability,
                turnover_factor=turnover_factor,
                profit_per_m3=profit_per_m3,
                profit_per_m3_per_day=profit_per_m3_per_day,
                mode=mode,
                exit_type=("instant" if instant_flag else ("planned" if mode == "planned_sell" else "speculative")),
                target_sell_price=float(target_sell_price if target_sell_price > 0 else (sell_sugg or 0.0)),
                target_price_basis=str(target_price_basis),
                target_price_confidence=float(target_price_confidence),
                has_reliable_price_basis=bool(has_reliable_price_basis),
                estimated_transport_cost=float(estimated_transport_cost),
                avg_daily_volume_30d=float(avg_daily_volume_30d),
                avg_daily_volume_7d=float(avg_daily_volume_7d),
                estimated_sellable_units_90d=float(estimated_sellable_units_90d),
                expected_days_to_sell=float(expected_days_to_sell),
                sell_through_ratio_90d=float(sell_through_ratio_90d),
                risk_score=float(risk_score),
                gross_profit_if_full_sell=float(gross_profit_if_full_sell),
                expected_units_sold_90d=float(expected_units_sold_90d),
                expected_units_unsold_90d=float(expected_units_unsold_90d),
                expected_realized_profit_90d=float(expected_realized_profit_90d),
                expected_realized_profit_per_m3_90d=float(expected_realized_profit_per_m3_90d),
                exit_confidence=float(exit_confidence),
                liquidity_confidence=float(liquidity_confidence),
                overall_confidence=float(overall_confidence if overall_confidence > 0.0 else strict_confidence_score),
                expected_profit_90d=float(expected_profit_90d),
                expected_profit_per_m3_90d=float(expected_profit_per_m3_90d),
                used_volume_fallback=bool(used_volume_fallback),
                reference_price=float(reference_price),
                reference_price_average=float(reference_price_average),
                reference_price_adjusted=float(reference_price_adjusted),
                reference_price_source=str(reference_price_source),
                buy_discount_vs_ref=float(buy_discount_vs_ref),
                sell_markup_vs_ref=float(sell_markup_vs_ref),
                reference_price_penalty=float(reference_price_penalty),
                strict_confidence_score=float(strict_confidence_score),
                strict_mode_enabled=bool(strict_enabled),
                jita_split_price=float(split_px),
            )
        )

    ranking_metric = str(filters.get("ranking_metric", "profit_per_m3_per_day")).lower()
    if ranking_metric == "expected_profit_per_m3_90d":
        candidates.sort(
            key=lambda c: (
                c.expected_realized_profit_per_m3_90d,
                c.expected_realized_profit_90d,
                -c.expected_days_to_sell,
                c.overall_confidence,
            ),
            reverse=True
        )
    elif ranking_metric == "profit_per_m3":
        candidates.sort(key=lambda c: (c.profit_per_m3, c.profit_pct), reverse=True)
    elif ranking_metric == "profit":
        candidates.sort(key=lambda c: (c.profit_per_unit * c.max_units, c.profit_pct), reverse=True)
    else:
        candidates.sort(key=lambda c: (c.profit_per_m3_per_day, c.profit_per_m3, c.profit_pct), reverse=True)

    filtered = []
    for c in candidates:
        max_profit_total = c.expected_realized_profit_90d if mode == "planned_sell" else (c.profit_per_unit * c.max_units)
        if max_profit_total >= min_profit_total:
            filtered.append(c)
            kept_metrics = {
                "profit_pct": float(c.profit_pct),
                "min_profit_pct": float(min_profit_pct),
                "max_units": int(c.max_units),
                "min_depth_units": int(min_depth_units),
                "profit_per_m3_per_day": float(c.profit_per_m3_per_day),
                "max_profit_total": float(max_profit_total),
                "min_profit_isk_total": float(min_profit_total),
                "instant_fill_ratio": float(c.instant_fill_ratio),
                "min_instant_fill_ratio": float(min_instant_fill_ratio),
                "dest_buy_depth_units": int(c.dest_buy_depth_units),
                "min_dest_buy_depth_units": int(min_dest_buy_depth_units)
            }
            if not c.instant:
                kept_metrics["fill_probability"] = float(c.fill_probability)
                kept_metrics["min_fill_probability"] = float(min_fill_probability)
            if mode == "planned_sell":
                kept_metrics["expected_days_to_sell"] = float(c.expected_days_to_sell)
                kept_metrics["max_expected_days_to_sell"] = float(max_expected_days_to_sell)
                kept_metrics["sell_through_ratio_90d"] = float(c.sell_through_ratio_90d)
                kept_metrics["min_sell_through_ratio_90d"] = float(min_sell_through_ratio_90d)
                kept_metrics["gross_profit_if_full_sell"] = float(c.gross_profit_if_full_sell)
                kept_metrics["expected_units_sold_90d"] = float(c.expected_units_sold_90d)
                kept_metrics["expected_units_unsold_90d"] = float(c.expected_units_unsold_90d)
                kept_metrics["expected_realized_profit_90d"] = float(c.expected_realized_profit_90d)
                kept_metrics["min_expected_profit_isk"] = float(min_expected_profit_isk)
                kept_metrics["avg_daily_volume_30d"] = float(c.avg_daily_volume_30d)
                kept_metrics["avg_daily_volume_7d"] = float(c.avg_daily_volume_7d)
                kept_metrics["estimated_sellable_units_90d"] = float(c.estimated_sellable_units_90d)
                kept_metrics["history_order_count_30d"] = int(c.history_order_count_30d)
                kept_metrics["min_avg_daily_volume"] = float(min_avg_daily_volume)
                kept_metrics["used_volume_fallback"] = bool(c.used_volume_fallback)
                kept_metrics["reference_price"] = float(c.reference_price)
                kept_metrics["reference_price_source"] = str(c.reference_price_source)
                kept_metrics["buy_discount_vs_ref"] = float(c.buy_discount_vs_ref)
                kept_metrics["sell_markup_vs_ref"] = float(c.sell_markup_vs_ref)
                kept_metrics["reference_price_penalty"] = float(c.reference_price_penalty)
                kept_metrics["target_price_basis"] = str(c.target_price_basis)
                kept_metrics["target_price_confidence"] = float(c.target_price_confidence)
                kept_metrics["queue_ahead_units"] = int(c.queue_ahead_units)
                kept_metrics["liquidity_confidence"] = float(c.liquidity_confidence)
                kept_metrics["exit_confidence"] = float(c.exit_confidence)
                kept_metrics["overall_confidence"] = float(c.overall_confidence)
                kept_metrics["strict_confidence_score"] = float(c.strict_confidence_score)
                kept_metrics["strict_mode_enabled"] = bool(c.strict_mode_enabled)
                kept_metrics["spread_pct"] = float(c.spread_pct)
                kept_metrics["depth_within_2pct_buy"] = int(c.depth_within_2pct_buy)
                kept_metrics["depth_within_2pct_sell"] = int(c.depth_within_2pct_sell)
                kept_metrics["orderbook_imbalance"] = float(c.orderbook_imbalance)
                kept_metrics["competition_density_near_best"] = int(c.competition_density_near_best)
            record_explain(
                "kept",
                c.type_id,
                c.name,
                "passed_all_filters",
                kept_metrics
            )
        else:
            record_explain(
                "rejected",
                c.type_id,
                c.name,
                "profit_threshold",
                {"max_profit_total": float(max_profit_total), "min_profit_isk_total": float(min_profit_total)}
            )
            if funnel:
                funnel.record_rejection(c.type_id, c.name, "profit_threshold")

    if funnel:
        funnel.record_stage("profit_threshold", len(filtered))
        funnel.record_stage("final", len(filtered))

    print(f"  {len(filtered)} profitable trade candidates found")
    return filtered


def _route_adjusted_candidate_score(c: "TradeCandidate", hop_count: int, scan_cfg: dict) -> float:
    extra = max(0, int(hop_count) - 1)
    cargo_pen = max(0.0, float(scan_cfg.get("cargo_penalty_per_extra_leg", 0.05)))
    cap_pen = max(0.0, float(scan_cfg.get("capital_lock_penalty_per_extra_leg", 0.07)))
    penalty_factor = max(0.0, (1.0 - cargo_pen * extra)) * max(0.0, (1.0 - cap_pen * extra))

    mode = str(getattr(c, "mode", "instant")).lower()
    if mode == "planned_sell":
        density = max(0.0, float(getattr(c, "expected_realized_profit_per_m3_90d", getattr(c, "expected_profit_per_m3_90d", 0.0))))
        absolute = max(0.0, float(getattr(c, "expected_realized_profit_90d", getattr(c, "expected_profit_90d", 0.0))))
    else:
        density = max(0.0, float(getattr(c, "profit_per_m3_per_day", 0.0)))
        absolute = max(0.0, float(getattr(c, "profit_per_unit", 0.0) * getattr(c, "max_units", 0)))

    margin = max(0.0, float(getattr(c, "profit_pct", 0.0)))
    fill_prob = max(0.0, min(1.0, float(getattr(c, "overall_confidence", getattr(c, "fill_probability", 0.0)))))
    instant_ratio = max(0.0, min(1.0, float(getattr(c, "instant_fill_ratio", 1.0))))
    liquidity_conf = max(0.0, min(1.0, float(getattr(c, "liquidity_confidence", fill_prob))))
    exit_conf = max(0.0, min(1.0, float(getattr(c, "exit_confidence", fill_prob))))
    liquidity = max(0.0, min(1.0, 0.35 * fill_prob + 0.25 * instant_ratio + 0.20 * liquidity_conf + 0.20 * exit_conf))
    plaus = max(0.0, min(1.0, 1.0 - float(getattr(c, "reference_price_penalty", 0.0))))

    density_sig = density / (density + 5000.0) if density > 0 else 0.0
    margin_sig = margin / (margin + 0.20) if margin > 0 else 0.0
    abs_sig = absolute / (absolute + 25_000_000.0) if absolute > 0 else 0.0

    w_density = max(0.0, float(scan_cfg.get("score_weight_density", 0.36)))
    w_margin = max(0.0, float(scan_cfg.get("score_weight_margin", 0.27)))
    w_abs = max(0.0, float(scan_cfg.get("score_weight_absolute", 0.17)))
    w_liq = max(0.0, float(scan_cfg.get("score_weight_liquidity", 0.12)))
    w_plaus = max(0.0, float(scan_cfg.get("score_weight_plausibility", 0.08)))
    w_sum = max(1e-9, w_density + w_margin + w_abs + w_liq + w_plaus)
    score01 = (
        (w_density / w_sum) * density_sig
        + (w_margin / w_sum) * margin_sig
        + (w_abs / w_sum) * abs_sig
        + (w_liq / w_sum) * liquidity
        + (w_plaus / w_sum) * plaus
    )
    return max(0.0, score01 * penalty_factor)


def _choose_best_route_wide_candidate(
    current: "TradeCandidate | None",
    challenger: "TradeCandidate",
    close_pct: float
) -> "TradeCandidate":
    if current is None:
        return challenger
    cur_score = float(getattr(current, "route_adjusted_score", 0.0))
    new_score = float(getattr(challenger, "route_adjusted_score", 0.0))
    if new_score > cur_score:
        if cur_score > 0:
            near_limit = cur_score * (1.0 + max(0.0, close_pct))
            if new_score <= near_limit and int(getattr(challenger, "dest_hop_count", 1)) > int(getattr(current, "dest_hop_count", 1)):
                return current
        return challenger
    if cur_score > 0:
        near_limit = new_score * (1.0 + max(0.0, close_pct))
        if cur_score <= near_limit and int(getattr(challenger, "dest_hop_count", 1)) < int(getattr(current, "dest_hop_count", 1)):
            return challenger
    return current


def compute_route_wide_candidates_for_source(
    esi,
    source_node: dict,
    source_index: int,
    destination_nodes: list[dict],
    chain_nodes_ordered: list[dict],
    structure_orders_by_id: dict[int, list[dict]],
    fees: dict,
    filters: dict,
    scan_cfg: dict,
    cfg: dict | None = None
) -> tuple[list["TradeCandidate"], dict]:
    source_orders = structure_orders_by_id.get(int(source_node["id"]), [])
    if not source_orders or not destination_nodes:
        return [], {"reason_counts": {}}

    close_pct = float(scan_cfg.get("prefer_nearer_exit_if_profit_close_pct", 0.10))
    merged_reason_counts: dict[str, int] = {}
    best_by_type: dict[int, "TradeCandidate"] = {}

    for dst_node in destination_nodes:
        dst_orders = structure_orders_by_id.get(int(dst_node["id"]), [])
        if not dst_orders:
            continue
        explain_local: dict = {}
        route_ctx = build_route_context(
            cfg if isinstance(cfg, dict) else {},
            f"{normalize_location_label(source_node.get('label', ''))}->{normalize_location_label(dst_node.get('label', ''))}",
            str(source_node.get("label", "")),
            str(dst_node.get("label", "")),
            source_id=int(source_node.get("id", 0) or 0),
            dest_id=int(dst_node.get("id", 0) or 0),
        )
        src_norm = normalize_location_label(str(source_node.get("label", "")))
        dst_norm = normalize_location_label(str(dst_node.get("label", "")))
        if src_norm == "jita":
            route_ctx["jita_split_prices"] = build_jita_split_price_map(source_orders)
        elif dst_norm == "jita":
            route_ctx["jita_split_prices"] = build_jita_split_price_map(dst_orders)
        cands = compute_candidates(
            esi=esi,
            source_orders=source_orders,
            dest_orders=dst_orders,
            fees=fees,
            filters=filters,
            dest_structure_id=int(dst_node["id"]),
            route_context=route_ctx,
            funnel=None,
            explain=explain_local
        )
        for reason, count in dict(explain_local.get("reason_counts", {})).items():
            merged_reason_counts[reason] = int(merged_reason_counts.get(reason, 0)) + int(count)

        dst_index = int(dst_node.get("route_index", source_index + 1))
        hop_count = max(1, dst_index - int(source_index))
        for c in cands:
            c.route_src_label = str(source_node["label"])
            c.route_dst_label = str(dst_node["label"])
            c.route_src_index = int(source_index)
            c.route_dst_index = int(dst_index)
            c.dest_hop_count = int(hop_count)
            c.carried_through_legs = int(hop_count)
            c.route_wide_selected = True
            c.route_adjusted_score = _route_adjusted_candidate_score(c, hop_count, scan_cfg)
            base_density = float(c.expected_profit_per_m3_90d if str(c.mode).lower() == "planned_sell" else c.profit_per_m3_per_day)
            c.extra_leg_penalty = max(0.0, 1.0 - (c.route_adjusted_score / max(1e-12, base_density)))
            tid = int(c.type_id)
            best_by_type[tid] = _choose_best_route_wide_candidate(best_by_type.get(tid), c, close_pct)

    best = list(best_by_type.values())
    ranking_metric = str(filters.get("ranking_metric", "profit_per_m3_per_day")).lower()
    if ranking_metric == "expected_profit_per_m3_90d":
        best.sort(
            key=lambda c: (
                float(getattr(c, "route_adjusted_score", 0.0)),
                float(getattr(c, "expected_realized_profit_per_m3_90d", getattr(c, "expected_profit_per_m3_90d", 0.0))),
                float(getattr(c, "expected_realized_profit_90d", getattr(c, "expected_profit_90d", 0.0))),
            ),
            reverse=True,
        )
    elif ranking_metric == "profit":
        best.sort(key=lambda c: (float(getattr(c, "route_adjusted_score", 0.0)), float(c.profit_per_unit * c.max_units)), reverse=True)
    elif ranking_metric == "profit_per_m3":
        best.sort(key=lambda c: (float(getattr(c, "route_adjusted_score", 0.0)), float(c.profit_per_m3)), reverse=True)
    else:
        best.sort(key=lambda c: (float(getattr(c, "route_adjusted_score", 0.0)), float(c.profit_per_m3_per_day)), reverse=True)
    return best, {"reason_counts": merged_reason_counts}

__all__ = [
    'build_levels',
    'get_structure_micro_liquidity',
    'depth_slice',
    'apply_strategy_filters',
    'compute_candidates',
    'compute_route_wide_candidates_for_source',
    'TradeCandidate',
]
