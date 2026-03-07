# Nullsec Trader Tool

Python tool for EVE Online trade planning across concrete routes (not just price comparison).
It supports live ESI and replay snapshots, instant sell and planned sell, fees/taxes,
shipping costs, route search + leaderboard, strict mode, route-wide scans, and portfolio
building under budget/cargo limits.

## Runtime Architecture

- `main.py`: thin entrypoint only.
- `nullsectrader.py`: compatibility facade (`import nullsectrader as nst` remains stable).
- `legacy_core.py`: thin compatibility layer that re-exports runtime symbols.
- `legacy_runtime.py`: legacy orchestrator/runtime implementation.
- Extracted modules (`config_loader.py`, `shipping.py`, `route_search.py`, `portfolio_builder.py`, etc.)
  are the source of truth for externalized logic.
- Startup helper functions used by runtime live in `startup_helpers.py`.

## Start

### PowerShell helper (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode live
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode replay
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode live -SnapshotOnly
```

`run_trader.ps1` now uses CLI args (`--cargo-m3`, `--budget-isk`) and no stdin piping.

Optional overrides:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode live -CargoM3 15000 -BudgetISK 800000000
```

### Batch helper

```bat
run.bat
```

`run.bat` reads defaults from `config.json` and calls CLI args directly.

### Direct

```powershell
python .\main.py --cargo-m3 10000 --budget-isk 500m
```

If args are omitted, interactive defaults are still supported.

## Replay

Replay can be enabled in config or via env override:

- `NULLSEC_REPLAY_ENABLED=1` forces replay
- `NULLSEC_REPLAY_ENABLED=0` forces live

Replay snapshot path comes from `replay.snapshot_path`.

A replay smoke path is tested via subprocess (`main.py`) in `tests/test_integration.py`.

## Config and Secret Source Priority

Loading order:

1. `config.json` (base)
2. `config.local.json` (or `NULLSEC_LOCAL_CONFIG` target) overlay
3. ENV overrides (`ESI_CLIENT_ID`, `ESI_CLIENT_SECRET`, ...)

Validation emits source-aware warnings for `esi.client_secret`:

- from `config.json`
- from `config.local.json`
- from `ENV`

## Route Search and Deduplication

When `route_search.enabled=true`:

- routes are generated across allowed source/destination nodes
- node deduplication is based on `node_id` (not only labels)
- aliases remain usable via `allowed_pairs` and lane pinning
- explicit lane override per pair is supported:
  - `{ "from": "jita_44", "to": "o4t", "shipping_lane_id": "hwl_jita_o4t" }`

Output includes `route_leaderboard_<timestamp>.txt`.

## Transport Cost Confidence

For routes without matching shipping lane and without explicit `route_costs` entry:

- transport cost is treated as assumed zero
- route and pick metadata are marked low confidence
- runtime and reports include a warning (`transport_cost_warning`)

This avoids silently over-ranking routes due implicit 0 logistics cost assumptions.

## Region Mapping and planned_sell Reliability

- `structure_regions` maps `structure_id -> region_id` for regional history usage.
- warnings now reference active structure ids and labels.
- if planned sell is active and mapping is missing, warnings explicitly state that
  the planned-sell evaluation is not reliable for those targets.
- `esi.strict_region_mapping=true` hard-fails on missing active mappings.

## Outputs

Typical runtime outputs:

- per-route CSV: `*_to_*_<timestamp>.csv`
- candidate dumps: `*_top_candidates_<timestamp>.txt`
- execution plan: `execution_plan_<timestamp>.txt`
- route leaderboard (route search mode): `route_leaderboard_<timestamp>.txt`

## Test Layout

Tests were split from monolith into themed modules:

- `tests/test_core.py`
- `tests/test_portfolio.py`
- `tests/test_config.py`
- `tests/test_shipping.py`
- `tests/test_route_search.py`
- `tests/test_integration.py`
- shared helpers: `tests/shared.py`
- runner: `tests/run_all.py`

Compatibility entrypoint remains:

```powershell
python .\test_nullsectrader.py
```

## Quality Checks

Run the local quality workflow:

```powershell
python .\scripts\quality_check.py
```

It runs:

1. `py_compile` on runtime and test modules
2. `pyflakes` on runtime/entrypoint modules
3. split test suite via `python test_nullsectrader.py`

## Repo Hygiene

`.gitignore` now ignores:

- `__pycache__/`, `*.py[cod]`
- `*.egg-info/`, `build/`, `dist/`
- local env files and local config overlays
- `cache/`
- generated runtime artifacts (`execution_plan_*`, `route_leaderboard_*`, CSV/TXT outputs)

Do not commit local secrets (`config.local.json`, token/cache files).
