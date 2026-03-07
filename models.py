from __future__ import annotations

from dataclasses import dataclass, field


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
    exit_type: str = ""
    target_sell_price: float = 0.0
    target_price_basis: str = ""
    target_price_confidence: float = 0.0
    has_reliable_price_basis: bool = False
    estimated_transport_cost: float = 0.0
    avg_daily_volume_30d: float = 0.0
    avg_daily_volume_7d: float = 0.0
    estimated_sellable_units_90d: float = 0.0
    expected_days_to_sell: float = 0.0
    sell_through_ratio_90d: float = 0.0
    risk_score: float = 0.0
    gross_profit_if_full_sell: float = 0.0
    expected_units_sold_90d: float = 0.0
    expected_units_unsold_90d: float = 0.0
    expected_realized_profit_90d: float = 0.0
    expected_realized_profit_per_m3_90d: float = 0.0
    transport_confidence: float = 1.0
    exit_confidence: float = 0.0
    liquidity_confidence: float = 0.0
    overall_confidence: float = 0.0
    raw_exit_confidence: float = 0.0
    raw_liquidity_confidence: float = 0.0
    raw_transport_confidence: float = 1.0
    raw_overall_confidence: float = 0.0
    calibrated_exit_confidence: float = 0.0
    calibrated_liquidity_confidence: float = 0.0
    calibrated_transport_confidence: float = 1.0
    calibrated_overall_confidence: float = 0.0
    raw_confidence: float = 0.0
    calibrated_confidence: float = 0.0
    decision_overall_confidence: float = 0.0
    calibration_warning: str = ""
    market_plausibility: dict = field(default_factory=dict)
    market_plausibility_score: float = 1.0
    manipulation_risk_score: float = 0.0
    profit_at_top_of_book: float = 0.0
    profit_at_usable_depth: float = 0.0
    profit_at_conservative_executable_price: float = 0.0
    positive_reasons: list[dict] = field(default_factory=list)
    negative_reasons: list[dict] = field(default_factory=list)
    gating_failures: list[dict] = field(default_factory=list)
    score_contributors: list[dict] = field(default_factory=list)
    confidence_contributors: list[dict] = field(default_factory=list)
    pruned_reason: dict | None = None
    warnings: list[dict] = field(default_factory=list)
    explainability_score: float | None = None
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

    def __post_init__(self) -> None:
        if not self.exit_type:
            mode = str(self.mode or "").strip().lower()
            if bool(self.instant) or mode == "instant":
                self.exit_type = "instant"
            elif mode == "planned_sell":
                self.exit_type = "planned"
            else:
                self.exit_type = "speculative"
        if self.gross_profit_if_full_sell <= 0.0 and self.max_units > 0 and self.profit_per_unit > 0.0:
            self.gross_profit_if_full_sell = float(self.profit_per_unit) * float(self.max_units)
        if self.expected_realized_profit_90d <= 0.0 and self.expected_profit_90d > 0.0:
            self.expected_realized_profit_90d = float(self.expected_profit_90d)
        if self.expected_profit_90d <= 0.0 and self.expected_realized_profit_90d > 0.0:
            self.expected_profit_90d = float(self.expected_realized_profit_90d)
        if self.expected_realized_profit_per_m3_90d <= 0.0 and self.expected_profit_per_m3_90d > 0.0:
            self.expected_realized_profit_per_m3_90d = float(self.expected_profit_per_m3_90d)
        if self.expected_profit_per_m3_90d <= 0.0 and self.expected_realized_profit_per_m3_90d > 0.0:
            self.expected_profit_per_m3_90d = float(self.expected_realized_profit_per_m3_90d)
        if self.expected_units_sold_90d <= 0.0 and self.max_units > 0:
            self.expected_units_sold_90d = float(self.max_units if self.instant else 0.0)
        if self.expected_units_unsold_90d <= 0.0 and self.max_units > 0:
            self.expected_units_unsold_90d = max(0.0, float(self.max_units) - float(self.expected_units_sold_90d))
        if self.estimated_sellable_units_90d <= 0.0:
            self.estimated_sellable_units_90d = float(self.expected_units_sold_90d)
        if self.target_price_confidence <= 0.0 and self.has_reliable_price_basis:
            self.target_price_confidence = 1.0
        if self.liquidity_confidence <= 0.0:
            self.liquidity_confidence = max(0.0, min(1.0, float(self.fill_probability)))
        if self.exit_confidence <= 0.0:
            self.exit_confidence = max(
                0.0,
                min(
                    1.0,
                    float(self.strict_confidence_score)
                    if self.strict_confidence_score > 0.0
                    else float(self.liquidity_confidence),
                ),
            )
        if self.overall_confidence <= 0.0:
            self.overall_confidence = max(
                0.0,
                min(
                    1.0,
                    float(self.strict_confidence_score)
                    if self.strict_confidence_score > 0.0
                    else min(float(self.exit_confidence), float(self.liquidity_confidence)),
                ),
            )
        if self.transport_confidence <= 0.0:
            self.transport_confidence = 1.0
        if self.raw_exit_confidence <= 0.0:
            self.raw_exit_confidence = float(self.exit_confidence)
        if self.raw_liquidity_confidence <= 0.0:
            self.raw_liquidity_confidence = float(self.liquidity_confidence)
        if self.raw_transport_confidence <= 0.0:
            self.raw_transport_confidence = float(self.transport_confidence)
        if self.raw_overall_confidence <= 0.0:
            self.raw_overall_confidence = min(
                float(self.overall_confidence),
                float(self.raw_exit_confidence),
                float(self.raw_liquidity_confidence),
                float(self.raw_transport_confidence),
            )
        if self.calibrated_exit_confidence <= 0.0:
            self.calibrated_exit_confidence = float(self.raw_exit_confidence)
        if self.calibrated_liquidity_confidence <= 0.0:
            self.calibrated_liquidity_confidence = float(self.raw_liquidity_confidence)
        if self.calibrated_transport_confidence <= 0.0:
            self.calibrated_transport_confidence = float(self.raw_transport_confidence)
        if self.calibrated_overall_confidence <= 0.0:
            self.calibrated_overall_confidence = float(self.raw_overall_confidence)
        if self.raw_confidence <= 0.0:
            self.raw_confidence = float(self.raw_overall_confidence)
        if self.calibrated_confidence <= 0.0:
            self.calibrated_confidence = float(self.calibrated_overall_confidence)
        if self.decision_overall_confidence <= 0.0:
            self.decision_overall_confidence = float(self.calibrated_overall_confidence or self.raw_overall_confidence)
        if self.market_plausibility_score <= 0.0 and self.manipulation_risk_score <= 0.0:
            self.market_plausibility_score = 1.0
        if self.manipulation_risk_score <= 0.0 and self.market_plausibility_score < 1.0:
            self.manipulation_risk_score = max(0.0, min(1.0, 1.0 - float(self.market_plausibility_score)))


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
