# Session Handoff

Date: 2026-03-14 (session 30 ansiblex corridor travel layer)
Branch: `dev`

## Completed This Session

Implemented a small directed ansiblex expansion for internal corridor travel
without rewriting route-search scoring or breaking the corridor-ordered
presentation work from the previous block.

## Root Cause

- internal `internal_self_haul` routes previously had only gate-chain context
  plus generic route costs, so realistic alliance corridor travel options were
  not visible
- route output showed total transport cost, but not whether a route used gate
  vs ansiblex travel or how much profit changed before/after those logistics
- the repository already had corridor ordering and visibility guarantees for
  longer spans like `O4T -> 1ST` and Jita connectors; the new travel layer had
  to preserve that behavior instead of replacing it

## What Changed

- `ansiblex.py`
  - added a small parser for directed `FROM -> TO` edges from `docs/Ansis.txt`
  - ignores blank lines and simple comments, but does not invent reverse edges
  - builds a small internal travel graph from `route_chain.legs[].system`
  - computes additive ansiblex logistics cost from ship mass, LO price, and
    optional toll settings
- `config.json`, `config_loader.py`
  - added the minimal `ansiblex` config block and validation
  - route-chain legs now map labels to explicit system names for corridor
    travel resolution
- `shipping.py`
  - keeps existing gate/external transport behavior
  - augments internal route context with travel summary, gate/ansiblex counts,
    visible travel legs, and ansiblex logistics cost
  - folds ansiblex logistics cost additively into transport cost instead of
    changing profit/scoring formulas
- `runtime_runner.py`, `journal_models.py`
  - preserve travel metadata plus profit before vs after logistics on final
    route results and `trade_plan_*.json`
- `execution_plan.py`
  - shows concise travel lines, gate/ansiblex counts, ansiblex logistics cost,
    and profit before vs after logistics
  - only lists detailed travel legs when ansiblex is involved or detail mode is
    requested
- `webapp/services/analysis_service.py`, `webapp/templates/results.html`
  - surface the same compact ansiblex travel summary in browser results
- `tests/test_ansiblex.py`
  - adds focused regression for parser directionality, no automatic reverse
    edges, cost calculation, travel metadata, and additive cost carry-through
- `tests/test_route_search.py`, `tests/test_execution_plan.py`,
  `tests/test_webapp.py`, `tests/test_config.py`
  - verify O4T -> 1ST and Jita visibility still hold, execution plans render
    ansiblex details, web results show ansiblex info, and config validation
    rejects invalid toll modes

## Tests And Verification

- `python -m pytest -q tests/test_ansiblex.py tests/test_config.py tests/test_route_search.py tests/test_runtime_runner.py tests/test_shipping.py tests/test_execution_plan.py tests/test_webapp.py`
  - **183 passed**
- `python scripts/quality_check.py`
  - **195 passed**

## Remaining Limits

- the ansiblex layer is intentionally small and private to the repo config: it
  uses `docs/Ansis.txt` as topology source of truth and does not attempt a full
  alliance logistics simulation
- `docs/Ansis.txt` carries no real LY distances, so the current default uses a
  constant per-ansiblex-leg distance estimate for fuel math
- only route-chain systems explicitly mapped through `route_chain.legs[].system`
  participate in the internal gate/ansiblex corridor graph
- route-search ranking, route score formulas, and corridor grouping logic were
  left intentionally unchanged

## Next Recommended Task

If travel realism needs to improve later, decide explicitly whether to add a
trustworthy distance source for ansiblex edges. Keep that as a data-layer
upgrade, not a scoring rewrite.

## Files Touched

- `ansiblex.py`
- `config.json`
- `config_loader.py`
- `shipping.py`
- `runtime_runner.py`
- `journal_models.py`
- `execution_plan.py`
- `webapp/services/analysis_service.py`
- `webapp/templates/results.html`
- `nullsectrader.py`
- `tests/test_ansiblex.py`
- `tests/test_config.py`
- `tests/test_execution_plan.py`
- `tests/test_route_search.py`
- `tests/test_webapp.py`
- `scripts/quality_check.py`
- `README.md`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
