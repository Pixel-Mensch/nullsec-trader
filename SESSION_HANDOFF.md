# Session Handoff

Date: 2026-03-13 (session 24 route-mix cleanup)
Branch: `dev`

## Completed This Session

Added a narrow post-selection route-mix cleanup so weak optional/speculative
add-on picks can be removed from the final route only when they clearly hurt
route confidence / route quality more than they help.

## Root Cause

- `portfolio_builder.py` optimizes pick-level selection, cargo fill, and local
  search before the final route summary exists
- `route_search.py` then evaluates the whole selected mix via average pick
  confidence / market quality, so a weak low-impact add-on can still depress a
  good route after final selection
- this is a final-mix problem, not a candidate-generation problem, so a small
  post-selection pass is the right seam

## What Changed

- `runtime_runner.py`
  - added `_apply_post_selection_route_mix_cleanup()` and called it from
    `_finalize_route_result_runtime_state()`
  - cleanup only evaluates non-mandatory picks
  - removal requires:
    - small removed profit share
    - material recovery in route confidence or market quality
    - route score improvement, or near-identical route score for very small
      add-ons with clear quality drag
  - cleanup will not:
    - remove robust mandatory picks
    - drop below the current profile's minimum strong-pick count
    - push an internal self-haul route below its operational route floor
  - removed picks are recorded in `route_mix_cleanup_removed_picks` and
    `route_mix_cleanup_notes`
- `execution_plan.py`
  - execution plans now surface route-mix cleanup notes in the route summary /
    warnings block
  - route leaderboard now prints `route_mix_cleanup:` lines when cleanup ran
- `nullsectrader.py`
  - exported the cleanup helper for focused tests

## Replay / Artifact Verification

- motivating artifact before this change:
  - narrow `replay_snapshot.json` O4T->Jita artifact showed
    `Noise-5 'Needlejack' Filament` as an optional add-on with only ~5.8m
    expected profit and much weaker confidence than the two core picks, while
    the route sat at `Route Confidence: 0.66`
- current narrow rerun after this change:
  - `o4t -> jita_44` now came in at `Route Confidence: 0.72`
  - cleanup did not fire on that rerun because the route no longer crossed the
    new removal threshold; this is intentional because the pass is meant for
    clear trade-off cases, not for cosmetic beautification
- focused replay fixture stayed stable:
  - `o4t -> jita_44`
  - `Noise-25 'Needlejack' Filament`
  - `Polarized Heavy Neutron Blaster`

## Tests And Verification

- focused regression:
  - `pytest -q tests/test_runtime_runner.py tests/test_execution_plan.py tests/test_route_search.py`
    -> **86 passed**
  - `pytest -q tests/test_no_trade.py tests/test_integration.py -k "replay_live_focused_fixture_keeps_real_pick_set or same_snapshot_keeps_stable_plan_and_pick_ids or no_trade"`
    -> **39 passed**
- new coverage proves:
  - a weak optional add-on is removed when route quality gains outweigh its
    small profit contribution
  - cleanup does not remove an optional pick if the active profile would lose a
    required second strong pick
  - execution plan and leaderboard surface cleanup notes

## Remaining Limits

- the cleanup is intentionally narrow and may not fire on every low-confidence
  optional pick; it only acts on clear small-share / quality-drag trade-offs
- current replay evidence did not produce a live cleanup removal after the
  latest market-quality calibration; the removal case is covered by targeted
  runtime tests built from the observed artifact pattern
- an unrelated pre-existing local modification in `location_utils.py` remains
  intentionally untouched

## Files Touched

- `runtime_runner.py`
- `execution_plan.py`
- `nullsectrader.py`
- `tests/test_runtime_runner.py`
- `tests/test_execution_plan.py`
- `tests/test_route_search.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
