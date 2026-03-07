# Module Map: confidence_calibration.py

## Purpose

Calibration module that learns from journal outcomes and applies calibrated
confidence values back to candidates, picks, and route records. This map is
based on a targeted audit, not a full edge-case review.

## Responsibilities

- normalizes calibration config
- classifies trade outcomes
- builds bucket and scope models
- calibrates values and mutates target records
- formats human-readable calibration reports

## Inputs

- journal entry dicts
- calibration config
- route/source/target metadata
- candidate or pick records to update

## Outputs

- calibration model dicts
- calibrated confidence values and warnings
- in-place record updates
- formatted calibration reports

## Key Files

- `confidence_calibration.py`
- `journal_models.py`
- `journal_cli.py`
- `tests/test_confidence_calibration.py`

## Important Entry Points

- `resolve_confidence_calibration_cfg()`
- `build_confidence_calibration()`
- `calibrate_confidence_value()`
- `apply_calibration_to_record()`
- `format_confidence_calibration_report()`

## Depends On

- `journal_models.py`
- standard library collections and datetime helpers

## Used By

- `runtime_runner.py`
- `journal_cli.py`
- `portfolio_builder.py`
- `route_search.py`

## Common Change Types

- tune bucket rules or scope behavior
- change sample eligibility rules
- adjust sparse-data fallback behavior
- add warning or report fields

## Risk Areas

- sparse journal data can look more precise than it is
- bucket and scope fallback behavior is subtle
- in-place mutation means downstream code may depend on added fields
- route, exit, liquidity, and transport confidence can drift if handled
  inconsistently

## Tests

- `tests/test_confidence_calibration.py`
- some downstream effects are also exercised by route and runtime tests

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `confidence_calibration.py`
3. relevant tests
4. dependent modules only if required

Read `journal_models.py` first if outcome semantics change. Read
`docs/module-maps/route_search.md` first if transport-confidence handling
changes.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
