from __future__ import annotations

from tests.shared import *  # noqa: F401,F403


def _fake_jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}
    header_s = nst.b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_s = nst.b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{header_s}.{payload_s}.sig"


class _FakeCharacterClient:
    def get_identity(self, requested_scopes, *, allow_login=True):
        return {
            "character_id": 90000001,
            "character_name": "Trader One",
            "loaded_scopes": list(requested_scopes),
            "token_expires_at": 4_102_444_800,
        }

    def get_public_character(self, character_id: int):
        return {"corporation_id": 99000001}

    def get_skills(self, character_id: int, *, allow_login=True):
        return {
            "total_sp": 1_000_000,
            "unallocated_sp": 500,
            "skills": [
                {"skill_id": 1, "active_skill_level": 5, "trained_skill_level": 5, "skillpoints_in_skill": 1000},
                {"skill_id": 2, "active_skill_level": 4, "trained_skill_level": 4, "skillpoints_in_skill": 2000},
                {"skill_id": 3, "active_skill_level": 3, "trained_skill_level": 3, "skillpoints_in_skill": 3000},
            ],
        }

    def get_skill_queue(self, character_id: int, *, allow_login=True):
        return [{"skill_id": 2, "queue_position": 0, "finished_level": 5}]

    def get_open_orders(self, character_id: int, *, allow_login=True):
        return [
            {"type_id": 34, "is_buy_order": False, "volume_remain": 150, "price": 11.0, "location_id": 60003760},
            {"type_id": 34, "is_buy_order": True, "volume_remain": 50, "price": 9.5, "location_id": 60003760},
        ]

    def get_wallet_balance(self, character_id: int, *, allow_login=True):
        return 125_000_000.0

    def get_wallet_journal(self, character_id: int, *, max_pages=None, allow_login=True, with_meta=False):
        rows = [{"id": 1, "amount": 1_000_000.0, "date": "2026-03-05T10:00:00+00:00"}]
        meta = {"pages_loaded": 2, "total_pages": 4, "page_limit": int(max_pages or 0), "history_truncated": True}
        return (rows, meta) if with_meta else rows

    def get_wallet_transactions(self, character_id: int, *, max_pages=None, allow_login=True, with_meta=False):
        rows = [{"transaction_id": 1, "type_id": 34, "quantity": 100, "date": "2026-03-06T10:00:00+00:00"}]
        meta = {"pages_loaded": 2, "total_pages": 3, "page_limit": int(max_pages or 0), "history_truncated": True}
        return (rows, meta) if with_meta else rows

    def resolve_names(self, ids: list[int]):
        mapping = {
            1: "Accounting",
            2: "Broker Relations",
            3: "Advanced Broker Relations",
            34: "Tritanium",
        }
        return {int(i): mapping.get(int(i), f"id_{int(i)}") for i in ids}


class _FailingCharacterClient:
    def get_identity(self, requested_scopes, *, allow_login=True):
        raise nst.CharacterESIError("network down")


class _FakeSSO:
    def ensure_token(self, requested_scopes, *, allow_login=True):
        return {"access_token": "fake-token"}


class _CharacterSeqSession:
    def __init__(self, responses: list[_SeqResponse]):
        self._responses = list(responses)
        self.headers = {}

    def get(self, url, params=None, headers=None, timeout=30):
        if not self._responses:
            raise RuntimeError("no fake responses left")
        return self._responses.pop(0)


def test_decode_access_token_claims_extracts_identity() -> None:
    token = _fake_jwt(
        {
            "sub": "CHARACTER:EVE:90000001",
            "name": "Trader One",
            "scp": ["esi-skills.read_skills.v1", "esi-wallet.read_character_wallet.v1"],
        }
    )
    claims = nst.decode_access_token_claims(token)
    ident = nst.token_identity_from_claims(claims)
    assert ident["character_id"] == 90000001
    assert ident["character_name"] == "Trader One"
    assert "esi-skills.read_skills.v1" in ident["scopes"]


def test_parse_cli_args_supports_auth_and_character_commands() -> None:
    auth_args = nst.parse_cli_args(["auth", "login"])
    char_args = nst.parse_cli_args(["character", "sync"])
    assert auth_args["command"] == "auth"
    assert auth_args["auth_action"] == "login"
    assert char_args["command"] == "character"
    assert char_args["character_action"] == "sync"


def test_eve_character_client_reports_wallet_paging_metadata() -> None:
    cfg = _minimal_valid_config()
    session = _CharacterSeqSession(
        [
            _SeqResponse(200, [{"transaction_id": 1, "type_id": 34, "quantity": 5}], {"X-Pages": "3"}),
            _SeqResponse(200, [{"transaction_id": 2, "type_id": 34, "quantity": 7}], {"X-Pages": "3"}),
            _SeqResponse(200, [{"id": 10, "amount": -5.0}], {"X-Pages": "4"}),
            _SeqResponse(200, [{"id": 11, "amount": -6.0}], {"X-Pages": "4"}),
        ]
    )
    client = nst.EveCharacterClient(cfg, session=session, sso=_FakeSSO())

    tx_rows, tx_meta = client.get_wallet_transactions(90000001, max_pages=2, with_meta=True)
    journal_rows, journal_meta = client.get_wallet_journal(90000001, max_pages=2, with_meta=True)

    assert len(tx_rows) == 2
    assert tx_meta["pages_loaded"] == 2
    assert tx_meta["total_pages"] == 3
    assert tx_meta["history_truncated"] is True
    assert len(journal_rows) == 2
    assert journal_meta["pages_loaded"] == 2
    assert journal_meta["total_pages"] == 4
    assert journal_meta["history_truncated"] is True


def test_sync_character_profile_maps_skills_orders_wallet_and_queue() -> None:
    cfg = _minimal_valid_config()
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg["character_context"] = {
            "enabled": True,
            "include_skill_queue": True,
            "profile_cache_path": os.path.join(tmpdir, "profile.json"),
            "token_path": os.path.join(tmpdir, "token.json"),
            "metadata_path": os.path.join(tmpdir, "metadata.json"),
        }
        context = nst.sync_character_profile(cfg, client=_FakeCharacterClient())

    assert context["source"] == "live"
    assert context["character_name"] == "Trader One"
    assert context["fee_skill_overrides"] == {
        "accounting": 5,
        "broker_relations": 4,
        "advanced_broker_relations": 3,
    }
    assert context["open_orders_count"] == 2
    assert abs(float(context["wallet_balance"]) - 125_000_000.0) < 1e-9
    queue = context["profile"]["skill_queue_snapshot"]
    assert int(queue["count"]) == 1
    wallet_snapshot = context["profile"]["wallet_snapshot"]
    assert int(wallet_snapshot["journal_pages_loaded"]) == 2
    assert int(wallet_snapshot["transactions_pages_loaded"]) == 2
    assert bool(wallet_snapshot["history_truncated"]) is True
    assert str(wallet_snapshot["transactions_oldest_at"]).startswith("2026-03-06T10:00:00")


def test_resolve_character_context_falls_back_to_cache_when_live_sync_fails() -> None:
    cfg = _minimal_valid_config()
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "profile.json")
        cfg["esi"]["client_id"] = "client-id"
        cfg["character_context"] = {
            "enabled": True,
            "profile_cache_ttl_sec": 0,
            "profile_cache_path": cache_path,
            "token_path": os.path.join(tmpdir, "token.json"),
            "metadata_path": os.path.join(tmpdir, "metadata.json"),
        }
        cached_profile = {
            "character_id": 90000001,
            "character_name": "Cached Pilot",
            "last_successful_sync": "2026-03-07T10:00:00+00:00",
            "loaded_scopes": ["esi-skills.read_skills.v1"],
            "skills_snapshot": {"fee_skills": {"accounting": 5}},
            "open_orders_snapshot": {"count": 0, "by_type": {}},
            "wallet_snapshot": {"balance": 10_000_000.0},
        }
        nst.save_cache_record(cache_path, cached_profile, source="live")
        context = nst.resolve_character_context(cfg, replay_enabled=False, client=_FailingCharacterClient())

    assert context["source"] == "cache"
    assert context["character_name"] == "Cached Pilot"
    assert any("using cache" in str(w).lower() for w in context["warnings"])


def test_apply_character_fee_overrides_uses_real_skill_levels() -> None:
    fees_cfg = {
        "sales_tax": 0.075,
        "sell_broker_fee": 0.03,
        "scc_surcharge": 0.005,
        "skills": {"accounting": 3, "broker_relations": 3, "advanced_broker_relations": 3},
    }
    context = {
        "available": True,
        "source": "live",
        "fee_skill_overrides": {"accounting": 5, "broker_relations": 4, "advanced_broker_relations": 2},
    }
    merged, meta = nst.apply_character_fee_overrides(fees_cfg, context)
    assert meta["applied"] is True
    assert merged["skills"]["accounting"] == 5
    assert merged["skills"]["broker_relations"] == 4
    assert merged["skills"]["advanced_broker_relations"] == 2


def test_attach_character_context_to_result_marks_order_overlap() -> None:
    result = {"picks": [{"type_id": 34, "name": "Tritanium"}]}
    context = {
        "enabled": True,
        "available": True,
        "source": "cache",
        "profile": {
            "character_id": 90000001,
            "character_name": "Trader One",
            "last_successful_sync": "2026-03-07T10:00:00+00:00",
            "loaded_scopes": [],
            "skills_snapshot": {"fee_skills": {"accounting": 5}},
            "wallet_snapshot": {"balance": 25_000_000.0},
            "open_orders_snapshot": {
                "count": 1,
                "buy_order_count": 0,
                "sell_order_count": 1,
                "buy_isk_committed": 0.0,
                "sell_gross_isk": 1_000_000.0,
            },
        },
        "open_orders_by_type": {
            "34": {
                "name": "Tritanium",
                "open_order_count": 1,
                "buy_order_count": 0,
                "sell_order_count": 1,
                "buy_isk_committed": 0.0,
                "sell_units": 150,
                "location_ids": [60003760],
            }
        },
        "warnings": [],
    }
    updated = nst.attach_character_context_to_result(result, context, budget_isk=30_000_000.0)
    assert updated["picks"][0]["character_open_orders"] == 1
    assert updated["picks"][0]["character_open_sell_units"] == 150
    summary = updated["_character_context_summary"]
    assert summary["overlapping_pick_count"] == 1
    assert summary["budget_exceeds_wallet"] is True
    assert summary["wallet_data_freshness"] in {"fresh", "unknown"}


def test_validate_config_rejects_invalid_character_context_fields() -> None:
    cfg = _minimal_valid_config()
    cfg["character_context"] = {"enabled": "yes", "profile_cache_ttl_sec": -1, "wallet_warn_stale_after_sec": -5}
    vr = nst.validate_config(cfg)
    assert any("character_context.enabled must be a boolean" in str(e) for e in vr.get("errors", []))
    assert any("character_context.profile_cache_ttl_sec" in str(e) for e in vr.get("errors", []))
    assert any("character_context.wallet_warn_stale_after_sec" in str(e) for e in vr.get("errors", []))
