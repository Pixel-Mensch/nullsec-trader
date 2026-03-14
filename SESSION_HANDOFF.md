# Session Handoff

Date: 2026-03-14 (session 26 output honesty + tail cleanup)
Branch: `dev`

## Completed This Session

Fixed the remaining output-honesty and weak-tail-pick issues in the
route-profile path without weakening the recent anti-bait / market-quality
work.

## Root Cause

- `execution_plan.py` rendered internal-route operational floor lines whenever
  `operational_profit_floor_isk` existed, even if the route used external
  shipping
- PRICE-SENS picks only emitted a warning, not the actual profit-basis context,
  so the shown sell quote and the shown profit looked inconsistent to a human
- the existing post-selection cleanup seam favored clear score wins, but could
  still keep a weak speculative / price-sensitive tail pick when route quality
  improved and profit share stayed small, yet the score change was only near-flat

## What Changed

- `execution_plan.py`
  - added small helpers for displayed profit, visible-book profit proxy,
    conservative executable profit proxy, retention, and internal-route
    metadata applicability
  - route summaries, leaderboard pruned entries, and no-trade near-misses now
    show `Internal Route Floor` / `Internal Route Note` only for actual
    `internal_self_haul` routes
  - price-sensitive or materially repriced picks now show:
    - quote basis
    - visible-book profit proxy
    - conservative executable profit proxy
    - displayed profit basis used in the plan
    - retention and implied net-exit basis
- `runtime_runner.py`
  - `_apply_post_selection_route_mix_cleanup()` now also considers explicit
    weak-tail signals (`speculative`, `price-sensitive`,
    `fragile-market-quality`, `weak-profit-retention`, `low-confidence`,
    `elevated-manip-risk`) when profit share stays small and score retention
    remains high
  - `_apply_internal_self_haul_operational_filter()` now clears internal-route
    floor metadata on external routes instead of carrying it forward
- tests
  - added focused coverage for hidden external floor lines, visible internal
    floor lines, price-basis transparency, speculative price-sensitive tail
    removal, and replay regression against known bait picks

## Tests And Verification

- focused regression:
  - `pytest -q tests/test_execution_plan.py tests/test_portfolio.py tests/test_route_search.py tests/test_integration.py tests/test_runtime_runner.py`
    -> **129 passed**
- new coverage proves:
  - external shipping routes do not render internal-route floor/note lines
  - internal self-haul routes still surface floor, suppressed profit, and note
  - PRICE-SENS picks expose the real profit basis in plan text
  - weak speculative / price-sensitive tail picks can be dropped while strong
    core picks remain
  - the focused replay fixture still keeps the known bait picks out

## Remaining Limits

- the new price-basis block explains the conservative basis via profit proxies
  and implied net-exit math; it still does not persist a separately named
  repriced unit sell quote for every path
- the tail cleanup remains intentionally narrow: it still refuses removals that
  would materially damage route score retention or break minimum strong-pick
  expectations
- an unrelated pre-existing local modification in `location_utils.py` remains
  intentionally untouched

## Files Touched

- `execution_plan.py`
- `runtime_runner.py`
- `tests/test_execution_plan.py`
- `tests/test_route_search.py`
- `tests/test_runtime_runner.py`
- `tests/test_integration.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
