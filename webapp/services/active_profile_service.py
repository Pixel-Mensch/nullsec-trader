from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from config_loader import load_config
from risk_profiles import BUILTIN_PROFILES, DEFAULT_PROFILE
from runtime_common import CACHE_DIR


STATE_PATH = os.path.join(CACHE_DIR, "web_active_profile.json")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_profile_name(value: object) -> str:
    name = str(value or "").strip().lower()
    return name if name in BUILTIN_PROFILES else ""


def _config_profile_name(cfg: dict | None = None) -> str:
    current_cfg = cfg if isinstance(cfg, dict) else load_config()
    profile_cfg = current_cfg.get("risk_profile", {}) if isinstance(current_cfg, dict) else {}
    if not isinstance(profile_cfg, dict):
        profile_cfg = {}
    return _normalize_profile_name(profile_cfg.get("name")) or DEFAULT_PROFILE


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "active_profile_name": _normalize_profile_name(payload.get("active_profile_name")),
        "updated_at": str(payload.get("updated_at", "") or "").strip(),
    }


def _save_state(profile_name: str) -> dict:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    payload = {
        "active_profile_name": _normalize_profile_name(profile_name),
        "updated_at": _utc_now_iso(),
    }
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return payload


def resolve_active_profile_name(cfg: dict | None = None) -> str:
    state = _load_state()
    active_profile_name = _normalize_profile_name(state.get("active_profile_name"))
    if active_profile_name:
        return active_profile_name
    return _config_profile_name(cfg)


def list_builtin_profiles() -> list[dict]:
    profiles: list[dict] = []
    for name, spec in BUILTIN_PROFILES.items():
        description = ""
        if isinstance(spec, dict):
            description = str(spec.get("description", "") or "").strip()
        profiles.append({"name": str(name), "description": description})
    return profiles


def get_switcher_context(*, current_path: str = "/", cfg: dict | None = None) -> dict:
    active_profile_name = resolve_active_profile_name(cfg)
    profiles: list[dict] = []
    for item in list_builtin_profiles():
        profiles.append({**item, "is_active": item["name"] == active_profile_name})
    active_profile = next((item for item in profiles if bool(item.get("is_active", False))), None)
    if not isinstance(active_profile, dict):
        active_profile = {"name": DEFAULT_PROFILE, "description": "", "is_active": True}
    config_profile_name = _config_profile_name(cfg)
    return {
        "available": bool(profiles),
        "active_profile": active_profile,
        "profiles": profiles,
        "return_to": str(current_path or "/") or "/",
        "config_profile_name": config_profile_name,
        "basis_note": "New analysis runs default to this active profile unless the form overrides it.",
    }


def activate_profile(profile_name: str) -> dict:
    normalized = _normalize_profile_name(profile_name)
    if not normalized:
        return {"ok": False, "error": "Unbekanntes Risk Profile."}
    payload = _save_state(normalized)
    return {
        "ok": True,
        "profile_name": normalized,
        "updated_at": str(payload.get("updated_at", "") or "").strip(),
    }


__all__ = [
    "activate_profile",
    "get_switcher_context",
    "list_builtin_profiles",
    "resolve_active_profile_name",
]
