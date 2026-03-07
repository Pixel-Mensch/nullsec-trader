from dataclasses import dataclass


DEFAULT_SKILL_LEVEL = 3


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    txt = str(value).strip().lower()
    if txt in ("1", "true", "yes", "on"):
        return True
    if txt in ("0", "false", "no", "off", ""):
        return False
    return default


def _to_skill_level(value, default: int = DEFAULT_SKILL_LEVEL) -> int:
    try:
        lvl = int(value)
    except Exception:
        lvl = int(default)
    return max(0, min(5, lvl))


@dataclass
class FeeBreakdown:
    cost_net: float
    revenue_net: float
    profit: float
    profit_pct: float
    buy_broker_fee_total: float
    sell_broker_fee_total: float
    sales_tax_total: float
    relist_budget_total: float
    scc_surcharge_total: float
    sales_tax_isk: float
    broker_fee_isk: float
    scc_surcharge_isk: float
    relist_fee_isk: float
    effective_sales_tax_rate: float
    effective_broker_fee_rate: float
    effective_scc_surcharge_rate: float
    accounting_level: int
    broker_relations_level: int
    advanced_broker_relations_level: int


class FeeEngine:
    """
    Computes net trade PnL for different execution styles.

    Execution mapping used by the tool:
    - instant_instant: buy now, instant sell to existing buy orders
    - instant_listed: buy now, place sell order
    - listed_listed / listed_instant: kept for compatibility
    """

    def __init__(self, fees_cfg: dict | None = None):
        self.cfg = dict(fees_cfg or {})
        skills_cfg = self.cfg.get("skills", {})
        self.skills_cfg = skills_cfg if isinstance(skills_cfg, dict) else {}

        self.buy_broker_rate = max(0.0, _to_float(self.cfg.get("buy_broker_fee", 0.0), 0.0))

        # Explicit default is skill level 3 (no silent accounting-5 assumptions).
        self.accounting_level = self._resolve_skill_level("accounting")
        self.broker_relations_level = self._resolve_skill_level("broker_relations")
        self.advanced_broker_relations_level = self._resolve_skill_level("advanced_broker_relations")

        # Anchor rates are interpreted as "at level 3", then adjusted by skill deltas.
        self.sales_tax_anchor_rate = max(
            0.0,
            _to_float(
                self.cfg.get("sales_tax_at_skill3", self.cfg.get("sales_tax", 0.075)),
                0.075,
            ),
        )
        self.sales_tax_delta_per_level = max(
            0.0,
            _to_float(
                self.cfg.get("sales_tax_delta_per_level", self.cfg.get("accounting_sales_tax_delta_per_level", 0.005)),
                0.005,
            ),
        )
        self.sales_tax_floor_rate = max(0.0, _to_float(self.cfg.get("sales_tax_floor_rate", 0.0), 0.0))

        self.sell_broker_anchor_rate = max(
            0.0,
            _to_float(
                self.cfg.get("sell_broker_fee_at_skill3", self.cfg.get("sell_broker_fee", 0.03)),
                0.03,
            ),
        )
        self.broker_relations_delta_per_level = max(
            0.0,
            _to_float(self.cfg.get("broker_relations_delta_per_level", 0.001), 0.001),
        )
        self.market_type = str(self.cfg.get("sell_market_type", self.cfg.get("market_type", "upwell")) or "upwell").strip().lower()
        self.apply_broker_relations_on_upwell = _to_bool(self.cfg.get("apply_broker_relations_on_upwell", False), False)

        self.scc_surcharge_rate = max(
            0.0,
            _to_float(self.cfg.get("scc_surcharge_rate", self.cfg.get("scc_surcharge", 0.005)), 0.005),
        )

        self.apply_advanced_broker_relations_to_relist = _to_bool(
            self.cfg.get("apply_advanced_broker_relations_to_relist", True),
            True,
        )
        self.relist_discount_per_level = max(
            0.0,
            _to_float(
                self.cfg.get(
                    "advanced_broker_relations_relist_discount_per_level",
                    self.cfg.get("advanced_broker_relist_discount_per_level", 0.05),
                ),
                0.05,
            ),
        )
        self.relist_fee_floor_multiplier = max(0.0, _to_float(self.cfg.get("relist_fee_floor_multiplier", 0.0), 0.0))

    def _resolve_skill_level(self, skill_name: str) -> int:
        aliases = {
            "accounting": ("accounting", "accounting_level"),
            "broker_relations": ("broker_relations", "broker_relations_level"),
            "advanced_broker_relations": (
                "advanced_broker_relations",
                "advanced_broker_relations_level",
                "advanced_broker",
                "advanced_broker_level",
            ),
        }
        for key in aliases.get(skill_name, (skill_name,)):
            if key in self.skills_cfg:
                return _to_skill_level(self.skills_cfg.get(key), DEFAULT_SKILL_LEVEL)
        for key in aliases.get(skill_name, (skill_name,)):
            if key in self.cfg:
                return _to_skill_level(self.cfg.get(key), DEFAULT_SKILL_LEVEL)
        return DEFAULT_SKILL_LEVEL

    def _effective_sales_tax_rate(self) -> float:
        delta = float(self.accounting_level - DEFAULT_SKILL_LEVEL)
        rate = self.sales_tax_anchor_rate - (delta * self.sales_tax_delta_per_level)
        return max(self.sales_tax_floor_rate, rate)

    def _effective_broker_fee_rate(self) -> float:
        apply_skill = self.market_type == "npc" or (
            self.market_type == "upwell" and self.apply_broker_relations_on_upwell
        )
        if not apply_skill:
            return max(0.0, self.sell_broker_anchor_rate)
        delta = float(self.broker_relations_level - DEFAULT_SKILL_LEVEL)
        rate = self.sell_broker_anchor_rate - (delta * self.broker_relations_delta_per_level)
        return max(0.0, rate)

    def _effective_relist_multiplier(self) -> float:
        if not self.apply_advanced_broker_relations_to_relist:
            return 1.0
        delta = float(self.advanced_broker_relations_level - DEFAULT_SKILL_LEVEL)
        factor = 1.0 - (delta * self.relist_discount_per_level)
        return max(self.relist_fee_floor_multiplier, factor)

    def compute(
        self,
        buy_price: float,
        sell_price: float,
        qty: int,
        execution: str = "instant_instant",
        relist_budget_pct: float = 0.0,
        relist_budget_isk: float = 0.0,
    ) -> FeeBreakdown:
        q = max(0, int(qty))
        gross_buy = max(0.0, float(buy_price)) * float(q)
        gross_sell = max(0.0, float(sell_price)) * float(q)

        mode = str(execution or "instant_instant").lower()
        buy_is_listed = mode in ("listed_listed", "listed_instant")
        sell_is_listed = mode in ("instant_listed", "listed_listed")

        sales_tax_rate = self._effective_sales_tax_rate()
        broker_fee_rate = self._effective_broker_fee_rate()
        scc_rate = self.scc_surcharge_rate

        buy_broker_fee_total = gross_buy * self.buy_broker_rate if buy_is_listed else 0.0
        sales_tax_total = gross_sell * sales_tax_rate
        sell_broker_fee_total = gross_sell * broker_fee_rate if sell_is_listed else 0.0
        scc_surcharge_total = gross_sell * scc_rate if sell_is_listed else 0.0

        relist_budget_total = 0.0
        if sell_is_listed:
            relist_budget_total += max(0.0, float(relist_budget_pct)) * gross_sell
            relist_budget_total += max(0.0, float(relist_budget_isk))
            relist_budget_total *= self._effective_relist_multiplier()

        cost_net = gross_buy + buy_broker_fee_total
        revenue_net = gross_sell - sell_broker_fee_total - scc_surcharge_total - sales_tax_total - relist_budget_total
        profit = revenue_net - cost_net
        profit_pct = (profit / cost_net) if cost_net > 0 else 0.0
        return FeeBreakdown(
            cost_net=cost_net,
            revenue_net=revenue_net,
            profit=profit,
            profit_pct=profit_pct,
            buy_broker_fee_total=buy_broker_fee_total,
            sell_broker_fee_total=sell_broker_fee_total,
            sales_tax_total=sales_tax_total,
            relist_budget_total=relist_budget_total,
            scc_surcharge_total=scc_surcharge_total,
            sales_tax_isk=sales_tax_total,
            broker_fee_isk=sell_broker_fee_total,
            scc_surcharge_isk=scc_surcharge_total,
            relist_fee_isk=relist_budget_total,
            effective_sales_tax_rate=sales_tax_rate,
            effective_broker_fee_rate=broker_fee_rate if sell_is_listed else 0.0,
            effective_scc_surcharge_rate=scc_rate if sell_is_listed else 0.0,
            accounting_level=int(self.accounting_level),
            broker_relations_level=int(self.broker_relations_level),
            advanced_broker_relations_level=int(self.advanced_broker_relations_level),
        )
