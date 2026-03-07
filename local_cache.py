from __future__ import annotations

import time
from datetime import datetime, timezone

from config_loader import load_json, save_json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso_ts(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return float(dt.timestamp())


def load_cache_record(path: str) -> dict:
    record = load_json(path, {})
    return dict(record) if isinstance(record, dict) else {}


def save_cache_record(
    path: str,
    payload,
    *,
    source: str = "cache",
    metadata: dict | None = None,
    saved_at: str | None = None,
) -> dict:
    record = {
        "saved_at": str(saved_at or utc_now_iso()),
        "source": str(source or "cache"),
        "metadata": dict(metadata or {}),
        "payload": payload,
    }
    save_json(path, record)
    return record


def cached_payload(record: dict, default=None):
    if not isinstance(record, dict):
        return default
    if "payload" not in record:
        return default
    return record.get("payload", default)


def cache_record_age_sec(record: dict, *, now_ts: float | None = None) -> float | None:
    if not isinstance(record, dict):
        return None
    saved_at_ts = _parse_iso_ts(record.get("saved_at"))
    if saved_at_ts is None:
        return None
    now_value = float(time.time()) if now_ts is None else float(now_ts)
    return max(0.0, now_value - saved_at_ts)


def is_cache_fresh(record: dict, ttl_sec: float | int | None, *, now_ts: float | None = None) -> bool:
    if ttl_sec is None:
        return False
    try:
        ttl_value = float(ttl_sec)
    except Exception:
        return False
    if ttl_value <= 0.0:
        return False
    age = cache_record_age_sec(record, now_ts=now_ts)
    if age is None:
        return False
    return age <= ttl_value


__all__ = [
    "cache_record_age_sec",
    "cached_payload",
    "is_cache_fresh",
    "load_cache_record",
    "save_cache_record",
    "utc_now_iso",
]
