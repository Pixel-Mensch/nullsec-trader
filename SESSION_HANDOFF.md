# Session Handoff

Date: 2026-03-07 (session 7 wallet history quality)
Branch: `dev`

## Completed This Session

### Task 5b - Wallet Paging, Freshness, And Fee-Matching Quality

Wallet fetch / cache layer:

- `eve_character_client.py` now supports optional paging metadata for wallet
  journal and wallet transactions:
  - `pages_loaded`
  - `total_pages`
  - `page_limit`
  - `history_truncated`
- `character_profile.py` now stores wallet snapshot metadata in the local
  character profile:
  - snapshot timestamp
  - stale threshold
  - journal/transaction page counts
  - journal/transaction truncation flags
  - oldest/newest wallet timestamps
  - component status (`loaded`, `disabled`, `error`)

Reconciliation and persistence:

- `journal_reconciliation.py` now evaluates wallet snapshot quality before
  matching:
  - fresh vs stale
  - full vs partial vs truncated history
  - transaction-window coverage for older journal entries
- Entries can now stay `match_uncertain` when a truncated transaction window
  does not actually cover the trade age, instead of being pushed toward a false
  `suggested_not_bought`.
- Fee matching is now explicitly tiered:
  - `exact`
  - `partial`
  - `fallback`
  - `uncertain`
  - `unavailable`
- Conservative fee fallback was added only for unique nearby wallet-journal
  candidates. Multiple plausible candidates remain uncertain.
- `journal_store.py` now persists the key wallet-quality fields on each journal
  entry:
  - `fee_match_quality`
  - `wallet_snapshot_age_sec`
  - `wallet_data_freshness`
  - `wallet_history_quality`
  - `wallet_history_truncated`
  - `wallet_transactions_pages_loaded`
  - `wallet_journal_pages_loaded`
  - `reconciliation_basis`

Reporting / CLI:

- Existing commands stayed the same:
  - `journal reconcile`
  - `journal personal`
  - `journal unmatched`
- `journal_reporting.py` now shows wallet quality summary lines and warnings for:
  - stale snapshot basis
  - truncated history
  - limited transaction window
  - fee-match quality
  - reconciliation basis

## Tests

- Updated:
  - `tests/test_character_context.py`
  - `tests/test_journal_reconciliation.py`
- Existing coverage still exercised:
  - `tests/test_journal.py`
- Focused tests after the patch:
  - `python -m pytest -q tests/test_character_context.py tests/test_journal_reconciliation.py tests/test_journal.py`
  - Result: **28 passed**

## Current Assessment

- Wallet history is now more honest and more useful:
  - multi-page wallet snapshots retain page-depth metadata
  - stale vs fresh cache/live basis is visible
  - truncated history is surfaced instead of hidden
  - fee linking is better for older or incomplete snapshots, without aggressive
    guessing
- The journal remains usable without live ESI.
- Reconciliation is still intentionally conservative and snapshot-bound.

## Known Limits

- This is still not a full historical sync. If the configured page window does
  not reach the real trade age, older trades can remain uncertain.
- Fee fallback only runs for unique nearby candidates. It will deliberately
  miss some real fees rather than overmatch.
- Wallet-based profit still excludes off-wallet costs like shipping.

## Next Recommended Task

Use the cleaner reconciliation basis for higher-level analytics, not scoring:

- improve personal trade-history summaries from reconciled outcomes
- evaluate whether confidence calibration should consume reconciled wallet
  outcomes more directly
- keep route ranking and candidate scoring unchanged unless a separate,
  evidence-backed task requires it

## Relevant Files For The Next Session

- `eve_character_client.py`
- `character_profile.py`
- `journal_reconciliation.py`
- `journal_store.py`
- `journal_reporting.py`
- `journal_cli.py`
- `tests/test_character_context.py`
- `tests/test_journal_reconciliation.py`
