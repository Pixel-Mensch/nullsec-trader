from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config_loader import load_config
from webapp.routes.pages import router as pages_router
from webapp.security import _is_local_host, enforce_request_access, resolve_access_settings


def create_app() -> FastAPI:
    cfg = load_config()
    app = FastAPI(
        title="Nullsec Trader Tool Web",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.web_access_settings = resolve_access_settings(cfg)

    @app.middleware("http")
    async def _web_access_guard(request, call_next):
        blocked = enforce_request_access(request, app.state.web_access_settings)
        if blocked is not None:
            return blocked
        response = await call_next(request)
        access = getattr(request.state, "web_access", {})
        if isinstance(access, dict) and bool(access.get("sensitive_path", False)):
            response.headers["Cache-Control"] = "no-store"
        return response

    base_dir = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
    app.include_router(pages_router)
    return app


def run_dev_server() -> None:
    import uvicorn

    cfg = load_config()
    web_cfg = dict(cfg.get("webapp", {}) or {}) if isinstance(cfg.get("webapp", {}), dict) else {}
    host = str(os.environ.get("NULLSEC_WEBAPP_HOST", "") or web_cfg.get("host", "127.0.0.1") or "127.0.0.1").strip()
    port = int(os.environ.get("NULLSEC_WEBAPP_PORT", "") or web_cfg.get("port", 8000) or 8000)
    access_settings = resolve_access_settings(cfg)
    if not _is_local_host(host):
        if access_settings["password_configured"]:
            print(f"[webapp] Non-local bind {host}:{port} with password protection enabled.")
        else:
            print(
                "[webapp] WARN: non-local bind without web password. "
                "Only direct localhost requests will work until NULLSEC_WEBAPP_PASSWORD or webapp.access_password is set."
            )
    uvicorn.run("webapp.app:create_app", factory=True, host=host, port=port, reload=False)


if __name__ == "__main__":
    run_dev_server()
