from __future__ import annotations
from typing import Any

from location_utils import normalize_location_label

ESIClient = Any
ReplayESIClient = Any

def _fetch_orders_for_node(
    esi,
    node: dict,
    replay_enabled: bool,
    replay_structs: dict | None,
) -> list[dict]:
    kind = str(node.get("kind", "structure"))
    node_id = int(node.get("id", 0) or 0)
    if replay_enabled:
        snap = replay_structs if isinstance(replay_structs, dict) else {}
        entry = snap.get(str(node_id), {})
        orders = entry.get("orders", []) if isinstance(entry, dict) else []
        return list(orders) if isinstance(orders, list) else []

    if kind == "location":
        location_id = int(node.get("location_id", node_id) or 0)
        region_id = int(node.get("region_id", 0) or 0)
        if location_id <= 0 or region_id <= 0:
            return []
        if normalize_location_label(str(node.get("label", ""))) == "jita":
            return list(esi.get_jita_44_orders(region_id=region_id, location_id=location_id))
        return list(esi.get_location_orders(region_id=region_id, location_id=location_id))
    return list(esi.fetch_structure_orders(node_id))

__all__ = [
    "ESIClient",
    "ReplayESIClient",
    "_fetch_orders_for_node",
]
