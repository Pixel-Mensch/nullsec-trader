# Module Map: eve_sso.py

## Purpose

Local EVE SSO helper for private character auth: metadata discovery, auth-code
flow, refresh flow, token storage, and token-claim decoding.

## Responsibilities

- load/save local SSO token
- discover official SSO metadata with cached fallback
- run the localhost callback flow
- exchange auth codes and refresh tokens
- decode JWT claims for character identity and granted scopes

## Inputs

- ESI client credentials and callback URL
- requested scopes
- local token / metadata cache files

## Outputs

- stored SSO token
- cached SSO metadata
- decoded identity/scopes from access token claims

## Key Files

- `eve_sso.py`
- `runtime_common.py`
- `local_cache.py`

## Important Entry Points

- `EveSSOAuth.ensure_token()`
- `EveSSOAuth.oauth_authorize()`
- `EveSSOAuth.refresh_token()`
- `decode_access_token_claims()`
- `token_identity_from_claims()`

## Depends On

- `requests`
- `local_cache.py`
- `config_loader.py`

## Used By

- `eve_character_client.py`
- `runtime_runner.py` auth command
- `tests/test_eve_sso.py`

## Common Change Types

- add auth error handling
- adjust metadata fallback behavior
- change token storage rules
- improve PKCE / callback handling

## Risk Areas

- token scopes and refresh state are security-sensitive
- callback URL handling is easy to break on Windows localhost setups
- auth bugs can block character sync entirely

## Tests

- `tests/test_eve_sso.py`
- indirect coverage via `tests/test_character_context.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `eve_sso.py`
3. `tests/test_eve_sso.py`
4. `character_profile.py` only if the change affects sync behavior

## When This File Must Be Updated

Update this module map when auth flow, token storage, metadata discovery, or
identity extraction changes.
