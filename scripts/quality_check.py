"""Local quality checks for Nullsec Trader Tool.

Runs syntax checks and the real pytest-based regression suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _repo_paths(pattern: str) -> list[str]:
    return sorted(str(path.relative_to(REPO_ROOT)) for path in REPO_ROOT.glob(pattern))


ROOT_MODULES = _repo_paths("*.py")
WEBAPP_MODULES = _repo_paths("webapp/**/*.py")
SCRIPT_MODULES = _repo_paths("scripts/*.py")
TEST_SOURCE_FILES = _repo_paths("tests/*.py")
TEST_MODULES = [
    "tests/test_ansiblex.py",
    "tests/test_config.py",
    "tests/test_execution_plan.py",
    "tests/test_integration.py",
    "tests/test_route_search.py",
    "tests/test_runtime_runner.py",
    "tests/test_shipping.py",
    "tests/test_webapp.py",
]


def _unique(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


PY_COMPILE_TARGETS = _unique(ROOT_MODULES + WEBAPP_MODULES + SCRIPT_MODULES + TEST_SOURCE_FILES)


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))


def main() -> None:
    _run([sys.executable, "-m", "py_compile", *PY_COMPILE_TARGETS])
    _run([sys.executable, "-m", "pytest", "-q", *TEST_MODULES])
    print("\nQuality checks passed.")


if __name__ == "__main__":
    main()
