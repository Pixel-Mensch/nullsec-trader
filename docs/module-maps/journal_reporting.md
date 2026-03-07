# Module Map: journal_reporting.py

## Purpose

Formats enriched journal entries into practical overview, reconciliation, and
personal-history reports without owning journal persistence or wallet matching.

## Responsibilities

- enriches raw journal entries with effective wallet-backed outcomes
- builds aggregate journal and personal-trade analytics
- formats overview, open/closed, reconciliation, unmatched, and personal views
- keeps personal history readable without changing ranking behavior

## Inputs

- journal entry dicts from `journal_store.py`
- optional reconciliation result dicts from `journal_reconciliation.py`
- optional personal calibration summary dicts from `confidence_calibration.py`

## Outputs

- enriched journal entry dicts
- journal summary/report dicts
- formatted CLI-ready report strings

## Key Files

- `journal_reporting.py`
- `journal_models.py`
- `journal_cli.py`
- `tests/test_journal.py`
- `tests/test_journal_reconciliation.py`

## Important Entry Points

- `enrich_journal_entry()`
- `build_journal_report()`
- `build_personal_trade_analytics()`
- `format_journal_report()`
- `format_reconciliation_overview()`
- `format_personal_trade_history()`

## Depends On

- `journal_models.py`
- `runtime_reports.py`
- optional lazy import of `confidence_calibration.py` for personal summaries

## Used By

- `journal_cli.py`
- tests and local tooling through `nullsectrader.py`

## Common Change Types

- add or rebalance personal analytics fields
- add concise warnings around data quality
- improve compact report formatting
- expose new reconciled fields without changing storage logic

## Risk Areas

- report text can drift away from actual matching semantics
- wallet-backed and manual outcomes must stay clearly distinguished
- personal analytics must remain advisory only, never a hidden ranking input
- overlong output can make CLI use worse instead of better

## Tests

- `tests/test_journal.py`
- `tests/test_journal_reconciliation.py`

## AI Editing Guidelines

Recommended reading order before editing:
1. this module map
2. `journal_reporting.py`
3. relevant tests
4. `journal_models.py` or `confidence_calibration.py` only if semantics change

## When This File Must Be Updated

Update this module map when report responsibilities, dependencies, entry
points, or personal-analytics behavior changes.
