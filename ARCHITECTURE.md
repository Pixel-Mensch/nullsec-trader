# Architecture

Last updated: 2026-03-07

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
- Market plausibility heuristics: `market_plausibility.py`
- Route ranking and route summary scoring: `route_search.py`
- Portfolio construction, liquidation gating, and cargo fill: `portfolio_builder.py`
- Shipping costs, route blocking, and transport context: `shipping.py`
- Fee calculations: `fees.py`, `fee_engine.py`
- Human-readable output, route plan rendering, and no-trade reports: `execution_plan.py`
- Do Not Trade decision engine (reason codes, near-misses, profile comparison): `no_trade.py`
- CSV and summary writers: `runtime_reports.py`
- Journal CLI and persistence: `journal_cli.py`, `journal_store.py`,
  `journal_models.py`, `journal_reporting.py`
- Wallet/journal reconciliation: `journal_reconciliation.py`
- Generic confidence calibration from journal outcomes: `confidence_calibration.py`
- Personal trade analytics and analytics-only personal calibration basis:
  `journal_reporting.py`, `confidence_calibration.py`
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

Journal reconciliation flow:

`eve_character_client.py` paged wallet fetches
-> `character_profile.py` wallet snapshot with freshness / coverage metadata
-> `journal_reconciliation.py`
-> `journal_store.py`
-> `journal_reporting.py` / `journal_cli.py`

Confidence calibration is fed by journal data:

`journal_store.py`
-> `confidence_calibration.py`
-> `runtime_runner.py` applies calibrated confidence to candidates, picks, and
route results

Personal analytics flow is separate on purpose:

`journal_store.py`
-> `journal_reporting.py`
-> optional `confidence_calibration.py` personal summary
-> `journal_cli.py`

This path is currently analytics-only and does not feed back into route ranking
or candidate scoring.

## Output And State Files

Confirmed output families from the current docs and entry modules:

- `execution_plan_<timestamp>.txt`
- `route_leaderboard_<timestamp>.txt`
- `roundtrip_plan_<timestamp>.txt`
- `*_to_*_<timestamp>.csv`
- `*_top_candidates_<timestamp>.txt`
- `trade_plan_<plan_id>.json`
- `market_snapshot.json`

Local mutable state:

- `config.local.json` is local-only and ignored by Git
- `cache/` holds runtime cache, SSO token/metadata, character profile cache,
  and journal data
- `trade_journal.sqlite3` now stores both manual trade events and optional
  wallet-reconciliation summaries on each entry, including wallet-snapshot
  quality fields that keep personal-history output independent from a fresh
  live sync

## Test Entry Points

Known test and quality entry points:

- `python -m pytest -q`
- `python tests/run_all.py`
- `python test_nullsectrader.py`
- `python scripts/quality_check.py`

`tests/run_all.py` currently imports targeted test modules instead of scanning
the repository dynamically.

## Current Hotspots

Most recent focused work on 2026-03-07 touched:

- risk profiles and profile-aware ranking/output
- execution-plan presentation
- optional private character context via EVE SSO / ESI
- wallet-to-journal reconciliation and personal trade-history reporting
- open-order warning tiers in output and journal views
- wallet paging, freshness visibility, and conservative fee/ref matching for
  older or truncated wallet snapshots
- personal trade analytics, data-quality tiers, and a separate personal
  calibration basis with explicit fallback-to-generic guardrails

Treat those areas as the most likely source of doc drift until targeted tests
confirm the current branch state.

## Source Of Truth By Concern

- Fees: `fees.py`, `fee_engine.py`
- Shipping and route transport blocking: `shipping.py`
- Candidate generation and planned-sell modeling: `candidate_engine.py`
- Confidence calibration logic: `confidence_calibration.py`
- Private character auth and cacheable profile sync: `eve_sso.py`,
  `eve_character_client.py`, `character_profile.py`
- Wallet-based personal trade reconciliation: `journal_reconciliation.py`
- Route ranking: `route_search.py`
- Portfolio construction, liquidation gating, and cargo fill: `portfolio_builder.py`
- Execution plan rendering: `execution_plan.py`
- Runtime orchestration: `runtime_runner.py`

## AI Navigation Notes

To keep context small:

- start with this file before opening large modules
- read a relevant file in `docs/module-maps/` before opening a covered large module
- read `README.md` for product behavior, not code ownership
- prefer targeted tests and targeted modules over repo-wide search
- avoid opening `runtime_runner.py` or `candidate_engine.py` unless the task
  actually changes orchestration or candidate math

If behavior changes, update this file in the same session.
