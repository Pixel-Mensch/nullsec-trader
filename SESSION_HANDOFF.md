# Session Handoff

Date: 2026-03-08 (session 18 remove web heartbeat)
Branch: `dev`

## Completed This Session

Removed the local webapp heartbeat and idle auto-shutdown path. The browser no
longer posts `/heartbeat`, and the FastAPI app now stays up until it is stopped
explicitly.

## Root Cause

- `webapp/app.py` still carried a browser-heartbeat endpoint, request-tracking
  middleware, and an auto-exit watcher thread
- `webapp/templates/base.html` posted heartbeat pings every 5 seconds
- that lifecycle behavior was no longer wanted and added avoidable local
  process churn

## What Changed

- `webapp/app.py`
  - removed heartbeat timeout state, request-tracking middleware, shutdown
    watcher thread, and `/heartbeat` route
  - kept `create_app()` as a plain FastAPI app factory with static mount and
    page router registration
- `webapp/templates/base.html`
  - removed the inline browser heartbeat script
- `tests/test_webapp.py`
  - removed the shutdown watcher test tied to internal heartbeat state
  - added a regression that asserts `POST /heartbeat` now returns `404`
- control files updated to reflect that the web app no longer uses heartbeat
  lifecycle behavior

## Tests And Verification

- Targeted regression:
  - `python -m pytest -q tests/test_webapp.py`
    -> **9 passed**

## Remaining Limits

- the local web server now remains running until it is stopped manually; there
  is no automatic idle exit anymore

## Files Touched

- `webapp/app.py`
- `webapp/templates/base.html`
- `tests/test_webapp.py`
- `PROJECT_STATE.md`
- `TASK_QUEUE.md`
- `ARCHITECTURE.md`
- `SESSION_HANDOFF.md`
