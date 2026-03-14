# Architecture

Last updated: 2026-03-14 (session 29 reviewer follow-up)

## Evidence And Limits

This map is intentionally narrow.
It is based on the root control files, `README.md`, `pyproject.toml`,
`config.json`, `main.py`, `runtime_runner.py`, `candidate_engine.py`,
`confidence_calibration.py`, `risk_profiles.py`, targeted tests, and current
`git status`.

It is meant to reduce future repository scanning, not to be a full code index.
If a module is not listed here, assume it was not re-audited in this session.

## Module Map System

Detailed hotspot maps live under `docs/module-maps/`.

Current module maps:

- `docs/module-maps/runtime_runner.md`
- `docs/module-maps/candidate_engine.md`
- `docs/module-maps/execution_plan.md`
- `docs/module-maps/route_search.md`
- `docs/module-maps/runtime_common.md`
- `docs/module-maps/risk_profiles.md`
- `docs/module-maps/confidence_calibration.md`
- `docs/module-maps/journal_reporting.md`
- `docs/module-maps/character_profile.md`
- `docs/module-maps/eve_sso.md`
- `docs/module-maps/eve_character_client.md`
- `docs/module-maps/journal_reconciliation.md`
- `docs/module-maps/webapp.md`

Use the relevant module map before opening one of these larger files.

## True Runtime Entry Path

The productive startup path is:

1. `run.bat` or `run_trader.ps1`
2. `main.py`
3. `runtime_runner.run_cli()`

`nullsectrader.py` is not the main CLI path. It is a thin compatibility and
import facade used by tests and local tooling.

## High-Value Files By Task

Use this section to avoid loading large unrelated modules.

- CLI argument parsing and shared runtime helpers: `runtime_common.py`
- Safe runtime-artifact cleanup and cache reset: `runtime_cleanup.py`
- Runtime orchestration, mode selection, replay/live flow, output fan-out:
  `runtime_runner.py`
- Config loading, validation, overrides, and directory setup: `config_loader.py`
- Live and replay clients: `runtime_clients.py`
- Private character SSO and token lifecycle: `eve_sso.py`
- Private character ESI fetches: `eve_character_client.py`
- Character profile mapping, cache fallback, and fee/order integration:
  `character_profile.py`
- Wallet-to-journal matching and personal trade reconciliation:
  `journal_reconciliation.py`
- Wallet snapshot persistence and reconciliation state storage:
  `journal_store.py`
- Candidate generation, planned-sell math, route-wide candidate scoring:
  `candidate_engine.py`
- Market plausibility heuristics plus anti-bait market-quality gate:
  `market_plausibility.py`
- Route ranking and route summary scoring, including market-quality confidence
  cap: `route_search.py`
- Portfolio construction, liquidation gating, cargo fill, and local-search
  selection objective: `portfolio_builder.py`
- Shipping costs, route blocking, and transport context: `shipping.py`
- Fee calculations: `fees.py`, `fee_engine.py`
- Human-readable output, route plan rendering, route leaderboard, and no-trade
  reports: `execution_plan.py`
- Do Not Trade decision engine (reason codes, near-misses, profile comparison): `no_trade.py`
- CSV and summary writers for chain/roundtrip artifacts with sequential-leg
  aggregate semantics: `runtime_reports.py`
- Journal CLI and persistence: `journal_cli.py`, `journal_store.py`,
  `journal_models.py`, `journal_reporting.py`
- Wallet/journal reconciliation: `journal_reconciliation.py`
- Generic confidence calibration from journal outcomes: `confidence_calibration.py`
- Personal trade analytics and personal decision-layer basis:
  `journal_reporting.py`, `confidence_calibration.py`
- Local browser UI and service bridge: `webapp/app.py`, `webapp/routes/pages.py`,
  `webapp/services/`
- Startup node and chain resolution: `startup_helpers.py`

## Runtime Flow

The main runtime flow is:

`config.json` + local/env overrides
-> `runtime_common.py` / `config_loader.py`
-> `runtime_runner.py`
-> `runtime_clients.py`
-> optional `eve_sso.py` / `eve_character_client.py` / `character_profile.py`
-> `candidate_engine.py`
-> `portfolio_builder.py`
-> `shipping.py`
-> `route_search.py`
-> `execution_plan.py` / `runtime_reports.py`
-> journal artifacts and report files

Safe clean-start flow:

`main.py clean`
-> `runtime_common.py`
-> `runtime_runner.py`
-> `runtime_cleanup.py`
-> removes generated root artifacts, transient HTTP/type caches, and Python
   cache directories
-> preserves `cache/token.json`, `cache/trade_journal.sqlite3`, and
   `cache/character_context/`

Journal reconciliation flow:

`eve_character_client.py` paged wallet fetches
-> `character_profile.py` wallet snapshot with freshness / coverage metadata
-> `journal_reconciliation.py`
-> `journal_store.py`
-> `journal_reporting.py` / `journal_cli.py`

Generic confidence calibration is fed by journal data:

`journal_store.py`
-> `confidence_calibration.py`
-> `runtime_runner.py` applies calibrated confidence to candidates, picks, and
route results

Local web flow is separate from the CLI and intentionally thin:

`webapp/app.py`
-> small request-level access guard in `webapp/security.py`
-> `webapp/routes/pages.py`
-> `webapp/services/*`
-> direct calls into `character_profile.py`, `journal_reporting.py`,
   `confidence_calibration.py`, and `journal_store.py`
-> or `webapp/services/runtime_bridge.py`
-> `runtime_runner.run_cli()` in-process for full analysis runs
-> existing artifacts and manifest files rendered into templates

`webapp.app` is now a plain local FastAPI app without browser-heartbeat or
idle auto-shutdown behavior. The local web process stays up until it is
stopped explicitly.

The web entry also owns a small private-deploy security seam:

- if `NULLSEC_WEBAPP_PASSWORD` or `webapp.access_password` is configured, the
  whole browser surface requires HTTP Basic Auth
- if no password is configured, only direct localhost request shape is treated
  as supported; proxy-shaped or non-local requests are blocked instead of
  exposing the app unguarded
- `/character` and `/config` are treated as sensitive pages and emit
  `Cache-Control: no-store`
- `webapp/services/config_service.py` and
  `webapp/services/character_service.py` now pass redacted/sanitized
  view-models into templates instead of the broader raw config/context payloads

The journal web path has two distinct data sources on purpose:

- the local journal DB drives overview/open/closed/report/personal/calibration
  pages
- character cache or live wallet data drives the journal page's snapshot
  summary plus the dedicated reconcile/unmatched views

The browser now makes that separation explicit: the journal page always shows
the current character snapshot summary it can resolve, and opening the
Reconcile/Unmatched tabs triggers real reconciliation work instead of showing a
pure placeholder.

The analysis/result browser views now rely on a small page-level layout
modifier in `base.html` plus overflow-safe CSS in `webapp/static/css/app.css`:
analysis pages can use a wider shell, grid items are allowed to shrink with
`min-width: 0`, and large runtime/report `<pre>` blocks are constrained inside
their own panels instead of widening the full page.

`shipping.py` now owns a central transport-mode decision seam:

- Jita-connected routes stay on the external shipping path (ITL/HWL lanes or
  explicit `route_costs`)
- internal structure-to-structure nullsec routes are classified as
  `internal_self_haul`
- `internal_self_haul` currently defaults to `0 ISK` transport cost unless an
  explicit internal `route_costs` entry is present
- route blocking for missing transport models still applies to non-internal,
  non-modeled routes

`runtime_runner.py` now owns a second shared post-build gating seam after
transport and confidence calibration:

- `risk_profiles.filter_picks_by_profile()` is applied to final picks in both
  `run_route()` and `run_route_wide_leg()`
- that shared seam is responsible for hard pick-level profile enforcement
  (expected profit, profit density, confidence, and max budget share)
- after that, `runtime_runner.py` can apply a narrow post-selection route-mix
  cleanup that removes clearly weak optional/speculative add-ons when route
  confidence / market quality recover materially and the route score stays
  effectively intact
- that cleanup now also looks for weak tail signals explicitly
  (`speculative`, `price-sensitive`, fragile market quality, weak retention,
  low confidence, elevated manipulation risk) instead of relying only on raw
  score deltas
- the same post-build seam also derives clearer `route_prune_reason` buckets
  and applies the internal-self-haul operational route floor before artifacts
  are emitted
- the route-profile path now also attaches `_route_display` metadata per route
  result so presentation consumers can group direct legs, longer spans, and
  Jita connectors without changing ranking

Trade quality now has one central seam instead of separate ad-hoc penalties:

- `market_plausibility.py` computes book-structure signals, profit retention
  after conservative repricing, a derived `market_quality_score`, and a small
  combined gate for fragile thin-book setups
- `candidate_engine.py` applies that seam during candidate generation and
  carries `market_quality_score` / `profit_retention_ratio` forward on records
- `portfolio_builder.py` and `execution_plan.py` reuse those fields instead of
  inventing second-pass heuristics for local search, cargo fill, or mandatory
  labeling
- `route_search.py` caps displayed `route_confidence` by average pick market
  quality so downstream leaderboard / no-trade artifacts stay aligned
- replay-guided calibration on 2026-03-13 kept that seam intact but softened
  only two generic structural penalties (`DEPTH_COLLAPSE`,
  `ORDERBOOK_CONCENTRATION`) and the candidate-stage quality confidence
  haircut; fake-spread / thin-top / unusable-depth gates were left unchanged
- `execution_plan.py` now surfaces that seam more honestly for operators:
  PRICE-SENS / materially repriced picks show the quote basis, visible-book
  profit proxy, conservative executable profit proxy, retention, and the
  displayed profit basis actually used in the plan
- internal-route operational floor metadata is now presentation-scoped to
  `internal_self_haul` routes instead of any route result that merely carried a
  floor value
- execution-plan plan sections can now render corridor-ordered groups when
  `_route_display` metadata is present

Volume validity is now intentionally conservative across the runtime path:

- `runtime_clients.py` returns `0.0` for missing/invalid type volume instead of
  silently coercing to a positive fallback
- `candidate_engine.py` rejects such candidates via `invalid_volume`
- execution plans and prune reasons can now surface invalid-volume failures
  explicitly

Personal history flow is separate on purpose and only becomes decision-relevant
through an explicit policy gate:

`journal_store.py`
-> `journal_reporting.py`
-> optional `confidence_calibration.py` personal summary + scoped segment index
-> `runtime_runner.py` applies an opt-in, capped personal adjustment to
   `decision_overall_confidence`
-> `execution_plan.py` / runtime stdout show mode, fallback reason, and applied
   scope

The generic calibration model remains the base path. The personal layer does
not rewrite `build_confidence_calibration()`, route-ranking formulas,
`no_trade`, or planned-sell heuristics; it only nudges the already-consumed
decision confidence when policy, quality, and sample-size guardrails all pass.

## Output And State Files

Confirmed output families from the current docs and entry modules:

- `execution_plan_<timestamp>.txt`
- `route_leaderboard_<timestamp>.txt`
- `roundtrip_plan_<timestamp>.txt`
- `no_trade_<timestamp>.txt`
- `*_to_*_<timestamp>.csv`
- `*_top_candidates_<timestamp>.txt`
- `trade_plan_<plan_id>.json`
- route entries inside `trade_plan_<plan_id>.json` can now also carry a
  `display` block used by the browser results page for corridor grouping parity
- `snapshot_<timestamp>.json`
- `market_snapshot.json`
- `replay_snapshot.json`

`plan_id` / `pick_id` identity is now intentionally deterministic for identical
snapshot+input runs. The human-readable text artifacts still keep their own
wall-clock timestamps, but the canonical trade-plan JSON is keyed by the stable
plan id so replayed runs can be compared or imported with the same IDs.

Local mutable state:

- `config.local.json` is local-only and ignored by Git
- `cache/` holds runtime cache, SSO token/metadata, character profile cache,
  and journal data
- `runtime_cleanup.py` powers `python main.py clean` and intentionally deletes
  only generated artifacts plus transient caches (`cache/http_cache.json`,
  `cache/types.json`, `.pytest_cache`, `__pycache__`) while preserving local
  auth and journal state
- `trade_journal.sqlite3` now stores both manual trade events and optional
  wallet-reconciliation summaries on each entry, including wallet-snapshot
  quality fields that keep personal-history output independent from a fresh
  live sync
- `journal_store.initialize_journal_db()` is also responsible for migrating
  older local journal schemas before creating newer reconciliation indexes, so
  existing caches remain usable for CLI and web entry points
- `webapp/` adds a local-only FastAPI/Jinja2 UI layer and does not replace the
  CLI entry path

## Test Entry Points

Known test and quality entry points:

- `python -m pytest -q`
- `python tests/run_all.py`
- `python test_nullsectrader.py`
- `python scripts/quality_check.py`

`tests/run_all.py` currently imports targeted test modules instead of scanning
the repository dynamically. `scripts/quality_check.py` now compiles the full
Python source set but runs the maintained pytest subset for the web /
execution-plan / corridor-display surface; the minimal CI workflow uses that
same script instead of a separate drifting command set.

## Current Hotspots

Most recent focused work on 2026-03-13 touched:

- risk profiles and profile-aware ranking/output
- replay-based market-quality calibration against focused execution-plan and
  top-candidate artifacts
- post-selection route-mix cleanup for weak optional/speculative add-ons
- execution-plan presentation
- optional private character context via EVE SSO / ESI
- wallet-to-journal reconciliation and personal trade-history reporting
- open-order warning tiers in output and journal views
- wallet paging, freshness visibility, and conservative fee/ref matching for
  older or truncated wallet snapshots
- personal trade analytics, data-quality tiers, and a separate personal
  calibration basis with explicit fallback-to-generic guardrails
- an opt-in personal decision layer with strict caps, explainability fields,
  and runtime / execution-plan visibility
- a local FastAPI/Jinja2 browser UI that reuses runtime, journal, and
  character services without rewriting trade logic

Treat those areas as the most likely source of doc drift until targeted tests
confirm the current branch state.

## Source Of Truth By Concern

- Fees: `fees.py`, `fee_engine.py`
- Shipping and route transport blocking: `shipping.py`
- Internal self-haul vs external shipping classification: `shipping.py`
- Candidate generation and planned-sell modeling: `candidate_engine.py`
- Confidence calibration logic and personal decision-layer policy:
  `confidence_calibration.py`
- Private character auth and cacheable profile sync: `eve_sso.py`,
  `eve_character_client.py`, `character_profile.py`
- Wallet-based personal trade reconciliation: `journal_reconciliation.py`
- Route ranking: `route_search.py`
- Portfolio construction, liquidation gating, and cargo fill: `portfolio_builder.py`
- Execution plan rendering and aggregate-vs-actionable text semantics:
  `execution_plan.py`
- Runtime orchestration: `runtime_runner.py`
- Local browser delivery and service glue: `webapp/`

## AI Navigation Notes

To keep context small:

- start with this file before opening large modules
- read a relevant file in `docs/module-maps/` before opening a covered large module
- read `README.md` for product behavior, not code ownership
- prefer targeted tests and targeted modules over repo-wide search
- avoid opening `runtime_runner.py` or `candidate_engine.py` unless the task
  actually changes orchestration or candidate math

If behavior changes, update this file in the same session.
