import time

from models import OrderLevel
from candidate_engine import build_levels
from shipping import build_jita_split_price_map, compute_jita_split_price


def normalize_replay_snapshot(raw: dict, fallback_o4t_id: int, fallback_cj6_id: int) -> dict:
    normalized = {"meta": {}, "structures": {}, "type_cache": {}}
    if not isinstance(raw, dict):
        return normalized

    if isinstance(raw.get("structures"), dict):
        normalized["meta"] = raw.get("meta", {}) if isinstance(raw.get("meta"), dict) else {}
        for sid, entry in raw.get("structures", {}).items():
            sid_key = str(sid)
            orders = []
            if isinstance(entry, dict):
                arr = entry.get("orders", [])
                if isinstance(arr, list):
                    orders = arr
                normalized["structures"][sid_key] = {
                    "orders": orders,
                    "meta": entry.get("meta", {}) if isinstance(entry.get("meta"), dict) else {}
                }
            elif isinstance(entry, list):
                normalized["structures"][sid_key] = {"orders": entry, "meta": {}}
        tc = raw.get("type_cache", {})
        if isinstance(tc, dict):
            normalized["type_cache"] = tc
        return normalized

    o4t_id = int(raw.get("o4t_structure_id", fallback_o4t_id))
    cj6_id = int(raw.get("cj6_structure_id", fallback_cj6_id))
    o4t_orders = raw.get("o4t_orders_data", [])
    cj6_orders = raw.get("cj6_orders_data", [])
    normalized["meta"] = {"timestamp": int(raw.get("timestamp", int(time.time())))}
    normalized["structures"][str(o4t_id)] = {"orders": o4t_orders if isinstance(o4t_orders, list) else [], "meta": {}}
    normalized["structures"][str(cj6_id)] = {"orders": cj6_orders if isinstance(cj6_orders, list) else [], "meta": {}}
    tc = raw.get("type_cache", {})
    if isinstance(tc, dict):
        normalized["type_cache"] = tc
    return normalized


def make_snapshot_payload(structure_orders_by_id: dict[int, list[dict]], type_cache: dict) -> dict:
    return {
        "meta": {"timestamp": int(time.time())},
        "structures": {
            str(int(sid)): {
                "orders": orders if isinstance(orders, list) else [],
                "meta": {}
            }
            for sid, orders in structure_orders_by_id.items()
        },
        "type_cache": type_cache if isinstance(type_cache, dict) else {}
    }


__all__ = [
    "OrderLevel",
    "build_levels",
    "build_jita_split_price_map",
    "compute_jita_split_price",
    "make_snapshot_payload",
    "normalize_replay_snapshot",
]
