# Module Map: runtime_runner.py

## Purpose

Main CLI orchestration module for live/replay execution, route modes, chain
execution, and output artifact creation. This map is based on a targeted audit,
not a full line-by-line review.

## Responsibilities

- owns `run_cli()` and the top-level runtime path
- coordinates route, route-wide, chain, and snapshot-only execution
- wires profiles, calibration, reporting, and plan artifacts together
- attaches advisory-only character/personal-history metadata to runtime results

## Inputs

- CLI args from `runtime_common.py`
- config data from `config_loader.py`
- live/replay market data from `runtime_clients.py`
- candidate, ranking, shipping, and journal data from domain modules

## Outputs

- route result dicts
- execution plans, leaderboards, summaries, CSVs, and plan artifacts
- CLI console output during runs

## Key Files

- `runtime_runner.py`
- `main.py`
- `run_trader.ps1`
- `run.bat`

## Important Entry Points

- `run_cli()`
- `run_route()`
- `run_route_wide_leg()`
- `run_snapshot_only()`
- `_build_personal_calibration_runtime()`
- `_write_trade_plan_artifact()`

## Depends On

- `runtime_common.py`
- `config_loader.py`
- `runtime_clients.py`
- `candidate_engine.py`
- `portfolio_builder.py`
- `shipping.py`
- `route_search.py`
- `execution_plan.py`
- `runtime_reports.py`
- `risk_profiles.py`
- `confidence_calibration.py`

## Used By

- `main.py`
- CLI wrapper scripts through `main.py`
- integration-style runtime tests

## Common Change Types

- add or adjust CLI/runtime modes
- wire new profile, calibration, or ranking behavior into the main flow
- surface advisory runtime metadata without turning it into a decision hook
- change artifact generation or route/chain branching

## Risk Areas

- many branches share one file
- easy to duplicate business logic that belongs in domain modules
- route summaries, output files, and metadata can drift together
- profile and calibration changes can affect multiple runtime paths at once
- personal-history output must stay separate from generic runtime calibration

## Tests

- `tests/test_integration.py`
- `tests/test_architecture.py`
- some behavior is also covered indirectly by `tests/test_risk_profiles.py`
  and `tests/test_execution_plan.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `runtime_runner.py`
3. relevant tests
4. dependent modules only if required

Read `docs/module-maps/runtime_common.md`, `docs/module-maps/route_search.md`,
and `docs/module-maps/execution_plan.md` first if the change touches startup,
ranking, or output behavior.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
