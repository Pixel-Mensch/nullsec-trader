# Module Map: confidence_calibration.py

## Purpose

Calibration module that learns from journal outcomes and applies calibrated
confidence values back to candidates, picks, and route records. This map is
based on a targeted audit, not a full edge-case review. It now also owns a
separate opt-in personal-history layer that can apply small bounded adjustments
to `decision_overall_confidence` without rewriting the generic model.

## Responsibilities

- normalizes calibration config
- classifies trade outcomes
- builds bucket and scope models
- builds a guarded personal calibration basis from reconciled history
- resolves `personal_history_policy` and personal-layer guardrails
- builds scoped personal segment indexes for decision use
- calibrates values and mutates target records
- applies bounded personal-history adjustments with explainability fields
- formats human-readable calibration reports
- formats compact layer status lines for runtime/output surfaces

## Inputs

- journal entry dicts
- calibration config
- route/source/target metadata
- candidate or pick records to update

## Outputs

- calibration model dicts
- personal calibration summary dicts with quality and sample-size guardrails
- personal layer state dicts
- calibrated confidence values and warnings
- in-place record updates with optional personal-layer explainability
- formatted calibration reports

## Key Files

- `confidence_calibration.py`
- `journal_models.py`
- `journal_cli.py`
- `journal_reporting.py`
- `tests/test_confidence_calibration.py`

## Important Entry Points

- `resolve_confidence_calibration_cfg()`
- `build_confidence_calibration()`
- `build_personal_calibration_summary()`
- `build_personal_history_layer_state()`
- `apply_personal_history_to_record()`
- `summarize_personal_history_effect()`
- `personal_history_layer_status_lines()`
- `calibrate_confidence_value()`
- `apply_calibration_to_record()`
- `format_confidence_calibration_report()`
- `format_personal_calibration_summary()`

## Depends On

- `journal_models.py`
- standard library collections and datetime helpers

## Used By

- `runtime_runner.py`
- `execution_plan.py`
- `journal_cli.py`
- `portfolio_builder.py`
- `route_search.py`

## Common Change Types

- tune bucket rules or scope behavior
- adjust personal-history quality thresholds, scoped signals, or guardrails
- change sample eligibility rules
- adjust sparse-data fallback behavior
- add warning or report fields

## Risk Areas

- sparse journal data can look more precise than it is
- personal history must remain explicit, bounded, and easy to disable
- the generic model and personal layer must not get conflated
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
`docs/module-maps/journal_reporting.md` first if personal-history output or
guardrails change. Read `docs/module-maps/route_search.md` first if
transport-confidence handling changes.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
