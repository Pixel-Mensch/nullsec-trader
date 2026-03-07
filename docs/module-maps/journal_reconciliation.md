# Module Map: journal_reconciliation.py

## Purpose

Maps cached wallet transactions and wallet journal entries onto local trade-journal
entries with explicit confidence, reasons, and unmatched/ambiguous tracking.

## Responsibilities

- normalize raw wallet transaction and journal snapshots
- score candidate matches against local journal entries
- distinguish matched, ambiguous, and unmatched wallet activity
- derive wallet-based realized profit, fee estimates, and reconciliation status

## Inputs

- local journal entries from `journal_store.py`
- `wallet_snapshot` from `character_profile.py`
- optional `character_id`

## Outputs

- per-entry reconciliation fields for persistence
- unmatched wallet transaction list
- ambiguous transaction list
- unmatched wallet-journal fee list

## Key Files

- `journal_reconciliation.py`
- `journal_store.py`
- `journal_reporting.py`
- `tests/test_journal_reconciliation.py`

## Important Entry Points

- `reconcile_wallet_snapshot()`

## Depends On

- `journal_models.py`

## Used By

- `journal_store.py`
- `journal_cli.py`
- `journal_reporting.py`

## Common Change Types

- tighten or relax transaction matching thresholds
- add new wallet-journal fee/ref-type handling
- refine reconciliation statuses or match reasons

## Risk Areas

- false-positive matching when the same type is traded repeatedly
- stale or paged wallet snapshots can make clean trades look unmatched
- wallet-based profit excludes costs not visible in wallet data unless mixed in explicitly

## Tests

- `tests/test_journal_reconciliation.py`
- `tests/test_journal.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `journal_reconciliation.py`
3. `tests/test_journal_reconciliation.py`
4. `journal_store.py` and `journal_reporting.py` only if persistence or output must change

## When This File Must Be Updated

Update this module map when matching rules, reconciliation statuses, or owned
outputs materially change.
