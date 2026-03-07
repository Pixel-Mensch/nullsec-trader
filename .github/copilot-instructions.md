# GitHub Copilot Instructions

Use the repository control files as the source of truth.

Before inspecting code, read:

1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `TASK_QUEUE.md`
4. `ARCHITECTURE.md`
5. `SESSION_HANDOFF.md`
6. `README.md`

## Workflow

- work on `dev` unless instructed otherwise
- prefer small focused changes
- do not scan the whole repository by default
- start with root docs, `pyproject.toml`, `config.json`, `main.py`, and
  `runtime_runner.py`
- open only the module that owns the requested behavior
- do not refactor unrelated modules just to "clean things up"

## Security

- never commit secrets or credentials
- do not inspect or quote values from `config.local.json` unless the user asks
- prefer `config.local.example.json` when documenting setup

## High-Value Entry Points

- CLI entry: `main.py`
- runtime orchestration: `runtime_runner.py`
- CLI parsing and shared helpers: `runtime_common.py`
- config load and validation: `config_loader.py`
- candidate logic: `candidate_engine.py`
- route ranking: `route_search.py`
- execution-plan output: `execution_plan.py`
- journal and calibration: `journal_cli.py`, `journal_store.py`,
  `confidence_calibration.py`

## Documentation Discipline

If behavior or architecture changes, update:

- `PROJECT_STATE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`

If task status changes, update:

- `TASK_QUEUE.md`

## Testing

- prefer targeted `pytest` runs first
- broader options: `python -m pytest -q`, `python tests/run_all.py`,
  `python test_nullsectrader.py`

Keep the repository handoff-ready for the next session.
