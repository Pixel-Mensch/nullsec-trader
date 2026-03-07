# Session Handoff

Date: 2026-03-07 (session 6 wallet journal reconciliation)
Branch: `dev`

## Completed This Session

### Task F - Wallet Journal / Transaction Reconciliation

New module:

- `journal_reconciliation.py` - normalizes cached wallet transactions and
  wallet journal entries, scores candidate matches against local journal
  entries, keeps ambiguous/unmatched activity explicit, and derives
  wallet-based realized profit plus fee estimates

Journal persistence:

- `journal_store.py` now patch-safely extends `journal_entries` with:
  - matched wallet transaction IDs
  - matched wallet journal IDs
  - ambiguous wallet transaction IDs
  - matched buy/sell qty and value
  - first/last matched timestamps
  - realized fee estimate
  - realized wallet profit
  - reconciliation status, confidence, reason
  - source/target location IDs
  - character ID and open-order warning fields
- Reconciliation is opt-in. If no wallet data is available, no empty
  reconciliation result is persisted over existing journal entries.

CLI and reporting:

- `journal_cli.py` adds:
  - `journal reconcile`
  - `journal personal`
  - `journal unmatched`
- `journal_reporting.py` now uses reconciled wallet metrics when present,
  while keeping manual journal data as fallback.
- `execution_plan.py` now surfaces order-overlap warning tiers more clearly:
  route header overlap counts plus per-pick `[WARN][ORDER-*]` lines.

Plan/import metadata:

- `journal_models.py` now stores character ID, source/target location IDs, and
  open-order warning metadata in new trade-plan manifests so later wallet
  matching has better context.

## Tests

- New: `tests/test_journal_reconciliation.py`
- Updated coverage via existing:
  - `tests/test_journal.py`
  - `tests/test_character_context.py`
  - `tests/test_execution_plan.py`
  - `tests/test_confidence_calibration.py`
  - `tests/test_core.py`
  - `tests/test_architecture.py`
- Focused tests: **104 passed**

## Current Assessment

- Wallet transactions and wallet journal data are now meaningfully linkable to
  local trade-journal entries without requiring live ESI on every run.
- Matching is intentionally conservative:
  - clear matches are persisted
  - ambiguous matches stay visible as uncertain
  - unmatched wallet activity is reported separately
- Personal trade history now has a first reliable base:
  - wallet-based realized profit
  - real sell duration from matched timestamps
  - improved open-position visibility
  - better suggested-vs-real comparison
- Open-order overlap is now a warning tier in output and journal context, but
  still not baked into route ranking.

## Known Limits

- Reconciliation is snapshot-based. If the cached/live wallet pages do not
  cover the real trade window, entries can remain `wallet_unmatched` or
  `match_uncertain`.
- Wallet-derived profit currently only includes wallet-visible fee/tax refs.
  Shipping and other off-wallet costs remain separate.
- Confidence calibration still uses the existing journal model and was not
  reworked to explicitly prefer reconciled wallet outcomes in this session.

## Next Recommended Task

Deepen Task 5b from `TASK_QUEUE.md`:

- improve wallet paging/freshness controls
- extend fee/ref matching for older or multi-page histories
- decide later, with evidence, whether reconciliation should feed confidence
  calibration more directly

## Relevant Files For The Next Session

- `journal_reconciliation.py`
- `journal_store.py`
- `journal_reporting.py`
- `journal_cli.py`
- `character_profile.py`
- `execution_plan.py`
- `docs/module-maps/journal_reconciliation.md`
- `tests/test_journal_reconciliation.py`
