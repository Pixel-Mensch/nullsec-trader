from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from eve_character_client import CharacterESIError, EveCharacterClient, SSOAuthError
from local_cache import cache_record_age_sec, cached_payload, is_cache_fresh, load_cache_record, save_cache_record, utc_now_iso
from runtime_common import BASE_DIR, CHARACTER_PROFILE_PATH, CHARACTER_SSO_METADATA_PATH, CHARACTER_SSO_TOKEN_PATH


DEFAULT_CHARACTER_CONTEXT_CFG = {
    "enabled": False,
    "allow_live_sync": True,
    "allow_cache_fallback": True,
    "apply_skill_fee_overrides": True,
    "include_skills": True,
    "include_skill_queue": False,
    "include_orders": True,
    "include_wallet_balance": True,
    "include_wallet_journal": True,
    "include_wallet_transactions": True,
    "wallet_journal_max_pages": 2,
    "wallet_transactions_max_pages": 2,
    "wallet_warn_stale_after_sec": 21600,
    "profile_cache_ttl_sec": 3600,
    "show_order_exposure_in_output": True,
    "warn_if_budget_exceeds_wallet": True,
    "profile_cache_path": CHARACTER_PROFILE_PATH,
    "token_path": CHARACTER_SSO_TOKEN_PATH,
    "metadata_path": CHARACTER_SSO_METADATA_PATH,
}


def _resolve_local_path(path: str, default_path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return str(default_path)
    if os.path.isabs(text):
        return text
    return os.path.join(BASE_DIR, text)


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _snapshot_age_sec(snapshot: dict, *, now: datetime | None = None) -> float | None:
    snap = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
    snap_dt = _parse_dt(snap.get("snapshot_at", snap.get("last_successful_sync", "")))
    if snap_dt is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - snap_dt).total_seconds())


def _wallet_data_freshness(snapshot: dict, *, now: datetime | None = None) -> str:
    age_sec = _snapshot_age_sec(snapshot, now=now)
    if age_sec is None:
        return "unknown"
    try:
        stale_after_sec = max(0, int(dict(snapshot or {}).get("warn_stale_after_sec", 21600) or 0))
    except Exception:
        stale_after_sec = 21600
    if stale_after_sec > 0 and age_sec > float(stale_after_sec):
        return "stale"
    return "fresh"


def _wallet_history_quality(snapshot: dict, *, now: datetime | None = None) -> str:
    snap = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
    if not snap:
        return "missing"
    if bool(snap.get("history_truncated", False)):
        return "truncated"
    journal_status = str(snap.get("journal_status", "unknown") or "unknown").strip().lower()
    transactions_status = str(snap.get("transactions_status", "unknown") or "unknown").strip().lower()
    if journal_status in {"disabled", "error", "unknown"} or transactions_status in {"disabled", "error", "unknown"}:
        return "partial"
    freshness = _wallet_data_freshness(snap, now=now)
    if freshness == "stale":
        return "stale"
    return "full"


def _wallet_window_bounds(rows: list[dict], keys: tuple[str, ...]) -> tuple[str, str]:
    dts: list[datetime] = []
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        for key in keys:
            dt = _parse_dt(row.get(key))
            if dt is not None:
                dts.append(dt)
                break
    if not dts:
        return "", ""
    return _to_iso(min(dts)), _to_iso(max(dts))


def _coerce_wallet_page_result(value: object) -> tuple[list[dict], dict]:
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], list)
        and isinstance(value[1], dict)
    ):
        return list(value[0]), dict(value[1])
    return list(value or []), {}


def resolve_character_context_cfg(cfg: dict | None) -> dict:
    out = dict(DEFAULT_CHARACTER_CONTEXT_CFG)
    raw = cfg.get("character_context", {}) if isinstance(cfg, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    for key in DEFAULT_CHARACTER_CONTEXT_CFG:
        if key in raw:
            out[key] = raw[key]
    out["enabled"] = bool(out.get("enabled", False))
    out["allow_live_sync"] = bool(out.get("allow_live_sync", True))
    out["allow_cache_fallback"] = bool(out.get("allow_cache_fallback", True))
    out["apply_skill_fee_overrides"] = bool(out.get("apply_skill_fee_overrides", True))
    out["include_skills"] = bool(out.get("include_skills", True))
    out["include_skill_queue"] = bool(out.get("include_skill_queue", False))
    out["include_orders"] = bool(out.get("include_orders", True))
    out["include_wallet_balance"] = bool(out.get("include_wallet_balance", True))
    out["include_wallet_journal"] = bool(out.get("include_wallet_journal", True))
    out["include_wallet_transactions"] = bool(out.get("include_wallet_transactions", True))
    out["show_order_exposure_in_output"] = bool(out.get("show_order_exposure_in_output", True))
    out["warn_if_budget_exceeds_wallet"] = bool(out.get("warn_if_budget_exceeds_wallet", True))
    try:
        out["wallet_journal_max_pages"] = max(1, int(out.get("wallet_journal_max_pages", 2) or 2))
    except Exception:
        out["wallet_journal_max_pages"] = 2
    try:
        out["wallet_transactions_max_pages"] = max(1, int(out.get("wallet_transactions_max_pages", 2) or 2))
    except Exception:
        out["wallet_transactions_max_pages"] = 2
    try:
        out["wallet_warn_stale_after_sec"] = max(0, int(out.get("wallet_warn_stale_after_sec", 21600) or 0))
    except Exception:
        out["wallet_warn_stale_after_sec"] = 21600
    try:
        out["profile_cache_ttl_sec"] = max(0, int(out.get("profile_cache_ttl_sec", 3600) or 0))
    except Exception:
        out["profile_cache_ttl_sec"] = 3600
    out["profile_cache_path"] = _resolve_local_path(str(out.get("profile_cache_path", "")), CHARACTER_PROFILE_PATH)
    out["token_path"] = _resolve_local_path(str(out.get("token_path", "")), CHARACTER_SSO_TOKEN_PATH)
    out["metadata_path"] = _resolve_local_path(str(out.get("metadata_path", "")), CHARACTER_SSO_METADATA_PATH)
    return out


def requested_character_scopes(cfg_or_context_cfg: dict | None) -> list[str]:
    if not isinstance(cfg_or_context_cfg, dict):
        resolved = dict(DEFAULT_CHARACTER_CONTEXT_CFG)
    elif "character_context" in cfg_or_context_cfg or "esi" in cfg_or_context_cfg:
        resolved = resolve_character_context_cfg(cfg_or_context_cfg)
    else:
        resolved = dict(DEFAULT_CHARACTER_CONTEXT_CFG)
        resolved.update(cfg_or_context_cfg)
    scopes: list[str] = []
    if bool(resolved.get("include_skills", True)) or bool(resolved.get("apply_skill_fee_overrides", True)):
        scopes.append("esi-skills.read_skills.v1")
    if bool(resolved.get("include_skill_queue", False)):
        scopes.append("esi-skills.read_skillqueue.v1")
    if bool(resolved.get("include_orders", True)) or bool(resolved.get("show_order_exposure_in_output", True)):
        scopes.append("esi-markets.read_character_orders.v1")
    if (
        bool(resolved.get("include_wallet_balance", True))
        or bool(resolved.get("include_wallet_journal", True))
        or bool(resolved.get("include_wallet_transactions", True))
        or bool(resolved.get("warn_if_budget_exceeds_wallet", True))
    ):
        scopes.append("esi-wallet.read_character_wallet.v1")
    seen = set()
    out: list[str] = []
    for scope in scopes:
        if scope in seen:
            continue
        seen.add(scope)
        out.append(scope)
    return out


def _norm_name(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _fee_skill_key_for_name(name: str) -> str:
    token = _norm_name(name)
    mapping = {
        "accounting": "accounting",
        "brokerrelations": "broker_relations",
        "advancedbrokerrelations": "advanced_broker_relations",
    }
    return str(mapping.get(token, "") or "")


def _map_skills_snapshot(skills_payload: dict, skill_names: dict[int, str]) -> dict:
    if not isinstance(skills_payload, dict):
        return {"skills": [], "fee_skills": {}}
    raw_skills = list(skills_payload.get("skills", []) or [])
    mapped: list[dict] = []
    fee_skills: dict[str, int] = {}
    for raw in raw_skills:
        if not isinstance(raw, dict):
            continue
        try:
            skill_id = int(raw.get("skill_id", 0) or 0)
        except Exception:
            skill_id = 0
        if skill_id <= 0:
            continue
        name = str(skill_names.get(skill_id, "") or "")
        try:
            active_level = int(raw.get("active_skill_level", raw.get("trained_skill_level", 0)) or 0)
        except Exception:
            active_level = 0
        entry = {
            "skill_id": int(skill_id),
            "name": name,
            "active_skill_level": int(max(0, min(5, active_level))),
            "trained_skill_level": int(max(0, min(5, int(raw.get("trained_skill_level", active_level) or active_level)))),
            "skillpoints_in_skill": int(raw.get("skillpoints_in_skill", 0) or 0),
        }
        mapped.append(entry)
        key = _fee_skill_key_for_name(name)
        if key:
            fee_skills[key] = int(entry["active_skill_level"])
    mapped.sort(key=lambda item: (str(item.get("name", "") or ""), int(item.get("skill_id", 0) or 0)))
    return {
        "total_sp": int(skills_payload.get("total_sp", 0) or 0),
        "unallocated_sp": int(skills_payload.get("unallocated_sp", 0) or 0),
        "skills": mapped,
        "fee_skills": fee_skills,
    }


def _map_skill_queue_snapshot(queue_payload: list[dict], skill_names: dict[int, str]) -> dict:
    mapped: list[dict] = []
    for raw in list(queue_payload or []):
        if not isinstance(raw, dict):
            continue
        try:
            skill_id = int(raw.get("skill_id", 0) or 0)
        except Exception:
            skill_id = 0
        entry = dict(raw)
        if skill_id > 0 and skill_id in skill_names:
            entry["name"] = skill_names[skill_id]
        mapped.append(entry)
    return {"entries": mapped, "count": len(mapped)}


def _map_open_orders_snapshot(orders: list[dict], type_names: dict[int, str]) -> dict:
    by_type: dict[str, dict] = {}
    buy_order_count = 0
    sell_order_count = 0
    buy_isk_committed = 0.0
    sell_gross_isk = 0.0
    locations = set()
    for raw in list(orders or []):
        if not isinstance(raw, dict):
            continue
        try:
            type_id = int(raw.get("type_id", 0) or 0)
        except Exception:
            type_id = 0
        if type_id <= 0:
            continue
        name = str(type_names.get(type_id, raw.get("type_name", f"type_{type_id}")) or f"type_{type_id}")
        is_buy = bool(raw.get("is_buy_order", False))
        try:
            volume_remain = int(raw.get("volume_remain", 0) or 0)
        except Exception:
            volume_remain = 0
        try:
            price = float(raw.get("price", 0.0) or 0.0)
        except Exception:
            price = 0.0
        try:
            location_id = int(raw.get("location_id", 0) or 0)
        except Exception:
            location_id = 0
        if location_id > 0:
            locations.add(location_id)
        rec = by_type.setdefault(
            str(type_id),
            {
                "type_id": int(type_id),
                "name": name,
                "open_order_count": 0,
                "buy_order_count": 0,
                "sell_order_count": 0,
                "buy_units": 0,
                "sell_units": 0,
                "buy_isk_committed": 0.0,
                "sell_gross_isk": 0.0,
                "location_ids": set(),
            },
        )
        rec["open_order_count"] = int(rec.get("open_order_count", 0) or 0) + 1
        rec["location_ids"].add(location_id)
        if is_buy:
            buy_order_count += 1
            rec["buy_order_count"] = int(rec.get("buy_order_count", 0) or 0) + 1
            rec["buy_units"] = int(rec.get("buy_units", 0) or 0) + int(max(0, volume_remain))
            committed = max(0.0, price) * float(max(0, volume_remain))
            rec["buy_isk_committed"] = float(rec.get("buy_isk_committed", 0.0) or 0.0) + committed
            buy_isk_committed += committed
        else:
            sell_order_count += 1
            rec["sell_order_count"] = int(rec.get("sell_order_count", 0) or 0) + 1
            rec["sell_units"] = int(rec.get("sell_units", 0) or 0) + int(max(0, volume_remain))
            sell_value = max(0.0, price) * float(max(0, volume_remain))
            rec["sell_gross_isk"] = float(rec.get("sell_gross_isk", 0.0) or 0.0) + sell_value
            sell_gross_isk += sell_value
    top_types: list[dict] = []
    for rec in by_type.values():
        rec["location_ids"] = sorted(int(x) for x in rec.get("location_ids", set()) if int(x) > 0)
        top_types.append(dict(rec))
    top_types.sort(
        key=lambda item: (
            -int(item.get("open_order_count", 0) or 0),
            -float(item.get("buy_isk_committed", 0.0) or 0.0),
            -float(item.get("sell_gross_isk", 0.0) or 0.0),
            str(item.get("name", "") or ""),
        )
    )
    return {
        "count": len(list(orders or [])),
        "buy_order_count": int(buy_order_count),
        "sell_order_count": int(sell_order_count),
        "buy_isk_committed": float(buy_isk_committed),
        "sell_gross_isk": float(sell_gross_isk),
        "markets": sorted(int(x) for x in locations if int(x) > 0),
        "by_type": by_type,
        "top_types": top_types[:20],
        "orders": list(orders or []),
    }


def _map_wallet_snapshot(
    balance: float,
    journal: list[dict],
    transactions: list[dict],
    *,
    journal_meta: dict | None = None,
    transactions_meta: dict | None = None,
    snapshot_at: str | None = None,
    balance_requested: bool = True,
    journal_status: str = "loaded",
    transactions_status: str = "loaded",
    warn_stale_after_sec: int = 21600,
) -> dict:
    journal_rows = list(journal or [])
    transaction_rows = list(transactions or [])
    journal_meta = dict(journal_meta or {})
    transactions_meta = dict(transactions_meta or {})
    journal_oldest_at, journal_newest_at = _wallet_window_bounds(journal_rows, ("date", "created_at"))
    transactions_oldest_at, transactions_newest_at = _wallet_window_bounds(
        transaction_rows,
        ("date", "transaction_date", "created_at"),
    )
    journal_pages_loaded = int(journal_meta.get("pages_loaded", 1 if journal_status == "loaded" else 0) or 0)
    journal_total_pages = int(journal_meta.get("total_pages", journal_pages_loaded) or 0)
    journal_page_limit = int(journal_meta.get("page_limit", 0) or 0)
    journal_history_truncated = bool(journal_meta.get("history_truncated", False))
    transactions_pages_loaded = int(
        transactions_meta.get("pages_loaded", 1 if transactions_status == "loaded" else 0) or 0
    )
    transactions_total_pages = int(transactions_meta.get("total_pages", transactions_pages_loaded) or 0)
    transactions_page_limit = int(transactions_meta.get("page_limit", 0) or 0)
    transactions_history_truncated = bool(transactions_meta.get("history_truncated", False))
    return {
        "snapshot_at": str(snapshot_at or utc_now_iso()),
        "warn_stale_after_sec": int(max(0, warn_stale_after_sec)),
        "balance": float(balance or 0.0),
        "balance_requested": bool(balance_requested),
        "journal_status": str(journal_status or "unknown"),
        "transactions_status": str(transactions_status or "unknown"),
        "journal_count": len(journal_rows),
        "transactions_count": len(transaction_rows),
        "journal_pages_loaded": int(journal_pages_loaded),
        "journal_total_pages": int(journal_total_pages),
        "journal_page_limit": int(journal_page_limit),
        "journal_history_truncated": bool(journal_history_truncated),
        "journal_oldest_at": str(journal_oldest_at),
        "journal_newest_at": str(journal_newest_at),
        "transactions_pages_loaded": int(transactions_pages_loaded),
        "transactions_total_pages": int(transactions_total_pages),
        "transactions_page_limit": int(transactions_page_limit),
        "transactions_history_truncated": bool(transactions_history_truncated),
        "transactions_oldest_at": str(transactions_oldest_at),
        "transactions_newest_at": str(transactions_newest_at),
        "history_truncated": bool(journal_history_truncated or transactions_history_truncated),
        "journal_entries": journal_rows,
        "transactions": transaction_rows,
    }


def build_character_profile(
    *,
    identity: dict,
    public_character: dict | None,
    skills_snapshot: dict | None,
    skill_queue_snapshot: dict | None,
    open_orders_snapshot: dict | None,
    wallet_snapshot: dict | None,
) -> dict:
    return {
        "character_id": int(identity.get("character_id", 0) or 0),
        "character_name": str(identity.get("character_name", "") or "").strip(),
        "last_successful_sync": utc_now_iso(),
        "loaded_scopes": list(identity.get("loaded_scopes", identity.get("scopes", [])) or []),
        "token_expires_at": int(identity.get("token_expires_at", 0) or 0),
        "public_character": dict(public_character or {}),
        "skills_snapshot": dict(skills_snapshot or {}),
        "skill_queue_snapshot": dict(skill_queue_snapshot or {}),
        "open_orders_snapshot": dict(open_orders_snapshot or {}),
        "wallet_snapshot": dict(wallet_snapshot or {}),
    }


def _build_character_context(
    profile: dict | None,
    *,
    source: str,
    enabled: bool,
    warnings: list[str] | None = None,
    cache_age_sec: float | None = None,
) -> dict:
    prof = dict(profile or {})
    skills_snapshot = prof.get("skills_snapshot", {}) if isinstance(prof.get("skills_snapshot", {}), dict) else {}
    orders_snapshot = prof.get("open_orders_snapshot", {}) if isinstance(prof.get("open_orders_snapshot", {}), dict) else {}
    wallet_snapshot = prof.get("wallet_snapshot", {}) if isinstance(prof.get("wallet_snapshot", {}), dict) else {}
    available = bool(prof.get("character_id", 0) or prof.get("character_name", ""))
    return {
        "enabled": bool(enabled),
        "available": bool(available),
        "source": str(source or "default"),
        "warnings": [str(w) for w in list(warnings or []) if str(w).strip()],
        "profile": prof,
        "character_id": int(prof.get("character_id", 0) or 0),
        "character_name": str(prof.get("character_name", "") or "").strip(),
        "loaded_scopes": list(prof.get("loaded_scopes", []) or []),
        "last_successful_sync": str(prof.get("last_successful_sync", "") or "").strip(),
        "fee_skill_overrides": dict(skills_snapshot.get("fee_skills", {}) or {}),
        "open_orders_by_type": dict(orders_snapshot.get("by_type", {}) or {}),
        "open_orders_count": int(orders_snapshot.get("count", 0) or 0),
        "wallet_balance": float(wallet_snapshot.get("balance", 0.0) or 0.0),
        "cache_age_sec": cache_age_sec,
    }


def _load_cached_profile_context(cfg: dict, *, enabled: bool, warning: str = "") -> dict:
    char_cfg = resolve_character_context_cfg(cfg)
    record = load_cache_record(char_cfg["profile_cache_path"])
    profile = cached_payload(record, {})
    if not isinstance(profile, dict) or not profile:
        return _build_character_context(None, source="default", enabled=enabled, warnings=[warning] if warning else [])
    warnings = [warning] if warning else []
    age = cache_record_age_sec(record)
    return _build_character_context(profile, source="cache", enabled=enabled, warnings=warnings, cache_age_sec=age)


def sync_character_profile(cfg: dict, *, allow_login: bool = True, client: EveCharacterClient | None = None) -> dict:
    char_cfg = resolve_character_context_cfg(cfg)
    live_client = client or EveCharacterClient(cfg)
    scopes = requested_character_scopes(char_cfg)
    warnings: list[str] = []
    identity = live_client.get_identity(scopes, allow_login=allow_login)
    character_id = int(identity.get("character_id", 0) or 0)
    if character_id <= 0:
        raise CharacterESIError("Konnte character_id aus dem EVE SSO Token nicht ableiten.")

    public_character: dict = {}
    try:
        public_character = live_client.get_public_character(character_id)
    except CharacterESIError as exc:
        warnings.append(f"public_character unavailable: {exc}")

    skills_snapshot: dict = {}
    skill_names: dict[int, str] = {}
    if bool(char_cfg.get("include_skills", True)) or bool(char_cfg.get("apply_skill_fee_overrides", True)):
        skills_payload = live_client.get_skills(character_id, allow_login=allow_login)
        skill_ids = []
        for entry in list(skills_payload.get("skills", []) or []):
            if not isinstance(entry, dict):
                continue
            try:
                sid = int(entry.get("skill_id", 0) or 0)
            except Exception:
                sid = 0
            if sid > 0:
                skill_ids.append(sid)
        if skill_ids:
            try:
                skill_names = live_client.resolve_names(skill_ids)
            except CharacterESIError as exc:
                warnings.append(f"skill name resolution unavailable: {exc}")
        skills_snapshot = _map_skills_snapshot(skills_payload, skill_names)

    skill_queue_snapshot: dict = {}
    if bool(char_cfg.get("include_skill_queue", False)):
        try:
            queue_payload = live_client.get_skill_queue(character_id, allow_login=allow_login)
            queue_skill_ids = []
            for entry in list(queue_payload or []):
                if not isinstance(entry, dict):
                    continue
                try:
                    sid = int(entry.get("skill_id", 0) or 0)
                except Exception:
                    sid = 0
                if sid > 0 and sid not in skill_names:
                    queue_skill_ids.append(sid)
            if queue_skill_ids:
                try:
                    skill_names.update(live_client.resolve_names(queue_skill_ids))
                except CharacterESIError as exc:
                    warnings.append(f"skill queue name resolution unavailable: {exc}")
            skill_queue_snapshot = _map_skill_queue_snapshot(queue_payload, skill_names)
        except CharacterESIError as exc:
            warnings.append(f"skill queue unavailable: {exc}")

    open_orders_snapshot: dict = {}
    if bool(char_cfg.get("include_orders", True)) or bool(char_cfg.get("show_order_exposure_in_output", True)):
        try:
            orders = live_client.get_open_orders(character_id, allow_login=allow_login)
            type_ids = []
            for order in list(orders or []):
                if not isinstance(order, dict):
                    continue
                try:
                    tid = int(order.get("type_id", 0) or 0)
                except Exception:
                    tid = 0
                if tid > 0:
                    type_ids.append(tid)
            type_names = live_client.resolve_names(type_ids) if type_ids else {}
            open_orders_snapshot = _map_open_orders_snapshot(orders, type_names)
        except CharacterESIError as exc:
            warnings.append(f"open orders unavailable: {exc}")

    wallet_snapshot: dict = {}
    if (
        bool(char_cfg.get("include_wallet_balance", True))
        or bool(char_cfg.get("include_wallet_journal", True))
        or bool(char_cfg.get("include_wallet_transactions", True))
    ):
        balance = 0.0
        balance_status = "disabled"
        journal: list[dict] = []
        journal_meta: dict = {}
        journal_status = "disabled"
        transactions: list[dict] = []
        transactions_meta: dict = {}
        transactions_status = "disabled"
        snapshot_at = utc_now_iso()
        try:
            if bool(char_cfg.get("include_wallet_balance", True)):
                balance_status = "loaded"
                balance = live_client.get_wallet_balance(character_id, allow_login=allow_login)
        except CharacterESIError as exc:
            balance_status = "error"
            warnings.append(f"wallet balance unavailable: {exc}")
        try:
            if bool(char_cfg.get("include_wallet_journal", True)):
                journal_status = "loaded"
                try:
                    journal_result = live_client.get_wallet_journal(
                        character_id,
                        max_pages=int(char_cfg.get("wallet_journal_max_pages", 2) or 2),
                        allow_login=allow_login,
                        with_meta=True,
                    )
                except TypeError:
                    journal_result = live_client.get_wallet_journal(
                        character_id,
                        max_pages=int(char_cfg.get("wallet_journal_max_pages", 2) or 2),
                        allow_login=allow_login,
                    )
                journal, journal_meta = _coerce_wallet_page_result(journal_result)
        except CharacterESIError as exc:
            journal_status = "error"
            warnings.append(f"wallet journal unavailable: {exc}")
        try:
            if bool(char_cfg.get("include_wallet_transactions", True)):
                transactions_status = "loaded"
                try:
                    transaction_result = live_client.get_wallet_transactions(
                        character_id,
                        max_pages=int(char_cfg.get("wallet_transactions_max_pages", 2) or 2),
                        allow_login=allow_login,
                        with_meta=True,
                    )
                except TypeError:
                    transaction_result = live_client.get_wallet_transactions(
                        character_id,
                        max_pages=int(char_cfg.get("wallet_transactions_max_pages", 2) or 2),
                        allow_login=allow_login,
                    )
                transactions, transactions_meta = _coerce_wallet_page_result(transaction_result)
        except CharacterESIError as exc:
            transactions_status = "error"
            warnings.append(f"wallet transactions unavailable: {exc}")
        wallet_snapshot = _map_wallet_snapshot(
            balance,
            journal,
            transactions,
            journal_meta=journal_meta,
            transactions_meta=transactions_meta,
            snapshot_at=snapshot_at,
            balance_requested=bool(char_cfg.get("include_wallet_balance", True)),
            journal_status=journal_status,
            transactions_status=transactions_status,
            warn_stale_after_sec=int(char_cfg.get("wallet_warn_stale_after_sec", 21600) or 21600),
        )
        wallet_snapshot["balance_status"] = str(balance_status)

    identity["loaded_scopes"] = list(identity.get("loaded_scopes", identity.get("scopes", scopes)) or scopes)
    profile = build_character_profile(
        identity=identity,
        public_character=public_character,
        skills_snapshot=skills_snapshot,
        skill_queue_snapshot=skill_queue_snapshot,
        open_orders_snapshot=open_orders_snapshot,
        wallet_snapshot=wallet_snapshot,
    )
    save_cache_record(
        char_cfg["profile_cache_path"],
        profile,
        source="live",
        metadata={"scopes": list(identity.get("loaded_scopes", scopes) or scopes)},
    )
    return _build_character_context(profile, source="live", enabled=True, warnings=warnings, cache_age_sec=0.0)


def resolve_character_context(
    cfg: dict,
    *,
    replay_enabled: bool = False,
    allow_live: bool = True,
    client: EveCharacterClient | None = None,
) -> dict:
    char_cfg = resolve_character_context_cfg(cfg)
    if not bool(char_cfg.get("enabled", False)):
        return _build_character_context(None, source="disabled", enabled=False, warnings=[])

    cache_record = load_cache_record(char_cfg["profile_cache_path"])
    cache_payload = cached_payload(cache_record, {})
    cache_available = isinstance(cache_payload, dict) and bool(cache_payload)
    cache_fresh = cache_available and is_cache_fresh(cache_record, char_cfg.get("profile_cache_ttl_sec", 3600))

    if cache_fresh and bool(char_cfg.get("allow_cache_fallback", True)):
        return _build_character_context(
            cache_payload,
            source="cache",
            enabled=True,
            warnings=[],
            cache_age_sec=cache_record_age_sec(cache_record),
        )

    client_id = str(((cfg or {}).get("esi", {}) if isinstance((cfg or {}).get("esi", {}), dict) else {}).get("client_id", "") or "").strip()
    live_allowed = bool(allow_live and not replay_enabled and char_cfg.get("allow_live_sync", True) and client_id)
    if live_allowed:
        try:
            return sync_character_profile(cfg, allow_login=True, client=client)
        except (CharacterESIError, SSOAuthError, RuntimeError) as exc:
            if cache_available and bool(char_cfg.get("allow_cache_fallback", True)):
                return _build_character_context(
                    cache_payload,
                    source="cache",
                    enabled=True,
                    warnings=[f"character live sync failed, using cache: {exc}"],
                    cache_age_sec=cache_record_age_sec(cache_record),
                )
            return _build_character_context(
                None,
                source="default",
                enabled=True,
                warnings=[f"character live sync unavailable: {exc}"],
            )

    if cache_available and bool(char_cfg.get("allow_cache_fallback", True)):
        warning = "replay/offline mode: character context loaded from cache" if replay_enabled else "live sync unavailable: using cached character profile"
        return _build_character_context(
            cache_payload,
            source="cache",
            enabled=True,
            warnings=[warning],
            cache_age_sec=cache_record_age_sec(cache_record),
        )

    if replay_enabled:
        return _build_character_context(None, source="default", enabled=True, warnings=["replay/offline mode without character cache"])
    return _build_character_context(None, source="default", enabled=True, warnings=["character context unavailable; using generic defaults"])


def apply_character_fee_overrides(fees_cfg: dict, context: dict) -> tuple[dict, dict]:
    base = dict(fees_cfg or {})
    meta = {"applied": False, "source": str(context.get("source", "default") or "default"), "skills": {}}
    if not bool(context.get("available", False)):
        return base, meta
    overrides = dict(context.get("fee_skill_overrides", {}) or {})
    if not overrides:
        return base, meta
    skills_cfg = base.get("skills", {})
    merged = dict(skills_cfg or {}) if isinstance(skills_cfg, dict) else {}
    applied = False
    for key in ("accounting", "broker_relations", "advanced_broker_relations"):
        if key not in overrides:
            continue
        merged[key] = int(overrides[key])
        applied = True
    if applied:
        base["skills"] = merged
        meta["applied"] = True
        meta["skills"] = merged
    return base, meta


def build_character_context_summary(context: dict, *, budget_isk: float | int | None = None) -> dict:
    profile = context.get("profile", {}) if isinstance(context.get("profile", {}), dict) else {}
    orders_snapshot = profile.get("open_orders_snapshot", {}) if isinstance(profile.get("open_orders_snapshot", {}), dict) else {}
    wallet_snapshot = profile.get("wallet_snapshot", {}) if isinstance(profile.get("wallet_snapshot", {}), dict) else {}
    skills_snapshot = profile.get("skills_snapshot", {}) if isinstance(profile.get("skills_snapshot", {}), dict) else {}
    wallet_balance = float(wallet_snapshot.get("balance", 0.0) or 0.0)
    wallet_snapshot_age_sec = _snapshot_age_sec(wallet_snapshot)
    wallet_data_freshness = _wallet_data_freshness(wallet_snapshot)
    wallet_history_quality = _wallet_history_quality(wallet_snapshot)
    budget_value = float(budget_isk or 0.0)
    summary = {
        "enabled": bool(context.get("enabled", False)),
        "available": bool(context.get("available", False)),
        "source": str(context.get("source", "default") or "default"),
        "character_id": int(profile.get("character_id", 0) or 0),
        "character_name": str(profile.get("character_name", "") or "").strip(),
        "last_successful_sync": str(profile.get("last_successful_sync", "") or "").strip(),
        "loaded_scopes": list(profile.get("loaded_scopes", []) or []),
        "wallet_balance": wallet_balance,
        "wallet_journal_count": int(wallet_snapshot.get("journal_count", 0) or 0),
        "wallet_transactions_count": int(wallet_snapshot.get("transactions_count", 0) or 0),
        "wallet_snapshot_age_sec": wallet_snapshot_age_sec,
        "wallet_data_freshness": wallet_data_freshness,
        "wallet_history_quality": wallet_history_quality,
        "wallet_history_truncated": bool(wallet_snapshot.get("history_truncated", False)),
        "wallet_journal_pages_loaded": int(wallet_snapshot.get("journal_pages_loaded", 0) or 0),
        "wallet_transactions_pages_loaded": int(wallet_snapshot.get("transactions_pages_loaded", 0) or 0),
        "open_orders_count": int(orders_snapshot.get("count", 0) or 0),
        "buy_order_count": int(orders_snapshot.get("buy_order_count", 0) or 0),
        "sell_order_count": int(orders_snapshot.get("sell_order_count", 0) or 0),
        "buy_isk_committed": float(orders_snapshot.get("buy_isk_committed", 0.0) or 0.0),
        "sell_gross_isk": float(orders_snapshot.get("sell_gross_isk", 0.0) or 0.0),
        "fee_skills": dict(skills_snapshot.get("fee_skills", {}) or {}),
        "warnings": list(context.get("warnings", []) or []),
        "budget_exceeds_wallet": bool(wallet_balance > 0.0 and budget_value > wallet_balance),
        "budget_gap_isk": max(0.0, budget_value - wallet_balance) if wallet_balance > 0.0 else 0.0,
        "overlapping_pick_count": 0,
        "high_overlap_pick_count": 0,
    }
    return summary


def annotate_picks_with_character_orders(picks: list[dict], context: dict) -> tuple[int, int]:
    by_type = dict(context.get("open_orders_by_type", {}) or {})
    overlap_count = 0
    high_overlap_count = 0
    for pick in list(picks or []):
        try:
            type_id = int(pick.get("type_id", 0) or 0)
        except Exception:
            type_id = 0
        if type_id <= 0:
            continue
        exposure = by_type.get(str(type_id))
        if not isinstance(exposure, dict) or not exposure:
            continue
        overlap_count += 1
        pick["character_open_orders"] = int(exposure.get("open_order_count", 0) or 0)
        pick["character_open_buy_orders"] = int(exposure.get("buy_order_count", 0) or 0)
        pick["character_open_sell_orders"] = int(exposure.get("sell_order_count", 0) or 0)
        pick["character_open_buy_isk_committed"] = float(exposure.get("buy_isk_committed", 0.0) or 0.0)
        pick["character_open_sell_units"] = int(exposure.get("sell_units", 0) or 0)
        pick["character_open_order_locations"] = list(exposure.get("location_ids", []) or [])
        pick["character_exposure_name"] = str(exposure.get("name", "") or "")
        warning_tier = ""
        warning_text = ""
        if int(pick.get("character_open_sell_orders", 0) or 0) > 0:
            warning_tier = "high"
            warning_text = "Existing sell-order overlap for this type."
            high_overlap_count += 1
        elif int(pick.get("character_open_buy_orders", 0) or 0) > 0:
            warning_tier = "medium"
            warning_text = "Existing buy-order overlap for this type."
        elif int(pick.get("character_open_orders", 0) or 0) > 0:
            warning_tier = "medium"
            warning_text = "Existing market-order overlap for this type."
        pick["open_order_warning_tier"] = warning_tier
        pick["open_order_warning_text"] = warning_text
        pick["character_id"] = int(context.get("character_id", 0) or 0)
    return overlap_count, high_overlap_count


def attach_character_context_to_result(result: dict, context: dict, *, budget_isk: float | int | None = None) -> dict:
    summary = build_character_context_summary(context, budget_isk=budget_isk)
    picks = list(result.get("picks", []) or [])
    overlap_count, high_overlap_count = annotate_picks_with_character_orders(picks, context)
    summary["overlapping_pick_count"] = overlap_count
    summary["high_overlap_pick_count"] = high_overlap_count
    result["_character_context_summary"] = summary
    result["picks"] = picks
    return result


def character_status_lines(context: dict, *, budget_isk: float | int | None = None) -> list[str]:
    summary = build_character_context_summary(context, budget_isk=budget_isk)
    if not bool(summary.get("enabled", False)):
        return ["Character Context: DISABLED"]
    if not bool(summary.get("available", False)):
        lines = [f"Character Context: {str(summary.get('source', 'default')).upper()} (no private data)"]
        for warning in list(summary.get("warnings", []) or []):
            lines.append(f"  WARN: {warning}")
        return lines
    lines = [
        f"Character Context: {str(summary.get('source', 'default')).upper()} | "
        f"{summary.get('character_name', '')} ({int(summary.get('character_id', 0) or 0)})",
        f"  Sync: {summary.get('last_successful_sync', '')}",
        f"  Scopes: {' '.join(list(summary.get('loaded_scopes', []) or []))}",
        f"  Wallet: {float(summary.get('wallet_balance', 0.0) or 0.0):,.2f} ISK",
        (
            f"  Wallet History: {str(summary.get('wallet_data_freshness', 'unknown')).upper()} / "
            f"{str(summary.get('wallet_history_quality', 'missing')).upper()} | "
            f"tx_pages={int(summary.get('wallet_transactions_pages_loaded', 0) or 0)} | "
            f"journal_pages={int(summary.get('wallet_journal_pages_loaded', 0) or 0)}"
        ),
        f"  Orders: {int(summary.get('open_orders_count', 0) or 0)} open "
        f"(buy {int(summary.get('buy_order_count', 0) or 0)} / sell {int(summary.get('sell_order_count', 0) or 0)})",
    ]
    fee_skills = dict(summary.get("fee_skills", {}) or {})
    if fee_skills:
        lines.append(
            "  Fee Skills: "
            f"accounting={int(fee_skills.get('accounting', 0) or 0)}, "
            f"broker_relations={int(fee_skills.get('broker_relations', 0) or 0)}, "
            f"advanced_broker_relations={int(fee_skills.get('advanced_broker_relations', 0) or 0)}"
        )
    if bool(summary.get("budget_exceeds_wallet", False)):
        lines.append(f"  WARN: Budget ueber Wallet um {float(summary.get('budget_gap_isk', 0.0) or 0.0):,.2f} ISK")
    if bool(summary.get("wallet_history_truncated", False)):
        lines.append("  WARN: Wallet-Historie wurde durch das Page-Limit abgeschnitten.")
    if str(summary.get("wallet_data_freshness", "") or "").strip().lower() == "stale":
        age_sec = summary.get("wallet_snapshot_age_sec")
        if age_sec is not None:
            lines.append(f"  WARN: Wallet-Snapshot ist alt ({float(age_sec) / 3600.0:.1f}h).")
    for warning in list(summary.get("warnings", []) or []):
        lines.append(f"  WARN: {warning}")
    return lines


__all__ = [
    "DEFAULT_CHARACTER_CONTEXT_CFG",
    "apply_character_fee_overrides",
    "attach_character_context_to_result",
    "build_character_context_summary",
    "build_character_profile",
    "character_status_lines",
    "requested_character_scopes",
    "resolve_character_context",
    "resolve_character_context_cfg",
    "sync_character_profile",
]
