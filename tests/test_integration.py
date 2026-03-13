"""Integration tests."""

from tests.shared import *  # noqa: F401,F403

def test_history_404_negative_cache_skips_repeat_calls() -> None:
    esi = _HistoryProbeESI(status_code=404, payload={"error": "not found"})
    s1 = esi.get_region_history_stats(10000002, 456, 30)
    s2 = esi.get_region_history_stats(10000002, 456, 30)
    s3 = esi.get_region_history_stats(10000002, 456, 7)
    assert int(esi.history_calls) == 1
    assert bool(s1.get("missing", False)) is True
    assert bool(s2.get("missing", False)) is True
    assert bool(s3.get("missing", False)) is True
    assert int(esi._perf_stats.get("history_http_404", 0)) == 1
    assert int(esi._perf_stats.get("history_negative_cache_hits", 0)) >= 1

def test_history_raw_cache_reused_across_days() -> None:
    payload = [
        {"date": "2026-03-03T00:00:00Z", "volume": 10, "order_count": 2},
        {"date": "2026-02-25T00:00:00Z", "volume": 20, "order_count": 4},
    ]
    esi = _HistoryProbeESI(status_code=200, payload=payload)
    _ = esi.get_region_history_stats(10000002, 789, 30)
    _ = esi.get_region_history_stats(10000002, 789, 7)
    assert int(esi.history_calls) == 1
    assert int(esi._perf_stats.get("history_raw_cache_hits", 0)) >= 1

def test_esi_cache_respects_expires() -> None:
    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    expires_http = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
    c = _make_cacheable_client([
        _SeqResponse(200, [{"x": 1}], headers={"Expires": expires_http, "ETag": "\"abc\""})
    ])
    r1 = c.esi_get("/markets/10000002/history/", params={"type_id": 34}, auth=False)
    r2 = c.esi_get("/markets/10000002/history/", params={"type_id": 34}, auth=False)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(c.session.calls) == 1
    assert int(len(c.request_log)) >= 2

def test_esi_cache_uses_if_none_match_and_handles_304() -> None:
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    c = _make_cacheable_client([
        _SeqResponse(
            200,
            [{"type_id": 34, "volume": 100, "date": "2026-03-03T00:00:00Z"}],
            headers={"Expires": past.strftime("%a, %d %b %Y %H:%M:%S GMT"), "ETag": "\"etag-1\""},
        ),
        _SeqResponse(
            304,
            None,
            headers={"Expires": future.strftime("%a, %d %b %Y %H:%M:%S GMT"), "ETag": "\"etag-1\""},
        ),
    ])
    _ = c.esi_get("/markets/10000002/history/", params={"type_id": 34}, auth=False)
    r2 = c.esi_get("/markets/10000002/history/", params={"type_id": 34}, auth=False)
    assert r2.status_code == 200
    assert len(c.session.calls) == 2
    second_headers = c.session.calls[1]["headers"]
    assert "If-None-Match" in second_headers
    assert second_headers["If-None-Match"] == "\"etag-1\""

def test_get_jita_44_orders_filters_location_id_from_paginated_region_orders() -> None:
    c = _make_cacheable_client([
        _SeqResponse(
            200,
            [
                {"type_id": 1, "location_id": 60003760, "is_buy_order": False, "price": 10.0, "volume_remain": 1},
                {"type_id": 2, "location_id": 12345, "is_buy_order": False, "price": 11.0, "volume_remain": 1},
            ],
            headers={"X-Pages": "2", "Expires": "Wed, 04 Mar 2026 22:30:00 GMT"},
        ),
        _SeqResponse(
            200,
            [
                {"type_id": 3, "location_id": 60003760, "is_buy_order": False, "price": 12.0, "volume_remain": 1},
            ],
            headers={"X-Pages": "2", "Expires": "Wed, 04 Mar 2026 22:30:00 GMT"},
        ),
        _SeqResponse(
            200,
            [
                {"type_id": 4, "location_id": 60003760, "is_buy_order": True, "price": 9.0, "volume_remain": 1},
                {"type_id": 5, "location_id": 99999, "is_buy_order": True, "price": 8.0, "volume_remain": 1},
            ],
            headers={"X-Pages": "1", "Expires": "Wed, 04 Mar 2026 22:30:00 GMT"},
        ),
    ])
    out = c.get_jita_44_orders(region_id=10000002, location_id=60003760, order_type="all")
    assert len(out) == 3
    assert all(int(o.get("location_id", 0)) == 60003760 for o in out)

def test_fetch_orders_for_node_uses_jita_path_for_location_source_and_dest() -> None:
    probe = _NodeFetchProbeESI()
    jita_node = {"label": "jita_44", "id": 60003760, "kind": "location", "location_id": 60003760, "region_id": 10000002}
    out_src = nst._fetch_orders_for_node(probe, jita_node, replay_enabled=False, replay_structs=None)
    out_dst = nst._fetch_orders_for_node(probe, jita_node, replay_enabled=False, replay_structs=None)
    assert len(out_src) == 1 and len(out_dst) == 1
    assert probe.jita_calls == 2
    assert probe.structure_calls == 0

def test_fetch_orders_for_location_node_does_not_call_structure_endpoint() -> None:
    probe = _NodeFetchProbeESI()
    generic_loc = {"label": "some_station", "id": 70000001, "kind": "location", "location_id": 70000001, "region_id": 10000002}
    out = nst._fetch_orders_for_node(probe, generic_loc, replay_enabled=False, replay_structs=None)
    assert len(out) == 1
    assert probe.location_calls == 1
    assert probe.structure_calls == 0

def test_replay_main_smoke_runs_to_completion() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = os.path.join(tmpdir, "replay_snapshot.json")
        local_cfg_path = os.path.join(tmpdir, "config.local.json")

        snapshot = {
            "meta": {"timestamp": 1},
            "structures": {
                "1040804972352": {
                    "orders": [
                        {"type_id": 34, "price": 100.0, "volume_remain": 5000, "is_buy_order": False},
                        {"type_id": 34, "price": 90.0, "volume_remain": 5000, "is_buy_order": True},
                    ],
                    "meta": {},
                },
                "1049588174021": {
                    "orders": [
                        {"type_id": 34, "price": 130.0, "volume_remain": 5000, "is_buy_order": False},
                        {"type_id": 34, "price": 120.0, "volume_remain": 5000, "is_buy_order": True},
                    ],
                    "meta": {},
                },
                "60003760": {
                    "orders": [
                        {"type_id": 34, "price": 110.0, "volume_remain": 5000, "is_buy_order": False},
                        {"type_id": 34, "price": 105.0, "volume_remain": 5000, "is_buy_order": True},
                    ],
                    "meta": {},
                },
            },
            "type_cache": {
                "34": {"name": "Tritanium", "volume": 0.01},
            },
        }
        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        local_cfg = {
            "replay": {
                "enabled": True,
                "snapshot_path": snapshot_path,
                "write_snapshot_after_fetch": False,
            },
            "route_chain": {
                "enabled": False,
                "legs": [],
            },
            "route_search": {
                "enabled": True,
                "allow_all_structures_internal": False,
                "allow_shipping_lanes": False,
                "max_routes": 1,
                "allowed_pairs": [{"from": "jita_44", "to": "o4t"}],
            },
            "filters_forward": {"mode": "instant"},
            "filters_return": {"mode": "instant"},
        }
        with open(local_cfg_path, "w", encoding="utf-8") as f:
            json.dump(local_cfg, f, ensure_ascii=False, indent=2)

        before_exec = set(glob.glob(os.path.join(repo_root, "execution_plan_*.txt")))
        before_board = set(glob.glob(os.path.join(repo_root, "route_leaderboard_*.txt")))

        env = os.environ.copy()
        env["NULLSEC_LOCAL_CONFIG"] = local_cfg_path
        env["NULLSEC_REPLAY_ENABLED"] = "1"
        proc = subprocess.run(
            [sys.executable, "main.py"],
            cwd=repo_root,
            input="\n\n",
            text=True,
            capture_output=True,
            env=env,
            timeout=120,
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        assert proc.returncode == 0, combined
        assert "Replay-Mode aktiv." in proc.stdout
        assert "Fertig!" in proc.stdout
        assert "NameError" not in combined

        after_exec = set(glob.glob(os.path.join(repo_root, "execution_plan_*.txt")))
        after_board = set(glob.glob(os.path.join(repo_root, "route_leaderboard_*.txt")))
        new_exec = sorted(after_exec - before_exec)
        new_board = sorted(after_board - before_board)
        assert new_exec, "expected execution_plan output file"
        assert new_board, "expected route_leaderboard output file"

        created_paths: list[str] = []
        capture = False
        for raw_line in proc.stdout.splitlines():
            line = str(raw_line).strip()
            if line == "=== ERSTELLTE DATEIEN ===":
                capture = True
                continue
            if capture and line.startswith("market_snapshot.json"):
                break
            if capture and os.path.isabs(line):
                created_paths.append(line)
        for p in created_paths:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass
        try:
            market_snapshot = os.path.join(repo_root, "market_snapshot.json")
            if os.path.isfile(market_snapshot):
                os.remove(market_snapshot)
        except Exception:
            pass

def test_replay_fixture_files_normalize_cleanly() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture_dir = os.path.join(repo_root, "tests", "fixtures")
    fixture_names = [
        "replay_profitable_jita_o4t.json",
        "replay_dead_market_jita_cj6.json",
        "replay_live_focused_o4t_jita_20260308.json",
    ]
    for fixture_name in fixture_names:
        path = os.path.join(fixture_dir, fixture_name)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        normalized = nst.normalize_replay_snapshot(raw, 1040804972352, 1049588174021)
        assert isinstance(normalized, dict)
        assert "structures" in normalized
        assert "60003760" in normalized["structures"]
        assert normalized["type_cache"], f"fixture missing type cache: {fixture_name}"


def _created_paths_from_stdout(stdout: str) -> list[str]:
    created_paths: list[str] = []
    capture = False
    for raw_line in str(stdout or "").splitlines():
        line = str(raw_line).strip()
        if line == "=== ERSTELLTE DATEIEN ===":
            capture = True
            continue
        if capture and line.startswith("market_snapshot.json"):
            break
        if capture and os.path.isabs(line):
            created_paths.append(line)
    return created_paths


def _cleanup_runtime_artifacts(paths: list[str]) -> None:
    for p in list(paths or []):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    market_snapshot = os.path.join(repo_root, "market_snapshot.json")
    try:
        if os.path.isfile(market_snapshot):
            os.remove(market_snapshot)
    except Exception:
        pass


def _focused_replay_local_cfg(snapshot_path: str) -> dict:
    return {
        "replay": {
            "enabled": True,
            "snapshot_path": snapshot_path,
            "write_snapshot_after_fetch": False,
        },
        "route_chain": {
            "enabled": False,
            "legs": [],
        },
        "structures": {
            "o4t": 1040804972352,
            "cj6": 1040804972352,
            "c-j6mt": 1040804972352,
        },
        "route_search": {
            "enabled": True,
            "allow_all_structures_internal": False,
            "allow_shipping_lanes": False,
            "max_routes": 2,
            "allowed_pairs": [
                {"from": "jita_44", "to": "o4t", "shipping_lane_id": "hwl_jita_o4t"},
                {"from": "o4t", "to": "jita_44", "shipping_lane_id": "hwl_o4t_jita"},
            ],
        },
        "filters_forward": {"mode": "instant"},
        "filters_return": {"mode": "instant"},
        "character_context": {"enabled": False},
    }


def _run_replay_with_local_cfg(local_cfg: dict) -> tuple[subprocess.CompletedProcess[str], dict]:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmpdir:
        local_cfg_path = os.path.join(tmpdir, "config.local.json")
        with open(local_cfg_path, "w", encoding="utf-8") as f:
            json.dump(local_cfg, f, ensure_ascii=False, indent=2)
        env = os.environ.copy()
        env["NULLSEC_LOCAL_CONFIG"] = local_cfg_path
        env["NULLSEC_REPLAY_ENABLED"] = "1"
        proc = subprocess.run(
            [sys.executable, "main.py", "--cargo-m3", "10000", "--budget-isk", "500m"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            env=env,
            timeout=120,
        )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, combined
    created_paths = _created_paths_from_stdout(proc.stdout)
    manifest_path = next((p for p in created_paths if os.path.basename(p).startswith("trade_plan_") and p.endswith(".json")), "")
    assert manifest_path, proc.stdout
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    _cleanup_runtime_artifacts(created_paths)
    return proc, manifest


def test_replay_live_focused_fixture_keeps_real_pick_set() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture_path = os.path.join(repo_root, "tests", "fixtures", "replay_live_focused_o4t_jita_20260308.json")
    proc, manifest = _run_replay_with_local_cfg(_focused_replay_local_cfg(fixture_path))
    assert "Replay-Mode aktiv." in proc.stdout
    assert manifest["runtime_mode"] == "route_profiles"
    assert int(manifest["route_count"]) == 2
    assert int(manifest["pick_count"]) == 2
    route_labels = [str(route.get("route_label", "")) for route in manifest["routes"]]
    assert route_labels == ["jita_44 -> o4t", "o4t -> jita_44"]
    actionable = [route for route in manifest["routes"] if bool(route.get("actionable", False))]
    assert len(actionable) == 1
    pick_names = [str(pick.get("item_name", "")) for pick in actionable[0].get("picks", [])]
    assert pick_names == [
        "Noise-25 'Needlejack' Filament",
        "Polarized Heavy Neutron Blaster",
    ]
    assert all(float(pick.get("proposed_sell_price", 0.0) or 0.0) > 0.0 for pick in actionable[0].get("picks", []))
    assert sum(float(pick.get("proposed_expected_profit", 0.0) or 0.0) for pick in actionable[0].get("picks", [])) > 200_000_000.0


def test_replay_same_snapshot_keeps_stable_plan_and_pick_ids() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture_path = os.path.join(repo_root, "tests", "fixtures", "replay_live_focused_o4t_jita_20260308.json")
    local_cfg = _focused_replay_local_cfg(fixture_path)
    proc_a, manifest_a = _run_replay_with_local_cfg(local_cfg)
    proc_b, manifest_b = _run_replay_with_local_cfg(local_cfg)
    assert manifest_a["plan_id"] == manifest_b["plan_id"]
    picks_a = [pick["pick_id"] for route in manifest_a["routes"] for pick in route.get("picks", [])]
    picks_b = [pick["pick_id"] for route in manifest_b["routes"] for pick in route.get("picks", [])]
    assert picks_a == picks_b
    assert f"Plan ID: {manifest_a['plan_id']}" in proc_a.stdout
    assert f"Plan ID: {manifest_b['plan_id']}" in proc_b.stdout

