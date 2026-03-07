"""Compatibility layer for legacy runtime symbols.

Source of truth for runtime behavior lives in ``legacy_runtime.py`` and
extracted modules. This module intentionally stays small so imports via
``legacy_core`` remain stable for existing tooling.
"""

import legacy_runtime as _legacy_runtime


def _export_runtime_symbols() -> None:
    for name in dir(_legacy_runtime):
        if name.startswith("__"):
            continue
        globals()[name] = getattr(_legacy_runtime, name)


_export_runtime_symbols()

