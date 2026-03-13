# Session Handoff

Date: 2026-03-13 (session 22 market-quality tightening)
Branch: `dev`

## Completed This Session

Tightened the actual trade-quality decision logic so fragile paper-profit picks
are less likely to survive as actionable, mandatory, or route-confidence-heavy
results.

## Root Cause

- `candidate_engine.py` only hard-rejected extreme market-plausibility cases;
  borderline thin-book / price-sensitive setups mostly kept high enough
  confidence to survive
- the `instant` candidate path reapplied fill-proxy confidence late and could
  partially wash out the earlier market-plausibility haircut
- `build_pick_score_breakdown()` and downstream portfolio selection focused on
  expected profit, days, and plausibility, but reacted too weakly to repricing
  fragility and manipulation-heavy orderbooks
- `local_search_optimize()` and `try_cargo_fill()` could reintroduce weaker
  candidates after initial ranking
- `execution_plan._categorize_pick()` still allowed some price-sensitive instant
  picks to appear as `MANDATORY`
- `route_search.summarize_route_for_ranking()` could keep route confidence too
  friendly because it did not cap against aggregate pick market quality

## What Changed

- `market_plausibility.py`
  - added `profit_retention_ratio_from_values()`
  - added `market_quality_score_from_metrics()`
  - added `market_quality_gate_from_metrics()`
  - `assess_market_plausibility()` now returns
    `profit_retention_ratio`, `market_quality_score`,
    `quality_gate_reject`, and `quality_gate_reason`
- `candidate_engine.py`
  - candidate confidence now uses market quality, not raw plausibility only
  - `instant` confidence no longer loses that quality haircut late in the flow
  - combined fragile-book quality gate can now reject anti-bait cases before
    they reach the portfolio
  - route-wide candidate score now uses market quality
- `portfolio_builder.py`
  - added the same market-quality gate as a safety net for main selection,
    local search, and cargo fill
  - local search now compares a quality-aware selection objective instead of
    only raw realized-profit objective
  - pick dictionaries now preserve `market_quality_score` and
    `profit_retention_ratio`
- `explainability.py`
  - pick score breakdown now uses market quality directly and surfaces
    retention/manipulation context in score contributors
  - candidate warnings now explain weak market quality and weak profit
    retention more explicitly
- `execution_plan.py`
  - `MANDATORY` now requires a clean instant exit, decent market quality, and
    no price-sensitive repricing dependency
  - fragile market-quality warnings are now visible in pick output
  - detail mode now prints `market_quality_score` and
    `profit_retention_ratio`
- `route_search.py`
  - route summary now exposes `market_quality_factor`
  - displayed `route_confidence` is capped by average pick market quality
- `models.py`
  - `TradeCandidate` now carries `market_quality_score` and
    `profit_retention_ratio`

## Tests And Verification

- Core quality regression:
  - `pytest -q tests/test_core.py tests/test_portfolio.py tests/test_execution_plan.py tests/test_route_search.py`
    -> **118 passed**
- Adjacent explainability / artifact regression:
  - `pytest -q tests/test_explainability.py tests/test_no_trade.py tests/test_runtime_reports.py`
    -> **45 passed**

## Remaining Limits

- this session tightened the existing heuristics; it did not introduce any new
  orderbook data source beyond current top-of-book/depth/reference inputs
- thresholds are still heuristic and should be re-evaluated against more live
  replay snapshots before further tightening
- an unrelated pre-existing local modification in `location_utils.py` remains
  intentionally untouched

## Files Touched

- `market_plausibility.py`
- `candidate_engine.py`
- `portfolio_builder.py`
- `explainability.py`
- `execution_plan.py`
- `route_search.py`
- `models.py`
- `tests/test_core.py`
- `tests/test_portfolio.py`
- `tests/test_execution_plan.py`
- `tests/test_route_search.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
- `docs/module-maps/candidate_engine.md`
- `docs/module-maps/route_search.md`
