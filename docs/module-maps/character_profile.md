# Module Map: character_profile.py

## Purpose

Owns optional private character context for the trader runtime: live sync,
cache fallback, profile mapping, fee-skill extraction, and pick/result
annotation.

## Responsibilities

- resolve `character_context` config defaults
- decide between live sync, cache, and generic fallback
- map skills, skill queue, orders, and wallet data into one local profile
- derive fee-skill overrides and order-exposure hints
- attach character summary data to route results and picks

## Inputs

- root config dict
- authenticated data from `eve_character_client.py`
- local cache envelopes from `local_cache.py`

## Outputs

- character context dict used by `runtime_runner.py`
- cached `character_profile.json`
- fee-skill override metadata
- pick/result annotations for output

## Key Files

- `character_profile.py`
- `eve_character_client.py`
- `eve_sso.py`
- `local_cache.py`

## Important Entry Points

- `resolve_character_context()`
- `sync_character_profile()`
- `apply_character_fee_overrides()`
- `attach_character_context_to_result()`
- `requested_character_scopes()`

## Depends On

- `eve_character_client.py`
- `local_cache.py`
- `runtime_common.py`

## Used By

- `runtime_runner.py`
- tests for character context / output integration

## Common Change Types

- add new cached character data domains
- change fallback rules between live/cache/default
- extend fee-skill mapping
- surface new order or wallet summaries in runtime/output

## Risk Areas

- easy to blur runtime policy and raw API mapping
- cache freshness rules affect whether sync happens at run start
- fee override changes can silently affect all profit calculations
- order-exposure annotation should stay diagnostic unless explicitly promoted to scoring

## Tests

- `tests/test_character_context.py`
- `tests/test_execution_plan.py`
- `tests/test_eve_sso.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `character_profile.py`
3. `tests/test_character_context.py`
4. `runtime_runner.py` only if the change affects runtime wiring

## When This File Must Be Updated

Update this module map when sync responsibilities, fallback rules, cache
format, or fee/order integration behavior changes.
