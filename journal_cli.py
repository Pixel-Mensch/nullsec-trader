from __future__ import annotations

from character_profile import resolve_character_context
from confidence_calibration import build_confidence_calibration, format_confidence_calibration_report
from config_loader import load_config
from journal_models import JOURNAL_ALLOWED_STATUSES
from journal_reporting import (
    format_closed_positions,
    format_journal_overview,
    format_journal_report,
    format_open_positions,
    format_personal_trade_history,
    format_reconciliation_overview,
    format_unmatched_wallet_activity,
)
from journal_store import (
    fetch_closed_journal_entries,
    fetch_journal_entries,
    fetch_journal_entry,
    fetch_open_journal_entries,
    import_trade_plan_into_journal,
    initialize_journal_db,
    load_trade_plan_manifest,
    reconcile_journal_with_character_context,
    record_journal_buy,
    record_journal_sell,
    resolve_journal_db_path,
    update_journal_entry_status,
)
from runtime_common import CONFIG_PATH, die


def _parse_money(raw: str) -> float:
    value = str(raw or "").strip().lower().replace(",", "").replace("_", "")
    if not value:
        raise ValueError("empty")
    factor = 1.0
    if value.endswith("b"):
        factor = 1_000_000_000.0
        value = value[:-1]
    elif value.endswith("m"):
        factor = 1_000_000.0
        value = value[:-1]
    elif value.endswith("k"):
        factor = 1_000.0
        value = value[:-1]
    return float(value) * factor


def _parse_positive_float(raw: str, field_name: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Ungueltiger Wert fuer {field_name}: {raw}") from None
    if value <= 0.0:
        raise ValueError(f"{field_name} muss positiv sein.")
    return value


def _journal_help() -> str:
    statuses = ", ".join(JOURNAL_ALLOWED_STATUSES)
    return "\n".join(
        [
            "Journal-Kommandos:",
            "  python main.py journal import-plan --plan-file .\\trade_plan_x.json [--notes ...] [--journal-db ...]",
            "  python main.py journal buy --entry-id pick_x --qty 10 --price 1200000 [--fees-paid 5m] [--shipping-paid 2m] [--at 2026-03-07T18:00:00+00:00]",
            "  python main.py journal sell --entry-id pick_x --qty 10 --price 1500000 [--fees-paid 5m] [--shipping-paid 0]",
            f"  python main.py journal status --entry-id pick_x --status <{statuses}> [--notes ...]",
            "  python main.py journal overview [--limit 20] [--journal-db ...]",
            "  python main.py journal open [--limit 20] [--journal-db ...]",
            "  python main.py journal closed [--limit 20] [--journal-db ...]",
            "  python main.py journal report [--limit 10] [--journal-db ...]",
            "  python main.py journal reconcile [--config .\\config.json] [--journal-db ...] [--limit 10]",
            "  python main.py journal personal [--config .\\config.json] [--journal-db ...] [--limit 10]",
            "  python main.py journal unmatched [--config .\\config.json] [--journal-db ...] [--limit 20]",
            "  python main.py journal calibration [--journal-db ...] [--config .\\config.json] [--limit 5]",
        ]
    )


def _parse_journal_args(argv: list[str]) -> dict:
    if not argv:
        die(_journal_help())
    args = {
        "action": str(argv[0]).strip().lower(),
        "journal_db": None,
        "plan_file": None,
        "entry_id": None,
        "qty": None,
        "price": None,
        "fees_paid": 0.0,
        "shipping_paid": 0.0,
        "status": None,
        "at": None,
        "notes": "",
        "limit": 20,
        "config_path": CONFIG_PATH,
    }
    i = 1
    while i < len(argv):
        tok = str(argv[i]).strip()
        if tok == "--journal-db":
            if i + 1 >= len(argv):
                die("--journal-db erwartet einen Dateipfad")
            args["journal_db"] = argv[i + 1]
            i += 2
            continue
        if tok == "--plan-file":
            if i + 1 >= len(argv):
                die("--plan-file erwartet einen Dateipfad")
            args["plan_file"] = argv[i + 1]
            i += 2
            continue
        if tok == "--entry-id":
            if i + 1 >= len(argv):
                die("--entry-id erwartet einen Wert")
            args["entry_id"] = argv[i + 1]
            i += 2
            continue
        if tok == "--qty":
            if i + 1 >= len(argv):
                die("--qty erwartet einen Wert")
            args["qty"] = _parse_positive_float(argv[i + 1], "--qty")
            i += 2
            continue
        if tok == "--price":
            if i + 1 >= len(argv):
                die("--price erwartet einen Wert")
            args["price"] = _parse_money(argv[i + 1])
            i += 2
            continue
        if tok == "--fees-paid":
            if i + 1 >= len(argv):
                die("--fees-paid erwartet einen Wert")
            args["fees_paid"] = _parse_money(argv[i + 1])
            i += 2
            continue
        if tok == "--shipping-paid":
            if i + 1 >= len(argv):
                die("--shipping-paid erwartet einen Wert")
            args["shipping_paid"] = _parse_money(argv[i + 1])
            i += 2
            continue
        if tok == "--status":
            if i + 1 >= len(argv):
                die("--status erwartet einen Wert")
            args["status"] = str(argv[i + 1]).strip().lower()
            i += 2
            continue
        if tok == "--at":
            if i + 1 >= len(argv):
                die("--at erwartet einen Zeitstempel")
            args["at"] = argv[i + 1]
            i += 2
            continue
        if tok == "--notes":
            if i + 1 >= len(argv):
                die("--notes erwartet einen Text")
            args["notes"] = str(argv[i + 1])
            i += 2
            continue
        if tok == "--limit":
            if i + 1 >= len(argv):
                die("--limit erwartet einen Wert")
            try:
                args["limit"] = max(1, int(argv[i + 1]))
            except (TypeError, ValueError):
                die(f"Ungueltiger Wert fuer --limit: {argv[i + 1]}")
            i += 2
            continue
        if tok == "--config":
            if i + 1 >= len(argv):
                die("--config erwartet einen Dateipfad")
            args["config_path"] = argv[i + 1]
            i += 2
            continue
        if tok in ("-h", "--help", "help"):
            die(_journal_help())
        die(f"Unbekanntes Journal-Argument: {tok}")
    return args


def _format_entry_update(prefix: str, entry: dict) -> str:
    lines = [
        prefix,
        f"journal_entry_id: {entry.get('journal_entry_id', '')}",
        f"status: {entry.get('status', '')}",
        f"item: {entry.get('item_name', '')} (type_id {int(entry.get('item_type_id', 0) or 0)})",
        f"route: {entry.get('route_label', '')}",
        f"actual_buy_qty: {float(entry.get('actual_buy_qty', 0.0) or 0.0):.2f} @ {float(entry.get('actual_buy_price_avg', 0.0) or 0.0):.2f}",
        f"actual_sell_qty: {float(entry.get('actual_sell_qty', 0.0) or 0.0):.2f} @ {float(entry.get('actual_sell_price_avg', 0.0) or 0.0):.2f}",
        f"actual_profit_net: {float(entry.get('actual_profit_net', 0.0) or 0.0):.2f} ISK",
    ]
    reconciliation_status = str(entry.get("reconciliation_status", "") or "").strip()
    if reconciliation_status:
        lines.extend(
            [
                f"reconciliation_status: {reconciliation_status}",
                f"match_confidence: {float(entry.get('match_confidence', 0.0) or 0.0):.2f}",
                f"realized_profit_net: {float(entry.get('realized_profit_net', 0.0) or 0.0):.2f} ISK",
            ]
        )
    return "\n".join(lines)


def run_journal_cli(argv: list[str]) -> None:
    args = _parse_journal_args(argv)
    action = str(args.get("action", "") or "").strip().lower()
    db_path = resolve_journal_db_path(args.get("journal_db"))
    initialize_journal_db(db_path)

    if action == "import-plan":
        plan_file = str(args.get("plan_file", "") or "").strip()
        if not plan_file:
            die("--plan-file ist fuer import-plan erforderlich")
        manifest = load_trade_plan_manifest(plan_file)
        result = import_trade_plan_into_journal(db_path, manifest, notes=str(args.get("notes", "") or ""))
        print(f"Journal-Datenbank: {result['db_path']}")
        print(f"Plan importiert: {result['plan_id']}")
        print(f"Neue Eintraege: {result['imported']}")
        print(f"Uebersprungen: {result['skipped']}")
        return

    if action == "buy":
        if not args.get("entry_id"):
            die("--entry-id ist fuer buy erforderlich")
        if args.get("qty") is None or args.get("price") is None:
            die("--qty und --price sind fuer buy erforderlich")
        entry = record_journal_buy(
            db_path,
            str(args["entry_id"]),
            float(args["qty"]),
            float(args["price"]),
            fees_paid=float(args.get("fees_paid", 0.0) or 0.0),
            shipping_paid=float(args.get("shipping_paid", 0.0) or 0.0),
            happened_at=str(args.get("at", "") or "") or None,
            notes=str(args.get("notes", "") or ""),
        )
        print(_format_entry_update("Kauf erfasst.", entry))
        return

    if action == "sell":
        if not args.get("entry_id"):
            die("--entry-id ist fuer sell erforderlich")
        if args.get("qty") is None or args.get("price") is None:
            die("--qty und --price sind fuer sell erforderlich")
        entry = record_journal_sell(
            db_path,
            str(args["entry_id"]),
            float(args["qty"]),
            float(args["price"]),
            fees_paid=float(args.get("fees_paid", 0.0) or 0.0),
            shipping_paid=float(args.get("shipping_paid", 0.0) or 0.0),
            happened_at=str(args.get("at", "") or "") or None,
            notes=str(args.get("notes", "") or ""),
        )
        print(_format_entry_update("Verkauf erfasst.", entry))
        return

    if action == "status":
        if not args.get("entry_id"):
            die("--entry-id ist fuer status erforderlich")
        status_value = str(args.get("status", "") or "").strip().lower()
        if status_value not in JOURNAL_ALLOWED_STATUSES:
            die(f"--status muss einer der folgenden Werte sein: {', '.join(JOURNAL_ALLOWED_STATUSES)}")
        entry = update_journal_entry_status(
            db_path,
            str(args["entry_id"]),
            status_value,
            happened_at=str(args.get("at", "") or "") or None,
            notes=str(args.get("notes", "") or ""),
        )
        print(_format_entry_update("Status aktualisiert.", entry))
        return

    if action == "overview":
        entries = fetch_journal_entries(db_path)
        print(format_journal_overview(entries, limit=int(args.get("limit", 20) or 20)))
        return

    if action == "open":
        entries = fetch_open_journal_entries(db_path, limit=int(args.get("limit", 20) or 20))
        print(format_open_positions(entries, limit=int(args.get("limit", 20) or 20)))
        return

    if action == "closed":
        entries = fetch_closed_journal_entries(db_path, limit=int(args.get("limit", 20) or 20))
        print(format_closed_positions(entries, limit=int(args.get("limit", 20) or 20)))
        return

    if action == "report":
        entries = fetch_journal_entries(db_path)
        print(format_journal_report(entries, limit=int(args.get("limit", 10) or 10)))
        return

    if action in {"reconcile", "personal", "unmatched"}:
        cfg = load_config(str(args.get("config_path", CONFIG_PATH) or CONFIG_PATH))
        context = resolve_character_context(cfg, replay_enabled=False, allow_live=True)
        result = reconcile_journal_with_character_context(db_path, context)
        if action == "reconcile":
            print(format_reconciliation_overview(result, limit=int(args.get("limit", 10) or 10)))
            return
        if action == "personal":
            print(format_personal_trade_history(list(result.get("entries", []) or []), limit=int(args.get("limit", 10) or 10)))
            return
        print(format_unmatched_wallet_activity(result, limit=int(args.get("limit", 20) or 20)))
        return

    if action == "calibration":
        entries = fetch_journal_entries(db_path)
        cfg = load_config(str(args.get("config_path", CONFIG_PATH) or CONFIG_PATH))
        calibration = build_confidence_calibration(entries, cfg)
        print(format_confidence_calibration_report(calibration, limit=int(args.get("limit", 5) or 5)))
        return

    if action == "show":
        if not args.get("entry_id"):
            die("--entry-id ist fuer show erforderlich")
        entry = fetch_journal_entry(db_path, str(args["entry_id"]))
        print(_format_entry_update("Journal-Eintrag:", entry))
        return

    die(_journal_help())


__all__ = ["run_journal_cli"]
