from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from journal_models import normalize_journal_timestamp


MATCH_THRESHOLD = 0.58
AMBIGUOUS_MARGIN = 0.08
DEFAULT_WALLET_STALE_AFTER_SEC = 21600
FEE_FALLBACK_WINDOW_SEC = 180
FEE_FALLBACK_MAX_SHARE = 0.20

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


def _wallet_snapshot_available(wallet: dict, transactions: list[dict], journal_entries: list[dict]) -> bool:
    snap = dict(wallet or {}) if isinstance(wallet, dict) else {}
    if not snap:
        return False
    if str(snap.get("snapshot_at", snap.get("last_successful_sync", "")) or "").strip():
        return True
    if transactions or journal_entries:
        return True
    if "balance" in snap or bool(snap.get("balance_requested", False)):
        return True
    return False


def _wallet_snapshot_age_sec(wallet: dict, *, now: datetime | None = None) -> float | None:
    snap_dt = _parse_dt(wallet.get("snapshot_at", wallet.get("last_successful_sync", "")))
    if snap_dt is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - snap_dt).total_seconds())


def _wallet_component_status(wallet: dict, key: str, rows: list[dict]) -> str:
    status_key = f"{key}_status"
    raw = str(wallet.get(status_key, "") or "").strip().lower()
    if raw:
        return raw
    if rows or f"{key}_count" in wallet or f"{key}_pages_loaded" in wallet:
        return "loaded"
    return "unknown"


def _wallet_component_pages_loaded(wallet: dict, key: str, rows: list[dict], status: str) -> int:
    raw = _as_int(wallet.get(f"{key}_pages_loaded", 0))
    if raw > 0:
        return raw
    if status == "loaded":
        return 1
    return 0


def _wallet_component_total_pages(wallet: dict, key: str, pages_loaded: int) -> int:
    raw = _as_int(wallet.get(f"{key}_total_pages", 0))
    if raw > 0:
        return raw
    return int(max(0, pages_loaded))


def _wallet_component_oldest_dt(wallet: dict, key: str, rows: list[dict]) -> datetime | None:
    stored = _parse_dt(wallet.get(f"{key}_oldest_at", ""))
    if stored is not None:
        return stored
    dts = [row.get("dt") for row in list(rows or []) if row.get("dt") is not None]
    return min(dts, default=None)


def _wallet_component_newest_dt(wallet: dict, key: str, rows: list[dict]) -> datetime | None:
    stored = _parse_dt(wallet.get(f"{key}_newest_at", ""))
    if stored is not None:
        return stored
    dts = [row.get("dt") for row in list(rows or []) if row.get("dt") is not None]
    return max(dts, default=None)


def _wallet_snapshot_meta(wallet: dict, transactions: list[dict], journal_entries: list[dict]) -> dict:
    wallet_available = _wallet_snapshot_available(wallet, transactions, journal_entries)
    age_sec = _wallet_snapshot_age_sec(wallet)
    stale_after_sec = _as_int(wallet.get("warn_stale_after_sec", DEFAULT_WALLET_STALE_AFTER_SEC), DEFAULT_WALLET_STALE_AFTER_SEC)
    data_freshness = "unknown"
    if age_sec is not None:
        data_freshness = "stale" if stale_after_sec > 0 and age_sec > float(stale_after_sec) else "fresh"
    transactions_status = _wallet_component_status(wallet, "transactions", transactions)
    journal_status = _wallet_component_status(wallet, "journal", journal_entries)
    transactions_pages_loaded = _wallet_component_pages_loaded(wallet, "transactions", transactions, transactions_status)
    journal_pages_loaded = _wallet_component_pages_loaded(wallet, "journal", journal_entries, journal_status)
    transactions_total_pages = _wallet_component_total_pages(wallet, "transactions", transactions_pages_loaded)
    journal_total_pages = _wallet_component_total_pages(wallet, "journal", journal_pages_loaded)
    transactions_history_truncated = bool(wallet.get("transactions_history_truncated", False))
    journal_history_truncated = bool(wallet.get("journal_history_truncated", False))
    history_truncated = bool(
        wallet.get("history_truncated", transactions_history_truncated or journal_history_truncated)
    )
    history_quality = "missing"
    if wallet_available:
        if history_truncated:
            history_quality = "truncated"
        elif transactions_status != "loaded" or journal_status != "loaded":
            history_quality = "partial"
        elif data_freshness == "stale":
            history_quality = "stale"
        else:
            history_quality = "full"
    return {
        "wallet_available": bool(wallet_available),
        "age_sec": age_sec,
        "stale_after_sec": int(max(0, stale_after_sec)),
        "data_freshness": data_freshness,
        "history_quality": history_quality,
        "history_truncated": history_truncated,
        "transactions_status": transactions_status,
        "journal_status": journal_status,
        "transactions_pages_loaded": int(transactions_pages_loaded),
        "transactions_total_pages": int(transactions_total_pages),
        "transactions_page_limit": _as_int(wallet.get("transactions_page_limit", 0)),
        "transactions_history_truncated": bool(transactions_history_truncated),
        "transactions_oldest_dt": _wallet_component_oldest_dt(wallet, "transactions", transactions),
        "transactions_newest_dt": _wallet_component_newest_dt(wallet, "transactions", transactions),
        "journal_pages_loaded": int(journal_pages_loaded),
        "journal_total_pages": int(journal_total_pages),
        "journal_page_limit": _as_int(wallet.get("journal_page_limit", 0)),
        "journal_history_truncated": bool(journal_history_truncated),
        "journal_oldest_dt": _wallet_component_oldest_dt(wallet, "journal", journal_entries),
        "journal_newest_dt": _wallet_component_newest_dt(wallet, "journal", journal_entries),
    }


def _entry_history_is_covered(entry: dict, wallet_meta: dict) -> bool:
    if not bool(wallet_meta.get("transactions_history_truncated", False)):
        return True
    oldest_tx_dt = wallet_meta.get("transactions_oldest_dt")
    if oldest_tx_dt is None:
        return True
    anchors = [
        _parse_dt(entry.get("first_buy_at")),
        _parse_dt(entry.get("created_at")),
    ]
    anchor_dt = min((dt for dt in anchors if dt is not None), default=None)
    if anchor_dt is None:
        return True
    return bool(anchor_dt >= (oldest_tx_dt - timedelta(hours=12)))


def _ref_links_journal_item(item: dict, ref_id: int) -> bool:
    if ref_id <= 0:
        return False
    return _as_int(item.get("ref_id", 0)) == ref_id or _as_int(item.get("journal_id", 0)) == ref_id


def _fee_fallback_candidates(journal_entries: list[dict], tx: dict, excluded_ids: set[int]) -> list[dict]:
    tx_dt = tx.get("dt")
    if tx_dt is None:
        return []
    tx_total_value = max(_as_float(tx.get("total_value", 0.0)), 1.0)
    direction = str(tx.get("direction", "") or "").strip().lower()
    out: list[dict] = []
    for item in list(journal_entries or []):
        journal_id = _as_int(item.get("journal_id", 0))
        if journal_id in excluded_ids:
            continue
        if not _is_fee_like_journal_entry(item):
            continue
        item_dt = item.get("dt")
        if item_dt is None:
            continue
        delta_sec = abs((item_dt - tx_dt).total_seconds())
        if delta_sec > float(FEE_FALLBACK_WINDOW_SEC):
            continue
        amount_abs = abs(_as_float(item.get("amount", 0.0)))
        if amount_abs <= 0.0 or amount_abs > (tx_total_value * FEE_FALLBACK_MAX_SHARE):
            continue
        ref_type = str(item.get("ref_type", "") or "").strip().lower()
        if direction == "buy" and ("tax" in ref_type) and ("fee" not in ref_type):
            continue
        candidate = dict(item)
        candidate["_fallback_delta_sec"] = float(delta_sec)
        out.append(candidate)
    out.sort(
        key=lambda item: (
            float(item.get("_fallback_delta_sec", 0.0)),
            abs(_as_float(item.get("amount", 0.0))),
            int(item.get("journal_id", 0)),
        )
    )
    return out


def _linked_journal_entries(journal_entries: list[dict], matched_txs: list[dict], *, wallet_meta: dict) -> dict:
    if not matched_txs:
        return {
            "linked_entries": [],
            "fee_estimate": 0.0,
            "quality": "not_applicable",
            "warnings": [],
        }

    linked_by_id: dict[int, dict] = {}
    exact_fee_tx_ids: set[int] = set()
    matched_tx_list = list(matched_txs or [])
    txs_without_fee_link: list[dict] = []
    for tx in matched_tx_list:
        ref_id = _as_int(tx.get("journal_ref_id", 0))
        exact_links = []
        if ref_id > 0:
            exact_links = [item for item in list(journal_entries or []) if _ref_links_journal_item(item, ref_id)]
        for item in exact_links:
            journal_id = _as_int(item.get("journal_id", 0))
            if journal_id != 0:
                linked_by_id[journal_id] = dict(item)
        if any(_is_fee_like_journal_entry(item) for item in exact_links):
            exact_fee_tx_ids.add(_as_int(tx.get("transaction_id", 0)))
        else:
            txs_without_fee_link.append(tx)

    linked_exact = list(linked_by_id.values())
    excluded_ids = {int(item.get("journal_id", 0)) for item in linked_exact if _as_int(item.get("journal_id", 0)) != 0}
    candidate_map: dict[int, list[dict]] = {}
    candidate_frequency: dict[int, int] = {}
    for tx in txs_without_fee_link:
        tx_id = _as_int(tx.get("transaction_id", 0))
        candidates = _fee_fallback_candidates(journal_entries, tx, excluded_ids)
        candidate_map[tx_id] = candidates
        for item in candidates:
            journal_id = _as_int(item.get("journal_id", 0))
            if journal_id == 0:
                continue
            candidate_frequency[journal_id] = int(candidate_frequency.get(journal_id, 0) or 0) + 1

    fallback_linked: list[dict] = []
    fallback_uncertain = False
    for tx in txs_without_fee_link:
        tx_id = _as_int(tx.get("transaction_id", 0))
        candidates = list(candidate_map.get(tx_id, []) or [])
        if len(candidates) != 1:
            fallback_uncertain = fallback_uncertain or len(candidates) > 1
            continue
        candidate = dict(candidates[0])
        journal_id = _as_int(candidate.get("journal_id", 0))
        if journal_id == 0 or int(candidate_frequency.get(journal_id, 0) or 0) != 1:
            fallback_uncertain = True
            continue
        fallback_linked.append(candidate)
        linked_by_id[journal_id] = dict(candidate)

    linked = list(linked_by_id.values())
    fee_estimate = sum(abs(_as_float(item.get("amount", 0.0))) for item in linked if _is_fee_like_journal_entry(item))
    warnings: list[str] = []
    journal_status = str(wallet_meta.get("journal_status", "unknown") or "unknown").strip().lower()
    if fallback_uncertain:
        warnings.append("fee matching uncertain due to multiple nearby wallet journal candidates")
    unresolved_fee_links = len(txs_without_fee_link) - len(fallback_linked)
    if unresolved_fee_links > 0:
        if journal_status != "loaded":
            warnings.append("fee matching incomplete because wallet journal snapshot is unavailable")
        elif bool(wallet_meta.get("journal_history_truncated", False)):
            warnings.append("fee matching incomplete because wallet journal history is truncated")
        else:
            warnings.append("fee matching incomplete due to missing wallet journal refs")

    quality = "not_applicable"
    if journal_status != "loaded" and not journal_entries:
        quality = "unavailable"
    elif fallback_uncertain:
        quality = "uncertain"
    elif not txs_without_fee_link:
        quality = "exact"
    elif fallback_linked and not exact_fee_tx_ids and len(fallback_linked) == len(txs_without_fee_link):
        quality = "fallback"
    elif exact_fee_tx_ids or fallback_linked:
        quality = "partial"
    else:
        quality = "partial" if journal_status == "loaded" else "unavailable"

    return {
        "linked_entries": linked,
        "fee_estimate": float(fee_estimate),
        "quality": quality,
        "warnings": warnings,
    }


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


def _reconciliation_status(
    entry: dict,
    *,
    wallet_available: bool,
    transactions_available: bool,
    history_covers_entry: bool,
    matched_buy_qty: float,
    matched_sell_qty: float,
    match_confidence: float,
    ambiguous_ids: set[int],
) -> str:
    manual_buy = _as_float(entry.get("actual_buy_qty", 0.0))
    manual_sell = _as_float(entry.get("actual_sell_qty", 0.0))
    if not wallet_available or not transactions_available:
        return "wallet_unavailable"
    if matched_buy_qty <= 0.0 and matched_sell_qty <= 0.0:
        if ambiguous_ids or not history_covers_entry:
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
    context_source: str = "wallet",
) -> dict:
    base_entries = [dict(entry or {}) for entry in list(entries or []) if isinstance(entry, dict)]
    wallet = dict(wallet_snapshot or {}) if isinstance(wallet_snapshot, dict) else {}
    transactions = _normalize_wallet_transactions(wallet)
    wallet_journal = _normalize_wallet_journal(wallet)
    wallet_meta = _wallet_snapshot_meta(wallet, transactions, wallet_journal)

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
    fee_match_qualities: list[str] = []
    entry_quality_warnings: list[str] = []

    for entry in base_entries:
        entry_id = str(entry.get("journal_entry_id", "") or "")
        matched_txs = list(assigned_by_entry.get(entry_id, []) or [])
        ambiguous_ids = set(ambiguous_by_entry.get(entry_id, set()) or set())
        buy_txs = [tx for tx in matched_txs if str(tx.get("direction", "")) == "buy"]
        sell_txs = [tx for tx in matched_txs if str(tx.get("direction", "")) == "sell"]
        fee_match = _linked_journal_entries(wallet_journal, matched_txs, wallet_meta=wallet_meta)
        linked_journal = list(fee_match.get("linked_entries", []) or [])
        fee_estimate = float(fee_match.get("fee_estimate", 0.0) or 0.0)
        fee_match_quality = str(fee_match.get("quality", "not_applicable") or "not_applicable")
        fee_match_warnings = [str(w) for w in list(fee_match.get("warnings", []) or []) if str(w).strip()]
        matched_journal_ids.update(_as_int(item.get("journal_id", 0)) for item in linked_journal)
        if fee_match_quality and fee_match_quality != "not_applicable":
            fee_match_qualities.append(fee_match_quality)
        entry_quality_warnings.extend(fee_match_warnings)

        matched_buy_qty = sum(_as_float(tx.get("quantity", 0.0)) for tx in buy_txs)
        matched_sell_qty = sum(_as_float(tx.get("quantity", 0.0)) for tx in sell_txs)
        matched_buy_value = sum(_as_float(tx.get("total_value", 0.0)) for tx in buy_txs)
        matched_sell_value = sum(_as_float(tx.get("total_value", 0.0)) for tx in sell_txs)
        match_confidence = _match_confidence(matched_txs, ambiguous_ids)
        realized_profit_net = matched_sell_value - matched_buy_value - fee_estimate
        first_buy_dt = min((tx.get("dt") for tx in buy_txs if tx.get("dt") is not None), default=None)
        last_sell_dt = max((tx.get("dt") for tx in sell_txs if tx.get("dt") is not None), default=None)
        history_covers_entry = _entry_history_is_covered(entry, wallet_meta)
        status = _reconciliation_status(
            entry,
            wallet_available=bool(wallet_meta.get("wallet_available", False)),
            transactions_available=str(wallet_meta.get("transactions_status", "unknown")) == "loaded",
            history_covers_entry=history_covers_entry,
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
        if fee_match_quality and fee_match_quality != "not_applicable":
            reason_parts.append(f"fee:{fee_match_quality}")
        top_reason = ""
        if matched_txs:
            tx_reasons = [str(tx.get("_match_reason", "") or "").strip() for tx in matched_txs if str(tx.get("_match_reason", "")).strip()]
            if tx_reasons:
                top_reason = tx_reasons[0]
        if top_reason:
            reason_parts.append(top_reason)
        if ambiguous_ids:
            reason_parts.append(f"ambiguous:{len(ambiguous_ids)}")
        if not history_covers_entry and bool(wallet_meta.get("transactions_history_truncated", False)):
            reason_parts.append("wallet transaction window does not cover this entry")
        if bool(wallet_meta.get("history_truncated", False)):
            reason_parts.append("wallet history truncated")
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
                "fee_match_quality": fee_match_quality,
                "wallet_snapshot_age_sec": (
                    float(wallet_meta.get("age_sec")) if wallet_meta.get("age_sec") is not None else -1.0
                ),
                "wallet_data_freshness": str(wallet_meta.get("data_freshness", "unknown") or "unknown"),
                "wallet_history_quality": str(wallet_meta.get("history_quality", "missing") or "missing"),
                "wallet_history_truncated": bool(wallet_meta.get("history_truncated", False)),
                "wallet_transactions_pages_loaded": int(wallet_meta.get("transactions_pages_loaded", 0) or 0),
                "wallet_journal_pages_loaded": int(wallet_meta.get("journal_pages_loaded", 0) or 0),
                "reconciliation_basis": "",
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

    applicable_fee_qualities = sorted({quality for quality in fee_match_qualities if quality and quality != "not_applicable"})
    if not applicable_fee_qualities:
        fee_match_quality = "not_applicable"
    elif len(applicable_fee_qualities) == 1:
        fee_match_quality = applicable_fee_qualities[0]
    else:
        fee_match_quality = "mixed"

    reconciliation_basis_suffix = "full_window"
    if not bool(wallet_meta.get("wallet_available", False)):
        reconciliation_basis_suffix = "unavailable"
    elif str(wallet_meta.get("transactions_status", "unknown")) != "loaded":
        reconciliation_basis_suffix = "partial_snapshot"
    elif bool(wallet_meta.get("history_truncated", False)):
        reconciliation_basis_suffix = "truncated_window"
    elif str(wallet_meta.get("history_quality", "missing")) == "stale":
        reconciliation_basis_suffix = "stale_snapshot"
    elif str(wallet_meta.get("journal_status", "unknown")) != "loaded":
        reconciliation_basis_suffix = "partial_snapshot"
    basis_prefix = str(context_source or "wallet").strip().lower() or "wallet"
    reconciliation_basis = f"{basis_prefix}:{reconciliation_basis_suffix}"

    data_quality_warnings: list[str] = []
    if str(wallet_meta.get("data_freshness", "unknown")) == "stale":
        age_sec = wallet_meta.get("age_sec")
        if age_sec is not None:
            data_quality_warnings.append(f"wallet snapshot stale ({float(age_sec) / 3600.0:.1f}h old)")
        else:
            data_quality_warnings.append("wallet snapshot stale")
    if bool(wallet_meta.get("history_truncated", False)):
        data_quality_warnings.append("wallet history truncated by page limit")
    if bool(wallet_meta.get("transactions_history_truncated", False)) and wallet_meta.get("transactions_oldest_dt") is not None:
        data_quality_warnings.append(
            f"reconciliation based on limited transaction window since {_to_iso(wallet_meta.get('transactions_oldest_dt'))}"
        )
    if str(wallet_meta.get("journal_status", "unknown")) != "loaded":
        data_quality_warnings.append("fee matching incomplete because wallet journal snapshot is unavailable")
    for warning in entry_quality_warnings:
        if warning not in data_quality_warnings:
            data_quality_warnings.append(warning)

    for entry in enriched_entries:
        entry["reconciliation_basis"] = reconciliation_basis

    return {
        "wallet_available": bool(wallet_meta.get("wallet_available", False)),
        "wallet_balance": _as_float(wallet.get("balance", 0.0)),
        "wallet_transaction_count": len(transactions),
        "wallet_journal_count": len(wallet_journal),
        "wallet_snapshot_age_sec": wallet_meta.get("age_sec"),
        "wallet_data_freshness": str(wallet_meta.get("data_freshness", "unknown") or "unknown"),
        "wallet_history_quality": str(wallet_meta.get("history_quality", "missing") or "missing"),
        "wallet_history_truncated": bool(wallet_meta.get("history_truncated", False)),
        "wallet_transactions_pages_loaded": int(wallet_meta.get("transactions_pages_loaded", 0) or 0),
        "wallet_transactions_total_pages": int(wallet_meta.get("transactions_total_pages", 0) or 0),
        "wallet_journal_pages_loaded": int(wallet_meta.get("journal_pages_loaded", 0) or 0),
        "wallet_journal_total_pages": int(wallet_meta.get("journal_total_pages", 0) or 0),
        "fee_match_quality": fee_match_quality,
        "reconciliation_basis": reconciliation_basis,
        "data_quality_warnings": data_quality_warnings,
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
