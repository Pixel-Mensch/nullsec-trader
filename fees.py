from fee_engine import FeeEngine


def compute_trade_financials(
    buy_price: float,
    sell_price: float,
    qty: int,
    fees: dict,
    instant: bool,
    execution_mode: str | None = None,
    relist_budget_pct: float = 0.0,
    relist_budget_isk: float = 0.0
) -> tuple[float, float, float, float]:
    """Return (cost_net, revenue_net, profit, profit_pct)."""
    mode = str(execution_mode or ("instant" if instant else "planned_sell")).lower()
    if mode == "instant":
        execution = "instant_instant"
    elif mode in ("planned_sell", "fast_sell"):
        execution = "instant_listed"
    else:
        execution = "instant_instant" if instant else "instant_listed"

    breakdown = FeeEngine(fees).compute(
        buy_price=buy_price,
        sell_price=sell_price,
        qty=qty,
        execution=execution,
        relist_budget_pct=(relist_budget_pct if execution == "instant_listed" else 0.0),
        relist_budget_isk=(relist_budget_isk if execution == "instant_listed" else 0.0),
    )
    return breakdown.cost_net, breakdown.revenue_net, breakdown.profit, breakdown.profit_pct


__all__ = ["FeeEngine", "compute_trade_financials"]
