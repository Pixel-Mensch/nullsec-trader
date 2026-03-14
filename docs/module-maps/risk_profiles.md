# Module Map: risk_profiles.py

## Purpose

Profile-definition module for built-in risk modes and profile-aware adjustments
to filters, portfolio rules, route scoring, and output summaries. This area is
currently an active worktree hotspot.

## Responsibilities

- owns built-in risk profile definitions
- resolves the active profile from env, CLI, and config
- tightens filter and portfolio settings
- can derive a spendable budget window for reserve-protecting profiles
- carries profile metadata needed for final pick-level enforcement
- applies profile-adjusted route scoring
- formats profile summary text for output

## Inputs

- config dicts and env/CLI overrides
- candidate filter dicts
- portfolio config dicts
- route result dicts and output pick lists

## Outputs

- resolved active profile name and params
- tightened filter and portfolio configs
- spendable-budget / reserved-budget pair for profiles that protect liquidity
- post-build pick rejections with explicit profile rejection codes
- profile-adjusted route score fields
- profile header and summary lines

## Key Files

- `risk_profiles.py`
- `runtime_runner.py`
- `execution_plan.py`
- `tests/test_risk_profiles.py`

## Important Entry Points

- `resolve_active_profile()`
- `apply_profile_to_filters()`
- `apply_profile_to_portfolio_cfg()`
- `resolve_profile_budget_window()`
- `apply_profile_to_route_result()`
- `filter_picks_by_profile()`

## Depends On

- `route_search.py` inside route-score application

## Used By

- `runtime_runner.py`
- `candidate_engine.py`
- `execution_plan.py`
- risk-profile tests

## Common Change Types

- add or tune built-in profiles
- change env/CLI/config precedence
- change reserve-budget policy for low-downside profiles
- adjust route penalty weights
- tighten or relax profile gates, including final liquidity / market-quality /
  capital-efficiency rules
- change whether visible profile rules are hard-gated on final picks

## Risk Areas

- profile behavior can drift across filters, portfolio rules, ranking, and output
- easy to conflict with strict-mode behavior
- profile behavior is user-facing and highly test-visible
- wider runtime verification is still needed for this active area

## Tests

- `tests/test_risk_profiles.py`
- `tests/test_execution_plan.py`
- broader runtime behavior is still only partially verified

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `risk_profiles.py`
3. relevant tests
4. dependent modules only if required

Read `docs/module-maps/route_search.md` first for ranking changes. Read
`docs/module-maps/execution_plan.md` first for output header changes.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
