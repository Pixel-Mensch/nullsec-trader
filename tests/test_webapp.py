from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient
from starlette.requests import Request

from webapp import security as web_security
from webapp.app import create_app
from webapp.routes import pages
from webapp.services import character_service as character_service_module, config_service as config_service_module, runtime_bridge


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
        "risk_profiles": [{"name": "balanced", "description": "Default"}],
        "replay_enabled": False,
        "route_mode": "roundtrip",
        "default_profile_name": "balanced",
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
            "expected_profit_total": 12000000.0,
            "full_sell_profit_total": 15000000.0,
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
            "expected_profit_total": 18000000.0,
            "full_sell_profit_total": 22000000.0,
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
            "expected_profit_total": 2500000.0,
            "full_sell_profit_total": 3100000.0,
            "pick_count": 1,
            "warnings": ["shipping warning"],
            "calibration_warning": "",
            "route_prune_reason": "confidence",
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
    monkeypatch.setattr(pages.character_service, "run_character_action", lambda action: {**_character_page(), "action_message": f"character {action}"})
    monkeypatch.setattr(pages.config_service, "get_config_page", lambda: _config_page())
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


def test_analysis_run_renders_results(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post("/analysis/run", data={"budget_isk": "500m", "cargo_m3": "12000", "risk_profile": "balanced"})
    assert response.status_code == 200
    assert "Analysis results" in response.text
    assert "Corridor O4T outbound" in response.text
    assert "O4T -&gt; R-ARKN" in response.text
    assert "3-leg span" in response.text
    assert "Jita connectors @ O4T" in response.text
    assert "Personal Layer" in response.text
    assert "Budget 45.3%" in response.text
    assert "Snapshot C:/tmp/replay_snapshot.json" in response.text
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
    assert "auth status" in auth.text
    assert "character status" in sync.text


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
    page = character_service_module.run_character_action("sync")
    payload = json.dumps(page, ensure_ascii=False)
    assert page["character_context"] == {"character_name": "Capsuleer", "source": "live", "warnings": ["sync warning"]}
    assert page["character_summary"] == {"character_name": "Capsuleer", "source": "live"}
    assert "wallet-secret" not in payload
    assert "esi-secret" not in payload
