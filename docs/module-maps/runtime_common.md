# Module Map: runtime_common.py

## Purpose

Shared runtime utility module for CLI parsing, path constants, and small helper
functions used across the CLI stack.

## Responsibilities

- owns runtime path constants
- owns `parse_cli_args()` and `parse_isk()`
- provides small CLI/input helpers
- provides basic auth helper generation

## Inputs

- raw CLI argument arrays
- environment values and local filesystem paths
- interactive input for default prompts

## Outputs

- parsed CLI option dicts
- normalized ISK values
- shared path constants and auth helper strings

## Key Files

- `runtime_common.py`
- `main.py`
- `journal_cli.py`
- `runtime_clients.py`

## Important Entry Points

- `parse_cli_args()`
- `parse_isk()`
- `_has_live_esi_credentials()`
- `input_with_default()`

## Depends On

- standard library only

## Used By

- `runtime_runner.py`
- `runtime_clients.py`
- `journal_cli.py`
- `journal_store.py`
- `nullsectrader.py`

## Common Change Types

- add CLI flags
- adjust shared path handling
- change credential detection rules
- add small startup helpers

## Risk Areas

- CLI flag changes ripple into runtime and tests quickly
- path changes can break cache, token, or journal locations
- this small file sits on the startup path for several modules

## Tests

- `tests/test_execution_plan.py` covers current `--compact` and `--detail`
  parsing
- other CLI parsing behavior may be covered indirectly through runtime tests

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `runtime_common.py`
3. relevant tests
4. dependent modules only if required

Read `docs/module-maps/runtime_runner.md` first if the CLI change affects
orchestration or output flow.

## When This File Must Be Updated

Update this module map when responsibilities, dependencies, architecture, or
key entry points change.
