"""The aggregation layer -- the firewall that prevents row explosion.

Every transactional source passes through this module before it is joined.
A merge input is always unique per item code, so a ``left`` join can never
explode rows.  This is the direct answer to the historical ``-25`` incident:
a duplicated warehouse row used to be counted twice.

The transfer classification is data-driven.  The ERP writes exactly two
movement descriptions:

``ارسال بضائع - تحويل بين الفروع``   -> outgoing (negative quantities)
``استقبال بضائع - تحويل بين الفروع``  -> incoming (positive quantities)

Note that ``استقبال`` contains neither ``ارسال`` nor ``استلام``, so an
incoming-token list built from ``استلام`` alone would silently drop every
incoming movement.
"""

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

from app_config import (
    OPERATION_AMBIGUOUS,
    OPERATION_INCOMING,
    OPERATION_OUTGOING,
    OPERATION_UNKNOWN,
    PACKS_COLUMN,
    PIECES_COLUMN,
    QUANTITY_COLUMN,
    TRANSFER_IN_TOKENS,
    TRANSFER_OUT_TOKENS,
)
from core.normalize import normalize_operation
from core.quantity import compute_pack_equivalent

__all__ = [
    "aggregate_by_sku",
    "aggregate_stock",
    "assert_unique_sku",
    "build_transfer_aggregates",
    "classify_operations",
    "detect_transfer_sign_convention",
    "prepare_master_data",
    "transfer_magnitudes",
]


# ---------------------------------------------------------------------------
# The uniqueness assertion
# ---------------------------------------------------------------------------
def assert_unique_sku(frame: pd.DataFrame, label: str) -> None:
    """Fail loudly when a frame carries more than one row per item code."""
    if "الكود" not in frame.columns:
        return
    duplicated = frame["الكود"].duplicated()
    if bool(duplicated.any()):
        examples = frame.loc[duplicated, "الكود"].unique()[:10]
        raise ValueError(
            f"Internal error: '{label}' is not unique per item code "
            f"(examples: {', '.join(map(str, examples))})."
        )


# ---------------------------------------------------------------------------
# The aggregation helper
# ---------------------------------------------------------------------------
def aggregate_by_sku(
    data: pd.DataFrame,
    sku_column: str,
    value_columns: list[str],
    output_names: list[str],
    *,
    dropna: bool = True,
) -> pd.DataFrame:
    """Reduce transactional rows to exactly one row per item code."""
    if data.empty:
        empty = pd.DataFrame(columns=["الكود", *output_names])
        return empty.astype({"الكود": "string"})

    grouped = (
        data.groupby(sku_column, as_index=False, dropna=dropna, sort=False)[value_columns]
        .sum()
        .rename(columns=dict(zip([sku_column, *value_columns], ["الكود", *output_names])))
    )
    assert_unique_sku(grouped, f"aggregated {sku_column}")
    return grouped


def aggregate_stock(
    data: pd.DataFrame,
    sku_column: str,
    *,
    pack_size: pd.Series | None = None,
    value_name: str = "Stock",
    clip_negative: bool = False,
) -> pd.DataFrame:
    """Aggregate a stock file into one row per item code.

    The ERP's own ``الكمية`` is the pack-equivalent quantity and is the
    authoritative value, so it is summed as reported.  The pack arithmetic
    (``عبوات + اجزاء ÷ master's الاجزاء``) is verified alongside it and the
    number of rows that disagree is reported as ``Stock_Row_Corrections`` so
    a data problem is visible instead of silently absorbed.

    ``value_name`` is the name of the summed column in the result -- the
    branch file and the central warehouse file must not share a name,
    because both are joined onto the same driver frame.

    ``clip_negative`` turns every negative quantity into zero *before* the
    sum.  The central warehouse uses it: a physical shelf cannot hold a
    negative number, and a negative balance in one store must never consume
    another store's positive balance.  The branch snapshot is left untouched
    because a negative branch position is a real signal that the transfers
    ledger has to explain.
    """
    if data.empty:
        return pd.DataFrame(
            columns=[
                "الكود",
                value_name,
                "Branch_Negative_Flag",
                "Stock_Row_Corrections",
            ]
        )

    frame = data.copy()
    reported = pd.to_numeric(frame[QUANTITY_COLUMN], errors="coerce").fillna(0.0)

    if pack_size is not None and not pack_size.empty:
        # ``map`` and not ``reindex``: a ledger may repeat an item code, and
        # a reindex on duplicated labels raises.
        sizes = frame[sku_column].astype("string").map(pack_size).fillna(1.0)
    else:
        sizes = pd.Series(1.0, index=frame.index)

    if PACKS_COLUMN in frame.columns and PIECES_COLUMN in frame.columns:
        derived = compute_pack_equivalent(
            frame[PACKS_COLUMN], frame[PIECES_COLUMN], sizes
        )
        corrections = int(((reported - derived).abs() > 1e-6).sum())
    else:
        corrections = 0

    frame["_stock_value"] = reported.clip(lower=0.0) if clip_negative else reported
    frame["_stock_negative"] = reported < 0

    grouped = (
        frame.groupby(sku_column, as_index=False, sort=False)
        .agg(
            Stock=("_stock_value", "sum"),
            Branch_Negative_Flag=("_stock_negative", "any"),
            Stock_Row_Corrections=("_stock_value", "size"),
        )
        .rename(columns={sku_column: "الكود"})
    )
    grouped["Stock_Row_Corrections"] = grouped["Stock_Row_Corrections"].astype("int64")
    if value_name != "Stock":
        grouped = grouped.rename(columns={"Stock": value_name})
    assert_unique_sku(grouped, "stock")
    return grouped


# ---------------------------------------------------------------------------
# Master data preparation
# ---------------------------------------------------------------------------
def prepare_master_data(master_data: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicated master cards without losing information.

    Conflicting values are resolved column by column: the first non-empty
    value wins.  Nothing is raised -- a duplicated catalogue card must never
    stop a purchase run.
    """
    if master_data.empty:
        return master_data.copy()

    frame = master_data.copy()
    frame["_order"] = range(len(frame))
    frame = frame.sort_values("_order", kind="stable")
    deduplicated = frame.drop_duplicates("كود الصنف", keep="first")
    return deduplicated.drop(columns="_order").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Transfer semantics
# ---------------------------------------------------------------------------
def _compile_token_pattern(tokens: Iterable[str]) -> re.Pattern[str]:
    """Compile a token-boundary pattern for a group of operation tokens.

    The definite article is optional, so ``ارسال`` also matches
    ``الارسال`` -- Arabic exports are not consistent about it.
    """
    alternatives = "|".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<!\w)(?:ال)?(?:{alternatives})(?!\w)")


_OUT_PATTERN = _compile_token_pattern(TRANSFER_OUT_TOKENS)
_IN_PATTERN = _compile_token_pattern(TRANSFER_IN_TOKENS)


def classify_operations(transfers: pd.DataFrame) -> pd.Series:
    """Classify every transfer row as outgoing / incoming / ambiguous / unknown."""
    if transfers.empty:
        return pd.Series(dtype="string")
    text = transfers["العملية"].astype("string").map(normalize_operation)
    has_out = text.str.contains(_OUT_PATTERN, na=False)
    has_in = text.str.contains(_IN_PATTERN, na=False)

    classification = pd.Series(OPERATION_UNKNOWN, index=transfers.index, dtype="string")
    classification.loc[has_out & ~has_in] = OPERATION_OUTGOING
    classification.loc[has_in & ~has_out] = OPERATION_INCOMING
    classification.loc[has_out & has_in] = OPERATION_AMBIGUOUS
    return classification


def transfer_magnitudes(
    transfers: pd.DataFrame,
    pack_size: pd.Series | None = None,
) -> pd.Series:
    """Return the pack-equivalent movement magnitude of every transfer row.

    The row *net* is computed first and then made positive, so a row such as
    ``عبوات=26, اجزاء=-3`` contributes ``23`` and not ``29``.
    """
    if transfers.empty:
        return pd.Series(dtype="float64")

    packs = pd.to_numeric(transfers[PACKS_COLUMN], errors="coerce").fillna(0.0)
    pieces = pd.to_numeric(transfers[PIECES_COLUMN], errors="coerce").fillna(0.0)

    if pack_size is not None and not pack_size.empty:
        sku_column = next(
            (column for column in ("كود الصنف", "الكود") if column in transfers.columns),
            None,
        )
        if sku_column is not None:
            # the transfer ledger repeats item codes -- a reindex would raise
            sizes = transfers[sku_column].astype("string").map(pack_size).fillna(1.0)
        else:
            sizes = pd.Series(1.0, index=transfers.index)
    else:
        sizes = pd.Series(1.0, index=transfers.index)

    net = compute_pack_equivalent(packs, pieces, sizes)
    magnitude = net.abs()
    cancelling = (net == 0) & ((packs != 0) | (pieces != 0))
    fallback = packs.abs() + pieces.abs()
    return magnitude.mask(cancelling, fallback)


def detect_transfer_sign_convention(outgoing_rows: pd.DataFrame) -> str:
    """Detect whether outgoing rows are stored with negative or positive numbers."""
    if outgoing_rows.empty:
        return "unsigned"
    net = (
        pd.to_numeric(outgoing_rows[PACKS_COLUMN], errors="coerce").fillna(0.0)
        + pd.to_numeric(outgoing_rows[PIECES_COLUMN], errors="coerce").fillna(0.0)
    )
    nonzero = net[net != 0]
    if nonzero.empty:
        return "unsigned"
    return "signed" if float((nonzero < 0).mean()) > 0.5 else "unsigned"


def build_transfer_aggregates(
    transfers: pd.DataFrame,
    pack_size: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aggregate outgoing, incoming and ambiguous transfer movements.

    Rows whose operation is ambiguous or unknown are EXCLUDED from the stock
    formula but reported so a human can classify them.
    """
    if transfers.empty:
        empty = pd.DataFrame(columns=["الكود", "Transfers_Out"])
        return (
            empty,
            empty.rename(columns={"Transfers_Out": "Transfers_In"}),
            pd.DataFrame(columns=["الكود", "Ambiguous_Quantity", "Ambiguous_Rows"]),
        )

    frame = transfers.copy()
    frame["Operation_Class"] = classify_operations(frame)
    frame["Transfer_Magnitude"] = transfer_magnitudes(frame, pack_size)

    outgoing_rows = frame.loc[frame["Operation_Class"] == OPERATION_OUTGOING].copy()
    incoming_rows = frame.loc[frame["Operation_Class"] == OPERATION_INCOMING].copy()
    unresolved_rows = frame.loc[
        frame["Operation_Class"].isin([OPERATION_AMBIGUOUS, OPERATION_UNKNOWN])
    ].copy()

    outgoing = aggregate_by_sku(
        outgoing_rows, "كود الصنف", ["Transfer_Magnitude"], ["Transfers_Out"]
    )
    incoming = aggregate_by_sku(
        incoming_rows, "كود الصنف", ["Transfer_Magnitude"], ["Transfers_In"]
    )
    unresolved = (
        unresolved_rows.groupby("كود الصنف", as_index=False, sort=False)
        .agg(
            Ambiguous_Quantity=("Transfer_Magnitude", "sum"),
            Ambiguous_Rows=("Transfer_Magnitude", "size"),
        )
        .rename(columns={"كود الصنف": "الكود"})
    )
    return outgoing, incoming, unresolved
