from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.routes.pages import router as pages_router

_HEARTBEAT_TIMEOUT = 12  # seconds without a ping before auto-shutdown
_last_ping: float = time.time()
_shutdown_timer_started = False
_active_request_count = 0
_app_state_lock = threading.Lock()


def _request_started() -> None:
    global _active_request_count
    with _app_state_lock:
        _active_request_count += 1


def _request_finished() -> None:
    global _active_request_count
    with _app_state_lock:
        _active_request_count = max(0, int(_active_request_count) - 1)


def _should_auto_shutdown(now: float | None = None) -> bool:
    current = time.time() if now is None else float(now)
    with _app_state_lock:
        active_request_count = int(_active_request_count)
        last_ping = float(_last_ping)
    if active_request_count > 0:
        return False
    return (current - last_ping) > _HEARTBEAT_TIMEOUT


def _shutdown_watcher() -> None:
    global _shutdown_timer_started
    while True:
        time.sleep(2)
        if _should_auto_shutdown():
            print("\n[webapp] Kein Browser-Tab mehr offen – Server beendet sich.", flush=True)
            os._exit(0)


def create_app() -> FastAPI:
    global _shutdown_timer_started
    app = FastAPI(
        title="Nullsec Trader Tool Web",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    base_dir = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
    app.include_router(pages_router)

    @app.middleware("http")
    async def _track_active_requests(request: Request, call_next):
        _request_started()
        try:
            return await call_next(request)
        finally:
            _request_finished()

    @app.post("/heartbeat")
    def heartbeat() -> JSONResponse:
        global _last_ping
        _last_ping = time.time()
        return JSONResponse({"ok": True})

    if not _shutdown_timer_started:
        _shutdown_timer_started = True
        t = threading.Thread(target=_shutdown_watcher, daemon=True)
        t.start()

    return app


def run_dev_server() -> None:
    import uvicorn

    uvicorn.run("webapp.app:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run_dev_server()
