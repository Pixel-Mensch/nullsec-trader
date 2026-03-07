"""Local quality checks for Nullsec Trader Tool.

Runs syntax checks, static lint checks (pyflakes) and the regression suite.
"""

from __future__ import annotations

import subprocess
import sys

MODULES = [
    "main.py",
    "nullsectrader.py",
    "legacy_core.py",
    "legacy_runtime.py",
    "startup_helpers.py",
    "config_loader.py",
    "shipping.py",
    "route_search.py",
    "execution_plan.py",
    "candidate_engine.py",
    "portfolio_builder.py",
    "fees.py",
    "fee_engine.py",
    "market_fetch.py",
    "market_normalization.py",
    "transport_allocation.py",
    "route_costs.py",
    "scoring.py",
    "models.py",
    "location_utils.py",
    "test_nullsectrader.py",
    "tests/run_all.py",
]

TEST_MODULES = [
    "tests/shared.py",
    "tests/test_core.py",
    "tests/test_portfolio.py",
    "tests/test_config.py",
    "tests/test_shipping.py",
    "tests/test_route_search.py",
    "tests/test_integration.py",
]


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    _run([sys.executable, "-m", "py_compile", *MODULES, *TEST_MODULES])
    _run([sys.executable, "-m", "pyflakes", *MODULES])
    _run([sys.executable, "test_nullsectrader.py"])
    print("\nQuality checks passed.")


if __name__ == "__main__":
    main()
