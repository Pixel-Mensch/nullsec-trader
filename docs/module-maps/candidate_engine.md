# Module Map: candidate_engine.py

## Purpose

Core candidate generation module for trade selection, planned-sell heuristics,
and route-wide candidate scoring. This map is based on a targeted audit.

## Responsibilities

- owns candidate creation and filtering
- owns planned-sell price and liquidity heuristics
- owns candidate-stage anti-bait market-quality enforcement via
  `market_plausibility.py`
- applies strategy/profile-aware filter tightening at candidate time
- computes route-wide candidate score adjustments

## Inputs

- source and destination order lists
- filter, strict-mode, and reference-price config
- fee config and optional route/shipping context
- optional explainability and funnel collectors

## Outputs

- `TradeCandidate` lists
- explainability and rejection data
- route-wide candidate selections and reason counts

## Key Files

- `candidate_engine.py`
- `models.py`
- `market_plausibility.py`
- `explainability.py`

## Important Entry Points

- `compute_candidates()`
- `compute_route_wide_candidates_for_source()`
- `apply_strategy_filters()`
- `_route_adjusted_candidate_score()`
- market-quality fields carried forward on `TradeCandidate`:
  `market_quality_score`, `profit_retention_ratio`

## Depends On

- `models.py`
- `fees.py`
- `shipping.py`
- `market_plausibility.py`
- `explainability.py`
- `risk_profiles.py`

## Used By

- `runtime_runner.py`
- `portfolio_builder.py`
- `config_loader.py`
- `market_normalization.py`
- `scoring.py`

## Common Change Types

- adjust planned-sell thresholds or price logic
- change profitability or fill heuristics
- add explainability fields or rejection reasons
- alter route-wide candidate ranking

## Risk Areas

- threshold changes can materially change trade output
- planned-sell logic mixes pricing, liquidity, and confidence assumptions
- easy to break explainability or downstream mandatory/optional semantics when
  adding new gates
- shipping and reference-price assumptions affect viability

## Tests

- `tests/test_core.py`
- `tests/test_portfolio.py`
- `tests/test_architecture.py`
- route-wide effects are also exercised indirectly through runtime tests

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `candidate_engine.py`
3. relevant tests
4. dependent modules only if required

Read `docs/module-maps/risk_profiles.md` first if profile gates are involved.
Read `docs/module-maps/route_search.md` first if ranking semantics are involved.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
