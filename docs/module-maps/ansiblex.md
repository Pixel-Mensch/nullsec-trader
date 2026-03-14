# Module Map: ansiblex.py

## Purpose

Small helper module for optional internal ansiblex travel. It parses the
directed source-of-truth file, builds a narrow gate/ansiblex travel graph for
route-chain systems, and returns presentation-ready travel metadata plus
additive logistics cost.

## Responsibilities

- parse directed `FROM -> TO` ansiblex edges from `docs/Ansis.txt`
- ignore blank lines and simple inline comments without inventing new syntax
- keep edges directed only; no automatic reverse bridges
- resolve a small internal travel graph from `route_chain.legs[].system`
- compute additive ansiblex logistics cost from ship mass, LO price, and
  optional toll settings
- return travel summary, travel legs, gate/ansiblex counts, and ansiblex cost
  without touching route-search scoring

## Inputs

- `cfg["ansiblex"]`
- `cfg["route_chain"]["legs"]`
- source/destination labels or systems
- `docs/Ansis.txt` or an override path from config

## Outputs

- resolved ansiblex config with defaults
- parsed directed edge list
- per-jump cost breakdown
- route travel details:
  - `travel_summary`
  - `travel_path_legs`
  - `gate_leg_count`
  - `ansiblex_leg_count`
  - `ansiblex_logistics_cost_isk`
  - `used_ansiblex`

## Key Files

- `ansiblex.py`
- `docs/Ansis.txt`
- `shipping.py`
- `tests/test_ansiblex.py`

## Important Entry Points

- `resolve_ansiblex_cfg()`
- `parse_ansiblex_edge_line()`
- `load_ansiblex_edges()`
- `compute_ansiblex_jump_cost()`
- `resolve_route_travel_details()`

## Depends On

- `location_utils.py`
- `config.json`
- `shipping.py` as the main caller

## Used By

- `shipping.py`
- `nullsectrader.py`
- focused travel/cost tests

## Common Change Types

- adjust parser robustness while keeping directed semantics
- tune additive cost defaults or validation
- extend the small travel summary payload consumed by plans or browser results
- update file-path resolution for the source-of-truth edge file

## Risk Areas

- easy to accidentally infer bidirectional edges or over-normalize labels
- easy to drift into a second routing engine if pathfinding becomes too smart
- distance data is currently topology-only, so cost realism is intentionally
  approximate

## Tests

- `tests/test_ansiblex.py`
- `tests/test_shipping.py`
- `tests/test_execution_plan.py`
- `tests/test_webapp.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `ansiblex.py`
3. `shipping.py`
4. `tests/test_ansiblex.py`
5. output consumers only if required

## When This File Must Be Updated

Update this module map when the ansiblex file format, cost model seam, or main
travel outputs materially change.
