"""Config tests."""

import io
import json
import os
import tempfile
from contextlib import redirect_stdout

import nullsectrader as nst

from tests.shared import _minimal_valid_config

def test_validate_config_accepts_minimal_valid_config() -> None:
    cfg = _minimal_valid_config()
    vr = nst.validate_config(cfg)
    assert vr.get("errors", []) == []

def test_validate_config_rejects_negative_fees() -> None:
    cfg = _minimal_valid_config()
    cfg["fees"]["sales_tax"] = -0.1
    vr = nst.validate_config(cfg)
    assert any("fees.sales_tax" in str(e) for e in vr.get("errors", []))

def test_validate_config_rejects_invalid_structure_id() -> None:
    cfg = _minimal_valid_config()
    cfg["structures"]["o4t"] = "abc"
    vr = nst.validate_config(cfg)
    assert any("structures.o4t has invalid structure id" in str(e) for e in vr.get("errors", []))

def test_validate_config_warns_on_client_secret_in_config() -> None:
    cfg = _minimal_valid_config()
    cfg["esi"]["client_secret"] = "secret"
    vr = nst.validate_config(cfg)
    assert any("client_secret is stored in config.json" in str(w) for w in vr.get("warnings", []))

def test_validate_config_does_not_warn_when_secret_is_env_injected() -> None:
    cfg = _minimal_valid_config()
    cfg["esi"]["client_secret"] = "secret-from-env"
    cfg["_runtime_meta"] = {"client_secret_from_env": True, "client_secret_source": "env"}
    vr = nst.validate_config(cfg)
    assert any("client_secret is provided via ENV" in str(w) for w in vr.get("warnings", []))
    assert not any("client_secret is stored in config.json" in str(w) for w in vr.get("warnings", []))

def test_validate_config_warns_when_secret_comes_from_local_config() -> None:
    cfg = _minimal_valid_config()
    cfg["esi"]["client_secret"] = "local-secret"
    cfg["_runtime_meta"] = {"client_secret_source": "config.local.json", "client_secret_from_local_config": True}
    vr = nst.validate_config(cfg)
    assert any("client_secret is loaded from config.local.json" in str(w) for w in vr.get("warnings", []))

def test_load_config_merges_local_overlay_and_env_overrides() -> None:
    base_cfg = _minimal_valid_config()
    base_cfg["esi"]["client_id"] = "base-id"
    base_cfg["esi"]["client_secret"] = "base-secret"
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, "config.json")
        local_cfg_path = os.path.join(tmpdir, "config.local.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(base_cfg, f, ensure_ascii=False, indent=2)
        with open(local_cfg_path, "w", encoding="utf-8") as f:
            json.dump({"esi": {"client_id": "local-id", "client_secret": "local-secret"}}, f, ensure_ascii=False, indent=2)

        old_env = {
            "ESI_CLIENT_ID": os.environ.get("ESI_CLIENT_ID"),
            "ESI_CLIENT_SECRET": os.environ.get("ESI_CLIENT_SECRET"),
            "NULLSEC_LOCAL_CONFIG": os.environ.get("NULLSEC_LOCAL_CONFIG"),
            "NULLSEC_REPLAY_ENABLED": os.environ.get("NULLSEC_REPLAY_ENABLED"),
        }
        try:
            os.environ["NULLSEC_LOCAL_CONFIG"] = local_cfg_path
            os.environ["ESI_CLIENT_ID"] = "env-id"
            os.environ["ESI_CLIENT_SECRET"] = "env-secret"
            os.environ["NULLSEC_REPLAY_ENABLED"] = "1"
            loaded = nst.load_config(cfg_path)
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    assert str(loaded["esi"]["client_id"]) == "env-id"
    assert str(loaded["esi"]["client_secret"]) == "env-secret"
    assert bool(loaded["replay"]["enabled"]) is True
    runtime_meta = loaded.get("_runtime_meta", {})
    assert bool(runtime_meta.get("client_secret_from_env", False)) is True
    assert str(runtime_meta.get("client_secret_source", "")) == "env"

def test_parse_cli_args_supports_non_interactive_budget_and_cargo() -> None:
    args = nst.parse_cli_args(["--detail", "--cargo-m3", "12345.6", "--budget-isk", "750m"])
    assert bool(args.get("detail", False)) is True
    assert abs(float(args.get("cargo_m3", 0.0)) - 12345.6) < 1e-9
    assert int(args.get("budget_isk", 0) or 0) == 750_000_000

def test_collect_required_structure_ids_ignores_disabled_chain_legs() -> None:
    cfg = {
        "structures": {"o4t": 1, "cj6": 2},
        "route_chain": {
            "enabled": False,
            "legs": [{"id": 3, "label": "middle"}],
        },
    }
    out = nst._collect_required_structure_ids(cfg, None)
    assert out == {1, 2}

def test_validate_config_rejects_invalid_mode() -> None:
    cfg = _minimal_valid_config()
    cfg["filters_forward"]["mode"] = "invalid_mode"
    vr = nst.validate_config(cfg)
    assert any("filters_forward.mode must be one of" in str(e) for e in vr.get("errors", []))


def test_validate_config_rejects_negative_internal_self_haul_profit_floor() -> None:
    cfg = _minimal_valid_config()
    cfg["route_search"] = {"internal_self_haul_min_expected_profit_isk": -1}
    vr = nst.validate_config(cfg)
    assert any("route_search.internal_self_haul_min_expected_profit_isk" in str(e) for e in vr.get("errors", []))


def test_validate_config_rejects_invalid_ansiblex_toll_mode() -> None:
    cfg = _minimal_valid_config()
    cfg["ansiblex"] = {"enabled": True, "toll_mode": "weird_mode"}
    vr = nst.validate_config(cfg)
    assert any("ansiblex.toll_mode" in str(e) for e in vr.get("errors", []))

def test_validate_config_rejects_invalid_structure_regions() -> None:
    cfg = _minimal_valid_config()
    cfg["structure_regions"] = {"bad": 10000059, "1040804972352": -1}
    vr = nst.validate_config(cfg)
    assert any("structure_regions key 'bad'" in str(e) for e in vr.get("errors", []))
    assert any("structure_regions[1040804972352]" in str(e) for e in vr.get("errors", []))

def test_validate_config_warns_on_unused_structure_region() -> None:
    cfg = _minimal_valid_config()
    cfg["structure_regions"]["999999999999"] = 10000009
    vr = nst.validate_config(cfg)
    assert any("unused structure_id 999999999999" in str(w) for w in vr.get("warnings", []))

def test_validate_config_strict_region_mapping_turns_missing_mapping_into_error() -> None:
    cfg = _minimal_valid_config()
    cfg["esi"]["strict_region_mapping"] = True
    cfg["structure_regions"] = {"1040804972352": 10000059}
    vr = nst.validate_config(cfg)
    assert any("Strict region mapping aktiv" in str(e) for e in vr.get("errors", []))

def test_fix_hint_for_negative_fee_contains_json_snippet() -> None:
    cfg = _minimal_valid_config()
    cfg["fees"]["sales_tax"] = -1
    vr = nst.validate_config(cfg)
    issues = [i for i in vr.get("issues", []) if str(i.get("code")) in ("FEES_NEGATIVE", "FEES_NOT_NUMBER", "FEES_IMPLAUSIBLE")]
    assert issues, "expected fee issue"
    hint = nst._build_fix_hint(issues[0], cfg) or ""
    assert "fees" in hint.lower()
    assert "sales_tax" in hint

def test_fix_hint_for_missing_region_mapping_mentions_structure_regions() -> None:
    cfg = _minimal_valid_config()
    cfg["esi"]["strict_region_mapping"] = True
    cfg["structure_regions"] = {"1040804972352": 10000059}
    vr = nst.validate_config(cfg)
    issues = [i for i in vr.get("issues", []) if str(i.get("code")) == "REGION_MAPPING_MISSING"]
    assert issues, "expected region mapping issue"
    hint = nst._build_fix_hint(issues[0], cfg) or ""
    assert "structure_regions" in hint

def test_fix_hint_for_invalid_mode_lists_allowed_modes() -> None:
    cfg = _minimal_valid_config()
    cfg["filters_forward"]["mode"] = "wrong"
    vr = nst.validate_config(cfg)
    issues = [i for i in vr.get("issues", []) if str(i.get("code")) == "MODE_INVALID"]
    assert issues, "expected mode issue"
    hint = nst._build_fix_hint(issues[0], cfg) or ""
    assert "instant" in hint and "fast_sell" in hint and "planned_sell" in hint

def test_fix_hint_for_secret_in_config_is_warning_and_mentions_env() -> None:
    cfg = _minimal_valid_config()
    cfg["esi"]["client_secret"] = "secret"
    vr = nst.validate_config(cfg)
    issues = [i for i in vr.get("issues", []) if str(i.get("code")) == "SECURITY_SECRET_IN_CONFIG"]
    assert issues, "expected secret warning issue"
    assert str(issues[0].get("level", "")).upper() == "WARNING"
    hint = nst._build_fix_hint(issues[0], cfg) or ""
    assert "ESI_CLIENT_SECRET" in hint

def test_strict_region_mapping_runs_after_autofill() -> None:
    cfg_ok = {
        "esi": {"strict_region_mapping": True, "auto_fill_structure_regions": True},
        "structures": {"o4t": 1040804972352, "cj6": 1049588174021},
        "structure_regions": {},
    }
    mapping_ok = nst._resolve_structure_region_map(cfg_ok)
    required_ok = nst._collect_required_structure_ids(cfg_ok, None)
    missing_ok = nst._validate_structure_region_mapping(
        cfg=cfg_ok,
        structure_region_map=mapping_ok,
        required_structure_ids=required_ok,
        planned_mode_active=True,
    )
    assert missing_ok == []

    cfg_fail = {
        "esi": {"strict_region_mapping": True, "auto_fill_structure_regions": True},
        "structures": {"o4t": 1040804972352, "cj6": 1049588174021},
        "required_structure_ids": [999999999999],
        "structure_regions": {},
    }
    mapping_fail = nst._resolve_structure_region_map(cfg_fail)
    required_fail = nst._collect_required_structure_ids(cfg_fail, None)
    raised = False
    try:
        _ = nst._validate_structure_region_mapping(
            cfg=cfg_fail,
            structure_region_map=mapping_fail,
            required_structure_ids=required_fail,
            planned_mode_active=True,
        )
    except SystemExit:
        raised = True
    assert raised is True

def test_strict_region_mapping_hard_fail() -> None:
    cfg = {
        "esi": {"strict_region_mapping": True},
        "structures": {"o4t": 1, "cj6": 2},
    }
    mapping = {1: 10000002}
    required = nst._collect_required_structure_ids(cfg, {1, 2})
    raised = False
    try:
        nst._validate_structure_region_mapping(
            cfg=cfg,
            structure_region_map=mapping,
            required_structure_ids=required,
            planned_mode_active=True,
        )
    except SystemExit as e:
        raised = True
        msg = str(e)
        assert "Strict region mapping aktiv" in msg
        assert "2" in msg
    assert raised is True

def test_non_strict_region_mapping_warns() -> None:
    cfg = {
        "esi": {"strict_region_mapping": False},
        "structures": {"o4t": 1, "cj6": 2},
    }
    mapping = {1: 10000002}
    required = nst._collect_required_structure_ids(cfg, {1, 2})
    buf = io.StringIO()
    with redirect_stdout(buf):
        missing = nst._validate_structure_region_mapping(
            cfg=cfg,
            structure_region_map=mapping,
            required_structure_ids=required,
            planned_mode_active=True,
        )
    out = buf.getvalue()
    assert 2 in missing
    assert "WARN: Kein region_id Mapping fuer aktive Structure IDs: 2 (cj6)." in out
    assert "planned_sell wird restriktiv" in out


def test_repo_config_has_unique_structure_ids() -> None:
    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    structures = dict(cfg.get("structures", {}) or {})
    seen: dict[int, str] = {}
    duplicates: list[tuple[int, str, str]] = []
    for label, raw in structures.items():
        if isinstance(raw, dict):
            sid = int(raw.get("id", 0) or 0)
        else:
            sid = int(raw or 0)
        if sid in seen and seen[sid] != str(label):
            duplicates.append((sid, seen[sid], str(label)))
        seen[sid] = str(label)
    assert duplicates == []


def test_repo_config_covers_internal_chain_structure_regions_for_planned_sell() -> None:
    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    structure_region_map = nst._resolve_structure_region_map(cfg)
    required_structure_ids = {
        1040804972352,  # O4T
        1048663825563,  # R-ARKN
        1046664001931,  # UALX-3
        1049588174021,  # 1st Taj Mahgoon / CJ6
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        missing = nst._validate_structure_region_mapping(
            cfg=cfg,
            structure_region_map=structure_region_map,
            required_structure_ids=required_structure_ids,
            planned_mode_active=True,
        )
    out = buf.getvalue()
    assert missing == []
    assert "planned_sell wird restriktiv" not in out
    assert int(structure_region_map.get(1048663825563, 0)) == 10000039
    assert int(structure_region_map.get(1046664001931, 0)) == 10000061

