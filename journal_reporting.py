from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from journal_models import (
    JOURNAL_CLOSED_STATUSES,
    JOURNAL_OPEN_STATUSES,
    effective_entry_days_to_sell,
    effective_entry_profit_net,
    effective_entry_qty,
    effective_entry_status,
    effective_entry_trade_history_source,
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


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100.0:.0f}%"


def _fmt_age_hours(value: object) -> str:
    try:
        age_sec = float(value)
    except (TypeError, ValueError):
        return "-"
    if age_sec < 0.0:
        return "-"
    return f"{age_sec / 3600.0:.1f}h"


def _entries_wallet_quality(entries: list[dict]) -> dict:
    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue
        if (
            str(entry.get("wallet_data_freshness", "") or "").strip()
            or str(entry.get("wallet_history_quality", "") or "").strip()
            or str(entry.get("reconciliation_basis", "") or "").strip()
        ):
            return {
                "wallet_data_freshness": str(entry.get("wallet_data_freshness", "unknown") or "unknown"),
                "wallet_history_quality": str(entry.get("wallet_history_quality", "missing") or "missing"),
                "wallet_history_truncated": bool(entry.get("wallet_history_truncated", False)),
                "wallet_snapshot_age_sec": entry.get("wallet_snapshot_age_sec"),
                "wallet_transactions_pages_loaded": int(entry.get("wallet_transactions_pages_loaded", 0) or 0),
                "wallet_journal_pages_loaded": int(entry.get("wallet_journal_pages_loaded", 0) or 0),
                "fee_match_quality": str(entry.get("fee_match_quality", "") or ""),
                "reconciliation_basis": str(entry.get("reconciliation_basis", "") or ""),
            }
    return {}


def _append_wallet_quality_lines(
    lines: list[str],
    *,
    freshness: str,
    age_sec: object,
    history_quality: str,
    history_truncated: bool,
    tx_pages_loaded: int,
    tx_total_pages: int = 0,
    journal_pages_loaded: int,
    journal_total_pages: int = 0,
    fee_match_quality: str = "",
    reconciliation_basis: str = "",
    warnings: list[str] | None = None,
) -> None:
    if freshness or history_quality or reconciliation_basis:
        tx_pages_txt = (
            f"{int(tx_pages_loaded)}/{int(tx_total_pages)}"
            if int(tx_total_pages or 0) > 0
            else str(int(tx_pages_loaded))
        )
        journal_pages_txt = (
            f"{int(journal_pages_loaded)}/{int(journal_total_pages)}"
            if int(journal_total_pages or 0) > 0
            else str(int(journal_pages_loaded))
        )
        basis_txt = f" | Basis: {reconciliation_basis}" if str(reconciliation_basis or "").strip() else ""
        fee_txt = f" | Fee match: {fee_match_quality}" if str(fee_match_quality or "").strip() else ""
        trunc_txt = " | truncated=yes" if bool(history_truncated) else ""
        lines.append(
            (
                f"Wallet quality: freshness={str(freshness or 'unknown')} ({_fmt_age_hours(age_sec)}) | "
                f"history={str(history_quality or 'missing')} | tx_pages={tx_pages_txt} | journal_pages={journal_pages_txt}"
                f"{fee_txt}{basis_txt}{trunc_txt}"
            )
        )
    for warning in list(warnings or []):
        lines.append(f"[WARN] {warning}")


def _realized_outcome_score(proposed_expected_profit: float, proposed_qty: float, proposed_days: float, actual_profit: float, actual_sell_qty: float, actual_days: float | None) -> float:
    profit_score = _clamp01(
        (actual_profit / proposed_expected_profit) if proposed_expected_profit > 1e-9 else (1.0 if actual_profit >= 0.0 else 0.0)
    )
    qty_score = _clamp01((actual_sell_qty / proposed_qty) if proposed_qty > 1e-9 else 1.0)
    if actual_days is None or proposed_days <= 0.0:
        duration_score = 0.0 if actual_days is None else 1.0
    else:
        duration_score = _clamp01(proposed_days / max(actual_days, 1e-9))
    return _clamp01((profit_score * 0.60) + (qty_score * 0.25) + (duration_score * 0.15))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def enrich_journal_entry(entry: dict, now: datetime | None = None) -> dict:
    current_now = now or datetime.now(timezone.utc)
    enriched = dict(entry or {})
    proposed_qty = _as_float(enriched.get("proposed_qty", 0.0))
    actual_buy_qty = effective_entry_qty(enriched, "buy")
    actual_sell_qty = effective_entry_qty(enriched, "sell")
    proposed_expected_profit = _as_float(enriched.get("proposed_expected_profit", 0.0))
    proposed_expected_days = _as_float(enriched.get("proposed_expected_days_to_sell", 0.0))
    actual_profit = effective_entry_profit_net(enriched)
    actual_days = effective_entry_days_to_sell(enriched)
    proposed_confidence = _as_float(
        enriched.get("proposed_overall_confidence_raw", enriched.get("proposed_confidence", 0.0))
    )
    outcome_score = _realized_outcome_score(
        proposed_expected_profit,
        proposed_qty,
        proposed_expected_days,
        actual_profit,
        actual_sell_qty,
        actual_days,
    )
    enriched["comparison_profit_delta"] = actual_profit - proposed_expected_profit
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
    enriched["effective_status"] = effective_entry_status(enriched)
    enriched["effective_buy_qty"] = actual_buy_qty
    enriched["effective_sell_qty"] = actual_sell_qty
    enriched["effective_profit_net"] = actual_profit
    enriched["trade_history_source"] = effective_entry_trade_history_source(enriched)
    first_buy = _parse_dt(str(enriched.get("first_buy_at", "") or ""))
    if first_buy is None:
        first_buy = _parse_dt(str(enriched.get("first_matched_buy_at", "") or ""))
    if first_buy is None:
        first_buy = _parse_dt(str(enriched.get("created_at", "") or ""))
    if first_buy is not None and str(enriched.get("effective_status", "") or "").strip().lower() in JOURNAL_OPEN_STATUSES:
        enriched["open_days"] = max(0.0, (current_now - first_buy).total_seconds() / 86400.0)
    else:
        enriched["open_days"] = 0.0
    enriched["actual_inventory_open_qty"] = max(0.0, actual_buy_qty - actual_sell_qty)
    return enriched


def build_personal_trade_analytics(entries: list[dict], now: datetime | None = None) -> dict:
    enriched = [enrich_journal_entry(entry, now=now) for entry in list(entries or [])]
    sold_entries = [entry for entry in enriched if str(entry.get("effective_status", "")).strip().lower() == "sold"]
    bought_entries = [entry for entry in enriched if _as_float(entry.get("effective_buy_qty", 0.0)) > 0.0]
    open_entries = [entry for entry in enriched if str(entry.get("effective_status", "")).strip().lower() in JOURNAL_OPEN_STATUSES]
    partial_entries = [entry for entry in enriched if str(entry.get("effective_status", "")).strip().lower() == "partially_sold"]
    uncertain_entries = [
        entry for entry in enriched if "uncertain" in str(entry.get("reconciliation_status", "") or "").strip().lower()
    ]
    wallet_unmatched_entries = [
        entry for entry in enriched if str(entry.get("reconciliation_status", "") or "").strip().lower() == "wallet_unmatched"
    ]
    overlap_entries = [
        entry for entry in enriched if str(entry.get("open_order_warning_tier", "") or "").strip().lower() in {"low", "medium", "high"}
    ]
    open_age_buckets = {"0-7d": 0, "7-30d": 0, "30d+": 0}
    for entry in open_entries:
        open_days = _as_float(entry.get("open_days", 0.0))
        if open_days < 7.0:
            open_age_buckets["0-7d"] += 1
        elif open_days < 30.0:
            open_age_buckets["7-30d"] += 1
        else:
            open_age_buckets["30d+"] += 1
    fee_quality_mix: dict[str, int] = defaultdict(int)
    freshness_mix: dict[str, int] = defaultdict(int)
    history_mix: dict[str, int] = defaultdict(int)
    for entry in enriched:
        fee_quality_mix[str(entry.get("fee_match_quality", "") or "none").strip().lower() or "none"] += 1
        freshness_mix[str(entry.get("wallet_data_freshness", "") or "unknown").strip().lower() or "unknown"] += 1
        history_mix[str(entry.get("wallet_history_quality", "") or "missing").strip().lower() or "missing"] += 1
    expected_days_values = [
        _as_float(entry.get("proposed_expected_days_to_sell", 0.0))
        for entry in sold_entries
        if entry.get("actual_days_to_sell") is not None
    ]
    actual_days_values = [
        _as_float(entry.get("actual_days_to_sell", 0.0))
        for entry in sold_entries
        if entry.get("actual_days_to_sell") is not None
    ]
    days_deltas = [
        _as_float(entry.get("comparison_days_delta", 0.0))
        for entry in sold_entries
        if entry.get("comparison_days_delta") is not None
    ]
    total_entries = len(enriched)
    bought_count = len(bought_entries)
    return {
        "entries_total": total_entries,
        "wallet_backed_count": sum(1 for entry in enriched if str(entry.get("trade_history_source", "") or "") == "wallet"),
        "manual_only_count": sum(1 for entry in enriched if str(entry.get("trade_history_source", "") or "") != "wallet"),
        "suggested_to_bought_rate": (bought_count / float(total_entries)) if total_entries > 0 else 0.0,
        "bought_to_fully_sold_rate": (len(sold_entries) / float(bought_count)) if bought_count > 0 else 0.0,
        "partial_sell_share": (len(partial_entries) / float(bought_count)) if bought_count > 0 else 0.0,
        "uncertain_match_share": (len(uncertain_entries) / float(total_entries)) if total_entries > 0 else 0.0,
        "wallet_unmatched_share": (len(wallet_unmatched_entries) / float(total_entries)) if total_entries > 0 else 0.0,
        "sold_expected_profit_total": sum(_as_float(entry.get("proposed_expected_profit", 0.0)) for entry in sold_entries),
        "sold_realized_profit_total": sum(_as_float(entry.get("effective_profit_net", 0.0)) for entry in sold_entries),
        "profit_delta_total": sum(_as_float(entry.get("comparison_profit_delta", 0.0)) for entry in sold_entries),
        "avg_expected_sell_days_sold": (sum(expected_days_values) / float(len(expected_days_values))) if expected_days_values else None,
        "avg_actual_sell_days_sold": (sum(actual_days_values) / float(len(actual_days_values))) if actual_days_values else None,
        "avg_sell_days_delta_sold": (sum(days_deltas) / float(len(days_deltas))) if days_deltas else None,
        "open_positions_by_age": open_age_buckets,
        "problem_counts": {
            "optimistic_profit": sum(1 for entry in sold_entries if _as_float(entry.get("comparison_profit_delta", 0.0)) < 0.0),
            "optimistic_sell_duration": sum(1 for entry in sold_entries if _as_float(entry.get("comparison_days_delta", 0.0)) > 0.0),
            "never_bought": sum(1 for entry in enriched if _as_float(entry.get("effective_buy_qty", 0.0)) <= 0.0),
            "partially_sold": len(partial_entries),
            "stuck_open": sum(
                1
                for entry in open_entries
                if _as_float(entry.get("open_days", 0.0))
                > max(14.0, _as_float(entry.get("proposed_expected_days_to_sell", 0.0)))
            ),
            "order_overlap": len(overlap_entries),
        },
        "data_quality": {
            "fee_match_quality_mix": dict(fee_quality_mix),
            "wallet_data_freshness_mix": dict(freshness_mix),
            "wallet_history_quality_mix": dict(history_mix),
            "secure_trade_count": sum(
                1
                for entry in enriched
                if "uncertain" not in str(entry.get("reconciliation_status", "") or "").strip().lower()
                and str(entry.get("reconciliation_status", "") or "").strip().lower() != "wallet_unmatched"
            ),
            "uncertain_trade_count": len(uncertain_entries),
        },
    }


def summarize_journal(entries: list[dict], now: datetime | None = None) -> dict:
    enriched = [enrich_journal_entry(e, now=now) for e in list(entries or [])]
    sold_entries = [e for e in enriched if str(e.get("effective_status", "")).strip().lower() == "sold"]
    open_entries = [e for e in enriched if str(e.get("effective_status", "")).strip().lower() in JOURNAL_OPEN_STATUSES]
    closed_entries = [e for e in enriched if str(e.get("effective_status", "")).strip().lower() in JOURNAL_CLOSED_STATUSES]
    return {
        "entries_total": len(enriched),
        "planned_count": sum(1 for e in enriched if str(e.get("effective_status", "")).strip().lower() == "planned"),
        "bought_count": sum(1 for e in enriched if str(e.get("effective_status", "")).strip().lower() == "bought"),
        "partial_count": sum(1 for e in enriched if str(e.get("effective_status", "")).strip().lower() == "partially_sold"),
        "sold_count": sum(1 for e in sold_entries),
        "abandoned_count": sum(1 for e in enriched if str(e.get("effective_status", "")).strip().lower() == "abandoned"),
        "invalidated_count": sum(1 for e in enriched if str(e.get("effective_status", "")).strip().lower() == "invalidated"),
        "open_count": len(open_entries),
        "closed_count": len(closed_entries),
        "reconciled_count": sum(1 for e in enriched if str(e.get("reconciliation_status", "")).strip()),
        "uncertain_match_count": sum(1 for e in enriched if "uncertain" in str(e.get("reconciliation_status", "")).strip().lower()),
        "wallet_unmatched_count": sum(1 for e in enriched if str(e.get("reconciliation_status", "")).strip().lower() == "wallet_unmatched"),
        "total_proposed_expected_profit": sum(_as_float(e.get("proposed_expected_profit", 0.0)) for e in enriched),
        "total_real_profit_closed": sum(_as_float(e.get("effective_profit_net", 0.0)) for e in sold_entries),
        "total_real_profit_all": sum(_as_float(e.get("effective_profit_net", 0.0)) for e in enriched),
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
        if str(entry.get("effective_status", "")).strip().lower() == "sold":
            group["sold_count"] += 1
            group["total_real_profit"] += _as_float(entry.get("effective_profit_net", 0.0))
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
    sold_entries = [e for e in enriched if str(e.get("effective_status", "")).strip().lower() == "sold"]
    open_positions = [
        e
        for e in enriched
        if str(e.get("effective_status", "")).strip().lower() in ("bought", "partially_sold") and _as_float(e.get("effective_buy_qty", 0.0)) > 0.0
    ]
    uncertain_matches = [
        entry for entry in enriched if "uncertain" in str(entry.get("reconciliation_status", "")).strip().lower()
    ][: max(1, int(limit))]
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
        "uncertain_matches": uncertain_matches,
    }


def _format_entry_line(entry: dict) -> str:
    item_name = str(entry.get("item_name", "") or "")
    route_label = str(entry.get("route_label", "") or "")
    status = str(entry.get("effective_status", entry.get("status", "")) or "")
    entry_id = str(entry.get("journal_entry_id", "") or "")
    expected = fmt_isk(_as_float(entry.get("proposed_expected_profit", 0.0)))
    actual = fmt_isk(_as_float(entry.get("effective_profit_net", 0.0)))
    extra = ""
    reconciliation_status = str(entry.get("reconciliation_status", "") or "").strip()
    if reconciliation_status:
        extra = f" | recon={reconciliation_status}"
    return f"- {entry_id} | {status} | {item_name} | {route_label} | exp={expected} | real={actual}{extra}"


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
        (
            f"Reconciled: {summary['reconciled_count']} | "
            f"uncertain: {summary['uncertain_match_count']} | wallet_unmatched: {summary['wallet_unmatched_count']}"
        ),
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
    open_entries = [entry for entry in enriched if str(entry.get("effective_status", "")).strip().lower() in JOURNAL_OPEN_STATUSES]
    lines = ["=" * 70, "OFFENE POSITIONEN", "=" * 70]
    if not open_entries:
        lines.append("Keine offenen Positionen.")
        return "\n".join(lines)
    for entry in open_entries[: max(1, int(limit))]:
        warning = ""
        if str(entry.get("open_order_warning_tier", "") or "").strip():
            warning = f" | order_warning={str(entry.get('open_order_warning_tier', '') or '').upper()}"
        lines.append(
            (
                f"- {entry.get('journal_entry_id', '')} | {entry.get('effective_status', entry.get('status', ''))} | {entry.get('item_name', '')} | "
                f"open_qty={entry.get('actual_inventory_open_qty', 0.0):.2f} | open_days={_fmt_days(entry.get('open_days'))} | "
                f"exp_days={_fmt_days(_as_float(entry.get('proposed_expected_days_to_sell', 0.0)))} | route={entry.get('route_label', '')}"
                f"{warning}"
            )
        )
    return "\n".join(lines)


def format_closed_positions(entries: list[dict], limit: int = 20, now: datetime | None = None) -> str:
    enriched = [enrich_journal_entry(entry, now=now) for entry in list(entries or [])]
    closed_entries = [entry for entry in enriched if str(entry.get("effective_status", "")).strip().lower() in JOURNAL_CLOSED_STATUSES]
    lines = ["=" * 70, "ABGESCHLOSSENE POSITIONEN", "=" * 70]
    if not closed_entries:
        lines.append("Keine abgeschlossenen Positionen.")
        return "\n".join(lines)
    for entry in closed_entries[: max(1, int(limit))]:
        recon = str(entry.get("reconciliation_status", "") or "").strip()
        lines.append(
            (
                f"- {entry.get('journal_entry_id', '')} | {entry.get('effective_status', entry.get('status', ''))} | {entry.get('item_name', '')} | "
                f"expected={fmt_isk(_as_float(entry.get('proposed_expected_profit', 0.0)))} | "
                f"real={fmt_isk(_as_float(entry.get('effective_profit_net', 0.0)))} | "
                f"delta={fmt_isk(_as_float(entry.get('comparison_profit_delta', 0.0)))} | "
                f"sell_days={_fmt_days(entry.get('actual_days_to_sell'))}"
                f"{f' | recon={recon}' if recon else ''}"
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
        (
            f"Reconciled={summary['reconciled_count']} | "
            f"uncertain={summary['uncertain_match_count']} | wallet_unmatched={summary['wallet_unmatched_count']}"
        ),
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
    lines.append("")
    lines.append("Unsichere Wallet-Matches:")
    if report["uncertain_matches"]:
        for entry in report["uncertain_matches"]:
            lines.append(
                f"- {entry.get('item_name', '')} | recon={entry.get('reconciliation_status', '')} | "
                f"confidence={_as_float(entry.get('match_confidence', 0.0)):.2f} | route={entry.get('route_label', '')}"
            )
    else:
        lines.append("- Keine unsicheren Wallet-Matches.")
    return "\n".join(lines)


def format_reconciliation_overview(result: dict, limit: int = 10, now: datetime | None = None) -> str:
    entries = [enrich_journal_entry(entry, now=now) for entry in list(result.get("entries", []) or [])]
    status_counts = dict(result.get("status_counts", {}) or {})
    lines = [
        "=" * 70,
        "WALLET RECONCILIATION",
        "=" * 70,
        (
            f"Wallet available: {'yes' if bool(result.get('wallet_available', False)) else 'no'} | "
            f"Transactions: {int(result.get('wallet_transaction_count', 0) or 0)} | "
            f"Journal: {int(result.get('wallet_journal_count', 0) or 0)}"
        ),
        (
            f"Matched entries: {int(result.get('matched_entry_count', 0) or 0)} | "
            f"Uncertain entries: {int(result.get('uncertain_entry_count', 0) or 0)} | "
            f"Unmatched transactions: {len(list(result.get('unmatched_transactions', []) or []))}"
        ),
    ]
    _append_wallet_quality_lines(
        lines,
        freshness=str(result.get("wallet_data_freshness", "unknown") or "unknown"),
        age_sec=result.get("wallet_snapshot_age_sec"),
        history_quality=str(result.get("wallet_history_quality", "missing") or "missing"),
        history_truncated=bool(result.get("wallet_history_truncated", False)),
        tx_pages_loaded=int(result.get("wallet_transactions_pages_loaded", 0) or 0),
        tx_total_pages=int(result.get("wallet_transactions_total_pages", 0) or 0),
        journal_pages_loaded=int(result.get("wallet_journal_pages_loaded", 0) or 0),
        journal_total_pages=int(result.get("wallet_journal_total_pages", 0) or 0),
        fee_match_quality=str(result.get("fee_match_quality", "") or ""),
        reconciliation_basis=str(result.get("reconciliation_basis", "") or ""),
        warnings=[str(w) for w in list(result.get("data_quality_warnings", []) or []) if str(w).strip()],
    )
    if status_counts:
        lines.append("Statuses: " + ", ".join(f"{key}={int(value)}" for key, value in sorted(status_counts.items())))
    if result.get("context_source") is not None:
        lines.append(f"Character context source: {result.get('context_source', 'default')}")
    for warning in list(result.get("context_warnings", []) or []):
        lines.append(f"[WARN] {warning}")
    lines.append("")
    lines.append("Top reconciled entries:")
    ranked = sorted(entries, key=lambda item: _as_float(item.get("effective_profit_net", 0.0)), reverse=True)
    for entry in ranked[: max(1, int(limit))]:
        lines.append(_format_entry_line(entry))
    if not ranked:
        lines.append("- Keine Journal-Eintraege vorhanden.")
    return "\n".join(lines)


def format_unmatched_wallet_activity(result: dict, limit: int = 20) -> str:
    lines = ["=" * 70, "UNGEMATCHTE WALLET-AKTIVITAET", "=" * 70]
    _append_wallet_quality_lines(
        lines,
        freshness=str(result.get("wallet_data_freshness", "unknown") or "unknown"),
        age_sec=result.get("wallet_snapshot_age_sec"),
        history_quality=str(result.get("wallet_history_quality", "missing") or "missing"),
        history_truncated=bool(result.get("wallet_history_truncated", False)),
        tx_pages_loaded=int(result.get("wallet_transactions_pages_loaded", 0) or 0),
        tx_total_pages=int(result.get("wallet_transactions_total_pages", 0) or 0),
        journal_pages_loaded=int(result.get("wallet_journal_pages_loaded", 0) or 0),
        journal_total_pages=int(result.get("wallet_journal_total_pages", 0) or 0),
        fee_match_quality=str(result.get("fee_match_quality", "") or ""),
        reconciliation_basis=str(result.get("reconciliation_basis", "") or ""),
        warnings=[str(w) for w in list(result.get("data_quality_warnings", []) or []) if str(w).strip()],
    )
    unmatched_transactions = list(result.get("unmatched_transactions", []) or [])
    ambiguous_transactions = list(result.get("ambiguous_transactions", []) or [])
    unmatched_journal_entries = list(result.get("unmatched_journal_entries", []) or [])
    lines.append(f"Unmatched transactions: {len(unmatched_transactions)}")
    for tx in unmatched_transactions[: max(1, int(limit))]:
        lines.append(
            f"- tx {int(tx.get('transaction_id', 0) or 0)} | {tx.get('direction', '')} | "
            f"type_id {int(tx.get('type_id', 0) or 0)} | qty={_as_float(tx.get('quantity', 0.0)):.2f} | "
            f"price={_as_float(tx.get('unit_price', 0.0)):.2f} | at={tx.get('happened_at', '')}"
        )
    if not unmatched_transactions:
        lines.append("- Keine ungematchten Wallet-Transactions.")
    lines.append("")
    lines.append(f"Ambiguous transactions: {len(ambiguous_transactions)}")
    for item in ambiguous_transactions[: max(1, int(limit))]:
        tx = item.get("transaction", {}) if isinstance(item.get("transaction", {}), dict) else {}
        candidates = list(item.get("candidate_entries", []) or [])
        candidate_text = ", ".join(
            f"{cand.get('journal_entry_id', '')}:{_as_float(cand.get('score', 0.0)):.2f}"
            for cand in candidates[:3]
        )
        lines.append(
            f"- tx {int(tx.get('transaction_id', 0) or 0)} | {tx.get('direction', '')} | "
            f"type_id {int(tx.get('type_id', 0) or 0)} | candidates={candidate_text}"
        )
    if not ambiguous_transactions:
        lines.append("- Keine ambigen Wallet-Transactions.")
    lines.append("")
    lines.append(f"Unmatched wallet journal fees: {len(unmatched_journal_entries)}")
    for item in unmatched_journal_entries[: max(1, int(limit))]:
        lines.append(
            f"- journal {int(item.get('journal_id', 0) or 0)} | {item.get('ref_type', '')} | "
            f"amount={fmt_isk(_as_float(item.get('amount', 0.0)))} | at={item.get('happened_at', '')}"
        )
    if not unmatched_journal_entries:
        lines.append("- Keine ungematchten Wallet-Journal-Gebuehren.")
    return "\n".join(lines)


def format_personal_trade_history(
    entries: list[dict],
    limit: int = 10,
    now: datetime | None = None,
    personal_calibration: dict | None = None,
) -> str:
    report = build_journal_report(entries, limit=limit, now=now)
    summary = report["summary"]
    analytics = build_personal_trade_analytics(list(report.get("entries", []) or []), now=now)
    wallet_quality = _entries_wallet_quality(list(report.get("entries", []) or []))
    if personal_calibration is None:
        from confidence_calibration import build_personal_calibration_summary

        personal_calibration = build_personal_calibration_summary(list(report.get("entries", []) or []), {}, now=now)
    sample_size = dict((personal_calibration or {}).get("sample_size", {}) or {})
    policy = dict((personal_calibration or {}).get("policy", {}) or {})
    overall_diag = dict(((personal_calibration or {}).get("diagnostics", {}) or {}).get("overall", {}) or {})
    personal_warnings = list((personal_calibration or {}).get("warnings", []) or [])
    lines = [
        "=" * 70,
        "PERSONAL TRADE HISTORY",
        "=" * 70,
        (
            f"Open={summary['open_count']} | Sold={summary['sold_count']} | "
            f"Reconciled={summary['reconciled_count']} | uncertain={summary['uncertain_match_count']}"
        ),
        f"Expected gesamt: {fmt_isk(summary['total_proposed_expected_profit'])}",
        f"Realisiert (sold): {fmt_isk(summary['total_real_profit_closed'])}",
        "",
        (
            f"History quality={str((personal_calibration or {}).get('quality_level', 'none'))} | "
            f"eligible={int(sample_size.get('eligible_entries', 0) or 0)} | "
            f"wallet_backed={int(sample_size.get('wallet_backed_entries', 0) or 0)} | "
            f"reliable={int(sample_size.get('reliable_entries', 0) or 0)}"
        ),
        (
            f"Policy: {'fallback generic' if bool(policy.get('fallback_to_generic', True)) else 'supplemental only'} | "
            f"ranking_effect={policy.get('ranking_effect', 'none')} | "
            f"diagnosis={str(overall_diag.get('diagnosis', 'n/a') or 'n/a')}"
        ),
        "",
    ]
    if personal_warnings:
        lines.append("Warnings:")
        for warning in personal_warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.extend(
        [
            "Persoenliche Trefferquoten:",
            (
                f"- suggested -> bought: {_fmt_pct(analytics.get('suggested_to_bought_rate'))} | "
                f"bought -> fully sold: {_fmt_pct(analytics.get('bought_to_fully_sold_rate'))}"
            ),
            (
                f"- partially sold share: {_fmt_pct(analytics.get('partial_sell_share'))} | "
                f"uncertain matches: {_fmt_pct(analytics.get('uncertain_match_share'))} | "
                f"wallet unmatched: {_fmt_pct(analytics.get('wallet_unmatched_share'))}"
            ),
            "",
            "Soll/Ist komprimiert:",
            (
                f"- sold expected: {fmt_isk(_as_float(analytics.get('sold_expected_profit_total', 0.0)))} | "
                f"sold realized: {fmt_isk(_as_float(analytics.get('sold_realized_profit_total', 0.0)))} | "
                f"delta: {fmt_isk(_as_float(analytics.get('profit_delta_total', 0.0)))}"
            ),
            (
                f"- expected sell days: {_fmt_days(analytics.get('avg_expected_sell_days_sold'))} | "
                f"actual sell days: {_fmt_days(analytics.get('avg_actual_sell_days_sold'))} | "
                f"delta: {_fmt_days(analytics.get('avg_sell_days_delta_sold'))}"
            ),
            (
                f"- open positions by age: 0-7d={int((analytics.get('open_positions_by_age', {}) or {}).get('0-7d', 0) or 0)} | "
                f"7-30d={int((analytics.get('open_positions_by_age', {}) or {}).get('7-30d', 0) or 0)} | "
                f"30d+={int((analytics.get('open_positions_by_age', {}) or {}).get('30d+', 0) or 0)}"
            ),
            "",
            "Problemklassen:",
            (
                f"- optimistic profit={int((analytics.get('problem_counts', {}) or {}).get('optimistic_profit', 0) or 0)} | "
                f"optimistic sell duration={int((analytics.get('problem_counts', {}) or {}).get('optimistic_sell_duration', 0) or 0)}"
            ),
            (
                f"- never bought={int((analytics.get('problem_counts', {}) or {}).get('never_bought', 0) or 0)} | "
                f"partially sold={int((analytics.get('problem_counts', {}) or {}).get('partially_sold', 0) or 0)} | "
                f"stuck open={int((analytics.get('problem_counts', {}) or {}).get('stuck_open', 0) or 0)} | "
                f"order overlap={int((analytics.get('problem_counts', {}) or {}).get('order_overlap', 0) or 0)}"
            ),
        ]
    )
    if wallet_quality:
        _append_wallet_quality_lines(
            lines,
            freshness=str(wallet_quality.get("wallet_data_freshness", "unknown") or "unknown"),
            age_sec=wallet_quality.get("wallet_snapshot_age_sec"),
            history_quality=str(wallet_quality.get("wallet_history_quality", "missing") or "missing"),
            history_truncated=bool(wallet_quality.get("wallet_history_truncated", False)),
            tx_pages_loaded=int(wallet_quality.get("wallet_transactions_pages_loaded", 0) or 0),
            journal_pages_loaded=int(wallet_quality.get("wallet_journal_pages_loaded", 0) or 0),
            fee_match_quality=str(wallet_quality.get("fee_match_quality", "") or ""),
            reconciliation_basis=str(wallet_quality.get("reconciliation_basis", "") or ""),
        )
        lines.append("")
    lines.append(
        (
            f"Persoenliche Calibration-Basis: "
            f"{'fallback to generic model' if bool(policy.get('fallback_to_generic', True)) else 'supplemental personal history available'}"
        )
    )
    lines.append("")
    lines.append("Soll/Ist groesste Abweichungen:")
    mismatches = sorted(
        list(report.get("entries", []) or []),
        key=lambda entry: abs(_as_float(entry.get("comparison_profit_delta", 0.0))),
        reverse=True,
    )
    for entry in mismatches[: max(1, int(limit))]:
        lines.append(
            f"- {entry.get('item_name', '')} | status={entry.get('effective_status', '')} | "
            f"delta={fmt_isk(_as_float(entry.get('comparison_profit_delta', 0.0)))} | "
            f"sell_days={_fmt_days(entry.get('actual_days_to_sell'))} | "
            f"source={entry.get('trade_history_source', '')}"
        )
    if not mismatches:
        lines.append("- Keine Journal-Eintraege vorhanden.")
    lines.append("")
    lines.append("Offene Positionen:")
    open_positions = [entry for entry in report.get("entries", []) if str(entry.get("effective_status", "")).strip().lower() in JOURNAL_OPEN_STATUSES]
    for entry in open_positions[: max(1, int(limit))]:
        lines.append(
            f"- {entry.get('item_name', '')} | open_qty={_as_float(entry.get('actual_inventory_open_qty', 0.0)):.2f} | "
            f"open_days={_fmt_days(entry.get('open_days'))} | recon={entry.get('reconciliation_status', '')}"
        )
    if not open_positions:
        lines.append("- Keine offenen Positionen.")
    lines.append("")
    lines.append("Unsichere / schlechte Matches:")
    uncertain = list(report.get("uncertain_matches", []) or [])
    for entry in uncertain[: max(1, int(limit))]:
        lines.append(
            f"- {entry.get('item_name', '')} | recon={entry.get('reconciliation_status', '')} | "
            f"confidence={_as_float(entry.get('match_confidence', 0.0)):.2f} | "
            f"fee={entry.get('fee_match_quality', '')} | reason={entry.get('match_reason', '')}"
        )
    if not uncertain:
        lines.append("- Keine unsicheren Matches.")
    return "\n".join(lines)


__all__ = [
    "build_journal_report",
    "build_personal_trade_analytics",
    "enrich_journal_entry",
    "format_closed_positions",
    "format_journal_overview",
    "format_journal_report",
    "format_open_positions",
    "format_personal_trade_history",
    "format_reconciliation_overview",
    "format_unmatched_wallet_activity",
    "summarize_journal",
]
