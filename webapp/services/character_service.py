from __future__ import annotations

from character_profile import (
    build_character_context_summary,
    character_status_lines,
    requested_character_scopes,
    resolve_character_context,
    resolve_character_context_cfg,
    sync_character_profile,
)
from config_loader import load_config
from eve_sso import EveSSOAuth


def _cfg_with_enabled_character_context(cfg: dict) -> dict:
    out = dict(cfg or {})
    raw = out.get("character_context", {})
    if not isinstance(raw, dict):
        raw = {}
    enabled = dict(raw)
    enabled["enabled"] = True
    out["character_context"] = enabled
    return out


def _build_sso(cfg: dict) -> EveSSOAuth | None:
    cfg_for_auth = _cfg_with_enabled_character_context(cfg)
    esi_cfg = cfg_for_auth.get("esi", {}) if isinstance(cfg_for_auth.get("esi", {}), dict) else {}
    client_id = str(esi_cfg.get("client_id", "") or "").strip()
    if not client_id:
        return None
    char_cfg = resolve_character_context_cfg(cfg_for_auth)
    return EveSSOAuth(
        client_id=client_id,
        client_secret=str(esi_cfg.get("client_secret", "") or ""),
        callback_url=str(esi_cfg.get("callback_url", "http://localhost:12563/callback") or "http://localhost:12563/callback"),
        user_agent=str(esi_cfg.get("user_agent", "NullsecTrader/1.0") or "NullsecTrader/1.0"),
        token_path=str(char_cfg.get("token_path", "") or ""),
        metadata_path=str(char_cfg.get("metadata_path", "") or ""),
    )


def get_character_page(*, action_message: str = "", action_error: str = "") -> dict:
    cfg = load_config()
    cfg_for_char = _cfg_with_enabled_character_context(cfg)
    sso = _build_sso(cfg)
    auth_status = sso.describe_token_status() if sso is not None else {"has_token": False, "valid": False, "scopes": [], "token_path": "", "character_name": "", "character_id": 0}
    context = resolve_character_context(cfg_for_char, replay_enabled=False, allow_live=False)
    summary = build_character_context_summary(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0)))
    return {
        "config": cfg,
        "auth_status": auth_status,
        "required_scopes": requested_character_scopes(cfg_for_char),
        "character_context": context,
        "character_summary": summary,
        "character_status_lines": character_status_lines(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0))),
        "action_message": str(action_message or "").strip(),
        "action_error": str(action_error or "").strip(),
    }


def run_auth_action(action: str) -> dict:
    cfg = load_config()
    cfg_for_auth = _cfg_with_enabled_character_context(cfg)
    sso = _build_sso(cfg_for_auth)
    if sso is None:
        return get_character_page(action_error="ESI client_id fehlt fuer EVE SSO.")
    requested_scopes = requested_character_scopes(cfg_for_auth)
    try:
        if str(action or "").strip().lower() == "login":
            sso.ensure_token(requested_scopes, allow_login=True)
        return get_character_page(action_message=f"Auth action '{action}' abgeschlossen.")
    except Exception as exc:
        return get_character_page(action_error=f"Auth action fehlgeschlagen: {exc}")


def run_character_action(action: str) -> dict:
    cfg = load_config()
    cfg_for_char = _cfg_with_enabled_character_context(cfg)
    try:
        if str(action or "").strip().lower() == "sync":
            context = sync_character_profile(cfg_for_char, allow_login=True)
            summary = build_character_context_summary(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0)))
            return {
                **get_character_page(action_message="Character sync abgeschlossen."),
                "character_context": context,
                "character_summary": summary,
                "character_status_lines": character_status_lines(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0))),
            }
        return get_character_page(action_message="Character status aktualisiert.")
    except Exception as exc:
        return get_character_page(action_error=f"Character action fehlgeschlagen: {exc}")

