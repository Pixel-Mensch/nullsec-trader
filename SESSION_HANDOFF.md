# Session Handoff

Date: 2026-03-13 (session 23 replay quality calibration)
Branch: `dev`

## Completed This Session

Calibrated the already-tightened market-quality / anti-bait logic against real
replay and execution-plan artifacts so robust trades stop being penalized
twice, while the earlier thin-book / fake-spread removals stay intact.

## Root Cause

- replay evidence showed the remaining over-calibration was narrow:
  `DEPTH_COLLAPSE` and `ORDERBOOK_CONCENTRATION` were common on still-robust
  survivors, but `market_quality_score` multiplied both penalties before
  `candidate_engine.py` multiplied liquidity/exit confidence by that same score
  again
- that double hit made decent instant survivors look weaker than the artifact
  evidence justified
- the clearly bad historical cases were driven by stricter signals
  (`THIN_TOP_OF_BOOK`, `UNUSABLE_DEPTH`, `FAKE_SPREAD_RISK`), not by those
  generic structural flags alone

## What Changed

- `market_plausibility.py`
  - softened only the generic quality multipliers:
    `DEPTH_COLLAPSE 0.90 -> 0.95`
    `ORDERBOOK_CONCENTRATION 0.92 -> 0.96`
- `candidate_engine.py`
  - replaced the direct
    `quality_conf_penalty = market_quality_score` coupling with a softer blend
    so candidate confidence is no longer effectively double-capped before the
    final market-quality cap applies
- `tests/test_core.py`
  - added coverage proving a robust book with only
    `DEPTH_COLLAPSE` + `ORDERBOOK_CONCENTRATION` stays actionable and keeps a
    healthy `market_quality_score`
- `tests/test_execution_plan.py`
  - added coverage showing a robust instant pick in that calibrated quality
    band still lands as `MANDATORY`
- `tests/test_route_search.py`
  - added a healthy-route confidence regression so the market-quality cap stays
    realistic instead of collapsing good single-pick routes
- `tests/test_integration.py`
  - updated the focused replay fixture expectation to the new stable real pick
    set of
    `Noise-25 'Needlejack' Filament` and
    `Polarized Heavy Neutron Blaster`

## Replay / Artifact Verification

- focused replay fixture:
  `tests/fixtures/replay_live_focused_o4t_jita_20260308.json`
  - actionable route stayed `o4t -> jita_44`
  - stable pick set stayed at 2 picks:
    `Noise-25 'Needlejack' Filament`,
    `Polarized Heavy Neutron Blaster`
  - execution plan now shows `Route Confidence: 0.83`
    with `2 MANDATORY, 0 OPTIONAL, 0 SPECULATIVE`
  - `Large Warhead Calefaction Catalyst II` stayed out
- narrow `replay_snapshot.json` audit on `o4t -> jita_44` and `jita_44 -> cj6`
  - bad historical names such as
    `IFFA Compact Damage Control`,
    `Large Warhead Calefaction Catalyst II`,
    `Heavy Gremlin Compact Energy Neutralizer`,
    `Drone Mutaplasmid Residue`
    did not return
  - robust survivors such as
    `Noise-25 'Needlejack' Filament`,
    `Medium Hybrid Locus Coordinator II`,
    `AV-Composite Molecular Condenser`
    remained actionable / mandatory where the artifacts supported it

## Tests And Verification

- focused regression:
  - `pytest -q tests/test_core.py tests/test_execution_plan.py tests/test_portfolio.py tests/test_route_search.py tests/test_integration.py`
    -> **132 passed**
- manual replay audit:
  - focused fixture run on `replay_live_focused_o4t_jita_20260308.json`
  - narrow route-search run on local `replay_snapshot.json`

## Remaining Limits

- this session did not add new market data or new scoring families; it only
  calibrated existing thresholds and the existing confidence seam
- route confidence can still drop when a selected route keeps a weak optional
  pick, because `route_search.py` intentionally caps by average pick market
  quality across the full selected route mix
- an unrelated pre-existing local modification in `location_utils.py` remains
  intentionally untouched

## Files Touched

- `market_plausibility.py`
- `candidate_engine.py`
- `tests/test_core.py`
- `tests/test_execution_plan.py`
- `tests/test_route_search.py`
- `tests/test_integration.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
