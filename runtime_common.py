from __future__ import annotations

import base64
import os


BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
TOKEN_PATH = os.path.join(CACHE_DIR, "token.json")
TYPE_CACHE_PATH = os.path.join(CACHE_DIR, "types.json")
HTTP_CACHE_PATH = os.path.join(CACHE_DIR, "http_cache.json")
JOURNAL_DB_PATH = os.path.join(CACHE_DIR, "trade_journal.sqlite3")
CHARACTER_CACHE_DIR = os.path.join(CACHE_DIR, "character_context")
CHARACTER_PROFILE_PATH = os.path.join(CHARACTER_CACHE_DIR, "character_profile.json")
CHARACTER_SSO_TOKEN_PATH = os.path.join(CHARACTER_CACHE_DIR, "sso_token.json")
CHARACTER_SSO_METADATA_PATH = os.path.join(CHARACTER_CACHE_DIR, "sso_metadata.json")


def die(msg: str) -> None:
    print(msg)
    raise SystemExit(1)


def parse_isk(s: str) -> int:
    raw = str(s or "").strip().lower().replace(",", "").replace("_", "")
    if not raw:
        raise ValueError("empty")
    mult = 1
    if raw.endswith("b"):
        mult = 1_000_000_000
        raw = raw[:-1]
    elif raw.endswith("m"):
        mult = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("k"):
        mult = 1_000
        raw = raw[:-1]
    value = float(raw)
    if value < 0:
        raise ValueError("negative")
    return int(value * mult)


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
        "command": "run",
        "journal_argv": [],
        "auth_action": "",
        "character_action": "",
        "snapshot_only": False,
        "snapshot_out": None,
        "structures": None,
        "cargo_m3": None,
        "budget_isk": None,
        "detail": False,
        "compact": False,
        "profile": None,
    }
    if argv and str(argv[0]).strip().lower() == "journal":
        args["command"] = "journal"
        args["journal_argv"] = list(argv[1:])
        return args
    if argv and str(argv[0]).strip().lower() == "auth":
        args["command"] = "auth"
        args["auth_action"] = str(argv[1]).strip().lower() if len(argv) > 1 else "login"
        return args
    if argv and str(argv[0]).strip().lower() == "character":
        args["command"] = "character"
        args["character_action"] = str(argv[1]).strip().lower() if len(argv) > 1 else "status"
        return args
    if argv and str(argv[0]).strip().lower() in ("clean", "cleanup"):
        args["command"] = "clean"
        return args
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--snapshot-only":
            args["snapshot_only"] = True
            i += 1
            continue
        if tok == "--detail":
            args["detail"] = True
            i += 1
            continue
        if tok in ("--compact", "--compact-mode"):
            args["compact"] = True
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
        if tok in ("--profile", "--risk-profile"):
            if i + 1 >= len(argv):
                die("--profile erwartet einen Profilnamen (z.B. conservative, balanced, aggressive)")
            args["profile"] = str(argv[i + 1]).strip().lower()
            i += 2
            continue
        die(f"Unbekanntes Argument: {tok}")
    return args


def input_with_default(prompt: str, default_value: str) -> str:
    value = input(f"{prompt} (default {default_value}): ").strip()
    return value if value else default_value


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def make_basic_auth(client_id: str, client_secret: str) -> str:
    token = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("utf-8")


__all__ = [
    "BASE_DIR",
    "CONFIG_PATH",
    "CACHE_DIR",
    "TOKEN_PATH",
    "TYPE_CACHE_PATH",
    "HTTP_CACHE_PATH",
    "JOURNAL_DB_PATH",
    "CHARACTER_CACHE_DIR",
    "CHARACTER_PROFILE_PATH",
    "CHARACTER_SSO_TOKEN_PATH",
    "CHARACTER_SSO_METADATA_PATH",
    "die",
    "parse_isk",
    "_has_live_esi_credentials",
    "parse_cli_args",
    "input_with_default",
    "b64url",
    "make_basic_auth",
]
