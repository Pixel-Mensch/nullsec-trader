from __future__ import annotations

import json
import os

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
from runtime_common import TOKEN_PATH
from webapp.services import active_character_service


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


def _auth_status_view(status: dict | None) -> dict:
    raw = dict(status or {})
    return {
        "has_token": bool(raw.get("has_token", False)),
        "valid": bool(raw.get("valid", False)),
        "scopes": [str(scope) for scope in list(raw.get("scopes", []) or []) if str(scope).strip()],
        "token_path": str(raw.get("token_path", "") or ""),
        "character_name": str(raw.get("character_name", "") or ""),
        "character_id": int(raw.get("character_id", 0) or 0),
    }


def _character_context_view(context: dict | None) -> dict:
    raw = dict(context or {})
    return {
        "character_name": str(raw.get("character_name", "") or ""),
        "source": str(raw.get("source", "") or ""),
        "warnings": [str(warning) for warning in list(raw.get("warnings", []) or []) if str(warning).strip()],
    }


def _character_summary_view(summary: dict | None) -> dict:
    raw = dict(summary or {})
    return {
        "character_name": str(raw.get("character_name", "") or ""),
        "source": str(raw.get("source", "") or ""),
    }


def _saved_characters_view(characters: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in list(characters or []):
        if not isinstance(raw, dict):
            continue
        out.append(
            {
                "character_id": int(raw.get("character_id", 0) or 0),
                "character_name": str(raw.get("character_name", "") or ""),
                "display_name": str(raw.get("display_name", "") or ""),
                "has_token": bool(raw.get("has_token", False)),
                "has_profile": bool(raw.get("has_profile", False)),
                "is_active": bool(raw.get("is_active", False)),
                "last_seen_at": str(raw.get("last_seen_at", "") or ""),
            }
        )
    return out


def get_character_page(*, action_message: str = "", action_error: str = "") -> dict:
    cfg = load_config()
    cfg_for_char = _cfg_with_enabled_character_context(cfg)
    active_character_service.capture_current_character()
    sso = _build_sso(cfg)
    auth_status = sso.describe_token_status() if sso is not None else {"has_token": False, "valid": False, "scopes": [], "token_path": "", "character_name": "", "character_id": 0}
    context = resolve_character_context(cfg_for_char, replay_enabled=False, allow_live=False)
    summary = build_character_context_summary(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0)))
    return {
        "auth_status": _auth_status_view(auth_status),
        "required_scopes": requested_character_scopes(cfg_for_char),
        "character_context": _character_context_view(context),
        "character_summary": _character_summary_view(summary),
        "character_status_lines": character_status_lines(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0))),
        "action_message": str(action_message or "").strip(),
        "action_error": str(action_error or "").strip(),
        "saved_characters": _saved_characters_view(active_character_service.list_known_characters()),
    }


def _all_scopes(cfg: dict) -> list[str]:
    """Return character scopes + market auth scope merged (deduplicated)."""
    char_scopes = requested_character_scopes(cfg)
    market_scope = str((cfg.get("esi", {}) or {}).get("scope", "") or "").strip()
    seen: set[str] = set()
    out: list[str] = []
    for s in char_scopes + ([market_scope] if market_scope else []):
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _sync_market_token(sso_token_path: str) -> None:
    """Copy the character SSO token to TOKEN_PATH so the runtime uses the same character."""
    try:
        if not os.path.exists(sso_token_path):
            return
        with open(sso_token_path, encoding="utf-8") as fh:
            token_data = json.load(fh)
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as fh:
            json.dump(token_data, fh, indent=2)
    except Exception:
        pass


def run_auth_action(action: str) -> dict:
    cfg = load_config()
    cfg_for_auth = _cfg_with_enabled_character_context(cfg)
    sso = _build_sso(cfg_for_auth)
    if sso is None:
        return get_character_page(action_error="ESI client_id fehlt fuer EVE SSO.")
    try:
        action_name = str(action or "").strip().lower()
        if action_name in {"login", "relogin"}:
            all_scopes = _all_scopes(cfg_for_auth)
            if action_name == "relogin":
                sso.oauth_authorize(all_scopes)
            else:
                sso.ensure_token(all_scopes, allow_login=True)
            # Mirror the token to TOKEN_PATH so the runtime uses the same character.
            char_cfg = resolve_character_context_cfg(cfg_for_auth)
            _sync_market_token(str(char_cfg.get("token_path", "") or ""))
            active_character_service.capture_current_character()
        if action_name == "relogin":
            return get_character_page(action_message="Neuer Character-Login abgeschlossen.")
        return get_character_page(action_message=f"Auth action '{action}' abgeschlossen.")
    except Exception as exc:
        return get_character_page(action_error=f"Auth action fehlgeschlagen: {exc}")


def run_character_action(action: str) -> dict:
    cfg = load_config()
    cfg_for_char = _cfg_with_enabled_character_context(cfg)
    try:
        if str(action or "").strip().lower() == "sync":
            context = sync_character_profile(cfg_for_char, allow_login=True)
            active_character_service.capture_current_character()
            summary = build_character_context_summary(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0)))
            return {
                **get_character_page(action_message="Character sync abgeschlossen."),
                "character_context": _character_context_view(context),
                "character_summary": _character_summary_view(summary),
                "character_status_lines": character_status_lines(context, budget_isk=((cfg.get("defaults", {}) or {}).get("budget_isk", 0))),
            }
        return get_character_page(action_message="Character status aktualisiert.")
    except Exception as exc:
        return get_character_page(action_error=f"Character action fehlgeschlagen: {exc}")


def activate_character(character_id: int | str) -> dict:
    return active_character_service.activate_character(character_id)

