from __future__ import annotations

from fastapi.testclient import TestClient

from webapp.app import create_app
from webapp.routes import pages
from webapp.services import runtime_bridge


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
    return {
        "ok": True,
        "error": "",
        "exit_code": 0,
        "runtime_mode": "roundtrip",
        "selected_profile": "balanced",
        "plan_id": "plan-123",
        "route_count": 1,
        "pick_count": 2,
        "actionable_route_count": 1,
        "used_replay": False,
        "snapshot_path": "C:/tmp/replay_snapshot.json",
        "created_files": ["execution_plan_2026.txt", "trade_plan_plan-123.json"],
        "personal_layer_lines": [
            "Personal Layer: ADVISORY | quality USABLE | generic only",
            "Fallback: generic only | advisory mode keeps the generic decision path",
        ],
        "route_cards": [
            {
                "route_label": "Jita -> Amarr",
                "route_id": "route-1",
                "actionable": True,
                "route_confidence": 0.72,
                "transport_confidence": 0.84,
                "capital_lock_risk": 0.18,
                "budget_util_pct": 45.3,
                "cargo_util_pct": 37.7,
                "isk_used": 226373819.86,
                "expected_profit_total": 12000000.0,
                "full_sell_profit_total": 15000000.0,
                "pick_count": 2,
                "warnings": ["calibration fallback"],
                "calibration_warning": "",
                "route_prune_reason": "",
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
            }
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
        "paths": {
            "config_path": "config.json",
            "journal_db_path": "cache/trade_journal.sqlite3",
            "character_profile_path": "cache/character_context/character_profile.json",
        },
        "sections_json": {"defaults": "{\n  \"budget_isk\": 500000000\n}"},
    }


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
    assert "Jita -&gt; Amarr" in response.text
    assert "Personal Layer" in response.text
    assert "Budget 45.3%" in response.text
    assert "Snapshot C:/tmp/replay_snapshot.json" in response.text
    assert 'class="log-output"' in response.text


def test_journal_views_render(monkeypatch) -> None:
    client = _client(monkeypatch)
    overview = client.get("/journal?tab=overview")
    reconcile = client.post("/journal/reconcile", data={"limit": 20})
    unmatched = client.get("/journal/unmatched")
    assert overview.status_code == 200
    assert reconcile.status_code == 200
    assert unmatched.status_code == 200
    assert "content for overview" in overview.text
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
