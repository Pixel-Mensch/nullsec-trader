# Session Handoff

Date: 2026-03-08 (session 14 live/replay/web verification)
Branch: `dev`

## Completed This Session

### Real live run -> replay run -> web verification

Performed a full local verification cycle instead of a code-only review:

- ran a focused real live CLI route-search flow with local ESI credentials
- wrote a fresh replay snapshot from that live run
- reran the exact same flow in replay mode against that snapshot
- compared live vs replay artifacts and manifest data
- started the real FastAPI app under `uvicorn`
- exercised `/analysis` and `/analysis/run` over HTTP in replay and live mode

### Fixes

**Bug 1 - replay identity drift**

- Root cause: `plan_id` used wall-clock time, so identical replay runs produced
  different `plan_id` and `pick_id` values even when snapshot and inputs were
  identical.
- Fix: `runtime_runner.py` now derives a deterministic plan-id seed from the
  snapshot payload plus runtime inputs. Live and replay now keep the same
  `plan_id` / `pick_id` set for the same snapshot+input combination.

**Bug 2 - manifest serialized `instant` exit price as 0**

- Root cause: `journal_models.build_trade_plan_manifest()` preferred
  `target_sell_price` even when it existed but was `0.0` for `instant` picks,
  so `sell_avg` was never used as fallback.
- Fix: added a proper sell-price resolver. `instant` picks now export the real
  executable exit price in `proposed_sell_price`.

**Bug 3 - web runtime bridge lost live replay snapshot path**

- Root cause: `webapp/services/runtime_bridge.py` only parsed
  `Snapshot geschrieben: ...`, not `Replay-Snapshot geschrieben: ...`.
- Fix: the bridge now captures both forms, so live browser runs show the real
  snapshot path and include it in the result payload.

**Bug 4 - browser server killed long `/analysis/run` requests**

- Root cause: `webapp/app.py` used only heartbeat timestamps for auto-shutdown.
  Long analysis POSTs had no concurrent heartbeat and the watcher could exit
  the process mid-request.
- Fix: the app now tracks active requests and suppresses auto-shutdown while a
  request is still in flight.

**Bug 5 - browser route cards hid important route-level metrics**

- Fix: the trade-plan manifest now includes route budget/cargo/cost metrics and
  warning lines; `analysis_service.py` and `results.html` now surface them in
  the browser.

## Tests And Verification

- Targeted regression set:
  `python -m pytest -q tests/test_journal.py tests/test_integration.py tests/test_webapp.py`
  -> **32 passed**
- Full suite:
  `python -m pytest -q`
  -> **330 passed**

### Real runtime checks

- Focused live CLI run: **success**
  - actionable route: `o4t -> jita_44`
  - route count: 2
  - pick count: 3
  - expected realized profit: about **240.66m ISK**
  - replay snapshot written to:
    `C:\Users\marck\AppData\Local\Temp\nullsec_live_replay_snapshot_focused.json`
- Replay CLI run against that snapshot: **success**
  - same `plan_id` as live run
  - same `pick_id` set as live run
  - execution plan / leaderboard differ only in their artifact timestamp lines
- Real HTTP replay run: **GET /analysis 200**, **POST /analysis/run 200**
  - browser result matched CLI replay plan id and route metrics
- Real HTTP live run: **POST /analysis/run 200** after ~216s
  - browser stayed alive for the full request
  - result page showed the written replay snapshot path

## New Regression Coverage

- `tests/test_integration.py`
  - real-data replay fixture stays actionable and keeps the expected pick set
  - repeated replay runs keep the same stable `plan_id` / `pick_id` values
- `tests/test_journal.py`
  - manifest falls back to `sell_avg` when `target_sell_price` is `0.0`
- `tests/test_webapp.py`
  - runtime bridge parses `Replay-Snapshot geschrieben: ...`
  - web auto-shutdown waits until no active request is running

## New Fixture

- Added:
  `tests/fixtures/replay_live_focused_o4t_jita_20260308.json`
- Purpose:
  compact replay regression based on real live market data captured on
  2026-03-08 for the focused O4T <-> Jita route test

## Known Limits

- Full browser analysis still depends on stdout/artifact parsing from
  `runtime_runner.run_cli()` rather than a structured runtime service API.
- Stable plan IDs now intentionally reuse the same canonical
  `trade_plan_<plan_id>.json` path for identical snapshot+input runs. That is
  good for reproducibility and journal parity, but the canonical trade-plan
  file is overwritten when the same plan is recomputed.
- The focused live verification used a local overlay config to keep the run
  practical. The default operator config is broader and can take several
  minutes while fetching extra markets.

## Next Recommended Task

- Reduce `webapp/services/runtime_bridge.py` dependence on stdout parsing by
  exposing a small structured runtime result API from `runtime_runner.py`
- Decide whether the canonical stable `trade_plan_<plan_id>.json` path should
  also get an optional run-scoped copy for easier side-by-side artifact review

## Files Touched

- `journal_models.py`
- `runtime_runner.py`
- `webapp/app.py`
- `webapp/services/analysis_service.py`
- `webapp/services/runtime_bridge.py`
- `webapp/templates/results.html`
- `tests/test_integration.py`
- `tests/test_journal.py`
- `tests/test_webapp.py`
- `tests/fixtures/replay_live_focused_o4t_jita_20260308.json`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
