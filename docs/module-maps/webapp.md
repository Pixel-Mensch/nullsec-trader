# Module Map: webapp

## Purpose

Local browser UI for Nullsec Trader Tool. It surfaces existing runtime,
journal, character, and config workflows without replacing the CLI.

## Responsibilities

- own the FastAPI app, page routes, templates, and static assets
- keep web calls separated from domain logic through small service modules
- reuse existing runtime, journal, and character functions instead of redoing
  trade logic in HTML handlers
- stay local-only and optional
- keep process lifetime simple; the local server no longer uses browser
  heartbeat or idle auto-shutdown logic

## Inputs

- config and runtime defaults from `config_loader.py`
- character context and cache summaries from `character_profile.py`
- journal and calibration summaries from `journal_reporting.py` and
  `confidence_calibration.py`
- runtime output bridged from `runtime_runner.run_cli()`

## Outputs

- local HTTP pages on `127.0.0.1:8000`
- rendered dashboard, analysis, journal, character, and config views
- browser-safe summaries of existing text artifacts and manifest files

## Key Files

- `webapp/app.py`
- `webapp/routes/pages.py`
- `webapp/services/runtime_bridge.py`
- `webapp/services/analysis_service.py`
- `webapp/services/dashboard_service.py`
- `webapp/services/journal_service.py`
- `webapp/services/character_service.py`
- `webapp/services/config_service.py`
- `webapp/templates/`
- `webapp/static/`
- `tests/test_webapp.py`

## Important Entry Points

- `webapp.app:create_app`
- `webapp.app:run_dev_server`
- page routes in `webapp/routes/pages.py`
- `invoke_runtime()` in `webapp/services/runtime_bridge.py`

## Depends On

- `runtime_runner.py`
- `runtime_common.py`
- `config_loader.py`
- `character_profile.py`
- `journal_reporting.py`
- `journal_store.py`
- `confidence_calibration.py`
- FastAPI / Jinja2

## Used By

- local browser sessions
- `nullsec-trader-web`
- `uvicorn webapp.app:create_app --factory`
- `tests/test_webapp.py`

## Common Change Types

- add or refine local pages
- improve browser-safe formatting of runtime or journal outputs
- tighten service boundaries around runtime and character calls
- expose more status metadata without changing trading logic

## Risk Areas

- easy to accidentally duplicate CLI business logic inside services
- runtime bridge currently calls `run_cli()` in-process; stdout/artifact parsing
  must stay aligned with CLI output
- character and reconcile actions must remain robust without live ESI
- templates can drift from real service payloads if not covered by tests

## Tests

- `tests/test_webapp.py`
- relevant regression coverage also comes from existing runtime, journal, and
  character-context tests

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. relevant service module in `webapp/services/`
3. `webapp/routes/pages.py`
4. `tests/test_webapp.py`
5. underlying runtime or journal module only if required

## When This File Must Be Updated

Update this module map when the web service boundaries, entry points, or page
coverage change.
