# Session Handoff

Date: 2026-03-07 (session 10 personal decision layer)
Branch: `dev`

## Completed This Session

### Task 5f - Explicit Personal History Decision Layer

Policy and guardrails:

- Added `personal_history_policy` support in `config.json` and
  `config_loader.py`
- Supported modes:
  - `off`
  - `advisory`
  - `soft`
  - `strict`
- The layer only activates when:
  - policy mode is `soft` or `strict`
  - personal quality is at least `usable`
  - wallet-backed and reliable sample minimums are met
- Stale, truncated, uncertain, or fee-weak history reduces effect strength and
  can still force fallback to the generic path

Decision-layer behavior:

- `confidence_calibration.py` still keeps generic
  `build_confidence_calibration()` unchanged
- Added separate helpers for:
  - policy resolution
  - personal layer state building
  - scoped segment indexing
  - bounded in-place `decision_overall_confidence` adjustment
  - effect summarization for output
- Current scoped personal axes:
  - `exit_type`
  - `target_market`
  - `route_id`
- Effects are intentionally small and capped:
  - config-driven positive / negative caps
  - `soft` is weaker than `strict`

Runtime and output wiring:

- `runtime_runner.py` now applies the personal layer after generic calibration
  on candidates and picks
- The relaxed-candidate path in `portfolio_builder.py` uses the same runtime
  state, so it does not silently skip the personal layer
- `execution_plan.py` now shows:
  - layer mode
  - quality
  - generic fallback vs active state
  - applied scoped effect if one was actually used

Explainability fields now written onto records:

- `personal_history_effect_applied`
- `personal_history_effect_scope`
- `personal_history_effect_reason`
- `personal_history_effect_value`
- `personal_history_adjusted_confidence`

## Tests

- Updated:
  - `tests/test_confidence_calibration.py`
  - `tests/test_execution_plan.py`
  - `tests/test_character_context.py`
- Focused tests after the patch:
  - `python -m pytest -q tests/test_confidence_calibration.py tests/test_execution_plan.py tests/test_character_context.py`
  - Result: **83 passed**
- Broader targeted regression:
  - `python -m pytest -q tests/test_journal.py tests/test_route_search.py tests/test_portfolio.py`
  - Result: **42 passed**
- Full suite after the patch:
  - `python -m pytest -q`
  - Result: **317 passed**

## Current Assessment

- Personal history is no longer only visible; it can now directly influence
  decision confidence when the user explicitly enables it and the data basis is
  strong enough
- Weak, sparse, stale, truncated, or unreliable history still falls back to
  the generic path
- Generic calibration remains the base model and was not rewritten
- Route-ranking formulas, `no_trade`, and planned-sell heuristics remain
  unchanged; only the bounded `decision_overall_confidence` input can move

## Known Limits

- The personal layer is intentionally narrow and currently only scopes by
  `exit_type`, `target_market`, and `route_id`
- Output parity still mainly exists in runtime stdout and
  `execution_plan.py`; `runtime_reports.py` summaries do not yet mirror the same
  compact layer status
- Wallet history is still snapshot-bound and page-limited, so old trades can
  keep the personal basis weak or uncertain

## Next Recommended Task

Choose one of these, in this order:

- add artifact parity in `runtime_reports.py` if roundtrip/chain summaries also
  need compact personal-layer visibility
- otherwise deepen regression evidence for scoped personal effects before any
  broader personal-model expansion
- keep avoiding any hidden coupling between personal history and unrelated
  ranking heuristics

## Relevant Files For The Next Session

- `runtime_runner.py`
- `execution_plan.py`
- `confidence_calibration.py`
- `config_loader.py`
- `portfolio_builder.py`
- `tests/test_execution_plan.py`
- `tests/test_confidence_calibration.py`
- `tests/test_route_search.py`
- `tests/test_portfolio.py`
- `docs/module-maps/runtime_runner.md`
- `docs/module-maps/execution_plan.md`
- `docs/module-maps/confidence_calibration.md`
