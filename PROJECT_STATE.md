# Project State

Last updated: 2026-03-07

## Snapshot

This repository is a Python CLI tool for EVE Online nullsec trading analysis.
It evaluates route candidates, applies fee and shipping models, builds
portfolios, and writes actionable execution-plan style outputs instead of only
showing raw spreads.

This state file is intentionally conservative. It is based on a small verified
file set, not a full repository scan.

## Evidence Base

Reviewed this session:

- `AGENTS.md`
- `README.md`
- `ARCHITECTURE.md`
- `pyproject.toml`
- `config.json`
- `main.py`
- `runtime_runner.py`
- `candidate_engine.py`
- `character_profile.py`
- `eve_character_client.py`
- `eve_sso.py`
- `journal_reconciliation.py`
- `journal_store.py`
- `journal_reporting.py`
- `journal_cli.py`
- `local_cache.py`
- `portfolio_builder.py`
- `route_search.py`
- `confidence_calibration.py`
- `risk_profiles.py`
- `tests/run_all.py`
- `tests/test_character_context.py`
- `tests/test_journal.py`
- `tests/test_journal_reconciliation.py`
- `tests/test_eve_sso.py`
- `tests/test_execution_plan.py`
- `tests/test_portfolio.py`
- `tests/test_route_search.py`
- `tests/test_risk_profiles.py`
- current `git status`
- `python -m pytest -q`

Not fully re-audited this session:

- most remaining modules under the root
- deep test fixture contents
- any local-only values in `config.local.json`

## Confirmed Project Goals

- evaluate whether a trade is actually executable after fees, transport, and
  exit realism
- support live and replay analysis from one CLI surface
- prefer conservative, decision-grade outputs over paper-profit lists
- keep the runtime usable for real trading plans and later journal review

## Confirmed Implemented Capabilities

- CLI entry path: `main.py` -> `runtime_runner.run_cli()`
- live and replay client support
- route profile, chain, roundtrip, and snapshot-only modes
- candidate generation for `instant`, `fast_sell`, and `planned_sell`
- centralized fee, shipping, and transport-blocking logic
- portfolio construction with budget and cargo constraints
- queue-aware liquidation-time handling for scaled planned positions in
  `portfolio_builder.py`
- cargo-fill density checks now compare expected-realized profit on both sides
  for planned exits
- execution plan, leaderboard, CSV, and summary outputs
- local trade journal and confidence calibration support
- targeted test suite plus lightweight custom test runner
- optional private character context via EVE SSO/ESI with local token storage,
  cache fallback, and character profile sync
- character profile contains identity, skills, optional skill queue, open
  orders, wallet balance, wallet journal snapshot, and wallet transaction
  snapshot
- real character skill levels can override generic fee assumptions in
  `fee_engine.py` via `runtime_runner.py`
- execution plan output can show character-context status and open-order
  exposure on overlapping picks
- wallet transactions and wallet journal can now be reconciled against local
  journal entries with persisted match IDs, match confidence, reconciliation
  status, and wallet-based realized-profit estimates
- wallet snapshots now persist page-depth and freshness metadata, so
  reconciliation can distinguish fresh vs stale snapshots and full vs truncated
  wallet windows
- wallet-journal fee matching is now tiered (`exact`, `partial`, `fallback`,
  `uncertain`, `unavailable`) instead of silently treating all misses the same
- journal CLI now supports `reconcile`, `personal`, and `unmatched` views for
  personal trade-history work without requiring live ESI
- `journal personal` now exposes personal hit rates, profit/duration deltas,
  open-position age buckets, problem classes, and sample-size/data-quality
  hints from reconciled history
- `journal calibration` now keeps the existing generic model intact while also
  printing a separate personal calibration basis with explicit
  fallback-to-generic guardrails
- normal runtime output and execution plans now show a compact
  `Personal Layer` status with mode, quality, sample size, and generic
  fallback reason when the personal basis is too weak
- an explicit `personal_history_policy` can now optionally nudge
  `decision_overall_confidence` through a small bounded personal decision layer
  (`off`, `advisory`, `soft`, `strict`) using scoped reconciled-history signals
  for `exit_type`, `target_market`, and `route_id`
- every personal decision-layer effect is explainable on records and route
  results via applied flag, scope, reason, and capped effect value; weak or
  sparse history still falls back to the generic path
- configurable risk profiles (6 built-in) with end-to-end enforcement in
  `runtime_runner.py`: candidate filter, min_profit_per_m3 gate,
  min_confidence gate, portfolio config, and route score multiplier
- Do Not Trade decision engine (`no_trade.py`): 11 structured reason codes,
  profile-aware thresholds, near-miss display, cross-profile comparison;
  writes `no_trade_<timestamp>.txt` and prints `[DO NOT TRADE]` on console
- Execution plan pick blocks now include `MAX BUY` and `MIN SELL` price
  thresholds, picks sorted by `expected_realized_profit_90d`, and a
  single clean trip summary (duplicate shipping and m3 lines removed)

## Current Strengths

- `README.md` already contains detailed business and operator context
- `ARCHITECTURE.md` and module naming are strong enough to build a narrow file map
- hotspot module maps can now live under `docs/module-maps/` to reduce repeat
  source-file loading
- project dependencies are minimal in `pyproject.toml`
- the runtime entry path is clear and non-magical
- tests are split into targeted modules instead of one giant file

## Current Pain Points

- control-file workflow was missing or incomplete before this session
- `runtime_runner.py` and `candidate_engine.py` are large, high-context files
- active worktree changes span several core modules, increasing handoff risk
- Copilot workflow is now standardized under `.github/copilot-instructions.md`,
  so session docs need to stay aligned with that single location
- module-map coverage is still partial; several large support modules remain
  unmapped
- business docs are strong, but session-state docs were not keeping pace
- legacy live market auth in `runtime_clients.py` and new private-character SSO
  in `eve_sso.py` are separate paths for now; that is intentional for low-risk
  integration, but still duplicated auth surface
- wallet reconciliation is intentionally conservative: it is snapshot-based and
  can only match the transaction/journal pages currently available in cache or
  live sync
- wallet history is now more transparent, but still bounded by configured page
  limits; very old trades can stay uncertain when the loaded transaction window
  does not reach far enough back
- personal analytics and the opt-in decision layer are now visible in journal
  views, normal runtime output, and execution plans, but chain/roundtrip
  summary artifacts outside `execution_plan.py` still do not mirror the same
  compact status block
- the personal decision layer is intentionally narrow: it only adjusts
  `decision_overall_confidence` with hard caps and explainability, so evidence
  for broader scope tuning is still limited

## Current Focus

Observed worktree activity on 2026-03-07 suggests current feature work is
centered on:

- risk-profile selection and enforcement
- route-ranking adjustments by profile
- execution-plan output restructuring
- CLI/runtime integration for profile-aware output
- targeted core-logic cleanup in portfolio construction
- optional private character-context integration and cacheable ESI sync
- wallet-to-journal reconciliation and personal trade-history reporting
- wallet paging, freshness visibility, and conservative fee/ref matching for
  older or truncated snapshots
- personal journal analytics and a separate personal calibration basis
- an explicit, bounded personal decision layer with strict
  sample-size/data-quality guardrails and visible explainability
- compact runtime visibility for personal-history quality, fallback reasons,
  and applied scoped personal adjustments

Files that indicate this focus:

- `risk_profiles.py`
- `runtime_runner.py`
- `runtime_common.py`
- `candidate_engine.py`
- `route_search.py`
- `portfolio_builder.py`
- `execution_plan.py`
- `character_profile.py`
- `journal_reconciliation.py`
- `journal_store.py`
- `journal_reporting.py`
- `journal_cli.py`
- `eve_character_client.py`
- `eve_sso.py`
- `tests/test_risk_profiles.py`
- `tests/test_character_context.py`
- `tests/test_journal.py`
- `tests/test_journal_reconciliation.py`
- `tests/test_eve_sso.py`
- `tests/test_execution_plan.py`
- `tests/test_portfolio.py`

## Known Issues And Uncertainties

- Risk-profile integration is confirmed end-to-end (see Confirmed Implemented
  Capabilities below and TASK_QUEUE Task 1). No known open gaps remain.
- `route_search.py` speculative penalty was re-reviewed on 2026-03-07. The
  small planned-share term still looks like a separate route-composition risk
  heuristic, not a confirmed double-counting defect, so no change was made.
- Character context is optional by design. Live sync now falls back to cache or
  generic defaults, but order exposure is currently surfaced as a diagnostic
  signal only, not a route-ranking penalty.
- Journal reconciliation is also optional by design. Without wallet data, the
  manual journal remains usable and reconciliation does not persist empty
  results over existing entries.
- Wallet reconciliation now exposes snapshot freshness, page coverage, and
  truncation warnings in the journal views. This reduces false confidence, but
  does not create a historical backfill system.
- Personal history quality is now graded (`none` to `good`) and sample-size
  aware. It can only influence `decision_overall_confidence` when
  `personal_history_policy` is explicitly enabled in `soft` or `strict` mode,
  the basis is at least `usable`, and wallet-backed / reliable minimums are
  met. Otherwise it falls back to the generic path.
- Route-ranking formulas, candidate heuristics, `no_trade`, and generic
  `build_confidence_calibration()` logic remain unchanged. When the personal
  layer is active, those existing paths can only see the already-capped
  `decision_overall_confidence` value they were designed to consume.
- The personal decision layer currently scopes only by `exit_type`,
  `target_market`, and `route_id`. It is not a general personal market model.
- Matching remains intentionally honest rather than magical: ambiguous
  transactions stay visible as uncertain, and unmatched wallet activity is
  reported separately instead of being forced onto a trade entry.
- This session did not perform a full code audit, so undocumented modules may
  contain behavior not yet reflected here.
- `config.local.json` exists locally but is Git-ignored; secret values were not
  inspected.
- Always check `git status --short` before editing. This repository often has
  in-flight work on core runtime and journal modules.

## Working Assumptions For Future Sessions

- branch `dev` is the correct working branch unless the user says otherwise
- future AI tasks should start from control files, then open only the module
  that owns the requested behavior
- documentation-first, targeted edits are preferred over broad refactors
