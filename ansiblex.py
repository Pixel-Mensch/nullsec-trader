from __future__ import annotations

import heapq
from pathlib import Path

from location_utils import normalize_location_label


_DEFAULT_ANSIBLEX_FILE = "Ansis.txt"
_DEFAULT_DISTANCE_LY_PER_JUMP = 1.0
_ALLOWED_TOLL_MODES = {"none", "per_ozone", "fixed_per_jump"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _strip_inline_comment(line: str) -> str:
    text = str(line or "")
    for marker in ("#", "//"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()


def _resolve_ansiblex_file_path(file_path: str) -> Path | None:
    raw = str(file_path or "").strip()
    candidates: list[Path] = []
    if raw:
        path = Path(raw)
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(_repo_root() / path)
    file_name = Path(raw or _DEFAULT_ANSIBLEX_FILE).name.lower()
    if file_name == "ansis.txt":
        candidates.append(_repo_root() / "Ansis.txt")
        candidates.append(_repo_root() / "docs" / "Ansis.txt")
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate
    return None


def resolve_ansiblex_cfg(cfg: dict) -> dict:
    raw = cfg.get("ansiblex", {}) if isinstance(cfg, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    toll_mode = str(raw.get("toll_mode", "none") or "none").strip().lower()
    if toll_mode not in _ALLOWED_TOLL_MODES:
        toll_mode = "none"
    file_path = str(raw.get("file_path", _DEFAULT_ANSIBLEX_FILE) or _DEFAULT_ANSIBLEX_FILE).strip() or _DEFAULT_ANSIBLEX_FILE
    resolved_path = _resolve_ansiblex_file_path(file_path)
    return {
        "enabled": bool(raw.get("enabled", False)),
        "file_path": file_path,
        "resolved_file_path": str(resolved_path) if resolved_path is not None else file_path,
        "file_found": resolved_path is not None,
        "ship_mass_kg": max(0.0, float(raw.get("ship_mass_kg", 200_000_000.0) or 0.0)),
        "liquid_ozone_price_isk": max(0.0, float(raw.get("liquid_ozone_price_isk", 1_000.0) or 0.0)),
        "toll_mode": toll_mode,
        "toll_isk_per_ozone": max(0.0, float(raw.get("toll_isk_per_ozone", 0.0) or 0.0)),
        "fixed_toll_isk_per_jump": max(0.0, float(raw.get("fixed_toll_isk_per_jump", 0.0) or 0.0)),
        "distance_ly_per_jump": _DEFAULT_DISTANCE_LY_PER_JUMP,
    }


def parse_ansiblex_edge_line(line: str) -> dict | None:
    text = _strip_inline_comment(line)
    if not text:
        return None
    if "->" not in text:
        return None
    src_raw, dst_raw = [part.strip() for part in text.split("->", 1)]
    if not src_raw or not dst_raw:
        return None
    src_norm = normalize_location_label(src_raw)
    dst_norm = normalize_location_label(dst_raw)
    if not src_norm or not dst_norm or src_norm == dst_norm:
        return None
    return {
        "from_system": src_raw,
        "to_system": dst_raw,
        "from_norm": src_norm,
        "to_norm": dst_norm,
    }


def load_ansiblex_edges(file_path: str) -> list[dict]:
    resolved_path = _resolve_ansiblex_file_path(file_path)
    if resolved_path is None:
        return []
    out: list[dict] = []
    with resolved_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            edge = parse_ansiblex_edge_line(raw_line)
            if edge is None:
                continue
            edge["line_no"] = int(line_no)
            out.append(edge)
    return out


def compute_ansiblex_jump_cost(
    *,
    ship_mass_kg: float,
    liquid_ozone_price_isk: float,
    distance_ly: float,
    toll_mode: str = "none",
    toll_isk_per_ozone: float = 0.0,
    fixed_toll_isk_per_jump: float = 0.0,
) -> dict:
    mass = max(0.0, float(ship_mass_kg or 0.0))
    ozone_price = max(0.0, float(liquid_ozone_price_isk or 0.0))
    ly = max(0.0, float(distance_ly or 0.0))
    fuel_ozone = (mass * ly * 0.000003) + 50.0
    fuel_cost = fuel_ozone * ozone_price
    mode = str(toll_mode or "none").strip().lower()
    if mode == "per_ozone":
        toll_cost = fuel_ozone * max(0.0, float(toll_isk_per_ozone or 0.0))
    elif mode == "fixed_per_jump":
        toll_cost = max(0.0, float(fixed_toll_isk_per_jump or 0.0))
    else:
        toll_cost = 0.0
        mode = "none"
    return {
        "distance_ly": float(ly),
        "fuel_ozone": float(fuel_ozone),
        "fuel_cost_isk": float(fuel_cost),
        "toll_mode": mode,
        "toll_cost_isk": float(toll_cost),
        "ansiblex_logistics_cost_isk": float(fuel_cost + toll_cost),
    }


def _chain_system_entries(cfg: dict) -> list[dict]:
    chain_cfg = cfg.get("route_chain", {}) if isinstance(cfg, dict) else {}
    legs = chain_cfg.get("legs", []) if isinstance(chain_cfg, dict) else []
    if not isinstance(legs, list):
        return []
    out: list[dict] = []
    for idx, raw_leg in enumerate(legs):
        if not isinstance(raw_leg, dict):
            continue
        label = str(raw_leg.get("label", raw_leg.get("system", "")) or "").strip()
        system = str(raw_leg.get("system", label) or label).strip()
        label_norm = normalize_location_label(label)
        system_norm = normalize_location_label(system)
        if not label_norm or not system_norm:
            continue
        out.append(
            {
                "index": int(idx),
                "label": label,
                "label_norm": label_norm,
                "system": system,
                "system_norm": system_norm,
            }
        )
    return out


def _route_travel_runtime(cfg: dict) -> dict:
    cached = cfg.get("_ansiblex_runtime", {}) if isinstance(cfg, dict) else {}
    if isinstance(cached, dict) and cached.get("_ready"):
        return cached

    ansiblex_cfg = resolve_ansiblex_cfg(cfg)
    chain_entries = _chain_system_entries(cfg)
    token_to_system: dict[str, dict] = {}
    adjacency: dict[str, list[dict]] = {}

    for entry in chain_entries:
        token_to_system[str(entry["label_norm"])] = entry
        token_to_system[str(entry["system_norm"])] = entry
        adjacency.setdefault(str(entry["system_norm"]), [])

    for idx in range(len(chain_entries) - 1):
        src = chain_entries[idx]
        dst = chain_entries[idx + 1]
        adjacency.setdefault(str(src["system_norm"]), []).append(
            {
                "mode": "gate",
                "from_system": str(src["system"]),
                "to_system": str(dst["system"]),
                "to_norm": str(dst["system_norm"]),
                "distance_ly": 0.0,
                "fuel_ozone": 0.0,
                "fuel_cost_isk": 0.0,
                "toll_cost_isk": 0.0,
                "cost_isk": 0.0,
            }
        )
        adjacency.setdefault(str(dst["system_norm"]), []).append(
            {
                "mode": "gate",
                "from_system": str(dst["system"]),
                "to_system": str(src["system"]),
                "to_norm": str(src["system_norm"]),
                "distance_ly": 0.0,
                "fuel_ozone": 0.0,
                "fuel_cost_isk": 0.0,
                "toll_cost_isk": 0.0,
                "cost_isk": 0.0,
            }
        )

    edges: list[dict] = []
    if bool(ansiblex_cfg.get("enabled", False)) and bool(ansiblex_cfg.get("file_found", False)):
        edges = load_ansiblex_edges(str(ansiblex_cfg.get("resolved_file_path", "")))
        for edge in edges:
            to_norm = str(edge.get("to_norm", "") or "")
            from_norm = str(edge.get("from_norm", "") or "")
            if not from_norm or not to_norm:
                continue
            jump_cost = compute_ansiblex_jump_cost(
                ship_mass_kg=float(ansiblex_cfg.get("ship_mass_kg", 0.0) or 0.0),
                liquid_ozone_price_isk=float(ansiblex_cfg.get("liquid_ozone_price_isk", 0.0) or 0.0),
                distance_ly=float(ansiblex_cfg.get("distance_ly_per_jump", _DEFAULT_DISTANCE_LY_PER_JUMP) or _DEFAULT_DISTANCE_LY_PER_JUMP),
                toll_mode=str(ansiblex_cfg.get("toll_mode", "none") or "none"),
                toll_isk_per_ozone=float(ansiblex_cfg.get("toll_isk_per_ozone", 0.0) or 0.0),
                fixed_toll_isk_per_jump=float(ansiblex_cfg.get("fixed_toll_isk_per_jump", 0.0) or 0.0),
            )
            adjacency.setdefault(from_norm, []).append(
                {
                    "mode": "ansiblex",
                    "from_system": str(edge.get("from_system", "") or ""),
                    "to_system": str(edge.get("to_system", "") or ""),
                    "to_norm": to_norm,
                    "distance_ly": float(jump_cost.get("distance_ly", 0.0) or 0.0),
                    "fuel_ozone": float(jump_cost.get("fuel_ozone", 0.0) or 0.0),
                    "fuel_cost_isk": float(jump_cost.get("fuel_cost_isk", 0.0) or 0.0),
                    "toll_cost_isk": float(jump_cost.get("toll_cost_isk", 0.0) or 0.0),
                    "cost_isk": float(jump_cost.get("ansiblex_logistics_cost_isk", 0.0) or 0.0),
                }
            )

    runtime = {
        "_ready": True,
        "config": ansiblex_cfg,
        "chain_entries": chain_entries,
        "token_to_system": token_to_system,
        "adjacency": adjacency,
        "edges": edges,
    }
    if isinstance(cfg, dict):
        cfg["_ansiblex_runtime"] = runtime
    return runtime


def _token_entry(runtime: dict, label: str) -> dict | None:
    token = normalize_location_label(label)
    if not token:
        return None
    entry = runtime.get("token_to_system", {}).get(token)
    if isinstance(entry, dict):
        return entry
    return None


def resolve_route_travel_details(cfg: dict, source_label: str, dest_label: str) -> dict:
    source_norm = normalize_location_label(source_label)
    dest_norm = normalize_location_label(dest_label)
    base = {
        "path_found": False,
        "path_kind": "external",
        "travel_summary": "External connector",
        "travel_path_legs": [],
        "gate_leg_count": 0,
        "ansiblex_leg_count": 0,
        "total_leg_count": 0,
        "ansiblex_logistics_cost_isk": 0.0,
        "used_ansiblex": False,
        "ansiblex_enabled": bool(resolve_ansiblex_cfg(cfg).get("enabled", False)),
        "source_system": "",
        "dest_system": "",
    }
    if not source_norm or not dest_norm:
        return base
    if "jita" in (source_norm, dest_norm):
        return base

    runtime = _route_travel_runtime(cfg)
    src_entry = _token_entry(runtime, source_label)
    dst_entry = _token_entry(runtime, dest_label)
    if src_entry is None or dst_entry is None:
        out = dict(base)
        out["path_kind"] = "unmapped_internal"
        out["travel_summary"] = "Internal route outside mapped corridor graph"
        return out

    start = str(src_entry.get("system_norm", "") or "")
    goal = str(dst_entry.get("system_norm", "") or "")
    out = dict(base)
    out["source_system"] = str(src_entry.get("system", "") or "")
    out["dest_system"] = str(dst_entry.get("system", "") or "")
    if not start or not goal:
        return out
    if start == goal:
        out.update(
            {
                "path_found": True,
                "path_kind": "same_system",
                "travel_summary": "Same-system route",
            }
        )
        return out

    adjacency = runtime.get("adjacency", {})
    queue: list[tuple[int, float, int, str, list[dict]]] = [(0, 0.0, 0, start, [])]
    best: dict[str, tuple[int, float, int]] = {start: (0, 0.0, 0)}
    final_path: list[dict] = []

    while queue:
        legs_total, ansiblex_cost, ansiblex_legs, current, path_legs = heapq.heappop(queue)
        if current == goal:
            final_path = path_legs
            break
        if (legs_total, ansiblex_cost, ansiblex_legs) > best.get(current, (10**9, float("inf"), 10**9)):
            continue
        for edge in list(adjacency.get(current, []) or []):
            if not isinstance(edge, dict):
                continue
            next_norm = str(edge.get("to_norm", "") or "")
            if not next_norm:
                continue
            next_legs_total = int(legs_total + 1)
            next_ansiblex_cost = float(ansiblex_cost + float(edge.get("cost_isk", 0.0) or 0.0))
            next_ansiblex_legs = int(ansiblex_legs + (1 if str(edge.get("mode", "") or "") == "ansiblex" else 0))
            best_state = best.get(next_norm)
            next_state = (next_legs_total, next_ansiblex_cost, next_ansiblex_legs)
            if best_state is not None and next_state >= best_state:
                continue
            best[next_norm] = next_state
            heapq.heappush(
                queue,
                (
                    next_legs_total,
                    next_ansiblex_cost,
                    next_ansiblex_legs,
                    next_norm,
                    path_legs
                    + [
                        {
                            "from_system": str(edge.get("from_system", "") or ""),
                            "to_system": str(edge.get("to_system", "") or ""),
                            "mode": str(edge.get("mode", "gate") or "gate"),
                            "distance_ly": float(edge.get("distance_ly", 0.0) or 0.0),
                            "fuel_ozone": float(edge.get("fuel_ozone", 0.0) or 0.0),
                            "fuel_cost_isk": float(edge.get("fuel_cost_isk", 0.0) or 0.0),
                            "toll_cost_isk": float(edge.get("toll_cost_isk", 0.0) or 0.0),
                            "ansiblex_logistics_cost_isk": float(edge.get("cost_isk", 0.0) or 0.0),
                        }
                    ],
                ),
            )

    if not final_path:
        out["path_kind"] = "unresolved_internal"
        out["travel_summary"] = "Internal route has no mapped gate/ansiblex path"
        return out

    gate_legs = sum(1 for leg in final_path if str(leg.get("mode", "") or "") == "gate")
    ansiblex_legs = sum(1 for leg in final_path if str(leg.get("mode", "") or "") == "ansiblex")
    ansiblex_cost = sum(float(leg.get("ansiblex_logistics_cost_isk", 0.0) or 0.0) for leg in final_path)
    if ansiblex_legs > 0:
        summary = f"{gate_legs} gate leg(s), {ansiblex_legs} ansiblex leg(s), {ansiblex_cost:.0f} ISK ansiblex logistics"
        kind = "ansiblex_mixed" if gate_legs > 0 else "ansiblex_only"
    else:
        summary = f"Pure gate route with {gate_legs} gate leg(s)"
        kind = "gate_only"
    out.update(
        {
            "path_found": True,
            "path_kind": kind,
            "travel_summary": summary,
            "travel_path_legs": final_path,
            "gate_leg_count": int(gate_legs),
            "ansiblex_leg_count": int(ansiblex_legs),
            "total_leg_count": int(len(final_path)),
            "ansiblex_logistics_cost_isk": float(ansiblex_cost),
            "used_ansiblex": bool(ansiblex_legs > 0),
        }
    )
    return out


__all__ = [
    "compute_ansiblex_jump_cost",
    "load_ansiblex_edges",
    "parse_ansiblex_edge_line",
    "resolve_ansiblex_cfg",
    "resolve_route_travel_details",
]
