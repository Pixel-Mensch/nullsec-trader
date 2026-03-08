from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from webapp.services import analysis_service, character_service, config_service, dashboard_service, journal_service


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _render(request: Request, template_name: str, **context):
    return templates.TemplateResponse(request, template_name, {"request": request, **context})


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return _render(request, "dashboard.html", page="dashboard", data=dashboard_service.get_dashboard_data())


@router.get("/analysis", response_class=HTMLResponse)
def analysis_form(request: Request):
    return _render(request, "analysis.html", page="analysis", data=analysis_service.get_analysis_form_data(), result=None)


@router.post("/analysis/run", response_class=HTMLResponse)
def analysis_run(
    request: Request,
    budget_isk: str = Form(""),
    cargo_m3: str = Form(""),
    snapshot_only: bool = Form(False),
    use_replay: bool = Form(False),
    risk_profile: str = Form(""),
):
    result = analysis_service.run_analysis(
        budget_isk_raw=budget_isk,
        cargo_m3_raw=cargo_m3,
        snapshot_only=bool(snapshot_only),
        use_replay=bool(use_replay),
        risk_profile=str(risk_profile or ""),
    )
    return _render(request, "results.html", page="analysis", result=result, data=result.get("form", analysis_service.get_analysis_form_data()))


@router.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, tab: str = "overview", limit: int = 20):
    data = journal_service.get_journal_page(tab=tab, limit=limit)
    return _render(request, "journal.html", page="journal", data=data)


@router.get("/journal/reconcile", response_class=HTMLResponse)
def journal_reconcile_page(request: Request, limit: int = 20):
    data = journal_service.run_reconciliation(limit=int(limit))
    return _render(request, "journal.html", page="journal", data=data)


@router.post("/journal/reconcile", response_class=HTMLResponse)
def journal_reconcile(request: Request, limit: int = Form(20)):
    data = journal_service.run_reconciliation(limit=int(limit))
    return _render(request, "journal.html", page="journal", data=data)


@router.get("/journal/unmatched", response_class=HTMLResponse)
def journal_unmatched(request: Request, limit: int = 20):
    data = journal_service.get_unmatched_page(limit=int(limit))
    return _render(request, "journal.html", page="journal", data=data)


@router.get("/character", response_class=HTMLResponse)
def character_page(request: Request):
    return _render(request, "character.html", page="character", data=character_service.get_character_page())


@router.post("/character/auth/{action}", response_class=HTMLResponse)
def character_auth_action(request: Request, action: str):
    return _render(request, "character.html", page="character", data=character_service.run_auth_action(action))


@router.post("/character/context/{action}", response_class=HTMLResponse)
def character_context_action(request: Request, action: str):
    return _render(request, "character.html", page="character", data=character_service.run_character_action(action))


@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
    return _render(request, "config.html", page="config", data=config_service.get_config_page())
