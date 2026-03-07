# Session Handoff

Date: 2026-03-07 (session 5 character context integration)
Branch: `dev`

## Completed This Session

### Task E - Optional private character context via EVE SSO / ESI

New modules:
- `eve_sso.py` - local EVE SSO metadata discovery, auth-code flow, refresh
  flow, token storage, and token-claim identity extraction
- `eve_character_client.py` - authenticated character ESI calls for skills,
  optional skill queue, open orders, wallet balance, wallet journal, wallet
  transactions, and bulk name resolution
- `character_profile.py` - local character-profile sync, cache fallback,
  fee-skill extraction, and route/pick annotation
- `local_cache.py` - small JSON envelope cache helper used by the new character
  layer

Runtime integration:
- `runtime_common.py` now supports `auth` and `character` CLI commands
- `runtime_runner.py` resolves optional character context at run start, falls
  back to cache/defaults, applies real fee skills when available, warns if the
  entered budget exceeds current wallet, and annotates results with character
  exposure
- `execution_plan.py` now surfaces character-context status in the plan header
  and shows open-order overlap on affected picks

Config and local files:
- `config.json` contains a default-disabled `character_context` block
- `config.local.example.json` documents the local opt-in shape
- private files stay inside ignored `cache/character_context/`

### Tests

- New: `tests/test_character_context.py`
- New: `tests/test_eve_sso.py`
- Updated: `tests/test_execution_plan.py`
- Targeted: **86 passed in 0.46s**
- Full suite: **289 passed in 17.85s**

### Current Assessment

- Character context is optional and does not hard-break live, replay, or offline
  use
- Skills are now genuinely usable: fee assumptions can be overridden with real
  character skill levels
- Open orders are integrated as a visible exposure signal, not yet as a hidden
  scoring penalty
- Wallet integration is at a pragmatic base level: balance, journal, and
  transactions are cached for later personal trade-history linkage
- Main conscious limitation: legacy market auth in `runtime_clients.py` and
  private character auth in `eve_sso.py` are separate low-risk paths for now
- Next recommended task: link wallet journal / transaction snapshots to the
  local trade journal and decide whether open-order overlap should remain a pure
  diagnostic or become an explicit warning tier

### Task D - Core logic follow-up

`portfolio_builder.py`
- Fixed B1: partial planned positions now keep queue-aware hold-time scaling via
  `queue_ahead_units + qty` instead of shrinking hold time only by
  `qty / max_units`
- Fixed B3: cargo-fill profitability comparisons and stored fill metrics now use
  expected-realized profit consistently for planned exits

`route_search.py`
- Re-reviewed B2: no patch applied
- Current judgment: `planned_share * 0.08` is a small route-composition /
  operational-risk penalty, separate from candidate-level confidence and fill
  probability discounting

### Tests

- Added regression coverage in `tests/test_portfolio.py` for:
  - queue-aware scaled `expected_days_to_sell`
  - portfolio pick hold-time output for reduced planned quantities
  - cargo-fill expected-realized profit-density gating for planned candidates
- Full suite: **278 passed in 17.47s**

### Current Assessment

- B1: real defect, fixed
- B3: real defect, fixed
- B2: not confirmed as a defect, left unchanged
- Next recommended task: keep scope narrow and add the profile-aware CLI smoke
  test from `main.py` through `runtime_runner.py`

### Task A+C — Execution Plan Restructuring + Audit Patches

**execution_plan.py — 5 fixes:**

| ID  | Severity | Description |
|-----|----------|-------------|
| A1  | HOCH     | `_route_level_warnings` dominance calc used gross `profit` not `expected_realized_profit_90d` — now consistent with portfolio_builder fix |
| A2  | MITTEL   | Picks within categories sorted by gross `profit` — now sorted by `expected_realized_profit_90d` |
| A3  | NIEDRIG  | `_write_route_trip_summary` printed `total_route_m3` and `shipping_cost_total` as duplicate lines — removed, now single `Shipping:` line |
| A4  | NEU      | Added `>>> MAX BUY: X ISK/unit` price threshold to every pick block (instant + planned) |
| A5  | NEU      | Added `>>> MIN SELL: X ISK/unit` for planned_sell picks |

**write_no_trade_report()** added to `execution_plan.py` — renders a
structured DO NOT TRADE report file.

### Task B — Do Not Trade Decision Engine

New module `no_trade.py`:
- `evaluate_no_trade(route_results, profile_name, profile_params, *, all_profiles)` — returns a structured result dict
- 10 reason codes: `NO_ACTIONABLE_ROUTES`, `NO_STRONG_EXITS`, `EXCESSIVE_SPECULATION`, `LOW_ROUTE_CONFIDENCE`, `SHIPPING_UNCERTAIN`, `CAPITAL_LOCK_TOO_HIGH`, `PROFIT_NOT_ACTIONABLE`, `DATA_QUALITY_TOO_WEAK`, `TOO_FEW_HIGH_QUALITY_PICKS`, `CANDIDATES_DID_NOT_SURVIVE_FILTERS`
- Decision rule: DNT if any critical severity code OR ≥2 high severity codes
- Profile-aware thresholds derived from `min_confidence`, `route_capital_lock_weight`, `route_speculative_penalty_weight`
- Near-miss summaries from non-actionable routes (up to 5)
- Cross-profile comparison: which other profiles would trade given same data

**runtime_runner.py integration** (around line 1553):
- Calls `evaluate_no_trade` after all route results are assembled
- If `should_trade=False` → writes `no_trade_<timestamp>.txt` and prints `[DO NOT TRADE]` to console
- Execution plan is still written regardless (for reference)

### Critical Review Patches (same session)

| ID  | File | Defect | Fix |
|-----|------|--------|-----|
| R1  | `no_trade.py` | `INSUFFICIENT_LIQUIDITY` defined but never emitted — dead code | Removed from `REASON_CODES` |
| R2  | `no_trade.py` | `PROFILE_REJECTED_AVAILABLE_TRADES` implied profile was the cause even when base config gates were responsible | Renamed to `CANDIDATES_DID_NOT_SURVIVE_FILTERS`; detail text now lists both possible causes |
| R3  | `no_trade.py` | Threshold helpers had no comments explaining their approximation basis | Added clear docstrings documenting that `_profile_max_capital_lock`, `_profile_max_speculative_share`, and `_profile_min_transport_conf` derive from ranking-penalty params, not explicit thresholds |
| R4  | `no_trade.py` | `_profile_min_route_conf` used pick-level `min_confidence` as route-level floor with no comment | Documented: it's a conservative proxy, safe but not exact |
| R5  | `tests/test_shipping.py` | `assert "5.000.000,00 ISK" in content` was trivially true (number appears multiple times) | Restored specific label: `assert "Shipping:  5.000.000,00 ISK (transport cost)" in content` |
| R6  | `tests/test_no_trade.py` | `test_profile_rejected_code_when_candidates_existed` used old code name | Updated to `CANDIDATES_DID_NOT_SURVIVE_FILTERS` |

### Tests

- New: `tests/test_no_trade.py` — 36 tests covering all reason codes, DNT threshold, profile comparison, near-misses, and report output
- Updated: `tests/test_execution_plan.py` — fixed dominance test to use `expected_realized_profit_90d`
- Updated: `tests/test_shipping.py` — restored specific shipping label assertion (R5 above)
- Full suite: **275 passed in 18.28s**

## What Was Reviewed

- `execution_plan.py` (fully read and patched)
- `no_trade.py` (created + critical review patched)
- `runtime_runner.py` (targeted read + patched)
- `risk_profiles.py` (read for profile param reference)
- `tests/test_execution_plan.py` (updated)
- `tests/test_no_trade.py` (created + R6 patch)
- `tests/test_shipping.py` (updated + R5 patch)

## Current Worktree State

Modified (uncommitted):
- `README.md`, `ARCHITECTURE.md`
- `candidate_engine.py`, `execution_plan.py`, `route_search.py`,
  `runtime_common.py`, `runtime_runner.py`
- `market_plausibility.py`, `portfolio_builder.py`
- `tests/test_execution_plan.py`, `tests/test_shipping.py`

Untracked (new files):
- `risk_profiles.py`, `no_trade.py`
- `tests/test_no_trade.py`, `tests/test_execution_plan.py`, `tests/test_risk_profiles.py`
- `AGENTS.md`, `PROJECT_STATE.md`, `TASK_QUEUE.md`, `SESSION_HANDOFF.md`
- `docs/`, `.github/`

None committed yet. Check `git status --short` before editing.

## Output Artifacts (new in this session)

- `no_trade_<timestamp>.txt` — DO NOT TRADE report when DNT triggered
- Execution plan pick blocks now include `>>> MAX BUY` and `>>> MIN SELL` lines

## Next Recommended Task

**TASK_QUEUE Task 3** — CLI smoke test for profile-aware runs.

A narrow test that parses `--profile <name>` through `main.py` → `runtime_common.py`
and verifies the profile name reaches `runtime_runner.run_cli()` without a live API.

Relevant files:
- `main.py`
- `runtime_common.py`
- `runtime_runner.py` (look for `resolve_active_profile` call site near top of `run_cli`)
- `tests/` (look for existing argparse test patterns in `test_execution_plan.py`)

## Relevant Files For The Next Session

- `main.py`
- `runtime_common.py`
- `runtime_runner.py`
- `tests/`
- `docs/module-maps/runtime_runner.md`
- `docs/module-maps/runtime_common.md`
- `TASK_QUEUE.md`
