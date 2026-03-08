"""Trade journal tests."""

import sqlite3

from tests.shared import *  # noqa: F401,F403


def test_initialize_journal_db_migrates_legacy_schema_before_creating_new_indexes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "legacy_journal.sqlite3")
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE journal_entries (
                    journal_entry_id TEXT PRIMARY KEY,
                    pick_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    route_profile TEXT NOT NULL,
                    route_label TEXT NOT NULL,
                    source_market TEXT NOT NULL,
                    target_market TEXT NOT NULL,
                    item_type_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    proposed_qty REAL NOT NULL,
                    proposed_buy_price REAL NOT NULL,
                    proposed_sell_price REAL NOT NULL,
                    proposed_full_sell_profit REAL NOT NULL,
                    proposed_expected_profit REAL NOT NULL,
                    proposed_expected_days_to_sell REAL NOT NULL,
                    proposed_exit_type TEXT NOT NULL,
                    proposed_confidence REAL NOT NULL,
                    proposed_expected_units_sold REAL NOT NULL DEFAULT 0,
                    proposed_expected_units_unsold REAL NOT NULL DEFAULT 0,
                    actual_buy_qty REAL NOT NULL DEFAULT 0,
                    actual_buy_price_avg REAL NOT NULL DEFAULT 0,
                    actual_sell_qty REAL NOT NULL DEFAULT 0,
                    actual_sell_price_avg REAL NOT NULL DEFAULT 0,
                    actual_fees_paid REAL NOT NULL DEFAULT 0,
                    actual_shipping_paid REAL NOT NULL DEFAULT 0,
                    actual_profit_net REAL NOT NULL DEFAULT 0,
                    first_buy_at TEXT NOT NULL DEFAULT '',
                    last_sell_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    calibration_warning TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE journal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_entry_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    qty REAL NOT NULL DEFAULT 0,
                    price REAL NOT NULL DEFAULT 0,
                    fees_paid REAL NOT NULL DEFAULT 0,
                    shipping_paid REAL NOT NULL DEFAULT 0,
                    happened_at TEXT NOT NULL,
                    status_to TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX idx_journal_entries_status ON journal_entries(status);
                CREATE INDEX idx_journal_entries_plan_id ON journal_entries(plan_id);
                CREATE INDEX idx_journal_entries_route_id ON journal_entries(route_id);
                CREATE INDEX idx_journal_entries_updated_at ON journal_entries(updated_at);
                CREATE INDEX idx_journal_events_entry ON journal_events(journal_entry_id, happened_at, event_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

        path = nst.initialize_journal_db(db_path)
        assert str(path) == db_path

        conn = sqlite3.connect(db_path)
        try:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(journal_entries)").fetchall()}
            indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(journal_entries)").fetchall()}
        finally:
            conn.close()

    assert "reconciliation_status" in columns
    assert "match_confidence" in columns
    assert "idx_journal_entries_reconciliation_status" in indexes


def _sample_route_results() -> list[dict]:
    return [
        {
            "route_tag": "jita_to_o4t",
            "route_label": "jita_44 -> o4t",
            "source_label": "jita_44",
            "dest_label": "o4t",
            "picks": [
                {
                    "type_id": 34,
                    "name": "Tritanium",
                    "qty": 10,
                    "buy_avg": 100.0,
                    "target_sell_price": 155.0,
                    "sell_avg": 155.0,
                    "gross_profit_if_full_sell": 550.0,
                    "expected_realized_profit_90d": 500.0,
                    "expected_days_to_sell": 12.0,
                    "expected_units_sold_90d": 9.0,
                    "expected_units_unsold_90d": 1.0,
                    "exit_type": "planned",
                    "overall_confidence": 0.72,
                    "instant": False,
                    "mode": "planned_sell",
                }
            ],
        }
    ]


def test_attach_plan_metadata_assigns_stable_ids() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_1", created_at="2026-03-07T12:00:00+00:00")
    route = route_results[0]
    pick = route["picks"][0]
    assert str(route["plan_id"]) == "plan_test_1"
    assert str(route["route_id"]) == "jita_to_o4t"
    assert str(pick["plan_id"]) == "plan_test_1"
    assert str(pick["route_id"]) == "jita_to_o4t"
    assert str(pick["pick_id"]).startswith("pick_")
    assert str(pick["journal_entry_id"]) == str(pick["pick_id"])


def test_trade_plan_manifest_falls_back_to_sell_avg_for_instant_picks() -> None:
    route_results = [
        {
            "route_tag": "o4t_to_jita",
            "route_label": "o4t -> jita_44",
            "source_label": "o4t",
            "dest_label": "jita_44",
            "route_actionable": True,
            "isk_used": 1000.0,
            "budget_total": 2000.0,
            "budget_util_pct": 50.0,
            "m3_used": 10.0,
            "cargo_total": 20.0,
            "cargo_util_pct": 50.0,
            "expected_realized_profit_total": 500.0,
            "full_sell_profit_total": 550.0,
            "picks": [
                {
                    "type_id": 35,
                    "name": "Pyerite",
                    "qty": 5,
                    "buy_avg": 100.0,
                    "sell_avg": 250.0,
                    "target_sell_price": 0.0,
                    "gross_profit_if_full_sell": 550.0,
                    "expected_realized_profit_90d": 500.0,
                    "expected_days_to_sell": 0.0,
                    "exit_type": "instant",
                    "overall_confidence": 0.88,
                    "instant": True,
                    "mode": "instant",
                }
            ],
        }
    ]
    nst.attach_plan_metadata(route_results, plan_id="plan_test_sell_avg", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_sell_avg",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    route = manifest["routes"][0]
    pick = route["picks"][0]
    assert float(pick["proposed_sell_price"]) == 250.0
    assert float(route["budget_util_pct"]) == 50.0
    assert float(route["cargo_util_pct"]) == 50.0
    assert float(route["expected_realized_profit_total"]) == 500.0


def test_trade_plan_import_creates_journal_entry() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_2", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_2",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
        primary_output_path="execution_plan_test.txt",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        result = nst.import_trade_plan_into_journal(db_path, manifest, notes="imported from test")
        assert int(result["imported"]) == 1
        entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
        entry = nst.fetch_journal_entry(db_path, entry_id)
        assert str(entry["plan_id"]) == "plan_test_2"
        assert str(entry["route_label"]) == "jita_44 -> o4t"
        assert int(entry["item_type_id"]) == 34
        assert float(entry["proposed_sell_price"]) == 155.0
        assert float(entry["proposed_expected_profit"]) == 500.0
        assert abs(float(entry["proposed_overall_confidence_raw"]) - 0.72) < 1e-9
        assert abs(float(entry["proposed_overall_confidence_calibrated"]) - 0.72) < 1e-9
        assert str(entry["status"]) == "planned"
        assert "imported from test" in str(entry["notes"])


def test_execution_plan_profiles_include_plan_and_pick_ids() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_ids", created_at="2026-03-07T12:00:00+00:00")
    route_results[0]["source_node_info"] = {"node_label": "jita_44", "node_kind": "location", "location_id": 60003760, "node_id": 60003760, "node_region_id": 10000002}
    route_results[0]["dest_node_info"] = {"node_label": "o4t", "node_kind": "structure", "structure_id": 1040804972352, "node_id": 1040804972352}
    route_results[0]["isk_used"] = 1000.0
    route_results[0]["budget_total"] = 2000.0
    route_results[0]["profit_total"] = 500.0
    route_results[0]["expected_realized_profit_total"] = 500.0
    route_results[0]["full_sell_profit_total"] = 550.0
    route_results[0]["route_actionable"] = True
    route_results[0]["cost_model_confidence"] = "normal"
    route_results[0]["picks"][0]["cost"] = 1000.0
    route_results[0]["picks"][0]["revenue_net"] = 1500.0
    route_results[0]["picks"][0]["profit"] = 500.0
    route_results[0]["picks"][0]["unit_volume"] = 0.01
    route_results[0]["picks"][0]["buy_at"] = "jita_44"
    route_results[0]["picks"][0]["sell_at"] = "o4t"
    route_results[0]["picks"][0]["fill_probability"] = 0.72
    route_results[0]["picks"][0]["order_duration_days"] = 90
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "execution_plan_test.txt")
        nst.write_execution_plan_profiles(out_path, "2026-03-07_12-00-00", route_results)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    assert "Plan ID: plan_test_ids" in content
    assert "Route ID: jita_to_o4t" in content
    assert "Pick ID: " in content


def test_parse_cli_args_detects_journal_mode() -> None:
    args = nst.parse_cli_args(["journal", "overview"])
    assert str(args.get("command", "")) == "journal"
    assert list(args.get("journal_argv", [])) == ["overview"]


def test_journal_buy_sell_updates_and_profit_calculation() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_3", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_3",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        nst.import_trade_plan_into_journal(db_path, manifest)

        bought = nst.record_journal_buy(
            db_path,
            entry_id,
            qty=10,
            price=100.0,
            fees_paid=5.0,
            shipping_paid=10.0,
            happened_at="2026-03-01T10:00:00+00:00",
            notes="full buy executed",
        )
        assert str(bought["status"]) == "bought"
        assert abs(float(bought["actual_buy_qty"]) - 10.0) < 1e-9
        assert abs(float(bought["actual_buy_price_avg"]) - 100.0) < 1e-9

        partial = nst.record_journal_sell(
            db_path,
            entry_id,
            qty=6,
            price=140.0,
            fees_paid=4.0,
            shipping_paid=0.0,
            happened_at="2026-03-05T10:00:00+00:00",
        )
        assert str(partial["status"]) == "partially_sold"
        assert abs(float(partial["actual_sell_qty"]) - 6.0) < 1e-9

        sold = nst.record_journal_sell(
            db_path,
            entry_id,
            qty=4,
            price=150.0,
            fees_paid=3.0,
            shipping_paid=2.0,
            happened_at="2026-03-10T10:00:00+00:00",
            notes="position closed",
        )
        assert str(sold["status"]) == "sold"
        assert abs(float(sold["actual_sell_qty"]) - 10.0) < 1e-9
        assert abs(float(sold["actual_sell_price_avg"]) - 144.0) < 1e-9
        assert abs(float(sold["actual_fees_paid"]) - 12.0) < 1e-9
        assert abs(float(sold["actual_shipping_paid"]) - 12.0) < 1e-9
        assert abs(float(sold["actual_profit_net"]) - 416.0) < 1e-9
        assert str(sold["first_buy_at"]) == "2026-03-01T10:00:00+00:00"
        assert str(sold["last_sell_at"]) == "2026-03-10T10:00:00+00:00"


def test_journal_status_updates_move_entries_between_open_and_closed() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_4", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_4",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        nst.import_trade_plan_into_journal(db_path, manifest)
        updated = nst.update_journal_entry_status(
            db_path,
            entry_id,
            "invalidated",
            happened_at="2026-03-08T09:00:00+00:00",
            notes="market flipped before buy",
        )
        assert str(updated["status"]) == "invalidated"
        open_entries = nst.fetch_open_journal_entries(db_path)
        closed_entries = nst.fetch_closed_journal_entries(db_path)
        assert all(str(entry["journal_entry_id"]) != entry_id for entry in open_entries)
        assert any(str(entry["journal_entry_id"]) == entry_id for entry in closed_entries)


def test_journal_report_compares_expected_vs_realized() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_5", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_5",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        nst.import_trade_plan_into_journal(db_path, manifest)
        nst.record_journal_buy(
            db_path,
            entry_id,
            qty=10,
            price=100.0,
            fees_paid=5.0,
            shipping_paid=10.0,
            happened_at="2026-03-01T10:00:00+00:00",
        )
        nst.record_journal_sell(
            db_path,
            entry_id,
            qty=10,
            price=144.3,
            fees_paid=4.0,
            shipping_paid=0.0,
            happened_at="2026-03-15T10:00:00+00:00",
        )
        entries = nst.fetch_journal_entries(db_path)
        report = nst.build_journal_report(entries, limit=5)
        assert int(report["summary"]["sold_count"]) == 1
        sold_entry = report["sold_entries"][0]
        assert str(sold_entry["journal_entry_id"]) == entry_id
        assert abs(float(sold_entry["comparison_profit_delta"]) - (-76.0)) < 1e-9
        assert abs(float(sold_entry["actual_days_to_sell"]) - 14.0) < 1e-9
        assert abs(float(sold_entry["comparison_days_delta"]) - 2.0) < 1e-9
        assert report["overestimated"][0]["journal_entry_id"] == entry_id
        overview = nst.format_journal_overview(entries, limit=5)
        closed = nst.format_closed_positions(entries, limit=5)
        report_text = nst.format_journal_report(entries, limit=5)
        assert "TRADE JOURNAL OVERVIEW" in overview
        assert entry_id in overview
        assert "ABGESCHLOSSENE POSITIONEN" in closed
        assert "TRADE JOURNAL REPORT" in report_text


def test_personal_trade_history_reports_fallback_when_no_personal_outcomes_exist() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_personal_none", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_personal_none",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        nst.import_trade_plan_into_journal(db_path, manifest)
        entries = nst.fetch_journal_entries(db_path)
        personal = nst.format_personal_trade_history(entries, limit=5)
    assert "History quality=none" in personal
    assert "fallback generic" in personal


def test_run_journal_cli_overview_prints_summary() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_6", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_6",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        nst.import_trade_plan_into_journal(db_path, manifest)
        buf = io.StringIO()
        with redirect_stdout(buf):
            nst.run_journal_cli(["overview", "--journal-db", db_path, "--limit", "5"])
        out = buf.getvalue()
    assert "TRADE JOURNAL OVERVIEW" in out
    assert "Tritanium" in out


def test_run_journal_cli_calibration_prints_generic_and_personal_sections() -> None:
    route_results = _sample_route_results()
    nst.attach_plan_metadata(route_results, plan_id="plan_test_calibration_cli", created_at="2026-03-07T12:00:00+00:00")
    manifest = nst.build_trade_plan_manifest(
        route_results,
        plan_id="plan_test_calibration_cli",
        created_at="2026-03-07T12:00:00+00:00",
        runtime_mode="route_profiles",
    )
    entry_id = manifest["routes"][0]["picks"][0]["journal_entry_id"]
    cfg = _minimal_valid_config()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "journal.sqlite3")
        cfg_path = os.path.join(tmpdir, "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        nst.import_trade_plan_into_journal(db_path, manifest)
        nst.record_journal_buy(
            db_path,
            entry_id,
            qty=10,
            price=100.0,
            happened_at="2026-03-01T10:00:00+00:00",
        )
        nst.record_journal_sell(
            db_path,
            entry_id,
            qty=10,
            price=150.0,
            happened_at="2026-03-09T10:00:00+00:00",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            nst.run_journal_cli(["calibration", "--journal-db", db_path, "--config", cfg_path, "--limit", "3"])
        out = buf.getvalue()
    assert "CONFIDENCE CALIBRATION REPORT" in out
    assert "PERSONAL CALIBRATION BASIS" in out
