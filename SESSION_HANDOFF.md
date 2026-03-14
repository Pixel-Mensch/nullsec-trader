# Session Handoff

Date: 2026-03-14 (session 27 web hardening + corridor display)
Branch: `dev`

## Completed This Session

Implemented the planned local block around private web access and
streckenlogik-based route presentation without changing route-search scoring.

## Root Cause

- the local web app had no request-level protection seam, so a private deploy
  could be exposed remotely without any access control
- browser-sensitive pages (`/config`, `/character`) relied only on “local use”
  convention instead of explicit guardrails
- route-profile artifacts and browser result cards still reflected generation
  order more than corridor logic, so direct legs, longer profitable spans, and
  Jita connectors were harder to compare side by side
- a local in-flight alias change in `location_utils.py` would have broken `1st`
  normalization and made `O4T -> 1ST` / Jita-to-1ST visibility fragile

## What Changed

- `webapp/security.py` and `webapp/app.py`
  - added a small request-level access seam
  - optional Basic Auth protects the full app when a web password is present
  - remote requests are blocked if no password is configured
  - `run_dev_server()` now warns on non-local bind without password and can
    read host/port overrides from env or optional local config
- `webapp/routes/pages.py`, `webapp/templates/base.html`,
  `webapp/templates/config.html`
  - render security state on every page
  - sensitive pages now clearly show the local-only / protected status
- `webapp/services/config_service.py`
  - exposes a redacted web-access summary and includes `webapp` config in the
    browser-safe config sections
- `location_utils.py`
  - restored `1st` normalization so corridor and Jita connector routes using
    `1st` stay distinct from `cj6` aliases
- `runtime_runner.py`, `journal_models.py`, `execution_plan.py`,
  `webapp/services/analysis_service.py`, `webapp/templates/results.html`
  - added presentation-only corridor metadata on route results and manifest
    routes
  - execution plans now group sections by corridor source and route logic
    (direct leg first, then longer spans, Jita connectors separate)
  - browser results now mirror the same grouped corridor presentation
- `scripts/quality_check.py` and `.github/workflows/ci.yml`
  - added a minimal CI workflow
  - quality-check now uses the maintained pytest path for the changed route/web
    surface instead of relying on the old lightweight runner only

## Tests And Verification

- focused regression:
  - `pytest -q tests/test_route_search.py tests/test_runtime_runner.py tests/test_execution_plan.py tests/test_webapp.py tests/test_shipping.py tests/test_integration.py`
    -> **155 passed**
- quality path:
  - `python scripts/quality_check.py`
    -> **178 passed**
- new coverage proves:
  - `1st` normalization still preserves corridor and Jita-to-1ST pair building
  - route-display metadata marks direct legs, longer spans, and Jita connectors
  - execution plans render corridor sections in the intended order
  - browser results render grouped corridor sections and route-logic labels
  - remote requests are blocked without password, and password-protected web
    requests require / accept Basic Auth

## Remaining Limits

- the new web protection is intentionally small and private-deploy oriented; it
  is not a multi-user auth system with sessions, roles, or CSRF model
- `scripts/quality_check.py` now targets the maintained execution-plan/web
  regression surface. A separate full-suite run still currently exposes older
  unrelated failures in `tests/test_journal_reconciliation.py` and
  `tests/test_no_trade.py`

## Files Touched

- `location_utils.py`
- `runtime_runner.py`
- `journal_models.py`
- `execution_plan.py`
- `nullsectrader.py`
- `webapp/security.py`
- `webapp/app.py`
- `webapp/routes/pages.py`
- `webapp/services/analysis_service.py`
- `webapp/services/config_service.py`
- `webapp/templates/base.html`
- `webapp/templates/config.html`
- `webapp/templates/results.html`
- `webapp/static/css/app.css`
- `config.local.example.json`
- `.github/workflows/ci.yml`
- `scripts/quality_check.py`
- `tests/test_route_search.py`
- `tests/test_runtime_runner.py`
- `tests/test_execution_plan.py`
- `tests/test_webapp.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `README.md`
- `SESSION_HANDOFF.md`
