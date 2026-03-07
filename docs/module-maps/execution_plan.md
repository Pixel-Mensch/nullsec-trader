# Module Map: execution_plan.py

## Purpose

Presentation module for human-readable execution plans and route leaderboards.
This map is based on focused output and test inspection, not a full audit.

## Responsibilities

- owns execution-plan text rendering
- owns route leaderboard text rendering
- categorizes picks and generates warnings
- handles compact/detail output differences

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

## Risk Areas

- formatting is highly test-visible
- this module assumes many pick and route fields exist
- presentation changes can accidentally embed business logic
- leaderboard ranking and plan messaging must stay aligned

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
