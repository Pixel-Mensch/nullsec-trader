# Project State

Last updated: 2026-03-14 (session 31 imperium candidate nodes)

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
- `.gitignore`
- `ARCHITECTURE.md`
- `pyproject.toml`
- `config.json`
- `main.py`
- `runtime_cleanup.py`
- `runtime_runner.py`
- `candidate_engine.py`
- `character_profile.py`
- `eve_character_client.py`
- `eve_sso.py`
- `webapp/app.py`
- `webapp/routes/pages.py`
- `webapp/services/analysis_service.py`
- `webapp/services/dashboard_service.py`
- `webapp/services/journal_service.py`
- `webapp/services/character_service.py`
- `webapp/services/runtime_bridge.py`
- `webapp/templates/results.html`
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
- `tests/test_integration.py`
- `tests/test_journal.py`
- `tests/test_journal_reconciliation.py`
- `tests/test_eve_sso.py`
- `tests/test_execution_plan.py`
- `tests/test_portfolio.py`
- `tests/test_route_search.py`
- `tests/test_risk_profiles.py`
- `tests/test_webapp.py`
- `tests/test_runtime_cleanup.py`
- current `git status`
- `python -m pytest -q`
- focused live CLI run on 2026-03-08 using local overlay config
- replay CLI run on 2026-03-08 against the freshly written live snapshot
- real HTTP `uvicorn` checks for `/analysis` replay and long-running live POST

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
- safe CLI `clean` / `cleanup` mode for removing generated reports, snapshots,
  transient HTTP/type caches, and Python cache directories while preserving
  local auth tokens, character cache, and journal state
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
- route-profile, chain, roundtrip, leaderboard, and no-trade text artifacts
  now distinguish between actionable routes/legs and aggregate sequential or
  alternative totals instead of implying one simultaneous executable spend
- execution-plan / leaderboard rendering now only shows internal-route floor
  metadata for actual `internal_self_haul` routes instead of leaking that
  floor onto external shipping routes
- price-sensitive or otherwise materially repriced picks now show an explicit
  profit-basis block in execution plans: quote basis, visible-book profit
  proxy, conservative executable profit proxy, retention, and the displayed
  profit basis used in the plan
- final route-mix cleanup in `runtime_runner.py` now removes some weak
  speculative / price-sensitive tail picks more aggressively when route quality
  improves, profit share stays small, and route score remains effectively intact
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
- a local FastAPI + Jinja2 web UI now exists under `webapp/` with dashboard,
  analysis, journal, character, and config pages
- the web UI reuses existing runtime, journal, calibration, and character
  functions through a service layer; it does not replace or break the CLI
- the local web UI now has a small private-deploy access seam: if a web
  password is configured it requires HTTP Basic Auth, otherwise non-local
  requests are blocked instead of exposing the app unguarded
- without a web password, that seam now only treats direct localhost request
  shape as the supported unprotected mode; proxy-shaped requests require
  protection instead of sliding through as local
- that web seam is intentionally aimed at private single-user operation; public
  multi-user hardening remains out of scope for this block
- sensitive web pages now receive redacted or sanitized view models instead of
  the broader raw config/context payloads previously passed into templates
- web security regressions now cover `Cache-Control: no-store`, config
  redaction, and proxy-shaped request classification; minimal CI uses the same
  `scripts/quality_check.py` path as local quality runs
- full analysis runs in the web UI currently use an in-process bridge to
  `runtime_runner.run_cli()` and read the existing artifact files instead of
  re-implementing trading logic
- focused live verification on 2026-03-08 produced a real actionable
  `o4t -> jita_44` route and wrote a reusable replay snapshot outside the repo
- live and replay now produce the same deterministic `plan_id` / `pick_id`
  set when they run against the same snapshot and inputs; only timestamped text
  artifact filenames still differ between runs
- internal structure-to-structure nullsec routes are now classified centrally
  as `internal_self_haul` in `shipping.py`; they no longer get blocked just
  because no external ITL/HWL lane exists
- Jita routes still use the existing external shipping model; the new internal
  self-haul policy does not zero out Jita transport costs
- the default repo config now includes `structure_regions` for `UALX-3`
  (`1046664001931 -> 10000061`) and `R-ARKN`
  (`1048663825563 -> 10000039`), so `planned_sell` no longer becomes
  unnecessarily restrictive on those internal targets
- the duplicate `structures` alias `c-j6mt` was removed from `config.json`;
  canonical startup still uses required key `cj6`, while shipping/route label
  normalization continues to understand `cj6`, `c-j6mt`, and `1st`
- `trade_plan_*.json` now preserves route budget/cargo/cost metrics for browser
  parity and no longer serializes `instant` picks with `proposed_sell_price=0`
- `trade_plan_*.json` route entries now also preserve presentation-only
  corridor display metadata for browser parity with execution-plan text output
- corridor display now keeps direct legs first but still preserves longer
  profitable spans and Jita connector routes instead of collapsing the view to
  nearest-leg-only output
- internal corridor travel can now optionally add a directed Ansiblex layer
  from `docs/Ansis.txt`; gate travel remains available and the route-search
  scoring path stays untouched
- route and pick transport summaries now preserve internal travel metadata:
  gate-leg count, ansiblex-leg count, estimated ansiblex logistics cost, and
  profit before vs after logistics
- execution plans, browser results, and `trade_plan_*.json` now surface those
  internal travel fields so ansiblex usage is visible without inventing a
  second ranking model
- the repo now also has a small config-driven candidate-node seam for Imperium
  watch systems: `station_candidate`, `market_candidate`, and
  `corridor_checkpoint` stay distinct instead of implicitly treating every
  named system as a real station market
- candidate-node hits are display-only metadata on routes; execution plans,
  browser results, and `trade_plan_*.json` can now show when a route starts,
  ends, or passes through such a configured node
- the web runtime bridge now captures `Replay-Snapshot geschrieben: ...` from
  live runs, so the browser shows the real snapshot path after a live analysis
- the local web app no longer uses a browser heartbeat or idle auto-shutdown;
  it now stays up until the operator stops the process explicitly
- the web journal page now surfaces current cached character snapshot data
  (open orders plus wallet transaction/journal counts) even when the local
  journal DB is empty; opening the dedicated Reconcile/Unmatched tabs now
  triggers the real reconciliation flow instead of showing an inert placeholder
- the `/analysis` and `/analysis/run` browser layout now allows analysis cards
  and log/report blocks to shrink correctly within the viewport; long paths and
  runtime logs no longer create page-wide horizontal overflow
- a new real-data replay regression fixture now exists:
  `tests/fixtures/replay_live_focused_o4t_jita_20260308.json`
- all webapp routes are confirmed reachable (200 OK) under real service data
  after session 13 bug fixes; `GET /analysis` was previously returning 500
- local journal initialization now migrates older `trade_journal.sqlite3`
  schemas before creating reconciliation-related indexes, so existing caches do
  not break dashboard or journal pages after schema expansion
- configurable risk profiles (6 built-in) with end-to-end enforcement in
  `runtime_runner.py`: candidate filter, min_profit_per_m3 gate,
  min_confidence gate, portfolio config, and route score multiplier
- route-profile pick filtering is now shared across `run_route()` and
  `run_route_wide_leg()`: pick-level expected profit, profit density,
  confidence, and max-budget-share rules are enforced after final transport and
  calibration data exist
- candidate quality is now gated more conservatively through the existing
  market-plausibility seam: fragile book structure, weak profit retention after
  repricing, and manipulation-heavy setups can now hard-reject a candidate even
  when paper profit still looks attractive
- replay-guided calibration on 2026-03-13 softened only the generic
  `DEPTH_COLLAPSE` / `ORDERBOOK_CONCENTRATION` quality penalties and the
  candidate-stage confidence haircut, so robust survivors with decent
  retention can remain actionable without re-admitting fake-spread /
  unusable-depth bait
- `instant` candidates no longer recover artificially high overall confidence
  after the market-quality haircut; route-level confidence now also caps itself
  by the average pick market quality instead of only fill/transport confidence
- final pick selection now uses the same quality-aware scoring seam in
  portfolio ranking, local search, and cargo fill, so thin-book or
  price-sensitive candidates are less likely to re-enter as final picks after
  surviving initial generation
- `mandatory` pick labeling is now stricter for instant exits: price-sensitive
  or low market-quality picks are downgraded to optional/speculative instead of
  being presented as first-buy convictions
- cargo-fill picks can no longer bypass the visible profile
  `Max Budget/Item`; profile application now clamps cargo-fill share caps to
  the same effective item-share limit shown in the output
- internal `internal_self_haul` routes now also pass through an explicit
  operational expected-profit floor
  (`route_search.internal_self_haul_min_expected_profit_isk`, default
  `2,000,000 ISK`) so low-signal internal routes are suppressed instead of
  shown as actionable
- execution-plan totals now distinguish between the single best actionable
  route and aggregate totals across alternative routes, with explicit wording
  that the aggregate is not one combined executable plan
- final route results now pass through a small post-selection route-mix cleanup
  in `runtime_runner.py`: clearly weak optional/speculative add-on picks can be
  removed after selection when they only contribute a small profit share but
  materially improve route confidence / market-quality and do not materially
  worsen the route score
- route prune reasons are now more specific for common failure families:
  no candidates, profit floor, confidence, budget rule, fill/depth, sell time,
  invalid volume, post-portfolio constraints, and internal route floor
- missing or invalid type volume is no longer silently normalized into a cheap
  executable pick path; invalid volume now stays invalid and is surfaced via
  `invalid_volume` / `candidates_invalid_volume`
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
- the repo now has a low-risk clean-start path for report clutter and oversized
  transient runtime caches
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
- the web UI currently depends on stdout/artifact parsing for full analysis
  runs; that is acceptable for an MVP but still tighter coupling than a future
  structured runtime API
- the default operator config is broad enough that a naive live full-run can
  take several minutes and fetch far more markets than a focused regression run
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
  views, normal runtime output, execution plans, and the adjacent no-trade /
  summary artifacts, but the non-CLI web surfaces still intentionally stay
  lighter-weight
- the personal decision layer is intentionally narrow: it only adjusts
  `decision_overall_confidence` with hard caps and explainability, so evidence
  for broader scope tuning is still limited
- transport policy now has two explicit modes in practice: external shipping
  for Jita-connected routes and `internal_self_haul` for internal nullsec
  structure routes. Future internal ansiplex/fuel/risk surcharges can attach to
  the same central transport-mode seam.
- the new ansiblex travel layer is intentionally narrow and topology-driven:
  `docs/Ansis.txt` is the source of truth, edges are directed only, and no
  automatic reverse bridges are inferred

## Current Focus

Observed worktree activity on 2026-03-13 suggests current feature work is
centered on:

- hard pick-level profile enforcement and explainable prune reasons
- route-ranking adjustments by profile
- replay-based calibration of market-quality and anti-bait thresholds
- post-selection route-mix cleanup for weak optional/speculative add-ons
- execution-plan and summary-output restructuring with honest
  aggregate-vs-actionable / sequential-leg semantics
- CLI/runtime integration for profile-aware output
- targeted core-logic cleanup in portfolio construction and volume handling
- optional private character-context integration and cacheable ESI sync
- wallet-to-journal reconciliation and personal trade-history reporting
- wallet paging, freshness visibility, and conservative fee/ref matching for
  older or truncated snapshots
- personal journal analytics and a separate personal calibration basis
- an explicit, bounded personal decision layer with strict
  sample-size/data-quality guardrails and visible explainability
- compact runtime visibility for personal-history quality, fallback reasons,
  and applied scoped personal adjustments
- a first local browser UI over the existing runtime and journal workflows
- local browser hardening plus corridor-ordered route presentation near the
  web entry and execution-plan path
- additive internal travel realism for `internal_self_haul` routes through a
  small directed ansiblex layer and more transparent route/output travel
  metadata
- cautious preparation for Imperium watch nodes and future market/station
  expansion without hardcoding unverified hubs into route-search logic

Files that indicate this focus:

- `candidate_nodes.py`
- `risk_profiles.py`
- `runtime_runner.py`
- `runtime_common.py`
- `candidate_engine.py`
- `route_search.py`
- `portfolio_builder.py`
- `execution_plan.py`
- `runtime_clients.py`
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
- `webapp/app.py`
- `webapp/routes/pages.py`
- `webapp/services/runtime_bridge.py`
- `tests/test_webapp.py`

## Known Issues And Uncertainties

- Route-profile, chain, roundtrip, leaderboard, and no-trade text outputs now
  share the same honest aggregate semantics and preserve internal-route floor
  messaging, but browser/UI surfaces were not re-audited in this session.
- the new web protection seam is intentionally small and private-deploy
  oriented; it is not a full multi-user auth/session system
- without a web password, the supported web mode is now direct localhost use by
  one operator; proxy-/tunnel-shaped requests are blocked and non-local private
  use requires a password
- public multi-user web hardening, session/role controls, and stronger reverse-
  proxy trust handling remain explicit follow-up work rather than implied
  guarantees of the current seam
- a fully opaque local proxy that strips all proxy hints before forwarding is
  not distinguishable from a direct localhost client at the HTTP app layer; the
  supported operator rule therefore stays simple: any proxy/tunnel deployment
  should be treated as password-required
- the corridor ordering is presentation-only and intentionally leaves route
  search formulas, ranking, and scoring untouched
- ansiblex travel currently uses a constant per-edge distance estimate because
  `docs/Ansis.txt` carries topology only, not geometric LY distances
- internal ansiblex/gate path metadata only exists for route-chain systems that
  are explicitly mapped through `route_chain.legs[].system`
- candidate nodes are intentionally descriptive only in this block: they do not
  fetch markets, create routes, or turn a system into a location/structure by
  themselves
- the default candidate-node block is intentionally cautious: the current
  Imperium watch list is preloaded as `market_candidate` or
  `corridor_checkpoint`; no default node in this block is hardcoded as a real
  `station_candidate`
- replay calibration used the focused O4T/Jita fixture plus a narrow
  `replay_snapshot.json` route search. Those checks confirmed that prior bait
  picks such as `Large Warhead Calefaction Catalyst II`, `IFFA Compact Damage
  Control`, `Heavy Gremlin Compact Energy Neutralizer`, and `Drone
  Mutaplasmid Residue` stayed out, while robust survivors like
  `Polarized Heavy Neutron Blaster` and `Noise-25 'Needlejack' Filament`
  regained stronger actionable labeling.
- route confidence can still be pulled down by a weak optional pick because
  `route_search.py` intentionally caps by average pick market quality across
  the whole selected route mix. That behavior was left unchanged in this
  session.
- a narrow post-selection route-mix cleanup seam now exists, but the current
  narrow `replay_snapshot.json` rerun did not previously produce a live removal
  after the latest market-quality calibration; the cleanup is now slightly more
  willing to drop weak speculative / price-sensitive tails, but still only when
  score retention remains high and route confidence / quality recover.
- execution-plan profit-basis transparency is now much better for PRICE-SENS
  picks, but it still explains the conservative basis via profit proxies and
  implied net-exit math rather than a separately persisted repriced unit sell
  quote.
- `route_search.py` speculative penalty was re-reviewed on 2026-03-07. The
  small planned-share term still looks like a separate route-composition risk
  heuristic, not a confirmed double-counting defect, so no change was made.
- Invalid type volume is now conservatively rejected instead of silently
  coerced to a fallback value. A future follow-up may still want an active
  cache/backfill repair path for missing volumes before candidate rejection.
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
- The local web UI is now fully reachable on all routes (session 13 fixed
  `GET /analysis` 500, dashboard stat mismatches, and input parse robustness).
  Full-run analysis still depends on CLI-style stdout and artifact contracts
  exposed by `runtime_runner.py`.
- Browser analysis no longer depends on heartbeat semantics; the local web app
  stays alive until it is stopped explicitly.
- The local journal remains plan-centric by design: overview/open/closed/report/
  personal/calibration still depend on imported or recorded journal entries.
  The web UI now makes that clearer by showing character snapshot counts and by
  fetching real reconcile/unmatched data on the dedicated tabs.
- Stable replay IDs now intentionally reuse the same `trade_plan_<plan_id>.json`
  filename for identical snapshot+input runs. That improves reproducibility and
  journal parity, but the canonical trade-plan file is overwritten when the
  content is recomputed for the same plan.
- Legacy local journal databases with missing reconciliation columns are now
  upgraded in place on startup instead of failing during index creation.
- Matching remains intentionally honest rather than magical: ambiguous
  transactions stay visible as uncertain, and unmatched wallet activity is
  reported separately instead of being forced onto a trade entry.
- This session did not perform a full code audit, so undocumented modules may
  contain behavior not yet reflected here.
- `config.local.json` exists locally but is Git-ignored; secret values were not
  inspected.
- `clean` / `cleanup` is intentionally conservative: it preserves
  `cache/token.json`, `cache/trade_journal.sqlite3`, and
  `cache/character_context/` rather than doing a full local identity/history
  reset.
- Always check `git status --short` before editing. This repository often has
  in-flight work on core runtime and journal modules.

## Working Assumptions For Future Sessions

- branch `dev` is the correct working branch unless the user says otherwise
- future AI tasks should start from control files, then open only the module
  that owns the requested behavior
- documentation-first, targeted edits are preferred over broad refactors
