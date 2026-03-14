from __future__ import annotations

import base64
import json
import os

from webapp.services import active_character_service


def _token_payload(character_id: int, name: str) -> dict:
    return {"sub": f"CHARACTER:EVE:{int(character_id)}", "name": str(name)}


def _jwt_for_character(character_id: int, name: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode("utf-8")).decode("ascii").rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(_token_payload(character_id, name)).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{header}.{payload}.sig"


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def test_activate_character_switches_runtime_token_and_profile(tmp_path, monkeypatch) -> None:
    registry_path = tmp_path / "web_character_registry.json"
    slots_dir = tmp_path / "saved_characters"
    runtime_token_path = tmp_path / "runtime" / "token.json"
    sso_token_path = tmp_path / "character_context" / "sso_token.json"
    profile_path = tmp_path / "character_context" / "character_profile.json"
    slot_dir = slots_dir / "90000002"
    slot_token_path = slot_dir / "token.json"
    slot_profile_path = slot_dir / "character_profile.json"

    _write_json(str(registry_path), {"active_character_id": 0, "characters": {"90000002": {"character_id": 90000002, "character_name": "Hauler Alt"}}})
    _write_json(str(slot_token_path), {"access_token": _jwt_for_character(90000002, "Hauler Alt")})
    _write_json(str(slot_profile_path), {"payload": {"character_id": 90000002, "character_name": "Hauler Alt"}})

    monkeypatch.setattr(active_character_service, "REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(active_character_service, "CHARACTER_SLOTS_DIR", str(slots_dir))
    monkeypatch.setattr(active_character_service, "TOKEN_PATH", str(runtime_token_path))
    monkeypatch.setattr(active_character_service, "load_config", lambda: {"character_context": {}})
    monkeypatch.setattr(
        active_character_service,
        "resolve_character_context_cfg",
        lambda cfg: {"token_path": str(sso_token_path), "profile_cache_path": str(profile_path)},
    )
    monkeypatch.setattr(
        active_character_service,
        "resolve_character_context",
        lambda cfg, replay_enabled=False, allow_live=False: {
            "character_id": 90000002,
            "character_name": "Hauler Alt",
            "profile": {"character_id": 90000002, "character_name": "Hauler Alt"},
        },
    )

    result = active_character_service.activate_character(90000002)

    assert result["ok"] is True
    with open(runtime_token_path, encoding="utf-8") as fh:
        runtime_token = json.load(fh)
    with open(sso_token_path, encoding="utf-8") as fh:
        sso_token = json.load(fh)
    with open(profile_path, encoding="utf-8") as fh:
        profile_payload = json.load(fh)
    assert runtime_token["access_token"] == _jwt_for_character(90000002, "Hauler Alt")
    assert sso_token["access_token"] == _jwt_for_character(90000002, "Hauler Alt")
    assert profile_payload == {"payload": {"character_id": 90000002, "character_name": "Hauler Alt"}}


def test_activate_character_without_profile_clears_old_active_profile(tmp_path, monkeypatch) -> None:
    registry_path = tmp_path / "web_character_registry.json"
    slots_dir = tmp_path / "saved_characters"
    runtime_token_path = tmp_path / "runtime" / "token.json"
    sso_token_path = tmp_path / "character_context" / "sso_token.json"
    profile_path = tmp_path / "character_context" / "character_profile.json"
    slot_dir = slots_dir / "90000003"
    slot_token_path = slot_dir / "token.json"

    _write_json(str(registry_path), {"active_character_id": 0, "characters": {"90000003": {"character_id": 90000003, "character_name": "Journal Alt"}}})
    _write_json(str(slot_token_path), {"access_token": _jwt_for_character(90000003, "Journal Alt")})
    _write_json(str(profile_path), {"payload": {"character_id": 90000001, "character_name": "Old Pilot"}})

    monkeypatch.setattr(active_character_service, "REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(active_character_service, "CHARACTER_SLOTS_DIR", str(slots_dir))
    monkeypatch.setattr(active_character_service, "TOKEN_PATH", str(runtime_token_path))
    monkeypatch.setattr(active_character_service, "load_config", lambda: {"character_context": {}})
    monkeypatch.setattr(
        active_character_service,
        "resolve_character_context_cfg",
        lambda cfg: {"token_path": str(sso_token_path), "profile_cache_path": str(profile_path)},
    )
    monkeypatch.setattr(
        active_character_service,
        "resolve_character_context",
        lambda cfg, replay_enabled=False, allow_live=False: {
            "character_id": 0,
            "character_name": "",
            "profile": {},
        },
    )

    result = active_character_service.activate_character(90000003)

    assert result["ok"] is True
    assert profile_path.exists() is False
    with open(runtime_token_path, encoding="utf-8") as fh:
        runtime_token = json.load(fh)
    assert runtime_token["access_token"] == _jwt_for_character(90000003, "Journal Alt")
