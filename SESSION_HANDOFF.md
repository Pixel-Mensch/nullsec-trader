# Session Handoff

Date: 2026-03-08 (session 15 internal self-haul fix)
Branch: `dev`

## Completed This Session

### False transport blocking on internal nullsec routes

Fixed the concrete business bug where profitable internal nullsec routes were
found by candidate generation but later blocked with:

`No shipping lane or explicit route_costs matched this route; route is blocked until transport cost is modeled.`

The fix is now centralized in `shipping.py` instead of being spread across
route consumers.

## Root Cause

- transport blocking previously treated every route without a matched shipping
  lane or explicit `route_costs` as unresolved external transport
- that was correct for Jita-connected routes, but wrong for internal
  structure-to-structure nullsec movement between the operator's own trading
  structures
- the runtime therefore found profitable internal candidates and then pruned
  them during transport-cost application

## What Changed

- `shipping.py`
  - added central route classification for internal structure-to-structure
    nullsec routes using configured `structures` plus `route_chain.legs`
  - internal routes without Jita now use `transport_mode=internal_self_haul`
  - `internal_self_haul` no longer blocks on missing external shipping lanes
  - default internal transport cost is currently `0 ISK`
  - Jita routes still stay on the external shipping model
- `runtime_runner.py`
  - now prints an explicit `INFO` line when a route is using
    `internal_self_haul`
  - carries `transport_mode` and `transport_mode_note` into route results
- `execution_plan.py`
  - now shows `Transport Mode: internal_self_haul`
  - now shows `Transport: internal_self_haul | Cost: 0,00 ISK`
- `journal_models.py`
  - trade-plan manifest now includes `transport_mode` and
    `transport_mode_note`
- `config.json`
  - removed duplicate `structures.c-j6mt` alias that reused the `cj6` ID
  - added `structure_regions` for:
    - `1046664001931 -> 10000061` (`UALX-3`, Tenerifis)
    - `1048663825563 -> 10000039` (`R-ARKN`, Esoteria)
- `README.md`
  - documents the new `internal_self_haul` rule for non-Jita internal routes

## Tests And Verification

- Targeted regression set:
  - `python -m pytest -q tests/test_shipping.py tests/test_config.py`
    -> **59 passed**
  - `python -m pytest -q tests/test_route_search.py tests/test_integration.py`
    -> **22 passed**

### New regression coverage

- `tests/test_shipping.py`
  - Jita -> internal keeps `external_shipping`
  - internal -> Jita keeps `external_shipping`
  - internal -> internal without shipping lane becomes `internal_self_haul`
  - internal self-haul route is not blocked and gets `0 ISK`
  - execution plan prints the internal self-haul transport mode and zero-cost note
- `tests/test_config.py`
  - repo `config.json` now has unique structure IDs
  - repo `config.json` now covers internal chain structure regions, so
    planned-sell validation does not warn about missing region mappings for
    `UALX-3` or `R-ARKN`

### Real replay verification

Ran:

`$env:NULLSEC_REPLAY_ENABLED='1'; python .\main.py --cargo-m3 10000 --budget-isk 500m`

Observed in real runtime output:

- no duplicate-structure warning anymore
- no missing-`structure_regions` warning for `UALX-3` / `R-ARKN`
- internal routes now print `INFO: ... Internal self haul ... 0 ISK`
- internal routes that still have no picks are now `no_picks`, not
  `missing_transport_cost_model`
- profitable internal routes remained actionable, for example:
  - `O4T -> UALX-3`
  - `R-ARKN -> 1st Taj Mahgoon`
  - `1st Taj Mahgoon -> UALX-3`

Checked generated artifacts from that replay run:

- `execution_plan_2026-03-08_03-47-44.txt`
  - contains `Transport Mode: internal_self_haul`
  - contains `Transport: internal_self_haul  |  Cost: 0,00 ISK`
- `route_leaderboard_2026-03-08_03-47-44.txt`
  - shows `transport_mode: internal_self_haul` on ranked internal routes

## Known Limits

- `internal_self_haul` is intentionally a zero-cost placeholder policy for now
  and does not yet model ansiplex fuel, move risk, or time cost
- future internal cost modeling should attach to the same central seam in
  `shipping.py` instead of reintroducing route-by-route exceptions
- replay run artifacts were used for verification but not committed

## Next Recommended Task

- if desired, extend `internal_self_haul` with optional internal
  `route_costs` presets for ansiplex/fuel/risk without changing the Jita
  shipping path
- decide whether the web route cards should also render `transport_mode` now
  that the manifest exposes it

## Files Touched

- `shipping.py`
- `runtime_runner.py`
- `execution_plan.py`
- `journal_models.py`
- `config.json`
- `README.md`
- `tests/test_shipping.py`
- `tests/test_config.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
