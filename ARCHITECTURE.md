# Architecture

## Productive Runtime Path

The productive startup path is:

1. `run.bat` or `run_trader.ps1`
2. [`main.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/main.py)
3. [`runtime_runner.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/runtime_runner.py): `run_cli()`

[`nullsectrader.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/nullsectrader.py) is not part of the CLI path. It remains only as the stable top-level import surface used by tests and local tooling. It contains no business logic.

## Productive Modules

Productive runtime/orchestration:

- [`runtime_common.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/runtime_common.py): CLI parsing, runtime paths, shared helpers
- [`runtime_clients.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/runtime_clients.py): live and replay ESI clients
- [`runtime_runner.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/runtime_runner.py): replay/live loading, route execution, chain orchestration
- [`runtime_reports.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/runtime_reports.py): CSV and chain/summary outputs
- [`journal_cli.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/journal_cli.py): local journal commands for importing plans and recording real trades

Trading/domain source of truth:

- [`candidate_engine.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/candidate_engine.py): candidate generation, planned-sell logic, route-wide candidate scoring
- [`journal_models.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/journal_models.py), [`journal_store.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/journal_store.py), [`journal_reporting.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/journal_reporting.py): trade-plan identifiers, local journal persistence, and plan-vs-reality reporting
- [`shipping.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/shipping.py): transport pricing, route blocking, per-pick transport allocation
- [`portfolio_builder.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/portfolio_builder.py): risk-weighted portfolio construction
- [`route_search.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/route_search.py): route search profile generation and risk-adjusted ranking inputs
- [`execution_plan.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/execution_plan.py): route-profile execution plan and leaderboard rendering
- [`fees.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/fees.py) and [`fee_engine.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/fee_engine.py): fee calculations
- [`market_fetch.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/market_fetch.py): node order loading
- [`market_normalization.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/market_normalization.py): replay snapshot normalization
- [`startup_helpers.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/startup_helpers.py): structure/node/chain resolution

## Thin Facades

- [`nullsectrader.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/nullsectrader.py): stable top-level import surface and direct module entrypoint
- [`test_nullsectrader.py`](/c:/Users/marck/Desktop/Echos%20of%20Null/nullsec_trader_tool/test_nullsectrader.py): lightweight compatibility test launcher

## Source Of Truth By Core Rule

- Fees: `fees.py` / `fee_engine.py`
- Shipping and route transport blocking: `shipping.py`
- Candidate generation and planned sell modeling: `candidate_engine.py`
- Route scoring/search ranking: `route_search.py`
- Portfolio building: `portfolio_builder.py`
- Route-profile execution-plan rendering: `execution_plan.py`
- Runtime orchestration: `runtime_runner.py`

## Runtime Notes

- Missing shipping models block routes by default in `shipping.py`.
- Route-profile and chain outputs are rendered by separate modules, but the route decision path is single-source:
  candidate generation -> portfolio building -> shipping adjustment/blocking -> execution-plan/report rendering.
- Replay and live mode share the same orchestration path. Only the client implementation changes.
