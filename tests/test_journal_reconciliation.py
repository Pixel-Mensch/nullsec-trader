"""Wallet reconciliation tests for the trade journal."""

from tests.shared import *  # noqa: F401,F403


def _sample_route_results(*, duplicate_pick: bool = False, with_overlap: bool = False) -> list[dict]:
    pick = {
        "type_id": 34,
        "name": "Tritanium",
        "qty": 10,
        "buy_avg": 100.0,
        "target_sell_price": 150.0,
        "sell_avg": 150.0,
        "gross_profit_if_full_sell": 500.0,
        "expected_realized_profit_90d": 480.0,
        "expected_days_to_sell": 10.0,
        "expected_units_sold_90d": 10.0,
        "expected_units_unsold_90d": 0.0,
        "exit_type": "planned",
        "overall_confidence": 0.75,
        "instant": False,
        "mode": "planned_sell",
        "buy_at": "jita_44",
        "sell_at": "o4t",
        "profit": 500.0,
        "unit_volume": 0.01,
        "fill_probability": 0.75,
        "order_duration_days": 90,
    }
    if with_overlap:
        pick.update(
            {
                "character_open_orders": 2,
                "character_open_buy_orders": 0,
                "character_open_sell_orders": 2,
                "character_open_buy_isk_committed": 0.0,
                "character_open_sell_units": 150,
                "open_order_warning_tier": "high",
                "open_order_warning_text": "Existing sell-order overlap for this type.",
                "character_id": 90000001,
            }
        )
    picks = [dict(pick)]
    if duplicate_pick:
        picks.append(dict(pick))
    return [
        {
            "route_tag": "jita_to_o4t",
            "route_label": "jita_44 -> o4t",
            "source_label": "jita_44",
            "dest_label": "o4t",
            "source_node_info": {
                "node_label": "jita_44",
                "node_kind": "location",
                "location_id": 60003760,
                "node_id": 60003760,
                "node_region_id": 10000002,
            },
            "dest_node_info": {
                "node_label": "o4t",
                "node_kind": "structure",
                "structure_id": 1040804972352,
                "node_id": 1040804972352,
            },
            "_character_context_summary": {
                "character_id": 90000001,
                "character_name": "Trader One",
                "overlapping_pick_count": 2 if duplicate_pick and with_overlap else (1 if with_overlap else 0),
                "high_overlap_pick_count": 2 if duplicate_pick and with_overlap else (1 if with_overlap else 0),
                "wallet_balance": 125_000_000.0,
                "open_orders_count": 2 if with_overlap else 0,
            },
            "picks": picks,
        }
    ]


def _import_manifest(db_path: str, *, duplicate_pick: bool = False, with_overlap: bool = False) -> tuple[dict, list[dict]]:
    route_results = _sample_route_results(duplicate_pick=duplicate_pick, with_overlap=with_overlap)
    nst.attach_plan_metadata(route_results, plan_id="plan_reconcile", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_reconcile",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
        primary_output_path="execution_plan_test.txt",
    )
    nst.import_trade_plan_into_journal(db_path, manifest)
    return manifest, route_results


def _wallet_snapshot(
    *,
    buy_qty: float = 10.0,
    sell_qty: float = 10.0,
    tx_type_id: int = 34,
    snapshot_at: str = "2026-03-07T12:00:00+00:00",
    warn_stale_after_sec: int = 86400,
    transactions_pages_loaded: int = 1,
    transactions_total_pages: int = 1,
    transactions_history_truncated: bool = False,
    journal_pages_loaded: int = 1,
    journal_total_pages: int = 1,
    journal_history_truncated: bool = False,
    journal_status: str = "loaded",
    transactions_status: str = "loaded",
) -> dict:
    transactions = [
        {
            "transaction_id": 101,
            "date": "2026-03-08T10:00:00+00:00",
            "is_buy": True,
            "type_id": tx_type_id,
            "quantity": buy_qty,
            "unit_price": 100.0,
            "location_id": 60003760,
            "journal_ref_id": 5001,
        }
    ]
    if sell_qty > 0.0:
        transactions.append(
            {
                "transaction_id": 102,
                "date": "2026-03-15T10:00:00+00:00",
                "is_buy": False,
                "type_id": tx_type_id,
                "quantity": sell_qty,
                "unit_price": 150.0,
                "location_id": 1040804972352,
                "journal_ref_id": 5002,
            }
        )
    return {
        "snapshot_at": snapshot_at,
        "warn_stale_after_sec": int(warn_stale_after_sec),
        "journal_status": journal_status,
        "transactions_status": transactions_status,
        "balance": 125_000_000.0,
        "transactions_pages_loaded": transactions_pages_loaded,
        "transactions_total_pages": transactions_total_pages,
        "transactions_history_truncated": transactions_history_truncated,
        "journal_pages_loaded": journal_pages_loaded,
        "journal_total_pages": journal_total_pages,
        "journal_history_truncated": journal_history_truncated,
        "transactions": transactions,
        "journal_entries": [
            {"id": 9001, "ref_id": 5001, "ref_type": "brokers_fee", "amount": -5.0, "date": "2026-03-08T10:00:05+00:00"},
            {"id": 9002, "ref_id": 5002, "ref_type": "transaction_tax", "amount": -6.0, "date": "2026-03-15T10:00:05+00:00"},
        ],
    }


def test_reconcile_journal_with_wallet_matches_clear_buy_sell_flow() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path)
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        result = nst.reconcile_journal_with_wallet(db_path, _wallet_snapshot(), character_id=90000001)
        entry = nst.fetch_journal_entry(db_path, entry_id)

    assert result["persisted"] is True
    assert entry["character_id"] == 90000001
    assert entry["source_location_id"] == 60003760
    assert entry["target_location_id"] == 1040804972352
    assert entry["reconciliation_status"] == "fully_sold"
    assert entry["matched_wallet_transaction_ids"] == [101, 102]
    assert entry["matched_wallet_journal_ids"] == [9001, 9002]
    assert entry["fee_match_quality"] == "exact"
    assert entry["reconciliation_basis"] == "wallet:full_window"
    assert abs(float(entry["matched_buy_qty"]) - 10.0) < 1e-9
    assert abs(float(entry["matched_sell_qty"]) - 10.0) < 1e-9
    assert abs(float(entry["realized_fee_estimate"]) - 11.0) < 1e-9
    assert abs(float(entry["realized_profit_net"]) - 489.0) < 1e-9


def test_reconcile_marks_ambiguous_wallet_transaction_as_uncertain() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path, duplicate_pick=True)
        result = nst.reconcile_journal_with_wallet(
            db_path,
            {
                "balance": 20_000_000.0,
                "transactions": [
                    {
                        "transaction_id": 501,
                        "date": "2026-03-08T10:00:00+00:00",
                        "is_buy": True,
                        "type_id": 34,
                        "quantity": 10,
                        "unit_price": 100.0,
                        "location_id": 60003760,
                    }
                ],
                "journal_entries": [],
            },
            character_id=90000001,
        )
        entries = nst.fetch_journal_entries(db_path)

    assert len(result["ambiguous_transactions"]) == 1
    assert {entry["reconciliation_status"] for entry in entries} == {"match_uncertain"}
    assert len(manifest["routes"][0]["picks"]) == 2


def test_reconcile_marks_buy_only_trade_as_open_position() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path, with_overlap=True)
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        nst.reconcile_journal_with_wallet(db_path, _wallet_snapshot(sell_qty=0.0), character_id=90000001)
        entry = nst.fetch_journal_entry(db_path, entry_id)
        text = nst.format_open_positions(nst.fetch_journal_entries(db_path), limit=5)

    assert entry["reconciliation_status"] == "bought_open"
    assert "order_warning=HIGH" in text
    assert entry["open_order_warning_tier"] == "high"


def test_reconcile_reports_unmatched_wallet_activity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        _import_manifest(db_path)
        result = nst.reconcile_journal_with_wallet(db_path, _wallet_snapshot(tx_type_id=35), character_id=90000001)
        text = nst.format_unmatched_wallet_activity(result, limit=5)
        entries = nst.fetch_journal_entries(db_path)

    assert len(result["unmatched_transactions"]) >= 1
    assert "tx 101" in text
    assert entries[0]["reconciliation_status"] == "suggested_not_bought"


def test_reconcile_without_wallet_data_keeps_existing_journal_usable() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path)
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        result = nst.reconcile_journal_with_wallet(db_path, {}, character_id=90000001)
        entry = nst.fetch_journal_entry(db_path, entry_id)

    assert result["persisted"] is False
    assert result["wallet_available"] is False
    assert str(entry.get("reconciliation_status", "") or "") == ""


def test_reconciliation_overview_and_personal_history_include_wallet_status() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        _import_manifest(db_path)
        result = nst.reconcile_journal_with_wallet(db_path, _wallet_snapshot(), character_id=90000001)
        overview = nst.format_reconciliation_overview(result, limit=5)
        personal = nst.format_personal_trade_history(nst.fetch_journal_entries(db_path), limit=5)

    assert "WALLET RECONCILIATION" in overview
    assert "Matched entries: 1" in overview
    assert "Wallet quality:" in overview
    assert "PERSONAL TRADE HISTORY" in personal
    assert "History quality=" in personal
    assert "Persoenliche Trefferquoten:" in personal
    assert "Soll/Ist groesste Abweichungen" in personal


def test_run_journal_cli_reconcile_and_unmatched_use_cached_character_context() -> None:
    cfg = _minimal_valid_config()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        cache_path = os.path.join(tmpdir, "character_profile.json")
        cfg["esi"]["client_id"] = "client-id"
        cfg["character_context"] = {
            "enabled": True,
            "profile_cache_ttl_sec": 3600,
            "profile_cache_path": cache_path,
            "token_path": os.path.join(tmpdir, "token.json"),
            "metadata_path": os.path.join(tmpdir, "metadata.json"),
        }
        cfg_path = os.path.join(tmpdir, "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        nst.save_cache_record(
            cache_path,
            {
                "character_id": 90000001,
                "character_name": "Cached Pilot",
                "last_successful_sync": "2026-03-07T10:00:00+00:00",
                "loaded_scopes": ["esi-wallet.read_character_wallet.v1"],
                "skills_snapshot": {},
                "open_orders_snapshot": {},
                "wallet_snapshot": _wallet_snapshot(),
            },
            source="cache",
        )
        _import_manifest(db_path)
        buf = io.StringIO()
        with redirect_stdout(buf):
            nst.run_journal_cli(["reconcile", "--journal-db", db_path, "--config", cfg_path, "--limit", "5"])
            nst.run_journal_cli(["personal", "--journal-db", db_path, "--config", cfg_path, "--limit", "5"])
            nst.run_journal_cli(["unmatched", "--journal-db", db_path, "--config", cfg_path, "--limit", "5"])
        out = buf.getvalue()

    assert "WALLET RECONCILIATION" in out
    assert "PERSONAL TRADE HISTORY" in out
    assert "UNGEMATCHTE WALLET-AKTIVITAET" in out


def test_reconcile_reports_truncated_and_stale_wallet_history() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        _import_manifest(db_path)
        result = nst.reconcile_journal_with_wallet(
            db_path,
            _wallet_snapshot(
                snapshot_at="2026-03-01T12:00:00+00:00",
                warn_stale_after_sec=3600,
                transactions_pages_loaded=2,
                transactions_total_pages=5,
                transactions_history_truncated=True,
                journal_pages_loaded=2,
                journal_total_pages=4,
                journal_history_truncated=True,
            ),
            character_id=90000001,
        )
        overview = nst.format_reconciliation_overview(result, limit=5)
        unmatched = nst.format_unmatched_wallet_activity(result, limit=5)

    assert result["wallet_history_truncated"] is True
    assert result["wallet_data_freshness"] == "stale"
    assert result["reconciliation_basis"] == "wallet:truncated_window"
    assert any("truncated by page limit" in str(w) for w in result["data_quality_warnings"])
    assert "history=truncated" in overview
    assert "tx_pages=2/5" in overview
    assert "journal_pages=2/4" in unmatched


def test_reconcile_marks_old_entries_uncertain_when_transaction_window_is_truncated() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path)
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        result = nst.reconcile_journal_with_wallet(
            db_path,
            {
                "snapshot_at": "2026-03-07T12:00:00+00:00",
                "warn_stale_after_sec": 86400,
                "transactions_status": "loaded",
                "journal_status": "loaded",
                "transactions_pages_loaded": 1,
                "transactions_total_pages": 3,
                "transactions_history_truncated": True,
                "transactions": [
                    {
                        "transaction_id": 777,
                        "date": "2026-03-14T10:00:00+00:00",
                        "is_buy": True,
                        "type_id": 35,
                        "quantity": 2,
                        "unit_price": 900.0,
                        "location_id": 60003760,
                    }
                ],
                "journal_entries": [],
            },
            character_id=90000001,
        )
        entry = nst.fetch_journal_entry(db_path, entry_id)

    assert result["status_counts"]["match_uncertain"] == 1
    assert entry["reconciliation_status"] == "match_uncertain"
    assert "wallet transaction window does not cover this entry" in str(entry["match_reason"])


def test_reconcile_uses_conservative_fee_fallback_for_unique_nearby_journal_entry() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path)
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        result = nst.reconcile_journal_with_wallet(
            db_path,
            {
                "snapshot_at": "2026-03-07T12:00:00+00:00",
                "warn_stale_after_sec": 86400,
                "transactions_status": "loaded",
                "journal_status": "loaded",
                "transactions": [
                    {
                        "transaction_id": 101,
                        "date": "2026-03-08T10:00:00+00:00",
                        "is_buy": True,
                        "type_id": 34,
                        "quantity": 10,
                        "unit_price": 100.0,
                        "location_id": 60003760,
                    },
                    {
                        "transaction_id": 102,
                        "date": "2026-03-15T10:00:00+00:00",
                        "is_buy": False,
                        "type_id": 34,
                        "quantity": 10,
                        "unit_price": 150.0,
                        "location_id": 1040804972352,
                    },
                ],
                "journal_entries": [
                    {
                        "id": 9501,
                        "ref_type": "transaction_tax",
                        "amount": -6.0,
                        "date": "2026-03-15T10:00:15+00:00",
                    }
                ],
            },
            character_id=90000001,
        )
        entry = nst.fetch_journal_entry(db_path, entry_id)

    assert result["fee_match_quality"] == "partial"
    assert entry["fee_match_quality"] == "partial"
    assert entry["matched_wallet_journal_ids"] == [9501]
    assert abs(float(entry["realized_fee_estimate"]) - 6.0) < 1e-9


def test_reconcile_marks_fee_matching_uncertain_when_multiple_nearby_fee_candidates_exist() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        manifest, _ = _import_manifest(db_path)
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        nst.reconcile_journal_with_wallet(
            db_path,
            {
                "snapshot_at": "2026-03-07T12:00:00+00:00",
                "warn_stale_after_sec": 86400,
                "transactions_status": "loaded",
                "journal_status": "loaded",
                "transactions": [
                    {
                        "transaction_id": 101,
                        "date": "2026-03-08T10:00:00+00:00",
                        "is_buy": True,
                        "type_id": 34,
                        "quantity": 10,
                        "unit_price": 100.0,
                        "location_id": 60003760,
                    }
                ],
                "journal_entries": [
                    {
                        "id": 9601,
                        "ref_type": "brokers_fee",
                        "amount": -4.0,
                        "date": "2026-03-08T10:00:10+00:00",
                    },
                    {
                        "id": 9602,
                        "ref_type": "brokers_fee",
                        "amount": -4.5,
                        "date": "2026-03-08T10:00:15+00:00",
                    },
                ],
            },
            character_id=90000001,
        )
        entry = nst.fetch_journal_entry(db_path, entry_id)

    assert entry["fee_match_quality"] == "uncertain"
    assert entry["matched_wallet_journal_ids"] == []
    assert "fee matching uncertain" in str(entry["match_reason"]) or "fee:uncertain" in str(entry["match_reason"])


def test_execution_plan_surfaces_order_overlap_warning_tier() -> None:
    route_results = _sample_route_results(with_overlap=True)
    nst.attach_plan_metadata(route_results, plan_id="plan_overlap", created_at="2026-03-07T12:00:00+00:00")
    route_results[0]["isk_used"] = 1000.0
    route_results[0]["budget_total"] = 2000.0
    route_results[0]["profit_total"] = 500.0
    route_results[0]["expected_realized_profit_total"] = 480.0
    route_results[0]["full_sell_profit_total"] = 500.0
    route_results[0]["route_actionable"] = True
    route_results[0]["cost_model_confidence"] = "normal"
    ctx = {
        "enabled": True,
        "available": True,
        "source": "cache",
        "character_id": 90000001,
        "profile": {
            "character_id": 90000001,
            "character_name": "Trader One",
            "last_successful_sync": "2026-03-07T10:00:00+00:00",
            "loaded_scopes": [],
            "skills_snapshot": {},
            "wallet_snapshot": {"balance": 125_000_000.0},
            "open_orders_snapshot": {"count": 2},
        },
        "open_orders_by_type": {
            "34": {
                "name": "Tritanium",
                "open_order_count": 2,
                "buy_order_count": 0,
                "sell_order_count": 2,
                "buy_isk_committed": 0.0,
                "sell_units": 150,
                "location_ids": [1040804972352],
            }
        },
        "warnings": [],
    }
    nst.attach_character_context_to_result(route_results[0], ctx, budget_isk=100_000_000.0)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_test.txt")
        nst.write_execution_plan_profiles(out_path, "2026-03-07_12-00-00", route_results)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

    assert "Order Overlap 1 picks" in content
    assert "[WARN][ORDER-HIGH] Existing sell-order overlap for this type." in content
