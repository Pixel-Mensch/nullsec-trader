"""Architecture regression tests."""

from __future__ import annotations

from pathlib import Path

import candidate_engine
import execution_plan
import fees
import nullsectrader as nst
import portfolio_builder
import route_search
import runtime_runner
import shipping


def test_runtime_facade_reexports_productive_core_functions() -> None:
    assert nst.compute_trade_financials is fees.compute_trade_financials
    assert nst.compute_candidates is candidate_engine.compute_candidates
    assert nst.build_portfolio is portfolio_builder.build_portfolio
    assert nst.apply_route_costs_to_picks is shipping.apply_route_costs_to_picks
    assert nst.build_route_search_profiles is route_search.build_route_search_profiles
    assert nst.write_execution_plan_profiles is execution_plan.write_execution_plan_profiles
    assert nst.run_cli is runtime_runner.run_cli
    assert nst.main is runtime_runner.main


def test_legacy_runtime_and_legacy_core_are_removed() -> None:
    assert not Path("legacy_runtime.py").exists()
    assert not Path("legacy_core.py").exists()


def test_nullsectrader_is_only_a_thin_facade() -> None:
    content = Path("nullsectrader.py").read_text(encoding="utf-8")
    assert "run_cli" in content
    assert "legacy_runtime" not in content
    assert "legacy_core" not in content
    assert "def compute_candidates(" not in content
    assert "def build_portfolio(" not in content
    assert "def apply_route_costs_to_picks(" not in content


def test_main_entrypoint_calls_runtime_runner_directly() -> None:
    content = Path("main.py").read_text(encoding="utf-8")
    assert "runtime_runner" in content
    assert "run_cli" in content
    assert "legacy_runtime" not in content
    assert "legacy_core" not in content


def test_architecture_doc_describes_real_runtime_path() -> None:
    content = Path("ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "run.bat" in content
    assert "main.py" in content
    assert "nullsectrader.py" in content
    assert "runtime_runner.py" in content
    assert "legacy_runtime.py" not in content
