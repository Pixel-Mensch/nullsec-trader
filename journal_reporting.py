from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from journal_models import (
    JOURNAL_CLOSED_STATUSES,
    JOURNAL_OPEN_STATUSES,
    compute_actual_days_to_sell,
    compute_realized_outcome_score,
    entry_profit_delta,
)
from runtime_reports import fmt_isk


def _parse_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt_days(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}d"


def enrich_journal_entry(entry: dict, now: datetime | None = None) -> dict:
    current_now = now or datetime.now(timezone.utc)
    enriched = dict(entry or {})
    proposed_qty = _as_float(enriched.get("proposed_qty", 0.0))
    actual_buy_qty = _as_float(enriched.get("actual_buy_qty", 0.0))
    actual_sell_qty = _as_float(enriched.get("actual_sell_qty", 0.0))
    proposed_expected_profit = _as_float(enriched.get("proposed_expected_profit", 0.0))
    proposed_expected_days = _as_float(enriched.get("proposed_expected_days_to_sell", 0.0))
    actual_profit = _as_float(enriched.get("actual_profit_net", 0.0))
    actual_days = compute_actual_days_to_sell(enriched)
    proposed_confidence = _as_float(
        enriched.get("proposed_overall_confidence_raw", enriched.get("proposed_confidence", 0.0))
    )
    outcome_score = compute_realized_outcome_score(enriched)
    enriched["comparison_profit_delta"] = entry_profit_delta(enriched)
    enriched["comparison_profit_ratio"] = (
        (actual_profit / proposed_expected_profit) if proposed_expected_profit > 1e-9 else 0.0
    )
    enriched["comparison_qty_delta"] = actual_sell_qty - proposed_qty
    enriched["comparison_qty_ratio"] = (actual_sell_qty / proposed_qty) if proposed_qty > 1e-9 else 0.0
    enriched["actual_days_to_sell"] = actual_days
    enriched["comparison_days_delta"] = (
        (actual_days - proposed_expected_days) if actual_days is not None and proposed_expected_days > 0.0 else None
    )
    enriched["realized_outcome_score"] = outcome_score
    enriched["confidence_gap"] = outcome_score - proposed_confidence
    first_buy = _parse_dt(str(enriched.get("first_buy_at", "") or ""))
    if first_buy is None:
        first_buy = _parse_dt(str(enriched.get("created_at", "") or ""))
    if first_buy is not None and str(enriched.get("status", "") or "").strip().lower() in JOURNAL_OPEN_STATUSES:
        enriched["open_days"] = max(0.0, (current_now - first_buy).total_seconds() / 86400.0)
    else:
        enriched["open_days"] = 0.0
    enriched["actual_inventory_open_qty"] = max(0.0, actual_buy_qty - actual_sell_qty)
    return enriched


def summarize_journal(entries: list[dict], now: datetime | None = None) -> dict:
    enriched = [enrich_journal_entry(e, now=now) for e in list(entries or [])]
    sold_entries = [e for e in enriched if str(e.get("status", "")).strip().lower() == "sold"]
    open_entries = [e for e in enriched if str(e.get("status", "")).strip().lower() in JOURNAL_OPEN_STATUSES]
    closed_entries = [e for e in enriched if str(e.get("status", "")).strip().lower() in JOURNAL_CLOSED_STATUSES]
    return {
        "entries_total": len(enriched),
        "planned_count": sum(1 for e in enriched if str(e.get("status", "")).strip().lower() == "planned"),
        "bought_count": sum(1 for e in enriched if str(e.get("status", "")).strip().lower() == "bought"),
        "partial_count": sum(1 for e in enriched if str(e.get("status", "")).strip().lower() == "partially_sold"),
        "sold_count": sum(1 for e in sold_entries),
        "abandoned_count": sum(1 for e in enriched if str(e.get("status", "")).strip().lower() == "abandoned"),
        "invalidated_count": sum(1 for e in enriched if str(e.get("status", "")).strip().lower() == "invalidated"),
        "open_count": len(open_entries),
        "closed_count": len(closed_entries),
        "total_proposed_expected_profit": sum(_as_float(e.get("proposed_expected_profit", 0.0)) for e in enriched),
        "total_real_profit_closed": sum(_as_float(e.get("actual_profit_net", 0.0)) for e in sold_entries),
        "total_real_profit_all": sum(_as_float(e.get("actual_profit_net", 0.0)) for e in enriched),
        "avg_profit_delta_sold": (
            sum(_as_float(e.get("comparison_profit_delta", 0.0)) for e in sold_entries) / len(sold_entries)
            if sold_entries
            else 0.0
        ),
        "avg_confidence_gap_sold": (
            sum(_as_float(e.get("confidence_gap", 0.0)) for e in sold_entries) / len(sold_entries) if sold_entries else 0.0
        ),
    }


def _group_performance(entries: list[dict], key_name: str) -> list[dict]:
    groups: dict[str, dict] = defaultdict(
        lambda: {
            "key": "",
            "count": 0,
            "sold_count": 0,
            "total_expected_profit": 0.0,
            "total_real_profit": 0.0,
            "avg_profit_delta": 0.0,
        }
    )
    for entry in list(entries or []):
        key = str(entry.get(key_name, "") or "(leer)")
        group = groups[key]
        group["key"] = key
        group["count"] += 1
        group["total_expected_profit"] += _as_float(entry.get("proposed_expected_profit", 0.0))
        if str(entry.get("status", "")).strip().lower() == "sold":
            group["sold_count"] += 1
            group["total_real_profit"] += _as_float(entry.get("actual_profit_net", 0.0))
            group["avg_profit_delta"] += _as_float(entry.get("comparison_profit_delta", 0.0))
    out = []
    for group in groups.values():
        sold_count = max(1, int(group["sold_count"]))
        group["avg_profit_delta"] = float(group["avg_profit_delta"]) / float(sold_count) if int(group["sold_count"]) > 0 else 0.0
        out.append(group)
    out.sort(key=lambda item: (float(item["total_real_profit"]), float(item["total_expected_profit"])), reverse=True)
    return out


def build_journal_report(entries: list[dict], limit: int = 10, now: datetime | None = None) -> dict:
    enriched = [enrich_journal_entry(entry, now=now) for entry in list(entries or [])]
    sold_entries = [e for e in enriched if str(e.get("status", "")).strip().lower() == "sold"]
    open_positions = [
        e
        for e in enriched
        if str(e.get("status", "")).strip().lower() in ("bought", "partially_sold") and _as_float(e.get("actual_buy_qty", 0.0)) > 0.0
    ]
    overestimated = sorted(
        [entry for entry in sold_entries if _as_float(entry.get("comparison_profit_delta", 0.0)) < 0.0],
        key=lambda entry: _as_float(entry.get("comparison_profit_delta", 0.0)),
    )[: max(1, int(limit))]
    underestimated = sorted(
        [entry for entry in sold_entries if _as_float(entry.get("comparison_profit_delta", 0.0)) > 0.0],
        key=lambda entry: _as_float(entry.get("comparison_profit_delta", 0.0)),
        reverse=True,
    )[: max(1, int(limit))]
    open_corpses = sorted(
        open_positions,
        key=lambda entry: (
            _as_float(entry.get("open_days", 0.0)) - _as_float(entry.get("proposed_expected_days_to_sell", 0.0)),
            _as_float(entry.get("open_days", 0.0)),
        ),
        reverse=True,
    )[: max(1, int(limit))]
    return {
        "summary": summarize_journal(enriched, now=now),
        "entries": enriched,
        "sold_entries": sold_entries,
        "per_route": _group_performance(enriched, "route_label"),
        "per_source_market": _group_performance(enriched, "source_market"),
        "per_target_market": _group_performance(enriched, "target_market"),
        "per_exit_type": _group_performance(enriched, "proposed_exit_type"),
        "overestimated": overestimated,
        "underestimated": underestimated,
        "open_corpses": open_corpses,
    }


def _format_entry_line(entry: dict) -> str:
    item_name = str(entry.get("item_name", "") or "")
    route_label = str(entry.get("route_label", "") or "")
    status = str(entry.get("status", "") or "")
    entry_id = str(entry.get("journal_entry_id", "") or "")
    expected = fmt_isk(_as_float(entry.get("proposed_expected_profit", 0.0)))
    actual = fmt_isk(_as_float(entry.get("actual_profit_net", 0.0)))
    return f"- {entry_id} | {status} | {item_name} | {route_label} | exp={expected} | real={actual}"


def format_journal_overview(entries: list[dict], limit: int = 20, now: datetime | None = None) -> str:
    report = build_journal_report(entries, limit=max(5, int(limit)), now=now)
    summary = report["summary"]
    lines = [
        "=" * 70,
        "TRADE JOURNAL OVERVIEW",
        "=" * 70,
        (
            f"Eintraege: {summary['entries_total']} | offen: {summary['open_count']} | "
            f"sold: {summary['sold_count']} | abandoned: {summary['abandoned_count']} | invalidated: {summary['invalidated_count']}"
        ),
        (
            f"Expected gesamt: {fmt_isk(summary['total_proposed_expected_profit'])} | "
            f"Realisiert (sold): {fmt_isk(summary['total_real_profit_closed'])}"
        ),
        f"Avg Profit Delta (sold): {fmt_isk(summary['avg_profit_delta_sold'])}",
        f"Avg Confidence Gap (sold): {summary['avg_confidence_gap_sold']:+.2f}",
        "",
        "Letzte Eintraege:",
    ]
    for entry in report["entries"][: max(1, int(limit))]:
        lines.append(_format_entry_line(entry))
    if len(report["entries"]) == 0:
        lines.append("- Keine Journal-Eintraege vorhanden.")
    return "\n".join(lines)


def format_open_positions(entries: list[dict], limit: int = 20, now: datetime | None = None) -> str:
    enriched = [enrich_journal_entry(entry, now=now) for entry in list(entries or [])]
    open_entries = [entry for entry in enriched if str(entry.get("status", "")).strip().lower() in JOURNAL_OPEN_STATUSES]
    lines = ["=" * 70, "OFFENE POSITIONEN", "=" * 70]
    if not open_entries:
        lines.append("Keine offenen Positionen.")
        return "\n".join(lines)
    for entry in open_entries[: max(1, int(limit))]:
        lines.append(
            (
                f"- {entry.get('journal_entry_id', '')} | {entry.get('status', '')} | {entry.get('item_name', '')} | "
                f"open_qty={entry.get('actual_inventory_open_qty', 0.0):.2f} | open_days={_fmt_days(entry.get('open_days'))} | "
                f"exp_days={_fmt_days(_as_float(entry.get('proposed_expected_days_to_sell', 0.0)))} | route={entry.get('route_label', '')}"
            )
        )
    return "\n".join(lines)


def format_closed_positions(entries: list[dict], limit: int = 20, now: datetime | None = None) -> str:
    enriched = [enrich_journal_entry(entry, now=now) for entry in list(entries or [])]
    closed_entries = [entry for entry in enriched if str(entry.get("status", "")).strip().lower() in JOURNAL_CLOSED_STATUSES]
    lines = ["=" * 70, "ABGESCHLOSSENE POSITIONEN", "=" * 70]
    if not closed_entries:
        lines.append("Keine abgeschlossenen Positionen.")
        return "\n".join(lines)
    for entry in closed_entries[: max(1, int(limit))]:
        lines.append(
            (
                f"- {entry.get('journal_entry_id', '')} | {entry.get('status', '')} | {entry.get('item_name', '')} | "
                f"expected={fmt_isk(_as_float(entry.get('proposed_expected_profit', 0.0)))} | "
                f"real={fmt_isk(_as_float(entry.get('actual_profit_net', 0.0)))} | "
                f"delta={fmt_isk(_as_float(entry.get('comparison_profit_delta', 0.0)))} | "
                f"sell_days={_fmt_days(entry.get('actual_days_to_sell'))}"
            )
        )
    return "\n".join(lines)


def format_journal_report(entries: list[dict], limit: int = 10, now: datetime | None = None) -> str:
    report = build_journal_report(entries, limit=limit, now=now)
    summary = report["summary"]
    lines = [
        "=" * 70,
        "TRADE JOURNAL REPORT",
        "=" * 70,
        (
            f"Entries={summary['entries_total']} | Open={summary['open_count']} | Sold={summary['sold_count']} | "
            f"Abandoned={summary['abandoned_count']} | Invalidated={summary['invalidated_count']}"
        ),
        f"Expected gesamt: {fmt_isk(summary['total_proposed_expected_profit'])}",
        f"Realisiert (sold): {fmt_isk(summary['total_real_profit_closed'])}",
        f"Avg Profit Delta (sold): {fmt_isk(summary['avg_profit_delta_sold'])}",
        "",
        "Performance nach Route:",
    ]
    for row in report["per_route"][: max(1, int(limit))]:
        lines.append(
            f"- {row['key']} | sold={row['sold_count']} | expected={fmt_isk(row['total_expected_profit'])} | real={fmt_isk(row['total_real_profit'])}"
        )
    lines.append("")
    lines.append("Performance nach Kaufmarkt:")
    for row in report["per_source_market"][: max(1, int(limit))]:
        lines.append(
            f"- {row['key']} | sold={row['sold_count']} | real={fmt_isk(row['total_real_profit'])}"
        )
    lines.append("")
    lines.append("Performance nach Zielmarkt:")
    for row in report["per_target_market"][: max(1, int(limit))]:
        lines.append(
            f"- {row['key']} | sold={row['sold_count']} | real={fmt_isk(row['total_real_profit'])}"
        )
    lines.append("")
    lines.append("Performance nach Exit-Typ:")
    for row in report["per_exit_type"][: max(1, int(limit))]:
        lines.append(
            f"- {row['key']} | sold={row['sold_count']} | real={fmt_isk(row['total_real_profit'])}"
        )
    lines.append("")
    lines.append("Meist ueberschaetzt:")
    if report["overestimated"]:
        for entry in report["overestimated"]:
            lines.append(
                f"- {entry.get('item_name', '')} | delta={fmt_isk(_as_float(entry.get('comparison_profit_delta', 0.0)))} | route={entry.get('route_label', '')}"
            )
    else:
        lines.append("- Keine abgeschlossenen Trades.")
    lines.append("")
    lines.append("Meist unterschaetzt:")
    if report["underestimated"]:
        for entry in report["underestimated"]:
            lines.append(
                f"- {entry.get('item_name', '')} | delta={fmt_isk(_as_float(entry.get('comparison_profit_delta', 0.0)))} | route={entry.get('route_label', '')}"
            )
    else:
        lines.append("- Keine abgeschlossenen Trades.")
    lines.append("")
    lines.append("Offene Leichen / Langdreher:")
    if report["open_corpses"]:
        for entry in report["open_corpses"]:
            lines.append(
                (
                    f"- {entry.get('item_name', '')} | open_days={_fmt_days(entry.get('open_days'))} | "
                    f"exp_days={_fmt_days(_as_float(entry.get('proposed_expected_days_to_sell', 0.0)))} | "
                    f"open_qty={entry.get('actual_inventory_open_qty', 0.0):.2f}"
                )
            )
    else:
        lines.append("- Keine offenen Leichen gefunden.")
    return "\n".join(lines)


__all__ = [
    "build_journal_report",
    "enrich_journal_entry",
    "format_closed_positions",
    "format_journal_overview",
    "format_journal_report",
    "format_open_positions",
    "summarize_journal",
]
