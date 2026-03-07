# AGENTS.md

## Purpose

This repository is maintained by humans and AI coding agents.
The priority is small, reliable changes with low context cost and clean handoffs.

Work should leave the repository in a state where the next session can continue
without re-scanning the whole project.

---

## 1. Mandatory Read Order

Before inspecting code, read these files in this order:

1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `TASK_QUEUE.md`
4. `ARCHITECTURE.md`
5. `SESSION_HANDOFF.md`
6. `README.md`

If you are working through GitHub Copilot or an IDE Copilot surface, read
`.github/copilot-instructions.md` after the list above.

Only after that should you open task-relevant code.

If a relevant module map exists under `docs/module-maps/`, read that map before
opening a large source file.

---

## 2. Repository Scanning Rules

Do not scan the entire repository by default.

Start narrow:

- check `git branch --show-current`
- check `git status --short`
- inspect the root file list
- read `pyproject.toml`
- read `config.json`
- read the true entry path: `main.py` -> `runtime_runner.py`

Open other files only when the task clearly requires them.

Avoid loading these paths unless the task depends on them:

- `cache/`
- `__pycache__/`
- `.pytest_cache/`
- `.claude/`
- large test fixtures under `tests/fixtures/`

Large file hotspots such as `runtime_runner.py` and `candidate_engine.py` are
expensive to load. Prefer the architecture map first, then a relevant file in
`docs/module-maps/`, then open the specific module that owns the behavior you
need.

---

## 3. Branch Workflow

Default working branch: `dev`

Rules:

- work on `dev` unless instructed otherwise
- if `dev` does not exist, create it from `main`
- never commit directly to `main` unless explicitly requested
- expect a dirty worktree; never revert unrelated user changes

---

## 4. Git and Push Discipline

When Git is available:

- complete each self-contained task with a commit
- use a clear commit message that states what changed and why
- after completing the task and updating the control files, push the branch to GitHub
- do not leave completed work only in the local working tree unless explicitly requested

Before editing, inspect `git status --short` so you know what is already in
progress.

---

## 5. Project Control Files

These files are the coordination layer for AI sessions and must stay current.

### `PROJECT_STATE.md`

Keep a concise snapshot of:

- project goals
- confirmed implemented features
- known issues and uncertainties
- current focus areas

### `TASK_QUEUE.md`

Track upcoming work as small, actionable tasks.

Each task should include:

- description
- priority
- relevant files
- expected result

### `ARCHITECTURE.md`

Document the smallest useful technical map:

- real entry points
- module ownership
- runtime flow
- where to look for common task types

### `SESSION_HANDOFF.md`

Update this at the end of every session with:

- what changed
- what was verified
- open risks or unknowns
- next recommended task
- files touched

---

## Module Maps

Before opening large source files, check whether a module map exists.

Module maps are located in:

- `docs/module-maps/`

Agents must read the relevant module map first if available.

Module maps help identify:

- ownership
- entry points
- dependencies
- tests
- risk areas

Keep module maps short and practical, and update them when the owned behavior
or entry points materially change.

---

## 6. Security Rules

Never commit or expose secrets.

Specific repo rules:

- do not inspect or quote values from `config.local.json` unless the user asks
- prefer `config.local.example.json` when documenting local config
- never commit `.env` files, tokens, or copied credentials
- do not add new remote services or network integrations without explanation

---

## 7. Testing and Verification

Before finishing:

- run targeted tests if practical
- if no tests are run, say so explicitly and explain why
- if behavior or architecture changed, update docs in the same session

Known test entry points:

- `python -m pytest -q`
- `python tests/run_all.py`
- `python test_nullsectrader.py`
- `python scripts/quality_check.py`

Prefer targeted `pytest` runs before broad test commands.

---

## 8. Definition Of Done

A task is done only when:

- requested changes are implemented
- tests were run or intentionally skipped
- relevant control files were updated
- `SESSION_HANDOFF.md` was updated
- the work was committed with a meaningful message
- the current branch was pushed to GitHub unless explicitly told not to

---

## 9. Documentation Discipline

When behavior, structure, or workflow changes, update the relevant docs in the
same session.

Minimum rule:

- behavior or architecture change -> update `PROJECT_STATE.md` and `ARCHITECTURE.md`
- task status change -> update `TASK_QUEUE.md`
- any completed work -> update `SESSION_HANDOFF.md`

---

## 10. Subdirectory Overrides

If a subdirectory contains its own `AGENTS.md`, that file overrides this one
for work inside that subtree.

As of 2026-03-07, no subdirectory override was detected in this repository.

---

## 11. Working Style

Agents should:

- document uncertainty instead of inventing details
- prefer targeted documentation before refactoring
- preserve the current codebase unless a small fix is necessary
- optimize for future handoffs, not one-session convenience

End of file.
