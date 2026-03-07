from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OrderLevel:
    price: float
    volume: int


@dataclass
class TradeCandidate:
    type_id: int
    name: str
    unit_volume: float
    buy_avg: float
    sell_avg: float
    max_units: int
    profit_per_unit: float
    profit_pct: float
    instant: bool = True
    suggested_sell_price: float | None = None
    actual_fillable_qty_buy: int = 0
    actual_fillable_qty_sell: int = 0
    blended_buy_price: float = 0.0
    blended_sell_price: float = 0.0
    fill_ratio_buy: float = 1.0
    fill_ratio_sell: float = 1.0
    fill_warning: str = ""
    liquidity_score: int = 0
    history_volume_30d: int = 0
    history_order_count_30d: int = 0
    daily_volume: float = 0.0
    dest_buy_depth_units: int = 0
    instant_fill_ratio: float = 1.0
    competition_price_levels_near_best: int = 0
    queue_ahead_units: int = 0
    spread_pct: float = 0.0
    depth_within_2pct_buy: int = 0
    depth_within_2pct_sell: int = 0
    orderbook_imbalance: float = 0.0
    competition_density_near_best: int = 0
    fill_probability: float = 0.0
    turnover_factor: float = 0.0
    profit_per_m3: float = 0.0
    profit_per_m3_per_day: float = 0.0
    mode: str = "instant"
    target_sell_price: float = 0.0
    avg_daily_volume_30d: float = 0.0
    avg_daily_volume_7d: float = 0.0
    expected_days_to_sell: float = 0.0
    sell_through_ratio_90d: float = 0.0
    risk_score: float = 0.0
    expected_profit_90d: float = 0.0
    expected_profit_per_m3_90d: float = 0.0
    used_volume_fallback: bool = False
    reference_price: float = 0.0
    reference_price_average: float = 0.0
    reference_price_adjusted: float = 0.0
    reference_price_source: str = ""
    buy_discount_vs_ref: float = 0.0
    sell_markup_vs_ref: float = 0.0
    reference_price_penalty: float = 0.0
    strict_confidence_score: float = 0.0
    strict_mode_enabled: bool = False
    dest_hop_count: int = 1
    route_src_label: str = ""
    route_dst_label: str = ""
    route_src_index: int = 0
    route_dst_index: int = 0
    extra_leg_penalty: float = 0.0
    route_wide_selected: bool = False
    carried_through_legs: int = 1
    route_adjusted_score: float = 0.0
    jita_split_price: float = 0.0


class FilterFunnel:
    def __init__(self):
        self.stage_stats = {
            "initial": 0,
            "excluded_type_id": 0,
            "excluded_name_keyword": 0,
            "exclude_type_ids": 0,
            "exclude_keywords": 0,
            "market_history": 0,
            "liquidity_score": 0,
            "profit_threshold": 0,
            "final": 0
        }
        self.rejections = []

    def record_stage(self, stage_name: str, count: int):
        if stage_name in self.stage_stats:
            self.stage_stats[stage_name] = count

    def record_rejection(self, type_id: int, type_name: str, reason: str):
        self.rejections.append((type_id, type_name, reason))

    def top_rejections(self, n: int = 10) -> list[tuple]:
        reason_freq = {}
        for _, name, reason in self.rejections:
            key = (name, reason)
            reason_freq[key] = reason_freq.get(key, 0) + 1
        sorted_reasons = sorted(reason_freq.items(), key=lambda x: x[1], reverse=True)
        return [(k[0], k[1], v) for k, v in sorted_reasons[:n]]

    def get_bottleneck(self) -> tuple[str, int]:
        stages = list(self.stage_stats.items())
        max_dropout = 0
        bottleneck_stage = "initial"
        for i in range(len(stages) - 1):
            _, count = stages[i]
            next_name, next_count = stages[i + 1]
            dropout = count - next_count
            if dropout > max_dropout:
                max_dropout = dropout
                bottleneck_stage = next_name
        return bottleneck_stage, max_dropout

    def get_summary_lines(self) -> list[str]:
        lines = []
        lines.append("Filter Funnel Analysis:")
        for stage, count in self.stage_stats.items():
            lines.append(f"  {stage}: {count}")
        bottleneck, dropout = self.get_bottleneck()
        lines.append(f"Bottleneck: {bottleneck} (lost {dropout} candidates)")
        lines.append("")
        lines.append("Top Rejection Reasons (top 5):")
        for name, reason, freq in self.top_rejections(5):
            lines.append(f"  {name}: {reason} ({freq}x)")
        return lines


__all__ = [
    "FilterFunnel",
    "OrderLevel",
    "TradeCandidate",
]
