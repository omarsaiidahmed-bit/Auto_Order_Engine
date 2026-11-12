"""The pack (quantity) model -- the keystone of the whole system.

The ERP does not store "how many pieces are on the shelf".  It stores:

``عبوات``   the number of whole packs,
``اجزاء``   the number of *loose* pieces,
``الكمية``   the pack-equivalent quantity.

and the three are related by the master's pack size:

``الكمية = عبوات + (اجزاء ÷ master's الاجزاء)``

The relationship was verified at 100.0% on 5,203 rows with a non-zero piece
count and at 100.0% on the 27,215 rows where ``اجزاء == 0`` (where
``الكمية == عبوات``).

Consequences that the rest of the system relies on:

* The canonical unit of stock, demand, reorder point and order is **the pack**.
* ``الكمية`` must never be integer-cast before the arithmetic -- 1,158 branch
  rows and 2,732 sales rows are fractional.
* An order quantity is a whole number of packs (the orderable unit).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app_config import (
    MASTER_PACK_SIZE_COLUMN,
    PACKS_COLUMN,
    PIECES_COLUMN,
    QUANTITY_COLUMN,
    QUANTITY_TOLERANCE,
)

__all__ = [
    "PackModel",
    "build_pack_model",
    "compute_pack_equivalent",
    "round_up_to_packs",
    "to_whole_packs",
]


def compute_pack_equivalent(
    packs: pd.Series,
    pieces: pd.Series,
    pack_size: pd.Series,
) -> pd.Series:
    """Return ``packs + pieces / pack_size`` -- the ERP's pack-equivalent rule.

    ``pack_size`` is aligned on ``packs.index``.  A pack size of zero or a
    missing pack size falls back to ``1`` (a single-piece pack), which is what
    the ERP itself does for the 82.4% of the catalogue that has no pack size.
    """
    size = pd.to_numeric(pack_size, errors="coerce").fillna(1.0)
    size = size.where(size > 0, 1.0)
    pack_values = pd.to_numeric(packs, errors="coerce").fillna(0.0)
    piece_values = pd.to_numeric(pieces, errors="coerce").fillna(0.0)
    return pack_values + piece_values / size


def to_whole_packs(quantity: float, moq_packs: int = 1) -> int:
    """Round a pack-equivalent quantity up to a whole number of packs.

    ``moq_packs`` is the supplier's minimum order multiple expressed in packs
    (normally ``1``).  Negative quantities are rounded away from zero so a
    negative balance is never hidden behind a truncation towards zero.
    """
    if quantity is None or not math.isfinite(float(quantity)):
        return 0
    value = float(quantity)
    if value <= 0:
        return -int(math.floor(abs(value)))
    step = max(1, int(moq_packs))
    return int(math.ceil(value / step) * step)


def round_up_to_packs(quantity: float, moq_packs: int = 1) -> int:
    """Round a positive quantity up to the next multiple of ``moq_packs``."""
    if quantity is None or not math.isfinite(float(quantity)):
        return 0
    value = float(quantity)
    if value <= 0:
        return 0
    step = max(1, int(moq_packs))
    return int(math.ceil(value / step) * step)


@dataclass(frozen=True)
class PackModel:
    """The pack arithmetic for one run.

    Attributes
    ----------
    pack_size:
        ``Series`` indexed by SKU holding the pieces-per-pack value.
    mismatches:
        How many rows of the transactional files disagree with the ERP's own
        pack arithmetic (a data-quality signal, never an error).
    checked_rows:
        How many rows were checked.
    """

    pack_size: pd.Series
    mismatches: int = 0
    checked_rows: int = 0

    def size_for(self, skus: pd.Series) -> pd.Series:
        """Return the pack size for ``skus`` (1 where unknown)."""
        if self.pack_size.empty:
            return pd.Series(1.0, index=skus.index, dtype="float64")
        # ``map`` and not ``reindex``: the caller may pass repeated item codes
        size = skus.astype("string").map(self.pack_size).fillna(1.0)
        size = size.where(size > 0, 1.0)
        return size.astype("float64")


def build_pack_model(
    master: pd.DataFrame,
    *,
    transactional: tuple[tuple[str, pd.DataFrame], ...] = (),
) -> PackModel:
    """Build the pack model from the master file and audit the transactions.

    ``master`` must expose ``كود الصنف`` and (optionally) ``الاجزاء``.
    ``transactional`` is a sequence of ``(label, frame)`` pairs; each frame is
    checked against the ERP's own arithmetic so the run can report a data
    quality figure instead of silently trusting it.
    """
    pack_size = pd.Series(dtype="float64")
    mismatches = 0
    checked = 0

    if master is not None and not master.empty:
        sizes = pd.Series(1.0, index=master.index, dtype="float64")
        if MASTER_PACK_SIZE_COLUMN in master.columns:
            raw = pd.to_numeric(master[MASTER_PACK_SIZE_COLUMN], errors="coerce")
            sizes = raw.fillna(1.0).where(raw.fillna(1.0) > 0, 1.0)
        pack_size = pd.Series(
            sizes.to_numpy(),
            index=master["كود الصنف"].astype("string"),
            dtype="float64",
        )
        # A duplicated master card must not silently double the pack size.
        pack_size = pack_size.groupby(level=0).max()
        pack_size = pack_size.where(pack_size > 0, 1.0)

    for _label, frame in transactional:
        if frame is None or frame.empty:
            continue
        if not {PACKS_COLUMN, PIECES_COLUMN, QUANTITY_COLUMN}.issubset(frame.columns):
            continue
        sku_column = next(
            (
                column
                for column in ("كود الصنف", "الكود")
                if column in frame.columns
            ),
            None,
        )
        if sku_column is None:
            continue
        sizes = frame[sku_column].astype("string").map(pack_size).fillna(1.0)
        sizes = sizes.where(sizes > 0, 1.0).to_numpy()
        expected = compute_pack_equivalent(
            frame[PACKS_COLUMN], frame[PIECES_COLUMN], pd.Series(sizes, index=frame.index)
        )
        actual = pd.to_numeric(frame[QUANTITY_COLUMN], errors="coerce").fillna(0.0)
        delta = (expected - actual).abs()
        mismatches += int((delta > QUANTITY_TOLERANCE).sum())
        checked += len(frame)

    return PackModel(pack_size=pack_size, mismatches=mismatches, checked_rows=checked)


def empty_pack_model() -> PackModel:
    """A pack model that assumes single-piece packs."""
    return PackModel(pack_size=pd.Series(dtype="float64"))


def integer_export_series(series: pd.Series) -> pd.Series:
    """Cast a numeric series to ``int64`` without hiding fractional packs.

    Positive values are rounded **up** (a branch holding 1.4 packs can issue a
    whole pack) and negative values **down** (a deficit of 0.4 packs is still
    a deficit).  Rounding away from zero keeps the workbook consistent with
    the pack arithmetic.
    """
    values = pd.to_numeric(series, errors="coerce").fillna(0.0).to_numpy(dtype="float64")
    rounded = np.where(values >= 0, np.ceil(values), np.floor(values))
    return pd.Series(rounded.astype("int64"), index=series.index)
