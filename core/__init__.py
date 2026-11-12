"""Pharmacy Auto-Order Engine -- business logic package.

Blueprint reference: Section 3.3 (target layout), Section 21 (code quality).

This package MUST NOT import ``streamlit`` (Blueprint 21.3.1) so that every rule can be
unit-tested headlessly.  ``app.py`` is the only module allowed to touch the UI.
"""

from __future__ import annotations

import os as _os_guard

_core_dir = _os_guard.path.dirname(__file__)
_duplicates = [
    f
    for f in _os_guard.listdir(_core_dir)
    if f.startswith("supply_chain") and f != "supply_chain.py" and f.endswith(".py")
]
if _duplicates:
    raise ImportError(
        f"❌ DUPLICATE SUPPLY_CHAIN FILES FOUND: {_duplicates}. "
        f"Delete them before running. Only supply_chain.py is allowed."
    )

__all__ = [
    "aggregation",
    "audit",
    "exporter",
    "ingestion",
    "merges",
    "normalize",
    "notes",
    "substitutes",
    "supply_chain",
]
