from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

from character_profile import resolve_character_context, resolve_character_context_cfg
from config_loader import load_config
from eve_sso import decode_access_token_claims, token_identity_from_claims
from runtime_common import CHARACTER_CACHE_DIR, TOKEN_PATH


REGISTRY_PATH = os.path.join(CHARACTER_CACHE_DIR, "web_character_registry.json")
CHARACTER_SLOTS_DIR = os.path.join(CHARACTER_CACHE_DIR, "saved_characters")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cfg_with_enabled_character_context(cfg: dict) -> dict:
    out = dict(cfg or {})
    raw = out.get("character_context", {})
    if not isinstance(raw, dict):
        raw = {}
    enabled = dict(raw)
    enabled["enabled"] = True
    out["character_context"] = enabled
    return out


def _active_paths() -> dict:
    cfg = _cfg_with_enabled_character_context(load_config())
    char_cfg = resolve_character_context_cfg(cfg)
    return {
        "cfg": cfg,
        "token_path": str(char_cfg.get("token_path", "") or ""),
        "profile_path": str(char_cfg.get("profile_cache_path", "") or ""),
    }


def _load_registry() -> dict:
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    characters = payload.get("characters", {})
    if not isinstance(characters, dict):
        characters = {}
    return {
        "active_character_id": int(payload.get("active_character_id", 0) or 0),
        "characters": characters,
    }


def _save_registry(registry: dict) -> dict:
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    payload = {
        "active_character_id": int(registry.get("active_character_id", 0) or 0),
        "characters": dict(registry.get("characters", {}) or {}),
    }
    with open(REGISTRY_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return payload


def _copy_file(src: str, dst: str) -> bool:
    src_path = str(src or "").strip()
    dst_path = str(dst or "").strip()
    if not src_path or not dst_path or not os.path.exists(src_path):
        return False
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copyfile(src_path, dst_path)
    return True


def _remove_file(path: str) -> None:
    target = str(path or "").strip()
    if not target:
        return
    try:
        if os.path.exists(target):
            os.remove(target)
    except Exception:
        pass


def _load_token_identity(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return {"character_id": 0, "character_name": ""}
    if not isinstance(payload, dict):
        return {"character_id": 0, "character_name": ""}
    claims = decode_access_token_claims(str(payload.get("access_token", "") or ""))
    ident = token_identity_from_claims(claims)
    return {
        "character_id": int(ident.get("character_id", 0) or 0),
        "character_name": str(ident.get("character_name", "") or "").strip(),
    }


def _slot_dir(character_id: int) -> str:
    return os.path.join(CHARACTER_SLOTS_DIR, str(int(character_id)))


def _slot_token_path(character_id: int) -> str:
    return os.path.join(_slot_dir(character_id), "token.json")


def _slot_profile_path(character_id: int) -> str:
    return os.path.join(_slot_dir(character_id), "character_profile.json")


def _saved_character_view(record: dict, *, active_character_id: int) -> dict:
    character_id = int(record.get("character_id", 0) or 0)
    token_path = _slot_token_path(character_id)
    profile_path = _slot_profile_path(character_id)
    character_name = str(record.get("character_name", "") or "").strip()
    display_name = character_name or (f"Character {character_id}" if character_id > 0 else "No character")
    return {
        "character_id": character_id,
        "character_name": character_name,
        "display_name": display_name,
        "has_token": bool(os.path.exists(token_path)),
        "has_profile": bool(os.path.exists(profile_path)),
        "is_active": bool(character_id > 0 and character_id == int(active_character_id or 0)),
        "last_seen_at": str(record.get("last_seen_at", "") or "").strip(),
    }


def capture_current_character() -> dict | None:
    paths = _active_paths()
    context = resolve_character_context(paths["cfg"], replay_enabled=False, allow_live=False)
    profile = context.get("profile", {}) if isinstance(context.get("profile", {}), dict) else {}
    profile_character_id = int(profile.get("character_id", 0) or 0)
    profile_character_name = str(profile.get("character_name", "") or "").strip()

    token_identity = _load_token_identity(paths["token_path"])
    if int(token_identity.get("character_id", 0) or 0) <= 0:
        token_identity = _load_token_identity(TOKEN_PATH)
    token_character_id = int(token_identity.get("character_id", 0) or 0)
    token_character_name = str(token_identity.get("character_name", "") or "").strip()

    active_character_id = token_character_id if token_character_id > 0 else profile_character_id
    active_character_name = token_character_name or profile_character_name
    if active_character_id <= 0:
        return None

    token_source = str(paths["token_path"] or "").strip()
    if not token_source or not os.path.exists(token_source):
        token_source = TOKEN_PATH
    profile_source = str(paths["profile_path"] or "").strip()

    os.makedirs(_slot_dir(active_character_id), exist_ok=True)
    if token_source and os.path.exists(token_source):
        _copy_file(token_source, _slot_token_path(active_character_id))
    if profile_character_id > 0 and profile_character_id == active_character_id and profile_source and os.path.exists(profile_source):
        _copy_file(profile_source, _slot_profile_path(active_character_id))

    registry = _load_registry()
    record = dict(registry["characters"].get(str(active_character_id), {}) or {})
    record.update(
        {
            "character_id": int(active_character_id),
            "character_name": active_character_name,
            "last_seen_at": _utc_now_iso(),
        }
    )
    registry["characters"][str(active_character_id)] = record
    registry["active_character_id"] = int(active_character_id)
    _save_registry(registry)
    return _saved_character_view(record, active_character_id=active_character_id)


def list_known_characters() -> list[dict]:
    registry = _load_registry()
    active_character_id = int(registry.get("active_character_id", 0) or 0)
    out: list[dict] = []
    for raw_key, raw_value in dict(registry.get("characters", {}) or {}).items():
        record = dict(raw_value or {}) if isinstance(raw_value, dict) else {}
        if int(record.get("character_id", 0) or 0) <= 0:
            try:
                record["character_id"] = int(raw_key)
            except Exception:
                record["character_id"] = 0
        if int(record.get("character_id", 0) or 0) <= 0:
            continue
        out.append(_saved_character_view(record, active_character_id=active_character_id))
    out.sort(
        key=lambda item: (
            0 if bool(item.get("is_active", False)) else 1,
            str(item.get("display_name", "") or "").lower(),
            int(item.get("character_id", 0) or 0),
        )
    )
    return out


def get_switcher_context(*, current_path: str = "/") -> dict:
    capture_current_character()
    characters = list_known_characters()
    active_character = next((item for item in characters if bool(item.get("is_active", False))), None)
    if not isinstance(active_character, dict):
        active_character = {
            "character_id": 0,
            "character_name": "",
            "display_name": "No active character",
            "has_token": False,
            "has_profile": False,
            "is_active": False,
            "last_seen_at": "",
        }
    return {
        "available": bool(characters),
        "active_character": active_character,
        "characters": characters,
        "return_to": str(current_path or "/") or "/",
        "basis_note": "Analysis, journal, and reconcile use this active character slot.",
    }


def activate_character(character_id: int | str) -> dict:
    try:
        active_character_id = int(character_id or 0)
    except Exception:
        active_character_id = 0
    if active_character_id <= 0:
        return {"ok": False, "error": "Ungueltige Character-ID."}

    registry = _load_registry()
    record = dict(registry.get("characters", {}).get(str(active_character_id), {}) or {})
    if not record:
        return {"ok": False, "error": f"Character {active_character_id} ist lokal nicht gespeichert."}

    slot_token_path = _slot_token_path(active_character_id)
    slot_profile_path = _slot_profile_path(active_character_id)
    has_token = bool(os.path.exists(slot_token_path))
    has_profile = bool(os.path.exists(slot_profile_path))
    if not has_token and not has_profile:
        return {"ok": False, "error": "Fuer diesen Character gibt es lokal weder Token noch Profil-Cache."}

    paths = _active_paths()
    target_token_path = str(paths["token_path"] or "").strip()
    target_profile_path = str(paths["profile_path"] or "").strip()

    if has_token:
        _copy_file(slot_token_path, TOKEN_PATH)
        if target_token_path:
            _copy_file(slot_token_path, target_token_path)
    else:
        _remove_file(TOKEN_PATH)
        _remove_file(target_token_path)

    if has_profile:
        _copy_file(slot_profile_path, target_profile_path)
    else:
        _remove_file(target_profile_path)

    registry["active_character_id"] = int(active_character_id)
    _save_registry(registry)
    refreshed = capture_current_character()
    character_name = str((refreshed or {}).get("character_name", record.get("character_name", "")) or "").strip()
    return {
        "ok": True,
        "character_id": int(active_character_id),
        "character_name": character_name,
        "has_token": bool(has_token),
        "has_profile": bool(has_profile),
    }


__all__ = [
    "activate_character",
    "capture_current_character",
    "get_switcher_context",
    "list_known_characters",
]
