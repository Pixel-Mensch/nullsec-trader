from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient
from starlette.requests import Request

from webapp import security as web_security
from webapp.app import create_app
from webapp.routes import pages
from webapp.services import analysis_service as analysis_service_module, character_service as character_service_module, config_service as config_service_module, runtime_bridge


def _character_switch(current_path: str = "/") -> dict:
    return {
        "available": True,
        "active_character": {
            "character_id": 90000001,
            "character_name": "Capsuleer",
            "display_name": "Capsuleer",
            "has_token": True,
            "has_profile": True,
            "is_active": True,
            "last_seen_at": "2026-03-14T09:10:47+00:00",
        },
        "characters": [
            {
                "character_id": 90000001,
                "character_name": "Capsuleer",
                "display_name": "Capsuleer",
                "has_token": True,
                "has_profile": True,
                "is_active": True,
                "last_seen_at": "2026-03-14T09:10:47+00:00",
            },
            {
                "character_id": 90000002,
                "character_name": "Hauler Alt",
                "display_name": "Hauler Alt",
                "has_token": True,
                "has_profile": True,
                "is_active": False,
                "last_seen_at": "2026-03-13T22:00:00+00:00",
            },
        ],
        "return_to": current_path,
        "basis_note": "Analysis, journal, and reconcile use this active character slot.",
    }


def _profile_switch(current_path: str = "/") -> dict:
    return {
        "available": True,
        "active_profile": {
            "name": "small_wallet_hub_safe",
            "description": "Small-wallet profile",
            "is_active": True,
        },
        "profiles": [
            {"name": "balanced", "description": "Default", "is_active": False},
            {"name": "small_wallet_hub_safe", "description": "Small-wallet profile", "is_active": True},
            {"name": "aggressive", "description": "Wide-open profile", "is_active": False},
        ],
        "return_to": current_path,
        "config_profile_name": "balanced",
        "basis_note": "New analysis runs default to this active profile unless the form overrides it.",
    }


def _dashboard_data() -> dict:
    return {
        "character_summary": {
            "character_name": "Capsuleer",
            "source": "cache",
            "wallet_history_quality": "usable",
            "wallet_data_freshness": "fresh",
        },
        "character_context": {"character_name": "Capsuleer", "warnings": []},
        "character_status_lines": ["Character: Capsuleer", "Wallet quality: usable"],
        "journal_summary": {"total_entries": 4, "open_entries": 1, "closed_entries": 3},
        "journal_entries": [
            {
                "item_name": "Tritanium",
                "target_market": "Jita",
                "effective_status": "sold",
                "reconciliation_status": "matched",
                "trade_history_source": "wallet",
            }
        ],
        "personal_analytics": {"wallet_quality": {"wallet_history_quality": "usable", "wallet_data_freshness": "fresh"}},
        "wallet_quality": {"wallet_history_quality": "usable", "wallet_data_freshness": "fresh"},
        "personal_summary": {"quality_level": "usable", "sample_size": {"wallet_backed_entries": 6}},
        "personal_layer": {"mode": "advisory", "active": False},
        "personal_layer_lines": ["Personal Layer: ADVISORY | quality USABLE | generic only"],
        "warnings": ["wallet snapshot stale"],
        "journal_db_path": "cache/trade_journal.sqlite3",
        "config_valid": True,
        "config_errors": [],
    }


def _analysis_form() -> dict:
    return {
        "config_valid": True,
        "config_errors": [],
        "defaults": {"budget_isk": 500000000, "cargo_m3": 12000},
        "risk_profiles": [
            {"name": "balanced", "description": "Default"},
            {"name": "small_wallet_hub_safe", "description": "Small-wallet profile"},
            {"name": "aggressive", "description": "Wide-open profile"},
        ],
        "replay_enabled": False,
        "route_mode": "roundtrip",
        "default_profile_name": "balanced",
        "config_profile_name": "balanced",
        "active_profile_name": "small_wallet_hub_safe",
        "selected_profile_name": "small_wallet_hub_safe",
        "config": {},
        "market_auth": {"character_name": "Navi Selerith", "has_token": True, "token_path": "cache/token.json"},
    }


def _analysis_result() -> dict:
    corridor_routes = [
        {
            "route_label": "O4T -> R-ARKN",
            "route_id": "route-direct",
            "actionable": True,
            "route_confidence": 0.74,
            "transport_confidence": 0.90,
            "capital_lock_risk": 0.10,
            "budget_util_pct": 45.3,
            "cargo_util_pct": 37.7,
            "isk_used": 226373819.86,
            "expected_profit_before_logistics_total": 12000000.0,
            "expected_profit_after_logistics_total": 12000000.0,
            "expected_profit_total": 12000000.0,
            "full_sell_profit_total": 15000000.0,
            "travel_summary": "Pure gate route with 1 gate leg(s)",
            "gate_leg_count": 1,
            "ansiblex_leg_count": 0,
            "ansiblex_logistics_cost_isk": 0.0,
            "used_ansiblex": False,
            "travel_path_legs": [{"from_system": "O4T-Z5", "to_system": "R-ARKN", "mode": "gate"}],
            "pick_count": 1,
            "warnings": ["calibration fallback"],
            "calibration_warning": "",
            "route_prune_reason": "",
            "route_logic_label": "direct leg",
            "display": {
                "section_key": "corridor_forward_0",
                "section_label": "Corridor O4T outbound",
                "section_note": "Direct legs first, then longer profitable spans along the corridor.",
                "section_order": 100,
                "item_order": 11,
                "logic_label": "direct leg",
            },
            "picks": [
                {
                    "name": "Tritanium",
                    "proposed_qty": 1000,
                    "proposed_exit_type": "sell",
                    "proposed_expected_days_to_sell": 3.5,
                    "proposed_overall_confidence_raw": 0.66,
                    "proposed_expected_profit": 4500000.0,
                }
            ],
        },
        {
            "route_label": "O4T -> 1st Taj Mahgoon",
            "route_id": "route-span",
            "actionable": True,
            "route_confidence": 0.68,
            "transport_confidence": 0.88,
            "capital_lock_risk": 0.22,
            "budget_util_pct": 54.9,
            "cargo_util_pct": 42.0,
            "isk_used": 286373819.86,
            "expected_profit_before_logistics_total": 18665000.0,
            "expected_profit_after_logistics_total": 18000000.0,
            "expected_profit_total": 18000000.0,
            "full_sell_profit_total": 22000000.0,
            "travel_summary": "1 gate leg(s), 1 ansiblex leg(s), 665000 ISK ansiblex logistics",
            "gate_leg_count": 1,
            "ansiblex_leg_count": 1,
            "ansiblex_logistics_cost_isk": 665000.0,
            "used_ansiblex": True,
            "travel_path_legs": [
                {"from_system": "O4T-Z5", "to_system": "R-ARKN", "mode": "gate"},
                {"from_system": "R-ARKN", "to_system": "WT-2J9", "mode": "ansiblex", "ansiblex_logistics_cost_isk": 665000.0},
            ],
            "candidate_node_summary": "corridor RE-C26 [corridor_checkpoint]",
            "candidate_nodes": [
                {"label": "RE-C26", "kind": "corridor_checkpoint", "match_role": "corridor", "note": ""},
            ],
            "pick_count": 1,
            "warnings": [],
            "calibration_warning": "",
            "route_prune_reason": "",
            "route_logic_label": "3-leg span",
            "display": {
                "section_key": "corridor_forward_0",
                "section_label": "Corridor O4T outbound",
                "section_note": "Direct legs first, then longer profitable spans along the corridor.",
                "section_order": 100,
                "item_order": 33,
                "logic_label": "3-leg span",
            },
            "picks": [
                {
                    "name": "Isogen",
                    "proposed_qty": 500,
                    "proposed_exit_type": "planned_sell",
                    "proposed_expected_days_to_sell": 9.0,
                    "proposed_overall_confidence_raw": 0.59,
                    "proposed_expected_profit": 8200000.0,
                }
            ],
        },
        {
            "route_label": "jita_44 -> O4T",
            "route_id": "route-jita",
            "actionable": False,
            "route_confidence": 0.40,
            "transport_confidence": 0.84,
            "capital_lock_risk": 0.18,
            "budget_util_pct": 12.0,
            "cargo_util_pct": 8.5,
            "isk_used": 60373819.86,
            "expected_profit_before_logistics_total": 2500000.0,
            "expected_profit_after_logistics_total": 2500000.0,
            "expected_profit_total": 2500000.0,
            "full_sell_profit_total": 3100000.0,
            "travel_summary": "External connector",
            "gate_leg_count": 0,
            "ansiblex_leg_count": 0,
            "ansiblex_logistics_cost_isk": 0.0,
            "used_ansiblex": False,
            "travel_path_legs": [],
            "pick_count": 1,
            "warnings": ["shipping warning"],
            "calibration_warning": "",
            "route_prune_reason": "confidence",
            "route_failure_hints": ["Candidates existed, but the active profile removed them on confidence."],
            "route_failure_summary": "Candidates existed, but the active profile removed them on confidence.",
            "route_logic_label": "Jita outbound connector",
            "display": {
                "section_key": "jita_0_from_jita",
                "section_label": "Jita connectors @ O4T",
                "section_note": "Jita routes stay visible as external connectors and are not folded into corridor spans.",
                "section_order": 300,
                "item_order": 0,
                "logic_label": "Jita outbound connector",
            },
            "picks": [
                {
                    "name": "Mexallon",
                    "proposed_qty": 800,
                    "proposed_exit_type": "instant",
                    "proposed_expected_days_to_sell": 1.0,
                    "proposed_overall_confidence_raw": 0.44,
                    "proposed_expected_profit": 1500000.0,
                }
            ],
        },
    ]
    return {
        "ok": True,
        "error": "",
        "exit_code": 0,
        "runtime_mode": "roundtrip",
        "selected_profile": "balanced",
        "plan_id": "plan-123",
        "route_count": 3,
        "pick_count": 3,
        "actionable_route_count": 2,
        "used_replay": False,
        "snapshot_path": "C:/tmp/replay_snapshot.json",
        "created_files": ["execution_plan_2026.txt", "trade_plan_plan-123.json"],
        "personal_layer_lines": [
            "Personal Layer: ADVISORY | quality USABLE | generic only",
            "Fallback: generic only | advisory mode keeps the generic decision path",
        ],
        "route_cards": corridor_routes,
        "route_sections": [
            {
                "key": "corridor_forward_0",
                "label": "Corridor O4T outbound",
                "note": "Direct legs first, then longer profitable spans along the corridor.",
                "routes": corridor_routes[:2],
            },
            {
                "key": "jita_0_from_jita",
                "label": "Jita connectors @ O4T",
                "note": "Jita routes stay visible as external connectors and are not folded into corridor spans.",
                "routes": corridor_routes[2:],
            },
        ],
        "manifest": {"route_count": 1},
        "summary_text": "Summary",
        "leaderboard_text": "",
        "execution_plan_text": "Execution plan",
        "no_trade_text": "",
        "form": _analysis_form(),
    }


def _journal_page(tab: str = "overview") -> dict:
    return {
        "tab": tab,
        "tabs": ["overview", "open", "closed", "report", "reconcile", "personal", "unmatched", "calibration"],
        "content": f"content for {tab}",
        "limit": 20,
        "entry_count": 4,
        "journal_db_path": "cache/trade_journal.sqlite3",
        "has_reconciliation_result": tab in {"reconcile", "unmatched"},
        "character_summary": {
            "character_name": "Capsuleer",
            "source": "cache",
            "warnings": [],
            "open_orders_count": 7,
            "sell_order_count": 5,
            "buy_order_count": 2,
            "wallet_transactions_count": 42,
            "wallet_journal_count": 84,
            "wallet_data_freshness": "fresh",
            "wallet_history_quality": "usable",
        },
        "active_sell_orders": {
            "available": True,
            "character_id": 90000001,
            "character_name": "Capsuleer",
            "sell_orders": [
                {
                    "type_id": 34,
                    "name": "Tritanium",
                    "sell_order_count": 3,
                    "sell_units": 12000,
                    "sell_gross_isk": 4200000.0,
                    "location_ids": [60003760],
                    "journal_match_count": 2,
                    "active_character_match_count": 1,
                }
            ],
        },
        "empty_notice": "",
    }


def _character_page() -> dict:
    return {
        "auth_status": {
            "valid": False,
            "has_token": False,
            "character_name": "",
            "character_id": 0,
            "scopes": [],
            "token_path": "cache/character_context/sso_token.json",
        },
        "required_scopes": ["esi-skills.read_skills.v1"],
        "character_summary": {"character_name": "", "source": "generic"},
        "character_context": {"warnings": ["character context disabled"]},
        "character_status_lines": ["Character context: generic defaults"],
        "saved_characters": _character_switch()["characters"],
        "action_message": "",
        "action_error": "",
    }


def _config_page() -> dict:
    return {
        "config_valid": True,
        "config_errors": [],
        "config_warnings": [],
        "webapp_security": {
            "password_configured": False,
            "username": "trader",
            "sensitive_paths": ["/character", "/config"],
        },
        "paths": {
            "config_path": "config.json",
            "journal_db_path": "cache/trade_journal.sqlite3",
            "character_profile_path": "cache/character_context/character_profile.json",
        },
        "sections_json": {"defaults": "{\n  \"budget_isk\": 500000000\n}"},
    }


def _access_request(*, path: str = "/", headers: dict[str, str] | None = None, client: tuple[str, int] = ("127.0.0.1", 1234)) -> Request:
    raw_headers = [
        (str(name).lower().encode("latin-1"), str(value).encode("latin-1"))
        for name, value in dict(headers or {"host": "127.0.0.1:8000"}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": raw_headers,
        "client": client,
        "server": ("127.0.0.1", 8000),
        "root_path": "",
    }
    return Request(scope)


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(pages.dashboard_service, "get_dashboard_data", lambda: _dashboard_data())
    monkeypatch.setattr(pages.analysis_service, "get_analysis_form_data", lambda: _analysis_form())
    monkeypatch.setattr(pages.analysis_service, "run_analysis", lambda **_: _analysis_result())
    monkeypatch.setattr(pages.journal_service, "get_journal_page", lambda tab="overview", limit=20: _journal_page(tab))
    monkeypatch.setattr(pages.journal_service, "run_reconciliation", lambda limit=20: {**_journal_page("reconcile"), "last_action": "reconcile"})
    monkeypatch.setattr(pages.journal_service, "get_unmatched_page", lambda limit=20: _journal_page("unmatched"))
    monkeypatch.setattr(pages.character_service, "get_character_page", lambda: _character_page())
    monkeypatch.setattr(pages.character_service, "run_auth_action", lambda action: {**_character_page(), "action_message": f"auth {action}"})
    monkeypatch.setattr(pages.character_service, "activate_character", lambda character_id: {"ok": True, "character_id": int(character_id), "character_name": "Hauler Alt"})
    monkeypatch.setattr(pages.character_service, "run_character_action", lambda action: {**_character_page(), "action_message": f"character {action}"})
    monkeypatch.setattr(pages.config_service, "get_config_page", lambda: _config_page())
    monkeypatch.setattr(pages.active_character_service, "get_switcher_context", lambda current_path="/": _character_switch(current_path))
    monkeypatch.setattr(pages.active_profile_service, "get_switcher_context", lambda current_path="/": _profile_switch(current_path))
    return TestClient(create_app())


def test_dashboard_renders(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Capsuleer" in response.text
    assert "wallet snapshot stale" in response.text


def test_analysis_form_renders(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/analysis")
    assert response.status_code == 200
    assert 'class="page-analysis"' in response.text
    assert "Run analysis" in response.text
    assert "balanced" in response.text
    assert "small_wallet_hub_safe" in response.text
    assert "Active basis:" in response.text
    assert "New runs use this local character token/profile slot." in response.text
    assert "Active profile:" in response.text
    assert "Change it in the header or override it for a single run below." in response.text


def test_analysis_run_renders_results(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post("/analysis/run", data={"budget_isk": "500m", "cargo_m3": "12000", "risk_profile": "balanced"})
    assert response.status_code == 200
    assert "Analysis results" in response.text
    assert 'name="return_to" value="/analysis"' in response.text
    assert "Corridor O4T outbound" in response.text
    assert "O4T -&gt; R-ARKN" in response.text
    assert "3-leg span" in response.text
    assert "Jita connectors @ O4T" in response.text
    assert "Personal Layer" in response.text
    assert "Budget 45.3%" in response.text
    assert "Profit pre-logistics 18665000 ISK" in response.text
    assert "Ansiblex legs 1" in response.text
    assert "Ansiblex cost 665000 ISK" in response.text
    assert "Candidate nodes: corridor RE-C26 [corridor_checkpoint]" in response.text
    assert "R-ARKN -&gt; WT-2J9" in response.text
    assert "Snapshot C:/tmp/replay_snapshot.json" in response.text
    assert "Diagnosis: Candidates existed, but the active profile removed them on confidence." in response.text
    assert 'class="log-output"' in response.text


def test_journal_views_render(monkeypatch) -> None:
    client = _client(monkeypatch)
    overview = client.get("/journal?tab=overview")
    reconcile_get = client.get("/journal/reconcile?limit=20")
    reconcile = client.post("/journal/reconcile", data={"limit": 20})
    unmatched = client.get("/journal/unmatched")
    assert overview.status_code == 200
    assert reconcile_get.status_code == 200
    assert reconcile.status_code == 200
    assert unmatched.status_code == 200
    assert "content for overview" in overview.text
    assert "Capsuleer" in overview.text
    assert "Open orders" in overview.text
    assert "42 tx" in overview.text
    assert "Active character sell orders" in overview.text
    assert "Tritanium" in overview.text
    assert "content for reconcile" in reconcile_get.text
    assert "content for reconcile" in reconcile.text
    assert "content for unmatched" in unmatched.text


def test_character_page_and_actions_render(monkeypatch) -> None:
    client = _client(monkeypatch)
    page = client.get("/character")
    auth = client.post("/character/auth/status")
    sync = client.post("/character/context/status")
    assert page.status_code == 200
    assert auth.status_code == 200
    assert sync.status_code == 200
    assert "Character / Auth" in page.text
    assert "character context disabled" in page.text
    assert "Saved characters" in page.text
    assert "auth status" in auth.text
    assert "character status" in sync.text


def test_global_character_switcher_redirects_back_to_page(monkeypatch) -> None:
    activated: list[int] = []

    def _activate(character_id: str) -> dict:
        activated.append(int(character_id))
        return {"ok": True, "character_id": int(character_id), "character_name": "Hauler Alt"}

    client = _client(monkeypatch)
    monkeypatch.setattr(pages.character_service, "activate_character", _activate)
    response = client.post(
        "/character/activate",
        data={"character_id": "90000002", "return_to": "/journal?tab=overview"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/journal?tab=overview"
    assert activated == [90000002]


def test_global_profile_switcher_redirects_back_to_page(monkeypatch) -> None:
    activated: list[str] = []

    def _activate(profile_name: str) -> dict:
        activated.append(str(profile_name))
        return {"ok": True, "profile_name": str(profile_name)}

    client = _client(monkeypatch)
    monkeypatch.setattr(pages.active_profile_service, "activate_profile", _activate)
    response = client.post(
        "/profile/activate",
        data={"profile_name": "balanced", "return_to": "/journal?tab=overview"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/journal?tab=overview"
    assert activated == ["balanced"]


def test_run_analysis_uses_active_profile_when_form_field_is_empty(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(analysis_service_module, "load_config", lambda: {"defaults": {}, "replay": {}, "risk_profile": {"name": "balanced"}})
    monkeypatch.setattr(analysis_service_module, "validate_config", lambda cfg: {"errors": []})
    monkeypatch.setattr(analysis_service_module.active_profile_service, "resolve_active_profile_name", lambda cfg=None: "small_wallet_hub_safe")

    def _invoke(argv: list[str], env_overrides: dict | None = None) -> dict:
        captured["argv"] = list(argv)
        captured["env_overrides"] = dict(env_overrides or {})
        return {
            "ok": True,
            "error": "",
            "exit_code": 0,
            "stdout": "",
            "plan_id": "plan-123",
            "created_files": [],
            "snapshot_path": "",
            "manifest": {"route_count": 0},
            "text_files": {},
        }

    monkeypatch.setattr(analysis_service_module, "invoke_runtime", _invoke)
    monkeypatch.setattr(analysis_service_module, "get_analysis_form_data", lambda: _analysis_form())

    result = analysis_service_module.run_analysis(
        budget_isk_raw="500m",
        cargo_m3_raw="12000",
        snapshot_only=False,
        use_replay=False,
        risk_profile="",
    )

    assert result["ok"] is True
    assert captured["argv"] == ["--cargo-m3", "12000.0", "--budget-isk", "500000000", "--profile", "small_wallet_hub_safe"]
    assert result["selected_profile"] == "small_wallet_hub_safe"


def test_config_page_renders(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/config")
    assert response.status_code == 200
    assert "Config / Runtime info" in response.text
    assert "config.json" in response.text


def test_sensitive_pages_emit_no_store(monkeypatch) -> None:
    client = _client(monkeypatch)
    config_response = client.get("/config")
    character_response = client.get("/character")
    assert config_response.headers.get("Cache-Control") == "no-store"
    assert character_response.headers.get("Cache-Control") == "no-store"


def test_static_assets_are_served(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert "--accent" in response.text
    assert "body.page-analysis" in response.text
    assert ".log-output" in response.text
    assert "overflow-wrap: anywhere;" in response.text


def test_runtime_bridge_extracts_replay_snapshot_path() -> None:
    output = "\n".join(
        [
            "Replay-Snapshot geschrieben: C:/tmp/live_snapshot.json",
            "=== ERSTELLTE DATEIEN ===",
            "C:/tmp/execution_plan.txt",
        ]
    )
    assert runtime_bridge._extract_snapshot_path(output) == "C:/tmp/live_snapshot.json"


def test_webapp_has_no_heartbeat_endpoint(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post("/heartbeat")
    assert response.status_code == 404


def test_remote_access_without_password_is_blocked(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/config", headers={"Host": "remote.example", "X-Forwarded-For": "203.0.113.10"})
    assert response.status_code == 403
    assert "Remote access blocked" in response.text
    assert "NULLSEC_WEBAPP_PASSWORD" in response.text


def test_loopback_proxy_shape_without_password_is_blocked(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/config", headers={"Host": "127.0.0.1:8000", "X-Forwarded-For": "203.0.113.10"})
    assert response.status_code == 403
    assert "direct localhost requests are allowed" in response.text


def test_password_protection_requires_basic_auth(monkeypatch) -> None:
    monkeypatch.setenv("NULLSEC_WEBAPP_PASSWORD", "secret-pass")
    client = _client(monkeypatch)
    response = client.get("/")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_password_protection_allows_authorized_request(monkeypatch) -> None:
    monkeypatch.setenv("NULLSEC_WEBAPP_PASSWORD", "secret-pass")
    client = _client(monkeypatch)
    auth = base64.b64encode(b"trader:secret-pass").decode("ascii")
    response = client.get("/character", headers={"Authorization": f"Basic {auth}"})
    assert response.status_code == 200
    assert "Character / Auth" in response.text


def test_describe_request_access_marks_direct_loopback_request_as_local() -> None:
    request = _access_request(headers={"Host": "127.0.0.1:8000"}, client=("127.0.0.1", 12000))
    context = web_security.describe_request_access(request, {"password_configured": False, "username": "trader", "sensitive_prefixes": ["/character", "/config"]})
    assert context["request_is_local"] is True
    assert context["remote_access_blocked"] is False
    assert context["proxy_headers_present"] is False


def test_describe_request_access_blocks_proxy_headers_without_password() -> None:
    request = _access_request(
        headers={"Host": "127.0.0.1:8000", "X-Forwarded-For": "203.0.113.10", "X-Forwarded-Host": "remote.example"},
        client=("127.0.0.1", 12000),
    )
    context = web_security.describe_request_access(request, {"password_configured": False, "username": "trader", "sensitive_prefixes": ["/character", "/config"]})
    assert context["request_is_local"] is False
    assert context["remote_access_blocked"] is True
    assert context["proxy_headers_present"] is True
    assert context["forwarded_host"] == "203.0.113.10"
    assert context["forwarded_request_host"] == "remote.example"


def test_describe_request_access_marks_loopback_proxy_host_as_non_local() -> None:
    request = _access_request(headers={"Host": "remote.example"}, client=("127.0.0.1", 12000))
    context = web_security.describe_request_access(request, {"password_configured": False, "username": "trader", "sensitive_prefixes": ["/character", "/config"]})
    assert context["request_is_local"] is False
    assert context["remote_access_blocked"] is True


def test_describe_request_access_allows_proxy_shape_only_when_password_is_configured() -> None:
    request = _access_request(
        headers={"Host": "127.0.0.1:8000", "X-Forwarded-For": "203.0.113.10"},
        client=("127.0.0.1", 12000),
    )
    context = web_security.describe_request_access(request, {"password_configured": True, "username": "trader", "sensitive_prefixes": ["/character", "/config"]})
    assert context["request_is_local"] is False
    assert context["remote_access_blocked"] is False
    assert context["proxy_headers_present"] is True


def test_config_service_redacts_web_password_and_omits_raw_config(monkeypatch) -> None:
    cfg = {
        "defaults": {"budget_isk": 500000000},
        "replay": {"enabled": False},
        "route_search": {"enabled": True},
        "route_profiles": {"enabled": True},
        "character_context": {"enabled": True},
        "confidence_calibration": {"enabled": True},
        "personal_history_policy": {"enabled": True},
        "webapp": {"access_password": "web-secret", "access_username": "pilot"},
        "esi": {"client_id": "visible-id", "client_secret": "esi-secret"},
    }
    monkeypatch.setattr(config_service_module, "load_config", lambda: cfg)
    monkeypatch.setattr(config_service_module, "validate_config", lambda value: {"errors": [], "warnings": []})
    page = config_service_module.get_config_page()
    payload = json.dumps(page, ensure_ascii=False)
    assert "config" not in page
    assert "sections" not in page
    assert "web-secret" not in payload
    assert "esi-secret" not in payload
    assert "***" in page["sections_json"]["webapp"]


def test_character_service_omits_raw_config_and_sanitizes_context(monkeypatch) -> None:
    class _FakeSSO:
        def describe_token_status(self) -> dict:
            return {
                "has_token": True,
                "valid": True,
                "scopes": ["scope.one"],
                "token_path": "cache/token.json",
                "character_name": "Capsuleer",
                "character_id": 42,
            }

    context = {
        "character_name": "Capsuleer",
        "source": "cache",
        "warnings": ["character context disabled"],
        "wallet_snapshot": {"secret": "wallet-secret"},
    }
    summary = {"character_name": "Capsuleer", "source": "cache", "wallet_balance": 123.0}
    cfg = {"defaults": {"budget_isk": 500000000}, "esi": {"client_id": "id", "client_secret": "esi-secret"}, "character_context": {}}
    monkeypatch.setattr(character_service_module, "load_config", lambda: cfg)
    monkeypatch.setattr(character_service_module, "_build_sso", lambda value: _FakeSSO())
    monkeypatch.setattr(character_service_module, "resolve_character_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(character_service_module, "build_character_context_summary", lambda *args, **kwargs: summary)
    monkeypatch.setattr(character_service_module, "character_status_lines", lambda *args, **kwargs: ["Character context: generic defaults"])
    monkeypatch.setattr(character_service_module, "requested_character_scopes", lambda value: ["scope.one"])
    monkeypatch.setattr(character_service_module.active_character_service, "capture_current_character", lambda: None)
    monkeypatch.setattr(character_service_module.active_character_service, "list_known_characters", lambda: [])
    page = character_service_module.get_character_page()
    payload = json.dumps(page, ensure_ascii=False)
    assert "config" not in page
    assert page["character_context"] == {"character_name": "Capsuleer", "source": "cache", "warnings": ["character context disabled"]}
    assert page["character_summary"] == {"character_name": "Capsuleer", "source": "cache"}
    assert "esi-secret" not in payload
    assert "wallet-secret" not in payload


def test_character_sync_action_sanitizes_context(monkeypatch) -> None:
    class _FakeSSO:
        def describe_token_status(self) -> dict:
            return {
                "has_token": False,
                "valid": False,
                "scopes": [],
                "token_path": "cache/token.json",
                "character_name": "",
                "character_id": 0,
            }

    context = {
        "character_name": "Capsuleer",
        "source": "live",
        "warnings": ["sync warning"],
        "wallet_snapshot": {"secret": "wallet-secret"},
    }
    summary = {"character_name": "Capsuleer", "source": "live", "wallet_balance": 123.0}
    cfg = {"defaults": {"budget_isk": 500000000}, "esi": {"client_id": "id", "client_secret": "esi-secret"}, "character_context": {}}
    monkeypatch.setattr(character_service_module, "load_config", lambda: cfg)
    monkeypatch.setattr(character_service_module, "_build_sso", lambda value: _FakeSSO())
    monkeypatch.setattr(character_service_module, "resolve_character_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(character_service_module, "build_character_context_summary", lambda *args, **kwargs: summary)
    monkeypatch.setattr(character_service_module, "character_status_lines", lambda *args, **kwargs: ["Character status"])
    monkeypatch.setattr(character_service_module, "requested_character_scopes", lambda value: ["scope.one"])
    monkeypatch.setattr(character_service_module, "sync_character_profile", lambda *args, **kwargs: context)
    monkeypatch.setattr(character_service_module.active_character_service, "capture_current_character", lambda: None)
    monkeypatch.setattr(character_service_module.active_character_service, "list_known_characters", lambda: [])
    page = character_service_module.run_character_action("sync")
    payload = json.dumps(page, ensure_ascii=False)
    assert page["character_context"] == {"character_name": "Capsuleer", "source": "live", "warnings": ["sync warning"]}
    assert page["character_summary"] == {"character_name": "Capsuleer", "source": "live"}
    assert "wallet-secret" not in payload
    assert "esi-secret" not in payload
