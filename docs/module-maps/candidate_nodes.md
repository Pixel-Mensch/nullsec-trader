# Module Map: candidate_nodes.py

## Purpose

Small helper for config-driven watch nodes. It keeps `station_candidate`,
`market_candidate`, and `corridor_checkpoint` separate and annotates routes
with descriptive metadata when they touch one of those configured nodes.

## Responsibilities

- resolve the `candidate_nodes` config block
- validate and normalize labels and aliases into match tokens
- keep node kinds explicit instead of implicitly treating every system as a
  station or trade hub
- annotate routes with start/end/corridor hits
- keep the whole seam display-only; no route scoring or hub ranking

## Inputs

- `cfg["candidate_nodes"]`
- route dicts with `source_label`, `dest_label`, `travel_source_system`,
  `travel_dest_system`, and optional `travel_path_legs`

## Outputs

- resolved candidate-node config
- route annotation payload:
  - `candidate_nodes`
  - `candidate_node_summary`

## Key Files

- `candidate_nodes.py`
- `config.json`
- `runtime_runner.py`
- `tests/test_candidate_nodes.py`

## Important Entry Points

- `resolve_candidate_nodes_cfg()`
- `annotate_route_candidate_nodes()`

## Depends On

- `location_utils.py`

## Used By

- `runtime_runner.py`
- `nullsectrader.py`
- output consumers through runtime/manifests

## Common Change Types

- adjust validation/normalization of watch-node config
- add or rename supported node kinds
- extend the descriptive route-annotation payload

## Risk Areas

- easy to blur watch nodes with real station/location semantics
- easy to smuggle ranking assumptions into what should stay a descriptive seam
- alias matching can overmatch if normalization becomes too loose

## Tests

- `tests/test_candidate_nodes.py`
- `tests/test_config.py`
- `tests/test_execution_plan.py`
- `tests/test_webapp.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `candidate_nodes.py`
3. `config.json`
4. the output consumer you need to touch
5. relevant tests

## When This File Must Be Updated

Update this module map when the supported candidate-node kinds, matching
strategy, or main route-annotation outputs materially change.
