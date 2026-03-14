# Module Map: route_search.py

## Purpose

Route-ranking module that scores route results and expands allowed route
profiles from config and node data. This map is based on targeted inspection.

## Responsibilities

- owns route ranking summaries
- caps route confidence by aggregate pick market quality
- owns numeric route ranking values
- owns allowed route-pair expansion and dedupe
- normalizes route-search config

## Inputs

- route result dicts
- node catalog entries
- route-search config
- transport-confidence labels, pick market-quality fields, and shipping policy
  data

## Outputs

- route summary dicts
- ranking values
- route profile lists for runtime execution

## Key Files

- `route_search.py`
- `shipping.py`
- `location_utils.py`
- `tests/test_route_search.py`

## Important Entry Points

- `summarize_route_for_ranking()`
- `route_ranking_value()`
- `build_route_search_profiles()`
- `_resolve_route_search_cfg()`

## Depends On

- `shipping.py`
- `location_utils.py`
- `explainability.py`
- `confidence_calibration.py`

## Used By

- `runtime_runner.py`
- `execution_plan.py`
- `runtime_reports.py`
- `risk_profiles.py`

## Common Change Types

- adjust route scoring weights or penalties
- change how route confidence reacts to weak pick mixes
- change allowed-pair policy handling
- alter node dedupe or alias behavior
- add ranking explanation fields

## Risk Areas

- ranking semantics affect both runtime choice and displayed results
- route-confidence changes propagate into leaderboard, no-trade, and execution
  plan artifacts
- allowed-pair logic can silently include or exclude routes
- transport confidence and route penalties are easy to double-count

## Tests

- `tests/test_route_search.py`
- `tests/test_shipping.py`
- route summary behavior is also exercised by output and profile tests

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `route_search.py`
3. relevant tests
4. dependent modules only if required

Read `docs/module-maps/confidence_calibration.md` first if transport confidence
handling changes. Read `docs/module-maps/risk_profiles.md` first if
profile-adjusted ranking changes.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
