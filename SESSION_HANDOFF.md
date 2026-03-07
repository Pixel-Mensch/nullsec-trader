# Session Handoff

Date: 2026-03-07 (session 8 personal analytics)
Branch: `dev`

## Completed This Session

### Task 5c - Personal Analytics And Separate Personal Calibration Basis

Shared outcome semantics:

- `journal_models.py` now owns the effective wallet-backed outcome helpers used
  by both reporting and personal calibration:
  - `effective_entry_status()`
  - `effective_entry_qty()`
  - `effective_entry_profit_net()`
  - `effective_entry_days_to_sell()`
  - `effective_entry_trade_history_source()`

Personal analytics:

- `journal_reporting.py` now builds richer personal analytics from reconciled
  entries:
  - suggested -> bought hit rate
  - bought -> fully sold hit rate
  - partially sold share
  - uncertain-match and `wallet_unmatched` share
  - expected vs realized profit and sell-duration deltas
  - open-position age buckets
  - compact problem-pattern counts
- `journal personal` now shows:
  - history quality and eligible sample size
  - explicit fallback/advisory policy
  - wallet quality lines
  - richer personal metrics without changing ranking

Personal calibration basis:

- `confidence_calibration.py` now has a separate personal-history path:
  - `classify_personal_trade_outcome()`
  - `build_personal_calibration_summary()`
  - `format_personal_calibration_summary()`
- Personal history quality is now graded:
  - `none`
  - `very_low`
  - `low`
  - `usable`
  - `good`
- Guardrails are explicit:
  - no personal history -> fallback generic
  - low sample size -> fallback generic
  - unreliable history -> fallback generic
  - ranking effect stays `none`
- The existing generic `build_confidence_calibration()` path was intentionally
  left unchanged, so route ranking and candidate scoring did not move.

CLI / docs / maps:

- `journal calibration` now prints the existing generic calibration report plus
  a separate `PERSONAL CALIBRATION BASIS`
- Added `docs/module-maps/journal_reporting.md`
- Updated the confidence-calibration module map and control files to document
  the advisory-only design

## Tests

- Updated:
  - `tests/test_confidence_calibration.py`
  - `tests/test_journal.py`
  - `tests/test_journal_reconciliation.py`
- Focused tests after the patch:
  - `python -m pytest -q tests/test_confidence_calibration.py tests/test_journal.py tests/test_journal_reconciliation.py`
  - Result: **31 passed**

## Current Assessment

- Personal journal analytics are now materially more useful and more honest.
- The system now distinguishes:
  - no personal history
  - weak sample size
  - unreliable wallet-backed basis
  - usable/good advisory history
- Reconciled outcomes can now be read as a calibration basis without feeding
  back into the runtime ranking path.

## Known Limits

- Personal history is still analytics-only. There is no opt-in decision hook
  yet.
- Quality grading is intentionally conservative and heuristic. It is meant to
  prevent false certainty, not to be a scientific trust score.
- Wallet history remains snapshot-bound and page-limited, so older trades can
  still stay uncertain even when the analytics layer is richer.

## Next Recommended Task

Keep personal history advisory until there is evidence for a careful opt-in
consumer:

- decide whether the personal calibration basis should appear in additional
  runtime reports
- if a future decision hook is desired, make it explicit, opt-in, and
  sample-size-aware
- continue avoiding silent changes to route ranking or candidate scoring

## Relevant Files For The Next Session

- `journal_models.py`
- `journal_reporting.py`
- `confidence_calibration.py`
- `journal_cli.py`
- `journal_reconciliation.py`
- `tests/test_confidence_calibration.py`
- `tests/test_journal.py`
- `tests/test_journal_reconciliation.py`
- `docs/module-maps/journal_reporting.md`
