"""Compatibility facade for Nullsec trader runtime.

`legacy_core.py` is now a thin compatibility re-export layer.
Runtime orchestration lives in `legacy_runtime.py`.
This module remains the stable import path for tests and external tooling.
"""

import legacy_core as _legacy_core


def _export_legacy_symbols() -> None:
    for name in dir(_legacy_core):
        if name.startswith("__"):
            continue
        globals()[name] = getattr(_legacy_core, name)


_export_legacy_symbols()


if __name__ == "__main__":
    _legacy_core.main()
