# Module Map: webapp

## Purpose

Local browser UI for Nullsec Trader Tool. It surfaces existing runtime,
journal, character, and config workflows without replacing the CLI.

## Responsibilities

- own the FastAPI app, page routes, templates, and static assets
- keep web calls separated from domain logic through small service modules
- reuse existing runtime, journal, and character functions instead of redoing
  trade logic in HTML handlers
- stay local-only / private and optional for one operator
- keep process lifetime simple; the local server no longer uses browser
  heartbeat or idle auto-shutdown logic
- enforce a small private-deploy access seam: optional Basic Auth when a web
  password exists, otherwise allow only direct localhost request shape and
  block proxy-shaped or non-local requests
- keep one small active-character seam for private single-user use: the web UI
  may switch between locally saved characters, but it should do so by
  replacing the existing active runtime token/profile files rather than
  inventing a parallel multi-user runtime model
- keep one equally small active-profile seam for private single-user use: the
  web UI may switch between existing built-in risk profiles, but it should do
  so through a tiny local default-state file instead of inventing a session or
  multi-user profile layer
- keep sensitive template payloads narrow: config and character pages should
  receive redacted/sanitized view-models, not raw secret-bearing config blobs
- keep public or multi-user web hardening explicitly out of scope for this seam

## Inputs

- config and runtime defaults from `config_loader.py`
- character context and cache summaries from `character_profile.py`
- journal and calibration summaries from `journal_reporting.py` and
  `confidence_calibration.py`
- runtime output bridged from `runtime_runner.run_cli()`

## Outputs

- local HTTP pages on `127.0.0.1:8000` for private single-user operation
- rendered dashboard, analysis, journal, character, and config views
- browser-safe summaries of existing text artifacts and manifest files

## Key Files

- `webapp/app.py`
- `webapp/routes/pages.py`
- `webapp/services/runtime_bridge.py`
- `webapp/services/analysis_service.py`
- `webapp/services/active_profile_service.py`
- `webapp/services/active_character_service.py`
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
- surface active-character state globally and switch it without bypassing the
  existing runtime/journal character-context files
- surface active-profile state globally and keep browser analysis defaults
  aligned with that selected built-in profile
- make the journal web flow clearly distinguish local journal entries from
  current character snapshot / reconcile data
- expose active-character sell-order context in the journal page using real
  cached character data instead of fabricated browser-side state
- keep browser route presentation aligned with runtime corridor-display
  metadata instead of inventing a second ranking view
- surface compact internal travel metadata from runtime artifacts, including
  gate/ansiblex counts, ansiblex logistics cost, and visible ansiblex legs,
  without designing a second corridor UI
- surface compact candidate-node summaries from runtime artifacts when routes
  touch configured watch nodes, without inventing a new browser-side routing or
  market classification model
- keep private-deploy wording honest so docs do not over-promise public-grade
  web hardening

## Risk Areas

- easy to accidentally duplicate CLI business logic inside services
- runtime bridge currently calls `run_cli()` in-process; stdout/artifact parsing
  must stay aligned with CLI output
- character and reconcile actions must remain robust without live ESI
- active-character switching must not leave mismatched token/profile state
  behind; when a saved character lacks one side of the data, the web seam
  should clear the stale active file rather than silently mixing characters
- active-profile switching must stay sourced from `BUILTIN_PROFILES`; the web
  layer should not grow a second profile registry or drift from runtime names
- templates can drift from real service payloads if not covered by tests,
  especially on sensitive pages where only redacted/sanitized fields should
  reach Jinja
- request locality is intentionally a small seam; reverse-proxy / public
  deployment assumptions should not be inferred from this module, and any
  proxy/tunnel deployment should be treated as password-required

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
