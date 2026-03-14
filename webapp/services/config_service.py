from __future__ import annotations

import json

from config_loader import load_config, validate_config
from runtime_common import CHARACTER_PROFILE_PATH, CONFIG_PATH, JOURNAL_DB_PATH
from webapp.security import resolve_access_settings


def _redact_webapp_section(section: dict) -> dict:
    out = dict(section or {})
    if str(out.get("access_password", "") or "").strip():
        out["access_password"] = "***"
    return out


def _config_sections(cfg: dict) -> dict:
    return {
        "defaults": dict(cfg.get("defaults", {}) or {}),
        "replay": dict(cfg.get("replay", {}) or {}),
        "route_search": dict(cfg.get("route_search", {}) or {}),
        "route_profiles": dict(cfg.get("route_profiles", {}) or {}),
        "character_context": dict(cfg.get("character_context", {}) or {}),
        "confidence_calibration": dict(cfg.get("confidence_calibration", {}) or {}),
        "personal_history_policy": dict(cfg.get("personal_history_policy", {}) or {}),
        "webapp": _redact_webapp_section(dict(cfg.get("webapp", {}) or {})),
    }


def get_config_page() -> dict:
    cfg = load_config()
    validation = validate_config(cfg)
    sections = _config_sections(cfg)
    access_settings = resolve_access_settings(cfg)
    return {
        "config_valid": not bool(validation.get("errors", [])),
        "config_errors": list(validation.get("errors", []) or []),
        "config_warnings": list(validation.get("warnings", []) or []),
        "paths": {
            "config_path": CONFIG_PATH,
            "journal_db_path": JOURNAL_DB_PATH,
            "character_profile_path": CHARACTER_PROFILE_PATH,
        },
        "sections_json": {name: json.dumps(value, indent=2, ensure_ascii=False) for name, value in sections.items()},
        "webapp_security": {
            "password_configured": bool(access_settings.get("password_configured", False)),
            "username": str(access_settings.get("username", "trader") or "trader"),
            "sensitive_paths": ["/character", "/config"],
        },
    }

