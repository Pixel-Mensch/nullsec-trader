from __future__ import annotations

from confidence_calibration import (
    build_confidence_calibration,
    build_personal_calibration_summary,
    format_confidence_calibration_report,
    format_personal_calibration_summary,
)
from config_loader import load_config
from character_profile import resolve_character_context
from journal_reporting import (
    format_closed_positions,
    format_journal_overview,
    format_journal_report,
    format_open_positions,
    format_personal_trade_history,
    format_reconciliation_overview,
    format_unmatched_wallet_activity,
)
from journal_store import (
    fetch_closed_journal_entries,
    fetch_journal_entries,
    fetch_open_journal_entries,
    initialize_journal_db,
    reconcile_journal_with_character_context,
    resolve_journal_db_path,
)


JOURNAL_TABS = ("overview", "open", "closed", "report", "reconcile", "personal", "unmatched", "calibration")
_LAST_RECONCILIATION_RESULT: dict | None = None


def _load_entries(db_path: str) -> list[dict]:
    initialize_journal_db(db_path)
    return fetch_journal_entries(db_path, limit=250)


def _placeholder_text(tab: str) -> str:
    if tab == "reconcile":
        return "Noch keine Reconciliation im Web-UI-Lauf ausgefuehrt. Nutze 'Run Reconcile'."
    if tab == "unmatched":
        return "Noch keine Reconciliation-Daten fuer ungematchte Wallet-Aktivitaet vorhanden."
    return "Noch keine Daten vorhanden."


def get_journal_page(tab: str = "overview", *, limit: int = 20) -> dict:
    cfg = load_config()
    db_path = resolve_journal_db_path(None)
    entries = _load_entries(db_path)
    active_tab = str(tab or "overview").strip().lower()
    if active_tab not in JOURNAL_TABS:
        active_tab = "overview"
    content = ""
    if active_tab == "overview":
        content = format_journal_overview(entries, limit=limit)
    elif active_tab == "open":
        content = format_open_positions(fetch_open_journal_entries(db_path, limit=250), limit=limit)
    elif active_tab == "closed":
        content = format_closed_positions(fetch_closed_journal_entries(db_path, limit=250), limit=limit)
    elif active_tab == "report":
        content = format_journal_report(entries, limit=min(25, limit))
    elif active_tab == "personal":
        content = format_personal_trade_history(entries, limit=min(25, limit))
    elif active_tab == "calibration":
        generic = format_confidence_calibration_report(build_confidence_calibration(entries, cfg), limit=5)
        personal = format_personal_calibration_summary(build_personal_calibration_summary(entries, cfg), limit=5)
        content = f"{generic}\n\n{personal}"
    elif active_tab in {"reconcile", "unmatched"} and isinstance(_LAST_RECONCILIATION_RESULT, dict):
        content = (
            format_reconciliation_overview(_LAST_RECONCILIATION_RESULT, limit=min(25, limit))
            if active_tab == "reconcile"
            else format_unmatched_wallet_activity(_LAST_RECONCILIATION_RESULT, limit=min(25, limit))
        )
    else:
        content = _placeholder_text(active_tab)
    return {
        "config": cfg,
        "tab": active_tab,
        "tabs": list(JOURNAL_TABS),
        "content": content,
        "limit": int(limit),
        "entry_count": len(entries),
        "journal_db_path": db_path,
        "has_reconciliation_result": isinstance(_LAST_RECONCILIATION_RESULT, dict),
    }


def run_reconciliation(*, limit: int = 20) -> dict:
    global _LAST_RECONCILIATION_RESULT
    cfg = load_config()
    db_path = resolve_journal_db_path(None)
    initialize_journal_db(db_path)
    replay_enabled = bool((cfg.get("replay", {}) if isinstance(cfg.get("replay", {}), dict) else {}).get("enabled", False))
    context = resolve_character_context(cfg, replay_enabled=replay_enabled)
    result = reconcile_journal_with_character_context(db_path, context)
    _LAST_RECONCILIATION_RESULT = dict(result)
    page = get_journal_page("reconcile", limit=limit)
    page["content"] = format_reconciliation_overview(result, limit=min(25, limit))
    page["last_action"] = "reconcile"
    return page


def get_unmatched_page(*, limit: int = 20) -> dict:
    page = get_journal_page("unmatched", limit=limit)
    if isinstance(_LAST_RECONCILIATION_RESULT, dict):
        page["content"] = format_unmatched_wallet_activity(_LAST_RECONCILIATION_RESULT, limit=min(25, limit))
    return page

