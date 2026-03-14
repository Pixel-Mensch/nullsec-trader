# Session Handoff

Date: 2026-03-14 (session 32 small wallet hub safe)
Branch: `dev`

## Completed This Session

Implemented a new conservative profile `small_wallet_hub_safe` for small-wallet
nullsec trading with protected reserve liquidity, harsh final liquidity /
market-quality gates, and a compact `SAFE BUYS TODAY` execution-plan summary.

## Root Cause

- existing profiles covered generic conservative behavior but not the specific
  small-wallet operating model: keep reserve liquid, avoid capital lock, cap
  per-item exposure hard, and only show a short safe-buy list for today
- the runtime already had a clean risk-profile seam and a compact shopping-list
  seam, so the right fix was to extend those seams instead of inventing a new
  mode-specific runner or report type

## What Changed

- `risk_profiles.py`
  - added built-in profile `small_wallet_hub_safe`
  - added optional final pick gates for sell-time, liquidity, market quality,
    manipulation risk, and profit/spend
  - added `resolve_profile_budget_window()` for protected reserve handling
- `runtime_runner.py`
  - applies the profile reserve before route planning and attaches the budget
    reserve metadata to route results
  - extends profile rejection metrics / prune-reason mapping for the stricter
    final gates
- `execution_plan.py`
  - adds `SAFE BUYS TODAY` to the top of plans when the active profile requests
    it
  - fixes internal-route near-miss floor rendering for explicit
    `internal_route_profit_below_operational_floor` rejections
- `config_loader.py`
  - validates `risk_profile.name` against the built-in profile registry
- `no_trade.py`
  - carries `transport_mode` through near-miss records for report parity
- `nullsectrader.py`
  - re-exports the new risk-profile budget helper for test/tool parity
- `tests/test_risk_profiles.py`, `tests/test_config.py`,
  `tests/test_execution_plan.py`, `tests/test_runtime_runner.py`
  - added focused coverage for the new profile, reserve-budget math,
    safe-buy output, config validation, and new prune buckets

## Tests And Verification

- `python -m pytest -q tests/test_risk_profiles.py tests/test_config.py tests/test_execution_plan.py tests/test_runtime_runner.py tests/test_webapp.py`
  - **195 passed**
- `python -m pytest -q tests/test_no_trade.py tests/test_execution_plan.py`
  - **108 passed**
- `python scripts/quality_check.py`
  - **203 passed**

## Remaining Limits

- `small_wallet_hub_safe` currently protects reserve liquidity by shrinking the
  spendable planning budget; it does not yet show separate reserve handling in
  every non-route-profile artifact
- the reserve floor intentionally soft-caps itself at 50% of budget on very
  small wallets so the profile still leaves some deployable capital
- the mode strongly prefers direct exits by blocking planned sells and
  hard-gating final picks, but it still relies on the existing hub / market
  evidence already modeled elsewhere in the runtime

## Next Recommended Task

Add one narrow CLI smoke test that proves `--profile small_wallet_hub_safe`
parses and reaches the runtime path without needing a full market-data run.

## Files Touched

- `risk_profiles.py`
- `runtime_runner.py`
- `execution_plan.py`
- `config_loader.py`
- `no_trade.py`
- `nullsectrader.py`
- `tests/test_config.py`
- `tests/test_risk_profiles.py`
- `tests/test_execution_plan.py`
- `tests/test_runtime_runner.py`
- `README.md`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
- `docs/module-maps/risk_profiles.md`
- `docs/module-maps/execution_plan.md`
- `docs/module-maps/runtime_runner.md`
