from __future__ import annotations

import json

from risk_profiles import BUILTIN_PROFILES
from webapp.services import active_profile_service


def test_activate_profile_persists_builtin_profile(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "web_active_profile.json"
    monkeypatch.setattr(active_profile_service, "STATE_PATH", str(state_path))

    result = active_profile_service.activate_profile("small_wallet_hub_safe")

    assert result["ok"] is True
    with open(state_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["active_profile_name"] == "small_wallet_hub_safe"


def test_resolve_active_profile_falls_back_to_config_when_state_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(active_profile_service, "STATE_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(active_profile_service, "load_config", lambda: {"risk_profile": {"name": "aggressive"}})

    assert active_profile_service.resolve_active_profile_name() == "aggressive"


def test_activate_profile_rejects_unknown_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(active_profile_service, "STATE_PATH", str(tmp_path / "web_active_profile.json"))

    result = active_profile_service.activate_profile("imaginary_profile")

    assert result["ok"] is False


def test_list_builtin_profiles_tracks_builtin_profile_names() -> None:
    listed_names = [item["name"] for item in active_profile_service.list_builtin_profiles()]

    assert listed_names == list(BUILTIN_PROFILES.keys())
