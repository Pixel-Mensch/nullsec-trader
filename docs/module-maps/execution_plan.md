# Module Map: execution_plan.py

## Purpose

Presentation module for human-readable execution plans and route leaderboards.
This map is based on focused output and test inspection, not a full audit.

## Responsibilities

- owns execution-plan text rendering
- owns route leaderboard text rendering
- categorizes picks and generates warnings
- handles compact/detail output differences
- renders compact character/history metadata in the plan header
- renders applied personal-layer scope/effect lines when a route actually used them
- distinguishes per-route actionable summaries from aggregate-alternative totals
- surfaces internal-route operational floor notes and suppressed low-profit routes
- surfaces route-mix cleanup notes when weak add-on picks were removed after
  final route selection
- exposes profit-basis context for price-sensitive / materially repriced picks
  so visible quote vs displayed profit stays explainable
- can render corridor-ordered route sections when runtime metadata provides a
  display-only direct-leg vs longer-span / Jita-connector grouping without
  changing ranking, and without dropping longer profitable spans from view
- can render compact internal travel metadata when runtime metadata provides
  gate/ansiblex leg counts, ansiblex logistics cost, profit before/after
  logistics, and visible ansiblex travel legs

## Inputs

- route result dicts
- timestamps and output paths
- ranking metric and mode flags
- route summaries from `route_search.py`

## Outputs

- `execution_plan_*.txt`
- `route_leaderboard_*.txt`
- formatted warning, fee, and summary sections

## Key Files

- `execution_plan.py`
- `route_search.py`
- `explainability.py`
- `tests/test_execution_plan.py`

## Important Entry Points

- `write_execution_plan_profiles()`
- `write_route_leaderboard()`
- `_categorize_pick()`
- `_pick_action_warnings()`
- `_route_level_warnings()`

## Depends On

- `route_search.py`
- `explainability.py`
- `confidence_calibration.py`
- `risk_profiles.py`

## Used By

- `runtime_runner.py`
- `scoring.py`
- output-focused test modules

## Common Change Types

- change output layout or wording
- add or adjust warnings
- change compact/detail behavior
- surface new route or profile metadata
- surface personal-layer state and explainability without inventing business logic
- keep "best actionable route" vs "aggregate alternatives" semantics honest
- keep internal-route floor messaging scoped to real internal routes only
- keep price-basis transparency honest for PRICE-SENS picks
- keep corridor presentation aligned with route-chain logic without changing
  the ranking path
- keep ansiblex travel visibility concise and presentation-only, without
  turning the plan writer into a second routing engine

## Risk Areas

- formatting is highly test-visible
- this module assumes many pick and route fields exist
- presentation changes can accidentally embed business logic
- leaderboard ranking and plan messaging must stay aligned
- personal-history messaging must stay honest about fallback vs active state
- applied scoped effects must stay visible without implying global market truth

## Tests

- `tests/test_execution_plan.py`
- `tests/test_shipping.py`
- `tests/test_journal.py`
- `tests/test_explainability.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `execution_plan.py`
3. relevant tests
4. dependent modules only if required

Read `docs/module-maps/route_search.md` first if ranking or summary fields
change. Read `docs/module-maps/risk_profiles.md` first if profile headers or
restriction summaries change.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
