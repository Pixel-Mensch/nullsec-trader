# Session Handoff

Date: 2026-03-14 (session 34 web active profile + internal route diagnosis)
Branch: `dev`

## Completed This Session

Implemented a small single-user active-profile seam for the local web UI and
tightened the explanation path for empty internal nullsec routes.

The browser can now switch the active built-in risk profile at any time from
the header. New browser analysis runs default to that selected profile through
the existing CLI/runtime path, so the change is not cosmetic. The internal
route output path now also distinguishes profile-side removals from broader
candidate scarcity more clearly and carries a short diagnosis string into text
artifacts and browser result cards.

## Root Cause

- the web UI already exposed available built-in profiles in the analysis form,
  but it had no persistent active-profile seam; each run only used the form
  field or config fallback
- real replay artifacts showed that many empty internal nullsec routes are not
  failing in transport wiring: `internal_self_haul` is already recognized
  correctly, but candidate generation often ends on weak books,
  non-positive-profit paths, or unreliable planned-sell orderbooks
- a smaller second class of internal routes did produce at least one candidate,
  but those survivors were later removed by the active profile on confidence or
  quality while the coarse final prune label still looked like a profit-floor
  failure

## What Changed

- `webapp/services/active_profile_service.py`
  - new tiny single-user web state for the active built-in risk profile under
    `cache/web_active_profile.json`
  - validates selections against `risk_profiles.BUILTIN_PROFILES`
- `webapp/routes/pages.py`
  - injects global active-profile switch state into templates
  - adds `POST /profile/activate` with redirect-back behavior parallel to the
    character switcher
- `webapp/services/analysis_service.py`
  - analysis form now knows the active profile and preselects it
  - browser runs now fall back to the active profile when the form does not
    explicitly override it
- `webapp/templates/base.html`
  - adds the global `Active profile` switcher in the header
- `webapp/templates/analysis.html`
  - states which profile is currently active and makes the one-run override in
    the analysis form explicit
- `webapp/templates/results.html`
  - surfaces the short route diagnosis on no-trade route cards
- `webapp/static/css/app.css`
  - styles the stacked character/profile switchers
- `runtime_runner.py`
  - final prune-reason derivation now prefers post-search profile buckets when
    candidates did pass search and were then removed by profile rules
  - adds short route-failure hints for transport block, internal operational
    floor, profile-side removals, thin books, unreliable planned pricing, and
    broad non-positive-profit candidate pools
- `execution_plan.py`
  - renders concise `diagnosis` / `route_diagnosis` lines for pruned routes and
    near misses
- `journal_models.py`
  - carries route-failure hints/summary into `trade_plan_*.json` so browser
    surfaces stay aligned with runtime text output
- `tests/test_active_profile_service.py`
  - covers persistence, config fallback, rejection of invalid profiles, and
    builtin-profile list parity
- `tests/test_webapp.py`
  - covers the global profile switcher, redirect-back behavior, active-profile
    rendering, and browser-run fallback to the active profile
- `tests/test_runtime_runner.py`
  - covers profile-aware prune-reason preference and short route-diagnosis hints
- `tests/test_execution_plan.py`
  - covers rendering of pruned-route diagnosis text

## Tests And Verification

- `python -m pytest -q tests/test_webapp.py tests/test_active_profile_service.py tests/test_runtime_runner.py tests/test_execution_plan.py tests/test_no_trade.py tests/test_journal.py tests/test_runtime_reports.py`
  - **165 passed**

Runtime evidence used for the internal-route diagnosis in this session:

- replay on the fresh 2026-03-14 snapshot with `--profile balanced` finished
  successfully and showed mixed internal behavior:
  some internal routes still had `0 profitable trade candidates found`,
  while at least one internal route produced a candidate that was later removed
  by the profile on confidence
- the strongest repeated reject reasons in the inspected candidate dumps were
  `non_positive_profit`, `planned_price_unreliable_orderbook`,
  `orderbook_window_units_too_low`, and `min_depth_units`

## Remaining Limits

- the active-profile seam is intentionally local and single-user; it is not a
  multi-user/session design and does not change CLI/profile precedence outside
  the web flow
- this session did not relax internal-market candidate thresholds or route
  scoring; it improved diagnosis only because the evidence did not justify a
  broader safe market-logic change yet
- the slow live-run path is still only localized at a coarse level: snapshot
  creation finished quickly, so the long-running work appears to be later in
  the live path, but this session did not profile that path further

## Next Recommended Task

Narrow the slow live-run path after snapshot creation, then decide whether
internal nullsec coverage needs a truly safe candidate-stage tweak or whether
the current honest diagnosis is sufficient.

## Files Touched

- `webapp/services/active_profile_service.py`
- `webapp/routes/pages.py`
- `webapp/services/analysis_service.py`
- `webapp/templates/base.html`
- `webapp/templates/analysis.html`
- `webapp/templates/results.html`
- `webapp/static/css/app.css`
- `runtime_runner.py`
- `execution_plan.py`
- `journal_models.py`
- `tests/test_active_profile_service.py`
- `tests/test_webapp.py`
- `tests/test_runtime_runner.py`
- `tests/test_execution_plan.py`
- `README.md`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `SESSION_HANDOFF.md`
- `docs/module-maps/webapp.md`
- `docs/module-maps/runtime_runner.md`
- `docs/module-maps/execution_plan.md`
