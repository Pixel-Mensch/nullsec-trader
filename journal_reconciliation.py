from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from journal_models import normalize_journal_timestamp


MATCH_THRESHOLD = 0.58
AMBIGUOUS_MARGIN = 0.08

_FEE_REF_TYPES = {
    "brokers_fee",
    "transaction_tax",
    "market_provider_tax",
    "industry_job_tax",
    "industry_job_fee",
}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_dt(value: object) -> datetime | None:
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


def _to_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _location_id_from_entry(entry: dict, direction: str) -> int:
    if direction == "buy":
        return _as_int(entry.get("source_location_id", entry.get("buy_location_id", 0)))
    return _as_int(entry.get("target_location_id", entry.get("sell_location_id", 0)))


def _entry_type_id(entry: dict) -> int:
    return _as_int(entry.get("item_type_id", entry.get("type_id", 0)))


def _entry_qty_target(entry: dict, direction: str) -> float:
    if direction == "buy":
        actual = _as_float(entry.get("actual_buy_qty", 0.0))
    else:
        actual = _as_float(entry.get("actual_sell_qty", 0.0))
    proposed = _as_float(entry.get("proposed_qty", 0.0))
    expected_units_sold = _as_float(entry.get("proposed_expected_units_sold", 0.0))
    if direction == "sell" and expected_units_sold > 0.0:
        proposed = max(proposed, expected_units_sold)
    return max(actual, proposed, 1.0)


def _entry_price_anchor(entry: dict, direction: str) -> float:
    if direction == "buy":
        return max(
            _as_float(entry.get("actual_buy_price_avg", 0.0)),
            _as_float(entry.get("proposed_buy_price", 0.0)),
        )
    return max(
        _as_float(entry.get("actual_sell_price_avg", 0.0)),
        _as_float(entry.get("proposed_sell_price", 0.0)),
    )


def _entry_time_anchor(entry: dict, direction: str) -> tuple[datetime | None, bool]:
    if direction == "buy":
        actual = _parse_dt(entry.get("first_buy_at"))
        if actual is not None:
            return actual, True
    else:
        actual = _parse_dt(entry.get("last_sell_at"))
        if actual is not None:
            return actual, True
        first_buy = _parse_dt(entry.get("first_buy_at"))
        if first_buy is not None:
            return first_buy, True
    return _parse_dt(entry.get("created_at")), False


def _normalize_wallet_transactions(wallet_snapshot: dict) -> list[dict]:
    out: list[dict] = []
    seen_ids: set[int] = set()
    for raw in list(wallet_snapshot.get("transactions", []) or []):
        if not isinstance(raw, dict):
            continue
        transaction_id = _as_int(raw.get("transaction_id", 0))
        if transaction_id <= 0:
            transaction_id = -len(out) - 1
        if transaction_id in seen_ids:
            continue
        seen_ids.add(transaction_id)
        quantity = max(0.0, _as_float(raw.get("quantity", raw.get("qty", 0.0))))
        if quantity <= 0.0:
            continue
        unit_price = max(0.0, _as_float(raw.get("unit_price", raw.get("price", 0.0))))
        happened_at = normalize_journal_timestamp(
            str(raw.get("date", raw.get("transaction_date", raw.get("created_at", ""))) or "")
        )
        direction = "buy" if bool(raw.get("is_buy", False)) else "sell"
        out.append(
            {
                "transaction_id": int(transaction_id),
                "type_id": _as_int(raw.get("type_id", 0)),
                "quantity": float(quantity),
                "unit_price": float(unit_price),
                "total_value": float(quantity * unit_price),
                "direction": direction,
                "happened_at": str(happened_at),
                "dt": _parse_dt(happened_at),
                "location_id": _as_int(raw.get("location_id", 0)),
                "journal_ref_id": _as_int(raw.get("journal_ref_id", raw.get("ref_id", 0))),
                "client_id": _as_int(raw.get("client_id", 0)),
                "raw": dict(raw),
            }
        )
    out.sort(key=lambda item: (str(item.get("happened_at", "")), int(item.get("transaction_id", 0))))
    return out


def _normalize_wallet_journal(wallet_snapshot: dict) -> list[dict]:
    out: list[dict] = []
    seen_ids: set[int] = set()
    for raw in list(wallet_snapshot.get("journal_entries", []) or []):
        if not isinstance(raw, dict):
            continue
        journal_id = _as_int(raw.get("id", raw.get("journal_id", raw.get("ref_id", 0))))
        if journal_id <= 0:
            journal_id = -len(out) - 1
        if journal_id in seen_ids:
            continue
        seen_ids.add(journal_id)
        happened_at = normalize_journal_timestamp(str(raw.get("date", raw.get("created_at", "")) or ""))
        out.append(
            {
                "journal_id": int(journal_id),
                "ref_id": _as_int(raw.get("ref_id", raw.get("context_id", 0))),
                "amount": _as_float(raw.get("amount", 0.0)),
                "balance": _as_float(raw.get("balance", 0.0)),
                "ref_type": str(raw.get("ref_type", raw.get("reference_type", "")) or "").strip().lower(),
                "description": str(raw.get("description", raw.get("reason", "")) or "").strip(),
                "happened_at": str(happened_at),
                "dt": _parse_dt(happened_at),
                "raw": dict(raw),
            }
        )
    out.sort(key=lambda item: (str(item.get("happened_at", "")), int(item.get("journal_id", 0))))
    return out


def _qty_score(tx_qty: float, target_qty: float) -> float:
    target = max(float(target_qty), 1.0)
    ratio = max(0.0, float(tx_qty)) / target
    if ratio <= 1.0:
        return _clamp01(0.70 + (0.30 * ratio))
    overflow = min((ratio - 1.0) / 1.0, 1.0)
    return _clamp01(1.0 - overflow)


def _price_score(price: float, anchor: float) -> float:
    if anchor <= 1e-9:
        return 0.55
    diff_pct = abs(float(price) - float(anchor)) / max(float(anchor), 1e-9)
    return _clamp01(1.0 - min(diff_pct / 0.25, 1.0))


def _time_score(tx_dt: datetime | None, anchor_dt: datetime | None, *, anchored_to_actual: bool, created_dt: datetime | None) -> float:
    if tx_dt is None:
        return 0.0
    if anchor_dt is None:
        return 0.50
    diff_days = abs((tx_dt - anchor_dt).total_seconds()) / 86400.0
    span_days = 14.0 if anchored_to_actual else 60.0
    score = _clamp01(1.0 - min(diff_days / span_days, 1.0))
    if created_dt is not None and tx_dt < created_dt - timedelta(days=2):
        score *= 0.25
    return score


def _location_score(tx_location_id: int, entry_location_id: int) -> float:
    if tx_location_id <= 0 or entry_location_id <= 0:
        return 0.65
    if int(tx_location_id) == int(entry_location_id):
        return 1.0
    return 0.15


def _candidate_reason(direction: str, price_score: float, time_score: float, qty_score: float, location_score: float) -> str:
    parts = [direction]
    if price_score >= 0.90:
        parts.append("price-close")
    elif price_score >= 0.65:
        parts.append("price-near")
    if time_score >= 0.90:
        parts.append("time-close")
    elif time_score >= 0.60:
        parts.append("time-window")
    if qty_score >= 0.80:
        parts.append("qty-fit")
    if location_score >= 0.95:
        parts.append("location-exact")
    return ", ".join(parts)


def _score_transaction_candidate(entry: dict, tx: dict, *, character_id: int = 0) -> dict | None:
    if _entry_type_id(entry) <= 0 or _entry_type_id(entry) != _as_int(tx.get("type_id", 0)):
        return None
    direction = str(tx.get("direction", "") or "").strip().lower()
    if direction not in ("buy", "sell"):
        return None
    entry_character_id = _as_int(entry.get("character_id", 0))
    if character_id > 0 and entry_character_id > 0 and entry_character_id != character_id:
        return None

    target_qty = _entry_qty_target(entry, direction)
    anchor_price = _entry_price_anchor(entry, direction)
    anchor_dt, anchored_to_actual = _entry_time_anchor(entry, direction)
    created_dt = _parse_dt(entry.get("created_at"))

    qty_score = _qty_score(_as_float(tx.get("quantity", 0.0)), target_qty)
    price_score = _price_score(_as_float(tx.get("unit_price", 0.0)), anchor_price)
    time_score = _time_score(tx.get("dt"), anchor_dt, anchored_to_actual=anchored_to_actual, created_dt=created_dt)
    location_score = _location_score(_as_int(tx.get("location_id", 0)), _location_id_from_entry(entry, direction))

    score = (0.35 * price_score) + (0.30 * time_score) + (0.25 * qty_score) + (0.10 * location_score)
    if score < MATCH_THRESHOLD:
        return None

    return {
        "journal_entry_id": str(entry.get("journal_entry_id", "")),
        "transaction_id": int(tx.get("transaction_id", 0)),
        "direction": direction,
        "score": float(_clamp01(score)),
        "reason": _candidate_reason(direction, price_score, time_score, qty_score, location_score),
    }


def _is_fee_like_journal_entry(item: dict) -> bool:
    amount = _as_float(item.get("amount", 0.0))
    ref_type = str(item.get("ref_type", "") or "").strip().lower()
    if amount >= 0.0:
        return False
    if ref_type in _FEE_REF_TYPES:
        return True
    return ("fee" in ref_type) or ("tax" in ref_type)


def _linked_journal_entries(journal_entries: list[dict], matched_txs: list[dict]) -> tuple[list[dict], float]:
    ref_ids = {
        _as_int(tx.get("journal_ref_id", 0))
        for tx in list(matched_txs or [])
        if _as_int(tx.get("journal_ref_id", 0)) > 0
    }
    if not ref_ids:
        return [], 0.0
    linked = [
        item
        for item in list(journal_entries or [])
        if _as_int(item.get("ref_id", 0)) in ref_ids or _as_int(item.get("journal_id", 0)) in ref_ids
    ]
    fee_estimate = sum(abs(_as_float(item.get("amount", 0.0))) for item in linked if _is_fee_like_journal_entry(item))
    return linked, float(fee_estimate)


def _match_confidence(matched_txs: list[dict], ambiguous_ids: set[int]) -> float:
    if not matched_txs:
        return 0.0
    total_weight = sum(max(1.0, _as_float(tx.get("total_value", 0.0), 1.0)) for tx in matched_txs)
    weighted = 0.0
    for tx in matched_txs:
        weight = max(1.0, _as_float(tx.get("total_value", 0.0), 1.0))
        weighted += weight * _as_float(tx.get("_match_score", 0.0))
    confidence = weighted / max(total_weight, 1.0)
    if ambiguous_ids:
        confidence -= 0.15
    return _clamp01(confidence)


def _reconciliation_status(entry: dict, *, tx_count: int, matched_buy_qty: float, matched_sell_qty: float, match_confidence: float, ambiguous_ids: set[int]) -> str:
    manual_buy = _as_float(entry.get("actual_buy_qty", 0.0))
    manual_sell = _as_float(entry.get("actual_sell_qty", 0.0))
    if tx_count <= 0:
        return "wallet_unavailable"
    if matched_buy_qty <= 0.0 and matched_sell_qty <= 0.0:
        if ambiguous_ids:
            return "match_uncertain"
        if manual_buy > 0.0 or manual_sell > 0.0:
            return "wallet_unmatched"
        return "suggested_not_bought"
    if ambiguous_ids or match_confidence < 0.70:
        if matched_sell_qty > 0.0:
            return "sold_match_uncertain"
        return "match_uncertain"
    if matched_buy_qty > 0.0 and matched_sell_qty <= 0.0:
        return "bought_open"
    if matched_sell_qty + 1e-9 < matched_buy_qty:
        return "partially_sold"
    return "fully_sold"


def _open_order_warning(entry: dict) -> tuple[str, str]:
    open_sell_orders = _as_int(entry.get("character_open_sell_orders", 0))
    open_buy_orders = _as_int(entry.get("character_open_buy_orders", 0))
    if open_sell_orders > 0:
        return "high", "Existing sell-order overlap for this item type."
    if open_buy_orders > 0:
        return "medium", "Existing buy-order overlap for this item type."
    open_orders = _as_int(entry.get("character_open_orders", 0))
    if open_orders > 0:
        return "medium", "Existing market-order overlap for this item type."
    return "", ""


def reconcile_wallet_snapshot(
    entries: list[dict],
    wallet_snapshot: dict | None,
    *,
    character_id: int = 0,
) -> dict:
    base_entries = [dict(entry or {}) for entry in list(entries or []) if isinstance(entry, dict)]
    wallet = dict(wallet_snapshot or {}) if isinstance(wallet_snapshot, dict) else {}
    transactions = _normalize_wallet_transactions(wallet)
    wallet_journal = _normalize_wallet_journal(wallet)

    entry_by_id = {
        str(entry.get("journal_entry_id", "")): entry
        for entry in base_entries
        if str(entry.get("journal_entry_id", "") or "").strip()
    }

    assigned_by_entry: dict[str, list[dict]] = {entry_id: [] for entry_id in entry_by_id}
    ambiguous_by_entry: dict[str, set[int]] = {entry_id: set() for entry_id in entry_by_id}
    unmatched_transactions: list[dict] = []
    ambiguous_transactions: list[dict] = []

    for tx in transactions:
        candidates = []
        for entry in base_entries:
            candidate = _score_transaction_candidate(entry, tx, character_id=character_id)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(key=lambda item: (float(item.get("score", 0.0)), str(item.get("journal_entry_id", ""))), reverse=True)
        if not candidates:
            unmatched_transactions.append(dict(tx))
            continue
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        if second is not None and (float(top.get("score", 0.0)) - float(second.get("score", 0.0))) < AMBIGUOUS_MARGIN:
            ambiguous_transactions.append(
                {
                    "transaction": dict(tx),
                    "candidate_entries": [dict(c) for c in candidates[:3]],
                }
            )
            for cand in candidates[:3]:
                entry_id = str(cand.get("journal_entry_id", ""))
                if entry_id in ambiguous_by_entry:
                    ambiguous_by_entry[entry_id].add(int(tx.get("transaction_id", 0)))
            continue
        tx_copy = dict(tx)
        tx_copy["_match_score"] = float(top.get("score", 0.0))
        tx_copy["_match_reason"] = str(top.get("reason", "") or "")
        assigned_by_entry[str(top.get("journal_entry_id", ""))].append(tx_copy)

    matched_journal_ids: set[int] = set()
    enriched_entries: list[dict] = []
    matched_entry_count = 0
    uncertain_entry_count = 0

    for entry in base_entries:
        entry_id = str(entry.get("journal_entry_id", "") or "")
        matched_txs = list(assigned_by_entry.get(entry_id, []) or [])
        ambiguous_ids = set(ambiguous_by_entry.get(entry_id, set()) or set())
        buy_txs = [tx for tx in matched_txs if str(tx.get("direction", "")) == "buy"]
        sell_txs = [tx for tx in matched_txs if str(tx.get("direction", "")) == "sell"]
        linked_journal, fee_estimate = _linked_journal_entries(wallet_journal, matched_txs)
        matched_journal_ids.update(_as_int(item.get("journal_id", 0)) for item in linked_journal)

        matched_buy_qty = sum(_as_float(tx.get("quantity", 0.0)) for tx in buy_txs)
        matched_sell_qty = sum(_as_float(tx.get("quantity", 0.0)) for tx in sell_txs)
        matched_buy_value = sum(_as_float(tx.get("total_value", 0.0)) for tx in buy_txs)
        matched_sell_value = sum(_as_float(tx.get("total_value", 0.0)) for tx in sell_txs)
        match_confidence = _match_confidence(matched_txs, ambiguous_ids)
        realized_profit_net = matched_sell_value - matched_buy_value - fee_estimate
        first_buy_dt = min((tx.get("dt") for tx in buy_txs if tx.get("dt") is not None), default=None)
        last_sell_dt = max((tx.get("dt") for tx in sell_txs if tx.get("dt") is not None), default=None)
        status = _reconciliation_status(
            entry,
            tx_count=len(transactions),
            matched_buy_qty=matched_buy_qty,
            matched_sell_qty=matched_sell_qty,
            match_confidence=match_confidence,
            ambiguous_ids=ambiguous_ids,
        )
        warning_tier, warning_text = _open_order_warning(entry)

        reason_parts = []
        if buy_txs:
            reason_parts.append(f"buy:{len(buy_txs)}")
        if sell_txs:
            reason_parts.append(f"sell:{len(sell_txs)}")
        if linked_journal:
            reason_parts.append(f"wallet_journal:{len(linked_journal)}")
        top_reason = ""
        if matched_txs:
            tx_reasons = [str(tx.get("_match_reason", "") or "").strip() for tx in matched_txs if str(tx.get("_match_reason", "")).strip()]
            if tx_reasons:
                top_reason = tx_reasons[0]
        if top_reason:
            reason_parts.append(top_reason)
        if ambiguous_ids:
            reason_parts.append(f"ambiguous:{len(ambiguous_ids)}")
        if not reason_parts:
            if status == "wallet_unavailable":
                reason_parts.append("wallet snapshot unavailable")
            elif status == "wallet_unmatched":
                reason_parts.append("wallet activity present but no clean match")
            else:
                reason_parts.append("no wallet transactions matched")

        entry_out = dict(entry)
        entry_out.update(
            {
                "matched_wallet_transaction_ids": [int(tx.get("transaction_id", 0)) for tx in matched_txs if _as_int(tx.get("transaction_id", 0)) != 0],
                "matched_wallet_journal_ids": [int(item.get("journal_id", 0)) for item in linked_journal if _as_int(item.get("journal_id", 0)) != 0],
                "matched_buy_qty": float(matched_buy_qty),
                "matched_sell_qty": float(matched_sell_qty),
                "matched_buy_value": float(matched_buy_value),
                "matched_sell_value": float(matched_sell_value),
                "first_matched_buy_at": _to_iso(first_buy_dt),
                "last_matched_sell_at": _to_iso(last_sell_dt),
                "realized_fee_estimate": float(fee_estimate),
                "realized_profit_net": float(realized_profit_net),
                "reconciliation_status": str(status),
                "match_confidence": float(match_confidence),
                "match_reason": "; ".join(reason_parts),
                "ambiguous_wallet_transaction_ids": sorted(int(x) for x in ambiguous_ids if int(x) != 0),
                "open_order_warning_tier": str(entry.get("open_order_warning_tier", "") or warning_tier),
                "open_order_warning_text": str(entry.get("open_order_warning_text", "") or warning_text),
            }
        )
        if matched_txs:
            matched_entry_count += 1
        if "uncertain" in status:
            uncertain_entry_count += 1
        enriched_entries.append(entry_out)

    unmatched_journal_entries = [
        dict(item)
        for item in wallet_journal
        if _as_int(item.get("journal_id", 0)) not in matched_journal_ids and _is_fee_like_journal_entry(item)
    ]
    status_counts: dict[str, int] = {}
    for entry in enriched_entries:
        status = str(entry.get("reconciliation_status", "") or "").strip().lower() or "unknown"
        status_counts[status] = int(status_counts.get(status, 0) or 0) + 1

    return {
        "wallet_available": bool(transactions or wallet_journal or _as_float(wallet.get("balance", 0.0)) > 0.0),
        "wallet_balance": _as_float(wallet.get("balance", 0.0)),
        "wallet_transaction_count": len(transactions),
        "wallet_journal_count": len(wallet_journal),
        "character_id": int(character_id),
        "entries": enriched_entries,
        "matched_entry_count": int(matched_entry_count),
        "uncertain_entry_count": int(uncertain_entry_count),
        "unmatched_transactions": unmatched_transactions,
        "ambiguous_transactions": ambiguous_transactions,
        "unmatched_journal_entries": unmatched_journal_entries,
        "status_counts": status_counts,
    }


__all__ = [
    "AMBIGUOUS_MARGIN",
    "MATCH_THRESHOLD",
    "reconcile_wallet_snapshot",
]
