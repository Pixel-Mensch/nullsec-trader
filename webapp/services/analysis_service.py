from __future__ import annotations

import base64
import json
import os

from risk_profiles import BUILTIN_PROFILES, DEFAULT_PROFILE
from runtime_common import TOKEN_PATH, parse_isk

from config_loader import load_config, validate_config
from webapp.services.runtime_bridge import extract_personal_layer_lines, invoke_runtime


def _market_auth_info() -> dict:
    """Read the current market-auth JWT and return the character name and token status."""
    try:
        if not os.path.exists(TOKEN_PATH):
            return {"character_name": "", "token_path": TOKEN_PATH, "has_token": False}
        with open(TOKEN_PATH, encoding="utf-8") as fh:
            tok = json.load(fh)
        access_token = str(tok.get("access_token", "") or "")
        parts = access_token.split(".")
        if len(parts) < 2:
            return {"character_name": "", "token_path": TOKEN_PATH, "has_token": bool(access_token)}
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return {
            "character_name": str(payload.get("name", "") or ""),
            "token_path": TOKEN_PATH,
            "has_token": True,
        }
    except Exception:
        return {"character_name": "", "token_path": TOKEN_PATH, "has_token": False}


def _route_cards(manifest: dict) -> list[dict]:
    cards: list[dict] = []
    for route in list((manifest or {}).get("routes", []) or []):
        if not isinstance(route, dict):
            continue
        picks = [pick for pick in list(route.get("picks", []) or []) if isinstance(pick, dict)]
        display = dict(route.get("display", {}) or {}) if isinstance(route.get("display", {}), dict) else {}
        expected_total = float(route.get("expected_realized_profit_total", 0.0) or 0.0)
        if expected_total <= 0.0:
            expected_total = sum(float(pick.get("proposed_expected_profit", 0.0) or 0.0) for pick in picks)
        full_total = float(route.get("full_sell_profit_total", 0.0) or 0.0)
        if full_total <= 0.0:
            full_total = sum(float(pick.get("proposed_full_sell_profit", 0.0) or 0.0) for pick in picks)
        cards.append(
            {
                "route_id": str(route.get("route_id", "") or ""),
                "route_label": str(route.get("route_label", "") or ""),
                "actionable": bool(route.get("actionable", False)),
                "route_confidence": float(route.get("route_confidence", 0.0) or 0.0),
                "transport_confidence": float(route.get("transport_confidence", 0.0) or 0.0),
                "capital_lock_risk": float(route.get("capital_lock_risk", 0.0) or 0.0),
                "calibration_warning": str(route.get("calibration_warning", "") or ""),
                "route_prune_reason": str(route.get("route_prune_reason", "") or ""),
                "cost_model_confidence": str(route.get("cost_model_confidence", "normal") or "normal"),
                "cost_model_warning": str(route.get("cost_model_warning", "") or ""),
                "pick_count": int(route.get("items_count", len(picks)) or len(picks)),
                "isk_used": float(route.get("isk_used", 0.0) or 0.0),
                "budget_total": float(route.get("budget_total", 0.0) or 0.0),
                "budget_util_pct": float(route.get("budget_util_pct", 0.0) or 0.0),
                "m3_used": float(route.get("m3_used", 0.0) or 0.0),
                "cargo_total": float(route.get("cargo_total", 0.0) or 0.0),
                "cargo_util_pct": float(route.get("cargo_util_pct", 0.0) or 0.0),
                "net_revenue_total": float(route.get("net_revenue_total", 0.0) or 0.0),
                "total_fees_taxes": float(route.get("total_fees_taxes", 0.0) or 0.0),
                "total_transport_cost": float(route.get("total_transport_cost", 0.0) or 0.0),
                "shipping_cost_total": float(route.get("shipping_cost_total", 0.0) or 0.0),
                "expected_profit_total": expected_total,
                "full_sell_profit_total": full_total,
                "warnings": [str(item).strip() for item in list(route.get("warnings", []) or []) if str(item).strip()],
                "display": display,
                "route_logic_label": str(display.get("logic_label", "") or ""),
                "picks": picks,
            }
        )
    indexed = list(enumerate(cards))
    indexed.sort(
        key=lambda entry: (
            int(entry[1].get("display", {}).get("section_order", 9999) or 9999),
            int(entry[1].get("display", {}).get("item_order", 9999) or 9999),
            0 if bool(entry[1].get("actionable", False)) else 1,
            -float(entry[1].get("expected_profit_total", 0.0) or 0.0),
            entry[0],
        )
    )
    return [card for _, card in indexed]


def _route_sections(route_cards: list[dict]) -> list[dict]:
    sections: list[dict] = []
    current_section: dict | None = None
    for card in list(route_cards or []):
        display = dict(card.get("display", {}) or {}) if isinstance(card.get("display", {}), dict) else {}
        section_key = str(display.get("section_key", "") or "")
        section_label = str(display.get("section_label", "") or "").strip()
        section_note = str(display.get("section_note", "") or "").strip()
        if not section_key or not section_label:
            section_key = "routes"
            section_label = "Routes"
            section_note = ""
        if current_section is None or str(current_section.get("key", "")) != section_key:
            current_section = {"key": section_key, "label": section_label, "note": section_note, "routes": []}
            sections.append(current_section)
        current_section["routes"].append(card)
    return sections


def get_analysis_form_data() -> dict:
    cfg = load_config()
    validation = validate_config(cfg)
    defaults = dict(cfg.get("defaults", {}) or {})
    replay_cfg = dict(cfg.get("replay", {}) or {})
    return {
        "config": cfg,
        "config_valid": not bool(validation.get("errors", [])),
        "config_errors": list(validation.get("errors", []) or []),
        "defaults": defaults,
        "replay_enabled": bool(replay_cfg.get("enabled", False)),
        "risk_profiles": [
            {"name": name, "description": str((spec or {}).get("description", "") or "")}
            for name, spec in BUILTIN_PROFILES.items()
        ],
        "route_mode": str(cfg.get("route_mode", "roundtrip") or "roundtrip"),
        "default_profile_name": DEFAULT_PROFILE,
        "market_auth": _market_auth_info(),
    }


def run_analysis(
    *,
    budget_isk_raw: str,
    cargo_m3_raw: str,
    snapshot_only: bool,
    use_replay: bool,
    risk_profile: str,
) -> dict:
    cfg = load_config()
    validation = validate_config(cfg)
    if validation.get("errors"):
        return {
            "ok": False,
            "error": "Konfiguration ist ungueltig.",
            "details": list(validation.get("errors", []) or []),
            "form": get_analysis_form_data(),
        }
    argv = []
    if snapshot_only:
        argv.append("--snapshot-only")
    if cargo_m3_raw:
        try:
            argv.extend(["--cargo-m3", str(float(cargo_m3_raw))])
        except (ValueError, TypeError):
            return {
                "ok": False,
                "error": f"Ungueltige Cargo-Angabe: '{cargo_m3_raw}'. Bitte eine Zahl eingeben (z.B. 10000).",
                "form": get_analysis_form_data(),
            }
    if budget_isk_raw:
        try:
            argv.extend(["--budget-isk", str(parse_isk(str(budget_isk_raw)))])
        except (ValueError, TypeError):
            return {
                "ok": False,
                "error": f"Ungueltige Budget-Angabe: '{budget_isk_raw}'. Bitte eine Zahl eingeben (z.B. 500m oder 500000000).",
                "form": get_analysis_form_data(),
            }
    profile_name = str(risk_profile or "").strip().lower()
    if profile_name:
        argv.extend(["--profile", profile_name])
    replay_override = "1" if bool(use_replay) else "0"
    runtime_result = invoke_runtime(argv, env_overrides={"NULLSEC_REPLAY_ENABLED": replay_override})
    text_files = dict(runtime_result.get("text_files", {}) or {})
    execution_plan_text = ""
    no_trade_text = ""
    summary_text = ""
    leaderboard_text = ""
    for name, content in text_files.items():
        if name.startswith("execution_plan_"):
            execution_plan_text = content
        elif name.startswith("no_trade_"):
            no_trade_text = content
        elif name.startswith("roundtrip_plan_"):
            summary_text = content
        elif name.startswith("route_leaderboard_"):
            leaderboard_text = content
    manifest = dict(runtime_result.get("manifest", {}) or {})
    route_cards = _route_cards(manifest)
    route_sections = _route_sections(route_cards)
    personal_layer_lines = extract_personal_layer_lines(execution_plan_text or runtime_result.get("stdout", ""))
    return {
        "ok": bool(runtime_result.get("ok", False)),
        "error": str(runtime_result.get("error", "") or "").strip(),
        "exit_code": int(runtime_result.get("exit_code", 0) or 0),
        "stdout": str(runtime_result.get("stdout", "") or ""),
        "plan_id": str(runtime_result.get("plan_id", "") or ""),
        "created_files": list(runtime_result.get("created_files", []) or []),
        "snapshot_path": str(runtime_result.get("snapshot_path", "") or ""),
        "manifest": manifest,
        "runtime_mode": str(manifest.get("runtime_mode", "snapshot_only" if snapshot_only else "") or ""),
        "route_cards": route_cards,
        "route_sections": route_sections,
        "route_count": int(manifest.get("route_count", len(route_cards)) or len(route_cards)),
        "pick_count": int(manifest.get("pick_count", sum(len(route.get("picks", [])) for route in route_cards)) or 0),
        "actionable_route_count": sum(1 for route in route_cards if bool(route.get("actionable", False))),
        "execution_plan_text": execution_plan_text,
        "leaderboard_text": leaderboard_text,
        "summary_text": summary_text,
        "no_trade_text": no_trade_text,
        "personal_layer_lines": personal_layer_lines,
        "form": get_analysis_form_data(),
        "selected_profile": profile_name or str((cfg.get("risk_profile", {}) or {}).get("name", "balanced")),
        "used_replay": bool(use_replay),
    }

