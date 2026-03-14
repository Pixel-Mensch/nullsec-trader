from __future__ import annotations

from pathlib import Path

from runtime_cleanup import collect_safe_cleanup_targets, run_safe_cleanup
from runtime_common import parse_cli_args


def test_parse_cli_args_supports_clean_command() -> None:
    args = parse_cli_args(["clean"])
    assert args["command"] == "clean"


def test_safe_cleanup_removes_runtime_artifacts_but_preserves_auth_and_journal(tmp_path: Path) -> None:
    files_to_create = [
        "execution_plan_2026-03-14_10-00-00.txt",
        "route_leaderboard_2026-03-14_10-00-00.txt",
        "trade_plan_plan-123.json",
        "snapshot_2026-03-14_10-00-00.json",
        "market_snapshot.json",
        "replay_snapshot.json",
        "cache/http_cache.json",
        "cache/types.json",
        "cache/token.json",
        "cache/trade_journal.sqlite3",
        "cache/character_context/sso_token.json",
        "subdir/__pycache__/module.cpython-312.pyc",
    ]
    for rel_path in files_to_create:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    pytest_cache = tmp_path / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "state").write_text("x", encoding="utf-8")

    targets = collect_safe_cleanup_targets(str(tmp_path))
    assert str(tmp_path / "cache" / "token.json") not in targets["files"]
    assert str(tmp_path / "cache" / "trade_journal.sqlite3") not in targets["files"]
    assert str(tmp_path / "cache" / "character_context") not in targets["dirs"]

    result = run_safe_cleanup(str(tmp_path))
    assert not result["failures"]

    assert not (tmp_path / "execution_plan_2026-03-14_10-00-00.txt").exists()
    assert not (tmp_path / "route_leaderboard_2026-03-14_10-00-00.txt").exists()
    assert not (tmp_path / "trade_plan_plan-123.json").exists()
    assert not (tmp_path / "snapshot_2026-03-14_10-00-00.json").exists()
    assert not (tmp_path / "market_snapshot.json").exists()
    assert not (tmp_path / "replay_snapshot.json").exists()
    assert not (tmp_path / "cache" / "http_cache.json").exists()
    assert not (tmp_path / "cache" / "types.json").exists()
    assert not (tmp_path / ".pytest_cache").exists()
    assert not (tmp_path / "subdir" / "__pycache__").exists()

    assert (tmp_path / "cache" / "token.json").exists()
    assert (tmp_path / "cache" / "trade_journal.sqlite3").exists()
    assert (tmp_path / "cache" / "character_context" / "sso_token.json").exists()
