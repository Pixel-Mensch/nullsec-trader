# Module Map: eve_character_client.py

## Purpose

Thin authenticated ESI client for private character endpoints used by the
character-profile layer.

## Responsibilities

- call authenticated character endpoints
- paginate character orders and wallet endpoints
- return wallet paging metadata when the caller asks for it
- resolve names for skills and item types
- keep raw transport separate from business mapping

## Inputs

- root config dict
- requested scopes
- `EveSSOAuth` token provider

## Outputs

- raw JSON payloads from character ESI endpoints
- optional wallet paging metadata (`pages_loaded`, `total_pages`, `history_truncated`)
- resolved ID->name mappings

## Key Files

- `eve_character_client.py`
- `eve_sso.py`
- `character_profile.py`

## Important Entry Points

- `get_identity()`
- `get_skills()`
- `get_skill_queue()`
- `get_open_orders()`
- `get_wallet_balance()`
- `get_wallet_journal()`
- `get_wallet_transactions()`
- `resolve_names()`

## Depends On

- `eve_sso.py`
- `requests`

## Used By

- `character_profile.py`

## Common Change Types

- add new character endpoints
- change pagination rules
- change wallet metadata returned to the profile layer
- tighten HTTP error handling

## Risk Areas

- path/scope mismatch breaks sync quickly
- over-eager pagination can create large sync payloads
- wallet paging changes silently affect reconciliation coverage downstream
- transport logic must stay free of trading heuristics

## Tests

- `tests/test_character_context.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `eve_character_client.py`
3. `character_profile.py`
4. tests only after the target endpoint is clear

## When This File Must Be Updated

Update this module map when supported endpoints, pagination behavior, or
dependencies change.
