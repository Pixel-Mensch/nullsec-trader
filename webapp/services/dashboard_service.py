from __future__ import annotations

from character_profile import build_character_context_summary, character_status_lines, resolve_character_context
from confidence_calibration import (
    build_personal_calibration_summary,
    build_personal_history_layer_state,
    personal_history_layer_status_lines,
)
from config_loader import load_config, validate_config
from journal_reporting import build_journal_report, build_personal_trade_analytics
from journal_store import fetch_journal_entries, initialize_journal_db, resolve_journal_db_path


def get_dashboard_data() -> dict:
    cfg = load_config()
    validation = validate_config(cfg)
    replay_enabled = bool((cfg.get("replay", {}) if isinstance(cfg.get("replay", {}), dict) else {}).get("enabled", False))
    context = resolve_character_context(cfg, replay_enabled=replay_enabled, allow_live=False)
    character_summary = build_character_context_summary(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0)))
    db_path = resolve_journal_db_path(None)
    initialize_journal_db(db_path)
    entries = fetch_journal_entries(db_path, limit=250)
    report = build_journal_report(entries, limit=5)
    analytics = build_personal_trade_analytics(list(report.get("entries", []) or []))
    personal_summary = build_personal_calibration_summary(list(report.get("entries", []) or []), cfg)
    personal_layer = build_personal_history_layer_state(personal_summary, cfg)
    warnings: list[str] = []
    warnings.extend(str(item).strip() for item in list(context.get("warnings", []) or []) if str(item).strip())
    warnings.extend(str(item).strip() for item in list(personal_summary.get("warnings", []) or [])[:3] if str(item).strip())
    warnings = list(dict.fromkeys(warnings))
    return {
        "config": cfg,
        "config_valid": not bool(validation.get("errors", [])),
        "config_errors": list(validation.get("errors", []) or []),
        "config_warnings": list(validation.get("warnings", []) or []),
        "character_context": context,
        "character_summary": character_summary,
        "character_status_lines": character_status_lines(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0))),
        "journal_report": report,
        "journal_summary": dict(report.get("summary", {}) or {}),
        "journal_entries": list(report.get("entries", []) or [])[:5],
        "personal_analytics": analytics,
        "wallet_quality": {
            "wallet_data_freshness": character_summary.get("wallet_data_freshness", "unknown"),
            "wallet_history_quality": character_summary.get("wallet_history_quality", "missing"),
        },
        "personal_summary": personal_summary,
        "personal_layer": personal_layer,
        "personal_layer_lines": personal_history_layer_status_lines(personal_summary, personal_layer),
        "warnings": warnings,
        "journal_db_path": db_path,
    }
