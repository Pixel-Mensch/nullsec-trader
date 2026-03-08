# Task Queue

Last updated: 2026-03-07 (session 11 local web UI)

This queue is intentionally small and focused.
It reflects the current visible hotspots from a narrow repository audit, not a
full backlog scrape.

## P0

### Task 1: Verify and stabilize risk-profile integration

- Priority: P0
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Fixed Gap 1: `filter_picks_by_profile` was never called in
    `runtime_runner.py` — now called after calibration so `min_profit_per_m3`
    is actually enforced.
  - Fixed Gap 2: `_profile_min_confidence` was stored in filters dict but never
    enforced against picks' `decision_overall_confidence` — confidence gate now
    runs in the same block.
  - Added `TestProfileEndToEnd` (9 tests) to `tests/test_risk_profiles.py`
    proving profiles produce different outcomes on identical inputs.
  - Full suite: 239 passed.

## P1

### Task 2: Practical output + Do Not Trade + full audit (this session)

- Priority: P0
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - **Task A/C — execution_plan.py patches:**
    - Fixed `_route_level_warnings` dominance calc to use `expected_realized_profit_90d`
      instead of gross `profit` (consistent with portfolio_builder K1 fix from last session)
    - Fixed pick sort order within categories to use `expected_realized_profit_90d`
    - Removed duplicate `total_route_m3` and `shipping_cost_total` lines from
      `_write_route_trip_summary` — now a single `Shipping:` line
    - Added `>>> MAX BUY: X ISK/unit` price threshold to every pick block
    - Added `>>> MIN SELL: X ISK/unit` threshold for planned_sell picks
    - Added `write_no_trade_report()` function for DO NOT TRADE artifacts
  - **Task B — no_trade.py (new module):**
    - `evaluate_no_trade()` with 10 reason codes, profile-aware thresholds,
      near-miss summaries, and cross-profile comparison
    - Integrated in `runtime_runner.py` after `write_execution_plan_profiles`
    - Produces `no_trade_<timestamp>.txt` when DNT is triggered
    - Prints `[DO NOT TRADE]` console message with reason code summary
  - 36 new tests in `tests/test_no_trade.py`
  - Updated `tests/test_execution_plan.py` and `tests/test_shipping.py`
    to match new output format
  - **Critical review follow-up patches:**
    - Removed dead `INSUFFICIENT_LIQUIDITY` reason code (defined but never emitted)
    - Renamed `PROFILE_REJECTED_AVAILABLE_TRADES` → `CANDIDATES_DID_NOT_SURVIVE_FILTERS`
      with corrected wording (base config gates also possible cause, not only profile)
    - Added honest docstrings to all threshold-derivation helpers in `no_trade.py`
    - Restored specific shipping label assertion in `test_shipping.py`
      (was trivially-true substring; now checks exact `Shipping:  ... (transport cost)` line)
  - Full suite: **275 passed**

### Task 2b: Core portfolio logic follow-up

- Priority: P0
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Fixed B1 in `portfolio_builder.py`: scaled `expected_days_to_sell` now
    keeps the `queue_ahead_units` component instead of shrinking only by
    `qty / max_units`
  - Fixed B3 in `portfolio_builder.py`: cargo-fill profit-per-m3 gating now
    uses expected-realized profit consistently for planned candidates and fill
    picks
  - Re-reviewed B2 in `route_search.py`: no code change; the planned-share
    speculative penalty still looks like a distinct route-mix heuristic rather
    than a confirmed double-penalty
  - Added regression coverage in `tests/test_portfolio.py`
  - Full suite: **278 passed**

### Task 2c: Optional private character context via EVE SSO / ESI

- Priority: P0
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Added local EVE SSO support in `eve_sso.py` with metadata discovery,
    auth-code flow, refresh flow, ignored local token storage, and token-claim
    identity extraction
  - Added `eve_character_client.py` for authenticated character endpoints:
    skills, optional skill queue, open orders, wallet balance, wallet journal,
    wallet transactions, and bulk name resolution
  - Added `character_profile.py` plus `local_cache.py` for character-profile
    sync, cache fallback, fee-skill extraction, and order-exposure annotation
  - Integrated optional character context into `runtime_runner.py`,
    `runtime_common.py`, and `execution_plan.py`
  - Added `auth` and `character` CLI subcommands for local login/status/sync
  - Added targeted tests in `tests/test_character_context.py` and
    `tests/test_eve_sso.py`
  - Full suite: **289 passed**

### Task 3: Add a targeted CLI smoke-test path for profile-aware runs

- Priority: P1
- Status: ready
- Relevant files: `main.py`, `runtime_common.py`, `runtime_runner.py`,
  `tests/`, `test_nullsectrader.py`
- Expected result: one narrow automated test or smoke-test script confirms that
  the CLI can parse profile flags and reach the expected runtime path without
  requiring a broad end-to-end environment.

### Task 3: Reduce AI context cost around large orchestration modules

- Priority: P1
- Status: in_progress
- Relevant files: `runtime_runner.py`, `candidate_engine.py`,
  `ARCHITECTURE.md`, `SESSION_HANDOFF.md`, `docs/module-maps/`
- Expected result: future tasks can target smaller sections or helper seams
  without reopening both large files in full; do this with small extractions or
  navigation notes only after behavior is verified.
- Progress note: initial module maps now cover `runtime_runner.py`,
  `candidate_engine.py`, `execution_plan.py`, `route_search.py`,
  `runtime_common.py`, `risk_profiles.py`,
  `confidence_calibration.py`, `character_profile.py`, `eve_sso.py`, and
  `eve_character_client.py`

### Task 4: Keep the control-file workflow current during feature work

- Priority: P1
- Status: ongoing
- Relevant files: `PROJECT_STATE.md`, `TASK_QUEUE.md`, `ARCHITECTURE.md`,
  `SESSION_HANDOFF.md`, `.github/copilot-instructions.md`
- Expected result: each behavior change or session updates the state, queue, and
  handoff docs so future agents do not need to infer session context from git
  status alone.

### Task 5: Improve personal trading context without hard-coupling live ESI

- Priority: P1
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Added `journal_reconciliation.py` for wallet transaction / wallet journal
    matching with explicit confidence, reasons, ambiguous matches, and unmatched
    activity tracking
  - Extended `journal_store.py` patch-safely so journal entries persist wallet
    transaction IDs, wallet journal IDs, matched quantities/values, realized
    fee estimate, realized wallet profit, reconciliation status, and order
    warning tier
  - Extended `journal_cli.py` with `reconcile`, `personal`, and `unmatched`
    commands using live-or-cache character context without hard dependency on
    live ESI
  - Extended `journal_reporting.py` to surface effective open positions,
    reconciled profit, uncertain matches, and personal trade-history views
  - Strengthened open-order overlap from pure diagnosis to visible warning tier
    in `execution_plan.py` and persisted plan imports
  - Added targeted coverage in `tests/test_journal_reconciliation.py`
  - Focused tests: **104 passed**

### Task 5b: Deepen wallet-history quality without forcing heuristics

- Priority: P1
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - `eve_character_client.py` now returns optional paging metadata for wallet
    journal and wallet transactions (`pages_loaded`, `total_pages`,
    `history_truncated`)
  - `character_profile.py` now stores wallet snapshot freshness and coverage
    metadata in the local character profile, including page counts, oldest/newest
    timestamps, and truncation hints
  - `journal_reconciliation.py` now distinguishes fresh/stale and
    full/partial/truncated wallet bases, marks entries uncertain when a
    truncated transaction window does not cover the trade, and makes fee
    matching explicitly `exact`, `partial`, `fallback`, `uncertain`, or
    `unavailable`
  - `journal_store.py` now persists the key reconciliation quality fields so
    `journal personal` and related views can show them without reopening the
    raw wallet snapshot
  - `journal_reporting.py` now surfaces wallet freshness, page coverage,
    truncation, fee-match quality, and reconciliation basis in the existing
    journal views
  - Targeted tests were extended in `tests/test_character_context.py` and
    `tests/test_journal_reconciliation.py`

### Task 5c: Use reconciled history for deeper journal analytics without changing ranking

- Priority: P1
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Moved effective wallet-backed outcome semantics into `journal_models.py`
    so personal analytics and personal calibration use the same conservative
    entry view
  - Extended `journal_reporting.py` with personal hit rates, partial-sell
    share, wallet-unmatched share, expected-vs-realized profit and duration
    deltas, open-position age buckets, and compact problem-pattern counts
  - Added a separate personal-history quality model in
    `confidence_calibration.py` with explicit levels (`none`, `very_low`,
    `low`, `usable`, `good`) and guardrails that keep poor or sparse history on
    generic fallback
  - Added `build_personal_calibration_summary()` and
    `format_personal_calibration_summary()` without changing
    `build_confidence_calibration()` or runtime ranking paths
  - Extended `journal personal` and `journal calibration` to surface the new
    analytics and personal calibration basis while keeping ranking effect at
    `none`
  - Added targeted coverage in `tests/test_confidence_calibration.py`,
    `tests/test_journal.py`, and `tests/test_journal_reconciliation.py`

### Task 5d: Decide how personal history should stay observable before any opt-in decision hook

- Priority: P1
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Added `personal_calibration_status_lines()` in
    `confidence_calibration.py` for compact runtime-safe advisory output
  - `runtime_runner.py` now loads the personal calibration summary from the
    journal DB during normal runs and prints a small `Personal History` block on
    stdout without touching generic calibration or decision logic
  - `execution_plan.py` now mirrors that advisory block in the route-profile
    execution-plan header
  - Generic `build_confidence_calibration()` behavior, ranking effect, route
    ranking, candidate scoring, and `no_trade` stayed unchanged
  - Added focused output coverage in `tests/test_confidence_calibration.py` and
    `tests/test_execution_plan.py`
  - Full suite: **310 passed**

### Task 5e: Decide whether advisory personal-history output needs artifact parity beyond execution plans

- Priority: P2
- Status: ready
- Relevant files: `runtime_reports.py`, `runtime_runner.py`, `README.md`,
  `ARCHITECTURE.md`
- Expected result: if roundtrip or chain summary artifacts also need the compact
  personal-history block, add that parity without touching ranking logic or
  turning personal history into a decision hook.

### Task 5f: Add an explicit and bounded personal decision layer

- Priority: P1
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Added `personal_history_policy` config validation in `config_loader.py` and
    the default policy block in `config.json`
  - Extended `confidence_calibration.py` with explicit personal-layer policy
    resolution, quality/sample-size guardrails, scoped segment indexes, and
    bounded explainable adjustments on `decision_overall_confidence`
  - Kept generic `build_confidence_calibration()` intact while adding a
    separate opt-in personal layer with modes `off`, `advisory`, `soft`, and
    `strict`
  - Wired the layer into `runtime_runner.py` and the relaxed-candidate path in
    `portfolio_builder.py`, then surfaced mode, fallback reason, and applied
    scoped effects in `execution_plan.py`
  - Added focused regression coverage in
    `tests/test_confidence_calibration.py`,
    `tests/test_execution_plan.py`, and `tests/test_character_context.py`
  - Full suite: **317 passed**

## P2

### Task 6: Extend regression coverage around confidence calibration and journal feedback loops

- Priority: P2
- Status: ready
- Relevant files: `confidence_calibration.py`, `journal_store.py`,
  `journal_models.py`, `runtime_runner.py`, `tests/`
- Expected result: calibration behavior remains explainable and safe as journal
  data grows, with targeted tests for scope selection, fallback behavior,
  personal-layer caps, and decision confidence application.

### Task 7: Add a first local web UI without touching trading logic

- Priority: P1
- Status: DONE
- Completed: 2026-03-07
- What was done:
  - Added `webapp/` with a local FastAPI app, Jinja2 templates, static assets,
    and small service modules for dashboard, analysis, journal, character, and
    config pages
  - Kept the CLI intact and reused existing Python modules instead of building a
    second trading core
  - Added `webapp/services/runtime_bridge.py` to run full analyses in-process
    through `runtime_runner.run_cli()` and render existing artifacts in the UI
  - Added `nullsec-trader-web` packaging entry point plus FastAPI/Jinja2
    dependencies
  - Added route-level web tests in `tests/test_webapp.py`

### Task 7b: Reduce runtime-bridge coupling for the web UI

- Priority: P2
- Status: ready
- Relevant files: `runtime_runner.py`, `webapp/services/runtime_bridge.py`,
  `webapp/services/analysis_service.py`, `tests/test_webapp.py`
- Expected result: replace some stdout/artifact parsing in the web analysis path
  with a smaller structured runtime service API, without rewriting CLI behavior
  or duplicating trading logic.

### Task 7c: Keep local journal schema migration robust for UI and CLI entry points

- Priority: P1
- Status: DONE
- Completed: 2026-03-08
- What was done:
  - Fixed `journal_store.initialize_journal_db()` so older local journal DBs
    are migrated before reconciliation-related indexes are created
  - Prevented the local web dashboard from failing with `sqlite3.OperationalError:
    no such column: reconciliation_status` on pre-migration caches
  - Added a regression test in `tests/test_journal.py` for legacy schema upgrade

### Task 7d: Fix web UI crashes and silent data mismatches

- Priority: P0
- Status: DONE
- Completed: 2026-03-08
- What was done:
  - Fixed `GET /analysis` returning 500 due to `data.config.risk_profile.name`
    in `analysis.html`; config dict does not have a `risk_profile` key.
    Added `default_profile_name` to `get_analysis_form_data()` in
    `analysis_service.py` and updated the template to use that field.
  - Fixed `dashboard.html` journal summary stats always showing 0 because
    template field names (`total_entries`, `open_entries`, `closed_entries`)
    did not match real service output (`entries_total`, `open_count`,
    `closed_count`).
  - Added `try/except (ValueError, TypeError)` guards around
    `float(cargo_m3_raw)` and `parse_isk(budget_isk_raw)` in
    `analysis_service.run_analysis()` so invalid user input returns a visible
    error instead of a 500.
  - Updated `_analysis_form()` test fixture in `tests/test_webapp.py` to
    match real service output (added `default_profile_name`, removed fake
    `config.risk_profile` struct that was masking the crash).
  - Full suite: **325 passed**; real HTTP check: all routes 200 OK.
