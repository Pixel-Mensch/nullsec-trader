import json
import os
import threading
import io
from contextlib import redirect_stdout


CACHE_IO_LOCK = threading.Lock()


def ensure_dirs(cache_dir: str | None = None) -> None:
    target = cache_dir or os.path.join(os.path.dirname(__file__), "cache")
    os.makedirs(target, exist_ok=True)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError:
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
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return
            except (PermissionError, OSError):
                if attempt < 2:
                    import time
                    time.sleep(0.5)
                    continue
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return


def _deep_merge_dict(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _parse_env_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    txt = str(value).strip().lower()
    if txt in ("1", "true", "yes", "on"):
        return True
    if txt in ("0", "false", "no", "off"):
        return False
    return None


def _apply_env_overrides(cfg: dict) -> dict:
    out = dict(cfg)
    esi_cfg = out.get("esi", {})
    if not isinstance(esi_cfg, dict):
        esi_cfg = {}
    replay_cfg = out.get("replay", {})
    if not isinstance(replay_cfg, dict):
        replay_cfg = {}

    env_to_esi_key = {
        "ESI_BASE_URL": "base_url",
        "ESI_USER_AGENT": "user_agent",
        "ESI_CALLBACK_URL": "callback_url",
        "ESI_SCOPE": "scope",
        "ESI_CLIENT_ID": "client_id",
        "ESI_CLIENT_SECRET": "client_secret",
    }
    runtime_meta = out.get("_runtime_meta", {})
    if not isinstance(runtime_meta, dict):
        runtime_meta = {}
    if str(esi_cfg.get("client_secret", "")).strip():
        if bool(runtime_meta.get("client_secret_from_local_config", False)):
            runtime_meta["client_secret_source"] = "config.local.json"
        elif bool(runtime_meta.get("client_secret_from_config_json", False)):
            runtime_meta["client_secret_source"] = "config.json"
    for env_key, cfg_key in env_to_esi_key.items():
        env_val = os.getenv(env_key)
        if env_val is None:
            continue
        val = str(env_val).strip()
        if not val:
            continue
        esi_cfg[cfg_key] = val
        if env_key == "ESI_CLIENT_SECRET":
            runtime_meta["client_secret_from_env"] = True
            runtime_meta["client_secret_source"] = "env"

    replay_enabled_env = _parse_env_bool(os.getenv("NULLSEC_REPLAY_ENABLED"))
    if replay_enabled_env is not None:
        replay_cfg["enabled"] = bool(replay_enabled_env)

    out["esi"] = esi_cfg
    out["replay"] = replay_cfg
    out["_runtime_meta"] = runtime_meta
    return out


def load_config(config_path: str | None = None) -> dict:
    path = config_path or os.path.join(os.path.dirname(__file__), "config.json")
    cfg = load_json(path, {})
    if not isinstance(cfg, dict):
        cfg = {}
    runtime_meta = cfg.get("_runtime_meta", {})
    if not isinstance(runtime_meta, dict):
        runtime_meta = {}
    base_esi_cfg = cfg.get("esi", {})
    if isinstance(base_esi_cfg, dict) and str(base_esi_cfg.get("client_secret", "")).strip():
        runtime_meta["client_secret_from_config_json"] = True
        runtime_meta["client_secret_source"] = "config.json"
    cfg["_runtime_meta"] = runtime_meta

    local_cfg_path = os.getenv("NULLSEC_LOCAL_CONFIG", "").strip()
    if not local_cfg_path:
        local_cfg_path = os.path.join(os.path.dirname(path), "config.local.json")
    if os.path.exists(local_cfg_path):
        local_cfg = load_json(local_cfg_path, {})
        if isinstance(local_cfg, dict):
            cfg = _deep_merge_dict(cfg, local_cfg)
            local_esi_cfg = local_cfg.get("esi", {})
            if isinstance(local_esi_cfg, dict) and str(local_esi_cfg.get("client_secret", "")).strip():
                runtime_meta = cfg.get("_runtime_meta", {})
                if not isinstance(runtime_meta, dict):
                    runtime_meta = {}
                runtime_meta["client_secret_from_local_config"] = True
                runtime_meta["client_secret_source"] = "config.local.json"
                cfg["_runtime_meta"] = runtime_meta

    return _apply_env_overrides(cfg)


def _resolve_strict_mode_cfg(cfg: dict) -> dict:
    strict = cfg.get("strict_mode", {})
    if not isinstance(strict, dict):
        strict = {}
    return {
        "enabled": bool(strict.get("enabled", False)),
        "prefer_instant_first": bool(strict.get("prefer_instant_first", True)),
        "disable_fallback_volume_for_planned": bool(strict.get("disable_fallback_volume_for_planned", True)),
        "require_reference_price_for_planned": bool(strict.get("require_reference_price_for_planned", True)),
        "planned_max_expected_days_to_sell": float(strict.get("planned_max_expected_days_to_sell", 45.0)),
        "planned_min_sell_through_ratio_90d": float(strict.get("planned_min_sell_through_ratio_90d", 0.70)),
        "planned_min_avg_daily_volume_30d": float(strict.get("planned_min_avg_daily_volume_30d", 0.25)),
        "planned_min_avg_daily_volume_7d": float(strict.get("planned_min_avg_daily_volume_7d", 0.15)),
        "planned_soft_sell_markup_vs_ref": float(strict.get("planned_soft_sell_markup_vs_ref", 0.20)),
        "planned_max_sell_markup_vs_ref": float(strict.get("planned_max_sell_markup_vs_ref", 0.40)),
        "planned_hard_max_sell_markup_vs_ref": float(strict.get("planned_hard_max_sell_markup_vs_ref", 0.80)),
        "planned_reference_penalty_strength": float(strict.get("planned_reference_penalty_strength", 0.60)),
        "planned_max_units_cap": int(strict.get("planned_max_units_cap", 3)),
        "planned_profit_floor_isk": float(strict.get("planned_profit_floor_isk", 2_000_000.0)),
        "instant_min_profit_pct": float(strict.get("instant_min_profit_pct", 0.03)),
        "instant_min_profit_isk_total": float(strict.get("instant_min_profit_isk_total", 1_000_000.0)),
        "instant_min_fill_probability": float(strict.get("instant_min_fill_probability", 0.90)),
        "instant_min_depth_units": int(strict.get("instant_min_depth_units", 3)),
        "fast_sell_allowed_for_capital_release": bool(strict.get("fast_sell_allowed_for_capital_release", False)),
        "chain_leg_max_budget_share": float(strict.get("chain_leg_max_budget_share", 0.60)),
    }


def _collect_required_structure_ids(cfg: dict, runtime_required_structure_ids: set[int] | None = None) -> set[int]:
    out: set[int] = set()
    if isinstance(runtime_required_structure_ids, set):
        for sid in runtime_required_structure_ids:
            try:
                iv = int(sid)
            except Exception:
                continue
            if iv > 0:
                out.add(iv)

    structures_cfg = cfg.get("structures", {})
    if isinstance(structures_cfg, dict):
        for _, raw in structures_cfg.items():
            sid = 0
            if isinstance(raw, dict):
                try:
                    sid = int(raw.get("id", 0) or 0)
                except Exception:
                    sid = 0
            else:
                try:
                    sid = int(raw)
                except Exception:
                    sid = 0
            if sid > 0:
                out.add(sid)

    chain_cfg = cfg.get("route_chain", {})
    chain_enabled = bool(chain_cfg.get("enabled", False)) if isinstance(chain_cfg, dict) else False
    legs = chain_cfg.get("legs", []) if isinstance(chain_cfg, dict) else []
    if chain_enabled and isinstance(legs, list):
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            try:
                sid = int(leg.get("id", 0) or 0)
            except Exception:
                sid = 0
            if sid > 0:
                out.add(sid)

    for key in ("required_structure_ids", "required_structure_ids_forward", "required_structure_ids_return"):
        vals = cfg.get(key, [])
        if not isinstance(vals, list):
            continue
        for v in vals:
            try:
                sid = int(v)
            except Exception:
                sid = 0
            if sid > 0:
                out.add(sid)

    return out


def _normalize_region_alias_token(s: str) -> str:
    txt = str(s or "").strip().lower()
    if not txt:
        return ""
    return "".join(ch for ch in txt if ch.isalnum())


def _infer_missing_structure_regions(cfg: dict, current_map: dict[int, int]) -> tuple[dict[int, int], list[tuple[int, int, str]]]:
    known_alias_to_region = {
        "o4t": 10000059,
        "o4tz5": 10000059,
        "cj6": 10000009,
        "cj6mt": 10000009,
    }
    auto_fill_enabled = bool(
        cfg.get("esi", {}).get("auto_fill_structure_regions", cfg.get("defaults", {}).get("auto_fill_structure_regions", False))
    )
    if not auto_fill_enabled:
        return dict(current_map), []

    out = dict(current_map)
    filled: list[tuple[int, int, str]] = []
    structures_cfg = cfg.get("structures", {})
    if isinstance(structures_cfg, dict):
        for key, raw in structures_cfg.items():
            sid = 0
            aliases = [str(key)]
            if isinstance(raw, dict):
                try:
                    sid = int(raw.get("id", 0) or 0)
                except Exception:
                    sid = 0
                aliases.append(str(raw.get("label", "")))
                aliases.append(str(raw.get("system", "")))
            else:
                try:
                    sid = int(raw)
                except Exception:
                    sid = 0
            if sid <= 0 or sid in out:
                continue
            rid = 0
            used_alias = ""
            for alias in aliases:
                token = _normalize_region_alias_token(alias)
                if token in known_alias_to_region:
                    rid = int(known_alias_to_region[token])
                    used_alias = alias
                    break
            if rid > 0:
                out[sid] = rid
                filled.append((sid, rid, used_alias))

    chain_cfg = cfg.get("route_chain", {})
    legs = chain_cfg.get("legs", []) if isinstance(chain_cfg, dict) else []
    if isinstance(legs, list):
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            try:
                sid = int(leg.get("id", 0) or 0)
            except Exception:
                sid = 0
            if sid <= 0 or sid in out:
                continue
            aliases = [str(leg.get("label", "")), str(leg.get("system", ""))]
            rid = 0
            used_alias = ""
            for alias in aliases:
                token = _normalize_region_alias_token(alias)
                if token in known_alias_to_region:
                    rid = int(known_alias_to_region[token])
                    used_alias = alias
                    break
            if rid > 0:
                out[sid] = rid
                filled.append((sid, rid, used_alias))
    return out, filled


def _resolve_structure_region_map(cfg: dict, emit_info: bool = False) -> dict[int, int]:
    out: dict[int, int] = {}
    raw_map = cfg.get("structure_regions", {})
    if isinstance(raw_map, dict):
        for sid_k, rid_v in raw_map.items():
            try:
                sid = int(sid_k)
                rid = int(rid_v)
            except Exception:
                continue
            if sid > 0 and rid > 0:
                out[sid] = rid

    structures_cfg = cfg.get("structures", {})
    if isinstance(structures_cfg, dict):
        for _, raw in structures_cfg.items():
            sid = 0
            rid = 0
            if isinstance(raw, dict):
                try:
                    sid = int(raw.get("id", 0) or 0)
                    rid = int(raw.get("region_id", 0) or 0)
                except Exception:
                    sid, rid = 0, 0
            else:
                try:
                    sid = int(raw)
                except Exception:
                    sid = 0
            if sid > 0 and rid > 0:
                out[sid] = rid

    chain_cfg = cfg.get("route_chain", {})
    legs = chain_cfg.get("legs", []) if isinstance(chain_cfg, dict) else []
    if isinstance(legs, list):
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            try:
                sid = int(leg.get("id", 0) or 0)
                rid = int(leg.get("region_id", 0) or 0)
            except Exception:
                sid, rid = 0, 0
            if sid > 0 and rid > 0:
                out[sid] = rid
    out, filled = _infer_missing_structure_regions(cfg, out)
    if emit_info and filled:
        print(f"INFO: Auto-filled structure_regions for {len(filled)} known structures from offline defaults.")
        for sid, rid, alias in filled:
            alias_txt = str(alias).strip() or "unknown"
            print(f"  -> structure_id {sid} => region_id {rid} (alias={alias_txt})")
    return out


def _warn_missing_structure_regions(
    cfg: dict,
    structure_region_map: dict[int, int],
    required_structure_ids: set[int],
    planned_mode_active: bool
) -> None:
    missing = [int(sid) for sid in sorted(required_structure_ids) if int(structure_region_map.get(int(sid), 0)) <= 0]
    if not missing:
        return
    labels_by_sid: dict[int, set[str]] = {}
    structures_cfg = cfg.get("structures", {})
    if isinstance(structures_cfg, dict):
        for label_raw, raw in structures_cfg.items():
            sid = 0
            if isinstance(raw, dict):
                try:
                    sid = int(raw.get("id", 0) or 0)
                except Exception:
                    sid = 0
            else:
                try:
                    sid = int(raw)
                except Exception:
                    sid = 0
            if sid <= 0:
                continue
            lbl = str(label_raw).strip()
            if not lbl:
                continue
            labels_by_sid.setdefault(int(sid), set()).add(lbl)
            if isinstance(raw, dict):
                alt = str(raw.get("label", "")).strip()
                if alt:
                    labels_by_sid.setdefault(int(sid), set()).add(alt)

    chain_cfg = cfg.get("route_chain", {})
    if isinstance(chain_cfg, dict) and bool(chain_cfg.get("enabled", False)):
        legs = chain_cfg.get("legs", [])
        if isinstance(legs, list):
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                try:
                    sid = int(leg.get("id", 0) or 0)
                except Exception:
                    sid = 0
                if sid <= 0:
                    continue
                lbl = str(leg.get("label", "")).strip()
                if lbl:
                    labels_by_sid.setdefault(int(sid), set()).add(lbl)

    def _fmt_sid(sid: int) -> str:
        labels = sorted(labels_by_sid.get(int(sid), set()))
        if labels:
            return f"{sid} ({' / '.join(labels)})"
        return str(sid)

    missing_s = ", ".join(_fmt_sid(sid) for sid in missing)
    print(f"WARN: Kein region_id Mapping fuer aktive Structure IDs: {missing_s}.")
    if planned_mode_active:
        print(
            "WARN: planned_sell kann ohne regionale History fuer diese Ziele nicht belastbar bewertet werden: "
            f"{missing_s}."
        )


def _validate_structure_region_mapping(
    cfg: dict,
    structure_region_map: dict[int, int],
    required_structure_ids: set[int],
    planned_mode_active: bool
) -> list[int]:
    missing = [int(sid) for sid in sorted(required_structure_ids) if int(structure_region_map.get(int(sid), 0)) <= 0]
    if not missing:
        return []

    strict_enabled = bool(cfg.get("esi", {}).get("strict_region_mapping", False))
    missing_s = ", ".join(str(s) for s in missing)
    if strict_enabled:
        raise SystemExit(
            "Strict region mapping aktiv. Fehlendes structure_id -> region_id Mapping fuer: "
            f"{missing_s}. planned_sell kann ohne regionale History nicht valide pruefen."
        )

    _warn_missing_structure_regions(
        cfg=cfg,
        structure_region_map=structure_region_map,
        required_structure_ids=set(missing),
        planned_mode_active=planned_mode_active
    )
    if planned_mode_active:
        print("WARN: planned_sell wird restriktiv, weil regionale History nicht geprueft werden kann.")
    return missing


def validate_or_raise(cfg: dict) -> dict:
    result = validate_config(cfg)
    fail_on_invalid_config(result)
    return result


def _classify_validation_message(level: str, msg: str) -> dict:
    s = str(msg).strip()
    level_u = str(level).upper()
    code = "VALIDATION_GENERIC"
    path = ""
    context: dict = {}

    if s.startswith("Security warning: client_secret is stored in config.json"):
        code = "SECURITY_SECRET_IN_CONFIG"
        path = "esi.client_secret"
    elif s.startswith("Security warning: client_secret is loaded from config.local.json"):
        code = "SECURITY_SECRET_IN_LOCAL_CONFIG"
        path = "esi.client_secret"
    elif s.startswith("Security warning: client_secret is provided via ENV"):
        code = "SECURITY_SECRET_FROM_ENV"
        path = "esi.client_secret"
    elif s.startswith("esi.user_agent"):
        code = "ESI_USER_AGENT_MISSING"
        path = "esi.user_agent"
    elif s.startswith("esi.base_url"):
        code = "ESI_BASE_URL_MISSING"
        path = "esi.base_url"
    elif s.startswith("fees.") and "non-negative number" in s:
        code = "FEES_NEGATIVE"
        path = s.split(" ", 1)[0]
    elif s.startswith("fees.") and "implausibly high" in s:
        code = "FEES_IMPLAUSIBLE"
        path = s.split(" ", 1)[0]
    elif s.startswith("structures must not be empty"):
        code = "STRUCTURES_EMPTY"
        path = "structures"
    elif s.startswith("structures.") and "invalid structure id" in s:
        code = "STRUCTURE_ID_INVALID"
        path = s.split(" ", 1)[0]
    elif s.startswith("structure_regions contains unused structure_id"):
        code = "REGION_MAPPING_UNUSED"
        path = "structure_regions"
    elif s.startswith("Kein region_id Mapping fuer aktive Structure IDs"):
        code = "REGION_MAPPING_MISSING"
        path = "structure_regions"
    elif s.startswith("planned_sell kann ohne regionale History fuer diese Ziele nicht belastbar bewertet werden"):
        code = "REGION_MAPPING_PLANNED_SELL_UNRELIABLE"
        path = "structure_regions"
    elif s.startswith("Missing region mapping for structure_id") or "Missing region mapping for structure_id" in s or "Strict region mapping aktiv" in s:
        code = "REGION_MAPPING_MISSING"
        path = "structure_regions"
    elif s.startswith("route_chain.legs"):
        code = "ROUTE_CHAIN_LEG_INVALID"
        path = "route_chain.legs"
    elif s.startswith("route_chain.legs cannot be empty"):
        code = "ROUTE_CHAIN_EMPTY"
        path = "route_chain.legs"
    elif s.startswith("route_chain.legs must be a list"):
        code = "ROUTE_CHAIN_INVALID"
        path = "route_chain.legs"
    elif ".mode must be one of:" in s:
        code = "MODE_INVALID"
        path = s.split(" ", 1)[0]

    return {
        "level": level_u,
        "code": code,
        "path": path,
        "message": s,
        "context": context,
    }


def _build_fix_hint(issue: dict, cfg: dict) -> str | None:
    code = str(issue.get("code", "")).upper()
    msg = str(issue.get("message", ""))
    strict_enabled = bool(cfg.get("esi", {}).get("strict_region_mapping", False))
    auto_fill_enabled = bool(cfg.get("esi", {}).get("auto_fill_structure_regions", False))

    if code in ("FEES_NEGATIVE", "FEES_NOT_NUMBER", "FEES_IMPLAUSIBLE"):
        return (
            "Setze in config.json plausible fees, z.B. "
            "\"fees\": {\"sales_tax\": 0.075, \"buy_broker_fee\": 0.0, "
            "\"sell_broker_fee\": 0.03, \"scc_surcharge\": 0.005, "
            "\"skills\": {\"accounting\": 3, \"broker_relations\": 3, \"advanced_broker_relations\": 3}, "
            "\"relist_budget_pct\": 0.0, \"relist_budget_isk\": 0.0}"
        )
    if code in ("STRUCTURE_ID_INVALID", "STRUCTURES_EMPTY"):
        return (
            "Nutze gueltige structures, z.B. "
            "\"structures\": {\"o4t\": 1040804972352, \"cj6\": 1049588174021} "
            "oder \"structures\": {\"o4t\": {\"id\": 1040804972352, \"region_id\": 10000059}}."
        )
    if code == "REGION_MAPPING_MISSING":
        strict_txt = " oder setze \"esi.strict_region_mapping\": false" if strict_enabled else ""
        autofill_txt = " Optional: \"esi.auto_fill_structure_regions\": true fuer bekannte Aliase." if not auto_fill_enabled else " auto_fill_structure_regions ist aktiv, explizites Mapping bleibt empfohlen."
        return (
            "Ergaenze structure_regions, z.B. "
            "\"structure_regions\": {\"1040804972352\": 10000059, \"1049588174021\": 10000009}"
            f"{strict_txt}.{autofill_txt}"
        )
    if code in ("ROUTE_CHAIN_INVALID", "ROUTE_CHAIN_EMPTY", "ROUTE_CHAIN_LEG_INVALID"):
        return (
            "Pruefe route_chain.legs, z.B. "
            "\"route_chain\": {\"legs\": [{\"id\": 1040804972352, \"label\": \"o4t\", \"region_id\": 10000059}, "
            "{\"id\": 1049588174021, \"label\": \"cj6\", \"region_id\": 10000009}]}"
        )
    if code == "MODE_INVALID":
        extra = " planned_sell wird ohne region mapping restriktiv." if "planned_sell" in msg.lower() else ""
        return f"Erlaubte mode-Werte sind: instant, fast_sell, planned_sell.{extra}"
    if code == "ESI_USER_AGENT_MISSING":
        return "Setze in config.json einen user_agent, z.B. \"user_agent\": \"NullsecTrader/0.1 (contact: discordname)\"."
    if code == "SECURITY_SECRET_IN_CONFIG":
        return (
            "Leere/entferne client_secret aus config.json und nutze ENV (z.B. ESI_CLIENT_SECRET) "
            "oder eine lokale, nicht versionierte Secret-Datei."
        )
    if code == "SECURITY_SECRET_IN_LOCAL_CONFIG":
        return (
            "Belasse Secrets nur in einer lokalen, nicht versionierten Datei. "
            "Stelle sicher, dass config.local.json in .gitignore bleibt."
        )
    if code == "SECURITY_SECRET_FROM_ENV":
        return "Secret-Quelle ist korrekt (ENV). Achte darauf, ESI_CLIENT_SECRET nicht in Logs auszugeben."
    if code == "REGION_MAPPING_UNUSED":
        return "Entferne den ungenutzten structure_regions Eintrag oder stelle sicher, dass die Structure im Run wirklich genutzt wird."
    if code == "REGION_MAPPING_PLANNED_SELL_UNRELIABLE":
        return (
            "Ergaenze structure_regions fuer die genannten Ziele, damit planned_sell regionale History nutzen kann "
            "und die Bewertung belastbar bleibt."
        )
    return None


def _build_validation_issues(errors: list[str], warnings: list[str]) -> list[dict]:
    issues = []
    for w in warnings:
        issues.append(_classify_validation_message("WARNING", w))
    for e in errors:
        issues.append(_classify_validation_message("ERROR", e))
    return issues


def validate_config(cfg: dict) -> dict:
    result = {"errors": [], "warnings": [], "issues": [], "cfg": cfg if isinstance(cfg, dict) else {}}

    def err(msg: str) -> None:
        result["errors"].append(str(msg))

    def warn(msg: str) -> None:
        result["warnings"].append(str(msg))

    def _is_num(v) -> bool:
        try:
            float(v)
            return True
        except Exception:
            return False

    def _check_non_negative(path: str, v, plausible_max: float | None = None) -> None:
        if not _is_num(v):
            err(f"{path} must be a non-negative number")
            return
        fv = float(v)
        if fv < 0:
            err(f"{path} must be a non-negative number")
            return
        if plausible_max is not None and fv > plausible_max:
            warn(f"{path} seems implausibly high ({fv})")

    if not isinstance(cfg, dict):
        err("config root must be an object")
        return result

    for key in ("esi", "fees", "structures", "locations", "structure_regions", "filters_forward", "filters_return", "route_chain", "defaults", "diagnostics", "replay", "route_costs", "shipping_lanes", "shipping_defaults", "route_profiles", "route_search", "confidence_calibration", "character_context"):
        if key in cfg and not isinstance(cfg.get(key), dict):
            err(f"{key} must be an object")

    esi_cfg = cfg.get("esi", {})
    replay_cfg = cfg.get("replay", {})
    replay_enabled = bool(replay_cfg.get("enabled", False)) if isinstance(replay_cfg, dict) else False
    live_mode = not replay_enabled
    if not isinstance(esi_cfg, dict):
        err("esi must be an object")
        esi_cfg = {}

    if live_mode:
        if not str(esi_cfg.get("base_url", "")).strip():
            err("esi.base_url must be non-empty in live mode")
    if not str(esi_cfg.get("user_agent", "")).strip():
        err("esi.user_agent must be non-empty")
    if "request_min_interval_sec" in esi_cfg:
        if not _is_num(esi_cfg.get("request_min_interval_sec")) or float(esi_cfg.get("request_min_interval_sec")) < 0:
            err("esi.request_min_interval_sec must be a non-negative number")
    ttl = esi_cfg.get("cache_default_ttl_sec", 60)
    if not _is_num(ttl) or int(float(ttl)) <= 0:
        err("esi.cache_default_ttl_sec must be a positive integer")
    if "strict_region_mapping" in esi_cfg and not isinstance(esi_cfg.get("strict_region_mapping"), bool):
        err("esi.strict_region_mapping must be a boolean")
    if "auto_fill_structure_regions" in esi_cfg and not isinstance(esi_cfg.get("auto_fill_structure_regions"), bool):
        err("esi.auto_fill_structure_regions must be a boolean")
    runtime_meta = cfg.get("_runtime_meta", {})
    if not isinstance(runtime_meta, dict):
        runtime_meta = {}
    client_secret = str(esi_cfg.get("client_secret", "")).strip()
    client_secret_source = str(runtime_meta.get("client_secret_source", "")).strip().lower()
    if client_secret:
        if client_secret_source == "env" or bool(runtime_meta.get("client_secret_from_env", False)):
            warn("Security warning: client_secret is provided via ENV.")
        elif client_secret_source == "config.local.json" or bool(runtime_meta.get("client_secret_from_local_config", False)):
            warn("Security warning: client_secret is loaded from config.local.json. Keep it local and untracked.")
        else:
            warn("Security warning: client_secret is stored in config.json. Prefer environment or local untracked secret storage.")

    structures_cfg = cfg.get("structures", {})
    if not isinstance(structures_cfg, dict):
        err("structures must be an object")
        structures_cfg = {}
    if len(structures_cfg) == 0:
        err("structures must not be empty")
    if "o4t" not in structures_cfg or "cj6" not in structures_cfg:
        err("structures must include both keys: o4t and cj6")
    seen_ids: dict[int, str] = {}
    for label, raw in structures_cfg.items():
        lbl = str(label).strip()
        if not lbl:
            err("structures contains an empty label key")
            continue
        sid = 0
        rid = None
        if isinstance(raw, dict):
            try:
                sid = int(raw.get("id", 0) or 0)
            except Exception:
                sid = 0
            if "region_id" in raw:
                rid = raw.get("region_id")
        else:
            try:
                sid = int(raw)
            except Exception:
                sid = 0
        if sid <= 0:
            err(f"structures.{lbl} has invalid structure id")
            continue
        if sid in seen_ids and seen_ids[sid] != lbl:
            warn(f"duplicate structure id {sid} used by labels '{seen_ids[sid]}' and '{lbl}'")
        seen_ids[sid] = lbl
        if rid is not None:
            try:
                rid_i = int(rid)
            except Exception:
                rid_i = 0
            if rid_i <= 0:
                err(f"structures.{lbl}.region_id must be a positive integer")

    locations_cfg = cfg.get("locations", {})
    if locations_cfg is not None and not isinstance(locations_cfg, dict):
        err("locations must be an object")
    elif isinstance(locations_cfg, dict):
        for label, raw in locations_cfg.items():
            lbl = str(label).strip()
            if not lbl:
                err("locations contains an empty label key")
                continue
            if not isinstance(raw, dict):
                err(f"locations.{lbl} must be an object with location_id/region_id")
                continue
            try:
                lid = int(raw.get("location_id", 0) or 0)
            except Exception:
                lid = 0
            if lid <= 0:
                err(f"locations.{lbl}.location_id must be a positive integer")
            if "region_id" in raw:
                try:
                    rid = int(raw.get("region_id", 0) or 0)
                except Exception:
                    rid = 0
                if rid <= 0:
                    err(f"locations.{lbl}.region_id must be a positive integer")

    structure_regions_cfg = cfg.get("structure_regions", {})
    if not isinstance(structure_regions_cfg, dict):
        err("structure_regions must be an object")
        structure_regions_cfg = {}
    for sk, rv in structure_regions_cfg.items():
        try:
            sid = int(sk)
        except Exception:
            sid = 0
        try:
            rid = int(rv)
        except Exception:
            rid = 0
        if sid <= 0:
            err(f"structure_regions key '{sk}' is not a valid positive structure id")
        if rid <= 0:
            err(f"structure_regions[{sk}] must be a valid positive region id")

    route_chain_cfg = cfg.get("route_chain", {})
    if isinstance(route_chain_cfg, dict):
        legs = route_chain_cfg.get("legs", None)
        if legs is not None and not isinstance(legs, list):
            err("route_chain.legs must be a list")
        if isinstance(legs, list):
            if bool(route_chain_cfg.get("enabled", False)) and len(legs) == 0:
                err("route_chain.legs cannot be empty when route_chain.enabled is true")
            seen_leg_ids = set()
            for i, leg in enumerate(legs):
                if not isinstance(leg, dict):
                    err(f"route_chain.legs[{i}] must be an object")
                    continue
                if "id" in leg:
                    try:
                        sid = int(leg.get("id", 0) or 0)
                    except Exception:
                        sid = 0
                    if sid <= 0:
                        err(f"route_chain.legs[{i}].id must be a positive integer")
                    else:
                        if sid in seen_leg_ids:
                            warn(f"duplicate route_chain leg id {sid}")
                        seen_leg_ids.add(sid)
                if "label" in leg and not isinstance(leg.get("label"), str):
                    err(f"route_chain.legs[{i}].label must be a string")
                if "system" in leg and not isinstance(leg.get("system"), str):
                    err(f"route_chain.legs[{i}].system must be a string")
                if "region_id" in leg:
                    try:
                        rid = int(leg.get("region_id", 0) or 0)
                    except Exception:
                        rid = 0
                    if rid <= 0:
                        err(f"route_chain.legs[{i}].region_id must be a positive integer")

    fees_cfg = cfg.get("fees", {})
    if isinstance(fees_cfg, dict):
        _check_non_negative("fees.sales_tax", fees_cfg.get("sales_tax", 0.0), plausible_max=0.2)
        _check_non_negative("fees.buy_broker_fee", fees_cfg.get("buy_broker_fee", 0.0), plausible_max=0.2)
        _check_non_negative("fees.sell_broker_fee", fees_cfg.get("sell_broker_fee", 0.0), plausible_max=0.2)
        _check_non_negative("fees.scc_surcharge", fees_cfg.get("scc_surcharge", fees_cfg.get("scc_surcharge_rate", 0.0)), plausible_max=0.2)
        _check_non_negative("fees.relist_budget_pct", fees_cfg.get("relist_budget_pct", 0.0), plausible_max=0.2)
        _check_non_negative("fees.relist_budget_isk", fees_cfg.get("relist_budget_isk", 0.0))
        skills_cfg = fees_cfg.get("skills", {})
        if skills_cfg is not None and not isinstance(skills_cfg, dict):
            err("fees.skills must be an object")
        elif isinstance(skills_cfg, dict):
            for skey in ("accounting", "broker_relations", "advanced_broker_relations"):
                if skey not in skills_cfg:
                    continue
                try:
                    lvl = int(skills_cfg.get(skey, 0))
                except Exception:
                    err(f"fees.skills.{skey} must be an integer in range [0..5]")
                    continue
                if lvl < 0 or lvl > 5:
                    err(f"fees.skills.{skey} must be in range [0..5]")
        for skey in ("accounting_level", "broker_relations_level", "advanced_broker_relations_level"):
            if skey not in fees_cfg:
                continue
            try:
                lvl = int(fees_cfg.get(skey, 0))
            except Exception:
                err(f"fees.{skey} must be an integer in range [0..5]")
                continue
            if lvl < 0 or lvl > 5:
                err(f"fees.{skey} must be in range [0..5]")
    else:
        err("fees must be an object")

    character_context_cfg = cfg.get("character_context", {})
    if character_context_cfg is not None and not isinstance(character_context_cfg, dict):
        err("character_context must be an object")
    elif isinstance(character_context_cfg, dict):
        for bkey in (
            "enabled",
            "allow_live_sync",
            "allow_cache_fallback",
            "apply_skill_fee_overrides",
            "include_skills",
            "include_skill_queue",
            "include_orders",
            "include_wallet_balance",
            "include_wallet_journal",
            "include_wallet_transactions",
            "show_order_exposure_in_output",
            "warn_if_budget_exceeds_wallet",
        ):
            if bkey in character_context_cfg and not isinstance(character_context_cfg.get(bkey), bool):
                err(f"character_context.{bkey} must be a boolean")
        for nkey in (
            "wallet_journal_max_pages",
            "wallet_transactions_max_pages",
            "wallet_warn_stale_after_sec",
            "profile_cache_ttl_sec",
        ):
            if nkey in character_context_cfg:
                try:
                    value = int(character_context_cfg.get(nkey, 0) or 0)
                except Exception:
                    value = -1
                if value < 0:
                    err(f"character_context.{nkey} must be a non-negative integer")
        for skey in ("profile_cache_path", "token_path", "metadata_path"):
            if skey in character_context_cfg and not isinstance(character_context_cfg.get(skey), str):
                err(f"character_context.{skey} must be a string")

    route_costs_cfg = cfg.get("route_costs", {})
    if route_costs_cfg is not None and not isinstance(route_costs_cfg, dict):
        err("route_costs must be an object")
    elif isinstance(route_costs_cfg, dict):
        for rid, rc in route_costs_cfg.items():
            if not isinstance(rc, dict):
                err(f"route_costs.{rid} must be an object")
                continue
            _check_non_negative(f"route_costs.{rid}.fixed_isk", rc.get("fixed_isk", 0.0))
            _check_non_negative(f"route_costs.{rid}.isk_per_m3", rc.get("isk_per_m3", 0.0))

    shipping_defaults_cfg = cfg.get("shipping_defaults", {})
    if shipping_defaults_cfg is not None and not isinstance(shipping_defaults_cfg, dict):
        err("shipping_defaults must be an object")
    elif isinstance(shipping_defaults_cfg, dict):
        _check_non_negative(
            "shipping_defaults.collateral_buffer_pct",
            shipping_defaults_cfg.get("collateral_buffer_pct", 0.0),
            plausible_max=5.0
        )

    lanes_cfg = cfg.get("shipping_lanes", {})
    if lanes_cfg is not None and not isinstance(lanes_cfg, dict):
        err("shipping_lanes must be an object")
    elif isinstance(lanes_cfg, dict):
        for lid, lane in lanes_cfg.items():
            if not isinstance(lane, dict):
                err(f"shipping_lanes.{lid} must be an object")
                continue
            if "enabled" in lane and not isinstance(lane.get("enabled"), bool):
                err(f"shipping_lanes.{lid}.enabled must be a boolean")
            if (
                not str(lane.get("from", "")).strip()
                and int(lane.get("from_structure_id", 0) or 0) <= 0
                and int(lane.get("from_location_id", 0) or 0) <= 0
            ):
                warn(f"shipping_lanes.{lid}.from is empty (label or *_id required)")
            if (
                not str(lane.get("to", "")).strip()
                and int(lane.get("to_structure_id", 0) or 0) <= 0
                and int(lane.get("to_location_id", 0) or 0) <= 0
            ):
                warn(f"shipping_lanes.{lid}.to is empty (label or *_id required)")
            for ikey in ("from_structure_id", "to_structure_id", "from_location_id", "to_location_id"):
                if ikey in lane:
                    try:
                        iv = int(lane.get(ikey, 0) or 0)
                    except Exception:
                        iv = 0
                    if iv < 0:
                        err(f"shipping_lanes.{lid}.{ikey} must be non-negative")
            for nkey in ("per_m3_rate", "full_load_reward", "minimum_reward", "collateral_rate", "full_load_flat_rate", "min_reward"):
                if nkey in lane and lane.get(nkey) is not None:
                    _check_non_negative(f"shipping_lanes.{lid}.{nkey}", lane.get(nkey))
            for nkey in ("additional_collateral_rate", "max_volume_per_contract_m3", "max_collateral_per_contract_isk", "max_value"):
                if nkey in lane and lane.get(nkey) is not None:
                    _check_non_negative(f"shipping_lanes.{lid}.{nkey}", lane.get(nkey))
            if "pricing_model" in lane:
                model = str(lane.get("pricing_model", "")).strip().lower()
                if model not in ("itl_max", "hwl_volume_plus_value"):
                    err(f"shipping_lanes.{lid}.pricing_model must be one of: itl_max, hwl_volume_plus_value")
            if "frequency" in lane and not isinstance(lane.get("frequency"), str):
                err(f"shipping_lanes.{lid}.frequency must be a string")

    route_search_cfg = cfg.get("route_search", {})
    zero_transport_allow = cfg.get("allow_zero_transport_cost_for_routes", [])
    if zero_transport_allow is not None and not isinstance(zero_transport_allow, list):
        err("allow_zero_transport_cost_for_routes must be a list")
    if route_search_cfg is not None and not isinstance(route_search_cfg, dict):
        err("route_search must be an object")
    elif isinstance(route_search_cfg, dict):
        if "enabled" in route_search_cfg and not isinstance(route_search_cfg.get("enabled"), bool):
            err("route_search.enabled must be a boolean")
        if "allow_all_structures_internal" in route_search_cfg and not isinstance(route_search_cfg.get("allow_all_structures_internal"), bool):
            err("route_search.allow_all_structures_internal must be a boolean")
        if "allow_shipping_lanes" in route_search_cfg and not isinstance(route_search_cfg.get("allow_shipping_lanes"), bool):
            err("route_search.allow_shipping_lanes must be a boolean")
        if "max_routes" in route_search_cfg:
            try:
                if int(route_search_cfg.get("max_routes", 0) or 0) <= 0:
                    err("route_search.max_routes must be a positive integer")
            except Exception:
                err("route_search.max_routes must be a positive integer")
        if "allowed_pairs" in route_search_cfg and not isinstance(route_search_cfg.get("allowed_pairs"), list):
            err("route_search.allowed_pairs must be a list")
        if (
            "allow_zero_transport_cost_for_routes" in route_search_cfg
            and not isinstance(route_search_cfg.get("allow_zero_transport_cost_for_routes"), list)
        ):
            err("route_search.allow_zero_transport_cost_for_routes must be a list")

    confidence_calibration_cfg = cfg.get("confidence_calibration", {})
    if confidence_calibration_cfg is not None and not isinstance(confidence_calibration_cfg, dict):
        err("confidence_calibration must be an object")
    elif isinstance(confidence_calibration_cfg, dict):
        for bkey in ("enabled", "apply_to_decisions", "scope_fallback_to_global"):
            if bkey in confidence_calibration_cfg and not isinstance(confidence_calibration_cfg.get(bkey), bool):
                err(f"confidence_calibration.{bkey} must be a boolean")
        for nkey in (
            "min_samples",
            "min_samples_per_bucket",
            "profit_close_ratio",
            "profit_close_tolerance_isk",
            "open_position_horizon_factor",
            "stale_open_position_days",
            "optimism_gap_warn",
        ):
            if nkey in confidence_calibration_cfg and (not _is_num(confidence_calibration_cfg.get(nkey)) or float(confidence_calibration_cfg.get(nkey)) < 0):
                err(f"confidence_calibration.{nkey} must be a non-negative number")
        if "scope" in confidence_calibration_cfg:
            scope = str(confidence_calibration_cfg.get("scope", "")).strip().lower()
            if scope not in ("global", "target_market", "route_id", "market_pair", "exit_type"):
                err("confidence_calibration.scope must be one of: global, target_market, route_id, market_pair, exit_type")
        if "buckets" in confidence_calibration_cfg:
            buckets = confidence_calibration_cfg.get("buckets")
            if not isinstance(buckets, list) or not buckets:
                err("confidence_calibration.buckets must be a non-empty list")
            else:
                previous = 0.0
                for idx, raw_value in enumerate(buckets):
                    if not _is_num(raw_value):
                        err(f"confidence_calibration.buckets[{idx}] must be numeric")
                        continue
                    value = float(raw_value)
                    if value <= 0.0 or value > 1.0:
                        err(f"confidence_calibration.buckets[{idx}] must be in range (0..1]")
                        continue
                    if value <= previous:
                        err("confidence_calibration.buckets must be strictly increasing")
                    previous = value

    market_plausibility_cfg = cfg.get("market_plausibility", {})
    if market_plausibility_cfg is not None and not isinstance(market_plausibility_cfg, dict):
        err("market_plausibility must be an object")
    elif isinstance(market_plausibility_cfg, dict):
        for bkey in ("enabled", "hard_reject_on_unusable_depth", "hard_reject_on_extreme_reference_deviation"):
            if bkey in market_plausibility_cfg and not isinstance(market_plausibility_cfg.get(bkey), bool):
                err(f"market_plausibility.{bkey} must be a boolean")
        for nkey in (
            "visible_levels",
            "min_usable_units",
            "min_usable_ratio",
            "thin_top_of_book_ratio",
            "price_gap_after_top_levels_pct",
            "depth_decay_floor",
            "order_concentration_ratio",
            "extreme_reference_deviation",
            "fake_spread_profit_ratio",
            "hard_reject_manipulation_risk",
            "warn_manipulation_risk",
            "reference_soft_cap_markup",
        ):
            if nkey in market_plausibility_cfg and (not _is_num(market_plausibility_cfg.get(nkey)) or float(market_plausibility_cfg.get(nkey)) < 0):
                err(f"market_plausibility.{nkey} must be a non-negative number")

    allowed_modes = {"instant", "fast_sell", "planned_sell"}
    for fkey in ("filters_forward", "filters_return"):
        fcfg = cfg.get(fkey, {})
        if not isinstance(fcfg, dict):
            err(f"{fkey} must be an object")
            continue
        if "mode" in fcfg:
            mode = str(fcfg.get("mode", "")).lower()
            if mode not in allowed_modes:
                err(f"{fkey}.mode must be one of: instant, fast_sell, planned_sell")
        for nkey in ("horizon_days", "order_duration_days", "min_market_history_order_count", "min_depth_within_2pct_sell", "max_competition_density_near_best"):
            if nkey in fcfg:
                if not _is_num(fcfg.get(nkey)):
                    err(f"{fkey}.{nkey} must be numeric")
                elif float(fcfg.get(nkey)) < 0:
                    err(f"{fkey}.{nkey} must be non-negative")
        if "fallback_require_high_profit_pct" in fcfg:
            if not _is_num(fcfg.get("fallback_require_high_profit_pct")) or float(fcfg.get("fallback_require_high_profit_pct")) < 0:
                err(f"{fkey}.fallback_require_high_profit_pct must be non-negative")
        if "strict_mode" in fcfg:
            scfg = fcfg.get("strict_mode")
            if not isinstance(scfg, dict):
                err(f"{fkey}.strict_mode must be an object")
            elif "enabled" in scfg and not isinstance(scfg.get("enabled"), bool):
                err(f"{fkey}.strict_mode.enabled must be a boolean")

    resolved_map = _resolve_structure_region_map(cfg, emit_info=False)
    required_ids = _collect_required_structure_ids(cfg, None)
    for sid in sorted(structure_regions_cfg.keys()):
        try:
            sid_i = int(sid)
        except Exception:
            continue
        if sid_i > 0 and sid_i not in required_ids:
            warn(f"structure_regions contains unused structure_id {sid_i}")
    planned_mode_active = (
        str(cfg.get("forward_mode", "")).lower() in ("planned_sell", "instant_first")
        or str((cfg.get("filters_forward", {}) if isinstance(cfg.get("filters_forward", {}), dict) else {}).get("mode", "")).lower() == "planned_sell"
        or str((cfg.get("filters_return", {}) if isinstance(cfg.get("filters_return", {}), dict) else {}).get("mode", "")).lower() == "planned_sell"
    )
    with io.StringIO() as buf:
        try:
            with redirect_stdout(buf):
                _ = _validate_structure_region_mapping(
                    cfg=cfg,
                    structure_region_map=resolved_map,
                    required_structure_ids=required_ids,
                    planned_mode_active=planned_mode_active,
                )
        except SystemExit as e:
            err(str(e))
        out = str(buf.getvalue() or "").splitlines()
        for line in out:
            line_s = str(line).strip()
            if line_s.startswith("WARN:"):
                warn(line_s[5:].strip())

    result["issues"] = _build_validation_issues(result["errors"], result["warnings"])
    return result


def fail_on_invalid_config(validation_result: dict) -> None:
    errors = list(validation_result.get("errors", []))
    issues = list(validation_result.get("issues", []))
    if not issues:
        for w in list(validation_result.get("warnings", [])):
            issues.append({"level": "WARNING", "code": "VALIDATION_GENERIC", "path": "", "message": str(w), "context": {}})
        for e in errors:
            issues.append({"level": "ERROR", "code": "VALIDATION_GENERIC", "path": "", "message": str(e), "context": {}})
    cfg = validation_result.get("cfg", {})
    for issue in issues:
        lvl = str(issue.get("level", "WARNING")).upper()
        msg = str(issue.get("message", ""))
        prefix = "CONFIG ERROR" if lvl == "ERROR" else "CONFIG WARNING"
        print(f"{prefix}: {msg}")
        fix = _build_fix_hint(issue, cfg if isinstance(cfg, dict) else {})
        if fix:
            print(f"  FIX: {fix}")
    if errors:
        raise SystemExit(f"Config validation failed with {len(errors)} error(s). See messages above.")


def _prepare_trade_filters(cfg: dict) -> tuple[dict, dict, str, str]:
    from candidate_engine import apply_strategy_filters

    def _normalize_int_list(values) -> list[int]:
        out = []
        if not isinstance(values, list):
            return out
        seen = set()
        for v in values:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv in seen:
                continue
            seen.add(iv)
            out.append(iv)
        return out

    def _normalize_kw_list(values) -> list[str]:
        out = []
        if not isinstance(values, list):
            return out
        seen = set()
        for v in values:
            s = str(v).strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    forward_filters = apply_strategy_filters(cfg, cfg["filters_forward"])
    return_filters = apply_strategy_filters(cfg, cfg["filters_return"])
    reference_price_cfg = cfg.get("reference_price", {})
    if isinstance(reference_price_cfg, dict):
        forward_filters["reference_price"] = dict(reference_price_cfg)
        return_filters["reference_price"] = dict(reference_price_cfg)
    market_plausibility_cfg = cfg.get("market_plausibility", {})
    if isinstance(market_plausibility_cfg, dict):
        forward_filters["market_plausibility"] = dict(market_plausibility_cfg)
        return_filters["market_plausibility"] = dict(market_plausibility_cfg)

    global_excludes = cfg.get("global_excludes", {})
    global_type_ids = []
    global_name_keywords = []
    if isinstance(global_excludes, dict):
        global_type_ids.extend(_normalize_int_list(global_excludes.get("type_ids", [])))
        global_name_keywords.extend(_normalize_kw_list(global_excludes.get("name_keywords", [])))
    global_type_ids.extend(_normalize_int_list(cfg.get("exclude_type_ids", [])))
    global_name_keywords.extend(_normalize_kw_list(cfg.get("exclude_name_keywords", [])))

    def _apply_global_excludes(filters: dict) -> None:
        existing_ids = _normalize_int_list(filters.get("exclude_type_ids", []))
        merged_ids = []
        seen_ids = set()
        for tid in existing_ids + global_type_ids:
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            merged_ids.append(tid)
        filters["exclude_type_ids"] = merged_ids

        existing_kw = _normalize_kw_list(filters.get("exclude_name_keywords", []))
        legacy_kw = _normalize_kw_list(filters.get("exclude_keywords", []))
        merged_kw = []
        seen_kw = set()
        for kw in existing_kw + legacy_kw + global_name_keywords:
            if kw in seen_kw:
                continue
            seen_kw.add(kw)
            merged_kw.append(kw)
        filters["exclude_name_keywords"] = merged_kw
        filters["exclude_keywords"] = merged_kw

    _apply_global_excludes(forward_filters)
    _apply_global_excludes(return_filters)

    strict_cfg = _resolve_strict_mode_cfg(cfg)
    strict_enabled = bool(strict_cfg.get("enabled", False))
    if strict_enabled:
        forward_filters["strict_mode"] = dict(strict_cfg)
        return_filters["strict_mode"] = dict(strict_cfg)
        forward_filters["strict_mode_enabled"] = True
        return_filters["strict_mode_enabled"] = True
        strict_force_instant_first = bool(strict_cfg.get("prefer_instant_first", True))
    else:
        strict_force_instant_first = False
        forward_filters["min_profit_pct"] = max(
            float(forward_filters.get("min_profit_pct", 0.0)),
            float(strict_cfg.get("instant_min_profit_pct", 0.03))
        )
        forward_filters["min_profit_isk_total"] = max(
            float(forward_filters.get("min_profit_isk_total", 0.0)),
            float(strict_cfg.get("instant_min_profit_isk_total", 1_000_000.0))
        )
        forward_filters["min_fill_probability"] = max(
            float(forward_filters.get("min_fill_probability", 0.0)),
            float(strict_cfg.get("instant_min_fill_probability", 0.90))
        )
        forward_filters["min_depth_units"] = max(
            int(forward_filters.get("min_depth_units", 0)),
            int(strict_cfg.get("instant_min_depth_units", 3))
        )

    forward_mode = str(cfg.get("forward_mode", forward_filters.get("mode", "instant"))).lower()
    if strict_force_instant_first:
        forward_mode = "instant_first"
    if forward_mode in ("planned_sell", "instant_first"):
        planned_cfg = cfg.get("planned_sell", {})
        if isinstance(planned_cfg, dict):
            if "horizon_days" in planned_cfg and "horizon_days" not in forward_filters:
                forward_filters["horizon_days"] = planned_cfg["horizon_days"]
            if "history_days" in planned_cfg and "history_days" not in forward_filters:
                forward_filters["history_days"] = planned_cfg["history_days"]
        ps_filters = cfg.get("filters_planned_sell_forward", {})
        if isinstance(ps_filters, dict):
            forward_filters.update(ps_filters)
        if strict_enabled:
            forward_filters["min_avg_daily_volume"] = max(
                float(forward_filters.get("min_avg_daily_volume", 0.0)),
                float(strict_cfg.get("planned_min_avg_daily_volume_30d", 0.25))
            )
            forward_filters["min_sell_through_ratio_90d"] = max(
                float(forward_filters.get("min_sell_through_ratio_90d", 0.0)),
                float(strict_cfg.get("planned_min_sell_through_ratio_90d", 0.70))
            )
            forward_filters["max_expected_days_to_sell"] = min(
                float(forward_filters.get("max_expected_days_to_sell", 99999.0)),
                float(strict_cfg.get("planned_max_expected_days_to_sell", 45.0))
            )
            forward_filters["min_expected_profit_isk"] = max(
                float(forward_filters.get("min_expected_profit_isk", 0.0)),
                float(strict_cfg.get("planned_profit_floor_isk", 2_000_000.0))
            )
            forward_filters["strict_require_avg_daily_volume_7d"] = float(strict_cfg.get("planned_min_avg_daily_volume_7d", 0.15))
            forward_filters["strict_disable_fallback_volume_for_planned"] = bool(strict_cfg.get("disable_fallback_volume_for_planned", True))
            forward_filters["strict_require_reference_price_for_planned"] = bool(strict_cfg.get("require_reference_price_for_planned", True))
            forward_filters["strict_planned_max_units_cap"] = int(strict_cfg.get("planned_max_units_cap", 3))
            rp = dict(forward_filters.get("reference_price", {}))
            rp["soft_sell_markup_vs_ref_planned"] = float(strict_cfg.get("planned_soft_sell_markup_vs_ref", 0.20))
            rp["max_sell_markup_vs_ref_planned"] = float(strict_cfg.get("planned_max_sell_markup_vs_ref", 0.40))
            rp["hard_max_sell_markup_vs_ref_planned"] = float(strict_cfg.get("planned_hard_max_sell_markup_vs_ref", 0.80))
            rp["ranking_penalty_strength"] = float(strict_cfg.get("planned_reference_penalty_strength", 0.60))
            forward_filters["reference_price"] = rp
        if forward_mode == "planned_sell":
            forward_filters["mode"] = "planned_sell"
        else:
            forward_filters["mode"] = "instant_first"
    else:
        forward_filters["mode"] = forward_mode
    region_map = _resolve_structure_region_map(cfg)
    if region_map:
        forward_filters["structure_region_map"] = dict(region_map)
        return_filters["structure_region_map"] = dict(region_map)

    relist_budget_pct = float(cfg.get("fees", {}).get("relist_budget_pct", 0.0) or 0.0)
    relist_budget_isk = float(cfg.get("fees", {}).get("relist_budget_isk", 0.0) or 0.0)
    forward_filters["relist_budget_pct"] = relist_budget_pct
    forward_filters["relist_budget_isk"] = relist_budget_isk
    return_filters["relist_budget_pct"] = relist_budget_pct
    return_filters["relist_budget_isk"] = relist_budget_isk
    return_mode = str(return_filters.get("mode", "instant")).lower()
    return forward_filters, return_filters, forward_mode, return_mode
