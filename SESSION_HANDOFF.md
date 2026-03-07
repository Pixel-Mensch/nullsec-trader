# Session Handoff

Date: 2026-03-07 (session 9 runtime personal advisory)
Branch: `dev`

## Completed This Session

### Task 5d - Runtime Visibility For Personal History / Calibration Basis

Runtime advisory output:

- `confidence_calibration.py` now exposes:
  - `personal_calibration_status_lines()`
- The helper is intentionally compact and runtime-safe:
  - weak basis -> quality + sample counts + `fallback to generic` + warning
  - usable/good basis -> quality + sample counts + compact outcome hint
  - every line stays explicitly advisory-only

Runtime wiring:

- `runtime_runner.py` now builds a separate personal-calibration runtime bundle
  from the local journal DB during normal runs
- That summary is printed once on stdout as a small `Personal History` section
- The same summary is attached to route results as metadata only:
  - `_personal_calibration_summary`
- No decision path was changed:
  - generic `build_confidence_calibration()` remains the real runtime model
  - route ranking stays unchanged
  - candidate scoring stays unchanged
  - `no_trade` stays unchanged

Execution-plan visibility:

- `execution_plan.py` now renders the compact personal-history advisory block in
  the route-profile execution-plan header
- This sits next to the existing character-context header and remains
  informational only

## Tests

- Updated:
  - `tests/test_confidence_calibration.py`
  - `tests/test_execution_plan.py`
- Focused tests after the patch:
  - `python -m pytest -q tests/test_confidence_calibration.py tests/test_execution_plan.py`
  - Result: **68 passed**
- Full suite after the patch:
  - `python -m pytest -q`
  - Result: **310 passed**

## Current Assessment

- Personal-history quality is now visible in the normal runtime path instead of
  only in journal-specific commands
- Weak history is clearly marked as weak and still falls back to the generic
  model
- Usable/good history now shows up as a compact informational hint with sample
  size and wallet-backed / reliable counts
- The advisory/runtime split is still intact

## Known Limits

- The compact advisory block is currently guaranteed in stdout and
  `execution_plan.py` route-profile output, but not yet mirrored across every
  summary artifact in `runtime_reports.py`
- Personal history is still not a decision hook
- Wallet history remains snapshot-bound and page-limited, so old trades can
  still keep the personal basis weak or uncertain

## Next Recommended Task

Choose one of these, in this order:

- if artifact parity matters, mirror the same compact advisory block into
  roundtrip/chain summaries in `runtime_reports.py`
- otherwise keep building evidence and guardrails before any future opt-in
  decision hook
- continue avoiding silent scoring or ranking changes from personal history

## Relevant Files For The Next Session

- `runtime_runner.py`
- `execution_plan.py`
- `confidence_calibration.py`
- `journal_reporting.py`
- `tests/test_execution_plan.py`
- `tests/test_confidence_calibration.py`
- `docs/module-maps/runtime_runner.md`
- `docs/module-maps/execution_plan.md`
- `docs/module-maps/confidence_calibration.md`
