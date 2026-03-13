# Session Handoff

Date: 2026-03-13 (session 20 execution-plan consistency cleanup)
Branch: `dev`

## Completed This Session

Fixed the current execution-plan consistency issues around visible profile
rules, alternative-route totals, weak internal nullsec routes, invalid volume
handling, and misleading output wording.

## Root Cause

- profile restrictions were partly enforced too early or only in one runtime
  path; final pick-level checks were not shared between `run_route()` and
  `run_route_wide_leg()`
- cargo-fill had its own looser per-item budget share cap, so a fill pick could
  exceed the visible profile `Max Budget/Item`
- the execution-plan footer summed alternative routes as if they were one
  simultaneous plan
- internal `internal_self_haul` routes had no separate operational route-level
  floor, so technically positive but practically weak nullsec routes stayed
  actionable
- missing or invalid volume could still drift through as a usable pick path via
  fallback normalization instead of becoming an explicit rejection
- prune reasons and warning wording were too coarse for the now-restored
  internal-route and profile-filter behavior

## What Changed

- `risk_profiles.py`
  - profile filter metadata is now carried explicitly for final pick-level
    enforcement
  - `filter_picks_by_profile()` now hard-gates expected profit, profit density,
    confidence, and max budget/item and records rejection codes
  - cargo-fill item share is clamped to the visible effective
    `max_item_share_of_budget`
- `portfolio_builder.py`
  - final built picks now respect `min_expected_profit_isk`
  - zero-volume candidates are skipped
  - cargo fill also respects the same final expected-profit logic
- `runtime_clients.py` and `candidate_engine.py`
  - invalid or missing volume now stays invalid (`0.0`) instead of silently
    becoming a positive fallback
  - candidate generation rejects such entries via `invalid_volume`
- `runtime_runner.py`
  - added shared post-build profile filtering for both route builders
  - added clearer prune-reason bucketing
  - added internal-self-haul operational profit floor handling
  - route results now refresh totals after pick filtering instead of leaving
    stale pick/route aggregates
- `execution_plan.py`
  - header now prefers resolved runtime profile params when present
  - output text was cleaned up to remove mojibake / ambiguous section labels
  - route summary now shows the internal-route operational floor and any
    suppressed low-profit route
  - footer now separates `BEST ACTIONABLE ROUTE` from
    `AGGREGATE ACROSS DISPLAYED ROUTE ALTERNATIVES`
- `config.json`, `config_loader.py`, `route_search.py`
  - added and validated `route_search.internal_self_haul_min_expected_profit_isk`
    (default `2,000,000`)
- tests
  - expanded coverage for pick-level profile enforcement, cargo-fill caps,
    invalid volume, aggregate output semantics, and runtime helper behavior

## Tests And Verification

- Targeted core/runtime/output regression:
  - `pytest -q tests/test_risk_profiles.py tests/test_portfolio.py tests/test_execution_plan.py tests/test_runtime_runner.py tests/test_config.py tests/test_shipping.py`
    -> **211 passed**
- Adjacent explainability / ranking / no-trade / web regression:
  - `pytest -q tests/test_explainability.py tests/test_route_search.py tests/test_no_trade.py tests/test_webapp.py`
    -> **61 passed**

## Remaining Limits

- chain/roundtrip summary artifacts outside `write_execution_plan_profiles()`
  still do not mirror the same best-route-vs-aggregate semantics
- invalid volume is now safely rejected, but there is still no proactive
  volume-backfill workflow beyond the existing caches / live lookup
- an unrelated pre-existing local modification in `location_utils.py` was left
  untouched on purpose

## Files Touched

- `candidate_engine.py`
- `config.json`
- `config_loader.py`
- `execution_plan.py`
- `explainability.py`
- `nullsectrader.py`
- `portfolio_builder.py`
- `risk_profiles.py`
- `route_search.py`
- `runtime_clients.py`
- `runtime_runner.py`
- `tests/test_config.py`
- `tests/test_execution_plan.py`
- `tests/test_portfolio.py`
- `tests/test_risk_profiles.py`
- `tests/test_runtime_runner.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
