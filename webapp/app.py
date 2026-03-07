from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from webapp.routes.pages import router as pages_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Nullsec Trader Tool Web",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    base_dir = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
    app.include_router(pages_router)
    return app


def run_dev_server() -> None:
    import uvicorn

    uvicorn.run("webapp.app:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run_dev_server()
