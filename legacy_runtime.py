import base64
import hashlib
import json
import math
import os
import sys
import time
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from fee_engine import FeeEngine
from config_loader import (
    _build_fix_hint as _mod_build_fix_hint,
    _collect_required_structure_ids as _mod_collect_required_structure_ids,
    _prepare_trade_filters as _mod_prepare_trade_filters,
    _resolve_strict_mode_cfg as _mod_resolve_strict_mode_cfg,
    _resolve_structure_region_map as _mod_resolve_structure_region_map,
    _validate_structure_region_mapping as _mod_validate_structure_region_mapping,
    ensure_dirs as _mod_ensure_dirs,
    fail_on_invalid_config as _mod_fail_on_invalid_config,
    load_config as _mod_load_config,
    load_json as _mod_load_json,
    save_json as _mod_save_json,
    validate_config as _mod_validate_config,
)
from execution_plan import (
    write_execution_plan_profiles as _mod_write_execution_plan_profiles,
    write_route_leaderboard as _mod_write_route_leaderboard,
)
from fees import compute_trade_financials as _mod_compute_trade_financials
from location_utils import (
    label_to_slug as _mod_label_to_slug,
    normalize_location_label as _mod_normalize_location_label2,
)
from startup_helpers import (
    _build_structure_context as _mod_main_build_structure_context,
    _node_source_dest_info as _mod_main_node_source_dest_info,
    _normalize_route_mode as _mod_main_normalize_route_mode,
    _resolve_chain_runtime as _mod_main_resolve_chain_runtime,
    _resolve_location_nodes as _mod_main_resolve_location_nodes,
    _resolve_node_catalog as _mod_main_resolve_node_catalog,
    _resolve_primary_structure_ids as _mod_main_resolve_primary_structure_ids,
)
from market_normalization import (
    make_snapshot_payload as _mod_make_snapshot_payload,
    normalize_replay_snapshot as _mod_normalize_replay_snapshot,
)
from models import (
    FilterFunnel,
    OrderLevel,
    TradeCandidate,
)
from route_search import (
    _parse_route_pair_token as _mod_parse_route_pair_token,
    _resolve_allowed_route_pair_lane_overrides as _mod_resolve_allowed_route_pair_lane_overrides,
    _resolve_allowed_route_pairs as _mod_resolve_allowed_route_pairs,
    _resolve_route_search_cfg as _mod_resolve_route_search_cfg,
    build_route_search_profiles as _mod_build_route_search_profiles,
)
from scoring import (
    apply_strategy_mode as _mod_apply_strategy_mode,
    compute_volatility_score as _mod_compute_volatility_score,
)
from shipping import (
    _extract_shipping_lane_params as _mod_extract_shipping_lane_params,
    _lane_has_complete_pricing_params as _mod_lane_has_complete_pricing_params,
    _lane_provider_from_cfg as _mod_lane_provider_from_cfg,
    _match_shipping_lanes as _mod_match_shipping_lanes,
    _pick_passes_profit_floors as _mod_pick_passes_profit_floors,
    _policy_provider_for_route as _mod_policy_provider_for_route,
    apply_route_costs_and_prune as _mod_apply_route_costs_and_prune,
    apply_route_costs_to_picks as _mod_apply_route_costs_to_picks,
    build_jita_split_price_map as _mod_build_jita_split_price_map,
    build_route_context as _mod_build_route_context,
    compute_jita_split_price as _mod_compute_jita_split_price,
    compute_shipping_lane_reward_cost as _mod_compute_shipping_lane_reward_cost,
    compute_shipping_lane_reward_cost_single as _mod_compute_shipping_lane_reward_cost_single,
    compute_shipping_lane_total_cost as _mod_compute_shipping_lane_total_cost,
    resolve_route_cost_cfg as _mod_resolve_route_cost_cfg,
    resolve_shipping_lane_cfg as _mod_resolve_shipping_lane_cfg,
    split_shipping_contracts as _mod_split_shipping_contracts,
)


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
TOKEN_PATH = os.path.join(CACHE_DIR, "token.json")
TYPE_CACHE_PATH = os.path.join(CACHE_DIR, "types.json")
HTTP_CACHE_PATH = os.path.join(CACHE_DIR, "http_cache.json")
CACHE_IO_LOCK = threading.Lock()


def ensure_dirs() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        # Accept UTF-8 files with or without BOM to avoid false "corrupt" detection.
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # Recover from partial/truncated cache writes.
        print(f"Warnung: Defekte JSON-Datei erkannt ({path}): {e}. Verwende Default und sichere defekte Datei.")
        try:
            bad_path = path + ".corrupt"
            if os.path.exists(bad_path):
                os.remove(bad_path)
            os.replace(path, bad_path)
        except Exception:
            pass
        return default


def save_json(path: str, data) -> None:
    with CACHE_IO_LOCK:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Retry logic for file lock issues on Windows
        max_retries = 3
        for attempt in range(max_retries):
            try:
                os.replace(tmp, path)
                return
            except (PermissionError, OSError) as e:
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    # Last attempt failed, but don't crash - just log and continue
                    print(f"Warnung: Konnte {path} nicht speichern: {e}")
                    # Clean up temp file
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                    return


def die(msg: str) -> None:
    print(msg)
    sys.exit(1)


def parse_isk(s: str) -> int:
    s = s.strip().lower().replace(",", "").replace("_", "")
    if not s:
        raise ValueError("empty")
    mult = 1
    if s.endswith("b"):
        mult = 1_000_000_000
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    val = float(s)
    if val < 0:
        raise ValueError("negative")
    return int(val * mult)


def _has_live_esi_credentials(cfg: dict) -> bool:
    esi_cfg = cfg.get("esi", {}) if isinstance(cfg, dict) else {}
    if not isinstance(esi_cfg, dict):
        return False
    client_id = str(esi_cfg.get("client_id", "")).strip()
    client_secret = str(esi_cfg.get("client_secret", "")).strip()
    if not client_id or client_id.startswith("PASTE_"):
        return False
    if not client_secret or client_secret.startswith("PASTE_"):
        return False
    return True


def parse_cli_args(argv: list[str]) -> dict:
    args = {
        "snapshot_only": False,
        "snapshot_out": None,
        "structures": None,
        "cargo_m3": None,
        "budget_isk": None,
    }
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--snapshot-only":
            args["snapshot_only"] = True
            i += 1
            continue
        if tok == "--snapshot-out":
            if i + 1 >= len(argv):
                die("--snapshot-out erwartet einen Dateipfad")
            args["snapshot_out"] = argv[i + 1]
            i += 2
            continue
        if tok == "--structures":
            vals = []
            j = i + 1
            while j < len(argv) and not str(argv[j]).startswith("--"):
                try:
                    vals.append(int(argv[j]))
                except Exception:
                    die(f"Ungueltige structure_id in --structures: {argv[j]}")
                j += 1
            if not vals:
                die("--structures erwartet mindestens eine structure_id")
            args["structures"] = vals
            i = j
            continue
        if tok == "--cargo-m3":
            if i + 1 >= len(argv):
                die("--cargo-m3 erwartet einen Wert")
            raw = str(argv[i + 1]).strip()
            if not raw:
                die("--cargo-m3 erwartet einen Wert")
            try:
                args["cargo_m3"] = float(raw)
            except Exception:
                die(f"Ungueltiger Wert fuer --cargo-m3: {raw}")
            i += 2
            continue
        if tok == "--budget-isk":
            if i + 1 >= len(argv):
                die("--budget-isk erwartet einen Wert")
            raw = str(argv[i + 1]).strip()
            if not raw:
                die("--budget-isk erwartet einen Wert")
            try:
                args["budget_isk"] = parse_isk(raw)
            except Exception:
                die(f"Ungueltiger Wert fuer --budget-isk: {raw}")
            i += 2
            continue
        die(f"Unbekanntes Argument: {tok}")
    return args


def input_with_default(prompt: str, default_value: str) -> str:
    s = input(f"{prompt} (default {default_value}): ").strip()
    return s if s else default_value


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def make_basic_auth(client_id: str, client_secret: str) -> str:
    token = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("utf-8")


def compute_trade_financials(
    buy_price: float,
    sell_price: float,
    qty: int,
    fees: dict,
    instant: bool,
    execution_mode: str | None = None,
    relist_budget_pct: float = 0.0,
    relist_budget_isk: float = 0.0
) -> tuple[float, float, float, float]:
    """Return (cost_net, revenue_net, profit, profit_pct)."""
    mode = str(execution_mode or ("instant" if instant else "planned_sell")).lower()
    if mode == "instant":
        execution = "instant_instant"
    elif mode in ("planned_sell", "fast_sell"):
        execution = "instant_listed"
    else:
        execution = "instant_instant" if instant else "instant_listed"

    breakdown = FeeEngine(fees).compute(
        buy_price=buy_price,
        sell_price=sell_price,
        qty=qty,
        execution=execution,
        relist_budget_pct=(relist_budget_pct if execution == "instant_listed" else 0.0),
        relist_budget_isk=(relist_budget_isk if execution == "instant_listed" else 0.0),
    )
    return breakdown.cost_net, breakdown.revenue_net, breakdown.profit, breakdown.profit_pct


def _pick_fee_components(pick: dict) -> dict[str, float]:
    sales_tax_isk = float(pick.get("sales_tax_isk", pick.get("sales_tax_total", 0.0)) or 0.0)
    broker_fee_isk = float(pick.get("broker_fee_isk", pick.get("sell_broker_fee_total", 0.0)) or 0.0)
    scc_surcharge_isk = float(pick.get("scc_surcharge_isk", pick.get("scc_surcharge_total", 0.0)) or 0.0)
    relist_fee_isk = float(pick.get("relist_fee_isk", pick.get("relist_budget_total", 0.0)) or 0.0)
    buy_broker_fee_isk = float(pick.get("buy_broker_fee_total", 0.0) or 0.0)
    return {
        "sales_tax_isk": sales_tax_isk,
        "broker_fee_isk": broker_fee_isk,
        "scc_surcharge_isk": scc_surcharge_isk,
        "relist_fee_isk": relist_fee_isk,
        "buy_broker_fee_isk": buy_broker_fee_isk,
    }


def _pick_total_fees_taxes(pick: dict) -> float:
    f = _pick_fee_components(pick)
    return (
        float(f["buy_broker_fee_isk"])
        + float(f["broker_fee_isk"])
        + float(f["sales_tax_isk"])
        + float(f["scc_surcharge_isk"])
        + float(f["relist_fee_isk"])
    )


def normalize_location_label(label: str) -> str:
    txt = str(label or "").strip().lower()
    if not txt:
        return ""
    out = []
    for ch in txt:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    norm = " ".join("".join(out).split())
    if norm in ("jita", "jita iv moon 4 caldari navy assembly plant", "jita 44", "jita 4 4"):
        return "jita"
    if norm in ("jita44", "jita 44"):
        return "jita"
    if norm.startswith("1st"):
        return "1st"
    if norm in ("ualx", "ualx 3", "ualx3"):
        return "ualx"
    if norm in ("o 4t", "o4 t"):
        return "o4t"
    if norm in ("c j6mt", "cj6mt", "c j 6mt", "cj6", "c j6", "c j 6"):
        return "c_j6mt"
    return norm


def _lane_provider_from_cfg(lane_id: str, lane_cfg: dict | None) -> str:
    lid = str(lane_id or "").strip().lower()
    model = str((lane_cfg or {}).get("pricing_model", "") or "").strip().lower()
    if lid.startswith("itl_") or model == "itl_max":
        return "ITL"
    if lid.startswith("hwl_") or model == "hwl_volume_plus_value":
        return "HWL"
    return ""


def _policy_provider_for_route(src_label: str, dst_label: str) -> str:
    src = normalize_location_label(src_label)
    dst = normalize_location_label(dst_label)
    pair = (src, dst)
    if pair in (("jita", "o4t"), ("o4t", "jita")):
        return "HWL"
    if pair in (
        ("jita", "1st"),
        ("1st", "jita"),
        ("jita", "ualx"),
        ("ualx", "jita"),
        ("jita", "c_j6mt"),
        ("c_j6mt", "jita"),
    ):
        return "ITL"
    return ""


def _lane_has_complete_pricing_params(lane_cfg: dict | None) -> bool:
    if not isinstance(lane_cfg, dict):
        return False
    model = str(lane_cfg.get("pricing_model", "itl_max") or "itl_max").strip().lower()
    if model == "itl_max":
        return (
            lane_cfg.get("per_m3_rate") is not None
            and lane_cfg.get("minimum_reward", lane_cfg.get("min_reward", None)) is not None
            and lane_cfg.get("full_load_reward", lane_cfg.get("full_load_flat_rate", None)) is not None
        )
    if model == "hwl_volume_plus_value":
        return (
            lane_cfg.get("per_m3_rate") is not None
            and lane_cfg.get("minimum_reward", lane_cfg.get("min_reward", None)) is not None
            and (
                lane_cfg.get("max_collateral_per_contract_isk") is not None
                or lane_cfg.get("max_value") is not None
            )
            and lane_cfg.get("additional_collateral_rate") is not None
        )
    return False


def compute_jita_split_price(best_buy: float, best_sell: float) -> float:
    bb = max(0.0, float(best_buy or 0.0))
    bs = max(0.0, float(best_sell or 0.0))
    if bb > 0.0 and bs > 0.0:
        return (bb + bs) / 2.0
    return bb if bb > 0.0 else bs


def build_jita_split_price_map(jita_orders: list[dict], type_ids: set[int] | None = None) -> dict[int, float]:
    best_buy: dict[int, float] = {}
    best_sell: dict[int, float] = {}
    wanted = set(type_ids or [])
    filter_enabled = len(wanted) > 0
    for o in list(jita_orders or []):
        try:
            tid = int(o.get("type_id", 0) or 0)
        except Exception:
            continue
        if tid <= 0:
            continue
        if filter_enabled and tid not in wanted:
            continue
        try:
            price = float(o.get("price", 0.0) or 0.0)
        except Exception:
            price = 0.0
        if price <= 0.0:
            continue
        if bool(o.get("is_buy_order", False)):
            prev = best_buy.get(tid, 0.0)
            if price > prev:
                best_buy[tid] = float(price)
        else:
            prev = best_sell.get(tid, 0.0)
            if prev <= 0.0 or price < prev:
                best_sell[tid] = float(price)
    out: dict[int, float] = {}
    tids = set(best_buy.keys()) | set(best_sell.keys())
    for tid in tids:
        split = compute_jita_split_price(best_buy.get(tid, 0.0), best_sell.get(tid, 0.0))
        if split > 0.0:
            out[int(tid)] = float(split)
    return out


def split_shipping_contracts(
    total_volume_m3: float,
    total_collateral_isk: float,
    max_volume_per_contract_m3: float | None = None,
    max_collateral_per_contract_isk: float | None = None,
) -> tuple[list[dict], str]:
    vol = max(0.0, float(total_volume_m3 or 0.0))
    coll = max(0.0, float(total_collateral_isk or 0.0))
    max_vol = None
    max_coll = None
    if max_volume_per_contract_m3 is not None:
        try:
            mv = float(max_volume_per_contract_m3)
            if mv > 0.0:
                max_vol = mv
        except Exception:
            max_vol = None
    if max_collateral_per_contract_isk is not None:
        try:
            mc = float(max_collateral_per_contract_isk)
            if mc > 0.0:
                max_coll = mc
        except Exception:
            max_coll = None

    n_contracts = 1
    split_reasons: list[str] = []
    if max_vol is not None and vol > max_vol:
        n_contracts = max(n_contracts, int(math.ceil(vol / max_vol)))
        split_reasons.append("max_volume_per_contract_m3")
    if max_coll is not None and coll > max_coll:
        n_contracts = max(n_contracts, int(math.ceil(coll / max_coll)))
        split_reasons.append("max_collateral_per_contract_isk")

    if n_contracts <= 1:
        return [{"volume_m3": float(vol), "collateral_isk": float(coll), "share": 1.0}], ""

    out: list[dict] = []
    vol_remaining = float(vol)
    coll_remaining = float(coll)
    use_max_vol = max_vol is not None and max_vol > 0.0
    use_max_coll = max_coll is not None and max_coll > 0.0
    for idx in range(n_contracts):
        slots_left = max(1, n_contracts - idx)
        vol_floor_needed = 0.0
        coll_floor_needed = 0.0
        if use_max_vol:
            vol_floor_needed = max(0.0, float(slots_left - 1) * float(max_vol))
        if use_max_coll:
            coll_floor_needed = max(0.0, float(slots_left - 1) * float(max_coll))
        c_vol = vol_remaining if not use_max_vol else min(float(max_vol), max(0.0, vol_remaining - vol_floor_needed))
        c_coll = coll_remaining if not use_max_coll else min(float(max_coll), max(0.0, coll_remaining - coll_floor_needed))
        if not use_max_vol:
            c_vol = vol_remaining / float(slots_left)
        if not use_max_coll:
            c_coll = coll_remaining / float(slots_left)
        vol_remaining = max(0.0, vol_remaining - c_vol)
        coll_remaining = max(0.0, coll_remaining - c_coll)
        out.append({
            "volume_m3": float(c_vol),
            "collateral_isk": float(c_coll),
            "share": (float(c_vol) / vol) if vol > 0 else (1.0 / float(n_contracts)),
        })
    return out, ",".join(split_reasons)


def compute_shipping_lane_reward_cost_single(
    lane_cfg: dict,
    volume_m3: float,
    collateral_isk: float
) -> float:
    vol = max(0.0, float(volume_m3 or 0.0))
    coll = max(0.0, float(collateral_isk or 0.0))
    pricing_model = str(lane_cfg.get("pricing_model", "itl_max") or "itl_max").strip().lower()
    per_m3_rate = lane_cfg.get("per_m3_rate", None)
    flat_rate = lane_cfg.get("full_load_reward", lane_cfg.get("full_load_flat_rate", None))
    collateral_rate = lane_cfg.get("collateral_rate", None)
    min_reward = lane_cfg.get("minimum_reward", lane_cfg.get("min_reward", None))
    additional_collateral_rate = lane_cfg.get("additional_collateral_rate", None)

    def _num(v):
        try:
            return float(v)
        except Exception:
            return None

    per_m3_valid = _num(per_m3_rate)
    if per_m3_valid is not None:
        per_m3_valid = max(0.0, per_m3_valid)
    flat_valid = _num(flat_rate)
    if flat_valid is not None:
        flat_valid = max(0.0, flat_valid)
    min_valid = _num(min_reward)
    if min_valid is not None:
        min_valid = max(0.0, min_valid)

    if pricing_model == "hwl_volume_plus_value":
        vol_component = (vol * per_m3_valid) if per_m3_valid is not None else 0.0
        coll_rate_valid = _num(additional_collateral_rate)
        if coll_rate_valid is None:
            coll_rate_valid = 0.0
        coll_component = max(0.0, coll_rate_valid) * coll
        return float(max(0.0, max(min_valid or 0.0, vol_component + coll_component)))

    # Default: ITL-style MAX(collateral, clamped-volume)
    volume_component = 0.0
    if per_m3_valid is not None:
        volume_reward_raw = vol * per_m3_valid
        volume_component = volume_reward_raw
        if min_valid is not None and volume_component < min_valid:
            volume_component = min_valid
        if flat_valid is not None and volume_component > flat_valid:
            volume_component = flat_valid
    elif flat_valid is not None:
        volume_component = flat_valid
    elif min_valid is not None:
        volume_component = min_valid

    collateral_component = 0.0
    if collateral_rate is not None:
        coll_rate_valid = _num(collateral_rate)
        if coll_rate_valid is not None:
            collateral_component = max(0.0, coll_rate_valid) * coll
    return float(max(0.0, max(collateral_component, volume_component)))


def compute_shipping_lane_total_cost(
    lane_cfg: dict,
    total_volume_m3: float,
    total_collateral_isk: float
) -> dict:
    pricing_model = str(lane_cfg.get("pricing_model", "itl_max") or "itl_max").strip().lower()
    max_volume_per_contract = lane_cfg.get("max_volume_per_contract_m3", None)
    max_collateral_per_contract = lane_cfg.get("max_collateral_per_contract_isk", lane_cfg.get("max_value", None))
    if pricing_model == "itl_max" and max_volume_per_contract is None:
        max_volume_per_contract = 350000.0
    contracts, split_reason = split_shipping_contracts(
        total_volume_m3=total_volume_m3,
        total_collateral_isk=total_collateral_isk,
        max_volume_per_contract_m3=max_volume_per_contract,
        max_collateral_per_contract_isk=max_collateral_per_contract,
    )
    total_cost = 0.0
    for c in contracts:
        c_cost = compute_shipping_lane_reward_cost_single(
            lane_cfg=lane_cfg,
            volume_m3=float(c.get("volume_m3", 0.0)),
            collateral_isk=float(c.get("collateral_isk", 0.0)),
        )
        c["shipping_cost"] = float(c_cost)
        total_cost += float(c_cost)
    return {
        "total_cost": float(max(0.0, total_cost)),
        "contracts": contracts,
        "contracts_used": int(len(contracts)),
        "split_reason": str(split_reason or ""),
        "pricing_model": str(lane_cfg.get("pricing_model", "itl_max") or "itl_max"),
    }


def compute_shipping_lane_reward_cost(
    lane_cfg: dict,
    volume_m3: float,
    collateral_isk: float
) -> float:
    summary = compute_shipping_lane_total_cost(
        lane_cfg=lane_cfg,
        total_volume_m3=volume_m3,
        total_collateral_isk=collateral_isk,
    )
    return float(summary.get("total_cost", 0.0))


def _match_shipping_lanes(
    cfg: dict,
    src_label: str,
    dst_label: str,
    source_id: int | None = None,
    dest_id: int | None = None
) -> list[tuple[str, dict]]:
    lanes = cfg.get("shipping_lanes", {})
    if not isinstance(lanes, dict):
        return []
    src_norm = normalize_location_label(src_label)
    dst_norm = normalize_location_label(dst_label)
    sid = int(source_id or 0)
    did = int(dest_id or 0)
    out: list[tuple[str, dict]] = []
    for lane_id, raw in lanes.items():
        if not isinstance(raw, dict):
            continue
        if not bool(raw.get("enabled", False)):
            continue
        from_structure_id = int(raw.get("from_structure_id", 0) or 0)
        to_structure_id = int(raw.get("to_structure_id", 0) or 0)
        from_location_id = int(raw.get("from_location_id", 0) or 0)
        to_location_id = int(raw.get("to_location_id", 0) or 0)
        # Prefer explicit ID matching.
        from_ok = False
        to_ok = False
        if sid > 0:
            from_ok = sid in (from_structure_id, from_location_id)
        if did > 0:
            to_ok = did in (to_structure_id, to_location_id)
        if from_ok and to_ok:
            lane_cfg = dict(raw)
            lane_cfg["id"] = str(lane_id)
            out.append((str(lane_id), lane_cfg))
            continue
        lane_from = normalize_location_label(raw.get("from", ""))
        lane_to = normalize_location_label(raw.get("to", ""))
        if lane_from == src_norm and lane_to == dst_norm:
            lane_cfg = dict(raw)
            lane_cfg["id"] = str(lane_id)
            out.append((str(lane_id), lane_cfg))
    return out


def resolve_shipping_lane_cfg(
    cfg: dict,
    src_label: str,
    dst_label: str,
    source_id: int | None = None,
    dest_id: int | None = None,
    preferred_lane_id: str | None = None,
) -> tuple[str, dict] | None:
    matches = _match_shipping_lanes(
        cfg,
        src_label,
        dst_label,
        source_id=source_id,
        dest_id=dest_id,
    )
    if not matches:
        return None
    pref = str(preferred_lane_id or "").strip()
    if pref:
        for lane_id, lane_cfg in matches:
            if str(lane_id) == pref:
                return lane_id, lane_cfg
    policy_provider = _policy_provider_for_route(src_label, dst_label)
    if policy_provider:
        policy_matches = [(lid, lcfg) for lid, lcfg in matches if _lane_provider_from_cfg(lid, lcfg) == policy_provider]
        if not policy_matches:
            return None
        complete_policy_matches = [(lid, lcfg) for lid, lcfg in policy_matches if _lane_has_complete_pricing_params(lcfg)]
        if complete_policy_matches:
            return complete_policy_matches[0]
        return policy_matches[0]
    return matches[0]


def resolve_route_cost_cfg(cfg: dict, route_id: str, src_label: str, dst_label: str) -> dict:
    route_costs = cfg.get("route_costs", {})
    if not isinstance(route_costs, dict):
        route_costs = {}
    normalized_id = str(route_id or "").strip().lower()
    key_pairs = [
        normalized_id,
        f"{normalize_location_label(src_label)}->{normalize_location_label(dst_label)}",
        f"{normalize_location_label(src_label)}_{normalize_location_label(dst_label)}",
    ]
    found = {}
    for key in key_pairs:
        if key in route_costs and isinstance(route_costs.get(key), dict):
            found = dict(route_costs.get(key) or {})
            break
    fixed_isk = float(found.get("fixed_isk", 0.0) or 0.0)
    isk_per_m3 = float(found.get("isk_per_m3", 0.0) or 0.0)
    return {"fixed_isk": max(0.0, fixed_isk), "isk_per_m3": max(0.0, isk_per_m3)}


def build_route_context(
    cfg: dict,
    route_id: str,
    source_label: str,
    dest_label: str,
    source_id: int | None = None,
    dest_id: int | None = None,
    preferred_shipping_lane_id: str | None = None,
) -> dict:
    shipping_candidates = _match_shipping_lanes(cfg, source_label, dest_label, source_id=source_id, dest_id=dest_id)
    shipping = resolve_shipping_lane_cfg(
        cfg,
        source_label,
        dest_label,
        source_id=source_id,
        dest_id=dest_id,
        preferred_lane_id=preferred_shipping_lane_id,
    )
    shipping_lane_id = ""
    shipping_lane_cfg = None
    if shipping:
        shipping_lane_id, shipping_lane_cfg = shipping
    route_cost_cfg = resolve_route_cost_cfg(cfg, route_id, source_label, dest_label)
    shipping_defaults = cfg.get("shipping_defaults", {})
    if not isinstance(shipping_defaults, dict):
        shipping_defaults = {}
    return {
        "route_id": str(route_id or ""),
        "source_label": str(source_label or ""),
        "dest_label": str(dest_label or ""),
        "source_id": int(source_id or 0),
        "dest_id": int(dest_id or 0),
        "jita_based_route": (
            normalize_location_label(str(source_label or "")) == "jita"
            or normalize_location_label(str(dest_label or "")) == "jita"
        ),
        "shipping_lane_id": str(shipping_lane_id or ""),
        "shipping_lane_cfg": shipping_lane_cfg if isinstance(shipping_lane_cfg, dict) else None,
        "shipping_lane_candidates": [{"id": str(lid), "cfg": cfg_i} for lid, cfg_i in shipping_candidates],
        "preferred_shipping_lane_id": str(preferred_shipping_lane_id or ""),
        "shipping_defaults": shipping_defaults,
        "route_cost_cfg": route_cost_cfg,
    }


def _extract_shipping_lane_params(lane_cfg: dict | None) -> dict:
    if not isinstance(lane_cfg, dict):
        return {}
    out = {
        "pricing_model": str(lane_cfg.get("pricing_model", "itl_max") or "itl_max"),
        "per_m3_rate": lane_cfg.get("per_m3_rate", None),
        "minimum_reward": lane_cfg.get("minimum_reward", lane_cfg.get("min_reward", None)),
        "full_load_reward": lane_cfg.get("full_load_reward", lane_cfg.get("full_load_flat_rate", None)),
        "collateral_rate": lane_cfg.get("collateral_rate", None),
        "additional_collateral_rate": lane_cfg.get("additional_collateral_rate", None),
        "max_volume_per_contract_m3": lane_cfg.get("max_volume_per_contract_m3", None),
        "max_collateral_per_contract_isk": lane_cfg.get("max_collateral_per_contract_isk", lane_cfg.get("max_value", None)),
        "max_value": lane_cfg.get("max_value", None),
        "collateral_basis": lane_cfg.get("collateral_basis", None),
    }
    return out


def apply_route_costs_to_picks(picks: list[dict], route_context: dict) -> dict:
    if not picks:
        return {
            "total_shipping_cost": 0.0,
            "total_route_cost": 0.0,
            "total_transport_cost": 0.0,
            "shipping_lane_id": str(route_context.get("shipping_lane_id", "") or ""),
        }

    total_volume = sum(max(0.0, float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0))) for p in picks)
    if total_volume <= 0:
        total_volume = 0.0
    route_cfg = route_context.get("route_cost_cfg", {})
    if not isinstance(route_cfg, dict):
        route_cfg = {}

    shipping_total = 0.0
    shipping_pricing_model = ""
    shipping_provider = ""
    shipping_contracts_used = 0
    shipping_split_reason = ""
    estimated_collateral_isk = 0.0
    selected_lane_id = str(route_context.get("shipping_lane_id", "") or "")
    selected_lane_cfg = route_context.get("shipping_lane_cfg")
    if isinstance(selected_lane_cfg, dict):
        selected_lane_cfg = dict(selected_lane_cfg)
    else:
        selected_lane_cfg = None
    lane_candidates_raw = route_context.get("shipping_lane_candidates", [])
    lane_candidates: list[tuple[str, dict]] = []
    if isinstance(lane_candidates_raw, list):
        for c in lane_candidates_raw:
            if not isinstance(c, dict):
                continue
            lid = str(c.get("id", "") or "")
            lcfg = c.get("cfg")
            if lid and isinstance(lcfg, dict):
                lane_candidates.append((lid, dict(lcfg)))
    preferred_lane_id = str(route_context.get("preferred_shipping_lane_id", "") or "").strip()

    def _estimate_collateral_for_lane(lane_cfg_local: dict) -> float:
        ship_defaults = route_context.get("shipping_defaults", {})
        if not isinstance(ship_defaults, dict):
            ship_defaults = {}
        collateral_buffer_pct = max(0.0, float(ship_defaults.get("collateral_buffer_pct", 0.0) or 0.0))
        total_buy = sum(max(0.0, float(p.get("cost", 0.0))) for p in picks)
        total_ref = 0.0
        total_jita_split = 0.0
        for p in picks:
            qty = int(p.get("qty", 0) or 0)
            ref_unit = float(p.get("reference_price_adjusted", p.get("reference_price", 0.0)) or 0.0)
            total_ref += max(0.0, ref_unit * qty)
            jita_split_unit = float(p.get("jita_split_price", 0.0) or 0.0)
            total_jita_split += max(0.0, jita_split_unit * qty)
        collateral_basis = str(lane_cfg_local.get("collateral_basis", "auto") or "auto").strip().lower()
        base_collateral = max(total_buy, total_ref)
        if collateral_basis in ("jita_split", "jita_mid"):
            base_collateral = max(0.0, total_jita_split)
        elif collateral_basis == "auto" and bool(route_context.get("jita_based_route", False)) and total_jita_split > 0.0:
            base_collateral = max(0.0, total_jita_split)
        return max(0.0, base_collateral) * (1.0 + collateral_buffer_pct)

    if lane_candidates:
        selected_lane_tuple: tuple[str, dict] | None = None
        if preferred_lane_id:
            for lane_id, lane_cfg in lane_candidates:
                if lane_id == preferred_lane_id:
                    selected_lane_tuple = (lane_id, lane_cfg)
                    break
        if selected_lane_tuple is None and selected_lane_id:
            for lane_id, lane_cfg in lane_candidates:
                if lane_id == selected_lane_id:
                    selected_lane_tuple = (lane_id, lane_cfg)
                    break
        if selected_lane_tuple is None and not _policy_provider_for_route(
            str(route_context.get("source_label", "") or ""),
            str(route_context.get("dest_label", "") or ""),
        ):
            selected_lane_tuple = lane_candidates[0]
        if selected_lane_tuple is not None:
            lane_id, lane_cfg = selected_lane_tuple
            est_coll = _estimate_collateral_for_lane(lane_cfg)
            shipping_meta = compute_shipping_lane_total_cost(lane_cfg, total_volume, est_coll)
            selected_lane_id = str(lane_id)
            selected_lane_cfg = dict(lane_cfg)
            estimated_collateral_isk = float(est_coll)
            shipping_total = float(shipping_meta.get("total_cost", 0.0))
            shipping_pricing_model = str(shipping_meta.get("pricing_model", ""))
            shipping_provider = _lane_provider_from_cfg(lane_id, lane_cfg)
            shipping_contracts_used = int(shipping_meta.get("contracts_used", 0) or 0)
            shipping_split_reason = str(shipping_meta.get("split_reason", "") or "")
    elif isinstance(selected_lane_cfg, dict):
        estimated_collateral_isk = _estimate_collateral_for_lane(selected_lane_cfg)
        shipping_meta = compute_shipping_lane_total_cost(selected_lane_cfg, total_volume, estimated_collateral_isk)
        shipping_total = float(shipping_meta.get("total_cost", 0.0))
        shipping_pricing_model = str(shipping_meta.get("pricing_model", ""))
        shipping_provider = _lane_provider_from_cfg(selected_lane_id, selected_lane_cfg)
        shipping_contracts_used = int(shipping_meta.get("contracts_used", 0) or 0)
        shipping_split_reason = str(shipping_meta.get("split_reason", "") or "")

    route_fixed = max(0.0, float(route_cfg.get("fixed_isk", 0.0) or 0.0))
    route_per_m3 = max(0.0, float(route_cfg.get("isk_per_m3", 0.0) or 0.0))
    route_total = route_fixed + (route_per_m3 * total_volume)
    transport_total = shipping_total + route_total

    if transport_total > 0.0 and total_volume > 0.0:
        for p in picks:
            pick_volume = max(0.0, float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)))
            share = pick_volume / total_volume if total_volume > 0 else 0.0
            pick_shipping = shipping_total * share
            pick_route = route_total * share
            pick_transport = pick_shipping + pick_route
            p["shipping_cost"] = float(pick_shipping)
            p["route_cost"] = float(pick_route)
            p["transport_cost"] = float(pick_transport)
            p["revenue_net"] = float(p.get("revenue_net", 0.0)) - float(pick_transport)
            p["profit"] = float(p.get("profit", 0.0)) - float(pick_transport)
            cost = float(p.get("cost", 0.0))
            p["profit_pct"] = (float(p["profit"]) / cost) if cost > 0 else 0.0
            pick_m3 = max(0.0, float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)))
            p["profit_per_m3"] = (float(p["profit"]) / pick_m3) if pick_m3 > 0 else 0.0
            p["profit_per_m3_per_day"] = float(p["profit_per_m3"]) * float(p.get("turnover_factor", 0.0))
    else:
        for p in picks:
            p.setdefault("shipping_cost", 0.0)
            p.setdefault("route_cost", 0.0)
            p.setdefault("transport_cost", 0.0)

    return {
        "total_shipping_cost": float(shipping_total),
        "total_route_cost": float(route_total),
        "total_transport_cost": float(transport_total),
        "shipping_lane_id": str(selected_lane_id or route_context.get("shipping_lane_id", "") or ""),
        "shipping_pricing_model": shipping_pricing_model,
        "shipping_provider": shipping_provider,
        "shipping_contracts_used": int(shipping_contracts_used),
        "shipping_split_reason": shipping_split_reason,
        "estimated_collateral_isk": float(estimated_collateral_isk),
        "shipping_lane_params": _extract_shipping_lane_params(selected_lane_cfg),
        "total_route_m3": float(total_volume),
    }


def _pick_passes_profit_floors(p: dict, filters_used: dict) -> bool:
    min_profit_abs = float(filters_used.get("min_profit_absolute", filters_used.get("min_profit_isk_total", 0.0)) or 0.0)
    min_profit_pct = float(filters_used.get("min_profit_pct", 0.0) or 0.0)
    min_profit_per_m3 = float(filters_used.get("min_profit_per_m3", 0.0) or 0.0)
    min_profit_per_isk = float(filters_used.get("min_profit_per_isk", 0.0) or 0.0)
    profit = float(p.get("profit", 0.0))
    if profit < min_profit_abs:
        return False
    cost = max(1e-9, float(p.get("cost", 0.0)))
    if (profit / cost) < min_profit_pct:
        return False
    qty = max(0.0, float(p.get("qty", 0)))
    m3 = max(1e-9, float(p.get("unit_volume", 0.0)) * qty)
    if (profit / m3) < min_profit_per_m3:
        return False
    if (profit / cost) < min_profit_per_isk:
        return False
    return True


def apply_route_costs_and_prune(picks: list[dict], route_context: dict, filters_used: dict) -> tuple[list[dict], dict]:
    work = list(picks)
    summary = apply_route_costs_to_picks(work, route_context)
    # Remove picks that become low-quality after fees+route/shipping and recompute allocation.
    changed = True
    while changed:
        changed = False
        kept = [p for p in work if _pick_passes_profit_floors(p, filters_used) and float(p.get("profit", 0.0)) > 0.0]
        if len(kept) < len(work):
            work = kept
            summary = apply_route_costs_to_picks(work, route_context)
            changed = True
    return work, summary



class CallbackState:
    def __init__(self):
        self.code = None
        self.error = None


class CachedResponse:
    def __init__(self, status_code: int, payload, headers: dict | None = None):
        self.status_code = int(status_code)
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
        self.content = self.text.encode("utf-8")
        self.ok = 200 <= self.status_code < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class OAuthHandler(BaseHTTPRequestHandler):
    state_obj: CallbackState = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        q = parse_qs(parsed.query)
        if "error" in q:
            OAuthHandler.state_obj.error = q.get("error", ["unknown"])[0]
        if "code" in q:
            OAuthHandler.state_obj.code = q.get("code", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Login ok</h2><p>Du kannst dieses Fenster schliessen.</p></body></html>"
        )

    def log_message(self, format, *args):
        return

class ESIClient:
    def __init__(self, cfg: dict):
        self.base_url = cfg["esi"]["base_url"].rstrip("/")
        self.user_agent = cfg["esi"]["user_agent"]
        self.client_id = cfg["esi"]["client_id"]
        self.client_secret = cfg["esi"]["client_secret"]
        self.callback_url = cfg["esi"]["callback_url"]
        self.scope = cfg["esi"]["scope"]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.diagnostics_enabled = bool(cfg.get("diagnostics", {}).get("network_verbose", True))
        self.request_min_interval_sec = float(cfg.get("esi", {}).get("request_min_interval_sec", 0.35))
        self.rate_limit_cooldown_sec = float(cfg.get("esi", {}).get("rate_limit_cooldown_sec", 0.0))
        self.error_limit_backoff_sec = float(cfg.get("esi", {}).get("error_limit_backoff_sec", 2.0))
        self.http_cache_default_ttl_sec = int(cfg.get("esi", {}).get("cache_default_ttl_sec", 60))
        self.request_log_limit = int(cfg.get("esi", {}).get("request_log_limit", 2000))
        self._request_pacing_lock = threading.Lock()
        self._next_request_at = 0.0

        self.token = load_json(TOKEN_PATH, {})
        self.type_cache = load_json(TYPE_CACHE_PATH, {})
        self.structure_region_map: dict[int, int] = {}
        self._http_cache = load_json(HTTP_CACHE_PATH, {})
        if not isinstance(self._http_cache, dict):
            self._http_cache = {}
        # Backward compatibility for earlier cache layout.
        legacy_http_cache = self.type_cache.get("_http_cache", {})
        if not self._http_cache and isinstance(legacy_http_cache, dict):
            self._http_cache = dict(legacy_http_cache)
        if "_http_cache" in self.type_cache:
            try:
                del self.type_cache["_http_cache"]
            except Exception:
                pass
        self.request_log = []
        self._type_cache_dirty = 0
        self._perf_stats = {
            "history_requests_total": 0,
            "history_http_404": 0,
            "history_cache_hits": 0,
            "history_raw_cache_hits": 0,
            "history_negative_cache_hits": 0,
            "history_skipped_negative": 0,
            "history_served_from_cache": 0,
            "type_name_cache_hits": 0,
            "type_name_network_fetches": 0,
            "type_volume_cache_hits": 0,
            "type_volume_network_fetches": 0,
        }

    def diag(self, msg: str) -> None:
        if self.diagnostics_enabled:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(f"[DIAG {ts}] {msg}", flush=True)

    def _pace_before_request(self, label: str) -> None:
        now = time.time()
        sleep_for = 0.0
        with self._request_pacing_lock:
            if self._next_request_at > now:
                sleep_for = self._next_request_at - now
            scheduled = max(now, self._next_request_at) + self.request_min_interval_sec
            self._next_request_at = scheduled
        if sleep_for > 0:
            self.diag(f"{label}: pacing sleep {sleep_for:.2f}s")
            time.sleep(sleep_for)

    def _set_global_cooldown(self, seconds: float, label: str) -> None:
        if seconds <= 0:
            return
        with self._request_pacing_lock:
            new_next = time.time() + seconds
            if new_next > self._next_request_at:
                self._next_request_at = new_next
        self.diag(f"{label}: global cooldown set to {seconds:.2f}s")

    def save_caches(self):
        save_json(TOKEN_PATH, self.token)
        save_json(TYPE_CACHE_PATH, self.type_cache)
        save_json(HTTP_CACHE_PATH, self._http_cache)
        self._type_cache_dirty = 0

    def _mark_type_cache_dirty(self, delta: int = 1, flush_threshold: int = 200) -> None:
        self._type_cache_dirty += max(0, int(delta))
        if self._type_cache_dirty >= max(1, int(flush_threshold)):
            save_json(TYPE_CACHE_PATH, self.type_cache)
            save_json(HTTP_CACHE_PATH, self._http_cache)
            self._type_cache_dirty = 0

    def oauth_authorize(self) -> None:
        self.diag("oauth_authorize gestartet")
        print("OAuth Login startet. Browser wird geoeffnet.")
        cb = urlparse(self.callback_url)
        host = cb.hostname or "localhost"
        port = cb.port or 12563

        state = CallbackState()
        OAuthHandler.state_obj = state
        server = HTTPServer((host, port), OAuthHandler)

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        params = {
            "response_type": "code",
            "redirect_uri": self.callback_url,
            "client_id": self.client_id,
            "scope": self.scope,
            "state": "nullsectrader"
        }
        url = "https://login.eveonline.com/v2/oauth/authorize/?" + urlencode(params)
        webbrowser.open(url)

        t0 = time.time()
        while time.time() - t0 < 180:
            if state.error:
                server.shutdown()
                die(f"OAuth Fehler: {state.error}")
            if state.code:
                code = state.code
                server.shutdown()
                self.exchange_code_for_token(code)
                return
            time.sleep(0.2)

        server.shutdown()
        self.diag("oauth_authorize timeout nach 180s")
        die("OAuth Timeout. Bitte erneut starten.")

    def exchange_code_for_token(self, code: str) -> None:
        self.diag("exchange_code_for_token gestartet")
        auth = make_basic_auth(self.client_id, self.client_secret)
        headers = {"Authorization": auth, "User-Agent": self.user_agent}
        data = {
            "grant_type": "authorization_code",
            "code": code
        }
        r = requests.post("https://login.eveonline.com/v2/oauth/token", headers=headers, data=data, timeout=30)
        if r.status_code != 200:
            self.diag(f"exchange_code_for_token fehlgeschlagen: HTTP {r.status_code}")
            die(f"Token Exchange fehlgeschlagen: {r.status_code} {r.text}")
        self.token = r.json()
        self.token["created_at"] = int(time.time())
        self.save_caches()
        self.diag("exchange_code_for_token erfolgreich")
        print("Token gespeichert.")

    def refresh_token_if_needed(self) -> None:
        self.diag("refresh_token_if_needed gestartet")
        if not self.token or "access_token" not in self.token:
            self.diag("kein access_token vorhanden -> oauth_authorize")
            self.oauth_authorize()
            return

        expires_in = int(self.token.get("expires_in", 0))
        created_at = int(self.token.get("created_at", 0))
        if int(time.time()) < created_at + max(expires_in - 60, 0):
            self.diag("token noch gueltig, kein refresh noetig")
            return

        refresh = self.token.get("refresh_token")
        if not refresh:
            self.diag("kein refresh_token vorhanden -> oauth_authorize")
            self.oauth_authorize()
            return

        age = int(time.time()) - created_at
        self.diag(f"token abgelaufen/nahe ablauf (age={age}s, expires_in={expires_in}s), starte refresh")
        auth = make_basic_auth(self.client_id, self.client_secret)
        headers = {"Authorization": auth, "User-Agent": self.user_agent}
        data = {"grant_type": "refresh_token", "refresh_token": refresh}
        r = requests.post("https://login.eveonline.com/v2/oauth/token", headers=headers, data=data, timeout=30)
        if r.status_code != 200:
            self.diag(f"token refresh fehlgeschlagen: HTTP {r.status_code}")
            print("Refresh fehlgeschlagen. Neue Autorisierung.")
            self.oauth_authorize()
            return
        newt = r.json()
        newt["created_at"] = int(time.time())
        if "refresh_token" not in newt:
            newt["refresh_token"] = refresh
        self.token = newt
        self.save_caches()
        self.diag("token refresh erfolgreich")
        print("Token refresh ok.")

    def _params_hash(self, params: dict | None) -> str:
        base = params if isinstance(params, dict) else {}
        raw = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _request_cache_key(self, path: str, params: dict | None, auth: bool) -> str:
        return f"GET|{path}|auth={1 if auth else 0}|p={self._params_hash(params)}"

    def _parse_expires_header(self, value: str | None) -> int:
        if not value:
            return int(time.time()) + int(self.http_cache_default_ttl_sec)
        try:
            dt = parsedate_to_datetime(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return int(time.time()) + int(self.http_cache_default_ttl_sec)

    def _build_cached_response(self, entry: dict) -> CachedResponse:
        headers = dict(entry.get("headers", {})) if isinstance(entry, dict) else {}
        headers["X-NullsecTrader-Cache"] = "HIT"
        return CachedResponse(200, entry.get("payload", []), headers=headers)

    def _record_request_log(
        self,
        endpoint: str,
        params: dict | None,
        status: int,
        latency_sec: float,
        expires_at: int | None,
        etag: str | None,
        ratelimit_remaining: str | None,
        retry_after: str | None,
        error_limit_remaining: str | None
    ) -> None:
        self.request_log.append({
            "ts": int(time.time()),
            "endpoint": str(endpoint),
            "params_hash": self._params_hash(params),
            "status": int(status),
            "latency_ms": int(max(0.0, float(latency_sec)) * 1000),
            "expires": int(expires_at) if expires_at is not None else None,
            "etag": str(etag) if etag else "",
            "x_ratelimit_remaining": str(ratelimit_remaining) if ratelimit_remaining is not None else "",
            "retry_after": str(retry_after) if retry_after is not None else "",
            "x_esi_error_limit_remaining": str(error_limit_remaining) if error_limit_remaining is not None else "",
        })
        if len(self.request_log) > max(50, int(self.request_log_limit)):
            self.request_log = self.request_log[-int(self.request_log_limit):]

    def _dynamic_throttle_from_headers(self, path: str, headers: dict) -> None:
        retry_after_raw = headers.get("Retry-After")
        if retry_after_raw:
            try:
                wait = max(0.0, float(retry_after_raw))
                if wait > 0:
                    self._set_global_cooldown(wait, f"GET {path} retry_after")
                    time.sleep(wait)
                    return
            except Exception:
                pass

        ratelimit_remaining_raw = headers.get("X-Ratelimit-Remaining")
        if ratelimit_remaining_raw is not None:
            try:
                remaining = int(float(ratelimit_remaining_raw))
                if remaining <= 2:
                    wait = max(self.request_min_interval_sec * 2.0, 1.5)
                    self._set_global_cooldown(wait, f"GET {path} low_rate_remaining")
                    time.sleep(wait)
            except Exception:
                pass

        error_limit_remaining_raw = headers.get("X-Esi-Error-Limit-Remain")
        error_limit_reset_raw = headers.get("X-Esi-Error-Limit-Reset")
        if error_limit_remaining_raw is not None:
            try:
                remain = int(float(error_limit_remaining_raw))
                if remain <= 5:
                    reset_wait = 0.0
                    try:
                        reset_wait = max(0.0, float(error_limit_reset_raw or 0.0))
                    except Exception:
                        reset_wait = 0.0
                    wait = max(self.error_limit_backoff_sec, reset_wait)
                    self._set_global_cooldown(wait, f"GET {path} low_error_limit")
                    time.sleep(wait)
            except Exception:
                pass

    def esi_get(
        self,
        path: str,
        params: dict | None = None,
        auth: bool = False,
        force_refresh: bool = False
    ) -> requests.Response | CachedResponse:
        url = self.base_url + path
        headers = {"User-Agent": self.user_agent}
        if auth:
            self.refresh_token_if_needed()
            headers["Authorization"] = "Bearer " + self.token["access_token"]

        cache_key = self._request_cache_key(path, params, auth)
        cache_entry = self._http_cache.get(cache_key)
        now_ts = int(time.time())
        if (
            not force_refresh
            and isinstance(cache_entry, dict)
            and int(cache_entry.get("expires_at", 0)) > now_ts
            and "payload" in cache_entry
        ):
            self._record_request_log(
                endpoint=path,
                params=params,
                status=200,
                latency_sec=0.0,
                expires_at=int(cache_entry.get("expires_at", 0)),
                etag=cache_entry.get("etag", ""),
                ratelimit_remaining=None,
                retry_after=None,
                error_limit_remaining=None
            )
            self.diag(f"GET {path}: served from cache until {int(cache_entry.get('expires_at', 0))}")
            return self._build_cached_response(cache_entry)

        if isinstance(cache_entry, dict):
            etag = str(cache_entry.get("etag", "") or "")
            if etag:
                headers["If-None-Match"] = etag

        last_response = None
        for attempt in range(6):
            try:
                self._pace_before_request(f"GET {path}")
                t0 = time.time()
                self.diag(f"GET {path} attempt={attempt+1}/6 params={params} auth={auth}")
                r = self.session.get(url, params=params, headers=headers, timeout=60)
                dt = time.time() - t0
                last_response = r
                self.diag(f"GET {path} attempt={attempt+1} -> HTTP {r.status_code} in {dt:.2f}s")
                resp_headers = dict(getattr(r, "headers", {}) or {})
                self._dynamic_throttle_from_headers(path, resp_headers)
                expires_at = self._parse_expires_header(resp_headers.get("Expires"))
                etag = str(resp_headers.get("ETag", "") or "")
                self._record_request_log(
                    endpoint=path,
                    params=params,
                    status=int(r.status_code),
                    latency_sec=dt,
                    expires_at=expires_at,
                    etag=etag,
                    ratelimit_remaining=resp_headers.get("X-Ratelimit-Remaining"),
                    retry_after=resp_headers.get("Retry-After"),
                    error_limit_remaining=resp_headers.get("X-Esi-Error-Limit-Remain"),
                )
                if r.status_code == 420:
                    wait = int(r.headers.get("X-Esi-Error-Limit-Reset", "2"))
                    sleep_for = max(wait, 2) + self.rate_limit_cooldown_sec
                    self._set_global_cooldown(sleep_for, f"GET {path}")
                    self.diag(f"GET {path} rate-limited (420), wait={sleep_for:.2f}s")
                    time.sleep(sleep_for)
                    continue
                if r.status_code == 429:
                    wait_header = r.headers.get("Retry-After")
                    try:
                        wait = max(1.0, float(wait_header or 1.0))
                    except Exception:
                        wait = 1.0
                    self._set_global_cooldown(wait, f"GET {path} rate-limited (429)")
                    time.sleep(wait)
                    continue
                if r.status_code >= 500:
                    self.diag(f"GET {path} server error HTTP {r.status_code}, retry")
                    time.sleep(2.0 + attempt * 0.5)
                    continue
                if r.status_code == 304 and isinstance(cache_entry, dict) and "payload" in cache_entry:
                    cache_entry["expires_at"] = int(expires_at)
                    cache_entry["headers"] = dict(resp_headers)
                    if etag:
                        cache_entry["etag"] = etag
                    self._http_cache[cache_key] = cache_entry
                    self._mark_type_cache_dirty()
                    return self._build_cached_response(cache_entry)
                if r.status_code == 200:
                    payload = None
                    try:
                        payload = r.json()
                    except Exception:
                        payload = None
                    self._http_cache[cache_key] = {
                        "payload": payload,
                        "expires_at": int(expires_at),
                        "etag": etag,
                        "headers": dict(resp_headers),
                        "cached_at": int(time.time())
                    }
                    self._mark_type_cache_dirty()
                return r
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as e:
                wait_time = 2.0 + attempt * 1.0
                self.diag(f"GET {path} attempt={attempt+1} exception={type(e).__name__} wait={wait_time}s")
                print(f"Netzwerkfehler bei {path} (Versuch {attempt+1}/6): {type(e).__name__}. Warte {wait_time}s...")
                time.sleep(wait_time)
                continue
        if last_response is not None:
            self.diag(f"GET {path} exhausted retries, returning last HTTP {last_response.status_code}")
            return last_response
        self.diag(f"GET {path} exhausted retries without HTTP response")
        raise RuntimeError(f"ESI GET fehlgeschlagen ohne HTTP-Response: {path}")

    def esi_post(self, path: str, json_body, auth: bool = False) -> requests.Response:
        url = self.base_url + path
        headers = {"User-Agent": self.user_agent}
        if auth:
            self.refresh_token_if_needed()
            headers["Authorization"] = "Bearer " + self.token["access_token"]

        last_response = None
        for attempt in range(6):
            try:
                self._pace_before_request(f"POST {path}")
                t0 = time.time()
                self.diag(f"POST {path} attempt={attempt+1}/6 auth={auth}")
                r = self.session.post(url, json=json_body, headers=headers, timeout=60)
                dt = time.time() - t0
                last_response = r
                self.diag(f"POST {path} attempt={attempt+1} -> HTTP {r.status_code} in {dt:.2f}s")
                if r.status_code == 420:
                    wait = int(r.headers.get("X-Esi-Error-Limit-Reset", "2"))
                    sleep_for = max(wait, 2) + self.rate_limit_cooldown_sec
                    self._set_global_cooldown(sleep_for, f"POST {path}")
                    self.diag(f"POST {path} rate-limited (420), wait={sleep_for:.2f}s")
                    time.sleep(sleep_for)
                    continue
                if r.status_code >= 500:
                    self.diag(f"POST {path} server error HTTP {r.status_code}, retry")
                    time.sleep(2.0 + attempt * 0.5)
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as e:
                wait_time = 2.0 + attempt * 1.0
                self.diag(f"POST {path} attempt={attempt+1} exception={type(e).__name__} wait={wait_time}s")
                print(f"Netzwerkfehler bei {path} (Versuch {attempt+1}/6): {type(e).__name__}. Warte {wait_time}s...")
                time.sleep(wait_time)
                continue
        if last_response is not None:
            self.diag(f"POST {path} exhausted retries, returning last HTTP {last_response.status_code}")
            return last_response
        self.diag(f"POST {path} exhausted retries without HTTP response")
        raise RuntimeError(f"ESI POST fehlgeschlagen ohne HTTP-Response: {path}")

    def preflight_structure_request(self, structure_id: int) -> None:
        """Early fail fast check before long paginated pulls."""
        self.diag(f"preflight_structure_request start structure_id={structure_id}")
        self.refresh_token_if_needed()
        url = self.base_url + f"/markets/structures/{structure_id}/"
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": "Bearer " + self.token["access_token"]
        }
        t0 = time.time()
        r = self.session.get(url, params={"page": 1}, headers=headers, timeout=30)
        self.diag(
            f"preflight_structure_request structure_id={structure_id} "
            f"HTTP {r.status_code} in {time.time()-t0:.2f}s"
        )
        if r.status_code == 420:
            reset_s = int(r.headers.get("X-Esi-Error-Limit-Reset", "60"))
            die(
                f"ESI Error-Limit aktiv (HTTP 420) vor Start fuer Struktur {structure_id}. "
                f"Bitte ca. {reset_s}s warten und erneut starten."
            )
        if r.status_code in (401, 403):
            die(f"Kein Zugriff auf Struktur {structure_id} (HTTP {r.status_code}).")
        if r.status_code != 200:
            die(f"Preflight fehlgeschlagen fuer Struktur {structure_id}: HTTP {r.status_code} {r.text}")
        self.diag(f"preflight_structure_request ok structure_id={structure_id}")

    def fetch_structure_orders(self, structure_id: int) -> list[dict]:
        ckpt_path = os.path.join(CACHE_DIR, f"orders_{structure_id}_checkpoint.json")
        checkpoint = load_json(ckpt_path, None)
        if isinstance(checkpoint, dict) and int(checkpoint.get("structure_id", 0)) == int(structure_id):
            orders = list(checkpoint.get("orders", []))
            page = int(checkpoint.get("next_page", 1))
            pages = checkpoint.get("pages")
            self.diag(
                f"fetch_structure_orders resume structure_id={structure_id} "
                f"next_page={page} cached_orders={len(orders)}"
            )
        else:
            orders = []
            page = 1
            pages = None
        self.diag(f"fetch_structure_orders start structure_id={structure_id}")
        while True:
            last_error = None
            response = None
            for attempt in range(1, 9):
                try:
                    self.diag(f"fetch_structure_orders structure={structure_id} page={page} attempt={attempt}/8")
                    response = self.esi_get(f"/markets/structures/{structure_id}/", params={"page": page}, auth=True)
                    if response.status_code == 200:
                        break
                    last_error = f"HTTP {response.status_code}"
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                wait_s = min(20.0, 1.5 * attempt)
                print(
                    f"Struktur {structure_id} Seite {page}: Versuch {attempt}/8 fehlgeschlagen"
                    f" ({last_error}). Warte {wait_s:.1f}s..."
                )
                time.sleep(wait_s)

            if response is None or response.status_code != 200:
                die(
                    f"ESI Fehler beim Laden der Struktur {structure_id} auf Seite {page}. "
                    f"Letzter Fehler: {last_error}. Bereits geladene Orders: {len(orders)}"
                )

            data = response.json()
            orders.extend(data)
            pages = int(response.headers.get("X-Pages", "1"))
            save_json(
                ckpt_path,
                {
                    "structure_id": int(structure_id),
                    "next_page": int(page + 1),
                    "pages": int(pages),
                    "orders": orders
                }
            )
            self.diag(
                f"fetch_structure_orders structure={structure_id} page={page}/{pages} "
                f"orders_this_page={len(data)} total_orders={len(orders)}"
            )
            if pages > 1 and page % 10 == 0:
                print(f"    Struktur {structure_id}: Seite {page}/{pages} geladen...")
            if page >= pages:
                break
            page += 1
        if os.path.exists(ckpt_path):
            try:
                os.remove(ckpt_path)
            except Exception:
                pass
        self.diag(f"fetch_structure_orders done structure_id={structure_id} total_orders={len(orders)}")
        return orders

    def fetch_region_orders(self, region_id: int, order_type: str = "all") -> list[dict]:
        rid = int(region_id)
        ot = str(order_type or "all").lower()
        if ot not in ("all", "buy", "sell"):
            ot = "all"
        orders: list[dict] = []
        page = 1
        pages = None
        while True:
            params = {"order_type": ot, "page": page}
            response = self.esi_get(f"/markets/{rid}/orders/", params=params, auth=False)
            if response.status_code != 200:
                break
            data = response.json()
            if isinstance(data, list):
                orders.extend(data)
            pages = int(response.headers.get("X-Pages", "1"))
            if page >= pages:
                break
            page += 1
        return orders

    def get_location_orders(
        self,
        region_id: int,
        location_id: int,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        rid = int(region_id)
        lid = int(location_id)
        tset = set(int(x) for x in type_ids) if type_ids else None
        order_types = ["sell", "buy"] if str(order_type or "all").lower() == "all" else [str(order_type or "all").lower()]
        out: list[dict] = []
        for ot in order_types:
            region_orders = self.fetch_region_orders(rid, ot)
            for o in region_orders:
                try:
                    if int(o.get("location_id", 0) or 0) != lid:
                        continue
                    if tset is not None and int(o.get("type_id", 0) or 0) not in tset:
                        continue
                except Exception:
                    continue
                out.append(o)
        return out

    def get_jita_44_orders(
        self,
        region_id: int = 10000002,
        location_id: int = 60003760,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        return self.get_location_orders(
            region_id=int(region_id),
            location_id=int(location_id),
            order_type=str(order_type or "all"),
            type_ids=type_ids,
        )

    def resolve_type_names(self, type_ids: list[int]) -> dict[int, str]:
        # 1) try bulk resolve via /universe/names (in chunks to avoid timeout)
        missing = [tid for tid in type_ids if self.type_cache.get(str(tid), {}).get("name") is None]
        self._perf_stats["type_name_cache_hits"] += max(0, len(type_ids) - len(missing))
        if missing:
            # Process in chunks of 500 to avoid oversized requests
            chunk_size = 500
            for i in range(0, len(missing), chunk_size):
                chunk = missing[i:i+chunk_size]
                try:
                    r = self.esi_post("/universe/names/", chunk, auth=False)
                    if r.status_code == 200:
                        for obj in r.json():
                            if obj.get("category") == "inventory_type":
                                tid = int(obj["id"])
                                self.type_cache.setdefault(str(tid), {})["name"] = obj.get("name", f"type_{tid}")
                                self._perf_stats["type_name_network_fetches"] += 1
                except Exception as e:
                    print(f"Fehler bei Bulk-Abfrage: {e}. Verwende Einzelabfragen...")
                    break

        # 2) fallback per type via /universe/types/{type_id}
        still_missing = [tid for tid in type_ids if self.type_cache.get(str(tid), {}).get("name") is None]
        for idx, tid in enumerate(still_missing):
            try:
                r = self.esi_get(f"/universe/types/{tid}/", auth=False)
                if r.status_code == 200:
                    data = r.json()
                    entry = self.type_cache.setdefault(str(tid), {})
                    entry["name"] = data.get("name", f"type_{tid}")
                    if "volume" not in entry:
                        try:
                            entry["volume"] = float(data.get("packaged_volume") or data.get("volume") or 1.0)
                        except Exception:
                            entry["volume"] = 1.0
                    self._perf_stats["type_name_network_fetches"] += 1
                else:
                    self.type_cache.setdefault(str(tid), {})["name"] = f"type_{tid}"
            except Exception as e:
                print(f"Fehler bei Typ {tid}: {e}. Verwende Default-Name.")
                self.type_cache.setdefault(str(tid), {})["name"] = f"type_{tid}"
            
            # Progress indicator alle 50 Typen
            if (idx + 1) % 50 == 0:
                print(f"Typ-Namen aufloesen: {idx + 1}/{len(still_missing)}...")

        self._mark_type_cache_dirty(delta=max(1, len(still_missing)), flush_threshold=200)

        return {tid: self.type_cache.get(str(tid), {}).get("name", f"type_{tid}") for tid in type_ids}

    def resolve_type_volume(self, type_id: int) -> float:
        entry = self.type_cache.get(str(type_id), {})
        if "volume" in entry:
            self._perf_stats["type_volume_cache_hits"] += 1
            return float(entry["volume"])

        try:
            r = self.esi_get(f"/universe/types/{type_id}/", auth=False)
            if r.status_code != 200:
                vol = 1.0
            else:
                obj = r.json()
                vol = float(obj.get("packaged_volume") or obj.get("volume") or 1.0)
                if self.type_cache.get(str(type_id), {}).get("name") is None:
                    self.type_cache.setdefault(str(type_id), {})["name"] = obj.get("name", f"type_{type_id}")
                self._perf_stats["type_volume_network_fetches"] += 1
        except Exception as e:
            print(f"Fehler beim Aufloesen von Volumen fuer Typ {type_id}: {e}. Verwende Default.")
            vol = 1.0

        self.type_cache.setdefault(str(type_id), {})["volume"] = vol
        self._mark_type_cache_dirty()
        return vol

    def preload_market_prices(self) -> None:
        if bool(getattr(self, "_market_prices_loaded", False)):
            return
        try:
            r = self.esi_get("/markets/prices/", auth=False)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for obj in data:
                        try:
                            tid = int(obj.get("type_id", 0))
                        except Exception:
                            continue
                        if tid <= 0:
                            continue
                        entry = self.type_cache.setdefault(str(tid), {})
                        if "average_price" in obj:
                            try:
                                entry["average_price"] = float(obj.get("average_price", 0.0) or 0.0)
                            except Exception:
                                pass
                        if "adjusted_price" in obj:
                            try:
                                entry["adjusted_price"] = float(obj.get("adjusted_price", 0.0) or 0.0)
                            except Exception:
                                pass
                    self.type_cache["_market_prices_cached_at"] = int(time.time())
                    self._mark_type_cache_dirty(delta=max(1, len(data)), flush_threshold=1)
        except Exception:
            pass
        finally:
            self._market_prices_loaded = True

    def get_market_reference_price(
        self,
        type_id: int,
        prefer: str = "average_price",
        fallback_to_adjusted: bool = True
    ) -> tuple[float, str, float, float]:
        self.preload_market_prices()
        entry = self.type_cache.get(str(int(type_id)), {})
        avg = float(entry.get("average_price", 0.0) or 0.0)
        adj = float(entry.get("adjusted_price", 0.0) or 0.0)
        pref = str(prefer or "average_price").lower()
        if pref == "adjusted_price":
            if adj > 0:
                return adj, "adjusted_price", avg, adj
            if fallback_to_adjusted and avg > 0:
                return avg, "average_price", avg, adj
            return 0.0, "", avg, adj
        if avg > 0:
            return avg, "average_price", avg, adj
        if fallback_to_adjusted and adj > 0:
            return adj, "adjusted_price", avg, adj
        return 0.0, "", avg, adj

    def get_region_history_stats(self, region_id: int, type_id: int, days: int = 30) -> dict:
        """Return market history stats from regional history endpoint."""
        rid = int(region_id)
        tid = int(type_id)
        days_i = int(days)
        cache_key = f"hist_stats_region_{rid}_{tid}_{days_i}"
        if cache_key in self.type_cache:
            self._perf_stats["history_cache_hits"] += 1
            self._perf_stats["history_served_from_cache"] += 1
            return self.type_cache[cache_key]

        missing_key = f"hist_missing_region_{rid}_{tid}"
        if bool(self.type_cache.get(missing_key, False)):
            self._perf_stats["history_negative_cache_hits"] += 1
            self._perf_stats["history_skipped_negative"] += 1
            stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing": True}
            self.type_cache[cache_key] = stats
            return stats

        raw_key = f"hist_raw_region_{rid}_{tid}"
        history = self.type_cache.get(raw_key)
        if isinstance(history, list):
            self._perf_stats["history_raw_cache_hits"] += 1
        else:
            self._perf_stats["history_requests_total"] += 1
            try:
                r = self.esi_get(f"/markets/{rid}/history/", params={"type_id": tid}, auth=False)
            except Exception:
                r = None
            if r is None:
                stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                self.type_cache[cache_key] = stats
                return stats
            if r.status_code == 404:
                self._perf_stats["history_http_404"] += 1
                self.type_cache[missing_key] = True
                stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing": True}
                self.type_cache[cache_key] = stats
                self._mark_type_cache_dirty()
                return stats
            if r.status_code != 200:
                stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                self.type_cache[cache_key] = stats
                return stats
            try:
                history = r.json()
            except Exception:
                history = []
            if not isinstance(history, list):
                history = []
            self.type_cache[raw_key] = history
            self._mark_type_cache_dirty()

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_i)
            recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            total_vol = 0
            total_orders = 0
            days_with = 0
            recent = False
            seen_dates = set()
            for entry in history:
                date_s = str(entry.get("date", "")).strip()
                try:
                    dt = datetime.fromisoformat(date_s.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                vol = int(entry.get("volume", 0) or 0)
                order_count = int(entry.get("order_count", 0) or 0)
                if dt >= cutoff:
                    total_vol += vol
                    total_orders += order_count
                    if dt.date() not in seen_dates and vol > 0:
                        days_with += 1
                        seen_dates.add(dt.date())
                if dt >= recent_cutoff and vol > 0:
                    recent = True
            stats = {
                "volume": int(total_vol),
                "order_count": int(total_orders),
                "days_with_trades": int(days_with),
                "recent_activity": bool(recent),
            }
            self.type_cache[cache_key] = stats
            self._mark_type_cache_dirty()
            return stats
        except Exception:
            stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
            self.type_cache[cache_key] = stats
            return stats

    def get_market_history_stats(self, structure_id: int, type_id: int, days: int = 30) -> dict:
        """Backward compatible wrapper that maps structure id to region id."""
        sid = int(structure_id)
        region_id = 0
        if isinstance(self.structure_region_map, dict) and self.structure_region_map:
            region_id = int(self.structure_region_map.get(int(sid), 0) or 0)
        if region_id <= 0:
            region_map = self.type_cache.get("_structure_region_map", {})
            if isinstance(region_map, dict):
                try:
                    region_id = int(region_map.get(str(sid), region_map.get(int(sid), 0)) or 0)
                except Exception:
                    region_id = 0
        if region_id <= 0:
            try:
                region_id = int(self.type_cache.get(f"_sid_region_{sid}", 0) or 0)
            except Exception:
                region_id = 0
        if region_id <= 0:
            stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing_region": True}
            cache_key = f"hist_stats_region_missing_{sid}_{int(type_id)}_{int(days)}"
            self.type_cache[cache_key] = stats
            return stats
        return self.get_region_history_stats(region_id, int(type_id), int(days))

    def get_performance_summary_lines(self) -> list[str]:
        s = dict(self._perf_stats)
        return [
            "PERFORMANCE SUMMARY:",
            f"  history_requests_total: {int(s.get('history_requests_total', 0))}",
            f"  history_http_404: {int(s.get('history_http_404', 0))}",
            f"  history_cache_hits: {int(s.get('history_cache_hits', 0))}",
            f"  history_raw_cache_hits: {int(s.get('history_raw_cache_hits', 0))}",
            f"  history_negative_cache_hits: {int(s.get('history_negative_cache_hits', 0))}",
            f"  history_skipped_negative: {int(s.get('history_skipped_negative', 0))}",
            f"  history_served_from_cache: {int(s.get('history_served_from_cache', 0))}",
            f"  type_name_cache_hits: {int(s.get('type_name_cache_hits', 0))}",
            f"  type_name_network_fetches: {int(s.get('type_name_network_fetches', 0))}",
            f"  type_volume_cache_hits: {int(s.get('type_volume_cache_hits', 0))}",
            f"  type_volume_network_fetches: {int(s.get('type_volume_network_fetches', 0))}",
        ]

    def get_market_history_volume(self, structure_id: int, type_id: int, days: int = 30) -> int:
        """Backward-compatible helper; delegates to get_market_history_stats."""
        stats = self.get_market_history_stats(structure_id, type_id, days)
        if isinstance(stats, dict):
            return int(stats.get("volume", 0) or 0)
        try:
            return int(stats)
        except Exception:
            return 0


class ReplayESIClient:
    """Offline replacement for ESIClient using a persisted type/history cache."""
    def __init__(self, type_cache: dict | None = None):
        self.type_cache = type_cache or {}
        self.structure_region_map: dict[int, int] = {}

    def resolve_type_names(self, type_ids: list[int]) -> dict[int, str]:
        result = {}
        for tid in type_ids:
            result[tid] = self.type_cache.get(str(tid), {}).get("name", f"type_{tid}")
        return result

    def resolve_type_volume(self, type_id: int) -> float:
        entry = self.type_cache.get(str(type_id), {})
        try:
            return float(entry.get("volume", 1.0))
        except Exception:
            return 1.0

    def get_region_history_stats(self, region_id: int, type_id: int, days: int = 30) -> dict:
        key = f"hist_stats_region_{region_id}_{type_id}_{days}"
        stats = self.type_cache.get(key)
        if isinstance(stats, dict):
            return stats
        return {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}

    def get_market_history_stats(self, structure_id: int, type_id: int, days: int = 30) -> dict:
        region_id = 0
        if isinstance(self.structure_region_map, dict) and self.structure_region_map:
            region_id = int(self.structure_region_map.get(int(structure_id), 0) or 0)
        if region_id <= 0:
            region_map = self.type_cache.get("_structure_region_map", {})
            if isinstance(region_map, dict):
                try:
                    region_id = int(region_map.get(str(int(structure_id)), region_map.get(int(structure_id), 0)) or 0)
                except Exception:
                    region_id = 0
        if region_id <= 0:
            try:
                region_id = int(self.type_cache.get(f"_sid_region_{int(structure_id)}", 0) or 0)
            except Exception:
                region_id = 0
        if region_id <= 0:
            return {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing_region": True}
        return self.get_region_history_stats(region_id, type_id, days)

    def preload_market_prices(self) -> None:
        return

    def get_market_reference_price(
        self,
        type_id: int,
        prefer: str = "average_price",
        fallback_to_adjusted: bool = True
    ) -> tuple[float, str, float, float]:
        entry = self.type_cache.get(str(int(type_id)), {})
        avg = float(entry.get("average_price", 0.0) or 0.0)
        adj = float(entry.get("adjusted_price", 0.0) or 0.0)
        pref = str(prefer or "average_price").lower()
        if pref == "adjusted_price":
            if adj > 0:
                return adj, "adjusted_price", avg, adj
            if fallback_to_adjusted and avg > 0:
                return avg, "average_price", avg, adj
            return 0.0, "", avg, adj
        if avg > 0:
            return avg, "average_price", avg, adj
        if fallback_to_adjusted and adj > 0:
            return adj, "adjusted_price", avg, adj
        return 0.0, "", avg, adj

    def get_performance_summary_lines(self) -> list[str]:
        return ["PERFORMANCE SUMMARY:", "  replay_mode: no_live_request_metrics"]

    def fetch_region_orders(self, region_id: int, order_type: str = "all") -> list[dict]:
        key = f"replay_region_orders_{int(region_id)}_{str(order_type or 'all').lower()}"
        data = self.type_cache.get(key, [])
        return list(data) if isinstance(data, list) else []

    def get_location_orders(
        self,
        region_id: int,
        location_id: int,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        # Replay payload usually stores final orders per id in snapshot structures map.
        # This method is a fallback for tests that mock region-order payloads in type_cache.
        rid = int(region_id)
        lid = int(location_id)
        tset = set(int(x) for x in type_ids) if type_ids else None
        order_types = ["sell", "buy"] if str(order_type or "all").lower() == "all" else [str(order_type or "all").lower()]
        out: list[dict] = []
        for ot in order_types:
            for o in self.fetch_region_orders(rid, ot):
                try:
                    if int(o.get("location_id", 0) or 0) != lid:
                        continue
                    if tset is not None and int(o.get("type_id", 0) or 0) not in tset:
                        continue
                except Exception:
                    continue
                out.append(o)
        return out

    def get_jita_44_orders(
        self,
        region_id: int = 10000002,
        location_id: int = 60003760,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        return self.get_location_orders(
            region_id=int(region_id),
            location_id=int(location_id),
            order_type=str(order_type or "all"),
            type_ids=type_ids,
        )


def build_levels(orders: list[dict], is_buy: bool) -> list[OrderLevel]:
    levels = {}
    for o in orders:
        if bool(o.get("is_buy_order")) != is_buy:
            continue
        price = float(o["price"])
        vol = int(o["volume_remain"])
        if vol <= 0:
            continue
        levels[price] = levels.get(price, 0) + vol

    if is_buy:
        prices = sorted(levels.keys(), reverse=True)
    else:
        prices = sorted(levels.keys())

    return [OrderLevel(p, levels[p]) for p in prices]


def get_structure_micro_liquidity(structure_orders: list[dict], type_id: int) -> dict:
    tid = int(type_id)
    buy_orders = [o for o in structure_orders if int(o.get("type_id", 0)) == tid and bool(o.get("is_buy_order"))]
    sell_orders = [o for o in structure_orders if int(o.get("type_id", 0)) == tid and not bool(o.get("is_buy_order"))]
    buy_levels = build_levels(buy_orders, is_buy=True)
    sell_levels = build_levels(sell_orders, is_buy=False)
    if not buy_levels and not sell_levels:
        return {
            "spread_pct": 1.0,
            "depth_within_2pct_buy": 0,
            "depth_within_2pct_sell": 0,
            "orderbook_imbalance": 0.0,
            "competition_density_near_best": 0,
        }

    best_bid = float(buy_levels[0].price) if buy_levels else 0.0
    best_ask = float(sell_levels[0].price) if sell_levels else 0.0

    spread_pct = 1.0
    if best_bid > 0 and best_ask > 0:
        mid = (best_bid + best_ask) / 2.0
        spread_pct = ((best_ask - best_bid) / mid) if mid > 0 else 1.0

    depth_within_2pct_buy = 0
    if best_bid > 0:
        cutoff_bid = best_bid * 0.98
        depth_within_2pct_buy = int(sum(int(lv.volume) for lv in buy_levels if float(lv.price) >= cutoff_bid))

    depth_within_2pct_sell = 0
    if best_ask > 0:
        cutoff_ask = best_ask * 1.02
        depth_within_2pct_sell = int(sum(int(lv.volume) for lv in sell_levels if float(lv.price) <= cutoff_ask))

    total_buy = int(sum(int(lv.volume) for lv in buy_levels))
    total_sell = int(sum(int(lv.volume) for lv in sell_levels))
    denom = max(1, total_buy + total_sell)
    orderbook_imbalance = float(total_buy - total_sell) / float(denom)

    competition_density_near_best = 0
    if best_ask > 0:
        near_best_cutoff = best_ask * 1.002
        competition_density_near_best = int(sum(1 for lv in sell_levels if float(lv.price) <= near_best_cutoff))

    return {
        "spread_pct": float(spread_pct),
        "depth_within_2pct_buy": int(depth_within_2pct_buy),
        "depth_within_2pct_sell": int(depth_within_2pct_sell),
        "orderbook_imbalance": float(orderbook_imbalance),
        "competition_density_near_best": int(competition_density_near_best),
    }


def depth_slice(
    levels: list[OrderLevel],
    is_buy: bool,
    depth_pct: float,
    outlier_ratio: float = 0.25,
    outlier_window_levels: int = 5,
    min_top_level_units: int = 0
) -> tuple[float, int]:
    if not levels:
        return 0.0, 0

    # Robust top-of-book sanity:
    # - filter tiny top-levels
    # - compare best against median of next N levels (more stable than best-vs-second only)
    import statistics
    sanity_levels = list(levels)
    max_prunes = min(3, max(0, len(sanity_levels) - 1))
    for _ in range(max_prunes):
        if len(sanity_levels) < 2:
            break
        drop_best = False
        best_level = sanity_levels[0]
        if min_top_level_units > 0 and int(best_level.volume) < min_top_level_units:
            drop_best = True

        window_n = max(1, int(outlier_window_levels))
        next_window = sanity_levels[1:1 + window_n]
        if next_window:
            median_next = statistics.median([lv.price for lv in next_window])
            ratio = max(1e-6, float(outlier_ratio))
            if median_next > 0:
                if not is_buy and best_level.price < median_next * ratio:
                    drop_best = True
                elif is_buy and best_level.price > (median_next / ratio):
                    drop_best = True

        if drop_best:
            sanity_levels = sanity_levels[1:]
            continue
        break
    if not sanity_levels:
        sanity_levels = levels

    best = sanity_levels[0].price
    if is_buy:
        cutoff = best * (1.0 - depth_pct)
        selected = [lv for lv in sanity_levels if lv.price >= cutoff]
    else:
        cutoff = best * (1.0 + depth_pct)
        selected = [lv for lv in sanity_levels if lv.price <= cutoff]

    total_qty = sum(lv.volume for lv in selected)
    if total_qty <= 0:
        return 0.0, 0

    weighted = sum(lv.price * lv.volume for lv in selected)
    avg = weighted / total_qty
    return avg, total_qty


def apply_strategy_filters(cfg: dict, filters: dict) -> dict:
    """Merge strategy-mode constraints into route filters."""
    merged = dict(filters)
    strategy_cfg = cfg.get("strategy", {})
    mode = strategy_cfg.get("mode", "balanced")
    mode_params = strategy_cfg.get("strategy_modes", {}).get(mode, {})
    orderbook_cfg = cfg.get("orderbook", {})

    if "min_profit_pct" in mode_params:
        merged["min_profit_pct"] = max(float(merged.get("min_profit_pct", 0.0)), float(mode_params["min_profit_pct"]))
    if "min_profit_pct_boost" in mode_params:
        merged["min_profit_pct"] = float(merged.get("min_profit_pct", 0.0)) + float(mode_params["min_profit_pct_boost"])
    if "liquidity_min_score" in mode_params:
        merged["min_liquidity_score"] = max(
            int(merged.get("min_liquidity_score", 0)),
            int(mode_params["liquidity_min_score"])
        )
    if "min_history_volume" in mode_params:
        merged["min_market_history_volume"] = max(
            int(merged.get("min_market_history_volume", 0)),
            int(mode_params["min_history_volume"])
        )
    for k in (
        "outlier_ratio",
        "outlier_window_levels",
        "min_top_level_units",
        "min_source_sell_price_isk",
        "min_units_in_window",
        "window_levels_for_units"
    ):
        if k not in merged and k in orderbook_cfg:
            merged[k] = orderbook_cfg[k]
    return merged


def compute_candidates(
    esi: ESIClient | ReplayESIClient,
    source_orders: list[dict],
    dest_orders: list[dict],
    fees: dict,
    filters: dict,
    dest_structure_id: int | None = None,
    dest_region_id: int | None = None,
    route_context: dict | None = None,
    funnel: "FilterFunnel | None" = None,
    explain: dict | None = None
) -> list[TradeCandidate]:
    import math
    # support two modes: instant (sell to existing buy orders) and
    # fast_sell (create a sell order at destination, undercutting best price)
    mode = str(filters.get("mode", "instant")).lower()
    if mode not in ("instant", "fast_sell", "planned_sell"):
        mode = "instant"
    depth_pct = float(filters["price_depth_pct"])
    min_depth_units = int(filters["min_depth_units"])
    min_profit_pct = float(filters["min_profit_pct"])
    min_profit_total = float(filters["min_profit_isk_total"])
    undercut_pct = float(filters.get("undercut_pct", 0.001))
    outlier_ratio = float(filters.get("outlier_ratio", 0.25))
    outlier_window_levels = int(filters.get("outlier_window_levels", 5))
    min_top_level_units = int(filters.get("min_top_level_units", 0))
    min_source_sell_price_isk = float(filters.get("min_source_sell_price_isk", 0.0))
    min_units_in_window = int(filters.get("min_units_in_window", 0))
    window_levels_for_units = int(filters.get("window_levels_for_units", 5))
    competition_band_pct = float(filters.get("competition_band_pct", 0.02))
    max_turnover_factor = float(filters.get("max_turnover_factor", 3.0))
    min_fill_probability = float(filters.get("min_fill_probability", 0.0))
    min_instant_fill_ratio = float(filters.get("min_instant_fill_ratio", 0.0))
    min_dest_buy_depth_units = int(filters.get("min_dest_buy_depth_units", 0))
    fallback_daily_volume = float(filters.get("fallback_daily_volume", 0.1))
    explain_max_entries = int(filters.get("explain_max_entries", 2000))
    # optional duration for suggested sell orders (days)
    order_duration = int(filters.get("order_duration_days", 90))
    min_liquidity_score = int(filters.get("min_liquidity_score", 0))
    history_probe_enabled = bool(filters.get("history_probe_enabled", mode == "planned_sell"))
    horizon_days = int(filters.get("horizon_days", 90))
    history_days = int(filters.get("history_days", 30))
    min_expected_profit_isk = float(filters.get("min_expected_profit_isk", 0.0))
    max_expected_days_to_sell = float(filters.get("max_expected_days_to_sell", 99999.0))
    min_sell_through_ratio_90d = float(filters.get("min_sell_through_ratio_90d", 0.0))
    min_avg_daily_volume = float(filters.get("min_avg_daily_volume", 0.0))
    fallback_volume_penalty = float(filters.get("fallback_volume_penalty", 0.35))
    fallback_fill_probability_cap = float(filters.get("fallback_fill_probability_cap", 0.20))
    fallback_max_units_cap = int(filters.get("fallback_max_units_cap", 5))
    fallback_require_high_profit_pct = float(filters.get("fallback_require_high_profit_pct", 0.12))
    relist_budget_pct = float(filters.get("relist_budget_pct", fees.get("relist_budget_pct", 0.0)))
    relist_budget_isk = float(filters.get("relist_budget_isk", fees.get("relist_budget_isk", 0.0)))
    min_history_order_count = int(filters.get("min_market_history_order_count", 1))
    min_depth_within_2pct_sell = int(filters.get("min_depth_within_2pct_sell", 1))
    max_competition_density_near_best = int(filters.get("max_competition_density_near_best", 8))
    reference_cfg = filters.get("reference_price", {})
    if not isinstance(reference_cfg, dict):
        reference_cfg = {}
    ref_enabled = bool(reference_cfg.get("enabled", False))
    ref_prefer = str(reference_cfg.get("prefer", "average_price")).lower()
    ref_fallback_to_adjusted = bool(reference_cfg.get("fallback_to_adjusted", True))
    ref_soft_sell_markup = float(reference_cfg.get("soft_sell_markup_vs_ref_planned", 0.50))
    ref_max_sell_markup = float(reference_cfg.get("max_sell_markup_vs_ref_planned", 1.00))
    ref_hard_max_sell_markup_raw = reference_cfg.get("hard_max_sell_markup_vs_ref_planned", None)
    ref_hard_max_sell_markup = None
    if ref_hard_max_sell_markup_raw is not None:
        try:
            ref_hard_max_sell_markup = float(ref_hard_max_sell_markup_raw)
        except Exception:
            ref_hard_max_sell_markup = None
    ref_penalty_strength = float(reference_cfg.get("ranking_penalty_strength", 0.35))
    strict_cfg = filters.get("strict_mode", {})
    if not isinstance(strict_cfg, dict):
        strict_cfg = {}
    if not isinstance(route_context, dict):
        route_context = {}
    shipping_lane_cfg = route_context.get("shipping_lane_cfg") if isinstance(route_context.get("shipping_lane_cfg"), dict) else None
    jita_split_prices = route_context.get("jita_split_prices", {})
    if not isinstance(jita_split_prices, dict):
        jita_split_prices = {}
    strict_enabled = bool(strict_cfg.get("enabled", False))
    strict_require_ref_planned = bool(
        filters.get("strict_require_reference_price_for_planned", strict_cfg.get("require_reference_price_for_planned", False))
    )
    strict_disable_fallback_planned = bool(
        filters.get("strict_disable_fallback_volume_for_planned", strict_cfg.get("disable_fallback_volume_for_planned", False))
    )
    strict_min_avg_daily_volume_7d = float(
        filters.get("strict_require_avg_daily_volume_7d", strict_cfg.get("planned_min_avg_daily_volume_7d", 0.0))
    )
    strict_planned_max_units_cap = int(
        filters.get("strict_planned_max_units_cap", strict_cfg.get("planned_max_units_cap", 0))
    )
    resolved_dest_region_id = int(dest_region_id or 0)
    if resolved_dest_region_id <= 0 and dest_structure_id:
        region_map = filters.get("structure_region_map", {})
        if isinstance(region_map, dict):
            try:
                resolved_dest_region_id = int(
                    region_map.get(str(int(dest_structure_id)), region_map.get(int(dest_structure_id), 0)) or 0
                )
            except Exception:
                resolved_dest_region_id = 0
    if ref_enabled and hasattr(esi, "preload_market_prices"):
        try:
            esi.preload_market_prices()
        except Exception:
            pass

    source_sell_by_type: dict[int, list[dict]] = {}
    source_buy_by_type: dict[int, list[dict]] = {}
    for o in source_orders:
        tid = int(o["type_id"])
        if bool(o.get("is_buy_order")):
            source_buy_by_type.setdefault(tid, []).append(o)
        else:
            source_sell_by_type.setdefault(tid, []).append(o)
    dest_sell_by_type: dict[int, list[dict]] = {}
    dest_buy_by_type: dict[int, list[dict]] = {}
    for o in dest_orders:
        tid = int(o["type_id"])
        if bool(o.get("is_buy_order")):
            dest_buy_by_type.setdefault(tid, []).append(o)
        else:
            dest_sell_by_type.setdefault(tid, []).append(o)

    src_sell_types = set(source_sell_by_type.keys())
    dst_buy_types = set(dest_buy_by_type.keys())
    dst_sell_types = set(dest_sell_by_type.keys())
    if mode == "instant":
        type_ids = sorted(src_sell_types & dst_buy_types)
    elif mode == "planned_sell":
        type_ids = sorted(src_sell_types & dst_sell_types)
    else:
        type_ids = sorted(src_sell_types & dst_sell_types)
    if explain is not None:
        explain.setdefault("kept", [])
        explain.setdefault("rejected", [])
        explain.setdefault("reason_counts", {})
        explain.setdefault("_first_rejection_by_type", {})

    def record_explain(status: str, tid: int, type_name: str, reason: str, metrics: dict | None = None) -> None:
        if explain is None:
            return
        if status == "rejected":
            first_rej = explain.get("_first_rejection_by_type", {})
            if tid in first_rej:
                return
            first_rej[tid] = reason
        rc = explain["reason_counts"]
        rc[reason] = int(rc.get(reason, 0)) + 1
        bucket = explain.get(status, [])
        if len(bucket) >= explain_max_entries:
            return
        bucket.append({
            "type_id": int(tid),
            "name": type_name,
            "reason": reason,
            "metrics": metrics or {}
        })
    if funnel:
        funnel.record_stage("initial", len(type_ids))
    # remove explicitly excluded type IDs if configured
    excluded = set(int(tid) for tid in filters.get("exclude_type_ids", []))
    if excluded:
        before = len(type_ids)
        if funnel:
            for tid in type_ids:
                if tid in excluded:
                    record_explain("rejected", tid, f"type_{tid}", "excluded_type_id")
                    funnel.record_rejection(tid, f"type_{tid}", "excluded_type_id")
        type_ids = [tid for tid in type_ids if tid not in excluded]
        removed = before - len(type_ids)
        if removed:
            print(f"  {removed} Typen anhand exclude_type_ids ausgeschlossen")
    if funnel:
        funnel.record_stage("excluded_type_id", len(type_ids))
        funnel.record_stage("exclude_type_ids", len(type_ids))
    print(f"  Resolving {len(type_ids)} type names...")
    names = esi.resolve_type_names(type_ids)
    print("  Type names resolved")

    # filter out unwanted items early based on name keywords
    exclude_kw = [kw.lower() for kw in filters.get("exclude_name_keywords", [])]
    legacy_kw = [kw.lower() for kw in filters.get("exclude_keywords", [])]
    if legacy_kw:
        exclude_kw.extend(legacy_kw)
    if exclude_kw:
        # de-dup while preserving order
        seen_kw = set()
        normalized_kw = []
        for kw in exclude_kw:
            k = str(kw).strip()
            if not k or k in seen_kw:
                continue
            seen_kw.add(k)
            normalized_kw.append(k)
        exclude_kw = normalized_kw
    if exclude_kw:
        orig_count = len(type_ids)
        kept = []
        for tid in type_ids:
            item_name = names.get(tid, "").lower()
            if any(kw in item_name for kw in exclude_kw):
                record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "excluded_name_keyword")
                if funnel:
                    funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "excluded_name_keyword")
                continue
            kept.append(tid)
        type_ids = kept
        removed = orig_count - len(type_ids)
        if removed:
            print(f"  Ausgeschlossen wegen Name-Keywords: {removed} Typen")
    if funnel:
        funnel.record_stage("excluded_name_keyword", len(type_ids))
        funnel.record_stage("exclude_keywords", len(type_ids))

    # filter by market history volume / liquidity at destination if configured
    min_hist_vol = int(filters.get("min_market_history_volume", 0))
    history_scores: dict[int, int] = {}
    history_volume_30d: dict[int, int] = {}
    history_order_count_30d: dict[int, int] = {}
    if history_probe_enabled and (min_hist_vol > 0 or min_liquidity_score > 0) and resolved_dest_region_id > 0:
        orig_count = len(type_ids)
        print(
            f"  Ueberpruefe regionale Markthistorie fuer {len(type_ids)} Typen "
            f"(Region {resolved_dest_region_id}, min. {min_hist_vol} Einheiten/30d)..."
        )
        # Parallelize history checks with limited concurrency, using internal cache
        from concurrent.futures import ThreadPoolExecutor, as_completed
        filtered_type_ids = []
        # choose a modest worker count to avoid hitting rate limits
        max_workers = min(6, max(1, len(type_ids) // 200))
        max_workers = max(2, max_workers)
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for tid in type_ids:
                futures[ex.submit(esi.get_region_history_stats, resolved_dest_region_id, tid, 30)] = tid

            completed = 0
            for fut in as_completed(futures):
                tid = futures[fut]
                completed += 1
                if completed % 50 == 0:
                    print(f"    Markthistorie: {completed}/{len(type_ids)}...")
                try:
                    stats = fut.result()
                except Exception:
                    stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                if not isinstance(stats, dict):
                    try:
                        stats = {"volume": int(stats), "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                    except Exception:
                        stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                hist_vol = stats.get("volume", 0)
                hist_orders = int(stats.get("order_count", 0) or 0)
                days_with = int(stats.get("days_with_trades", 0) or 0)
                recent = bool(stats.get("recent_activity", False))
                vol_component = min(60.0, max(0.0, math.log10(max(float(hist_vol), 1.0)) * 15.0))
                days_component = min(30.0, float(days_with))
                recent_component = 10.0 if recent else 0.0
                liquidity_score = int(vol_component + days_component + recent_component)
                history_scores[tid] = liquidity_score
                history_volume_30d[tid] = int(hist_vol)
                history_order_count_30d[tid] = int(hist_orders)
                # depth will be computed later per-type; here we do a minimal filter
                # accept types that meet min_hist_vol and min_liquidity_score
                if hist_vol >= min_hist_vol and liquidity_score >= min_liquidity_score and hist_orders >= min_history_order_count:
                    filtered_type_ids.append(tid)
                elif funnel:
                    if hist_vol < min_hist_vol:
                        record_explain(
                            "rejected",
                            tid,
                            names.get(tid, f"type_{tid}"),
                            "market_history",
                            {"history_volume_30d": int(hist_vol), "min_market_history_volume": int(min_hist_vol)}
                        )
                        funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "market_history")
                    elif hist_orders < min_history_order_count:
                        record_explain(
                            "rejected",
                            tid,
                            names.get(tid, f"type_{tid}"),
                            "market_history_order_count",
                            {
                                "history_order_count_30d": int(hist_orders),
                                "min_market_history_order_count": int(min_history_order_count)
                            }
                        )
                        funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "market_history_order_count")
                    else:
                        record_explain(
                            "rejected",
                            tid,
                            names.get(tid, f"type_{tid}"),
                            "liquidity_score",
                            {"liquidity_score": int(liquidity_score), "min_liquidity_score": int(min_liquidity_score)}
                        )
                        funnel.record_rejection(tid, names.get(tid, f"type_{tid}"), "liquidity_score")
        type_ids = filtered_type_ids
        removed = orig_count - len(type_ids)
        if removed:
            print(f"  {removed} Typen wegen unzureichender Markthistorie ausgeschlossen (< {min_hist_vol} units/30d)")
    if funnel:
        funnel.record_stage("market_history", len(type_ids))
        funnel.record_stage("liquidity_score", len(type_ids))

    candidates: list[TradeCandidate] = []
    for idx, tid in enumerate(type_ids):
        if (idx + 1) % 100 == 0:
            print(f"  Verarbeite Typen: {idx + 1}/{len(type_ids)}...")
        src_lv = build_levels(source_sell_by_type.get(tid, []), is_buy=False)
        if src_lv and min_units_in_window > 0:
            window_units = int(sum(lv.volume for lv in src_lv[:max(1, window_levels_for_units)]))
            if window_units < min_units_in_window:
                record_explain(
                    "rejected",
                    tid,
                    names.get(tid, f"type_{tid}"),
                    "orderbook_window_units_too_low",
                    {
                        "window_units": int(window_units),
                        "min_units_in_window": int(min_units_in_window),
                        "window_levels_for_units": int(window_levels_for_units)
                    }
                )
                continue

        instant_flag = True
        sell_sugg = None

        target_sell_price = 0.0
        if mode == "instant":
            dst_lv = build_levels(dest_buy_by_type.get(tid, []), is_buy=True)
            if not src_lv or not dst_lv:
                # no buy orders available - try fast_sell fallback
                dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
                if not src_lv or not dst_sell_lv:
                    record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "no_orderbook")
                    continue
                buy_avg, buy_qty = depth_slice(src_lv, is_buy=False, depth_pct=depth_pct)
                best_sell_price = dst_sell_lv[0].price
                sell_avg = best_sell_price * (1.0 - undercut_pct)
                sell_qty = sum(lv.volume for lv in dst_sell_lv[:5])
                instant_flag = False
                sell_sugg = sell_avg
            else:
                buy_avg, buy_qty = depth_slice(
                    src_lv, is_buy=False, depth_pct=depth_pct,
                    outlier_ratio=outlier_ratio,
                    outlier_window_levels=outlier_window_levels,
                    min_top_level_units=min_top_level_units
                )
                sell_avg, sell_qty = depth_slice(
                    dst_lv, is_buy=True, depth_pct=depth_pct,
                    outlier_ratio=outlier_ratio,
                    outlier_window_levels=outlier_window_levels,
                    min_top_level_units=min_top_level_units
                )
        elif mode == "fast_sell":
            # fast_sell: use destination sell side and offer just under the best price
            dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
            if not src_lv or not dst_sell_lv:
                record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "no_orderbook")
                continue
            buy_avg, buy_qty = depth_slice(
                src_lv, is_buy=False, depth_pct=depth_pct,
                outlier_ratio=outlier_ratio,
                outlier_window_levels=outlier_window_levels,
                min_top_level_units=min_top_level_units
            )

            best_sell_price = dst_sell_lv[0].price
            sell_avg = best_sell_price * (1.0 - undercut_pct)
            sell_qty = sum(lv.volume for lv in dst_sell_lv[:5])
            instant_flag = False
            sell_sugg = sell_avg
        else:
            # planned_sell: buy at source now, list at destination sell side and evaluate
            # expected sell-through over horizon_days from market history.
            dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
            if not src_lv or not dst_sell_lv:
                record_explain("rejected", tid, names.get(tid, f"type_{tid}"), "no_orderbook")
                continue
            buy_avg, buy_qty = depth_slice(
                src_lv, is_buy=False, depth_pct=depth_pct,
                outlier_ratio=outlier_ratio,
                outlier_window_levels=outlier_window_levels,
                min_top_level_units=min_top_level_units
            )
            target_sell_price = float(dst_sell_lv[0].price)
            sell_avg = target_sell_price
            sell_qty = int(buy_qty)
            instant_flag = False
            sell_sugg = target_sell_price

        max_units = min(buy_qty, sell_qty)
        if buy_avg < min_source_sell_price_isk:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "orderbook_min_source_sell_price",
                {
                    "buy_avg_price": float(buy_avg),
                    "min_source_sell_price_isk": float(min_source_sell_price_isk)
                }
            )
            continue
        if max_units < min_depth_units:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "min_depth_units",
                {"max_units": int(max_units), "min_depth_units": int(min_depth_units)}
            )
            continue

        unit_vol = esi.resolve_type_volume(tid)
        if unit_vol <= 0:
            unit_vol = 1.0

        cost_net, revenue_net, profit_per_unit, _ = compute_trade_financials(
            buy_avg,
            sell_avg,
            1,
            fees,
            instant_flag,
            execution_mode=mode,
            relist_budget_pct=relist_budget_pct,
            relist_budget_isk=(relist_budget_isk if mode == "planned_sell" else 0.0),
        )
        if profit_per_unit <= 0:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "non_positive_profit_90d" if mode == "planned_sell" else "non_positive_profit",
                {"profit_per_unit": float(profit_per_unit)}
            )
            continue

        profit_pct = profit_per_unit / cost_net if cost_net > 0 else 0.0
        if profit_pct < min_profit_pct:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "min_profit_pct",
                {"profit_pct": float(profit_pct), "min_profit_pct": float(min_profit_pct)}
            )
            continue

        name = names.get(tid, f"type_{tid}")
        hist_vol_30d = int(history_volume_30d.get(tid, 0))
        hist_orders_30d = int(history_order_count_30d.get(tid, 0))
        hist_vol_7d = 0
        used_volume_fallback = False
        reference_price = 0.0
        reference_price_average = 0.0
        reference_price_adjusted = 0.0
        reference_price_source = ""
        buy_discount_vs_ref = 0.0
        sell_markup_vs_ref = 0.0
        reference_price_penalty = 0.0
        strict_confidence_score = 0.0
        avg_daily_volume_7d = 0.0
        micro_liq = get_structure_micro_liquidity(dest_orders, tid)
        spread_pct = float(micro_liq.get("spread_pct", 1.0))
        depth_within_2pct_buy = int(micro_liq.get("depth_within_2pct_buy", 0))
        depth_within_2pct_sell = int(micro_liq.get("depth_within_2pct_sell", 0))
        orderbook_imbalance = float(micro_liq.get("orderbook_imbalance", 0.0))
        competition_density_near_best = int(micro_liq.get("competition_density_near_best", 0))
        if ref_enabled and hasattr(esi, "get_market_reference_price"):
            try:
                rp, rp_source, rp_avg, rp_adj = esi.get_market_reference_price(
                    tid, prefer=ref_prefer, fallback_to_adjusted=ref_fallback_to_adjusted
                )
            except Exception:
                rp, rp_source, rp_avg, rp_adj = 0.0, "", 0.0, 0.0
            reference_price = float(rp or 0.0)
            reference_price_source = str(rp_source or "")
            reference_price_average = float(rp_avg or 0.0)
            reference_price_adjusted = float(rp_adj or 0.0)
            if reference_price > 0:
                buy_discount_vs_ref = (reference_price - float(buy_avg)) / reference_price
                planned_price = float(target_sell_price if target_sell_price > 0 else sell_avg)
                sell_markup_vs_ref = (planned_price - reference_price) / reference_price
                if (
                    mode == "planned_sell"
                    and ref_hard_max_sell_markup is not None
                    and sell_markup_vs_ref > ref_hard_max_sell_markup
                ):
                    record_explain(
                        "rejected",
                        tid,
                        names.get(tid, f"type_{tid}"),
                        "strict_reference_price_hard_sell_markup" if strict_enabled else "reference_price_hard_sell_markup",
                        {
                            "sell_markup_vs_ref": float(sell_markup_vs_ref),
                            "hard_max_sell_markup_vs_ref_planned": float(ref_hard_max_sell_markup),
                            "reference_price": float(reference_price),
                            "planned_sell_price": float(planned_price)
                        }
                    )
                    continue
                if mode == "planned_sell" and sell_markup_vs_ref > ref_soft_sell_markup:
                    hard = max(ref_max_sell_markup, ref_soft_sell_markup + 1e-9)
                    ramp = (sell_markup_vs_ref - ref_soft_sell_markup) / max(1e-9, hard - ref_soft_sell_markup)
                    ramp = max(0.0, min(1.0, ramp))
                    reference_price_penalty = ramp * max(0.0, min(1.0, ref_penalty_strength))
        if mode == "planned_sell" and strict_enabled and strict_require_ref_planned and reference_price <= 0.0:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "strict_missing_reference_price"
            )
            continue
        if mode == "planned_sell" and ref_enabled and reference_price > 0.0 and sell_markup_vs_ref > ref_max_sell_markup:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "reference_price_plausibility",
                {
                    "sell_markup_vs_ref": float(sell_markup_vs_ref),
                    "max_sell_markup_vs_ref_planned": float(ref_max_sell_markup),
                    "reference_price": float(reference_price),
                    "target_sell_price": float(target_sell_price if target_sell_price > 0 else sell_avg),
                }
            )
            continue
        if mode == "planned_sell" and resolved_dest_region_id <= 0:
            record_explain(
                "rejected",
                tid,
                names.get(tid, f"type_{tid}"),
                "missing_region_mapping"
            )
            continue
        if mode == "planned_sell" and resolved_dest_region_id > 0:
            hist_stats = esi.get_region_history_stats(resolved_dest_region_id, tid, history_days)
            hist_vol_30d = int((hist_stats or {}).get("volume", 0) if isinstance(hist_stats, dict) else 0)
            hist_orders_30d = int((hist_stats or {}).get("order_count", 0) if isinstance(hist_stats, dict) else 0)
            if strict_enabled and strict_min_avg_daily_volume_7d > 0:
                hist_stats_7d = esi.get_region_history_stats(resolved_dest_region_id, tid, 7)
                hist_vol_7d = int((hist_stats_7d or {}).get("volume", 0) if isinstance(hist_stats_7d, dict) else 0)
        if mode == "planned_sell":
            if hist_vol_30d > 0:
                avg_daily_volume_30d = float(hist_vol_30d) / max(1.0, float(history_days))
            else:
                avg_daily_volume_30d = float(fallback_daily_volume)
                used_volume_fallback = True
            if hist_vol_7d > 0:
                avg_daily_volume_7d = float(hist_vol_7d) / 7.0
            if used_volume_fallback:
                avg_daily_volume_30d *= fallback_volume_penalty
                if fallback_max_units_cap > 0:
                    max_units = min(max_units, fallback_max_units_cap)
            if strict_enabled and strict_planned_max_units_cap > 0:
                max_units = min(max_units, strict_planned_max_units_cap)
            daily_vol = avg_daily_volume_30d
        else:
            daily_vol = float(hist_vol_30d) / 30.0 if hist_vol_30d > 0 else 0.0
            avg_daily_volume_30d = daily_vol
            avg_daily_volume_7d = 0.0
        dest_buy_depth_units = int(sell_qty) if instant_flag else 0
        instant_fill_ratio = 1.0 if instant_flag else 1.0
        if instant_flag and dest_buy_depth_units < min_dest_buy_depth_units:
            record_explain(
                "rejected",
                tid,
                name,
                "dest_buy_depth_units",
                {"dest_buy_depth_units": int(dest_buy_depth_units), "min_dest_buy_depth_units": int(min_dest_buy_depth_units)}
            )
            continue
        # Heuristic competition and queue-ahead model. For fast_sell this estimates
        # how crowded the top of the destination sell book is.
        competition_price_levels_near_best = 0
        queue_ahead_units = 0
        fill_probability = 1.0 if instant_flag else 0.0
        expected_days_to_sell = 0.0
        sell_through_ratio_90d = 0.0
        risk_score = 0.0
        expected_profit_90d = 0.0
        expected_profit_per_m3_90d = 0.0
        split_px = 0.0
        if instant_flag:
            coverage = float(dest_buy_depth_units) / max(1.0, float(max_units))
            instant_fill_ratio = min(1.0, max(0.0, coverage))
            queue_ahead_units = 0
            if coverage >= 1.5 and queue_ahead_units <= 0:
                fill_probability = 1.0
            else:
                fill_probability = min(0.99, max(0.0, coverage))
        elif mode == "planned_sell":
            if avg_daily_volume_30d <= 0:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "no_history_volume",
                    {"history_days": int(history_days), "fallback_daily_volume": float(fallback_daily_volume)}
                )
                continue
            if strict_enabled and strict_disable_fallback_planned and used_volume_fallback:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_no_fallback_volume",
                    {"used_volume_fallback": True}
                )
                continue
            if (avg_daily_volume_30d + 1e-9) < min_avg_daily_volume:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "avg_daily_volume_too_low",
                    {"avg_daily_volume_30d": float(avg_daily_volume_30d), "min_avg_daily_volume": float(min_avg_daily_volume)}
                )
                continue
            if strict_enabled and strict_min_avg_daily_volume_7d > 0.0 and (avg_daily_volume_7d + 1e-9) < strict_min_avg_daily_volume_7d:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_avg_daily_volume_7d_too_low",
                    {
                        "avg_daily_volume_7d": float(avg_daily_volume_7d),
                        "strict_min_avg_daily_volume_7d": float(strict_min_avg_daily_volume_7d)
                    }
                )
                continue
            if hist_orders_30d < min_history_order_count:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_history_order_count",
                    {
                        "history_order_count_30d": int(hist_orders_30d),
                        "min_market_history_order_count": int(min_history_order_count),
                    }
                )
                continue
            if used_volume_fallback and profit_pct < fallback_require_high_profit_pct:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "fallback_profit_pct_too_low",
                    {
                        "profit_pct": float(profit_pct),
                        "fallback_require_high_profit_pct": float(fallback_require_high_profit_pct)
                    }
                )
                continue
            depth_ok = depth_within_2pct_sell >= min_depth_within_2pct_sell
            competition_ok = competition_density_near_best <= max_competition_density_near_best
            if not (depth_ok or competition_ok):
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "planned_structure_micro_liquidity",
                    {
                        "depth_within_2pct_sell": int(depth_within_2pct_sell),
                        "min_depth_within_2pct_sell": int(min_depth_within_2pct_sell),
                        "competition_density_near_best": int(competition_density_near_best),
                        "max_competition_density_near_best": int(max_competition_density_near_best),
                    }
                )
                continue
            expected_days_to_sell = float(max_units) / max(avg_daily_volume_30d, 1e-9)
            sell_through_ratio_90d = min(1.0, (avg_daily_volume_30d * float(horizon_days)) / max(1.0, float(max_units)))
            risk_score = min(1.0, max(0.0, 1.0 - sell_through_ratio_90d))
            expected_profit_90d = float(profit_per_unit) * float(max_units)
            expected_profit_per_m3_90d = expected_profit_90d / max(1.0, float(max_units) * float(unit_vol))
            fill_probability = min(0.85, sell_through_ratio_90d)
            if used_volume_fallback:
                fill_probability = min(fill_probability, fallback_fill_probability_cap)
                sell_through_ratio_90d = min(sell_through_ratio_90d, fallback_fill_probability_cap)
                risk_score = max(risk_score, 1.0 - fallback_fill_probability_cap)
                expected_profit_90d *= fallback_fill_probability_cap
                expected_profit_per_m3_90d *= fallback_fill_probability_cap
            if reference_price_penalty > 0.0:
                penalty_factor = max(0.0, 1.0 - reference_price_penalty)
                expected_profit_90d *= penalty_factor
                expected_profit_per_m3_90d *= penalty_factor
                risk_score = max(risk_score, reference_price_penalty)
            if strict_enabled and expected_days_to_sell > max_expected_days_to_sell:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_expected_days_too_high",
                    {
                        "expected_days_to_sell": float(expected_days_to_sell),
                        "strict_max_expected_days_to_sell": float(max_expected_days_to_sell)
                    }
                )
                continue
            if expected_days_to_sell > max_expected_days_to_sell:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "expected_days_too_high",
                    {"expected_days_to_sell": float(expected_days_to_sell), "max_expected_days_to_sell": float(max_expected_days_to_sell)}
                )
                continue
            if strict_enabled and sell_through_ratio_90d < min_sell_through_ratio_90d:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "strict_sell_through_too_low",
                    {
                        "sell_through_ratio_90d": float(sell_through_ratio_90d),
                        "strict_min_sell_through_ratio_90d": float(min_sell_through_ratio_90d)
                    }
                )
                continue
            if sell_through_ratio_90d < min_sell_through_ratio_90d:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "sell_through_too_low",
                    {"sell_through_ratio_90d": float(sell_through_ratio_90d), "min_sell_through_ratio_90d": float(min_sell_through_ratio_90d)}
                )
                continue
            if expected_profit_90d < min_expected_profit_isk:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "expected_profit_too_low",
                    {"expected_profit_90d": float(expected_profit_90d), "min_expected_profit_isk": float(min_expected_profit_isk)}
                )
                continue
        elif not instant_flag:
            dst_sell_lv = build_levels(dest_sell_by_type.get(tid, []), is_buy=False)
            if dst_sell_lv:
                best_sell = dst_sell_lv[0].price
                band_cutoff = best_sell * (1.0 + competition_band_pct)
                competition_price_levels_near_best = sum(1 for lv in dst_sell_lv if lv.price <= band_cutoff)
                queue_ahead_units = sum(lv.volume for lv in dst_sell_lv if lv.price <= band_cutoff)
                denom = max(1.0, float(queue_ahead_units + max_units))
                fill_probability = min(1.0, daily_vol / denom) if daily_vol > 0 else 0.0

        if shipping_lane_cfg is not None and max_units > 0:
            ship_defaults = route_context.get("shipping_defaults", {})
            if not isinstance(ship_defaults, dict):
                ship_defaults = {}
            collateral_buffer_pct = max(0.0, float(ship_defaults.get("collateral_buffer_pct", 0.0) or 0.0))
            ref_for_collateral = float(reference_price_adjusted if reference_price_adjusted > 0 else reference_price)
            base_collateral = max(
                float(cost_net * float(max_units)),
                max(0.0, ref_for_collateral * float(max_units))
            )
            split_px = float(jita_split_prices.get(int(tid), 0.0) or 0.0)
            collateral_basis = str(shipping_lane_cfg.get("collateral_basis", "auto") or "auto").strip().lower()
            if collateral_basis in ("jita_split", "jita_mid"):
                if split_px > 0.0:
                    base_collateral = split_px * float(max_units)
            elif collateral_basis == "auto" and bool(route_context.get("jita_based_route", False)) and split_px > 0.0:
                base_collateral = split_px * float(max_units)
            conservative_collateral = max(0.0, base_collateral) * (1.0 + collateral_buffer_pct)
            est_shipping_total = float(compute_shipping_lane_total_cost(
                lane_cfg=shipping_lane_cfg,
                total_volume_m3=float(unit_vol) * float(max_units),
                total_collateral_isk=conservative_collateral
            ).get("total_cost", 0.0))
            est_shipping_per_unit = est_shipping_total / max(1.0, float(max_units))
            profit_per_unit -= est_shipping_per_unit
            if mode == "planned_sell":
                expected_profit_90d = max(0.0, expected_profit_90d - est_shipping_total * max(0.0, float(fill_probability)))
                expected_profit_per_m3_90d = (
                    expected_profit_90d / max(1.0, float(max_units) * float(unit_vol))
                ) if unit_vol > 0 else 0.0
            if profit_per_unit <= 0.0:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "shipping_cost_non_positive_profit",
                    {"estimated_shipping_total": float(est_shipping_total)}
                )
                continue
            profit_pct = profit_per_unit / cost_net if cost_net > 0 else 0.0
            if profit_pct < min_profit_pct:
                record_explain(
                    "rejected",
                    tid,
                    name,
                    "min_profit_pct_after_shipping",
                    {"profit_pct": float(profit_pct), "min_profit_pct": float(min_profit_pct)}
                )
                continue
        if mode != "planned_sell" and fill_probability < min_fill_probability:
            record_explain(
                "rejected",
                tid,
                name,
                "fill_probability",
                {"fill_probability": float(fill_probability), "min_fill_probability": float(min_fill_probability)}
            )
            if funnel:
                funnel.record_rejection(tid, name, "fill_probability")
            continue

        if instant_flag:
            # Candidate-stage proxy for instant mode; true fill ratio is computed on final portfolio qty.
            turnover_factor = 1.0
        elif mode == "planned_sell":
            turnover_factor = sell_through_ratio_90d
        else:
            effective_daily_vol = daily_vol if daily_vol > 0 else fallback_daily_volume
            turnover_factor = (effective_daily_vol / max(1.0, float(max_units))) if max_units > 0 else 0.0
            turnover_factor = min(max_turnover_factor, max(0.0, turnover_factor))
        profit_per_m3 = (profit_per_unit / unit_vol) if unit_vol > 0 else 0.0
        profit_per_m3_per_day = profit_per_m3 * turnover_factor
        if mode == "planned_sell":
            # Conservative confidence proxy for diagnostics and optional ranking sanity checks.
            conf = 0.0
            conf += 0.15 if not used_volume_fallback else 0.0
            conf += min(0.20, max(0.0, avg_daily_volume_30d / max(1e-9, min_avg_daily_volume)) * 0.20)
            if strict_min_avg_daily_volume_7d > 0:
                conf += min(0.20, max(0.0, avg_daily_volume_7d / max(1e-9, strict_min_avg_daily_volume_7d)) * 0.20)
            else:
                conf += min(0.10, max(0.0, avg_daily_volume_7d) * 0.01)
            conf += min(0.20, max(0.0, sell_through_ratio_90d) * 0.20)
            conf += min(0.15, max(0.0, 1.0 - min(1.0, expected_days_to_sell / max(1e-9, max_expected_days_to_sell))) * 0.15)
            if reference_price > 0:
                conf += min(0.10, max(0.0, 1.0 - max(0.0, sell_markup_vs_ref)) * 0.10)
            strict_confidence_score = max(0.0, min(1.0, conf))
        else:
            strict_confidence_score = max(0.0, min(1.0, float(fill_probability)))

        if mode in ("fast_sell", "planned_sell"):
            print(f"    Hinweis: {name} (type_id {tid}) benoetigt Verkaufsauftrag @ {sell_sugg:.2f} fuer {order_duration}d")
        candidates.append(
            TradeCandidate(
                type_id=tid,
                name=name,
                unit_volume=unit_vol,
                buy_avg=buy_avg,
                sell_avg=sell_avg,
                max_units=max_units,
                profit_per_unit=profit_per_unit,
                profit_pct=profit_pct,
                instant=instant_flag,
                suggested_sell_price=sell_sugg,
                liquidity_score=history_scores.get(tid, 0),
                history_volume_30d=hist_vol_30d,
                history_order_count_30d=hist_orders_30d,
                daily_volume=daily_vol,
                dest_buy_depth_units=dest_buy_depth_units,
                instant_fill_ratio=instant_fill_ratio,
                competition_price_levels_near_best=competition_price_levels_near_best,
                queue_ahead_units=queue_ahead_units,
                spread_pct=float(spread_pct),
                depth_within_2pct_buy=int(depth_within_2pct_buy),
                depth_within_2pct_sell=int(depth_within_2pct_sell),
                orderbook_imbalance=float(orderbook_imbalance),
                competition_density_near_best=int(competition_density_near_best),
                fill_probability=fill_probability,
                turnover_factor=turnover_factor,
                profit_per_m3=profit_per_m3,
                profit_per_m3_per_day=profit_per_m3_per_day,
                mode=mode,
                target_sell_price=float(target_sell_price if target_sell_price > 0 else (sell_sugg or 0.0)),
                avg_daily_volume_30d=float(avg_daily_volume_30d),
                avg_daily_volume_7d=float(avg_daily_volume_7d),
                expected_days_to_sell=float(expected_days_to_sell),
                sell_through_ratio_90d=float(sell_through_ratio_90d),
                risk_score=float(risk_score),
                expected_profit_90d=float(expected_profit_90d),
                expected_profit_per_m3_90d=float(expected_profit_per_m3_90d),
                used_volume_fallback=bool(used_volume_fallback),
                reference_price=float(reference_price),
                reference_price_average=float(reference_price_average),
                reference_price_adjusted=float(reference_price_adjusted),
                reference_price_source=str(reference_price_source),
                buy_discount_vs_ref=float(buy_discount_vs_ref),
                sell_markup_vs_ref=float(sell_markup_vs_ref),
                reference_price_penalty=float(reference_price_penalty),
                strict_confidence_score=float(strict_confidence_score),
                strict_mode_enabled=bool(strict_enabled),
                jita_split_price=float(split_px),
            )
        )

    ranking_metric = str(filters.get("ranking_metric", "profit_per_m3_per_day")).lower()
    if ranking_metric == "expected_profit_per_m3_90d":
        candidates.sort(
            key=lambda c: (c.expected_profit_per_m3_90d, -c.expected_days_to_sell, -c.risk_score),
            reverse=True
        )
    elif ranking_metric == "profit_per_m3":
        candidates.sort(key=lambda c: (c.profit_per_m3, c.profit_pct), reverse=True)
    elif ranking_metric == "profit":
        candidates.sort(key=lambda c: (c.profit_per_unit * c.max_units, c.profit_pct), reverse=True)
    else:
        candidates.sort(key=lambda c: (c.profit_per_m3_per_day, c.profit_per_m3, c.profit_pct), reverse=True)

    filtered = []
    for c in candidates:
        max_profit_total = c.expected_profit_90d if mode == "planned_sell" else (c.profit_per_unit * c.max_units)
        if max_profit_total >= min_profit_total:
            filtered.append(c)
            kept_metrics = {
                "profit_pct": float(c.profit_pct),
                "min_profit_pct": float(min_profit_pct),
                "max_units": int(c.max_units),
                "min_depth_units": int(min_depth_units),
                "profit_per_m3_per_day": float(c.profit_per_m3_per_day),
                "max_profit_total": float(max_profit_total),
                "min_profit_isk_total": float(min_profit_total),
                "instant_fill_ratio": float(c.instant_fill_ratio),
                "min_instant_fill_ratio": float(min_instant_fill_ratio),
                "dest_buy_depth_units": int(c.dest_buy_depth_units),
                "min_dest_buy_depth_units": int(min_dest_buy_depth_units)
            }
            if not c.instant:
                kept_metrics["fill_probability"] = float(c.fill_probability)
                kept_metrics["min_fill_probability"] = float(min_fill_probability)
            if mode == "planned_sell":
                kept_metrics["expected_days_to_sell"] = float(c.expected_days_to_sell)
                kept_metrics["max_expected_days_to_sell"] = float(max_expected_days_to_sell)
                kept_metrics["sell_through_ratio_90d"] = float(c.sell_through_ratio_90d)
                kept_metrics["min_sell_through_ratio_90d"] = float(min_sell_through_ratio_90d)
                kept_metrics["expected_profit_90d"] = float(c.expected_profit_90d)
                kept_metrics["min_expected_profit_isk"] = float(min_expected_profit_isk)
                kept_metrics["avg_daily_volume_30d"] = float(c.avg_daily_volume_30d)
                kept_metrics["avg_daily_volume_7d"] = float(c.avg_daily_volume_7d)
                kept_metrics["history_order_count_30d"] = int(c.history_order_count_30d)
                kept_metrics["min_avg_daily_volume"] = float(min_avg_daily_volume)
                kept_metrics["used_volume_fallback"] = bool(c.used_volume_fallback)
                kept_metrics["reference_price"] = float(c.reference_price)
                kept_metrics["reference_price_source"] = str(c.reference_price_source)
                kept_metrics["buy_discount_vs_ref"] = float(c.buy_discount_vs_ref)
                kept_metrics["sell_markup_vs_ref"] = float(c.sell_markup_vs_ref)
                kept_metrics["reference_price_penalty"] = float(c.reference_price_penalty)
                kept_metrics["strict_confidence_score"] = float(c.strict_confidence_score)
                kept_metrics["strict_mode_enabled"] = bool(c.strict_mode_enabled)
                kept_metrics["spread_pct"] = float(c.spread_pct)
                kept_metrics["depth_within_2pct_buy"] = int(c.depth_within_2pct_buy)
                kept_metrics["depth_within_2pct_sell"] = int(c.depth_within_2pct_sell)
                kept_metrics["orderbook_imbalance"] = float(c.orderbook_imbalance)
                kept_metrics["competition_density_near_best"] = int(c.competition_density_near_best)
            record_explain(
                "kept",
                c.type_id,
                c.name,
                "passed_all_filters",
                kept_metrics
            )
        else:
            record_explain(
                "rejected",
                c.type_id,
                c.name,
                "profit_threshold",
                {"max_profit_total": float(max_profit_total), "min_profit_isk_total": float(min_profit_total)}
            )
            if funnel:
                funnel.record_rejection(c.type_id, c.name, "profit_threshold")

    if funnel:
        funnel.record_stage("profit_threshold", len(filtered))
        funnel.record_stage("final", len(filtered))

    print(f"  {len(filtered)} profitable trade candidates found")
    return filtered




def portfolio_stats(picks: list[dict]) -> tuple[float, float, float, dict]:
    """Return (total_cost, total_profit, total_m3, spent_by_type) for a list of picks."""
    total_cost = sum(p["cost"] for p in picks)
    total_profit = sum(p["profit"] for p in picks)
    total_m3 = sum(p["unit_volume"] * p["qty"] for p in picks)
    spent_by_type: dict = {}
    for p in picks:
        spent_by_type[p["type_id"]] = spent_by_type.get(p["type_id"], 0) + p["cost"]
    return total_cost, total_profit, total_m3, spent_by_type


def build_portfolio(
    candidates: list[TradeCandidate],
    budget_isk: int,
    cargo_m3: float,
    fees: dict,
    filters: dict,
    portfolio_cfg: dict,
    cfg: dict | None = None
):
    buy_broker = float(fees["buy_broker_fee"])
    max_turnover_factor = float(filters.get("max_turnover_factor", 3.0))
    min_instant_fill_ratio = float(filters.get("min_instant_fill_ratio", 0.0))
    max_share = float(portfolio_cfg["max_item_share_of_budget"])
    max_items = int(portfolio_cfg["max_items"])
    order_duration = int(filters.get("order_duration_days", 90))
    relist_budget_pct = float(filters.get("relist_budget_pct", fees.get("relist_budget_pct", 0.0)))
    relist_budget_isk = float(filters.get("relist_budget_isk", fees.get("relist_budget_isk", 0.0)))

    remaining_budget = float(budget_isk)
    remaining_cargo = float(cargo_m3)

    picks = []
    spent_by_type = {}

    def run_candidates_loop():
        """Build portfolio from the provided candidate list."""
        nonlocal remaining_budget, remaining_cargo, picks
        remaining_budget = float(budget_isk)
        remaining_cargo = float(cargo_m3)
        picks = []
        spent_by_type.clear()

        for c in candidates[: max_items * 5]:
            if remaining_budget <= 0 or remaining_cargo <= 0:
                break

            max_budget_for_item = budget_isk * max_share
            already_for_item = spent_by_type.get(c.type_id, 0.0)
            unit_cost = c.buy_avg * (1.0 + buy_broker)
            if unit_cost <= 0:
                continue

            max_by_budget = int(remaining_budget // unit_cost)
            max_by_share = int((max_budget_for_item - already_for_item) // unit_cost)
            max_by_cargo = int(remaining_cargo // c.unit_volume)
            qty = min(c.max_units, max_by_budget, max_by_share, max_by_cargo)

            if qty <= 0:
                continue

            mode_str = str(getattr(c, "mode", "instant"))
            execution = "instant_instant" if mode_str.lower() == "instant" else "instant_listed"
            breakdown = FeeEngine(fees).compute(
                buy_price=c.buy_avg,
                sell_price=c.sell_avg,
                qty=qty,
                execution=execution,
                relist_budget_pct=relist_budget_pct if execution == "instant_listed" else 0.0,
                relist_budget_isk=(relist_budget_isk if mode_str.lower() == "planned_sell" else 0.0),
            )
            cost = float(breakdown.cost_net)
            revenue_net = float(breakdown.revenue_net)
            profit = float(breakdown.profit)

            if profit <= 0:
                continue

            pick_profit_per_m3 = (float(profit) / float(qty) / float(c.unit_volume)) if qty > 0 and c.unit_volume > 0 else 0.0
            if c.instant:
                instant_fill_ratio = min(1.0, float(c.dest_buy_depth_units) / max(1.0, float(qty)))
                if instant_fill_ratio < min_instant_fill_ratio:
                    continue
                turnover_factor = min(max_turnover_factor, max(0.0, instant_fill_ratio))
                fill_probability = instant_fill_ratio
            else:
                instant_fill_ratio = 1.0
                turnover_factor = float(c.turnover_factor)
                fill_probability = float(c.fill_probability)
            pick_profit_per_m3_per_day = pick_profit_per_m3 * turnover_factor

            picks.append({
                "type_id": c.type_id,
                "name": c.name,
                "qty": qty,
                "unit_volume": c.unit_volume,
                "buy_avg": c.buy_avg,
                "sell_avg": c.sell_avg,
                "cost": cost,
                "revenue_net": revenue_net,
                "profit": profit,
                "profit_pct": profit / cost if cost > 0 else 0.0,
                "buy_broker_fee_total": float(breakdown.buy_broker_fee_total),
                "sell_broker_fee_total": float(breakdown.sell_broker_fee_total),
                "sales_tax_total": float(breakdown.sales_tax_total),
                "relist_budget_total": float(breakdown.relist_budget_total),
                "instant": c.instant,
                "suggested_sell_price": c.suggested_sell_price,
                "order_duration_days": order_duration,
                "liquidity_score": c.liquidity_score,
                "history_volume_30d": c.history_volume_30d,
                "history_order_count_30d": c.history_order_count_30d,
                "daily_volume": c.daily_volume,
                "dest_buy_depth_units": c.dest_buy_depth_units,
                "instant_fill_ratio": instant_fill_ratio,
                "competition_price_levels_near_best": c.competition_price_levels_near_best,
                "queue_ahead_units": c.queue_ahead_units,
                "spread_pct": float(getattr(c, "spread_pct", 0.0)),
                "depth_within_2pct_buy": int(getattr(c, "depth_within_2pct_buy", 0)),
                "depth_within_2pct_sell": int(getattr(c, "depth_within_2pct_sell", 0)),
                "orderbook_imbalance": float(getattr(c, "orderbook_imbalance", 0.0)),
                "competition_density_near_best": int(getattr(c, "competition_density_near_best", 0)),
                "fill_probability": fill_probability,
                "turnover_factor": turnover_factor,
                "profit_per_m3": pick_profit_per_m3,
                "profit_per_m3_per_day": pick_profit_per_m3_per_day,
                "mode": getattr(c, "mode", "instant"),
                "target_sell_price": float(getattr(c, "target_sell_price", 0.0)),
                "avg_daily_volume_30d": float(getattr(c, "avg_daily_volume_30d", 0.0)),
                "avg_daily_volume_7d": float(getattr(c, "avg_daily_volume_7d", 0.0)),
                "expected_days_to_sell": float(getattr(c, "expected_days_to_sell", 0.0)),
                "sell_through_ratio_90d": float(getattr(c, "sell_through_ratio_90d", 0.0)),
                "risk_score": float(getattr(c, "risk_score", 0.0)),
                "expected_profit_90d": float(getattr(c, "expected_profit_90d", 0.0)),
                "expected_profit_per_m3_90d": float(getattr(c, "expected_profit_per_m3_90d", 0.0)),
                "used_volume_fallback": bool(getattr(c, "used_volume_fallback", False)),
                "reference_price": float(getattr(c, "reference_price", 0.0)),
                "reference_price_average": float(getattr(c, "reference_price_average", 0.0)),
                "reference_price_adjusted": float(getattr(c, "reference_price_adjusted", 0.0)),
                "jita_split_price": float(getattr(c, "jita_split_price", 0.0)),
                "reference_price_source": str(getattr(c, "reference_price_source", "")),
                "buy_discount_vs_ref": float(getattr(c, "buy_discount_vs_ref", 0.0)),
                "sell_markup_vs_ref": float(getattr(c, "sell_markup_vs_ref", 0.0)),
                "reference_price_penalty": float(getattr(c, "reference_price_penalty", 0.0)),
                "strict_confidence_score": float(getattr(c, "strict_confidence_score", 0.0)),
                "strict_mode_enabled": bool(getattr(c, "strict_mode_enabled", False)),
                "buy_at": str(getattr(c, "route_src_label", "")),
                "sell_at": str(getattr(c, "route_dst_label", "")),
                "route_hops": int(getattr(c, "dest_hop_count", 1)),
                "carried_through_legs": int(getattr(c, "carried_through_legs", getattr(c, "dest_hop_count", 1))),
                "route_src_index": int(getattr(c, "route_src_index", 0)),
                "route_dst_index": int(getattr(c, "route_dst_index", 0)),
                "extra_leg_penalty": float(getattr(c, "extra_leg_penalty", 0.0)),
                "route_wide_selected": bool(getattr(c, "route_wide_selected", False)),
                "route_adjusted_score": float(getattr(c, "route_adjusted_score", 0.0)),
                "release_leg_index": int(getattr(c, "route_dst_index", 0) - 1) if int(getattr(c, "route_dst_index", 0)) > 0 else -1
            })

            remaining_budget -= cost
            remaining_cargo -= c.unit_volume * qty
            spent_by_type[c.type_id] = already_for_item + cost

            if len(picks) >= max_items:
                break

    # initial pass
    run_candidates_loop()

    total_cost = sum(p["cost"] for p in picks)
    total_profit = sum(p["profit"] for p in picks)
    total_m3 = sum(p["unit_volume"] * p["qty"] for p in picks)

    # attempt local search to improve the portfolio
    # convert candidate objects to pick-like dicts so local_search works on the
    # same data shape as `picks` (some callers may pass TradeCandidate objects)
    candidate_dicts = []
    for c in candidates:
        try:
            # if c is a TradeCandidate dataclass-like object
            type_id = getattr(c, 'type_id', None) or c.get('type_id')
            name = getattr(c, 'name', None) or c.get('name', '')
            unit_volume = float(getattr(c, 'unit_volume', None) or c.get('unit_volume', 0.0))
            buy_avg = float(getattr(c, 'buy_avg', None) or c.get('buy_avg', 0.0))
            sell_avg = float(getattr(c, 'sell_avg', None) or c.get('sell_avg', 0.0))
            max_units = int(getattr(c, 'max_units', None) or c.get('max_units', 0))
        except Exception:
            continue
        # guess a reasonable qty for the prototype (bounded by max_units)
        unit_cost = buy_avg * (1.0 + buy_broker) if buy_avg > 0 else 0.0
        if unit_cost > 0:
            proto_qty = max(1, min(max_units, int(budget_isk // unit_cost)))
        else:
            proto_qty = min(1, max_units)
        cost = unit_cost * proto_qty
        instant_flag = getattr(c, 'instant', c.get('instant', True) if isinstance(c, dict) else True)
        mode_value = getattr(c, "mode", None)
        if mode_value is None and isinstance(c, dict):
            mode_value = c.get("mode", "instant")
        mode_str = str(mode_value or "instant")
        execution = "instant_instant" if mode_str.lower() == "instant" else "instant_listed"
        breakdown = FeeEngine(fees).compute(
            buy_price=buy_avg,
            sell_price=sell_avg,
            qty=proto_qty,
            execution=execution,
            relist_budget_pct=relist_budget_pct if execution == "instant_listed" else 0.0,
            relist_budget_isk=(relist_budget_isk if mode_str.lower() == "planned_sell" else 0.0),
        )
        revenue_net = float(breakdown.revenue_net)
        profit = float(breakdown.profit)
        candidate_dicts.append({
            'type_id': int(type_id), 'name': name, 'qty': proto_qty,
            'unit_volume': unit_volume, 'buy_avg': buy_avg, 'sell_avg': sell_avg,
            'cost': cost, 'revenue_net': revenue_net, 'profit': profit,
            'profit_pct': profit / cost if cost > 0 else 0.0,
            'instant': instant_flag,
            'suggested_sell_price': getattr(c, 'suggested_sell_price', c.get('suggested_sell_price', None) if isinstance(c, dict) else None),
            'order_duration_days': order_duration,
            'liquidity_score': getattr(c, 'liquidity_score', c.get('liquidity_score', 0) if isinstance(c, dict) else 0),
            'history_volume_30d': getattr(c, 'history_volume_30d', c.get('history_volume_30d', 0) if isinstance(c, dict) else 0),
            'daily_volume': getattr(c, 'daily_volume', c.get('daily_volume', 0.0) if isinstance(c, dict) else 0.0),
            'dest_buy_depth_units': getattr(c, 'dest_buy_depth_units', c.get('dest_buy_depth_units', 0) if isinstance(c, dict) else 0),
            'instant_fill_ratio': getattr(c, 'instant_fill_ratio', c.get('instant_fill_ratio', 1.0) if isinstance(c, dict) else 1.0),
            'competition_price_levels_near_best': getattr(c, 'competition_price_levels_near_best', c.get('competition_price_levels_near_best', 0) if isinstance(c, dict) else 0),
            'queue_ahead_units': getattr(c, 'queue_ahead_units', c.get('queue_ahead_units', 0) if isinstance(c, dict) else 0),
            'fill_probability': getattr(c, 'fill_probability', c.get('fill_probability', 0.0) if isinstance(c, dict) else 0.0),
            'turnover_factor': getattr(c, 'turnover_factor', c.get('turnover_factor', 0.0) if isinstance(c, dict) else 0.0),
            'profit_per_m3': getattr(c, 'profit_per_m3', c.get('profit_per_m3', 0.0) if isinstance(c, dict) else 0.0),
            'profit_per_m3_per_day': getattr(c, 'profit_per_m3_per_day', c.get('profit_per_m3_per_day', 0.0) if isinstance(c, dict) else 0.0),
            'mode': getattr(c, 'mode', c.get('mode', 'instant') if isinstance(c, dict) else 'instant'),
            'target_sell_price': getattr(c, 'target_sell_price', c.get('target_sell_price', 0.0) if isinstance(c, dict) else 0.0),
            'avg_daily_volume_30d': getattr(c, 'avg_daily_volume_30d', c.get('avg_daily_volume_30d', 0.0) if isinstance(c, dict) else 0.0),
            'avg_daily_volume_7d': getattr(c, 'avg_daily_volume_7d', c.get('avg_daily_volume_7d', 0.0) if isinstance(c, dict) else 0.0),
            'expected_days_to_sell': getattr(c, 'expected_days_to_sell', c.get('expected_days_to_sell', 0.0) if isinstance(c, dict) else 0.0),
            'sell_through_ratio_90d': getattr(c, 'sell_through_ratio_90d', c.get('sell_through_ratio_90d', 0.0) if isinstance(c, dict) else 0.0),
            'risk_score': getattr(c, 'risk_score', c.get('risk_score', 0.0) if isinstance(c, dict) else 0.0),
            'expected_profit_90d': getattr(c, 'expected_profit_90d', c.get('expected_profit_90d', 0.0) if isinstance(c, dict) else 0.0),
            'expected_profit_per_m3_90d': getattr(c, 'expected_profit_per_m3_90d', c.get('expected_profit_per_m3_90d', 0.0) if isinstance(c, dict) else 0.0),
            'used_volume_fallback': getattr(c, 'used_volume_fallback', c.get('used_volume_fallback', False) if isinstance(c, dict) else False),
            'reference_price': getattr(c, 'reference_price', c.get('reference_price', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_average': getattr(c, 'reference_price_average', c.get('reference_price_average', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_adjusted': getattr(c, 'reference_price_adjusted', c.get('reference_price_adjusted', 0.0) if isinstance(c, dict) else 0.0),
            'jita_split_price': getattr(c, 'jita_split_price', c.get('jita_split_price', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_source': getattr(c, 'reference_price_source', c.get('reference_price_source', "") if isinstance(c, dict) else ""),
            'buy_discount_vs_ref': getattr(c, 'buy_discount_vs_ref', c.get('buy_discount_vs_ref', 0.0) if isinstance(c, dict) else 0.0),
            'sell_markup_vs_ref': getattr(c, 'sell_markup_vs_ref', c.get('sell_markup_vs_ref', 0.0) if isinstance(c, dict) else 0.0),
            'reference_price_penalty': getattr(c, 'reference_price_penalty', c.get('reference_price_penalty', 0.0) if isinstance(c, dict) else 0.0),
            'strict_confidence_score': getattr(c, 'strict_confidence_score', c.get('strict_confidence_score', 0.0) if isinstance(c, dict) else 0.0),
            'strict_mode_enabled': getattr(c, 'strict_mode_enabled', c.get('strict_mode_enabled', False) if isinstance(c, dict) else False),
            'buy_at': getattr(c, 'route_src_label', c.get('buy_at', "") if isinstance(c, dict) else ""),
            'sell_at': getattr(c, 'route_dst_label', c.get('sell_at', "") if isinstance(c, dict) else ""),
            'route_hops': getattr(c, 'dest_hop_count', c.get('route_hops', 1) if isinstance(c, dict) else 1),
            'carried_through_legs': getattr(c, 'carried_through_legs', c.get('carried_through_legs', 1) if isinstance(c, dict) else 1),
            'route_src_index': getattr(c, 'route_src_index', c.get('route_src_index', 0) if isinstance(c, dict) else 0),
            'route_dst_index': getattr(c, 'route_dst_index', c.get('route_dst_index', 0) if isinstance(c, dict) else 0),
            'extra_leg_penalty': getattr(c, 'extra_leg_penalty', c.get('extra_leg_penalty', 0.0) if isinstance(c, dict) else 0.0),
            'route_wide_selected': getattr(c, 'route_wide_selected', c.get('route_wide_selected', False) if isinstance(c, dict) else False),
            'route_adjusted_score': getattr(c, 'route_adjusted_score', c.get('route_adjusted_score', 0.0) if isinstance(c, dict) else 0.0)
        })

    optimized = _mod_local_search_optimize(picks, candidate_dicts, budget_isk, cargo_m3, portfolio_cfg)
    if optimized is not picks:
        opt_cost, opt_profit, opt_m3, _ = portfolio_stats(optimized)
        if opt_profit > total_profit + 1e-6:
            picks = optimized
            total_cost = opt_cost
            total_profit = opt_profit
            total_m3 = opt_m3
            print(f"  Portfolio improved by local search: {fmt_isk(total_profit)} profit")

    # Apply strategy mode if cfg provided
    if cfg:
        _mod_apply_strategy_mode(cfg, filters, picks)

    print(f"  Portfolio built: {len(picks)} items, {fmt_isk(total_profit)} profit")
    return picks, total_cost, total_profit, total_m3


def write_csv(path: str, picks: list[dict]) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = [
            "type_id", "name", "ingame_search", "qty", "unit_volume_m3",
            "buy_avg_price", "sell_avg_price",
            "cost", "revenue_net", "profit", "profit_pct",
            "buy_broker_fee_total", "sell_broker_fee_total", "sales_tax_total", "scc_surcharge_total", "relist_budget_total",
            "sales_tax_isk", "broker_fee_isk", "scc_surcharge_isk", "relist_fee_isk",
            "shipping_cost", "route_cost", "transport_cost",
            "instant", "suggested_sell_price", "order_duration_days",
            "profit_per_m3", "profit_per_m3_per_day", "turnover_factor",
            "dest_buy_depth_units", "instant_fill_ratio",
            "fill_probability", "competition_price_levels_near_best", "queue_ahead_units",
            "daily_volume", "history_volume_30d", "liquidity_score",
            "mode", "target_sell_price", "avg_daily_volume_30d", "avg_daily_volume_7d", "expected_days_to_sell",
            "sell_through_ratio_90d", "risk_score", "expected_profit_90d", "expected_profit_per_m3_90d",
            "used_volume_fallback",
            "reference_price", "reference_price_source", "reference_price_average", "reference_price_adjusted", "jita_split_price",
            "buy_discount_vs_ref", "sell_markup_vs_ref", "reference_price_penalty",
            "strict_confidence_score", "strict_mode_enabled",
            "buy_at", "sell_at", "route_hops", "carried_through_legs",
            "route_src_index", "route_dst_index", "extra_leg_penalty",
            "route_wide_selected", "route_adjusted_score", "release_leg_index"
        ]
        w.writerow(header)
        for p in picks:
            search_name = str(p.get("name", ""))
            search_name = search_name.replace("’", "'").replace('"', "")
            row = [
                p["type_id"], p["name"], search_name, p["qty"], f'{p["unit_volume"]:.4f}',
                f'{p["buy_avg"]:.2f}', f'{p["sell_avg"]:.2f}',
                f'{p["cost"]:.2f}', f'{p["revenue_net"]:.2f}', f'{p["profit"]:.2f}', f'{p["profit_pct"]:.4f}',
                f'{float(p.get("buy_broker_fee_total", 0.0)):.2f}',
                f'{float(p.get("sell_broker_fee_total", 0.0)):.2f}',
                f'{float(p.get("sales_tax_total", 0.0)):.2f}',
                f'{float(p.get("scc_surcharge_total", p.get("scc_surcharge_isk", 0.0))):.2f}',
                f'{float(p.get("relist_budget_total", 0.0)):.2f}',
                f'{float(p.get("sales_tax_isk", p.get("sales_tax_total", 0.0))):.2f}',
                f'{float(p.get("broker_fee_isk", p.get("sell_broker_fee_total", 0.0))):.2f}',
                f'{float(p.get("scc_surcharge_isk", p.get("scc_surcharge_total", 0.0))):.2f}',
                f'{float(p.get("relist_fee_isk", p.get("relist_budget_total", 0.0))):.2f}',
                f'{float(p.get("shipping_cost", 0.0)):.2f}',
                f'{float(p.get("route_cost", 0.0)):.2f}',
                f'{float(p.get("transport_cost", 0.0)):.2f}',
                p.get("instant", True),
                f'{p.get("suggested_sell_price", "")}',
                p.get("order_duration_days", ""),
                f'{float(p.get("profit_per_m3", 0.0)):.4f}',
                f'{float(p.get("profit_per_m3_per_day", 0.0)):.4f}',
                f'{float(p.get("turnover_factor", 0.0)):.4f}',
                int(p.get("dest_buy_depth_units", 0)),
                f'{float(p.get("instant_fill_ratio", 1.0)):.4f}',
                f'{float(p.get("fill_probability", 0.0)):.4f}',
                int(p.get("competition_price_levels_near_best", 0)),
                int(p.get("queue_ahead_units", 0)),
                f'{float(p.get("daily_volume", 0.0)):.2f}',
                int(p.get("history_volume_30d", 0)),
                int(p.get("liquidity_score", 0)),
                p.get("mode", "instant"),
                f'{float(p.get("target_sell_price", 0.0)):.2f}',
                f'{float(p.get("avg_daily_volume_30d", 0.0)):.4f}',
                f'{float(p.get("avg_daily_volume_7d", 0.0)):.4f}',
                f'{float(p.get("expected_days_to_sell", 0.0)):.4f}',
                f'{float(p.get("sell_through_ratio_90d", 0.0)):.4f}',
                f'{float(p.get("risk_score", 0.0)):.4f}',
                f'{float(p.get("expected_profit_90d", 0.0)):.2f}',
                f'{float(p.get("expected_profit_per_m3_90d", 0.0)):.4f}',
                bool(p.get("used_volume_fallback", False)),
                f'{float(p.get("reference_price", 0.0)):.2f}',
                str(p.get("reference_price_source", "")),
                f'{float(p.get("reference_price_average", 0.0)):.2f}',
                f'{float(p.get("reference_price_adjusted", 0.0)):.2f}',
                f'{float(p.get("jita_split_price", 0.0)):.2f}',
                f'{float(p.get("buy_discount_vs_ref", 0.0)):.4f}',
                f'{float(p.get("sell_markup_vs_ref", 0.0)):.4f}',
                f'{float(p.get("reference_price_penalty", 0.0)):.4f}',
                f'{float(p.get("strict_confidence_score", 0.0)):.4f}',
                bool(p.get("strict_mode_enabled", False)),
                str(p.get("buy_at", "")),
                str(p.get("sell_at", "")),
                int(p.get("route_hops", 1)),
                int(p.get("carried_through_legs", p.get("route_hops", 1))),
                int(p.get("route_src_index", 0)),
                int(p.get("route_dst_index", 0)),
                f'{float(p.get("extra_leg_penalty", 0.0)):.4f}',
                bool(p.get("route_wide_selected", False)),
                f'{float(p.get("route_adjusted_score", 0.0)):.6f}',
                int(p.get("release_leg_index", -1))
            ]
            assert len(header) == len(row), f"CSV mismatch: {len(header)} vs {len(row)}"
            w.writerow(row)


def write_top_candidate_dump(path: str, candidates: list[TradeCandidate], label: str, filters_used: dict, explain: dict | None = None) -> None:
    """Write top-10 diagnostics across key metrics for fast strategy iteration."""
    import json
    from datetime import datetime
    lines = []
    lines.append(f"CANDIDATE DIAGNOSTICS - {label}")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Route: {label}")
    lines.append(f"Mode: {str(filters_used.get('mode', 'instant')).lower()}")
    lines.append(f"strict_mode_enabled: {bool(filters_used.get('strict_mode_enabled', False))}")
    lines.append(f"ranking_metric: {str(filters_used.get('ranking_metric', 'profit_per_m3_per_day')).lower()}")
    lines.append(f"Total candidates: {len(candidates)}")
    lines.append("Note: In instant mode, CSV pick metrics are qty-based; fill_probability equals instant_fill_ratio.")
    profit_threshold_rejects = 0
    if explain:
        profit_threshold_rejects = int(explain.get("reason_counts", {}).get("profit_threshold", 0))
    lines.append(f"Candidates before profit_threshold: {len(candidates) + profit_threshold_rejects}")
    lines.append(f"Candidates after profit_threshold: {len(candidates)}")
    lines.append("Filters:")
    lines.append(json.dumps(filters_used, ensure_ascii=False, sort_keys=True))
    lines.append("")

    def section(title: str, ranked: list[TradeCandidate]) -> None:
        lines.append(title)
        lines.append("-" * len(title))
        for c in ranked[:10]:
            display_name = getattr(c, "name", f"type_{getattr(c, 'type_id', 0)}")
            lines.append(
                f"{display_name} (type_id {c.type_id}) | max_profit={fmt_isk(c.profit_per_unit * c.max_units)} "
                f"| profit_pct={c.profit_pct*100:.2f}% | isk_per_m3={c.profit_per_m3:.2f} "
                f"| isk_per_m3_day={c.profit_per_m3_per_day:.2f} | fill_prob={c.fill_probability*100:.1f}% "
                f"| instant_fill_ratio={c.instant_fill_ratio:.2f} | dest_buy_units={c.dest_buy_depth_units} "
                f"| competition_levels={c.competition_price_levels_near_best} | queue={c.queue_ahead_units} "
                f"| daily_vol={c.daily_volume:.1f} | ref={getattr(c, 'reference_price', 0.0):.2f}"
                f"| avg_daily_7d={getattr(c, 'avg_daily_volume_7d', 0.0):.4f}"
                f"| ref_src={getattr(c, 'reference_price_source', '')}"
                f"| buy_vs_ref={getattr(c, 'buy_discount_vs_ref', 0.0):.4f}"
                f"| sell_vs_ref={getattr(c, 'sell_markup_vs_ref', 0.0):.4f}"
                f"| ref_penalty={getattr(c, 'reference_price_penalty', 0.0):.4f}"
                f"| strict_conf={getattr(c, 'strict_confidence_score', 0.0):.4f}"
                f"| buy_at={getattr(c, 'route_src_label', '')}"
                f"| sell_at={getattr(c, 'route_dst_label', '')}"
                f"| hops={int(getattr(c, 'dest_hop_count', 1))}"
                f"| route_adj={float(getattr(c, 'route_adjusted_score', 0.0)):.6f}"
            )
            lines.append(
                "  WHY_IN: "
                f"profit_pct {c.profit_pct:.4f} >= min_profit_pct {float(filters_used.get('min_profit_pct', 0.0)):.4f}; "
                f"max_units {c.max_units} >= min_depth_units {int(filters_used.get('min_depth_units', 0))}; "
                + (
                    f"dest_buy_depth_units {c.dest_buy_depth_units} >= min_dest_buy_depth_units "
                    f"{int(filters_used.get('min_dest_buy_depth_units', 0))}"
                    if c.instant else
                    f"fill_probability {c.fill_probability:.4f} >= min_fill_probability "
                    f"{float(filters_used.get('min_fill_probability', 0.0)):.4f}"
                )
            )
        lines.append("")

    section("Top 10 by Net Profit", sorted(candidates, key=lambda c: c.profit_per_unit * c.max_units, reverse=True))
    section("Top 10 by Profit %", sorted(candidates, key=lambda c: c.profit_pct, reverse=True))
    section("Top 10 by ISK per m3", sorted(candidates, key=lambda c: c.profit_per_m3, reverse=True))
    section("Top 10 by ISK per m3 per day", sorted(candidates, key=lambda c: c.profit_per_m3_per_day, reverse=True))
    section(
        "Top 10 by Lowest Competition (then high fill)",
        sorted(candidates, key=lambda c: (c.competition_price_levels_near_best, -c.fill_probability, -c.profit_per_m3_per_day))
    )

    if explain:
        lines.append("WHY_OUT Summary")
        lines.append("-" * len("WHY_OUT Summary"))
        reason_counts = explain.get("reason_counts", {})
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"{reason}: {count}")
        lines.append("")
        lines.append("WHY_OUT Samples")
        lines.append("-" * len("WHY_OUT Samples"))
        for entry in explain.get("rejected", [])[:20]:
            metrics = entry.get("metrics", {})
            ppct = metrics.get("profit_pct", "n/a")
            m_units = metrics.get("max_units", "n/a")
            fprob = metrics.get("fill_probability", "n/a")
            lines.append(
                f"{entry.get('name', '')} (type_id {entry.get('type_id', 0)}) -> {entry.get('reason', '')} "
                f"| profit_pct={ppct} max_units={m_units} fill_probability={fprob} | {metrics}"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_enhanced_summary(
    path: str,
    forward_picks: list[dict],
    forward_cost: float,
    forward_profit: float,
    return_picks: list[dict],
    return_cost: float,
    return_profit: float,
    cargo_m3: float,
    budget_isk: float,
    forward_funnel: FilterFunnel = None,
    return_funnel: FilterFunnel = None,
    run_uuid: str = ""
) -> None:
    """Write enhanced summary with funnel stats and rejection analysis."""
    from datetime import datetime
    lines = []
    lines.append("=" * 70)
    lines.append("ROUNDTRIP TRADING PLAN - ENHANCED REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if run_uuid:
        lines.append(f"Run UUID: {run_uuid}")
    lines.append("")
    
    lines.append("PARAMETERS:")
    lines.append(f"  Cargo available: {cargo_m3:.2f} m3")
    lines.append(f"  Trading budget: {fmt_isk(budget_isk)}")
    lines.append("")
    
    lines.append("FORWARD ROUTE (O4T -> CJ6):")
    lines.append(f"  Selected items: {len(forward_picks)}")
    lines.append(f"  Total cost: {fmt_isk(forward_cost)}")
    lines.append(f"  Total profit: {fmt_isk(forward_profit)}")
    if forward_picks:
        lines.append("  Top 5 picks:")
        for p in forward_picks[:5]:
            lines.append(f"    - {p['name']} x{p['qty']}: {fmt_isk(p['profit'])} profit")
    lines.append("")
    
    if forward_funnel:
        lines.extend(forward_funnel.get_summary_lines())
    
    lines.append("RETURN ROUTE (CJ6 -> O4T):")
    lines.append(f"  Selected items: {len(return_picks)}")
    lines.append(f"  Total cost: {fmt_isk(return_cost)}")
    lines.append(f"  Total profit: {fmt_isk(return_profit)}")
    if return_picks:
        lines.append("  Top 5 picks:")
        for p in return_picks[:5]:
            lines.append(f"    - {p['name']} x{p['qty']}: {fmt_isk(p['profit'])} profit")
    lines.append("")
    
    if return_funnel:
        lines.extend(return_funnel.get_summary_lines())
    
    lines.append("=" * 70)
    lines.append(f"TOTAL PROFIT: {fmt_isk(forward_profit + return_profit)}")
    lines.append(f"Total margin: {((forward_profit + return_profit) / (forward_cost + return_cost) * 100) if (forward_cost + return_cost) > 0 else 0:.2f}%")
    lines.append("=" * 70)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def fmt_isk(x: float) -> str:
    x = float(x)
    if x >= 1_000_000_000:
        return f"{x/1_000_000_000:.2f}b"
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}m"
    if x >= 1_000:
        return f"{x/1_000:.2f}k"
    return f"{x:.0f}"


def label_to_slug(label: str) -> str:
    s = (label or "").strip().lower()
    if not s:
        return "unknown"
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    slug = "".join(out).strip("_")
    return slug or "unknown"



def run_snapshot_only(cfg: dict, structure_ids: list[int], snapshot_out: str | None = None) -> None:
    if not _has_live_esi_credentials(cfg):
        die("Fehlende ESI-Credentials. Setze ESI_CLIENT_ID/ESI_CLIENT_SECRET oder nutze config.local.json.")
    esi = ESIClient(cfg)
    wanted = [int(s) for s in structure_ids]
    print("Snapshot-Only Modus aktiv.")
    print("Fuehre ESI-Preflight durch...")
    for sid in wanted:
        esi.preflight_structure_request(int(sid))
    structure_orders_by_id: dict[int, list[dict]] = {}
    print("Lade Marktorders...")
    for sid in wanted:
        print(f"  -> Lade Structure ({sid})...")
        orders = esi.fetch_structure_orders(int(sid))
        structure_orders_by_id[int(sid)] = orders if isinstance(orders, list) else []
        print(f"    {len(structure_orders_by_id[int(sid)])} Orders geladen")

    merged_type_cache = {}
    cached_types_from_disk = load_json(TYPE_CACHE_PATH, {})
    live_type_cache = getattr(esi, "type_cache", {})
    if isinstance(cached_types_from_disk, dict):
        merged_type_cache.update(cached_types_from_disk)
    if isinstance(live_type_cache, dict):
        merged_type_cache.update(live_type_cache)

    payload = _mod_make_snapshot_payload(structure_orders_by_id, merged_type_cache)
    out_dir = os.path.dirname(__file__)
    if snapshot_out:
        out_path = snapshot_out
        if not os.path.isabs(out_path):
            out_path = os.path.join(out_dir, out_path)
    else:
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        out_path = os.path.join(out_dir, f"snapshot_{ts}.json")
    save_json(out_path, payload)
    print(f"Snapshot geschrieben: {out_path}")


def sort_picks_for_output(picks: list[dict], filters_used: dict) -> None:
    ranking_metric = str(filters_used.get("ranking_metric", "profit_per_m3_per_day")).lower()
    if ranking_metric == "expected_profit_per_m3_90d":
        picks.sort(
            key=lambda x: (
                x.get("expected_profit_per_m3_90d", 0.0),
                -x.get("expected_days_to_sell", 0.0),
                -x.get("risk_score", 0.0)
            ),
            reverse=True
        )
    elif ranking_metric == "profit":
        picks.sort(key=lambda x: x.get("profit", 0.0), reverse=True)
    elif ranking_metric == "profit_per_m3":
        picks.sort(key=lambda x: x.get("profit_per_m3", 0.0), reverse=True)
    else:
        picks.sort(key=lambda x: x.get("profit_per_m3_per_day", 0.0), reverse=True)


def _sort_candidates_for_cargo_fill(candidates: list[TradeCandidate], ranking_metric: str) -> list[TradeCandidate]:
    metric = str(ranking_metric or "profit_per_m3_per_day").lower()
    if metric in ("hybrid", "profit_per_m3_and_isk", "profit_per_m3_plus_isk"):
        def hybrid_score(c: TradeCandidate) -> float:
            density = max(0.0, float(getattr(c, "profit_per_m3", 0.0)))
            cap_eff = max(0.0, float(getattr(c, "profit_pct", 0.0)))
            return (density * 0.7) + (cap_eff * 1000.0 * 0.3)
        return sorted(
            candidates,
            key=lambda c: (
                hybrid_score(c),
                float(getattr(c, "profit_per_m3_per_day", 0.0)),
                float(getattr(c, "profit_pct", 0.0))
            ),
            reverse=True
        )
    if metric == "expected_profit_per_m3_90d":
        return sorted(
            candidates,
            key=lambda c: (
                float(getattr(c, "expected_profit_per_m3_90d", 0.0)),
                -float(getattr(c, "expected_days_to_sell", 0.0)),
                -float(getattr(c, "risk_score", 0.0))
            ),
            reverse=True
        )
    if metric == "profit":
        return sorted(
            candidates,
            key=lambda c: float(getattr(c, "profit_per_unit", 0.0)) * float(getattr(c, "max_units", 0)),
            reverse=True
        )
    if metric == "profit_per_m3":
        return sorted(candidates, key=lambda c: float(getattr(c, "profit_per_m3", 0.0)), reverse=True)
    # Cargo fill default: prioritize dense and liquid picks.
    return sorted(
        candidates,
        key=lambda c: (
            float(getattr(c, "profit_per_m3_per_day", 0.0)),
            float(getattr(c, "profit_per_m3", 0.0)),
            float(getattr(c, "sell_through_ratio_90d", 0.0)),
            -float(getattr(c, "risk_score", 0.0)),
            float(getattr(c, "profit_pct", 0.0))
        ),
        reverse=True
    )


def try_cargo_fill(
    base_picks: list[dict],
    candidates: list[TradeCandidate],
    budget_isk: float,
    cargo_m3: float,
    fees: dict,
    filters_used: dict,
    port_cfg: dict
) -> tuple[list[dict], float, float, float, int]:
    buy_broker = float(fees["buy_broker_fee"])
    max_turnover_factor = float(filters_used.get("max_turnover_factor", 3.0))
    min_instant_fill_ratio = float(filters_used.get("min_instant_fill_ratio", 0.0))
    base_max_share = float(port_cfg.get("max_item_share_of_budget", 1.0))
    max_share = float(port_cfg.get("cargo_fill_max_item_share_of_budget", base_max_share))
    max_items = int(port_cfg.get("max_items", 50))
    order_duration = int(filters_used.get("order_duration_days", 90))
    relist_budget_pct = float(filters_used.get("relist_budget_pct", fees.get("relist_budget_pct", 0.0)))
    relist_budget_isk = float(filters_used.get("relist_budget_isk", fees.get("relist_budget_isk", 0.0)))
    fill_metric = str(port_cfg.get("cargo_fill_ranking_metric", "profit_per_m3_per_day")).lower()
    cargo_fill_stop_util = float(port_cfg.get("cargo_fill_stop_util", 0.98))
    cargo_fill_min_profit_per_m3_ratio = float(port_cfg.get("cargo_fill_min_profit_per_m3_ratio", 0.75))
    cargo_fill_min_profit_pct = float(port_cfg.get("cargo_fill_min_profit_pct", 0.0))
    cargo_fill_min_profit_abs_isk = float(port_cfg.get("cargo_fill_min_profit_abs_isk", 0.0))
    max_extra_items = int(port_cfg.get("cargo_fill_max_extra_items", 8))
    allow_topup_existing = bool(port_cfg.get("cargo_fill_allow_topup_existing", False))

    if max_extra_items <= 0:
        total_cost, total_profit, total_m3, _ = portfolio_stats(base_picks)
        return list(base_picks), total_cost, total_profit, total_m3, 0

    total_cost, total_profit, total_m3, spent_by_type = portfolio_stats(base_picks)
    remaining_budget = max(0.0, float(budget_isk) - float(total_cost))
    remaining_cargo = max(0.0, float(cargo_m3) - float(total_m3))
    if remaining_budget <= 1e-6 or remaining_cargo <= 1e-6:
        return list(base_picks), total_cost, total_profit, total_m3, 0

    picked_type_ids = {int(p.get("type_id", 0)) for p in base_picks}
    if allow_topup_existing:
        fill_pool = list(candidates)
    else:
        fill_pool = [c for c in candidates if int(getattr(c, "type_id", 0)) not in picked_type_ids]
    if not fill_pool:
        return list(base_picks), total_cost, total_profit, total_m3, 0
    sorted_fill_pool = _sort_candidates_for_cargo_fill(fill_pool, fill_metric)

    picks = list(base_picks)
    picks_by_type: dict[int, dict] = {int(p.get("type_id", 0)): p for p in picks}
    max_new_slots = min(max_extra_items, max(0, max_items - len(picks)))
    if max_new_slots <= 0 and not allow_topup_existing:
        return picks, total_cost, total_profit, total_m3, 0

    added = 0
    added_new_types = 0
    base_total_m3 = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in base_picks)
    base_total_profit = sum(float(p.get("profit", 0.0)) for p in base_picks)
    base_profit_per_m3 = (base_total_profit / base_total_m3) if base_total_m3 > 0 else 0.0
    for c in sorted_fill_pool:
        if remaining_budget <= 1e-6 or remaining_cargo <= 1e-6:
            break
        projected_util = (total_m3 / max(1e-9, float(cargo_m3))) if float(cargo_m3) > 0 else 1.0
        if projected_util >= max(0.0, min(1.0, cargo_fill_stop_util)):
            break
        tid = int(getattr(c, "type_id", 0))
        existing_pick = picks_by_type.get(tid)
        is_existing = existing_pick is not None
        if not is_existing and (added_new_types >= max_new_slots or len(picks) >= max_items):
            if not allow_topup_existing:
                break
            continue

        unit_cost = float(getattr(c, "buy_avg", 0.0)) * (1.0 + buy_broker)
        unit_vol = float(getattr(c, "unit_volume", 0.0))
        if unit_cost <= 0.0 or unit_vol <= 0.0:
            continue

        max_budget_for_item = float(budget_isk) * max_share
        already_for_item = float(spent_by_type.get(tid, 0.0))
        existing_qty = int(existing_pick.get("qty", 0)) if is_existing else 0
        max_candidate_remaining = int(getattr(c, "max_units", 0)) - existing_qty if is_existing else int(getattr(c, "max_units", 0))
        if max_candidate_remaining <= 0:
            continue
        max_by_budget = int(remaining_budget // unit_cost)
        max_by_share = int((max_budget_for_item - already_for_item) // unit_cost)
        max_by_cargo = int(remaining_cargo // unit_vol)
        qty = min(max_candidate_remaining, max_by_budget, max_by_share, max_by_cargo)
        if qty <= 0:
            continue

        total_qty_after = existing_qty + qty
        if bool(getattr(c, "instant", True)):
            instant_fill_ratio_after = min(1.0, float(getattr(c, "dest_buy_depth_units", 0)) / max(1.0, float(total_qty_after)))
            if instant_fill_ratio_after < min_instant_fill_ratio:
                continue
            turnover_factor_after = min(max_turnover_factor, max(0.0, instant_fill_ratio_after))
            fill_probability_after = instant_fill_ratio_after
        else:
            instant_fill_ratio_after = 1.0
            turnover_factor_after = float(getattr(c, "turnover_factor", 0.0))
            fill_probability_after = float(getattr(c, "fill_probability", 0.0))

        mode_str = str(getattr(c, "mode", "instant"))
        execution = "instant_instant" if mode_str.lower() == "instant" else "instant_listed"
        breakdown = FeeEngine(fees).compute(
            buy_price=float(getattr(c, "buy_avg", 0.0)),
            sell_price=float(getattr(c, "sell_avg", 0.0)),
            qty=qty,
            execution=execution,
            relist_budget_pct=relist_budget_pct if execution == "instant_listed" else 0.0,
            relist_budget_isk=(relist_budget_isk if mode_str.lower() == "planned_sell" else 0.0),
        )
        cost = float(breakdown.cost_net)
        revenue_net = float(breakdown.revenue_net)
        profit = float(breakdown.profit)
        if profit <= 0:
            continue
        cost_for_ratio = max(1e-9, cost)
        profit_pct = float(profit) / cost_for_ratio
        if profit_pct < max(0.0, cargo_fill_min_profit_pct):
            continue
        if float(profit) < max(0.0, cargo_fill_min_profit_abs_isk):
            continue
        candidate_profit_per_m3 = (float(profit) / max(1e-9, unit_vol * qty))
        if base_profit_per_m3 > 0 and candidate_profit_per_m3 < (base_profit_per_m3 * max(0.0, cargo_fill_min_profit_per_m3_ratio)):
            continue

        if is_existing:
            existing_pick["qty"] = int(existing_pick.get("qty", 0)) + qty
            existing_pick["cost"] = float(existing_pick.get("cost", 0.0)) + cost
            existing_pick["revenue_net"] = float(existing_pick.get("revenue_net", 0.0)) + revenue_net
            existing_pick["profit"] = float(existing_pick.get("profit", 0.0)) + profit
            existing_pick["buy_broker_fee_total"] = float(existing_pick.get("buy_broker_fee_total", 0.0)) + float(breakdown.buy_broker_fee_total)
            existing_pick["sell_broker_fee_total"] = float(existing_pick.get("sell_broker_fee_total", 0.0)) + float(breakdown.sell_broker_fee_total)
            existing_pick["sales_tax_total"] = float(existing_pick.get("sales_tax_total", 0.0)) + float(breakdown.sales_tax_total)
            existing_pick["relist_budget_total"] = float(existing_pick.get("relist_budget_total", 0.0)) + float(breakdown.relist_budget_total)
            existing_pick["instant_fill_ratio"] = float(instant_fill_ratio_after)
            existing_pick["turnover_factor"] = float(turnover_factor_after)
            existing_pick["fill_probability"] = float(fill_probability_after)
            existing_pick["dest_buy_depth_units"] = int(getattr(c, "dest_buy_depth_units", existing_pick.get("dest_buy_depth_units", 0)))
            existing_pick["order_duration_days"] = order_duration
            if "buy_at" not in existing_pick:
                existing_pick["buy_at"] = str(getattr(c, "route_src_label", ""))
            if "sell_at" not in existing_pick:
                existing_pick["sell_at"] = str(getattr(c, "route_dst_label", ""))
            if "route_hops" not in existing_pick:
                existing_pick["route_hops"] = int(getattr(c, "dest_hop_count", 1))
            if "carried_through_legs" not in existing_pick:
                existing_pick["carried_through_legs"] = int(getattr(c, "carried_through_legs", getattr(c, "dest_hop_count", 1)))
            if "route_src_index" not in existing_pick:
                existing_pick["route_src_index"] = int(getattr(c, "route_src_index", 0))
            if "route_dst_index" not in existing_pick:
                existing_pick["route_dst_index"] = int(getattr(c, "route_dst_index", 0))
            if "release_leg_index" not in existing_pick:
                existing_pick["release_leg_index"] = int(getattr(c, "route_dst_index", 0) - 1) if int(getattr(c, "route_dst_index", 0)) > 0 else int(existing_pick.get("release_leg_index", -1))
            total_pick_cost = float(existing_pick.get("cost", 0.0))
            total_pick_profit = float(existing_pick.get("profit", 0.0))
            total_pick_m3 = float(existing_pick.get("unit_volume", unit_vol)) * float(existing_pick.get("qty", 0))
            existing_pick["profit_pct"] = (total_pick_profit / total_pick_cost) if total_pick_cost > 0 else 0.0
            existing_pick["profit_per_m3"] = (total_pick_profit / total_pick_m3) if total_pick_m3 > 0 else 0.0
            existing_pick["profit_per_m3_per_day"] = float(existing_pick["profit_per_m3"]) * float(turnover_factor_after)
        else:
            pick_profit_per_m3 = (float(profit) / float(qty) / unit_vol)
            pick_profit_per_m3_per_day = pick_profit_per_m3 * turnover_factor_after
            new_pick = {
                "type_id": c.type_id,
                "name": c.name,
                "qty": qty,
                "unit_volume": unit_vol,
                "buy_avg": c.buy_avg,
                "sell_avg": c.sell_avg,
                "cost": cost,
                "revenue_net": revenue_net,
                "profit": profit,
                "profit_pct": profit / cost if cost > 0 else 0.0,
                "buy_broker_fee_total": float(breakdown.buy_broker_fee_total),
                "sell_broker_fee_total": float(breakdown.sell_broker_fee_total),
                "sales_tax_total": float(breakdown.sales_tax_total),
                "relist_budget_total": float(breakdown.relist_budget_total),
                "instant": c.instant,
                "suggested_sell_price": c.suggested_sell_price,
                "order_duration_days": order_duration,
                "liquidity_score": c.liquidity_score,
                "history_volume_30d": c.history_volume_30d,
                "daily_volume": c.daily_volume,
                "dest_buy_depth_units": c.dest_buy_depth_units,
                "instant_fill_ratio": instant_fill_ratio_after,
                "competition_price_levels_near_best": c.competition_price_levels_near_best,
                "queue_ahead_units": c.queue_ahead_units,
                "fill_probability": fill_probability_after,
                "turnover_factor": turnover_factor_after,
                "profit_per_m3": pick_profit_per_m3,
                "profit_per_m3_per_day": pick_profit_per_m3_per_day,
                "mode": getattr(c, "mode", "instant"),
                "target_sell_price": float(getattr(c, "target_sell_price", 0.0)),
                "avg_daily_volume_30d": float(getattr(c, "avg_daily_volume_30d", 0.0)),
                "avg_daily_volume_7d": float(getattr(c, "avg_daily_volume_7d", 0.0)),
                "expected_days_to_sell": float(getattr(c, "expected_days_to_sell", 0.0)),
                "sell_through_ratio_90d": float(getattr(c, "sell_through_ratio_90d", 0.0)),
                "risk_score": float(getattr(c, "risk_score", 0.0)),
                "expected_profit_90d": float(getattr(c, "expected_profit_90d", 0.0)),
                "expected_profit_per_m3_90d": float(getattr(c, "expected_profit_per_m3_90d", 0.0)),
                "used_volume_fallback": bool(getattr(c, "used_volume_fallback", False)),
                "reference_price": float(getattr(c, "reference_price", 0.0)),
                "reference_price_average": float(getattr(c, "reference_price_average", 0.0)),
                "reference_price_adjusted": float(getattr(c, "reference_price_adjusted", 0.0)),
                "jita_split_price": float(getattr(c, "jita_split_price", 0.0)),
                "reference_price_source": str(getattr(c, "reference_price_source", "")),
                "buy_discount_vs_ref": float(getattr(c, "buy_discount_vs_ref", 0.0)),
                "sell_markup_vs_ref": float(getattr(c, "sell_markup_vs_ref", 0.0)),
                "reference_price_penalty": float(getattr(c, "reference_price_penalty", 0.0)),
                "strict_confidence_score": float(getattr(c, "strict_confidence_score", 0.0)),
                "strict_mode_enabled": bool(getattr(c, "strict_mode_enabled", False)),
                "buy_at": str(getattr(c, "route_src_label", "")),
                "sell_at": str(getattr(c, "route_dst_label", "")),
                "route_hops": int(getattr(c, "dest_hop_count", 1)),
                "carried_through_legs": int(getattr(c, "carried_through_legs", getattr(c, "dest_hop_count", 1))),
                "route_src_index": int(getattr(c, "route_src_index", 0)),
                "route_dst_index": int(getattr(c, "route_dst_index", 0)),
                "extra_leg_penalty": float(getattr(c, "extra_leg_penalty", 0.0)),
                "route_wide_selected": bool(getattr(c, "route_wide_selected", False)),
                "route_adjusted_score": float(getattr(c, "route_adjusted_score", 0.0)),
                "release_leg_index": int(getattr(c, "route_dst_index", 0) - 1) if int(getattr(c, "route_dst_index", 0)) > 0 else -1
            }
            picks.append(new_pick)
            picks_by_type[tid] = new_pick
            added_new_types += 1

        total_cost += cost
        total_profit += profit
        total_m3 += (unit_vol * qty)
        remaining_budget -= cost
        remaining_cargo -= (unit_vol * qty)
        spent_by_type[tid] = already_for_item + cost
        added += 1

    return picks, total_cost, total_profit, total_m3, added


def choose_portfolio_for_route(
    esi,
    route_label: str,
    source_orders: list[dict],
    dest_orders: list[dict],
    candidates: list[TradeCandidate],
    filters_used: dict,
    dest_structure_id: int,
    budget_isk: float,
    cargo_m3: float,
    fees: dict,
    port_cfg: dict,
    cfg: dict
) -> tuple[list[dict], float, float, float, str]:
    def build_from_candidates(cands, f_used):
        inst = [c for c in cands if c.instant]
        if inst:
            p, c, pr, m = build_portfolio(inst, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            md = "instant"
        else:
            p, c, pr, m = build_portfolio(cands, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            md = "fallback"
        p.sort(key=lambda x: x["profit"], reverse=True)
        return p, c, pr, m, md

    picks, cost, profit, m3, mode = build_from_candidates(candidates, filters_used)
    target_util = float(port_cfg.get("target_budget_utilization", 0.0))
    util = (cost / budget_isk) if budget_isk > 0 else 1.0
    strict_active = bool(filters_used.get("strict_mode_enabled", False))
    if (not strict_active) and target_util > 0 and util < (target_util - 0.05):
        relaxed = dict(filters_used)
        relaxed["min_profit_pct"] = max(0.0, float(filters_used.get("min_profit_pct", 0.0)) - 0.01)
        relaxed["min_profit_isk_total"] = max(0.0, float(filters_used.get("min_profit_isk_total", 0.0)) * 0.5)
        print(
            f"    Hinweis: {route_label} nutzt nur {util*100:.1f}% Budget "
            f"(Ziel {target_util*100:.1f}%), berechne mit gelockerten Schwellwerten..."
        )
        relaxed_candidates = compute_candidates(
            esi, source_orders, dest_orders, fees, relaxed, dest_structure_id=dest_structure_id
        )
        r_picks, r_cost, r_profit, r_m3, r_mode = build_from_candidates(relaxed_candidates, relaxed)
        if r_cost > cost and r_profit >= (profit * 0.95):
            print("    Gelockerte Schwellwerte liefern bessere Auslastung, Portfolio wurde aktualisiert.")
            picks, cost, profit, m3, mode = r_picks, r_cost, r_profit, r_m3, r_mode

    cargo_fill_enabled = bool(port_cfg.get("cargo_fill_enabled", False))
    cargo_fill_trigger_gap = float(port_cfg.get("cargo_fill_trigger_gap", 0.20))
    cargo_fill_profit_floor_ratio = float(port_cfg.get("cargo_fill_profit_floor_ratio", 0.90))
    target_cargo_util = float(port_cfg.get("target_cargo_utilization", 0.0))
    cargo_util = (m3 / cargo_m3) if cargo_m3 > 0 else 1.0
    cargo_gap = target_cargo_util - cargo_util
    if (
        cargo_fill_enabled
        and target_cargo_util > 0.0
        and cargo_m3 > 0.0
        and cargo_gap >= cargo_fill_trigger_gap
        and cost < budget_isk
        and m3 < cargo_m3
    ):
        print(
            f"    Hinweis: {route_label} nutzt nur {cargo_util*100:.1f}% Cargo "
            f"(Ziel {target_cargo_util*100:.1f}%), starte Cargo-Fill..."
        )
        f_picks, f_cost, f_profit, f_m3, added = try_cargo_fill(
            picks, candidates, budget_isk, cargo_m3, fees, filters_used, port_cfg
        )
        min_allowed_profit = float(profit) * max(0.0, cargo_fill_profit_floor_ratio)
        if added > 0 and f_m3 > (m3 + 1e-6) and f_profit >= min_allowed_profit:
            print(
                "    Cargo-Fill verbessert Auslastung bei ausreichender Profitqualitaet, "
                "Portfolio wurde aktualisiert."
            )
            picks, cost, profit, m3 = f_picks, f_cost, f_profit, f_m3
        else:
            print("    Cargo-Fill verworfen (kein ausreichender Cargo-Gewinn oder Profitfloor unterschritten).")
    return picks, cost, profit, m3, mode


def evaluate_leg_disabled(leg_result: dict, budget_util_min_pct: float) -> tuple[bool, str]:
    if int(leg_result.get("items_count", 0)) <= 0:
        return True, "no_items"
    if float(leg_result.get("budget_util_pct", 0.0)) < float(budget_util_min_pct):
        return True, f"low_budget_util<{budget_util_min_pct:.2f}%"
    return False, ""


def _resolve_capital_flow_cfg(cfg: dict) -> dict:
    cap = cfg.get("capital_flow", {})
    if not isinstance(cap, dict):
        cap = {}
    strict_cfg = cfg.get("strict_mode", {})
    strict_enabled = isinstance(strict_cfg, dict) and bool(strict_cfg.get("enabled", False))
    strict_release_fast = bool(strict_cfg.get("fast_sell_allowed_for_capital_release", False)) if strict_enabled else None
    release_fast_default = bool(cap.get("release_on_fast_sell", False))
    release_fast = (strict_release_fast if strict_release_fast is not None else release_fast_default)
    return {
        "enabled": bool(cap.get("enabled", False)),
        "release_on_instant": bool(cap.get("release_on_instant", True)),
        "release_on_fast_sell": bool(release_fast),
        "fast_sell_release_ratio": max(0.0, min(1.0, float(cap.get("fast_sell_release_ratio", 1.0))))
    }



def _resolve_budget_split_cfg(port_cfg: dict) -> dict:
    # New simple ratio keys (preferred by prompt) with backward-compatible fallback.
    if "instant_budget_ratio" in port_cfg or "planned_budget_ratio" in port_cfg:
        inst = float(port_cfg.get("instant_budget_ratio", 1.0) or 1.0)
        planned = float(port_cfg.get("planned_budget_ratio", 0.0) or 0.0)
        total = inst + planned
        if total <= 0:
            return {"instant": 1.0, "planned_sell": 0.0, "enabled": False}
        if abs(total - 1.0) > 1e-6:
            inst = inst / total
            planned = planned / total
        return {"instant": max(0.0, inst), "planned_sell": max(0.0, planned), "enabled": True}

    raw = port_cfg.get("instant_planned_budget_split", {})
    if not isinstance(raw, dict):
        raw = {}
    inst = float(raw.get("instant", 1.0) or 1.0)
    planned = float(raw.get("planned_sell", 0.0) or 0.0)
    total = inst + planned
    if total <= 0:
        return {"instant": 1.0, "planned_sell": 0.0, "enabled": False}
    if abs(total - 1.0) > 1e-6:
        inst = inst / total
        planned = planned / total
    enabled = bool(raw.get("enabled", False))
    return {"instant": max(0.0, inst), "planned_sell": max(0.0, planned), "enabled": enabled}


def _compute_chain_leg_budget(
    capital_available: float,
    start_budget_isk: float,
    cap_cfg: dict,
    strict_cfg: dict
) -> tuple[float, bool]:
    base_budget = float(capital_available) if bool(cap_cfg.get("enabled", False)) else float(start_budget_isk)
    strict_enabled = bool(strict_cfg.get("enabled", False))
    max_share = float(strict_cfg.get("chain_leg_max_budget_share", 1.0)) if strict_enabled else 1.0
    if strict_enabled and 0.0 < max_share < 1.0:
        cap_budget = float(capital_available) * max_share if bool(cap_cfg.get("enabled", False)) else float(start_budget_isk) * max_share
        capped_budget = min(base_budget, cap_budget)
        return float(max(0.0, capped_budget)), bool(capped_budget + 1e-6 < base_budget)
    return float(max(0.0, base_budget)), False


def _apply_capital_flow_to_leg(
    leg: dict,
    mode: str,
    capital_before: float,
    cap_cfg: dict,
    current_leg_index: int | None = None,
    pending_releases: dict[int, float] | None = None
) -> float:
    enabled = bool(cap_cfg.get("enabled", False))
    spent = float(leg.get("isk_used", 0.0))
    released = 0.0
    release_rule = "none"
    if enabled:
        picks = leg.get("picks", []) or []
        release_instant = bool(cap_cfg.get("release_on_instant", True))
        release_fast = bool(cap_cfg.get("release_on_fast_sell", False))
        fast_ratio = float(cap_cfg.get("fast_sell_release_ratio", 1.0))

        if pending_releases is not None and current_leg_index is not None:
            for p in picks:
                p_mode = str(p.get("mode", "")).strip().lower()
                if not p_mode:
                    p_mode = "instant" if bool(p.get("instant", False)) else str(mode).lower()
                rev = float(p.get("revenue_net", 0.0) or 0.0)
                if p_mode == "instant" and release_instant:
                    ridx = int(p.get("release_leg_index", current_leg_index))
                    pending_releases[ridx] = float(pending_releases.get(ridx, 0.0)) + rev
                elif p_mode == "fast_sell" and release_fast:
                    ridx = int(p.get("release_leg_index", current_leg_index))
                    pending_releases[ridx] = float(pending_releases.get(ridx, 0.0)) + (rev * fast_ratio)
            released = float(pending_releases.pop(int(current_leg_index), 0.0))
            if released > 0.0:
                release_rule = "route_exit_schedule"
        else:
            for p in picks:
                p_mode = str(p.get("mode", "")).strip().lower()
                if not p_mode:
                    p_mode = "instant" if bool(p.get("instant", False)) else str(mode).lower()
                rev = float(p.get("revenue_net", 0.0) or 0.0)
                if p_mode == "instant" and release_instant:
                    released += rev
                elif p_mode == "fast_sell" and release_fast:
                    released += rev * fast_ratio

            if released > 0.0:
                parts = []
                if release_instant:
                    parts.append("instant_revenue_net")
                if release_fast:
                    parts.append(f"fast_sell_revenue_net_x{fast_ratio:.2f}")
                release_rule = "+".join(parts) if parts else "none"
        capital_after = max(0.0, float(capital_before) - spent + released)
    else:
        capital_after = float(capital_before)

    leg["capital_flow_enabled"] = bool(enabled)
    leg["capital_available_before"] = float(capital_before)
    leg["capital_committed"] = float(spent)
    leg["capital_released"] = float(released)
    leg["capital_available_after"] = float(capital_after)
    leg["capital_release_rule"] = release_rule
    if pending_releases is not None:
        leg["capital_locked_future_release"] = float(sum(float(v) for v in pending_releases.values()))
    return float(capital_after)


def _choose_portfolio_from_candidates_only(
    route_label: str,
    candidates: list[TradeCandidate],
    filters_used: dict,
    budget_isk: float,
    cargo_m3: float,
    fees: dict,
    port_cfg: dict,
    cfg: dict
) -> tuple[list[dict], float, float, float, str]:
    def build_from_candidates(cands, f_used):
        inst = [c for c in cands if bool(getattr(c, "instant", False))]
        if inst:
            p, c, pr, m = build_portfolio(inst, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            md = "instant"
        else:
            p, c, pr, m = build_portfolio(cands, budget_isk, cargo_m3, fees, f_used, port_cfg, cfg)
            md = "fallback"
        p.sort(key=lambda x: x["profit"], reverse=True)
        return p, c, pr, m, md

    picks, cost, profit, m3, mode = build_from_candidates(candidates, filters_used)
    cargo_fill_enabled = bool(port_cfg.get("cargo_fill_enabled", False))
    cargo_fill_trigger_gap = float(port_cfg.get("cargo_fill_trigger_gap", 0.20))
    cargo_fill_profit_floor_ratio = float(port_cfg.get("cargo_fill_profit_floor_ratio", 0.90))
    target_cargo_util = float(port_cfg.get("target_cargo_utilization", 0.0))
    cargo_util = (m3 / cargo_m3) if cargo_m3 > 0 else 1.0
    cargo_gap = target_cargo_util - cargo_util
    if (
        cargo_fill_enabled
        and target_cargo_util > 0.0
        and cargo_m3 > 0.0
        and cargo_gap >= cargo_fill_trigger_gap
        and cost < budget_isk
        and m3 < cargo_m3
    ):
        print(
            f"    Hinweis: {route_label} nutzt nur {cargo_util*100:.1f}% Cargo "
            f"(Ziel {target_cargo_util*100:.1f}%), starte Cargo-Fill..."
        )
        f_picks, f_cost, f_profit, f_m3, added = try_cargo_fill(
            picks, candidates, budget_isk, cargo_m3, fees, filters_used, port_cfg
        )
        min_allowed_profit = float(profit) * max(0.0, cargo_fill_profit_floor_ratio)
        if added > 0 and f_m3 > (m3 + 1e-6) and f_profit >= min_allowed_profit:
            print("    Cargo-Fill uebernommen.")
            picks, cost, profit, m3 = f_picks, f_cost, f_profit, f_m3
        else:
            print("    Cargo-Fill verworfen.")
    return picks, cost, profit, m3, mode


def run_route_wide_leg(
    esi,
    route_tag: str,
    source_node: dict,
    immediate_dest_node: dict,
    source_index: int,
    chain_nodes_ordered: list[dict],
    max_hops: int,
    scan_cfg: dict,
    structure_orders_by_id: dict[int, list[dict]],
    filters: dict,
    portfolio_cfg: dict,
    fees: dict,
    mode: str,
    budget_isk: float,
    cargo_m3: float,
    cfg: dict,
    timestamp: str,
    out_dir: str
) -> dict:
    route_label = f"{source_node['label']} -> {immediate_dest_node['label']}"
    print(f"Berechne {route_label} (route-wide)...")
    filters_used = dict(filters)
    filters_used["mode"] = mode

    destination_nodes: list[dict] = []
    max_hops_i = max(1, int(max_hops))
    for j in range(source_index + 1, len(chain_nodes_ordered)):
        hop_count = int(j - source_index)
        if hop_count > max_hops_i:
            break
        n = dict(chain_nodes_ordered[j])
        n["route_index"] = int(j)
        n["hop_count"] = int(hop_count)
        destination_nodes.append(n)

    candidates: list[TradeCandidate] = []
    explain: dict = {"reason_counts": {}}
    if str(mode).lower() == "instant_first":
        budget_split = _resolve_budget_split_cfg(portfolio_cfg)
        instant_budget = float(budget_isk)
        planned_budget_cap = float(budget_isk)
        if bool(budget_split.get("enabled", False)):
            instant_budget = min(float(budget_isk), float(budget_isk) * float(budget_split.get("instant", 1.0)))
            planned_budget_cap = max(0.0, float(budget_isk) * float(budget_split.get("planned_sell", 0.0)))
        instant_filters = dict(filters_used)
        instant_filters["mode"] = "instant"
        instant_candidates, instant_explain = _mod_compute_route_wide_candidates_for_source(
            esi=esi,
            source_node=source_node,
            source_index=source_index,
            destination_nodes=destination_nodes,
            chain_nodes_ordered=chain_nodes_ordered,
            structure_orders_by_id=structure_orders_by_id,
            fees=fees,
            filters=instant_filters,
            scan_cfg=scan_cfg,
            cfg=cfg
        )
        for k, v in dict(instant_explain.get("reason_counts", {})).items():
            explain["reason_counts"][k] = int(explain["reason_counts"].get(k, 0)) + int(v)
        candidates.extend(instant_candidates)

        remaining_budget = float(budget_isk)
        remaining_cargo = float(cargo_m3)
        picks, total_cost, total_profit, total_m3, selected_mode = _choose_portfolio_from_candidates_only(
            route_label=route_label,
            candidates=instant_candidates,
            filters_used=instant_filters,
            budget_isk=instant_budget,
            cargo_m3=remaining_cargo,
            fees=fees,
            port_cfg=portfolio_cfg,
            cfg=cfg
        )
        remaining_budget = max(0.0, remaining_budget - float(total_cost))
        remaining_cargo = max(0.0, remaining_cargo - float(total_m3))

        planned_filters = dict(filters_used)
        planned_filters["mode"] = "planned_sell"
        planned_candidates, planned_explain = _mod_compute_route_wide_candidates_for_source(
            esi=esi,
            source_node=source_node,
            source_index=source_index,
            destination_nodes=destination_nodes,
            chain_nodes_ordered=chain_nodes_ordered,
            structure_orders_by_id=structure_orders_by_id,
            fees=fees,
            filters=planned_filters,
            scan_cfg=scan_cfg,
            cfg=cfg
        )
        for k, v in dict(planned_explain.get("reason_counts", {})).items():
            explain["reason_counts"][k] = int(explain["reason_counts"].get(k, 0)) + int(v)
        picked_ids = {int(p.get("type_id", 0)) for p in picks}
        planned_candidates = [c for c in planned_candidates if int(c.type_id) not in picked_ids]
        candidates.extend(planned_candidates)
        if planned_candidates and remaining_budget > 1e-6 and remaining_cargo > 1e-6:
            planned_budget = remaining_budget
            if bool(budget_split.get("enabled", False)):
                planned_budget = min(planned_budget, planned_budget_cap)
            p2, c2, pr2, m2, _ = _choose_portfolio_from_candidates_only(
                route_label=route_label,
                candidates=planned_candidates,
                filters_used=planned_filters,
                budget_isk=planned_budget,
                cargo_m3=remaining_cargo,
                fees=fees,
                port_cfg=portfolio_cfg,
                cfg=cfg
            )
            if p2:
                picks.extend(p2)
                total_cost += float(c2)
                total_profit += float(pr2)
                total_m3 += float(m2)
                selected_mode = "instant_first/mixed"
    else:
        candidates, explain = _mod_compute_route_wide_candidates_for_source(
            esi=esi,
            source_node=source_node,
            source_index=source_index,
            destination_nodes=destination_nodes,
            chain_nodes_ordered=chain_nodes_ordered,
            structure_orders_by_id=structure_orders_by_id,
            fees=fees,
            filters=filters_used,
            scan_cfg=scan_cfg,
            cfg=cfg
        )
        picks, total_cost, total_profit, total_m3, selected_mode = _choose_portfolio_from_candidates_only(
            route_label=route_label,
            candidates=candidates,
            filters_used=filters_used,
            budget_isk=budget_isk,
            cargo_m3=cargo_m3,
            fees=fees,
            port_cfg=portfolio_cfg,
            cfg=cfg
        )

    for p in picks:
        if not p.get("buy_at"):
            p["buy_at"] = str(source_node["label"])
        if not p.get("sell_at"):
            p["sell_at"] = str(immediate_dest_node["label"])
        p["route_hops"] = int(p.get("route_hops", max(1, int(p.get("route_dst_index", source_index + 1)) - int(source_index))))
        p["carried_through_legs"] = int(p.get("carried_through_legs", p["route_hops"]))
        if "release_leg_index" not in p:
            dst_idx = int(p.get("route_dst_index", source_index + 1))
            p["release_leg_index"] = max(0, dst_idx - 1)

    if not bool(scan_cfg.get("allow_mixed_destinations_within_leg", True)) and picks:
        # Keep leg execution simple if mixed exits are disabled: keep dominant sell target only.
        by_sell: dict[str, float] = {}
        for p in picks:
            dst = str(p.get("sell_at", ""))
            by_sell[dst] = float(by_sell.get(dst, 0.0)) + float(p.get("profit", 0.0))
        dominant_sell = max(by_sell.items(), key=lambda x: x[1])[0] if by_sell else ""
        picks = [p for p in picks if str(p.get("sell_at", "")) == dominant_sell]
        total_cost = sum(float(p.get("cost", 0.0)) for p in picks)
        total_profit = sum(float(p.get("profit", 0.0)) for p in picks)
        total_m3 = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in picks)

    route_context = build_route_context(
        cfg,
        route_tag,
        str(source_node["label"]),
        str(immediate_dest_node["label"]),
        source_id=int(source_node.get("id", 0) or 0),
        dest_id=int(immediate_dest_node.get("id", 0) or 0),
    )
    picks, transport_summary = apply_route_costs_and_prune(picks, route_context, filters_used)
    if bool(transport_summary.get("transport_cost_assumed_zero", False)):
        warn_msg = str(transport_summary.get("cost_model_warning", "") or "")
        if warn_msg:
            print(f"    WARN: {route_label}: {warn_msg}")
    total_cost = sum(float(p.get("cost", 0.0)) for p in picks)
    total_revenue = sum(float(p.get("revenue_net", 0.0)) for p in picks)
    total_profit = sum(float(p.get("profit", 0.0)) for p in picks)
    total_fees_taxes = sum(_pick_total_fees_taxes(p) for p in picks)
    total_m3 = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in picks)
    sort_picks_for_output(picks, filters_used)
    csv_name = f"{label_to_slug(source_node['label'])}_to_{label_to_slug(immediate_dest_node['label'])}_{timestamp}.csv"
    csv_path = os.path.join(out_dir, csv_name)
    write_csv(csv_path, picks)

    dump_name = f"{route_tag}_top_candidates_{timestamp}.txt"
    dump_path = os.path.join(out_dir, dump_name)
    write_top_candidate_dump(dump_path, candidates, route_label, filters_used, explain)

    reason_counts = dict(explain.get("reason_counts", {}))
    passed_all = int(reason_counts.get("passed_all_filters", 0))
    budget_util_pct = (float(total_cost) / float(budget_isk) * 100.0) if float(budget_isk) > 0 else 0.0
    cargo_util_pct = (float(total_m3) / float(cargo_m3) * 100.0) if float(cargo_m3) > 0 else 0.0
    budget_left_reason = ""
    if float(budget_isk) > 0 and (float(budget_isk) - float(total_cost)) / float(budget_isk) >= 0.05:
        budget_left_reason = "Keine weiteren Picks erfuellen Profit-Floors nach Gebuehren und Routenkosten."
    return {
        "route_tag": route_tag,
        "route_label": route_label,
        "source_structure_id": int(source_node["id"]),
        "dest_structure_id": int(immediate_dest_node["id"]),
        "source_label": str(source_node["label"]),
        "dest_label": str(immediate_dest_node["label"]),
        "filters_used": filters_used,
        "mode": mode,
        "selected_mode": selected_mode,
        "candidates": candidates,
        "picks": picks,
        "csv_path": csv_path,
        "dump_path": dump_path,
        "items_count": len(picks),
        "m3_used": float(total_m3),
        "cargo_total": float(cargo_m3),
        "cargo_util_pct": float(cargo_util_pct),
        "isk_used": float(total_cost),
        "net_revenue_total": float(total_revenue),
        "total_fees_taxes": float(total_fees_taxes),
        "budget_total": float(budget_isk),
        "budget_util_pct": float(budget_util_pct),
        "budget_left_reason": budget_left_reason,
        "profit_total": float(total_profit),
        "total_shipping_cost": float(transport_summary.get("total_shipping_cost", 0.0)),
        "shipping_cost_total": float(transport_summary.get("total_shipping_cost", 0.0)),
        "total_route_cost": float(transport_summary.get("total_route_cost", 0.0)),
        "total_transport_cost": float(transport_summary.get("total_transport_cost", 0.0)),
        "shipping_lane_id": str(transport_summary.get("shipping_lane_id", "")),
        "shipping_pricing_model": str(transport_summary.get("shipping_pricing_model", "")),
        "shipping_provider": str(transport_summary.get("shipping_provider", "")),
        "shipping_contracts_used": int(transport_summary.get("shipping_contracts_used", 0) or 0),
        "shipping_split_reason": str(transport_summary.get("shipping_split_reason", "")),
        "estimated_collateral_isk": float(transport_summary.get("estimated_collateral_isk", 0.0)),
        "shipping_lane_params": dict(transport_summary.get("shipping_lane_params", {})),
        "total_route_m3": float(transport_summary.get("total_route_m3", total_m3)),
        "route_cost_is_explicit": bool(transport_summary.get("route_cost_is_explicit", False)),
        "cost_model_status": str(transport_summary.get("cost_model_status", "configured")),
        "cost_model_confidence": str(transport_summary.get("cost_model_confidence", "normal")),
        "transport_cost_assumed_zero": bool(transport_summary.get("transport_cost_assumed_zero", False)),
        "cost_model_warning": str(transport_summary.get("cost_model_warning", "")),
        "total_candidates": len(candidates),
        "why_out_summary": reason_counts,
        "passed_all_filters": passed_all,
        "funnel": FilterFunnel(),
        "explain": explain
    }


def run_route(
    esi,
    source_structure_id: int,
    dest_structure_id: int,
    route_tag: str,
    source_label: str,
    dest_label: str,
    filters: dict,
    portfolio_cfg: dict,
    fees: dict,
    mode: str,
    replay_cfg: dict,
    replay_snapshot: dict | None,
    structure_orders_by_id: dict[int, list[dict]],
    budget_isk: float,
    cargo_m3: float,
    cfg: dict,
    timestamp: str,
    out_dir: str,
    source_node_meta: dict | None = None,
    dest_node_meta: dict | None = None,
    preferred_shipping_lane_id: str | None = None,
) -> dict:
    filters_used = dict(filters)
    filters_used["mode"] = mode
    source_orders = structure_orders_by_id.get(int(source_structure_id), [])
    dest_orders = structure_orders_by_id.get(int(dest_structure_id), [])
    route_context = build_route_context(
        cfg,
        route_tag,
        source_label,
        dest_label,
        source_id=int(source_structure_id),
        dest_id=int(dest_structure_id),
        preferred_shipping_lane_id=preferred_shipping_lane_id,
    )
    src_norm = normalize_location_label(source_label)
    dst_norm = normalize_location_label(dest_label)
    jita_orders_for_split: list[dict] = []
    if src_norm == "jita":
        jita_orders_for_split = source_orders
    elif dst_norm == "jita":
        jita_orders_for_split = dest_orders
    route_context["jita_split_prices"] = build_jita_split_price_map(jita_orders_for_split)

    funnel = FilterFunnel()
    explain = {}
    route_label = f"{source_label} -> {dest_label}"
    print(f"Berechne {route_label}...")
    candidates: list[TradeCandidate] = []
    picks: list[dict] = []
    total_cost = 0.0
    total_revenue = 0.0
    total_profit = 0.0
    total_m3 = 0.0
    selected_mode = "fallback"

    if str(mode).lower() == "instant_first":
        def merge_reason_counts(dst: dict, src: dict) -> None:
            for k, v in src.items():
                dst[k] = int(dst.get(k, 0)) + int(v)

        combined_reason_counts: dict[str, int] = {}
        budget_split = _resolve_budget_split_cfg(portfolio_cfg)
        instant_budget = float(budget_isk)
        planned_budget_cap = float(budget_isk)
        if bool(budget_split.get("enabled", False)):
            instant_budget = min(float(budget_isk), float(budget_isk) * float(budget_split.get("instant", 1.0)))
            planned_budget_cap = max(0.0, float(budget_isk) * float(budget_split.get("planned_sell", 0.0)))

        instant_filters = dict(filters_used)
        instant_filters["mode"] = "instant"
        instant_funnel = FilterFunnel()
        instant_explain = {}
        instant_candidates = compute_candidates(
            esi,
            source_orders,
            dest_orders,
            fees,
            instant_filters,
            dest_structure_id=dest_structure_id,
            route_context=route_context,
            funnel=instant_funnel,
            explain=instant_explain
        )
        merge_reason_counts(combined_reason_counts, dict(instant_explain.get("reason_counts", {})))
        print(f"Baue {route_label} Portfolio (Instant-Phase)...")
        instant_picks, instant_cost, instant_profit, instant_m3, instant_selected = choose_portfolio_for_route(
            esi,
            route_label,
            source_orders,
            dest_orders,
            instant_candidates,
            instant_filters,
            dest_structure_id,
            instant_budget,
            cargo_m3,
            fees,
            portfolio_cfg,
            cfg
        )
        candidates.extend(instant_candidates)
        picks = list(instant_picks)
        total_cost = float(instant_cost)
        total_profit = float(instant_profit)
        total_m3 = float(instant_m3)
        selected_mode = f"instant_first/instant:{instant_selected}"
        funnel = instant_funnel

        remaining_budget = max(0.0, float(budget_isk) - total_cost)
        remaining_cargo = max(0.0, float(cargo_m3) - total_m3)
        if remaining_budget > 1e-6 and remaining_cargo > 1e-6:
            planned_filters = dict(filters_used)
            planned_filters["mode"] = "planned_sell"
            planned_funnel = FilterFunnel()
            planned_explain = {}
            planned_candidates = compute_candidates(
                esi,
                source_orders,
                dest_orders,
                fees,
                planned_filters,
                dest_structure_id=dest_structure_id,
                route_context=route_context,
                funnel=planned_funnel,
                explain=planned_explain
            )
            merge_reason_counts(combined_reason_counts, dict(planned_explain.get("reason_counts", {})))
            instant_type_ids = {int(p.get("type_id")) for p in picks if p.get("type_id") is not None}
            planned_candidates_filtered = [
                c for c in planned_candidates
                if int(c.type_id) not in instant_type_ids
            ]
            candidates.extend(planned_candidates_filtered)
            if planned_candidates_filtered:
                print(f"Baue {route_label} Portfolio (Planned-Sell-Ergaenzung)...")
                planned_budget = remaining_budget
                if bool(budget_split.get("enabled", False)):
                    planned_budget = min(planned_budget, planned_budget_cap)
                planned_picks, planned_cost, planned_profit, planned_m3, planned_selected = choose_portfolio_for_route(
                    esi,
                    route_label,
                    source_orders,
                    dest_orders,
                    planned_candidates_filtered,
                    planned_filters,
                    dest_structure_id,
                    planned_budget,
                    remaining_cargo,
                    fees,
                    portfolio_cfg,
                    cfg
                )
                if planned_picks:
                    picks.extend(planned_picks)
                    total_cost += float(planned_cost)
                    total_profit += float(planned_profit)
                    total_m3 += float(planned_m3)
                    selected_mode = f"instant_first/mixed:{planned_selected}"
            for k, v in planned_funnel.stage_stats.items():
                if k in funnel.stage_stats:
                    funnel.stage_stats[k] += int(v)
            funnel.rejections.extend(planned_funnel.rejections)

        explain = {"reason_counts": combined_reason_counts}
    else:
        candidates = compute_candidates(
            esi,
            source_orders,
            dest_orders,
            fees,
            filters_used,
            dest_structure_id=dest_structure_id,
            route_context=route_context,
            funnel=funnel,
            explain=explain
        )

        print(f"Baue {route_label} Portfolio...")
        picks, total_cost, total_profit, total_m3, selected_mode = choose_portfolio_for_route(
            esi,
            route_label,
            source_orders,
            dest_orders,
            candidates,
            filters_used,
            dest_structure_id,
            budget_isk,
            cargo_m3,
            fees,
            portfolio_cfg,
            cfg
        )
    if selected_mode == "fallback":
        print("    * Hinweis: es wurden keine passenden Kaufauftraege gefunden, Vorschlaege basieren auf Verkaufsorder-Preisen.")

    picks, transport_summary = apply_route_costs_and_prune(picks, route_context, filters_used)
    if bool(transport_summary.get("transport_cost_assumed_zero", False)):
        warn_msg = str(transport_summary.get("cost_model_warning", "") or "")
        if warn_msg:
            print(f"    WARN: {route_label}: {warn_msg}")
    total_cost = sum(float(p.get("cost", 0.0)) for p in picks)
    total_revenue = sum(float(p.get("revenue_net", 0.0)) for p in picks)
    total_profit = sum(float(p.get("profit", 0.0)) for p in picks)
    total_fees_taxes = sum(_pick_total_fees_taxes(p) for p in picks)
    total_m3 = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in picks)
    sort_picks_for_output(picks, filters_used)
    csv_name = f"{label_to_slug(source_label)}_to_{label_to_slug(dest_label)}_{timestamp}.csv"
    csv_path = os.path.join(out_dir, csv_name)
    write_csv(csv_path, picks)

    dump_name = f"{route_tag}_top_candidates_{timestamp}.txt"
    dump_path = os.path.join(out_dir, dump_name)
    write_top_candidate_dump(dump_path, candidates, route_label, filters_used, explain)

    reason_counts = dict(explain.get("reason_counts", {}))
    passed_all = int(reason_counts.get("passed_all_filters", 0))
    budget_util_pct = (total_cost / budget_isk * 100.0) if budget_isk > 0 else 0.0
    cargo_util_pct = (total_m3 / cargo_m3 * 100.0) if cargo_m3 > 0 else 0.0
    budget_left_reason = ""
    if budget_isk > 0 and (float(budget_isk) - float(total_cost)) / float(budget_isk) >= 0.05:
        budget_left_reason = "Keine weiteren Picks erfuellen Profit-Floors nach Gebuehren und Routenkosten."

    return {
        "route_tag": route_tag,
        "route_label": route_label,
        "source_structure_id": int(source_structure_id),
        "dest_structure_id": int(dest_structure_id),
        "source_node_info": _node_source_dest_info(source_node_meta or {"label": source_label, "id": int(source_structure_id), "kind": "structure", "structure_id": int(source_structure_id)}),
        "dest_node_info": _node_source_dest_info(dest_node_meta or {"label": dest_label, "id": int(dest_structure_id), "kind": "structure", "structure_id": int(dest_structure_id)}),
        "source_label": source_label,
        "dest_label": dest_label,
        "filters_used": filters_used,
        "mode": mode,
        "selected_mode": selected_mode,
        "candidates": candidates,
        "picks": picks,
        "csv_path": csv_path,
        "dump_path": dump_path,
        "items_count": len(picks),
        "m3_used": float(total_m3),
        "cargo_total": float(cargo_m3),
        "cargo_util_pct": float(cargo_util_pct),
        "isk_used": float(total_cost),
        "net_revenue_total": float(total_revenue),
        "total_fees_taxes": float(total_fees_taxes),
        "budget_total": float(budget_isk),
        "budget_util_pct": float(budget_util_pct),
        "budget_left_reason": budget_left_reason,
        "profit_total": float(total_profit),
        "total_shipping_cost": float(transport_summary.get("total_shipping_cost", 0.0)),
        "shipping_cost_total": float(transport_summary.get("total_shipping_cost", 0.0)),
        "total_route_cost": float(transport_summary.get("total_route_cost", 0.0)),
        "total_transport_cost": float(transport_summary.get("total_transport_cost", 0.0)),
        "shipping_lane_id": str(transport_summary.get("shipping_lane_id", "")),
        "shipping_pricing_model": str(transport_summary.get("shipping_pricing_model", "")),
        "shipping_provider": str(transport_summary.get("shipping_provider", "")),
        "shipping_contracts_used": int(transport_summary.get("shipping_contracts_used", 0) or 0),
        "shipping_split_reason": str(transport_summary.get("shipping_split_reason", "")),
        "estimated_collateral_isk": float(transport_summary.get("estimated_collateral_isk", 0.0)),
        "shipping_lane_params": dict(transport_summary.get("shipping_lane_params", {})),
        "total_route_m3": float(transport_summary.get("total_route_m3", total_m3)),
        "route_cost_is_explicit": bool(transport_summary.get("route_cost_is_explicit", False)),
        "cost_model_status": str(transport_summary.get("cost_model_status", "configured")),
        "cost_model_confidence": str(transport_summary.get("cost_model_confidence", "normal")),
        "transport_cost_assumed_zero": bool(transport_summary.get("transport_cost_assumed_zero", False)),
        "cost_model_warning": str(transport_summary.get("cost_model_warning", "")),
        "total_candidates": len(candidates),
        "why_out_summary": reason_counts,
        "passed_all_filters": passed_all,
        "funnel": funnel,
        "explain": explain
    }


def write_chain_summary(path: str, chain_label: str, timestamp: str, leg_results: list[dict]) -> None:
    def fmt_isk_exact(x: float) -> str:
        return f"{float(x):,.2f} ISK"

    def format_trade_instruction(leg: dict, pick: dict, idx: int) -> list[str]:
        src = str(pick.get("buy_at") or leg.get("source_label", "SOURCE"))
        dst = str(pick.get("sell_at") or leg.get("dest_label", "DEST"))
        qty = int(pick.get("qty", 0))
        buy_unit = float(pick.get("buy_avg", 0.0))
        sell_unit = float(pick.get("target_sell_price", 0.0) or pick.get("sell_avg", 0.0))
        buy_total = buy_unit * qty
        sell_total = sell_unit * qty
        instant = bool(pick.get("instant", True))
        duration_days = int(float(pick.get("order_duration_days", 0) or 0))
        expected_days = float(pick.get("expected_days_to_sell", 0.0) or 0.0)
        fill_prob = float(pick.get("fill_probability", 0.0) or 0.0)
        profit = float(pick.get("profit", 0.0) or 0.0)
        pick_m3 = float(pick.get("unit_volume", 0.0) or 0.0) * float(qty)
        route_hops = int(pick.get("route_hops", 1))

        lines_local = []
        lines_local.append(f"  {idx}. {pick.get('name', '')} (type_id {pick.get('type_id', 0)})")
        lines_local.append(
            f"     BUY  in {src}: qty={qty} @ {fmt_isk_exact(buy_unit)} pro Stk "
            f"(Gesamt {fmt_isk_exact(buy_total)})"
        )
        if instant:
            lines_local.append(
                f"     SELL in {dst}: SOFORTVERKAUF/Buy-Order @ {fmt_isk_exact(sell_unit)} pro Stk "
                f"(Gesamt {fmt_isk_exact(sell_total)})"
            )
        else:
            lines_local.append(
                f"     SELL in {dst}: SELL-ORDER @ {fmt_isk_exact(sell_unit)} pro Stk "
                f"(Gesamt {fmt_isk_exact(sell_total)}) | Laufzeit: {duration_days}d"
            )
            lines_local.append(
                f"     Erwartete Verkaufsdauer: {expected_days:.1f}d | Fill-Wahrscheinlichkeit: {fill_prob*100:.1f}%"
            )
        lines_local.append(f"     Erwarteter Profit: {fmt_isk_exact(profit)}")
        lines_local.append(f"     Cargo fuer diesen Pick: {pick_m3:.2f} m3")
        lines_local.append(f"     Route-Hops: {route_hops}")
        return lines_local

    lines = []
    lines.append("=" * 70)
    lines.append(f"{chain_label.upper()} CHAIN SUMMARY")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    lines.append("")
    if not leg_results:
        lines.append("Keine Legs ausgefuehrt.")
        lines.append("")
    for leg in leg_results:
        lines.append(f"Route: {leg['route_label']}")
        lines.append(f"leg_disabled: {bool(leg.get('leg_disabled', False))} ({leg.get('leg_disabled_reason', '')})")
        lines.append(f"Mode: {leg['mode']} (selected: {leg['selected_mode']})")
        lines.append(f"strict_mode_enabled: {bool(leg['filters_used'].get('strict_mode_enabled', False))}")
        lines.append(f"Ranking Metric: {str(leg['filters_used'].get('ranking_metric', 'profit_per_m3_per_day'))}")
        lines.append(f"Filters: {json.dumps(leg['filters_used'], ensure_ascii=False, sort_keys=True)}")
        lines.append(f"Total candidates: {leg['total_candidates']}")
        lines.append(f"passed_all_filters: {leg['passed_all_filters']}")
        lines.append("WHY_OUT Summary (top 10):")
        reason_counts = leg.get("why_out_summary", {})
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"  {reason}: {count}")
        lines.append("Portfolio:")
        lines.append(f"  items_count: {leg['items_count']}")
        lines.append(f"  m3_used/cargo_total: {leg['m3_used']:.2f}/{leg['cargo_total']:.2f} ({leg['cargo_util_pct']:.2f}%)")
        lines.append(f"  isk_used/budget_total: {fmt_isk(leg['isk_used'])}/{fmt_isk(leg['budget_total'])} ({leg['budget_util_pct']:.2f}%)")
        lines.append(f"  profit_total: {fmt_isk(leg['profit_total'])}")
        if "capital_available_before" in leg:
            lines.append("CAPITAL FLOW:")
            lines.append(f"  available_before: {fmt_isk(float(leg.get('capital_available_before', 0.0)))}")
            lines.append(f"  committed_this_leg: {fmt_isk(float(leg.get('capital_committed', 0.0)))}")
            lines.append(f"  released_this_leg: {fmt_isk(float(leg.get('capital_released', 0.0)))}")
            lines.append(f"  available_after: {fmt_isk(float(leg.get('capital_available_after', 0.0)))}")
            lines.append(f"  release_rule: {str(leg.get('capital_release_rule', 'none'))}")
        cargo_total = float(leg.get("cargo_total", 0.0))
        cargo_used = float(leg.get("m3_used", 0.0))
        cargo_free = max(0.0, cargo_total - cargo_used)
        cargo_util_pct = (cargo_used / cargo_total * 100.0) if cargo_total > 0 else 0.0
        lines.append("CARGO:")
        lines.append(f"  used_m3: {cargo_used:.2f}")
        lines.append(f"  free_m3: {cargo_free:.2f}")
        lines.append(f"  total_m3: {cargo_total:.2f}")
        lines.append(f"  util_pct: {cargo_util_pct:.2f}%")
        picks = leg.get("picks", [])
        lines.append("Top 10 Picks by Profit:")
        for p in sorted(picks, key=lambda x: x.get("profit", 0.0), reverse=True)[:10]:
            pick_qty = int(p.get("qty", 0))
            pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(pick_qty)
            lines.append(
                f"  {p.get('name', '')} | qty={pick_qty} | m3={pick_m3:.2f} | "
                f"profit={fmt_isk(p.get('profit', 0.0))} | strict_conf={float(p.get('strict_confidence_score', 0.0)):.3f}"
                f" | buy_at={str(p.get('buy_at', ''))} | sell_at={str(p.get('sell_at', ''))} | hops={int(p.get('route_hops', 1))}"
            )
        lines.append("Top 10 Picks by profit_per_m3_per_day:")
        for p in sorted(picks, key=lambda x: x.get("profit_per_m3_per_day", 0.0), reverse=True)[:10]:
            pick_qty = int(p.get("qty", 0))
            pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(pick_qty)
            lines.append(
                f"  {p.get('name', '')} | qty={pick_qty} | m3={pick_m3:.2f} | "
                f"profit_per_m3_per_day={p.get('profit_per_m3_per_day', 0.0):.4f}"
            )
        lines.append("HANDELSPLAN (menschenlesbar):")
        if not picks:
            lines.append("  Keine Picks fuer dieses Leg.")
        else:
            # Keep instructions sorted by absolute profit so execution priority is obvious.
            ordered = sorted(picks, key=lambda x: x.get("profit", 0.0), reverse=True)
            for i, p in enumerate(ordered, start=1):
                lines.extend(format_trade_instruction(leg, p, i))
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_execution_plan_chain(
    path: str,
    timestamp: str,
    forward_leg_results: list[dict],
    return_leg_results: list[dict] | None = None
) -> None:
    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("EXECUTION PLAN (CHAIN)")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    lines.append("")

    total_cost = 0.0
    total_revenue = 0.0
    total_profit = 0.0
    total_fees_taxes = 0.0
    total_shipping_cost = 0.0
    total_route_costs = 0.0

    def append_section(title: str, leg_results: list[dict]) -> tuple[float, float, float, float, float]:
        section_cost = 0.0
        section_revenue = 0.0
        section_profit = 0.0
        section_fees_taxes = 0.0
        section_route_costs = 0.0
        section_leg_num = 0
        lines.append(title)
        lines.append("-" * len(title))
        lines.append("")
        for leg in leg_results:
            if bool(leg.get("leg_disabled", False)):
                continue
            picks = leg.get("picks", []) or []
            if not picks:
                continue
            section_leg_num += 1
            lines.append(f"LEG: LEG {section_leg_num}")
            lines.append(f"Route: {leg.get('route_label', '')}")
            src_info = leg.get("source_node_info", {}) if isinstance(leg.get("source_node_info", {}), dict) else {}
            dst_info = leg.get("dest_node_info", {}) if isinstance(leg.get("dest_node_info", {}), dict) else {}
            if src_info:
                if str(src_info.get("node_kind", "")) == "location":
                    lines.append(
                        f"Source: {src_info.get('node_label', leg.get('source_label', ''))} "
                        f"(location_id {int(src_info.get('location_id', src_info.get('node_id', 0)) or 0)}, "
                        f"region {int(src_info.get('node_region_id', 0) or 0)})"
                    )
                else:
                    lines.append(
                        f"Source: {src_info.get('node_label', leg.get('source_label', ''))} "
                        f"(structure_id {int(src_info.get('structure_id', src_info.get('node_id', 0)) or 0)})"
                    )
            if dst_info:
                if str(dst_info.get("node_kind", "")) == "location":
                    lines.append(
                        f"Dest: {dst_info.get('node_label', leg.get('dest_label', ''))} "
                        f"(location_id {int(dst_info.get('location_id', dst_info.get('node_id', 0)) or 0)}, "
                        f"region {int(dst_info.get('node_region_id', 0) or 0)})"
                    )
                else:
                    lines.append(
                        f"Dest: {dst_info.get('node_label', leg.get('dest_label', ''))} "
                        f"(structure_id {int(dst_info.get('structure_id', dst_info.get('node_id', 0)) or 0)})"
                    )
            shipping_lane_id = str(leg.get("shipping_lane_id", "") or "")
            if shipping_lane_id:
                lines.append(f"Shipping Lane: {shipping_lane_id}")
                pricing_model = str(leg.get("shipping_pricing_model", "") or "")
                if pricing_model:
                    lines.append(f"pricing_model: {pricing_model}")
                contracts_used = int(leg.get("shipping_contracts_used", 0) or 0)
                if contracts_used > 0:
                    lines.append(f"contracts_used: {contracts_used}")
                split_reason = str(leg.get("shipping_split_reason", "") or "")
                if split_reason:
                    lines.append(f"split_reason: {split_reason}")
                est_collateral = float(leg.get("estimated_collateral_isk", 0.0) or 0.0)
                if est_collateral > 0.0:
                    lines.append(f"estimated_collateral_isk: {fmt_isk_de(est_collateral)}")
            leg_cargo_total = float(leg.get("cargo_total", 0.0))
            leg_cargo_used = float(leg.get("m3_used", 0.0))
            leg_cargo_free = max(0.0, leg_cargo_total - leg_cargo_used)
            leg_cargo_util = (leg_cargo_used / leg_cargo_total * 100.0) if leg_cargo_total > 0 else 0.0
            lines.append(
                f"Cargo: used {leg_cargo_used:.2f} m3 | free {leg_cargo_free:.2f} m3 | "
                f"total {leg_cargo_total:.2f} m3 | util {leg_cargo_util:.2f}%"
            )
            lines.append("")
            ordered = sorted(picks, key=lambda x: float(x.get("profit", 0.0)), reverse=True)
            for idx, p in enumerate(ordered, start=1):
                qty = int(p.get("qty", 0))
                buy_avg = float(p.get("buy_avg", 0.0))
                buy_total = buy_avg * qty
                sell_unit = float(p.get("target_sell_price", 0.0) or p.get("sell_avg", 0.0))
                sell_total = sell_unit * qty
                duration = int(float(p.get("order_duration_days", 0) or 0))
                is_instant = bool(p.get("instant", False)) or str(p.get("mode", "")).lower() == "instant"
                exp_days = float(p.get("expected_days_to_sell", 0.0) or 0.0)
                fill_prob = float(p.get("fill_probability", 0.0) or 0.0) * 100.0
                profit = float(p.get("profit", 0.0) or 0.0)
                pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(qty)
                lines.append(f"{idx}. {p.get('name', '')} (type_id {int(p.get('type_id', 0))})")
                lines.append(
                    f"   BUY  [{p.get('buy_at') or leg.get('source_label', 'SOURCE')}] qty={qty} @ {fmt_isk_de(buy_avg)} "
                    f"(Total {fmt_isk_de(buy_total)})"
                )
                if is_instant:
                    lines.append(
                        f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SOFORTVERKAUF/Buy-Order @ {fmt_isk_de(sell_unit)} "
                        f"(Total {fmt_isk_de(sell_total)}) | SOFORT"
                    )
                else:
                    lines.append(
                        f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SELL-ORDER @ {fmt_isk_de(sell_unit)} "
                        f"(Total {fmt_isk_de(sell_total)}) | Laufzeit {duration}d"
                    )
                lines.append(f"   Erwartet: {exp_days:.1f}d bis Verkauf | Fill {fill_prob:.1f}%")
                lines.append(f"   Erwarteter Profit: {fmt_isk_de(profit)}")
                lines.append(f"   Cargo fuer diesen Pick: {pick_m3:.2f} m3")
                lines.append(f"   Route-Hops: {int(p.get('route_hops', 1))}")
                lines.append("")
            leg_cost = float(leg.get("isk_used", 0.0))
            leg_revenue = sum(float(p.get("revenue_net", 0.0)) for p in ordered)
            leg_profit = float(leg.get("profit_total", 0.0))
            leg_fees_taxes = sum(_pick_total_fees_taxes(p) for p in ordered)
            leg_route_cost = float(leg.get("total_transport_cost", 0.0))
            leg_shipping_cost = float(leg.get("total_shipping_cost", 0.0))
            section_cost += leg_cost
            section_revenue += leg_revenue
            section_profit += leg_profit
            section_fees_taxes += leg_fees_taxes
            section_route_costs += leg_route_cost
            lines.append(f"Leg Total Cost: {fmt_isk_de(leg_cost)}")
            lines.append(f"Leg Total Net Revenue: {fmt_isk_de(leg_revenue)}")
            lines.append(f"Leg Total Profit: {fmt_isk_de(leg_profit)}")
            lines.append(f"Leg Fees+Taxes: {fmt_isk_de(leg_fees_taxes)}")
            lines.append(f"Leg Route Costs: {fmt_isk_de(leg_route_cost)}")
            if leg_shipping_cost > 0.0:
                lines.append(f"Leg Shipping Cost: {fmt_isk_de(leg_shipping_cost)}")
                lines.append(f"shipping_cost_total: {fmt_isk_de(leg_shipping_cost)}")
            lines.append("")
        if section_leg_num == 0:
            lines.append("Keine aktiven Legs mit Picks.")
            lines.append("")
        return section_cost, section_revenue, section_profit, section_fees_taxes, section_route_costs

    f_cost, f_revenue, f_profit, f_fees_taxes, f_route_costs = append_section("FORWARD", forward_leg_results)
    total_cost += f_cost
    total_revenue += f_revenue
    total_profit += f_profit
    total_fees_taxes += f_fees_taxes
    total_shipping_cost += sum(float(leg.get("total_shipping_cost", 0.0)) for leg in forward_leg_results)
    total_route_costs += f_route_costs
    r_cost = 0.0
    r_profit = 0.0
    if return_leg_results is not None:
        r_cost, r_revenue, r_profit, r_fees_taxes, r_route_costs = append_section("RETURN", return_leg_results)
        total_cost += r_cost
        total_revenue += r_revenue
        total_profit += r_profit
        total_fees_taxes += r_fees_taxes
        total_shipping_cost += sum(float(leg.get("total_shipping_cost", 0.0)) for leg in return_leg_results)
        total_route_costs += r_route_costs

    lines.append("=" * 70)
    lines.append(f"TOTAL COST: {fmt_isk_de(total_cost)}")
    lines.append(f"TOTAL NET REVENUE: {fmt_isk_de(total_revenue)}")
    lines.append(f"TOTAL EXPECTED PROFIT: {fmt_isk_de(total_profit)}")
    lines.append(f"TOTAL FEES AND TAXES: {fmt_isk_de(total_fees_taxes)}")
    if total_shipping_cost > 0.0:
        lines.append(f"TOTAL SHIPPING COST: {fmt_isk_de(total_shipping_cost)}")
        lines.append(f"shipping_cost_total: {fmt_isk_de(total_shipping_cost)}")
    lines.append(f"TOTAL ROUTE COSTS: {fmt_isk_de(total_route_costs)}")
    lines.append("=" * 70)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_execution_plan_profiles(path: str, timestamp: str, route_results: list[dict]) -> None:
    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("EXECUTION PLAN (ROUTE PROFILES)")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    lines.append("")

    total_cost = 0.0
    total_revenue = 0.0
    total_profit = 0.0
    total_fees_taxes = 0.0
    total_shipping_cost = 0.0
    total_route_costs = 0.0

    for idx, leg in enumerate(route_results, start=1):
        picks = list(leg.get("picks", []) or [])
        lines.append(f"PLAN {idx}: {leg.get('route_label', '')}")
        lines.append("-" * max(8, len(lines[-1])))
        src_info = leg.get("source_node_info", {}) if isinstance(leg.get("source_node_info", {}), dict) else {}
        dst_info = leg.get("dest_node_info", {}) if isinstance(leg.get("dest_node_info", {}), dict) else {}
        if src_info:
            if str(src_info.get("node_kind", "")) == "location":
                lines.append(
                    f"Source: {src_info.get('node_label', leg.get('source_label', ''))} "
                    f"(location_id {int(src_info.get('location_id', src_info.get('node_id', 0)) or 0)}, "
                    f"region {int(src_info.get('node_region_id', 0) or 0)})"
                )
            else:
                lines.append(
                    f"Source: {src_info.get('node_label', leg.get('source_label', ''))} "
                    f"(structure_id {int(src_info.get('structure_id', src_info.get('node_id', 0)) or 0)})"
                )
        if dst_info:
            if str(dst_info.get("node_kind", "")) == "location":
                lines.append(
                    f"Dest: {dst_info.get('node_label', leg.get('dest_label', ''))} "
                    f"(location_id {int(dst_info.get('location_id', dst_info.get('node_id', 0)) or 0)}, "
                    f"region {int(dst_info.get('node_region_id', 0) or 0)})"
                )
            else:
                lines.append(
                    f"Dest: {dst_info.get('node_label', leg.get('dest_label', ''))} "
                    f"(structure_id {int(dst_info.get('structure_id', dst_info.get('node_id', 0)) or 0)})"
                )
        shipping_lane_id = str(leg.get("shipping_lane_id", "") or "")
        if shipping_lane_id:
            lines.append(f"Shipping Lane: {shipping_lane_id}")
            provider = str(leg.get("shipping_provider", "") or "")
            if provider:
                lines.append(f"provider: {provider}")
            pricing_model = str(leg.get("shipping_pricing_model", "") or "")
            if pricing_model:
                lines.append(f"pricing_model: {pricing_model}")
            contracts_used = int(leg.get("shipping_contracts_used", 0) or 0)
            if contracts_used > 0:
                lines.append(f"contracts_used: {contracts_used}")
            split_reason = str(leg.get("shipping_split_reason", "") or "")
            if split_reason:
                lines.append(f"split_reason: {split_reason}")
            est_collateral = float(leg.get("estimated_collateral_isk", 0.0) or 0.0)
            if est_collateral > 0.0:
                lines.append(f"estimated_collateral_isk: {fmt_isk_de(est_collateral)}")
            lane_params = leg.get("shipping_lane_params", {})
            if isinstance(lane_params, dict) and lane_params:
                for key in (
                    "per_m3_rate",
                    "minimum_reward",
                    "full_load_reward",
                    "collateral_rate",
                    "additional_collateral_rate",
                    "max_volume_per_contract_m3",
                    "max_collateral_per_contract_isk",
                    "max_value",
                    "collateral_basis",
                ):
                    if key in lane_params:
                        lines.append(f"{key}: {lane_params.get(key)}")
        leg_cost = float(leg.get("isk_used", 0.0))
        leg_revenue = sum(float(p.get("revenue_net", 0.0)) for p in picks)
        leg_profit = float(leg.get("profit_total", 0.0))
        leg_fees_taxes = sum(_pick_total_fees_taxes(p) for p in picks)
        leg_route_costs = float(leg.get("total_transport_cost", 0.0))
        leg_shipping_costs = float(leg.get("total_shipping_cost", 0.0))
        total_cost += leg_cost
        total_revenue += leg_revenue
        total_profit += leg_profit
        total_fees_taxes += leg_fees_taxes
        total_shipping_cost += leg_shipping_costs
        total_route_costs += leg_route_costs
        lines.append(f"Total Cost: {fmt_isk_de(leg_cost)}")
        lines.append(f"Total Net Revenue: {fmt_isk_de(leg_revenue)}")
        lines.append(f"Total Expected Net Profit: {fmt_isk_de(leg_profit)}")
        lines.append(f"Total Fees and Taxes: {fmt_isk_de(leg_fees_taxes)}")
        lines.append(f"Total Route Costs: {fmt_isk_de(leg_route_costs)}")
        lines.append(f"total_route_m3: {float(leg.get('total_route_m3', leg.get('m3_used', 0.0)) or 0.0):.2f} m3")
        if leg_shipping_costs > 0.0:
            lines.append(f"Shipping Cost Total: {fmt_isk_de(leg_shipping_costs)}")
            lines.append(f"shipping_cost_total: {fmt_isk_de(leg_shipping_costs)}")
        budget_total = float(leg.get("budget_total", 0.0))
        budget_used = float(leg.get("isk_used", 0.0))
        budget_left = max(0.0, budget_total - budget_used)
        if budget_total > 0 and (budget_left / budget_total) >= 0.05:
            lines.append(
                "Budget Rest: "
                f"{fmt_isk_de(budget_left)}. Grund: Keine weiteren Picks erfuellen Profit-Floors nach Gebuehren und Routenkosten."
            )
        lines.append("")
        ordered = sorted(picks, key=lambda x: float(x.get("profit", 0.0)), reverse=True)
        for p_i, p in enumerate(ordered, start=1):
            qty = int(p.get("qty", 0))
            buy_avg = float(p.get("buy_avg", 0.0))
            buy_total = buy_avg * qty
            sell_unit = float(p.get("target_sell_price", 0.0) or p.get("sell_avg", 0.0))
            sell_total = sell_unit * qty
            duration = int(float(p.get("order_duration_days", 0) or 0))
            is_instant = bool(p.get("instant", False)) or str(p.get("mode", "")).lower() == "instant"
            exp_days = float(p.get("expected_days_to_sell", 0.0) or 0.0)
            fill_prob = float(p.get("fill_probability", 0.0) or 0.0) * 100.0
            profit = float(p.get("profit", 0.0) or 0.0)
            pick_m3 = float(p.get("unit_volume", 0.0) or 0.0) * float(qty)
            unit_m3 = float(p.get("unit_volume", 0.0) or 0.0)
            lines.append(f"{p_i}. {p.get('name', '')} (type_id {int(p.get('type_id', 0))})")
            lines.append(
                f"   BUY  [{p.get('buy_at') or leg.get('source_label', 'SOURCE')}] qty={qty} @ {fmt_isk_de(buy_avg)} "
                f"(Total {fmt_isk_de(buy_total)})"
            )
            if is_instant:
                lines.append(
                    f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SOFORTVERKAUF/Buy-Order @ {fmt_isk_de(sell_unit)} "
                    f"(Total {fmt_isk_de(sell_total)}) | SOFORT"
                )
            else:
                lines.append(
                    f"   SELL [{p.get('sell_at') or leg.get('dest_label', 'DEST')}] SELL-ORDER @ {fmt_isk_de(sell_unit)} "
                    f"(Total {fmt_isk_de(sell_total)}) | Laufzeit {duration}d"
                )
            lines.append(f"   Erwartet: {exp_days:.1f}d bis Verkauf | Fill {fill_prob:.1f}%")
            lines.append(f"   Erwarteter Net Profit: {fmt_isk_de(profit)}")
            fee_components = _pick_fee_components(p)
            lines.append(f"   Fees+Taxes: {fmt_isk_de(_pick_total_fees_taxes(p))}")
            lines.append(f"   sales_tax_isk: {fmt_isk_de(fee_components['sales_tax_isk'])}")
            lines.append(f"   broker_fee_isk: {fmt_isk_de(fee_components['broker_fee_isk'])}")
            lines.append(f"   scc_surcharge_isk: {fmt_isk_de(fee_components['scc_surcharge_isk'])}")
            lines.append(f"   relist_fee_isk: {fmt_isk_de(fee_components['relist_fee_isk'])}")
            lines.append(f"   Route/Shipping Cost: {fmt_isk_de(float(p.get('transport_cost', 0.0)))}")
            lines.append(f"   unit_volume: {unit_m3:.2f} m3 | total_m3: {pick_m3:.2f} m3")
            lines.append(f"   Cargo fuer diesen Pick: {pick_m3:.2f} m3")
            lines.append("")
        if not ordered:
            lines.append("Keine Picks fuer diese Route.")
            lines.append("")

    lines.append("=" * 70)
    lines.append(f"TOTAL COST: {fmt_isk_de(total_cost)}")
    lines.append(f"TOTAL NET REVENUE: {fmt_isk_de(total_revenue)}")
    lines.append(f"TOTAL EXPECTED NET PROFIT: {fmt_isk_de(total_profit)}")
    lines.append(f"TOTAL FEES AND TAXES: {fmt_isk_de(total_fees_taxes)}")
    if total_shipping_cost > 0.0:
        lines.append(f"TOTAL SHIPPING COST: {fmt_isk_de(total_shipping_cost)}")
        lines.append(f"shipping_cost_total: {fmt_isk_de(total_shipping_cost)}")
    lines.append(f"TOTAL ROUTE COSTS: {fmt_isk_de(total_route_costs)}")
    lines.append("=" * 70)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def build_adjacent_pairs(chain_nodes: list[dict], reverse: bool = False) -> list[tuple[dict, dict]]:
    nodes = list(chain_nodes)
    if reverse:
        nodes = list(reversed(nodes))
    return [(nodes[i], nodes[i + 1]) for i in range(max(0, len(nodes) - 1))]


def build_route_wide_pairs(
    chain_nodes: list[dict],
    reverse: bool = False,
    max_hops: int = 99
) -> list[dict]:
    nodes = list(chain_nodes)
    if reverse:
        nodes = list(reversed(nodes))
    out: list[dict] = []
    n = len(nodes)
    hop_cap = max(1, int(max_hops))
    for src_idx in range(n - 1):
        src = nodes[src_idx]
        for dst_idx in range(src_idx + 1, n):
            dst = nodes[dst_idx]
            hop_count = int(dst_idx - src_idx)
            if hop_count > hop_cap:
                break
            out.append({
                "src_idx": int(src_idx),
                "dst_idx": int(dst_idx),
                "src_id": int(src["id"]),
                "dst_id": int(dst["id"]),
                "src_label": str(src["label"]),
                "dst_label": str(dst["label"]),
                "hop_count": int(hop_count),
            })
    return out


def _resolve_route_profiles_cfg(cfg: dict) -> dict:
    raw = cfg.get("route_profiles", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "include_forward_pairs": bool(raw.get("include_forward_pairs", True)),
        "include_reverse_pairs": bool(raw.get("include_reverse_pairs", True)),
        "max_hops": int(raw.get("max_hops", 99)),
        "routes": list(raw.get("routes", [])) if isinstance(raw.get("routes", []), list) else [],
    }


def build_route_profiles(chain_nodes: list[dict], cfg: dict) -> list[dict]:
    rp_cfg = _resolve_route_profiles_cfg(cfg)
    if not bool(rp_cfg.get("enabled", True)):
        return []
    explicit = rp_cfg.get("routes", [])
    profiles: list[dict] = []
    if explicit:
        for i, route in enumerate(explicit, start=1):
            if not isinstance(route, dict):
                continue
            src_raw = str(route.get("from", "")).strip()
            dst_raw = str(route.get("to", "")).strip()
            if not src_raw or not dst_raw:
                continue
            profiles.append({
                "id": str(route.get("id", f"profile_{i}")),
                "from": src_raw,
                "to": dst_raw,
                "mode": str(route.get("mode", "") or ""),
                "shipping_lane_id": str(route.get("shipping_lane_id", route.get("shipping_lane", "")) or ""),
            })
        return profiles

    nodes = list(chain_nodes or [])
    if len(nodes) < 2:
        return profiles
    max_hops = max(1, int(rp_cfg.get("max_hops", 99)))
    include_fwd = bool(rp_cfg.get("include_forward_pairs", True))
    include_rev = bool(rp_cfg.get("include_reverse_pairs", True))
    for i in range(len(nodes) - 1):
        src = nodes[i]
        for j in range(i + 1, len(nodes)):
            hop_count = int(j - i)
            if hop_count > max_hops:
                break
            dst = nodes[j]
            if include_fwd:
                profiles.append({
                    "id": f"{label_to_slug(str(src['label']))}_to_{label_to_slug(str(dst['label']))}",
                    "from": str(src["label"]),
                    "to": str(dst["label"]),
                    "mode": "",
                    "shipping_lane_id": "",
                })
            if include_rev:
                profiles.append({
                    "id": f"{label_to_slug(str(dst['label']))}_to_{label_to_slug(str(src['label']))}",
                    "from": str(dst["label"]),
                    "to": str(src["label"]),
                    "mode": "",
                    "shipping_lane_id": "",
                })
    # De-duplicate while keeping order.
    seen = set()
    out: list[dict] = []
    for p in profiles:
        key = (normalize_location_label(p.get("from", "")), normalize_location_label(p.get("to", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _resolve_route_search_cfg(cfg: dict) -> dict:
    raw = cfg.get("route_search", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "max_routes": max(1, int(raw.get("max_routes", 10) or 10)),
        "ranking_metric": str(raw.get("ranking_metric", "profit_total") or "profit_total").strip().lower(),
        "allow_all_structures_internal": bool(raw.get("allow_all_structures_internal", True)),
        "allow_shipping_lanes": bool(raw.get("allow_shipping_lanes", True)),
        "allowed_pairs": list(raw.get("allowed_pairs", [])) if isinstance(raw.get("allowed_pairs", []), list) else [],
    }


def _parse_route_pair_token(token: str) -> tuple[str, str] | None:
    txt = str(token or "").strip()
    if not txt:
        return None
    sep = "->" if "->" in txt else (":" if ":" in txt else None)
    if sep is None:
        return None
    parts = [p.strip() for p in txt.split(sep, 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return normalize_location_label(parts[0]), normalize_location_label(parts[1])


def _resolve_allowed_route_pairs(cfg: dict) -> set[tuple[str, str]]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    raw_pairs = rs_cfg.get("allowed_pairs", [])
    out: set[tuple[str, str]] = set()
    for raw in raw_pairs:
        if isinstance(raw, str):
            parsed = _parse_route_pair_token(raw)
            if parsed is not None:
                out.add(parsed)
            continue
        if isinstance(raw, dict):
            src = normalize_location_label(str(raw.get("from", "")))
            dst = normalize_location_label(str(raw.get("to", "")))
            if src and dst:
                out.add((src, dst))
    return out


def _resolve_allowed_route_pair_lane_overrides(cfg: dict) -> dict[tuple[str, str], str]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    raw_pairs = rs_cfg.get("allowed_pairs", [])
    out: dict[tuple[str, str], str] = {}
    for raw in raw_pairs:
        if not isinstance(raw, dict):
            continue
        src = normalize_location_label(str(raw.get("from", "")))
        dst = normalize_location_label(str(raw.get("to", "")))
        lane_id = str(raw.get("shipping_lane_id", raw.get("shipping_lane", "")) or "").strip()
        if src and dst and lane_id:
            out[(src, dst)] = lane_id
    return out


def build_route_search_profiles(node_catalog: dict[str, dict], cfg: dict) -> list[dict]:
    rs_cfg = _resolve_route_search_cfg(cfg)
    if not bool(rs_cfg.get("enabled", False)):
        return []
    nodes: list[dict] = []
    for _, n in sorted(node_catalog.items(), key=lambda kv: kv[0]):
        if not isinstance(n, dict):
            continue
        if int(n.get("id", 0) or 0) <= 0:
            continue
        if not str(n.get("label", "")).strip():
            continue
        nodes.append(dict(n))
    allowed_explicit = _resolve_allowed_route_pairs(cfg)
    allowed_lane_overrides = _resolve_allowed_route_pair_lane_overrides(cfg)
    allow_struct_internal = bool(rs_cfg.get("allow_all_structures_internal", True))
    allow_shipping = bool(rs_cfg.get("allow_shipping_lanes", True))

    pairs: list[tuple[dict, dict, str]] = []
    seen: set[tuple[str, str]] = set()
    for src in nodes:
        for dst in nodes:
            src_norm = normalize_location_label(str(src.get("label", "")))
            dst_norm = normalize_location_label(str(dst.get("label", "")))
            if not src_norm or not dst_norm or src_norm == dst_norm:
                continue
            if int(src.get("id", 0) or 0) == int(dst.get("id", 0) or 0):
                continue
            pair_key = (src_norm, dst_norm)
            if pair_key in seen:
                continue
            allowed = False
            selected_lane_id = str(allowed_lane_overrides.get(pair_key, "") or "")
            lane_match = resolve_shipping_lane_cfg(
                cfg,
                str(src.get("label", "")),
                str(dst.get("label", "")),
                source_id=int(src.get("id", 0) or 0),
                dest_id=int(dst.get("id", 0) or 0),
                preferred_lane_id=selected_lane_id,
            )
            if allow_struct_internal and str(src.get("kind", "structure")) == "structure" and str(dst.get("kind", "structure")) == "structure":
                allowed = True
            if allow_shipping and _policy_provider_for_route(str(src.get("label", "")), str(dst.get("label", ""))) and lane_match is not None:
                allowed = True
            if pair_key in allowed_explicit:
                allowed = True
            if not allowed:
                continue
            seen.add(pair_key)
            pairs.append((src, dst, str(lane_match[0]) if lane_match is not None else selected_lane_id))

    out: list[dict] = []
    for idx, (src, dst, lane_id) in enumerate(pairs, start=1):
        out.append({
            "id": f"search_{label_to_slug(str(src.get('label', '')))}_to_{label_to_slug(str(dst.get('label', '')))}_{idx}",
            "from": str(src.get("label", "")),
            "to": str(dst.get("label", "")),
            "mode": "",
            "shipping_lane_id": str(lane_id or ""),
            "search_generated": True,
        })
    return out


def _route_ranking_value(route: dict, metric: str) -> float:
    m = str(metric or "profit_total").strip().lower()
    profit = float(route.get("profit_total", 0.0) or 0.0)
    isk_used = float(route.get("isk_used", 0.0) or 0.0)
    m3_used = float(route.get("m3_used", 0.0) or 0.0)
    if m in ("profit_per_m3", "isk_per_m3"):
        return profit / max(1e-9, m3_used)
    if m in ("profit_pct", "profit_per_isk"):
        return profit / max(1e-9, isk_used)
    return profit


def _profit_dominance(route: dict) -> tuple[float, float, bool]:
    picks = list(route.get("picks", []) or [])
    profits = sorted([max(0.0, float(p.get("profit", 0.0) or 0.0)) for p in picks], reverse=True)
    total_profit = max(0.0, float(route.get("profit_total", 0.0) or 0.0))
    if total_profit <= 0.0 or not profits:
        return 0.0, 0.0, False
    top3 = sum(profits[:3]) / total_profit
    top5 = sum(profits[:5]) / total_profit
    dominant = top3 > 0.60 or top5 > 0.60
    return top3, top5, dominant


def write_route_leaderboard(
    path: str,
    timestamp: str,
    route_results: list[dict],
    ranking_metric: str,
    max_routes: int
) -> None:
    metric = str(ranking_metric or "profit_total").strip().lower()
    ranked = sorted(
        list(route_results or []),
        key=lambda r: (_route_ranking_value(r, metric), float(r.get("profit_total", 0.0))),
        reverse=True
    )[: max(1, int(max_routes or 10))]

    def fmt_isk_de(x: float) -> str:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} ISK"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("ROUTE LEADERBOARD")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {timestamp}")
    lines.append(f"ranking_metric: {metric}")
    lines.append(f"routes_considered: {len(list(route_results or []))}")
    lines.append(f"top_n: {len(ranked)}")
    lines.append("")
    if not ranked:
        lines.append("Keine Routen mit Picks gefunden.")
    for idx, r in enumerate(ranked, start=1):
        profit = float(r.get("profit_total", 0.0) or 0.0)
        isk_used = float(r.get("isk_used", 0.0) or 0.0)
        m3_used = float(r.get("m3_used", 0.0) or 0.0)
        top3_ratio, top5_ratio, dominant = _profit_dominance(r)
        lines.append(f"{idx}. Route {r.get('route_label', '')}")
        lines.append(f"   Start: {r.get('source_label', '')}")
        lines.append(f"   Ziel: {r.get('dest_label', '')}")
        lines.append(f"   provider: {str(r.get('shipping_provider', '') or '')}")
        lines.append(f"   Total Cost: {fmt_isk_de(isk_used)}")
        lines.append(f"   Total Net Revenue: {fmt_isk_de(float(r.get('net_revenue_total', 0.0) or 0.0))}")
        lines.append(f"   Total Expected Net Profit: {fmt_isk_de(profit)}")
        lines.append(f"   Total Fees and Taxes: {fmt_isk_de(float(r.get('total_fees_taxes', 0.0) or 0.0))}")
        lines.append(f"   Total Route Costs: {fmt_isk_de(float(r.get('total_route_cost', 0.0) or 0.0))}")
        lines.append(f"   Total Shipping Cost: {fmt_isk_de(float(r.get('shipping_cost_total', 0.0) or 0.0))}")
        lines.append(f"   Profit per m3: {profit / max(1e-9, m3_used):.2f} ISK/m3")
        lines.append(f"   Profit per ISK: {profit / max(1e-9, isk_used):.6f}")
        lines.append(f"   Gesamt m3: {m3_used:.2f}")
        lines.append(f"   Picks Count: {int(r.get('items_count', 0) or 0)}")
        lines.append(f"   Budget Usage: {float(r.get('budget_util_pct', 0.0) or 0.0):.2f}%")
        lines.append(f"   Cargo Usage: {float(r.get('cargo_util_pct', 0.0) or 0.0):.2f}%")
        lines.append(f"   Top3 Profit Share: {top3_ratio*100.0:.2f}%")
        lines.append(f"   Top5 Profit Share: {top5_ratio*100.0:.2f}%")
        lines.append(f"   Dominance Flag (>60%): {'YES' if dominant else 'NO'}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def enforce_route_destination(picks: list[dict], expected_dest_label: str) -> list[dict]:
    expected = normalize_location_label(expected_dest_label)
    out: list[dict] = []
    for p in list(picks or []):
        sell_at_raw = str(p.get("sell_at", "") or "").strip()
        # For regular route-profile picks sell_at may be omitted; keep those.
        if not sell_at_raw:
            out.append(p)
            continue
        if normalize_location_label(sell_at_raw) == expected:
            out.append(p)
    return out


def _resolve_route_wide_scan_cfg(cfg: dict) -> dict:
    rw = cfg.get("route_wide_scan", {})
    if not isinstance(rw, dict):
        rw = {}
    return {
        "enabled": bool(rw.get("enabled", False)),
        "max_hops_forward": int(rw.get("max_hops_forward", 99)),
        "max_hops_return": int(rw.get("max_hops_return", 99)),
        "prefer_nearer_exit_if_profit_close_pct": float(rw.get("prefer_nearer_exit_if_profit_close_pct", 0.10)),
        "cargo_penalty_per_extra_leg": float(rw.get("cargo_penalty_per_extra_leg", 0.05)),
        "capital_lock_penalty_per_extra_leg": float(rw.get("capital_lock_penalty_per_extra_leg", 0.07)),
        "allow_mixed_destinations_within_leg": bool(rw.get("allow_mixed_destinations_within_leg", True)),
        "score_weight_density": float(rw.get("score_weight_density", 0.36)),
        "score_weight_margin": float(rw.get("score_weight_margin", 0.27)),
        "score_weight_absolute": float(rw.get("score_weight_absolute", 0.17)),
        "score_weight_liquidity": float(rw.get("score_weight_liquidity", 0.12)),
        "score_weight_plausibility": float(rw.get("score_weight_plausibility", 0.08)),
    }


def make_skipped_chain_leg(
    src_label: str,
    dst_label: str,
    reason: str,
    mode: str,
    filters_used: dict,
    budget_isk: float,
    cargo_m3: float
) -> dict:
    return {
        "route_label": f"{src_label} -> {dst_label}",
        "leg_disabled": True,
        "leg_disabled_reason": reason,
        "mode": mode,
        "selected_mode": "skipped",
        "filters_used": filters_used,
        "total_candidates": 0,
        "passed_all_filters": 0,
        "why_out_summary": {},
        "items_count": 0,
        "m3_used": 0.0,
        "cargo_total": cargo_m3,
        "cargo_util_pct": 0.0,
        "isk_used": 0.0,
        "budget_total": budget_isk,
        "budget_util_pct": 0.0,
        "profit_total": 0.0,
        "picks": []
    }


def _normalize_route_mode(route_mode_raw: str) -> str:
    route_mode = str(route_mode_raw or "roundtrip").lower()
    if route_mode not in ("roundtrip", "forward_only"):
        return "roundtrip"
    return route_mode


def _resolve_chain_runtime(cfg: dict, o4t_id: int, cj6_id: int) -> dict:
    chain_cfg = cfg.get("route_chain", {})
    chain_enabled = bool(chain_cfg.get("enabled", False))
    chain_nodes: list[dict] = []

    legs_cfg = chain_cfg.get("legs", [])
    if isinstance(legs_cfg, list) and legs_cfg:
        seen_chain_ids: set[int] = set()
        invalid_reason = ""
        for idx, n in enumerate(legs_cfg):
            if not isinstance(n, dict):
                invalid_reason = f"route_chain.legs[{idx}] ist kein Objekt"
                break
            sid_raw = n.get("id", 0)
            label_raw = n.get("label", f"SID_{sid_raw}")
            region_raw = n.get("region_id", 0)
            try:
                sid = int(sid_raw)
            except Exception:
                sid = 0
            try:
                rid = int(region_raw or 0)
            except Exception:
                rid = 0
            label = str(label_raw).strip()
            if sid <= 0:
                invalid_reason = f"route_chain.legs[{idx}].id ist ungueltig"
                break
            if sid in seen_chain_ids:
                invalid_reason = f"route_chain.legs[{idx}].id ist doppelt ({sid})"
                break
            if not label:
                invalid_reason = f"route_chain.legs[{idx}].label fehlt"
                break
            seen_chain_ids.add(sid)
            node = {"id": sid, "label": label}
            if rid > 0:
                node["region_id"] = rid
            chain_nodes.append(node)
        if invalid_reason:
            print(f"WARN: {invalid_reason}. Fallback auf non-chain.")
            chain_enabled = False
            chain_nodes = []
        elif len(chain_nodes) < 2:
            print("WARN: route_chain.legs braucht mindestens 2 Stationen. Fallback auf non-chain.")
            chain_enabled = False
            chain_nodes = []
    elif chain_enabled:
        # Legacy chain config: one middle node between O4T and CJ6.
        middle_id = int(chain_cfg.get("middle_structure_id", 0) or 0)
        middle_label = str(chain_cfg.get("middle_label", "R-ARKN"))
        if middle_id > 0:
            chain_nodes = [
                {"id": int(o4t_id), "label": "O4T"},
                {"id": int(middle_id), "label": middle_label},
                {"id": int(cj6_id), "label": "CJ6"},
            ]
        else:
            print("WARN: route_chain.enabled=true aber weder legs noch middle_structure_id gueltig. Fallback auf non-chain.")
            chain_enabled = False
            chain_nodes = []

    fallback_to_non_chain_on_middle_failure = bool(chain_cfg.get("fallback_to_non_chain_on_middle_failure", False))
    fallback_to_non_chain_on_invalid_route = bool(chain_cfg.get("fallback_to_non_chain_on_invalid_route", False))
    chain_leg_budget_util_min_pct = float(cfg.get("chain_leg_budget_util_min_pct", chain_cfg.get("chain_leg_budget_util_min_pct", 0.5)))
    chain_return_mode = str(cfg.get("chain_return_mode", chain_cfg.get("chain_return_mode", "off"))).lower()
    if chain_return_mode not in ("off", "instant", "fast_sell"):
        chain_return_mode = "off"
    chain_return_overrides = cfg.get("filters_chain_return", {})
    if not isinstance(chain_return_overrides, dict):
        chain_return_overrides = {}

    if chain_enabled and len(chain_nodes) < 2:
        if fallback_to_non_chain_on_invalid_route:
            print("WARN: Chain-Route ungueltig. Fallback auf non-chain.")
        else:
            print("WARN: Chain-Route ungueltig. Fallback auf non-chain.")
        chain_enabled = False

    return {
        "chain_enabled": chain_enabled,
        "chain_nodes": chain_nodes,
        "fallback_to_non_chain_on_middle_failure": fallback_to_non_chain_on_middle_failure,
        "fallback_to_non_chain_on_invalid_route": fallback_to_non_chain_on_invalid_route,
        "chain_leg_budget_util_min_pct": chain_leg_budget_util_min_pct,
        "chain_return_mode": chain_return_mode,
        "chain_return_overrides": chain_return_overrides,
    }


def _build_structure_context(o4t_id: int, cj6_id: int, chain_enabled: bool, chain_nodes: list[dict]) -> tuple[dict[int, str], set[int]]:
    structure_labels: dict[int, str] = {
        int(o4t_id): "O4T",
        int(cj6_id): "CJ6",
    }
    if chain_enabled:
        for n in chain_nodes:
            structure_labels[int(n["id"])] = str(n["label"])

    required_structure_ids: set[int] = {int(o4t_id), int(cj6_id)}
    if chain_enabled:
        required_structure_ids = {int(n["id"]) for n in chain_nodes}
    return structure_labels, required_structure_ids


def _resolve_location_nodes(cfg: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    # Built-in fallback for jita_44 (can be overridden by config.locations).
    out["jita_44"] = {
        "label": "jita_44",
        "id": 60003760,
        "kind": "location",
        "location_id": 60003760,
        "region_id": 10000002,
    }
    loc_cfg = cfg.get("locations", {})
    if not isinstance(loc_cfg, dict):
        return out
    for label_raw, raw in loc_cfg.items():
        label = str(label_raw).strip()
        if not label:
            continue
        rid = 0
        lid = 0
        if isinstance(raw, dict):
            try:
                lid = int(raw.get("location_id", 0) or 0)
            except Exception:
                lid = 0
            try:
                rid = int(raw.get("region_id", 0) or 0)
            except Exception:
                rid = 0
        else:
            try:
                lid = int(raw)
            except Exception:
                lid = 0
        if lid <= 0:
            continue
        out[str(label)] = {
            "label": str(label),
            "id": int(lid),
            "kind": "location",
            "location_id": int(lid),
            "region_id": int(rid),
        }
    return out


def _resolve_node_catalog(cfg: dict, chain_nodes: list[dict]) -> dict[str, dict]:
    by_label: dict[str, dict] = {}
    structures_cfg = cfg.get("structures", {})
    if isinstance(structures_cfg, dict):
        for label_raw, raw in structures_cfg.items():
            label = str(label_raw).strip()
            if not label:
                continue
            sid = 0
            rid = 0
            if isinstance(raw, dict):
                try:
                    sid = int(raw.get("id", 0) or 0)
                except Exception:
                    sid = 0
                try:
                    rid = int(raw.get("region_id", 0) or 0)
                except Exception:
                    rid = 0
            else:
                try:
                    sid = int(raw)
                except Exception:
                    sid = 0
            if sid <= 0:
                continue
            by_label[normalize_location_label(label)] = {
                "label": label,
                "id": sid,
                "kind": "structure",
                "structure_id": sid,
                "region_id": rid,
            }
    for n in chain_nodes:
        label = str(n.get("label", "")).strip()
        if not label:
            continue
        sid = int(n.get("id", 0) or 0)
        node = {
            "label": label,
            "id": sid,
            "kind": "structure",
            "structure_id": sid,
            "region_id": int(n.get("region_id", 0) or 0),
        }
        by_label[normalize_location_label(label)] = node
    for label, raw in _resolve_location_nodes(cfg).items():
        by_label[normalize_location_label(label)] = dict(raw)
    return by_label


def _node_source_dest_info(node: dict | None) -> dict:
    if not isinstance(node, dict):
        return {}
    kind = str(node.get("kind", "structure"))
    info = {
        "node_label": str(node.get("label", "")),
        "node_kind": kind,
        "node_id": int(node.get("id", 0) or 0),
        "node_region_id": int(node.get("region_id", 0) or 0),
    }
    if kind == "location":
        info["location_id"] = int(node.get("location_id", node.get("id", 0)) or 0)
    else:
        info["structure_id"] = int(node.get("structure_id", node.get("id", 0)) or 0)
    return info


def _resolve_primary_structure_ids(cfg: dict) -> tuple[int, int]:
    structures = cfg.get("structures", {})
    if not isinstance(structures, dict):
        die("config.structures fehlt oder ist ungueltig.")

    def _read_sid(v, key_name: str) -> int:
        if isinstance(v, dict):
            raw = v.get("id", 0)
        else:
            raw = v
        try:
            sid = int(raw)
        except Exception:
            sid = 0
        if sid <= 0:
            die(f"config.structures.{key_name} ist ungueltig.")
        return sid

    if "o4t" not in structures or "cj6" not in structures:
        die("config.structures muss mindestens o4t und cj6 enthalten.")

    return _read_sid(structures["o4t"], "o4t"), _read_sid(structures["cj6"], "cj6")



def _legacy_main():
    ensure_dirs()
    cli = parse_cli_args(sys.argv[1:])
    cfg = _mod_load_config(CONFIG_PATH)

    if not cfg:
        die("config.json fehlt oder ist unlesbar.")
    validation_result = _mod_validate_config(cfg)
    _mod_fail_on_invalid_config(validation_result)

    replay_cfg = cfg.get("replay", {})
    replay_enabled = bool(replay_cfg.get("enabled", False))

    o4t_id, cj6_id = _resolve_primary_structure_ids(cfg)
    route_mode = _normalize_route_mode(cfg.get("route_mode", "roundtrip"))
    chain_runtime = _resolve_chain_runtime(cfg, o4t_id, cj6_id)
    chain_enabled = bool(chain_runtime["chain_enabled"])
    chain_nodes = list(chain_runtime["chain_nodes"])
    fallback_to_non_chain_on_middle_failure = bool(chain_runtime["fallback_to_non_chain_on_middle_failure"])
    chain_leg_budget_util_min_pct = float(chain_runtime["chain_leg_budget_util_min_pct"])
    chain_return_mode = str(chain_runtime["chain_return_mode"])
    chain_return_overrides = dict(chain_runtime["chain_return_overrides"])

    if cli.get("snapshot_only"):
        snap_structs = cli.get("structures")
        if snap_structs is None:
            snap_structs = [int(o4t_id), int(cj6_id)]
            if chain_enabled:
                snap_structs = [int(n["id"]) for n in chain_nodes]
        run_snapshot_only(cfg, snap_structs, snapshot_out=cli.get("snapshot_out"))
        return

    if not replay_enabled and not _has_live_esi_credentials(cfg):
        die("Fehlende ESI-Credentials. Setze ESI_CLIENT_ID/ESI_CLIENT_SECRET oder nutze config.local.json.")

    defaults = cfg["defaults"]
    cargo_default = str(defaults["cargo_m3"])
    budget_default = fmt_isk(defaults["budget_isk"])

    cargo_cli = cli.get("cargo_m3", None)
    budget_cli = cli.get("budget_isk", None)
    if cargo_cli is None:
        cargo_s = input_with_default("Gib freien Cargo in m3 ein", cargo_default)
        try:
            cargo_m3 = float(cargo_s)
        except Exception:
            die("Eingabe ungueltig. Beispiel Cargo 10000 und Budget 500m oder 2.5b")
    else:
        cargo_m3 = float(cargo_cli)

    if budget_cli is None:
        budget_s = input_with_default("Gib Trading Budget in ISK ein", budget_default)
        try:
            budget_isk = parse_isk(budget_s)
        except Exception:
            die("Eingabe ungueltig. Beispiel Cargo 10000 und Budget 500m oder 2.5b")
    else:
        budget_isk = int(budget_cli)

    if cargo_m3 <= 0 or budget_isk <= 0:
        die("Cargo und Budget muessen positiv sein.")

    structure_labels, required_structure_ids = _build_structure_context(o4t_id, cj6_id, chain_enabled, chain_nodes)
    node_catalog = _resolve_node_catalog(cfg, chain_nodes)
    route_search_cfg = _resolve_route_search_cfg(cfg)
    route_profiles_cfg = _resolve_route_profiles_cfg(cfg)
    if bool(route_search_cfg.get("enabled", False)):
        route_profiles = build_route_search_profiles(node_catalog, cfg)
    else:
        route_profiles = build_route_profiles(chain_nodes, cfg) if bool(route_profiles_cfg.get("enabled", True)) else []

    default_replay_path = os.path.join(os.path.dirname(__file__), "replay_snapshot.json")
    replay_snapshot = None
    structure_orders_by_id: dict[int, list[dict]] = {}
    replay_structs: dict | None = None
    if replay_enabled:
        replay_path = str(replay_cfg.get("snapshot_path", default_replay_path))
        replay_raw = load_json(replay_path, None)
        if not isinstance(replay_raw, dict):
            die(f"Replay aktiviert, aber Snapshot fehlt/ungueltig: {replay_path}")
        replay_snapshot = _mod_normalize_replay_snapshot(replay_raw, o4t_id, cj6_id)
        replay_type_cache = replay_snapshot.get("type_cache", {})
        if not isinstance(replay_type_cache, dict) or not replay_type_cache:
            replay_type_cache = load_json(TYPE_CACHE_PATH, {})
        esi = ReplayESIClient(replay_type_cache if isinstance(replay_type_cache, dict) else {})
        print(f"Replay-Mode aktiv. Nutze Snapshot: {replay_path}")
        snap_structs = replay_snapshot.get("structures", {})
        replay_structs = snap_structs if isinstance(snap_structs, dict) else {}
        if chain_enabled:
            missing_chain_nodes = []
            for n in chain_nodes:
                sid = int(n["id"])
                entry = snap_structs.get(str(sid), {})
                orders = entry.get("orders", []) if isinstance(entry, dict) else []
                if not (isinstance(orders, list) and len(orders) > 0):
                    missing_chain_nodes.append((sid, str(n["label"])))
            if missing_chain_nodes:
                missing_msg = ", ".join(f"{lbl} ({sid})" for sid, lbl in missing_chain_nodes)
                msg = f"Replay-Snapshot enthaelt keine Orders fuer Chain-Station(en): {missing_msg}"
                if fallback_to_non_chain_on_middle_failure:
                    print(f"WARN: {msg}. Fallback auf non-chain (O4T <-> CJ6).")
                    chain_enabled = False
                    chain_nodes = []
                    structure_labels, required_structure_ids = _build_structure_context(
                        o4t_id, cj6_id, chain_enabled, chain_nodes
                    )
                else:
                    die(msg)
        for sid in required_structure_ids:
            entry = snap_structs.get(str(int(sid)), {})
            orders = entry.get("orders", []) if isinstance(entry, dict) else []
            if not isinstance(orders, list):
                orders = []
            structure_orders_by_id[int(sid)] = orders
            print(f"  -> {structure_labels.get(int(sid), f'SID_{sid}')} Orders aus Snapshot: {len(orders)}")
        missing = [sid for sid in required_structure_ids if not structure_orders_by_id.get(int(sid))]
        if missing:
            missing_s = ", ".join(str(x) for x in sorted(missing))
            die(f"Replay-Snapshot enthaelt keine Orders fuer benoetigte Strukturen: {missing_s}")
    else:
        esi = ESIClient(cfg)
        print("Fuehre ESI-Preflight durch...")
        try:
            for sid in sorted(required_structure_ids):
                esi.preflight_structure_request(int(sid))
        except SystemExit:
            if chain_enabled and fallback_to_non_chain_on_middle_failure:
                print(
                    "WARN: Kein Zugriff auf mindestens eine Chain-Structure. "
                    "Fallback auf non-chain (O4T <-> CJ6)."
                )
                chain_enabled = False
                chain_nodes = []
                structure_labels, required_structure_ids = _build_structure_context(
                    o4t_id, cj6_id, chain_enabled, chain_nodes
                )
                for sid in sorted(required_structure_ids):
                    esi.preflight_structure_request(int(sid))
            else:
                raise

        print("Lade Marktorders. Das kann beim ersten Mal etwas dauern.")
        for sid in sorted(required_structure_ids):
            lbl = structure_labels.get(int(sid), f"SID_{sid}")
            print(f"  -> Lade {lbl} Structure ({sid})...")
            orders = esi.fetch_structure_orders(int(sid))
            structure_orders_by_id[int(sid)] = orders if isinstance(orders, list) else []
            print(f"    {len(structure_orders_by_id[int(sid)])} Orders geladen")

    # Ensure route-profile nodes (including location_id nodes like jita_44) are loaded.
    if route_profiles:
        used_labels = set()
        for p in route_profiles:
            used_labels.add(normalize_location_label(str(p.get("from", ""))))
            used_labels.add(normalize_location_label(str(p.get("to", ""))))
        for lbl in sorted(used_labels):
            node = node_catalog.get(lbl)
            if not isinstance(node, dict):
                continue
            nid = int(node.get("id", 0) or 0)
            if nid <= 0 or nid in structure_orders_by_id:
                continue
            orders = _mod_fetch_orders_for_node(
                esi=esi,
                node=node,
                replay_enabled=replay_enabled,
                replay_structs=replay_structs,
            )
            structure_orders_by_id[nid] = orders if isinstance(orders, list) else []
            kind = str(node.get("kind", "structure"))
            if kind == "location":
                print(
                    f"  -> Lade {node.get('label', 'location')} "
                    f"(location_id {nid}, region {int(node.get('region_id', 0) or 0)}): "
                    f"{len(structure_orders_by_id[nid])} Orders"
                )
            else:
                print(f"  -> Lade {node.get('label', 'structure')} Structure ({nid}): {len(structure_orders_by_id[nid])} Orders")

    snapshot = {
        "timestamp": int(time.time()),
        "structures": {
            str(int(sid)): {"orders_count": len(structure_orders_by_id.get(int(sid), []))}
            for sid in sorted(required_structure_ids)
        }
    }
    save_json(os.path.join(os.path.dirname(__file__), "market_snapshot.json"), snapshot)
    if not replay_enabled and bool(replay_cfg.get("write_snapshot_after_fetch", True)):
        replay_path = str(replay_cfg.get("snapshot_path", default_replay_path))
        cached_types_from_disk = load_json(TYPE_CACHE_PATH, {})
        live_type_cache = getattr(esi, "type_cache", {})
        merged_type_cache = {}
        if isinstance(cached_types_from_disk, dict):
            merged_type_cache.update(cached_types_from_disk)
        if isinstance(live_type_cache, dict):
            merged_type_cache.update(live_type_cache)
        replay_payload = _mod_make_snapshot_payload(structure_orders_by_id, merged_type_cache)
        save_json(replay_path, replay_payload)
        print(f"Replay-Snapshot geschrieben: {replay_path}")

    fees = cfg["fees"]
    port_cfg = cfg["portfolio"]
    capital_flow_cfg = _resolve_capital_flow_cfg(cfg)
    strict_mode_cfg = _mod_resolve_strict_mode_cfg(cfg)
    route_wide_scan_cfg = _resolve_route_wide_scan_cfg(cfg)
    forward_filters, return_filters, forward_mode, return_mode = _mod_prepare_trade_filters(cfg)
    structure_region_map = _mod_resolve_structure_region_map(cfg, emit_info=True)
    if structure_region_map and hasattr(esi, "type_cache") and isinstance(getattr(esi, "type_cache", None), dict):
        esi.type_cache["_structure_region_map"] = {str(int(k)): int(v) for k, v in structure_region_map.items()}
        for sid, rid in structure_region_map.items():
            esi.type_cache[f"_sid_region_{int(sid)}"] = int(rid)
    if hasattr(esi, "structure_region_map"):
        try:
            esi.structure_region_map = {int(k): int(v) for k, v in structure_region_map.items()}
        except Exception:
            pass

    print("")
    print("=== BERECHNE TRADE-KANDIDATEN ===")
    out_dir = os.path.dirname(__file__)
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    created_files = []
    route_profiles_active = False

    if route_profiles:
        route_results: list[dict] = []
        for i, profile in enumerate(route_profiles, start=1):
            src_norm = normalize_location_label(profile.get("from", ""))
            dst_norm = normalize_location_label(profile.get("to", ""))
            src_node = node_catalog.get(src_norm)
            dst_node = node_catalog.get(dst_norm)
            if not src_node or not dst_node:
                continue
            p_mode = str(profile.get("mode", "")).strip().lower()
            active_mode = p_mode if p_mode in ("instant", "fast_sell", "planned_sell", "instant_first") else forward_mode
            route_id = str(profile.get("id", f"profile_{i}"))
            result = run_route(
                esi=esi,
                source_structure_id=int(src_node["id"]),
                dest_structure_id=int(dst_node["id"]),
                route_tag=route_id,
                source_label=str(src_node["label"]),
                dest_label=str(dst_node["label"]),
                filters=forward_filters,
                portfolio_cfg=port_cfg,
                fees=fees,
                mode=active_mode,
                replay_cfg=replay_cfg,
                replay_snapshot=replay_snapshot,
                structure_orders_by_id=structure_orders_by_id,
                budget_isk=float(budget_isk),
                cargo_m3=float(cargo_m3),
                cfg=cfg,
                timestamp=timestamp,
                out_dir=out_dir,
                source_node_meta=src_node,
                dest_node_meta=dst_node,
                preferred_shipping_lane_id=str(profile.get("shipping_lane_id", "") or ""),
            )
            # Route profile constraint: one plan == one destination.
            filtered_picks = enforce_route_destination(list(result.get("picks", [])), str(dst_node.get("label", "")))
            if len(filtered_picks) != len(list(result.get("picks", []))):
                result["picks"] = filtered_picks
                isk_used = sum(float(p.get("cost", 0.0)) for p in filtered_picks)
                profit_total = sum(float(p.get("profit", 0.0)) for p in filtered_picks)
                m3_used = sum(float(p.get("unit_volume", 0.0)) * float(p.get("qty", 0)) for p in filtered_picks)
                net_revenue_total = sum(float(p.get("revenue_net", 0.0)) for p in filtered_picks)
                total_fees_taxes = sum(_pick_total_fees_taxes(p) for p in filtered_picks)
                budget_total = float(result.get("budget_total", budget_isk))
                cargo_total = float(result.get("cargo_total", cargo_m3))
                result["items_count"] = int(len(filtered_picks))
                result["isk_used"] = float(isk_used)
                result["profit_total"] = float(profit_total)
                result["m3_used"] = float(m3_used)
                result["net_revenue_total"] = float(net_revenue_total)
                result["total_fees_taxes"] = float(total_fees_taxes)
                result["budget_util_pct"] = (float(isk_used) / budget_total * 100.0) if budget_total > 0 else 0.0
                result["cargo_util_pct"] = (float(m3_used) / cargo_total * 100.0) if cargo_total > 0 else 0.0
            route_results.append(result)
            if "csv_path" in result:
                created_files.append(result["csv_path"])
            if "dump_path" in result:
                created_files.append(result["dump_path"])

        if route_results:
            route_profiles_active = True
            execution_plan_path = os.path.join(out_dir, f"execution_plan_{timestamp}.txt")
            write_execution_plan_profiles(execution_plan_path, timestamp, route_results)
            created_files.append(execution_plan_path)
            if bool(route_search_cfg.get("enabled", False)):
                leaderboard_path = os.path.join(out_dir, f"route_leaderboard_{timestamp}.txt")
                write_route_leaderboard(
                    path=leaderboard_path,
                    timestamp=timestamp,
                    route_results=route_results,
                    ranking_metric=str(route_search_cfg.get("ranking_metric", "profit_total")),
                    max_routes=int(route_search_cfg.get("max_routes", 10)),
                )
                created_files.append(leaderboard_path)

    if route_profiles_active:
        pass
    elif chain_enabled:
        forward_pairs = build_adjacent_pairs(chain_nodes, reverse=False)
        return_pairs = build_adjacent_pairs(chain_nodes, reverse=True)
        ordered_forward_nodes = list(chain_nodes)
        ordered_return_nodes = list(reversed(chain_nodes))
        forward_legs_for_summary: list[dict] = []
        emitted_legs: list[dict] = []
        capital_available = float(budget_isk)
        pending_releases_forward: dict[int, float] = {}
        pending_releases_return: dict[int, float] = {}
        route_wide_enabled = bool(route_wide_scan_cfg.get("enabled", False))

        for idx, (src_node, dst_node) in enumerate(forward_pairs, start=1):
            leg_idx0 = idx - 1
            leg_budget_isk, leg_budget_capped = _compute_chain_leg_budget(
                capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg
            )
            if route_wide_enabled:
                leg = run_route_wide_leg(
                    esi=esi,
                    route_tag=f"forward_leg{idx}",
                    source_node=src_node,
                    immediate_dest_node=dst_node,
                    source_index=leg_idx0,
                    chain_nodes_ordered=ordered_forward_nodes,
                    max_hops=int(route_wide_scan_cfg.get("max_hops_forward", 99)),
                    scan_cfg=route_wide_scan_cfg,
                    structure_orders_by_id=structure_orders_by_id,
                    filters=forward_filters,
                    portfolio_cfg=port_cfg,
                    fees=fees,
                    mode=forward_mode,
                    budget_isk=leg_budget_isk,
                    cargo_m3=cargo_m3,
                    cfg=cfg,
                    timestamp=timestamp,
                    out_dir=out_dir
                )
            else:
                leg = run_route(
                    esi, int(src_node["id"]), int(dst_node["id"]), f"forward_leg{idx}",
                    str(src_node["label"]), str(dst_node["label"]),
                    forward_filters, port_cfg, fees, forward_mode,
                    replay_cfg, replay_snapshot, structure_orders_by_id,
                    leg_budget_isk, cargo_m3, cfg, timestamp, out_dir
                )
            if leg_budget_capped:
                why = leg.setdefault("why_out_summary", {})
                why["strict_leg_budget_cap"] = int(why.get("strict_leg_budget_cap", 0)) + 1
            capital_available = _apply_capital_flow_to_leg(
                leg, forward_mode, capital_available, capital_flow_cfg,
                current_leg_index=leg_idx0 if route_wide_enabled else None,
                pending_releases=pending_releases_forward if route_wide_enabled else None
            )
            disabled, reason = evaluate_leg_disabled(leg, chain_leg_budget_util_min_pct)
            leg["leg_disabled"] = disabled
            leg["leg_disabled_reason"] = reason
            forward_legs_for_summary.append(leg)
            emitted_legs.append(leg)

        forward_active = any(not bool(leg.get("leg_disabled", False)) for leg in forward_legs_for_summary)
        forward_chain_summary = os.path.join(out_dir, f"forward_chain_summary_{timestamp}.txt")
        return_chain_summary = os.path.join(out_dir, f"return_chain_summary_{timestamp}.txt")
        write_chain_summary(forward_chain_summary, "Forward", timestamp, forward_legs_for_summary)

        chain_return_filters = dict(return_filters)
        chain_return_filters.update(chain_return_overrides)
        chain_return_filters["mode"] = chain_return_mode

        return_legs_for_summary: list[dict] = []
        if route_mode == "forward_only":
            print("route_mode=forward_only -> Return-Legs werden im Chain-Mode uebersprungen.")
            skip_reason = "route_mode_forward_only"
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, _ = _compute_chain_leg_budget(
                    capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg
                )
                skipped = make_skipped_chain_leg(
                        str(src_node["label"]), str(dst_node["label"]), skip_reason,
                        chain_return_mode, chain_return_filters, leg_budget_isk, cargo_m3
                    )
                capital_available = _apply_capital_flow_to_leg(
                    skipped, chain_return_mode, capital_available, capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None
                )
                return_legs_for_summary.append(skipped)
        elif chain_return_mode == "off":
            print("chain_return_mode=off -> Return-Legs werden im Chain-Mode uebersprungen.")
            skip_reason = "chain_return_mode_off"
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, _ = _compute_chain_leg_budget(
                    capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg
                )
                skipped = make_skipped_chain_leg(
                        str(src_node["label"]), str(dst_node["label"]), skip_reason,
                        chain_return_mode, chain_return_filters, leg_budget_isk, cargo_m3
                    )
                capital_available = _apply_capital_flow_to_leg(
                    skipped, chain_return_mode, capital_available, capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None
                )
                return_legs_for_summary.append(skipped)
        elif not forward_active:
            print("Keine aktive Forward-Leg -> Return-Legs werden im Chain-Mode uebersprungen.")
            skip_reason = "no_active_forward_leg"
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, _ = _compute_chain_leg_budget(
                    capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg
                )
                skipped = make_skipped_chain_leg(
                        str(src_node["label"]), str(dst_node["label"]), skip_reason,
                        chain_return_mode, chain_return_filters, leg_budget_isk, cargo_m3
                    )
                capital_available = _apply_capital_flow_to_leg(
                    skipped, chain_return_mode, capital_available, capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None
                )
                return_legs_for_summary.append(skipped)
        else:
            for idx, (src_node, dst_node) in enumerate(return_pairs, start=1):
                leg_idx0 = idx - 1
                leg_budget_isk, leg_budget_capped = _compute_chain_leg_budget(
                    capital_available, float(budget_isk), capital_flow_cfg, strict_mode_cfg
                )
                if route_wide_enabled:
                    leg = run_route_wide_leg(
                        esi=esi,
                        route_tag=f"return_leg{idx}",
                        source_node=src_node,
                        immediate_dest_node=dst_node,
                        source_index=leg_idx0,
                        chain_nodes_ordered=ordered_return_nodes,
                        max_hops=int(route_wide_scan_cfg.get("max_hops_return", 99)),
                        scan_cfg=route_wide_scan_cfg,
                        structure_orders_by_id=structure_orders_by_id,
                        filters=chain_return_filters,
                        portfolio_cfg=port_cfg,
                        fees=fees,
                        mode=chain_return_mode,
                        budget_isk=leg_budget_isk,
                        cargo_m3=cargo_m3,
                        cfg=cfg,
                        timestamp=timestamp,
                        out_dir=out_dir
                    )
                else:
                    leg = run_route(
                        esi, int(src_node["id"]), int(dst_node["id"]), f"return_leg{idx}",
                        str(src_node["label"]), str(dst_node["label"]),
                        chain_return_filters, port_cfg, fees, chain_return_mode,
                        replay_cfg, replay_snapshot, structure_orders_by_id,
                        leg_budget_isk, cargo_m3, cfg, timestamp, out_dir
                    )
                if leg_budget_capped:
                    why = leg.setdefault("why_out_summary", {})
                    why["strict_leg_budget_cap"] = int(why.get("strict_leg_budget_cap", 0)) + 1
                capital_available = _apply_capital_flow_to_leg(
                    leg, chain_return_mode, capital_available, capital_flow_cfg,
                    current_leg_index=leg_idx0 if route_wide_enabled else None,
                    pending_releases=pending_releases_return if route_wide_enabled else None
                )
                disabled, reason = evaluate_leg_disabled(leg, chain_leg_budget_util_min_pct)
                leg["leg_disabled"] = disabled
                leg["leg_disabled_reason"] = reason
                return_legs_for_summary.append(leg)
                emitted_legs.append(leg)

        write_chain_summary(return_chain_summary, "Return", timestamp, return_legs_for_summary)
        execution_plan_path = os.path.join(out_dir, f"execution_plan_{timestamp}.txt")
        write_execution_plan_chain(
            execution_plan_path,
            timestamp,
            forward_legs_for_summary,
            return_legs_for_summary
        )
        for leg in emitted_legs:
            if "csv_path" in leg:
                created_files.append(leg["csv_path"])
            if "dump_path" in leg:
                created_files.append(leg["dump_path"])
        created_files.extend([forward_chain_summary, return_chain_summary, execution_plan_path])
    else:
        capital_available = float(budget_isk)
        forward_budget_isk = capital_available if bool(capital_flow_cfg.get("enabled", False)) else float(budget_isk)
        forward_result = run_route(
            esi, o4t_id, cj6_id, "forward",
            structure_labels[o4t_id], structure_labels[cj6_id],
            forward_filters, port_cfg, fees, forward_mode,
            replay_cfg, replay_snapshot, structure_orders_by_id,
            forward_budget_isk, cargo_m3, cfg, timestamp, out_dir
        )
        capital_available = _apply_capital_flow_to_leg(forward_result, forward_mode, capital_available, capital_flow_cfg)
        if route_mode == "forward_only":
            print("route_mode=forward_only -> Return-Route wird uebersprungen.")
            return_result = {
                "picks": [],
                "isk_used": 0.0,
                "profit_total": 0.0,
                "funnel": None
            }
        else:
            return_budget_isk = capital_available if bool(capital_flow_cfg.get("enabled", False)) else float(budget_isk)
            return_result = run_route(
                esi, cj6_id, o4t_id, "return",
                structure_labels[cj6_id], structure_labels[o4t_id],
                return_filters, port_cfg, fees, return_mode,
                replay_cfg, replay_snapshot, structure_orders_by_id,
                return_budget_isk, cargo_m3, cfg, timestamp, out_dir
            )
            capital_available = _apply_capital_flow_to_leg(return_result, return_mode, capital_available, capital_flow_cfg)

        summary_path = os.path.join(out_dir, f"roundtrip_plan_{timestamp}.txt")
        write_enhanced_summary(
            summary_path,
            forward_result["picks"], float(forward_result["isk_used"]), float(forward_result["profit_total"]),
            return_result["picks"], float(return_result["isk_used"]), float(return_result["profit_total"]),
            cargo_m3, budget_isk,
            forward_funnel=forward_result.get("funnel"),
            return_funnel=return_result.get("funnel"),
            run_uuid=""
        )
        created_files.append(summary_path)
        created_files.append(forward_result["csv_path"])
        created_files.append(forward_result["dump_path"])
        if route_mode != "forward_only":
            created_files.append(return_result["csv_path"])
            created_files.append(return_result["dump_path"])

    if hasattr(esi, "_type_cache_dirty") and int(getattr(esi, "_type_cache_dirty", 0)) > 0:
        try:
            save_json(TYPE_CACHE_PATH, getattr(esi, "type_cache", {}))
            save_json(HTTP_CACHE_PATH, getattr(esi, "_http_cache", {}))
            setattr(esi, "_type_cache_dirty", 0)
        except Exception:
            pass

    print("")
    if hasattr(esi, "get_performance_summary_lines"):
        try:
            for l in esi.get_performance_summary_lines():
                print(l)
        except Exception:
            pass
        print("")
    print("Fertig!")
    print("=== ERSTELLTE DATEIEN ===")
    for p in created_files:
        print(p)
    print("market_snapshot.json erstellt.")
    print("")


# Externalized module overrides (phase 1 refactor).
# Runtime source-of-truth is intentionally the extracted modules below.
# Kept legacy function bodies above remain for compatibility/history only.
from candidate_engine import (
    _choose_best_route_wide_candidate as _mod_choose_best_route_wide_candidate,
    _route_adjusted_candidate_score as _mod_route_adjusted_candidate_score,
    apply_strategy_filters as _mod_apply_strategy_filters,
    build_levels as _mod_build_levels,
    compute_candidates as _mod_compute_candidates,
    compute_route_wide_candidates_for_source as _mod_compute_route_wide_candidates_for_source,
    depth_slice as _mod_depth_slice,
    get_structure_micro_liquidity as _mod_get_structure_micro_liquidity,
)
from market_fetch import _fetch_orders_for_node as _mod_fetch_orders_for_node
from portfolio_builder import (
    _sort_candidates_for_cargo_fill as _mod_sort_candidates_for_cargo_fill,
    build_portfolio as _mod_build_portfolio,
    choose_portfolio_for_route as _mod_choose_portfolio_for_route,
    local_search_optimize as _mod_local_search_optimize,
    portfolio_stats as _mod_portfolio_stats,
    sort_picks_for_output as _mod_sort_picks_for_output,
    try_cargo_fill as _mod_try_cargo_fill,
    validate_portfolio as _mod_validate_portfolio,
)

globals().update(
    {
        "ensure_dirs": _mod_ensure_dirs,
        "load_config": _mod_load_config,
        "load_json": _mod_load_json,
        "save_json": _mod_save_json,
        "validate_config": _mod_validate_config,
        "fail_on_invalid_config": _mod_fail_on_invalid_config,
        "_prepare_trade_filters": _mod_prepare_trade_filters,
        "_build_fix_hint": _mod_build_fix_hint,
        "_resolve_strict_mode_cfg": _mod_resolve_strict_mode_cfg,
        "_collect_required_structure_ids": _mod_collect_required_structure_ids,
        "_resolve_structure_region_map": _mod_resolve_structure_region_map,
        "_validate_structure_region_mapping": _mod_validate_structure_region_mapping,
        "apply_strategy_mode": _mod_apply_strategy_mode,
        "compute_volatility_score": _mod_compute_volatility_score,
        "compute_trade_financials": _mod_compute_trade_financials,
        "normalize_location_label": _mod_normalize_location_label2,
        "label_to_slug": _mod_label_to_slug,
        "build_levels": _mod_build_levels,
        "get_structure_micro_liquidity": _mod_get_structure_micro_liquidity,
        "depth_slice": _mod_depth_slice,
        "apply_strategy_filters": _mod_apply_strategy_filters,
        "compute_candidates": _mod_compute_candidates,
        "compute_route_wide_candidates_for_source": _mod_compute_route_wide_candidates_for_source,
        "_route_adjusted_candidate_score": _mod_route_adjusted_candidate_score,
        "_choose_best_route_wide_candidate": _mod_choose_best_route_wide_candidate,
        "build_portfolio": _mod_build_portfolio,
        "choose_portfolio_for_route": _mod_choose_portfolio_for_route,
        "validate_portfolio": _mod_validate_portfolio,
        "local_search_optimize": _mod_local_search_optimize,
        "portfolio_stats": _mod_portfolio_stats,
        "sort_picks_for_output": _mod_sort_picks_for_output,
        "_sort_candidates_for_cargo_fill": _mod_sort_candidates_for_cargo_fill,
        "try_cargo_fill": _mod_try_cargo_fill,
        "_fetch_orders_for_node": _mod_fetch_orders_for_node,
        "normalize_replay_snapshot": _mod_normalize_replay_snapshot,
        "make_snapshot_payload": _mod_make_snapshot_payload,
        "compute_jita_split_price": _mod_compute_jita_split_price,
        "build_jita_split_price_map": _mod_build_jita_split_price_map,
        "split_shipping_contracts": _mod_split_shipping_contracts,
        "compute_shipping_lane_reward_cost_single": _mod_compute_shipping_lane_reward_cost_single,
        "compute_shipping_lane_total_cost": _mod_compute_shipping_lane_total_cost,
        "compute_shipping_lane_reward_cost": _mod_compute_shipping_lane_reward_cost,
        "_lane_provider_from_cfg": _mod_lane_provider_from_cfg,
        "_policy_provider_for_route": _mod_policy_provider_for_route,
        "_lane_has_complete_pricing_params": _mod_lane_has_complete_pricing_params,
        "_match_shipping_lanes": _mod_match_shipping_lanes,
        "resolve_shipping_lane_cfg": _mod_resolve_shipping_lane_cfg,
        "resolve_route_cost_cfg": _mod_resolve_route_cost_cfg,
        "build_route_context": _mod_build_route_context,
        "_extract_shipping_lane_params": _mod_extract_shipping_lane_params,
        "_pick_passes_profit_floors": _mod_pick_passes_profit_floors,
        "apply_route_costs_to_picks": _mod_apply_route_costs_to_picks,
        "apply_route_costs_and_prune": _mod_apply_route_costs_and_prune,
        "_resolve_route_search_cfg": _mod_resolve_route_search_cfg,
        "_parse_route_pair_token": _mod_parse_route_pair_token,
        "_resolve_allowed_route_pairs": _mod_resolve_allowed_route_pairs,
        "_resolve_allowed_route_pair_lane_overrides": _mod_resolve_allowed_route_pair_lane_overrides,
        "build_route_search_profiles": _mod_build_route_search_profiles,
        "_normalize_route_mode": _mod_main_normalize_route_mode,
        "_resolve_chain_runtime": _mod_main_resolve_chain_runtime,
        "_build_structure_context": _mod_main_build_structure_context,
        "_resolve_location_nodes": _mod_main_resolve_location_nodes,
        "_resolve_node_catalog": _mod_main_resolve_node_catalog,
        "_node_source_dest_info": _mod_main_node_source_dest_info,
        "_resolve_primary_structure_ids": _mod_main_resolve_primary_structure_ids,
        "write_execution_plan_profiles": _mod_write_execution_plan_profiles,
        "write_route_leaderboard": _mod_write_route_leaderboard,
    }
)


def main():
    from main import main as _primary_main
    return _primary_main()


if __name__ == "__main__":
    main()
