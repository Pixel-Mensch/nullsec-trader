# Module Map: runtime_runner.py

## Purpose

Main CLI orchestration module for live/replay execution, route modes, chain
execution, and output artifact creation. This map is based on a targeted audit,
not a full line-by-line review.

## Responsibilities

- owns `run_cli()` and the top-level runtime path
- coordinates route, route-wide, chain, and snapshot-only execution
- dispatches the safe clean-start maintenance path
- wires profiles, calibration, reporting, and plan artifacts together
- applies the opt-in personal-history layer after generic calibration
- attaches character/personal-history metadata and explainability to runtime results
- owns the shared post-build pick-gating seam after transport and calibration
- owns the post-selection route-mix cleanup seam for weak non-mandatory add-ons
- owns the internal-self-haul operational route floor before artifact emission
- keeps external routes from carrying misleading internal-route floor metadata
- carries presentation-ready internal travel metadata from transport context
  into final route results and `trade_plan` artifacts

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
- `_apply_post_build_profile_filters()`
- `_apply_post_selection_route_mix_cleanup()`
- `_derive_route_prune_reason()`
- `_apply_internal_self_haul_operational_filter()`
- `_build_personal_calibration_runtime()`
- `_apply_confidence_calibration_to_candidates()`
- `_apply_confidence_calibration_to_picks()`
- `_attach_runtime_advisories_to_result()`
- `_write_trade_plan_artifact()`

## Depends On

- `runtime_common.py`
- `runtime_cleanup.py`
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
- `webapp/services/runtime_bridge.py`
- integration-style runtime tests

## Common Change Types

- add or adjust CLI/runtime modes
- wire new profile, calibration, or ranking behavior into the main flow
- surface runtime metadata and keep personal-layer effects explicit
- change artifact generation or route/chain branching
- tune the weak-tail cleanup seam without weakening candidate-stage anti-bait gates
- preserve display-only travel metadata such as gate/ansiblex counts and
  profit-before/after-logistics without leaking routing logic into the runner

## Risk Areas

- many branches share one file
- easy to duplicate business logic that belongs in domain modules
- route summaries, output files, and metadata can drift together
- profile and calibration changes can affect multiple runtime paths at once
- generic calibration and the personal layer must stay ordered and separate
- easy to accidentally apply the personal layer twice or forget the relaxed
  candidate path in `portfolio_builder.py`
- the local web UI currently bridges into `run_cli()` in-process, so stdout and
  artifact output remain part of that contract

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
