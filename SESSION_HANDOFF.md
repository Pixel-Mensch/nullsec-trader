# Session Handoff

Date: 2026-03-14 (session 25 clean-start command)
Branch: `dev`

## Completed This Session

Added a safe operator-facing clean-start command so the repo can be reset for a
fresh runtime without manually deleting dozens of generated artifacts or wiping
local auth/journal state.

## Root Cause

- the tool writes many timestamped reports, snapshots, and large transient HTTP
  caches into the working tree during normal use
- there was no first-class cleanup path, so a "clean restart" required manual
  deletion and carried needless risk around tokens, journal data, and cached
  character state
- `.gitignore` already treated most of these outputs as ephemeral, which made a
  small explicit cleanup seam the low-risk fix

## What Changed

- `runtime_common.py`
  - `parse_cli_args()` now recognizes `clean` and `cleanup` as a dedicated
    maintenance command
- `runtime_cleanup.py`
  - new focused helper module for safe cleanup target discovery and deletion
  - removes generated root artifacts plus `cache/http_cache.json`,
    `cache/types.json`, `.pytest_cache`, and recursive `__pycache__`
  - preserves `cache/token.json`, `cache/trade_journal.sqlite3`, and
    `cache/character_context/`
- `runtime_runner.py`
  - `run_cli()` now dispatches `python main.py clean` before config loading
    and prints a concise cleanup summary
- `.gitignore`
  - now also ignores `roundtrip_plan_*.txt`, `no_trade_*.txt`,
    `trade_plan_*.json`, and `snapshot_*.json`
- `README.md` / control files
  - documented the new clean-start path and its safety boundaries

## Runtime Verification

- executed `python main.py clean` in the repo root
- result: **111 files** and **7 directories** removed
- preserved state confirmed afterwards:
  - `cache/token.json`
  - `cache/trade_journal.sqlite3`
  - `cache/character_context/`

## Tests And Verification

- focused regression:
  - `pytest -q tests/test_runtime_cleanup.py tests/test_config.py tests/test_character_context.py tests/test_execution_plan.py -k "clean or parse_cli_args or compact_flag"`
    -> **8 passed**
- new coverage proves:
  - CLI parsing recognizes `clean`
  - cleanup removes generated artifacts and transient caches
  - cleanup preserves auth token, journal DB, and character-context cache

## Remaining Limits

- this is a safe cleanup, not a destructive full reset; operator identity,
  journal history, and character cache are intentionally retained
- if a future session needs a full credential/history wipe, that should be a
  separate explicit command or manual step, not folded into `clean`
- an unrelated pre-existing local modification in `location_utils.py` remains
  intentionally untouched

## Files Touched

- `.gitignore`
- `runtime_common.py`
- `runtime_cleanup.py`
- `runtime_runner.py`
- `tests/run_all.py`
- `tests/test_runtime_cleanup.py`
- `README.md`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
