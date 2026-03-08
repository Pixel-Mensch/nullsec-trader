from __future__ import annotations

import io
import os
import re
import sys
import traceback
from contextlib import contextmanager, redirect_stdout

from config_loader import load_json
from runtime_runner import run_cli


@contextmanager
def _patched_argv(argv: list[str]):
    old = list(sys.argv)
    sys.argv = [old[0] if old else "main.py", *list(argv or [])]
    try:
        yield
    finally:
        sys.argv = old


@contextmanager
def _patched_env(overrides: dict[str, str | None] | None):
    overrides = dict(overrides or {})
    old: dict[str, str | None] = {}
    try:
        for key, value in overrides.items():
            old[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _extract_plan_id(output: str) -> str:
    match = re.search(r"^Plan ID:\s*(.+)$", str(output or ""), flags=re.MULTILINE)
    return str(match.group(1)).strip() if match else ""


def _extract_snapshot_path(output: str) -> str:
    match = re.search(r"^(?:Replay-)?Snapshot geschrieben:\s*(.+)$", str(output or ""), flags=re.MULTILINE)
    return str(match.group(1)).strip() if match else ""


def _extract_created_files(output: str) -> list[str]:
    lines = str(output or "").splitlines()
    created: list[str] = []
    capture = False
    for raw in lines:
        line = str(raw).strip()
        if line == "=== ERSTELLTE DATEIEN ===":
            capture = True
            continue
        if not capture:
            continue
        if not line:
            if created:
                break
            continue
        if line == "market_snapshot.json erstellt.":
            break
        created.append(line)
    return created


def _read_text(path: str) -> str:
    text = str(path or "").strip()
    if not text or not os.path.exists(text):
        return ""
    with open(text, "r", encoding="utf-8") as handle:
        return handle.read()


def _load_manifest(plan_id: str, created_files: list[str]) -> dict:
    for path in list(created_files or []):
        name = os.path.basename(str(path))
        if name.startswith("trade_plan_") and name.endswith(".json"):
            payload = load_json(str(path), {})
            return dict(payload) if isinstance(payload, dict) else {}
    if plan_id:
        default_path = os.path.join(os.path.dirname(__file__), "..", "..", f"trade_plan_{plan_id}.json")
        payload = load_json(os.path.abspath(default_path), {})
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def extract_personal_layer_lines(text: str) -> list[str]:
    lines = str(text or "").splitlines()
    prefixes = ("Personal Basis:", "Fallback:", "Applied:", "Policy:")
    for idx, raw in enumerate(lines):
        current = str(raw).strip()
        if not current.startswith("Personal Layer:"):
            continue
        block = [current]
        pos = idx + 1
        while pos < len(lines):
            nxt = str(lines[pos]).strip()
            if nxt.startswith(prefixes):
                block.append(nxt)
                pos += 1
                continue
            break
        return block
    return []


def invoke_runtime(argv: list[str], *, env_overrides: dict[str, str | None] | None = None) -> dict:
    buffer = io.StringIO()
    error_message = ""
    exit_code = 0
    ok = True
    with _patched_env(env_overrides), _patched_argv(list(argv or [])), redirect_stdout(buffer):
        try:
            run_cli()
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
            ok = exit_code == 0
        except Exception as exc:  # pragma: no cover - defensive bridge path
            ok = False
            exit_code = 1
            error_message = f"{exc}\n{traceback.format_exc()}"
    output = buffer.getvalue()
    created_files = _extract_created_files(output)
    snapshot_path = _extract_snapshot_path(output)
    manifest = _load_manifest(_extract_plan_id(output), created_files)
    text_files = {os.path.basename(path): _read_text(path) for path in list(created_files or []) if str(path).endswith(".txt")}
    if snapshot_path and snapshot_path not in created_files:
        created_files = [snapshot_path, *created_files]
    execution_plan_text = ""
    for name, content in text_files.items():
        if str(name).startswith("execution_plan_"):
            execution_plan_text = content
            break
    return {
        "ok": bool(ok),
        "exit_code": int(exit_code),
        "stdout": output,
        "error": error_message,
        "plan_id": _extract_plan_id(output),
        "snapshot_path": snapshot_path,
        "created_files": created_files,
        "manifest": manifest,
        "text_files": text_files,
        "personal_layer_lines": extract_personal_layer_lines(execution_plan_text or output),
    }
