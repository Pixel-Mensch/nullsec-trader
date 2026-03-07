from candidate_engine import (
    _choose_best_route_wide_candidate,
    _route_adjusted_candidate_score,
    apply_strategy_filters,
)
from execution_plan import _profit_dominance, _route_ranking_value


def apply_strategy_mode(cfg: dict, filters: dict, picks: list[dict]) -> dict:
    strategy_cfg = cfg.get("strategy", {})
    mode = strategy_cfg.get("mode", "balanced")
    modes = strategy_cfg.get("strategy_modes", {})
    mode_params = modes.get(mode, {})

    concentration_limit = float(mode_params.get("concentration_limit", 0.5))
    if picks:
        total_cost = sum(p["cost"] for p in picks)
        for p in picks:
            if total_cost > 0 and p["cost"] / total_cost > concentration_limit:
                p["concentration_warning"] = (
                    f"Item uses {p['cost']/total_cost*100:.1f}% of budget "
                    f"(limit: {concentration_limit*100:.0f}%)"
                )

    diversity_min = int(mode_params.get("diversity_min_items", 5))
    if len(picks) < diversity_min:
        return {"warning": f"Portfolio has {len(picks)} items (strategy recommends min {diversity_min})"}

    return {}


def compute_volatility_score(history_stats: dict) -> float:
    if not history_stats:
        return 0.5
    vol = float(history_stats.get("volume", 0))
    days = float(history_stats.get("days_with_trades", 1))
    if vol > 0 and days > 0:
        avg_daily = vol / max(1, days)
        return max(0.0, 1.0 - min(1.0, avg_daily / 100.0))
    return 0.5


__all__ = [
    "_choose_best_route_wide_candidate",
    "_profit_dominance",
    "_route_adjusted_candidate_score",
    "_route_ranking_value",
    "apply_strategy_filters",
    "apply_strategy_mode",
    "compute_volatility_score",
]
