"""Lightweight test runner for split test modules."""

import os
import sys
from importlib import import_module

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MODULES = ['test_core', 'test_portfolio', 'test_config', 'test_shipping', 'test_route_search', 'test_integration', 'test_architecture', 'test_journal', 'test_journal_reconciliation', 'test_confidence_calibration', 'test_explainability', 'test_market_plausibility']

def _iter_tests(module):
    for name, obj in module.__dict__.items():
        if name.startswith("test_") and callable(obj):
            yield name, obj

def run_all_tests() -> None:
    total = 0
    for mod_name in MODULES:
        module = import_module(f"tests.{mod_name}")
        for name, fn in _iter_tests(module):
            fn()
            print(f"[OK] {name}")
            total += 1
    print(f"\n{total} tests erfolgreich.")

if __name__ == "__main__":
    run_all_tests()
