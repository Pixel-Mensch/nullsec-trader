from __future__ import annotations

import glob
import os
import shutil

from runtime_common import BASE_DIR


ROOT_ARTIFACT_PATTERNS = [
    "execution_plan_*.txt",
    "route_leaderboard_*.txt",
    "*_chain_summary_*.txt",
    "roundtrip_plan_*.txt",
    "no_trade_*.txt",
    "*_top_candidates_*.txt",
    "*_to_*_20??-??-??_??-??-??.csv",
    "trade_plan_*.json",
    "snapshot_*.json",
    "market_snapshot.json",
    "replay_snapshot.json",
]

RUNTIME_CACHE_FILES = [
    os.path.join("cache", "http_cache.json"),
    os.path.join("cache", "types.json"),
]

RUNTIME_CACHE_DIR_PATTERNS = [
    ".pytest_cache",
    "**/__pycache__",
]


def _normalized(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def collect_safe_cleanup_targets(base_dir: str | None = None) -> dict:
    root = os.path.abspath(base_dir or BASE_DIR)
    files: set[str] = set()
    dirs: set[str] = set()

    for pattern in ROOT_ARTIFACT_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern)):
            if os.path.isfile(path):
                files.add(os.path.abspath(path))

    for rel_path in RUNTIME_CACHE_FILES:
        path = os.path.join(root, rel_path)
        if os.path.isfile(path):
            files.add(os.path.abspath(path))

    for pattern in RUNTIME_CACHE_DIR_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern), recursive=True):
            if os.path.isdir(path):
                dirs.add(os.path.abspath(path))

    protected = {
        _normalized(os.path.join(root, "cache", "token.json")),
        _normalized(os.path.join(root, "cache", "trade_journal.sqlite3")),
        _normalized(os.path.join(root, "cache", "character_context")),
    }
    files = {path for path in files if _normalized(path) not in protected}
    dirs = {path for path in dirs if _normalized(path) not in protected}
    return {
        "base_dir": root,
        "files": sorted(files),
        "dirs": sorted(dirs),
    }


def run_safe_cleanup(base_dir: str | None = None) -> dict:
    targets = collect_safe_cleanup_targets(base_dir)
    removed_files: list[str] = []
    removed_dirs: list[str] = []
    failures: list[dict] = []

    for path in targets["files"]:
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed_files.append(path)
        except Exception as exc:
            failures.append({"path": path, "error": str(exc)})

    for path in sorted(targets["dirs"], key=len, reverse=True):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                removed_dirs.append(path)
        except Exception as exc:
            failures.append({"path": path, "error": str(exc)})

    return {
        "base_dir": targets["base_dir"],
        "planned_files": list(targets["files"]),
        "planned_dirs": list(targets["dirs"]),
        "removed_files": removed_files,
        "removed_dirs": removed_dirs,
        "failures": failures,
    }


__all__ = [
    "ROOT_ARTIFACT_PATTERNS",
    "RUNTIME_CACHE_DIR_PATTERNS",
    "RUNTIME_CACHE_FILES",
    "collect_safe_cleanup_targets",
    "run_safe_cleanup",
]
