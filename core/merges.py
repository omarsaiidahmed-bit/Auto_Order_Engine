"""Safe merge helpers.

Blueprint reference: Section 9 (the merge layer).

Every merge in this system is a ``left`` join from the driver frame onto a
**pre-aggregated, unique-key** frame.  ``validate="one_to_one"`` is mandatory and a
row-count invariant is checked independently (Blueprint 9.2).
"""

from __future__ import annotations

import pandas as pd

from core.aggregation import assert_unique_sku

__all__ = ["merge_measure"]


def merge_measure(
    base: pd.DataFrame,
    right: pd.DataFrame,
    *,
    label: str,
    expected_rows: int,
) -> pd.DataFrame:
    """Left-join a pre-aggregated, unique-key frame onto the driver frame.

    Raises when the right frame has a duplicate key, when pandas' ``validate``
    rejects the join, or when the row count changes -- the three ways a Cartesian
    product can occur (Blueprint 9.2, invariant INV-1).
    """
    assert_unique_sku(right, label)
    merged = base.merge(right, how="left", on="الكود", validate="one_to_one")
    if len(merged) != expected_rows:
        raise ValueError(
            f"Internal error while joining '{label}': row count changed from "
            f"{expected_rows:,} to {len(merged):,}. A duplicated item code "
            f"caused a row explosion."
        )
    return merged
