# Session Handoff

Date: 2026-03-14 (session 29 reviewer follow-up for private web deploy semantics)
Branch: `dev`

## Completed This Session

Implemented only the reviewer-requested follow-up around the private web seam,
sensitive browser payloads, security regressions, and minimal CI alignment.
No corridor-ordering or route-scoring logic was expanded.

## Root Cause

- the first web-hardening pass still allowed proxy-like loopback requests to
  look local too easily when password auth was disabled
- `/config` and `/character` still passed broader raw config/context objects
  into templates than needed
- security regressions did not yet prove `Cache-Control`, redaction, and
  request-classification behavior end to end
- CI still installed unused `pyflakes`, so the workflow and
  `scripts/quality_check.py` had minor drift

## What Changed

- `webapp/security.py`
  - tightened request classification so passwordless mode only accepts direct
    localhost request shape
  - proxy hint headers and non-loopback host/client combinations now fall into
    the blocked path until a password is configured
- `webapp/app.py`
  - aligned the dev-server warning text with the stricter localhost-only
    passwordless mode
- `webapp/services/config_service.py`
  - removed raw config objects from the template payload
  - kept only explicit redacted view fields, including masked web password data
- `webapp/services/character_service.py`
  - removed raw config/context objects from the template payload
  - now passes only sanitized auth, character-context, and summary fields
- `tests/test_webapp.py`
  - added regressions for `Cache-Control: no-store` on `/config` and
    `/character`
  - added config redaction and sanitized character-context checks
  - added direct tests for `describe_request_access()` with proxy-shaped inputs
- `.github/workflows/ci.yml`
  - removed unused `pyflakes` installation so the workflow matches the real
    maintained quality path
- `README.md`, `PROJECT_STATE.md`, `TASK_QUEUE.md`, `ARCHITECTURE.md`,
  `docs/module-maps/webapp.md`
  - aligned docs with the stricter private-deploy semantics and the sensitive
    page minimization now in code

## Tests And Verification

- `python -m pytest -q tests/test_webapp.py`
  - **21 passed**
- `python -m pytest -q tests/test_route_search.py tests/test_runtime_runner.py tests/test_execution_plan.py tests/test_webapp.py tests/test_shipping.py tests/test_integration.py`
  - **164 passed**
- `python scripts/quality_check.py`
  - **187 passed**

## Remaining Limits

- the web seam remains intentionally small and private-deploy oriented; it is
  still not a public or multi-user auth/session system
- the supported passwordless mode is direct localhost use by one operator;
  proxy/tunnel/private remote use is intentionally password-required
- a fully opaque local proxy that strips all proxy hints before forwarding is
  not distinguishable from a direct localhost client at the HTTP app layer, so
  deployment guidance stays simple: treat any proxy/tunnel setup as
  password-required
- `scripts/quality_check.py` and CI still intentionally cover the maintained
  regression surface rather than the entire historical suite

## Next Recommended Task

If further hardening is needed later, decide explicitly whether the project
wants a trusted reverse-proxy model or to keep the simpler rule that any
proxy/tunnel deployment must run behind a password.

## Files Touched

- `.github/workflows/ci.yml`
- `webapp/app.py`
- `webapp/security.py`
- `webapp/services/character_service.py`
- `webapp/services/config_service.py`
- `tests/test_webapp.py`
- `README.md`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
- `docs/module-maps/webapp.md`
