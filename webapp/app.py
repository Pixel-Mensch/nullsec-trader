from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.routes.pages import router as pages_router

_HEARTBEAT_TIMEOUT = 12  # seconds without a ping before auto-shutdown
_last_ping: float = time.time()
_shutdown_timer_started = False


def _shutdown_watcher() -> None:
    global _shutdown_timer_started
    while True:
        time.sleep(2)
        if time.time() - _last_ping > _HEARTBEAT_TIMEOUT:
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
