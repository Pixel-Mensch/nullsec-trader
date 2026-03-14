# Session Handoff

Date: 2026-03-14 (session 33 web active character seam)
Branch: `dev`

## Completed This Session

Implemented a small single-user active-character seam for the local web UI.
The browser can now switch the active character at any time, and that switch
really changes the token/profile basis used by later analysis and journal /
reconcile views. The journal page also now surfaces active-character sell-order
context, and the `trade_plan_*.json` manifest no longer drops route/transport
confidence to `0.0` when the route record itself omitted those fields.

## Root Cause

- the web UI previously read only the one current active character/token state
  from the existing runtime paths, so there was no safe browser seam to pivot
  analysis and journal views between locally known characters
- runtime analysis, character status, and journal/reconcile already depended on
  the same active token/profile files, so the smallest correct solution was to
  switch those files deliberately instead of adding a parallel browser-only
  character layer
- the confidence mismatch came from `trade_plan_*.json` serializing raw route
  fields directly even when text-plan / leaderboard confidence was derived
  later from `route_search.summarize_route_for_ranking()`

## What Changed

- `webapp/services/active_character_service.py`
  - new small single-user registry of locally saved characters under
    `cache/character_context/`
  - captures currently active characters into per-character saved slots
  - activates a chosen character by copying its saved token/profile into the
    existing active runtime paths
- `webapp/routes/pages.py`
  - injects global active-character switch state into page templates
  - adds `POST /character/activate` with safe redirect-back behavior
  - normalizes switch return targets so switching from `/analysis/run` returns
    to `/analysis` instead of a POST-only endpoint
- `webapp/services/character_service.py`
  - captures characters after login/sync and exposes saved local characters to
    the character page
- `webapp/services/journal_service.py`
  - adds active-character sell-order summary from the cached character profile
  - matches those sell-order types against local journal entries by
    `item_type_id` and optional `character_id`
- `webapp/templates/base.html`
  - adds the global `Active character` switcher in the header
- `webapp/templates/analysis.html`
  - states that new analyses use the active local character slot
- `webapp/templates/journal.html`
  - states that journal/reconcile use the active slot and shows active sell
    orders for that character
- `webapp/templates/character.html`
  - lists locally saved characters and lets the operator activate one directly
- `webapp/static/css/app.css`
  - styles the new switcher and compact sell-order / saved-character blocks
- `journal_models.py`
  - uses derived route-summary confidence as a manifest fallback when raw route
    confidence fields are absent or zero
- `tests/test_active_character_service.py`
  - verifies that character activation swaps the real active token/profile
    files and clears stale profile state when needed
- `tests/test_webapp.py`
  - covers the global switcher, redirect-back behavior, analysis basis note,
    journal sell-order block, and character saved-slot view
- `tests/test_journal.py`
  - covers the confidence fallback in `trade_plan_*.json`

## Tests And Verification

- `python -m pytest -q tests/test_webapp.py tests/test_active_character_service.py tests/test_journal.py tests/test_runtime_runner.py tests/test_execution_plan.py`
  - **118 passed**

Additional verification from the prior live/replay check still relevant here:

- the exact live command
  `python .\main.py --profile small_wallet_hub_safe --cargo-m3 12000 --budget-isk 800m --compact`
  wrote the live snapshot but did not finish after more than 20 minutes
- the direct replay against that fresh snapshot completed successfully and
  showed the expected safe-route output

## Remaining Limits

- the active-character seam is intentionally local and single-user; it is not
  a multi-user/session architecture and does not handle concurrent operators
- journal sell-order visibility is intentionally narrow: cached open orders are
  matched against local journal entries by `item_type_id` and optional
  `character_id`, not by a deeper order-to-trade linkage model
- the slow live-run path is still only localized at a coarse level: snapshot
  creation happened quickly, so the long-running part appears to be later in
  the live path, but this session did not perform a full runtime profiling pass

## Next Recommended Task

Narrow the slow live-run path after snapshot creation: identify whether the
remaining long-running work is cache/type enrichment, extra live fetch work, or
later post-fetch processing, without doing a broad performance refactor first.

## Files Touched

- `webapp/services/active_character_service.py`
- `webapp/routes/pages.py`
- `webapp/services/character_service.py`
- `webapp/services/journal_service.py`
- `webapp/templates/base.html`
- `webapp/templates/analysis.html`
- `webapp/templates/journal.html`
- `webapp/templates/character.html`
- `webapp/static/css/app.css`
- `journal_models.py`
- `tests/test_active_character_service.py`
- `tests/test_webapp.py`
- `tests/test_journal.py`
- `README.md`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `SESSION_HANDOFF.md`
- `docs/module-maps/webapp.md`
