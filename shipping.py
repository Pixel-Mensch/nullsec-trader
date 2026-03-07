import math
from location_utils import normalize_location_label


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


def compute_shipping_lane_reward_cost_single(lane_cfg: dict, volume_m3: float, collateral_isk: float) -> float:
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


def compute_shipping_lane_total_cost(lane_cfg: dict, total_volume_m3: float, total_collateral_isk: float) -> dict:
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


def compute_shipping_lane_reward_cost(lane_cfg: dict, volume_m3: float, collateral_isk: float) -> float:
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
    matched = False
    for key in key_pairs:
        if key in route_costs and isinstance(route_costs.get(key), dict):
            found = dict(route_costs.get(key) or {})
            matched = True
            break
    fixed_isk = float(found.get("fixed_isk", 0.0) or 0.0)
    isk_per_m3 = float(found.get("isk_per_m3", 0.0) or 0.0)
    return {
        "fixed_isk": max(0.0, fixed_isk),
        "isk_per_m3": max(0.0, isk_per_m3),
        "is_explicit": bool(matched),
    }


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
    return {
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


def apply_route_costs_to_picks(picks: list[dict], route_context: dict) -> dict:
    if not picks:
        route_cfg = route_context.get("route_cost_cfg", {})
        if not isinstance(route_cfg, dict):
            route_cfg = {}
        route_cost_is_explicit = bool(route_cfg.get("is_explicit", False))
        missing_cost_model = (
            route_context.get("shipping_lane_cfg") is None
            and not list(route_context.get("shipping_lane_candidates", []) or [])
            and not route_cost_is_explicit
        )
        cost_model_confidence = "low" if missing_cost_model else "normal"
        cost_model_status = "assumed_zero_transport" if missing_cost_model else "configured"
        cost_model_warning = ""
        if missing_cost_model:
            cost_model_warning = (
                "No shipping lane or explicit route_costs matched this route; transport cost is assumed as 0 ISK."
            )
        return {
            "total_shipping_cost": 0.0,
            "total_route_cost": 0.0,
            "total_transport_cost": 0.0,
            "shipping_lane_id": str(route_context.get("shipping_lane_id", "") or ""),
            "route_cost_is_explicit": bool(route_cost_is_explicit),
            "cost_model_status": cost_model_status,
            "cost_model_confidence": cost_model_confidence,
            "transport_cost_assumed_zero": bool(missing_cost_model),
            "cost_model_warning": cost_model_warning,
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
    route_cost_is_explicit = bool(route_cfg.get("is_explicit", False))
    route_total = route_fixed + (route_per_m3 * total_volume)
    transport_total = shipping_total + route_total
    missing_cost_model = (
        selected_lane_cfg is None
        and not lane_candidates
        and not route_cost_is_explicit
    )
    cost_model_confidence = "low" if missing_cost_model else "normal"
    cost_model_status = "assumed_zero_transport" if missing_cost_model else "configured"
    cost_model_warning = ""
    if missing_cost_model:
        cost_model_warning = (
            "No shipping lane or explicit route_costs matched this route; transport cost is assumed as 0 ISK."
        )

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
            p["transport_cost_confidence"] = cost_model_confidence
            if cost_model_warning:
                p["transport_cost_warning"] = cost_model_warning
    else:
        for p in picks:
            p.setdefault("shipping_cost", 0.0)
            p.setdefault("route_cost", 0.0)
            p.setdefault("transport_cost", 0.0)
            p["transport_cost_confidence"] = cost_model_confidence
            if cost_model_warning:
                p["transport_cost_warning"] = cost_model_warning

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
        "route_cost_is_explicit": bool(route_cost_is_explicit),
        "cost_model_status": cost_model_status,
        "cost_model_confidence": cost_model_confidence,
        "transport_cost_assumed_zero": bool(missing_cost_model),
        "cost_model_warning": cost_model_warning,
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
    changed = True
    while changed:
        changed = False
        kept = [p for p in work if _pick_passes_profit_floors(p, filters_used) and float(p.get("profit", 0.0)) > 0.0]
        if len(kept) < len(work):
            work = kept
            summary = apply_route_costs_to_picks(work, route_context)
            changed = True
    return work, summary
