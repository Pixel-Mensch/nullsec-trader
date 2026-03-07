from __future__ import annotations

from contextlib import closing
import json
import os
import sqlite3

from journal_reconciliation import reconcile_wallet_snapshot
from journal_models import (
    JOURNAL_ALLOWED_STATUSES,
    JOURNAL_CLOSED_STATUSES,
    JOURNAL_OPEN_STATUSES,
    normalize_journal_timestamp,
    utc_now_iso,
)
from runtime_common import CACHE_DIR


DEFAULT_JOURNAL_DB_PATH = os.path.join(CACHE_DIR, "trade_journal.sqlite3")


JOURNAL_ENTRY_EXTRA_COLUMNS = {
    "source_location_id": "INTEGER NOT NULL DEFAULT 0",
    "target_location_id": "INTEGER NOT NULL DEFAULT 0",
    "character_id": "INTEGER NOT NULL DEFAULT 0",
    "character_open_orders": "INTEGER NOT NULL DEFAULT 0",
    "character_open_buy_orders": "INTEGER NOT NULL DEFAULT 0",
    "character_open_sell_orders": "INTEGER NOT NULL DEFAULT 0",
    "character_open_buy_isk_committed": "REAL NOT NULL DEFAULT 0",
    "character_open_sell_units": "REAL NOT NULL DEFAULT 0",
    "open_order_warning_tier": "TEXT NOT NULL DEFAULT ''",
    "open_order_warning_text": "TEXT NOT NULL DEFAULT ''",
    "proposed_exit_confidence_raw": "REAL NOT NULL DEFAULT 0",
    "proposed_liquidity_confidence_raw": "REAL NOT NULL DEFAULT 0",
    "proposed_transport_confidence_raw": "REAL NOT NULL DEFAULT 1",
    "proposed_overall_confidence_raw": "REAL NOT NULL DEFAULT 0",
    "proposed_exit_confidence_calibrated": "REAL NOT NULL DEFAULT 0",
    "proposed_liquidity_confidence_calibrated": "REAL NOT NULL DEFAULT 0",
    "proposed_transport_confidence_calibrated": "REAL NOT NULL DEFAULT 1",
    "proposed_overall_confidence_calibrated": "REAL NOT NULL DEFAULT 0",
    "calibration_warning": "TEXT NOT NULL DEFAULT ''",
    "matched_wallet_transaction_ids": "TEXT NOT NULL DEFAULT '[]'",
    "matched_wallet_journal_ids": "TEXT NOT NULL DEFAULT '[]'",
    "ambiguous_wallet_transaction_ids": "TEXT NOT NULL DEFAULT '[]'",
    "matched_buy_qty": "REAL NOT NULL DEFAULT 0",
    "matched_sell_qty": "REAL NOT NULL DEFAULT 0",
    "matched_buy_value": "REAL NOT NULL DEFAULT 0",
    "matched_sell_value": "REAL NOT NULL DEFAULT 0",
    "first_matched_buy_at": "TEXT NOT NULL DEFAULT ''",
    "last_matched_sell_at": "TEXT NOT NULL DEFAULT ''",
    "realized_fee_estimate": "REAL NOT NULL DEFAULT 0",
    "realized_profit_net": "REAL NOT NULL DEFAULT 0",
    "reconciliation_status": "TEXT NOT NULL DEFAULT ''",
    "match_confidence": "REAL NOT NULL DEFAULT 0",
    "match_reason": "TEXT NOT NULL DEFAULT ''",
    "fee_match_quality": "TEXT NOT NULL DEFAULT ''",
    "wallet_snapshot_age_sec": "REAL NOT NULL DEFAULT -1",
    "wallet_data_freshness": "TEXT NOT NULL DEFAULT ''",
    "wallet_history_quality": "TEXT NOT NULL DEFAULT ''",
    "wallet_history_truncated": "INTEGER NOT NULL DEFAULT 0",
    "wallet_transactions_pages_loaded": "INTEGER NOT NULL DEFAULT 0",
    "wallet_journal_pages_loaded": "INTEGER NOT NULL DEFAULT 0",
    "reconciliation_basis": "TEXT NOT NULL DEFAULT ''",
    "reconciliation_updated_at": "TEXT NOT NULL DEFAULT ''",
}

JSON_ARRAY_COLUMNS = {
    "matched_wallet_transaction_ids",
    "matched_wallet_journal_ids",
    "ambiguous_wallet_transaction_ids",
}


def resolve_journal_db_path(db_path: str | None = None) -> str:
    raw = str(db_path or DEFAULT_JOURNAL_DB_PATH).strip()
    if not raw:
        raw = DEFAULT_JOURNAL_DB_PATH
    if os.path.isabs(raw):
        return raw
    return os.path.join(os.path.dirname(__file__), raw)


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = resolve_journal_db_path(db_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_journal_entry_columns(conn: sqlite3.Connection) -> None:
    existing = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(journal_entries)").fetchall()
    }
    for column, ddl in JOURNAL_ENTRY_EXTRA_COLUMNS.items():
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE journal_entries ADD COLUMN {column} {ddl}")


def initialize_journal_db(db_path: str | None = None) -> str:
    path = resolve_journal_db_path(db_path)
    with closing(_connect(path)) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS journal_entries (
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
                    source_location_id INTEGER NOT NULL DEFAULT 0,
                    target_location_id INTEGER NOT NULL DEFAULT 0,
                    character_id INTEGER NOT NULL DEFAULT 0,
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
                    proposed_exit_confidence_raw REAL NOT NULL DEFAULT 0,
                    proposed_liquidity_confidence_raw REAL NOT NULL DEFAULT 0,
                    proposed_transport_confidence_raw REAL NOT NULL DEFAULT 1,
                    proposed_overall_confidence_raw REAL NOT NULL DEFAULT 0,
                    proposed_exit_confidence_calibrated REAL NOT NULL DEFAULT 0,
                    proposed_liquidity_confidence_calibrated REAL NOT NULL DEFAULT 0,
                    proposed_transport_confidence_calibrated REAL NOT NULL DEFAULT 1,
                    proposed_overall_confidence_calibrated REAL NOT NULL DEFAULT 0,
                    proposed_expected_units_sold REAL NOT NULL DEFAULT 0,
                    proposed_expected_units_unsold REAL NOT NULL DEFAULT 0,
                    character_open_orders INTEGER NOT NULL DEFAULT 0,
                    character_open_buy_orders INTEGER NOT NULL DEFAULT 0,
                    character_open_sell_orders INTEGER NOT NULL DEFAULT 0,
                    character_open_buy_isk_committed REAL NOT NULL DEFAULT 0,
                    character_open_sell_units REAL NOT NULL DEFAULT 0,
                    open_order_warning_tier TEXT NOT NULL DEFAULT '',
                    open_order_warning_text TEXT NOT NULL DEFAULT '',
                    actual_buy_qty REAL NOT NULL DEFAULT 0,
                    actual_buy_price_avg REAL NOT NULL DEFAULT 0,
                    actual_sell_qty REAL NOT NULL DEFAULT 0,
                    actual_sell_price_avg REAL NOT NULL DEFAULT 0,
                    actual_fees_paid REAL NOT NULL DEFAULT 0,
                    actual_shipping_paid REAL NOT NULL DEFAULT 0,
                    actual_profit_net REAL NOT NULL DEFAULT 0,
                    matched_wallet_transaction_ids TEXT NOT NULL DEFAULT '[]',
                    matched_wallet_journal_ids TEXT NOT NULL DEFAULT '[]',
                    ambiguous_wallet_transaction_ids TEXT NOT NULL DEFAULT '[]',
                    matched_buy_qty REAL NOT NULL DEFAULT 0,
                    matched_sell_qty REAL NOT NULL DEFAULT 0,
                    matched_buy_value REAL NOT NULL DEFAULT 0,
                    matched_sell_value REAL NOT NULL DEFAULT 0,
                    first_matched_buy_at TEXT NOT NULL DEFAULT '',
                    last_matched_sell_at TEXT NOT NULL DEFAULT '',
                    realized_fee_estimate REAL NOT NULL DEFAULT 0,
                    realized_profit_net REAL NOT NULL DEFAULT 0,
                    reconciliation_status TEXT NOT NULL DEFAULT '',
                    match_confidence REAL NOT NULL DEFAULT 0,
                    match_reason TEXT NOT NULL DEFAULT '',
                    fee_match_quality TEXT NOT NULL DEFAULT '',
                    wallet_snapshot_age_sec REAL NOT NULL DEFAULT -1,
                    wallet_data_freshness TEXT NOT NULL DEFAULT '',
                    wallet_history_quality TEXT NOT NULL DEFAULT '',
                    wallet_history_truncated INTEGER NOT NULL DEFAULT 0,
                    wallet_transactions_pages_loaded INTEGER NOT NULL DEFAULT 0,
                    wallet_journal_pages_loaded INTEGER NOT NULL DEFAULT 0,
                    reconciliation_basis TEXT NOT NULL DEFAULT '',
                    reconciliation_updated_at TEXT NOT NULL DEFAULT '',
                    first_buy_at TEXT NOT NULL DEFAULT '',
                    last_sell_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    calibration_warning TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS journal_events (
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
                    notes TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(journal_entry_id) REFERENCES journal_entries(journal_entry_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_journal_entries_status ON journal_entries(status);
                CREATE INDEX IF NOT EXISTS idx_journal_entries_plan_id ON journal_entries(plan_id);
                CREATE INDEX IF NOT EXISTS idx_journal_entries_route_id ON journal_entries(route_id);
                CREATE INDEX IF NOT EXISTS idx_journal_entries_reconciliation_status ON journal_entries(reconciliation_status);
                CREATE INDEX IF NOT EXISTS idx_journal_entries_updated_at ON journal_entries(updated_at);
                CREATE INDEX IF NOT EXISTS idx_journal_events_entry ON journal_events(journal_entry_id, happened_at, event_id);
                """
            )
            _ensure_journal_entry_columns(conn)
    return path


def load_trade_plan_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Plan-Datei ist kein JSON-Objekt.")
    return payload


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = {key: row[key] for key in row.keys()}
    for column in JSON_ARRAY_COLUMNS:
        raw = out.get(column)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = []
            out[column] = list(parsed) if isinstance(parsed, list) else []
    return out


def _json_array_text(value: object) -> str:
    if isinstance(value, list):
        items = value
    elif value is None:
        items = []
    else:
        items = [value]
    return json.dumps(items, ensure_ascii=True, separators=(",", ":"))


def _append_notes(existing: str, notes: str, happened_at: str) -> str:
    old = str(existing or "").strip()
    new = str(notes or "").strip()
    if not new:
        return old
    stamped = f"[{normalize_journal_timestamp(happened_at)}] {new}"
    if not old:
        return stamped
    return f"{old}\n{stamped}"


def _fetch_entry_row(conn: sqlite3.Connection, journal_entry_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM journal_entries WHERE journal_entry_id = ?",
        (str(journal_entry_id),),
    ).fetchone()


def fetch_journal_entry(db_path: str | None, journal_entry_id: str) -> dict:
    initialize_journal_db(db_path)
    with closing(_connect(db_path)) as conn:
        row = _fetch_entry_row(conn, journal_entry_id)
        if row is None:
            raise KeyError(f"Journal-Eintrag nicht gefunden: {journal_entry_id}")
        out = _row_to_dict(row)
    return out or {}


def fetch_journal_entries(db_path: str | None, statuses: list[str] | None = None, limit: int | None = None) -> list[dict]:
    initialize_journal_db(db_path)
    status_list = [str(s).strip() for s in list(statuses or []) if str(s).strip()]
    sql = "SELECT * FROM journal_entries"
    params: list[object] = []
    if status_list:
        placeholders = ",".join("?" for _ in status_list)
        sql += f" WHERE status IN ({placeholders})"
        params.extend(status_list)
    sql += " ORDER BY updated_at DESC, created_at DESC, journal_entry_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def fetch_open_journal_entries(db_path: str | None, limit: int | None = None) -> list[dict]:
    return fetch_journal_entries(db_path, statuses=list(JOURNAL_OPEN_STATUSES), limit=limit)


def fetch_closed_journal_entries(db_path: str | None, limit: int | None = None) -> list[dict]:
    return fetch_journal_entries(db_path, statuses=list(JOURNAL_CLOSED_STATUSES), limit=limit)


def _auto_status(current_status: str, actual_buy_qty: float, actual_sell_qty: float) -> str:
    status_now = str(current_status or "").strip().lower()
    if status_now in ("abandoned", "invalidated"):
        return status_now
    if float(actual_buy_qty) <= 0.0 and float(actual_sell_qty) <= 0.0:
        return "planned"
    if float(actual_buy_qty) <= 0.0 and float(actual_sell_qty) > 0.0:
        return "sold"
    if float(actual_sell_qty) <= 0.0:
        return "bought"
    if float(actual_sell_qty) + 1e-9 < float(actual_buy_qty):
        return "partially_sold"
    return "sold"


def _recompute_entry(conn: sqlite3.Connection, journal_entry_id: str) -> dict:
    row = _fetch_entry_row(conn, journal_entry_id)
    if row is None:
        raise KeyError(f"Journal-Eintrag nicht gefunden: {journal_entry_id}")
    events = conn.execute(
        "SELECT * FROM journal_events WHERE journal_entry_id = ? ORDER BY happened_at ASC, event_id ASC",
        (str(journal_entry_id),),
    ).fetchall()

    buy_qty = 0.0
    buy_gross = 0.0
    sell_qty = 0.0
    sell_gross = 0.0
    fees_paid = 0.0
    shipping_paid = 0.0
    first_buy_at = ""
    last_sell_at = ""

    for event in events:
        event_type = str(event["event_type"] or "").strip().lower()
        qty = float(event["qty"] or 0.0)
        price = float(event["price"] or 0.0)
        happened_at = str(event["happened_at"] or "")
        fees_paid += float(event["fees_paid"] or 0.0)
        shipping_paid += float(event["shipping_paid"] or 0.0)
        if event_type == "buy":
            buy_qty += qty
            buy_gross += qty * price
            if happened_at and (not first_buy_at or happened_at < first_buy_at):
                first_buy_at = happened_at
        elif event_type == "sell":
            sell_qty += qty
            sell_gross += qty * price
            if happened_at and (not last_sell_at or happened_at > last_sell_at):
                last_sell_at = happened_at

    actual_buy_price_avg = (buy_gross / buy_qty) if buy_qty > 1e-12 else 0.0
    actual_sell_price_avg = (sell_gross / sell_qty) if sell_qty > 1e-12 else 0.0
    actual_profit_net = sell_gross - buy_gross - fees_paid - shipping_paid
    next_status = _auto_status(str(row["status"] or ""), buy_qty, sell_qty)
    updated_at = utc_now_iso()

    conn.execute(
        """
        UPDATE journal_entries
        SET actual_buy_qty = ?,
            actual_buy_price_avg = ?,
            actual_sell_qty = ?,
            actual_sell_price_avg = ?,
            actual_fees_paid = ?,
            actual_shipping_paid = ?,
            actual_profit_net = ?,
            first_buy_at = ?,
            last_sell_at = ?,
            status = ?,
            updated_at = ?
        WHERE journal_entry_id = ?
        """,
        (
            float(buy_qty),
            float(actual_buy_price_avg),
            float(sell_qty),
            float(actual_sell_price_avg),
            float(fees_paid),
            float(shipping_paid),
            float(actual_profit_net),
            str(first_buy_at),
            str(last_sell_at),
            str(next_status),
            str(updated_at),
            str(journal_entry_id),
        ),
    )
    refreshed = _fetch_entry_row(conn, journal_entry_id)
    return _row_to_dict(refreshed) or {}


def import_trade_plan_into_journal(db_path: str | None, plan_manifest: dict, notes: str = "") -> dict:
    path = initialize_journal_db(db_path)
    if not isinstance(plan_manifest, dict):
        raise ValueError("Plan-Manifest fehlt oder ist ungueltig.")
    plan_id = str(plan_manifest.get("plan_id", plan_manifest.get("source_run_id", "")) or "").strip()
    if not plan_id:
        raise ValueError("Plan-Manifest enthaelt keine plan_id.")
    created_at = normalize_journal_timestamp(str(plan_manifest.get("created_at", "") or ""))
    imported = 0
    skipped = 0
    with closing(_connect(path)) as conn:
        with conn:
            for route in list(plan_manifest.get("routes", []) or []):
                if not isinstance(route, dict):
                    continue
                route_id = str(route.get("route_id", "") or "").strip()
                route_profile = str(route.get("route_profile", route_id) or route_id)
                route_label = str(route.get("route_label", "") or "")
                source_market = str(route.get("source_market", "") or "")
                target_market = str(route.get("target_market", "") or "")
                for pick in list(route.get("picks", []) or []):
                    if not isinstance(pick, dict):
                        continue
                    journal_entry_id = str(pick.get("journal_entry_id", pick.get("pick_id", "")) or "").strip()
                    if not journal_entry_id:
                        continue
                    if _fetch_entry_row(conn, journal_entry_id) is not None:
                        skipped += 1
                        continue
                    entry_notes = _append_notes("", notes, created_at)
                    conn.execute(
                        """
                        INSERT INTO journal_entries (
                            journal_entry_id,
                            pick_id,
                            created_at,
                            updated_at,
                            plan_id,
                            source_run_id,
                            route_id,
                            route_profile,
                            route_label,
                            source_market,
                            target_market,
                            source_location_id,
                            target_location_id,
                            character_id,
                            item_type_id,
                            item_name,
                            proposed_qty,
                            proposed_buy_price,
                            proposed_sell_price,
                            proposed_full_sell_profit,
                            proposed_expected_profit,
                            proposed_expected_days_to_sell,
                            proposed_exit_type,
                            proposed_confidence,
                            proposed_exit_confidence_raw,
                            proposed_liquidity_confidence_raw,
                            proposed_transport_confidence_raw,
                            proposed_overall_confidence_raw,
                            proposed_exit_confidence_calibrated,
                            proposed_liquidity_confidence_calibrated,
                            proposed_transport_confidence_calibrated,
                            proposed_overall_confidence_calibrated,
                            proposed_expected_units_sold,
                            proposed_expected_units_unsold,
                            character_open_orders,
                            character_open_buy_orders,
                            character_open_sell_orders,
                            character_open_buy_isk_committed,
                            character_open_sell_units,
                            open_order_warning_tier,
                            open_order_warning_text,
                            status,
                            calibration_warning,
                            notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            journal_entry_id,
                            str(pick.get("pick_id", journal_entry_id) or journal_entry_id),
                            created_at,
                            created_at,
                            plan_id,
                            str(plan_manifest.get("source_run_id", plan_id) or plan_id),
                            route_id,
                            route_profile,
                            route_label,
                            str(pick.get("source_market", source_market) or source_market),
                            str(pick.get("target_market", target_market) or target_market),
                            int(pick.get("source_location_id", 0) or 0),
                            int(pick.get("target_location_id", 0) or 0),
                            int(pick.get("character_id", 0) or 0),
                            int(pick.get("item_type_id", 0) or 0),
                            str(pick.get("item_name", "") or ""),
                            float(pick.get("proposed_qty", 0.0) or 0.0),
                            float(pick.get("proposed_buy_price", 0.0) or 0.0),
                            float(pick.get("proposed_sell_price", 0.0) or 0.0),
                            float(pick.get("proposed_full_sell_profit", 0.0) or 0.0),
                            float(pick.get("proposed_expected_profit", 0.0) or 0.0),
                            float(pick.get("proposed_expected_days_to_sell", 0.0) or 0.0),
                            str(pick.get("proposed_exit_type", "instant") or "instant"),
                            float(pick.get("proposed_confidence", 0.0) or 0.0),
                            float(pick.get("proposed_exit_confidence_raw", 0.0) or 0.0),
                            float(pick.get("proposed_liquidity_confidence_raw", 0.0) or 0.0),
                            float(pick.get("proposed_transport_confidence_raw", 1.0) or 1.0),
                            float(pick.get("proposed_overall_confidence_raw", pick.get("proposed_confidence", 0.0)) or 0.0),
                            float(pick.get("proposed_exit_confidence_calibrated", pick.get("proposed_exit_confidence_raw", 0.0)) or 0.0),
                            float(pick.get("proposed_liquidity_confidence_calibrated", pick.get("proposed_liquidity_confidence_raw", 0.0)) or 0.0),
                            float(pick.get("proposed_transport_confidence_calibrated", pick.get("proposed_transport_confidence_raw", 1.0)) or 1.0),
                            float(pick.get("proposed_overall_confidence_calibrated", pick.get("proposed_overall_confidence_raw", pick.get("proposed_confidence", 0.0))) or 0.0),
                            float(pick.get("proposed_expected_units_sold", 0.0) or 0.0),
                            float(pick.get("proposed_expected_units_unsold", 0.0) or 0.0),
                            int(pick.get("character_open_orders", 0) or 0),
                            int(pick.get("character_open_buy_orders", 0) or 0),
                            int(pick.get("character_open_sell_orders", 0) or 0),
                            float(pick.get("character_open_buy_isk_committed", 0.0) or 0.0),
                            float(pick.get("character_open_sell_units", 0.0) or 0.0),
                            str(pick.get("open_order_warning_tier", "") or ""),
                            str(pick.get("open_order_warning_text", "") or ""),
                            "planned",
                            str(pick.get("calibration_warning", "") or ""),
                            entry_notes,
                        ),
                    )
                    imported += 1
    return {
        "db_path": path,
        "plan_id": plan_id,
        "imported": int(imported),
        "skipped": int(skipped),
    }


def _record_event(
    db_path: str | None,
    journal_entry_id: str,
    event_type: str,
    *,
    qty: float = 0.0,
    price: float = 0.0,
    fees_paid: float = 0.0,
    shipping_paid: float = 0.0,
    happened_at: str | None = None,
    notes: str = "",
    status_to: str = "",
) -> dict:
    path = initialize_journal_db(db_path)
    timestamp = normalize_journal_timestamp(happened_at)
    created_at = utc_now_iso()
    event_kind = str(event_type or "").strip().lower()
    if event_kind not in ("buy", "sell", "status"):
        raise ValueError(f"Ungueltiger Journal-Event-Typ: {event_type}")
    if event_kind in ("buy", "sell"):
        if float(qty) <= 0.0:
            raise ValueError("qty muss positiv sein.")
        if float(price) < 0.0:
            raise ValueError("price darf nicht negativ sein.")
    if event_kind == "status":
        target_status = str(status_to or "").strip().lower()
        if target_status not in JOURNAL_ALLOWED_STATUSES:
            raise ValueError(f"Ungueltiger Journal-Status: {status_to}")
    with closing(_connect(path)) as conn:
        with conn:
            row = _fetch_entry_row(conn, journal_entry_id)
            if row is None:
                raise KeyError(f"Journal-Eintrag nicht gefunden: {journal_entry_id}")
            current_status = str(row["status"] or "").strip().lower()
            if current_status in ("abandoned", "invalidated") and event_kind in ("buy", "sell"):
                raise ValueError(f"Journal-Eintrag {journal_entry_id} ist bereits {current_status}.")
            conn.execute(
                """
                INSERT INTO journal_events (
                    journal_entry_id,
                    created_at,
                    event_type,
                    qty,
                    price,
                    fees_paid,
                    shipping_paid,
                    happened_at,
                    status_to,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(journal_entry_id),
                    created_at,
                    event_kind,
                    float(qty),
                    float(price),
                    float(fees_paid),
                    float(shipping_paid),
                    timestamp,
                    str(status_to or ""),
                    str(notes or ""),
                ),
            )
            if notes:
                next_notes = _append_notes(str(row["notes"] or ""), notes, timestamp)
                conn.execute(
                    "UPDATE journal_entries SET notes = ?, updated_at = ? WHERE journal_entry_id = ?",
                    (next_notes, created_at, str(journal_entry_id)),
                )
            if event_kind == "status":
                conn.execute(
                    "UPDATE journal_entries SET status = ?, updated_at = ? WHERE journal_entry_id = ?",
                    (target_status, created_at, str(journal_entry_id)),
                )
                refreshed = _fetch_entry_row(conn, journal_entry_id)
                return _row_to_dict(refreshed) or {}
            return _recompute_entry(conn, journal_entry_id)


def record_journal_buy(
    db_path: str | None,
    journal_entry_id: str,
    qty: float,
    price: float,
    *,
    fees_paid: float = 0.0,
    shipping_paid: float = 0.0,
    happened_at: str | None = None,
    notes: str = "",
) -> dict:
    return _record_event(
        db_path,
        journal_entry_id,
        "buy",
        qty=float(qty),
        price=float(price),
        fees_paid=float(fees_paid),
        shipping_paid=float(shipping_paid),
        happened_at=happened_at,
        notes=notes,
    )


def record_journal_sell(
    db_path: str | None,
    journal_entry_id: str,
    qty: float,
    price: float,
    *,
    fees_paid: float = 0.0,
    shipping_paid: float = 0.0,
    happened_at: str | None = None,
    notes: str = "",
) -> dict:
    return _record_event(
        db_path,
        journal_entry_id,
        "sell",
        qty=float(qty),
        price=float(price),
        fees_paid=float(fees_paid),
        shipping_paid=float(shipping_paid),
        happened_at=happened_at,
        notes=notes,
    )


def update_journal_entry_status(
    db_path: str | None,
    journal_entry_id: str,
    status: str,
    *,
    happened_at: str | None = None,
    notes: str = "",
) -> dict:
    target_status = str(status or "").strip().lower()
    if target_status not in JOURNAL_ALLOWED_STATUSES:
        raise ValueError(f"Ungueltiger Journal-Status: {status}")
    return _record_event(
        db_path,
        journal_entry_id,
        "status",
        happened_at=happened_at,
        notes=notes or f"Status gesetzt auf {target_status}",
        status_to=target_status,
    )


def fetch_journal_events(db_path: str | None, journal_entry_id: str | None = None) -> list[dict]:
    initialize_journal_db(db_path)
    sql = "SELECT * FROM journal_events"
    params: list[object] = []
    if journal_entry_id:
        sql += " WHERE journal_entry_id = ?"
        params.append(str(journal_entry_id))
    sql += " ORDER BY happened_at ASC, event_id ASC"
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def reconcile_journal_with_wallet(
    db_path: str | None,
    wallet_snapshot: dict | None,
    *,
    character_id: int = 0,
    context_source: str = "wallet",
) -> dict:
    path = initialize_journal_db(db_path)
    entries = fetch_journal_entries(path)
    result = reconcile_wallet_snapshot(
        entries,
        wallet_snapshot,
        character_id=character_id,
        context_source=context_source,
    )
    result["db_path"] = path
    if not bool(result.get("wallet_available", False)):
        result["persisted"] = False
        return result

    updated_at = utc_now_iso()
    with closing(_connect(path)) as conn:
        with conn:
            for entry in list(result.get("entries", []) or []):
                conn.execute(
                    """
                    UPDATE journal_entries
                    SET matched_wallet_transaction_ids = ?,
                        matched_wallet_journal_ids = ?,
                        ambiguous_wallet_transaction_ids = ?,
                        matched_buy_qty = ?,
                        matched_sell_qty = ?,
                        matched_buy_value = ?,
                        matched_sell_value = ?,
                        first_matched_buy_at = ?,
                        last_matched_sell_at = ?,
                        realized_fee_estimate = ?,
                        realized_profit_net = ?,
                        reconciliation_status = ?,
                        match_confidence = ?,
                        match_reason = ?,
                        fee_match_quality = ?,
                        wallet_snapshot_age_sec = ?,
                        wallet_data_freshness = ?,
                        wallet_history_quality = ?,
                        wallet_history_truncated = ?,
                        wallet_transactions_pages_loaded = ?,
                        wallet_journal_pages_loaded = ?,
                        reconciliation_basis = ?,
                        open_order_warning_tier = ?,
                        open_order_warning_text = ?,
                        reconciliation_updated_at = ?,
                        updated_at = ?
                    WHERE journal_entry_id = ?
                    """,
                    (
                        _json_array_text(entry.get("matched_wallet_transaction_ids", [])),
                        _json_array_text(entry.get("matched_wallet_journal_ids", [])),
                        _json_array_text(entry.get("ambiguous_wallet_transaction_ids", [])),
                        float(entry.get("matched_buy_qty", 0.0) or 0.0),
                        float(entry.get("matched_sell_qty", 0.0) or 0.0),
                        float(entry.get("matched_buy_value", 0.0) or 0.0),
                        float(entry.get("matched_sell_value", 0.0) or 0.0),
                        str(entry.get("first_matched_buy_at", "") or ""),
                        str(entry.get("last_matched_sell_at", "") or ""),
                        float(entry.get("realized_fee_estimate", 0.0) or 0.0),
                        float(entry.get("realized_profit_net", 0.0) or 0.0),
                        str(entry.get("reconciliation_status", "") or ""),
                        float(entry.get("match_confidence", 0.0) or 0.0),
                        str(entry.get("match_reason", "") or ""),
                        str(entry.get("fee_match_quality", "") or ""),
                        float(entry.get("wallet_snapshot_age_sec", -1.0) or -1.0),
                        str(entry.get("wallet_data_freshness", "") or ""),
                        str(entry.get("wallet_history_quality", "") or ""),
                        1 if bool(entry.get("wallet_history_truncated", False)) else 0,
                        int(entry.get("wallet_transactions_pages_loaded", 0) or 0),
                        int(entry.get("wallet_journal_pages_loaded", 0) or 0),
                        str(entry.get("reconciliation_basis", "") or ""),
                        str(entry.get("open_order_warning_tier", "") or ""),
                        str(entry.get("open_order_warning_text", "") or ""),
                        updated_at,
                        updated_at,
                        str(entry.get("journal_entry_id", "") or ""),
                    ),
                )
    result["persisted"] = True
    result["reconciliation_updated_at"] = updated_at
    result["entries"] = fetch_journal_entries(path)
    return result


def reconcile_journal_with_character_context(db_path: str | None, context: dict | None) -> dict:
    ctx = dict(context or {}) if isinstance(context, dict) else {}
    profile = ctx.get("profile", {}) if isinstance(ctx.get("profile", {}), dict) else {}
    wallet_snapshot = profile.get("wallet_snapshot", {}) if isinstance(profile.get("wallet_snapshot", {}), dict) else {}
    result = reconcile_journal_with_wallet(
        db_path,
        wallet_snapshot,
        character_id=int(ctx.get("character_id", profile.get("character_id", 0)) or 0),
        context_source=str(ctx.get("source", "default") or "default"),
    )
    result["context_source"] = str(ctx.get("source", "default") or "default")
    result["context_available"] = bool(ctx.get("available", False))
    result["context_warnings"] = list(ctx.get("warnings", []) or [])
    return result


__all__ = [
    "DEFAULT_JOURNAL_DB_PATH",
    "fetch_closed_journal_entries",
    "fetch_journal_entries",
    "fetch_journal_entry",
    "fetch_journal_events",
    "fetch_open_journal_entries",
    "import_trade_plan_into_journal",
    "initialize_journal_db",
    "load_trade_plan_manifest",
    "reconcile_journal_with_character_context",
    "reconcile_journal_with_wallet",
    "record_journal_buy",
    "record_journal_sell",
    "resolve_journal_db_path",
    "update_journal_entry_status",
]
