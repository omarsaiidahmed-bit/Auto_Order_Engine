"""The demand spine -- how a monthly demand figure is derived for every item.

Three signals exist in a branch folder and they disagree:

1. **The historical sales panel** (``branch x month``).  This is the only
   source that is a *monthly rate* by construction and the only one that
   yields a real per-item standard deviation.
2. **The ERP's monthly average** (``المتوسط``).  Measured on a real export it
   is zero for 66.9% of the items that actually sell, and about 11% low where
   it is populated.
3. **The recent branch sales report.**  A short window (20 days in the
   measured export).  Comparing it with a 30-day figure without rescaling
   over-weights it by exactly ``30 / 20``.

The rules implemented here:

* every signal is first expressed as a **monthly rate**;
* the demand is the **maximum** of the available signals, which is the
  business rule ("monthly average *or* recent sales") with the window bug
  fixed;
* the standard deviation is the real sample deviation of the recent sales
  report's last months, then the ERP's own deviation, then the panel's sample
  deviation, and finally a 25%-of-``المتوسط`` coefficient-of-variation
  fallback.  The fallback is used only when there is no measurable dispersion;
  a measured sigma of zero is treated as "no information", not as zero risk.

The contract
------------
:func:`build_demand_spine` is the only entry point and it is **index based**:
``universe`` is the catalogue (one SKU per row) and *every* other input
series is indexed by the same SKU.  The function never aligns on row
position, so a filtered or re-ordered input can never silently shift an
item's demand onto another item's row.

Units
-----
Every quantity handled here is a **monthly rate in packs**
(``pack-equivalents``).  The ERP's ``الكمية`` is already a pack-equivalent
(``الكمية = عبوات + اجزاء ÷ master's اجزاء``), so no piece arithmetic
happens in this module -- see :mod:`core.quantity` for that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from app_config import (
    DAYS_PER_MONTH,
    MIN_SIGMA_OBSERVATIONS,
    RECENT_SIGMA_MIN_MONTHS,
    RECENT_SIGMA_MONTHS,
)
from core.normalize import normalize_arabic_text, parse_date_series

__all__ = [
    "DemandSpine",
    "aggregate_family_demand",
    "aggregate_sales_by_sku",
    "build_demand_spine",
    "detect_sales_window_days",
    "monthly_sales_average",
    "panel_monthly_statistics",
    "recent_monthly_statistics",
    "shortage_recent_average",
]


# ---------------------------------------------------------------------------
# Provenance labels -- the source that won for each item
# ---------------------------------------------------------------------------

SOURCE_PANEL = "لوحة المبيعات"
SOURCE_ERP = "متوسط النظام"
SOURCE_RECENT = "المبيعات الحديثة"
SOURCE_NONE = "لا يوجد"
SOURCE_SHORTAGE = "متوسط شيت النواقص"

#: Provenance labels for the standard deviation.
SIGMA_SOURCE_RECENT = "انحراف المبيعات الحديثة"
SIGMA_SOURCE_ERP = "انحراف النظام"
SIGMA_SOURCE_PANEL = "انحراف لوحة المبيعات"
SIGMA_SOURCE_FALLBACK = "نسبة الاحتياطي"

#: The identity columns of a panel block -- everything else is a month.
PANEL_IDENTITY_COLUMNS: frozenset[str] = frozenset({"sku", "name", "category", "price"})

#: The date columns a sales report may use.
SALES_DATE_COLUMNS: tuple[str, ...] = ("التاريخ", "تاريخ البيع")


@dataclass(frozen=True)
class DemandSpine:
    """The per-item demand result.

    ``frame`` is indexed by SKU and carries:

    ``Demand``
        the monthly demand in packs -- the value the engine orders against;
    ``Monthly_Mean``
        the ERP's own monthly average (the raw signal, not the winner);
    ``Panel_Mean``
        the panel's monthly rate (NaN when the panel is unavailable);
    ``Recent_Monthly``
        the recent sales report rescaled to a monthly rate;
    ``Monthly_Sigma``
        the monthly standard deviation used by the safety stock;
    ``Sigma_Observations``
        how many monthly totals actually fed the deviation (``0`` when the
        ERP value or the coefficient of variation was used instead);
    ``Sigma_Source``
        which signal produced ``Monthly_Sigma``;
    ``Demand_Source``
        which signal produced ``Demand``.
    """

    frame: pd.DataFrame
    panel_available: bool = False
    panel_branch: str = ""
    panel_months: int = 0
    recent_days: int = DAYS_PER_MONTH

    @property
    def daily_rate(self) -> pd.Series:
        """The daily demand per item, derived from the monthly rate."""
        return self.frame["Demand"] / float(DAYS_PER_MONTH)

    @property
    def moving_items(self) -> int:
        """How many catalogue items have a positive monthly demand."""
        return int((self.frame["Demand"] > 0).sum())


# ---------------------------------------------------------------------------
# The historical panel
# ---------------------------------------------------------------------------
def panel_monthly_statistics(
    block: pd.DataFrame,
    *,
    min_observations: int = MIN_SIGMA_OBSERVATIONS,
) -> pd.DataFrame:
    """Reduce one branch block of the sales panel to monthly statistics.

    A month in which the item did not move is a **zero**, not a missing
    observation: the panel lists every catalogue item, so an empty cell means
    "no sale in that month".  The monthly rate is therefore
    ``total sold / number of months owned by the branch``.

    Duplicate SKUs are summed before the statistics are computed, so the
    result is guaranteed to have a unique index.

    Returns a frame indexed by SKU with the columns ``Panel_Mean``,
    ``Panel_Sigma``, ``Panel_Observations`` and ``Panel_Total``.
    """
    empty = pd.DataFrame(
        columns=["Panel_Mean", "Panel_Sigma", "Panel_Observations", "Panel_Total"]
    )
    if block is None or block.empty:
        return empty

    months = [column for column in block.columns if column not in PANEL_IDENTITY_COLUMNS]
    if not months or "sku" not in block.columns:
        return empty

    values = block.loc[:, months].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    month_count = len(months)

    # one row per SKU -- a SKU that appears twice has its months added up
    grouped = values.groupby(block["sku"].astype("string"), sort=False).sum()

    result = pd.DataFrame(index=grouped.index)
    result["Panel_Total"] = grouped.sum(axis=1)
    result["Panel_Mean"] = result["Panel_Total"] / month_count
    result["Panel_Observations"] = month_count

    if month_count >= 2:
        sigma = grouped.std(axis=1, ddof=1)
    else:
        sigma = pd.Series(np.nan, index=grouped.index, dtype="float64")
    # the deviation is only trusted once the branch owns enough months
    result["Panel_Sigma"] = (
        sigma if month_count >= min_observations else pd.Series(
            np.nan, index=grouped.index, dtype="float64"
        )
    )
    result.index = result.index.astype("string")
    return result


def count_panel_months(block: pd.DataFrame | None) -> int:
    """How many month columns a panel block owns."""
    if block is None or block.empty:
        return 0
    return len([column for column in block.columns if column not in PANEL_IDENTITY_COLUMNS])


# ---------------------------------------------------------------------------
# The recent sales report
# ---------------------------------------------------------------------------
def detect_sales_window_days(sales: pd.DataFrame) -> int:
    """Return how many calendar days the recent sales report covers.

    The window length matters: a 20-day report must be rescaled by
    ``30 / 20`` before it is comparable with a monthly rate.  When the file
    carries no usable dates the window is assumed to be a full month.

    The day/month order is detected from the values themselves -- a fixed
    ``dayfirst`` flag would read the ERP's ``2026/10/03`` as the 3rd of
    October and stretch a twenty-day report into a three-hundred-and-thirty-
    five-day one.
    """
    if sales is None or sales.empty:
        return DAYS_PER_MONTH

    for column in SALES_DATE_COLUMNS:
        if column not in sales.columns:
            continue
        parsed = parse_date_series(sales[column])
        if parsed.notna().sum() < 2:
            continue
        span = (parsed.max() - parsed.min()).days + 1
        if 1 <= span <= 366:
            return int(span)
    return DAYS_PER_MONTH


def aggregate_sales_by_sku(
    sales: pd.DataFrame,
    *,
    sku_column: str = "كود الصنف",
    quantity_column: str = "الكمية",
) -> pd.Series:
    """Sum the recent sales report into one quantity per SKU.

    The quantity is the ERP's pack-equivalent ``الكمية``; the rescaling to a
    monthly rate happens in :func:`build_demand_spine`, which knows the
    window length.  Returns an empty series when the file does not carry the
    expected columns.
    """
    if sales is None or sales.empty:
        return pd.Series(dtype="float64")
    if sku_column not in sales.columns or quantity_column not in sales.columns:
        return pd.Series(dtype="float64")

    frame = pd.DataFrame(
        {
            "sku": sales[sku_column].astype("string"),
            "quantity": pd.to_numeric(sales[quantity_column], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["sku"])
    frame["quantity"] = frame["quantity"].fillna(0.0)
    return frame.groupby("sku", sort=False)["quantity"].sum()


def recent_monthly_statistics(
    sales: pd.DataFrame,
    *,
    sku_column: str = "كود الصنف",
    quantity_column: str = "الكمية",
    window_months: int = RECENT_SIGMA_MONTHS,
    min_observations: int = RECENT_SIGMA_MIN_MONTHS,
) -> pd.DataFrame:
    """Reduce the recent sales report to a real monthly mean and deviation.

    The report is a transaction ledger, not a monthly matrix: one item can
    appear many times on the same day.  The ledger is therefore grouped by
    **calendar month** first, and the deviation is computed over the monthly
    totals of the most recent ``window_months`` months present in the file.

    A month in which the item does not appear is a **zero**, not a missing
    observation -- the report is a sales export, so silence means no sale.  A
    SKU that is completely absent from the window is absent from the result
    and falls through to the caller's fallback.

    The result is indexed by SKU and carries ``Recent_Total``,
    ``Recent_Mean``, ``Recent_Sigma``, ``Recent_Observations`` and
    ``Recent_Window_Months``.  ``Recent_Sigma`` is the sample deviation
    (``ddof=1``); it may be zero when the item sold exactly the same quantity
    every month, which the caller treats as "no measurable dispersion".
    """
    columns = [
        "Recent_Total",
        "Recent_Mean",
        "Recent_Sigma",
        "Recent_Observations",
        "Recent_Window_Months",
    ]
    empty = pd.DataFrame(columns=columns)

    if sales is None or sales.empty:
        return empty
    if sku_column not in sales.columns or quantity_column not in sales.columns:
        return empty

    date_column = next(
        (column for column in SALES_DATE_COLUMNS if column in sales.columns),
        None,
    )
    if date_column is None:
        # Without dates there is no monthly series to measure.  The caller
        # must fall back to the coefficient of variation.
        return empty

    frame = pd.DataFrame(
        {
            "sku": sales[sku_column].astype("string"),
            "quantity": pd.to_numeric(sales[quantity_column], errors="coerce").fillna(0.0),
            "date": parse_date_series(sales[date_column]),
        }
    )
    frame = frame.dropna(subset=["sku", "date"])
    if frame.empty:
        return empty

    frame["period"] = frame["date"].dt.to_period("M")
    periods = sorted(frame["period"].unique())[-max(1, int(window_months)) :]
    if len(periods) < max(2, int(min_observations)):
        return empty

    window = frame.loc[frame["period"].isin(periods)]
    grouped = (
        window.groupby(["sku", "period"], sort=False)["quantity"]
        .sum()
        .unstack("period")
        .reindex(columns=periods)
        .fillna(0.0)
    )
    if grouped.empty:
        return empty

    result = pd.DataFrame(index=grouped.index)
    result["Recent_Total"] = grouped.sum(axis=1)
    result["Recent_Mean"] = result["Recent_Total"] / float(len(periods))
    result["Recent_Sigma"] = grouped.std(axis=1, ddof=1)
    result["Recent_Observations"] = int(len(periods))
    result["Recent_Window_Months"] = int(len(periods))
    result.index = result.index.astype("string")
    return result


#: Arabic month names and their Levantine/English aliases, keyed by month.
_MONTH_ALIASES: dict[int, tuple[str, ...]] = {
    1: ("يناير", "كانون الثاني", "january", "jan"),
    2: ("فبراير", "شباط", "february", "feb"),
    3: ("مارس", "اذار", "march", "mar"),
    4: ("ابريل", "نيسان", "april", "apr"),
    5: ("مايو", "ايار", "may"),
    6: ("يونيو", "حزيران", "june", "jun"),
    7: ("يوليو", "يوليه", "تموز", "july", "jul"),
    8: ("اغسطس", "اب", "august", "aug"),
    9: ("سبتمبر", "ايلول", "september", "sep", "sept"),
    10: ("اكتوبر", "تشرين الاول", "october", "oct"),
    11: ("نوفمبر", "تشرين الثاني", "november", "nov"),
    12: ("ديسمبر", "كانون الاول", "december", "dec"),
}

_CODE_COLUMN_CANDIDATES = ("كود الصنف", "الكود", "كود", "sku", "SKU")


def _month_number_from_label(value: object) -> int | None:
    """Return the calendar month encoded in a column label, if any.

    Handles plain month names and labels such as ``مبيعات أغسطس``.  The
    text is normalised first, so ``أغسطس`` and ``اغسطس`` are equivalent.
    A label that is only a number (``8`` or ``08``) is also accepted.
    """
    text = normalize_arabic_text(value).casefold()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 12 else None
    tokens = set(re.findall(r"[^\W_]+", text))
    for month, aliases in _MONTH_ALIASES.items():
        for alias in aliases:
            if alias in tokens or (len(alias) >= 4 and alias in text):
                return month
    # Support numeric month labels and the ``month_8`` columns produced by
    # the historical-sales pivot builder.
    match = re.search(r"(?<!\d)(0?[1-9]|1[0-2])(?!\d)", text)
    if match:
        return int(match.group(1))
    return None


def monthly_sales_average(
    frame: pd.DataFrame | None,
    *,
    order_date: date | datetime | None,
    months: int = 4,
    sku_column: str | None = None,
) -> pd.Series:
    """Average the last ``months`` calendar months of month-labelled columns.

    This is the preferred shortage fallback.  It works on either the uploaded
    shortage report (when it carries ``مبيعات أغسطس`` / ``مبيعات سبتمبر`` ...
    columns) or on the historical sales panel (whose columns are plain month
    names).  The window ends at ``order_date``'s month and has a fixed length,
    so a month that is absent from the file counts as a real zero and the
    total is still divided by ``months``.

    Returns a SKU-indexed series named ``Monthly_Columns_Average``.  It is
    empty when no month-labelled column can be found.
    """
    empty = pd.Series(dtype="float64", name="Monthly_Columns_Average")
    if frame is None or frame.empty or order_date is None:
        return empty
    if isinstance(order_date, datetime):
        order_date = order_date.date()

    months = max(1, int(months))
    month_columns: dict[int, list[object]] = {}
    for column in frame.columns:
        month = _month_number_from_label(column)
        if month is not None:
            month_columns.setdefault(month, []).append(column)
    if not month_columns:
        return empty

    code_column = sku_column if sku_column in frame.columns else None
    if code_column is None:
        code_column = next(
            (column for column in _CODE_COLUMN_CANDIDATES if column in frame.columns),
            None,
        )
    if code_column is None:
        return empty

    end_month = int(order_date.month)
    window = [
        ((end_month - offset - 1) % 12) + 1 for offset in range(months)
    ]

    total = pd.Series(0.0, index=frame.index, dtype="float64")
    for month in window:
        columns = month_columns.get(month)
        if not columns:
            continue
        for column in columns:
            values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
            total = total.add(values, fill_value=0.0)

    frame_sku = frame[code_column].astype("string").str.strip()
    grouped = total.groupby(frame_sku, sort=False).sum()
    grouped = grouped[~grouped.index.isna()]
    grouped = grouped[grouped.index != ""]
    if grouped.empty:
        return empty

    result = (grouped / float(months)).clip(lower=0.0)
    result.index = result.index.astype("string")
    result.name = "Monthly_Columns_Average"
    return result


def shortage_recent_average(
    sales: pd.DataFrame | None,
    *,
    order_date: date | datetime | None,
    months: int = 4,
    sku_column: str = "كود الصنف",
    quantity_column: str = "الكمية",
) -> pd.Series:
    """Monthly average from the last calendar months of the sales ledger.

    This is the fallback used only when the shortage report carries a zero
    (or missing) ``المتوسط``.  The window ends at ``order_date``'s calendar
    month and contains that month plus the previous ``months - 1`` months.
    A month with no sale is a real zero, so the total is divided by the full
    window length, not by the number of months that happen to appear in the
    file.

    Returns a SKU-indexed series named ``Shortage_Recent_Average``.  It is
    empty when the ledger has no usable date/quantity columns or when
    ``order_date`` is not supplied.
    """
    empty = pd.Series(dtype="float64", name="Shortage_Recent_Average")
    if sales is None or sales.empty or order_date is None:
        return empty
    if sku_column not in sales.columns or quantity_column not in sales.columns:
        return empty

    date_column = next(
        (column for column in SALES_DATE_COLUMNS if column in sales.columns),
        None,
    )
    if date_column is None:
        return empty

    if isinstance(order_date, datetime):
        order_date = order_date.date()

    frame = pd.DataFrame(
        {
            "sku": sales[sku_column].astype("string"),
            "quantity": pd.to_numeric(
                sales[quantity_column], errors="coerce"
            ).fillna(0.0),
            "date": parse_date_series(sales[date_column]),
        }
    )
    frame = frame.dropna(subset=["sku", "date"])
    frame = frame.loc[frame["date"] <= pd.Timestamp(order_date)]
    if frame.empty:
        return empty

    end_period = pd.Period(pd.Timestamp(order_date), freq="M")
    periods = pd.period_range(
        end=end_period,
        periods=max(1, int(months)),
        freq="M",
    )
    frame["period"] = frame["date"].dt.to_period("M")
    window = frame.loc[frame["period"].isin(periods)]
    if window.empty:
        return empty

    grouped = (
        window.groupby(["sku", "period"], sort=False)["quantity"]
        .sum()
        .unstack("period")
        .reindex(columns=periods)
        .fillna(0.0)
    )
    if grouped.empty:
        return empty

    result = grouped.sum(axis=1) / float(len(periods))
    result = result.clip(lower=0.0)
    result.index = result.index.astype("string")
    result.name = "Shortage_Recent_Average"
    return result


# ---------------------------------------------------------------------------
# The spine
# ---------------------------------------------------------------------------
def _align_to_universe(
    series: pd.Series | None,
    index: pd.Index,
    *,
    fill: float = 0.0,
) -> pd.Series:
    """Align a SKU-indexed series onto the catalogue.

    The series is expected to be indexed by SKU.  A series that still carries
    the default ``RangeIndex`` is accepted as *positional* (this keeps the
    pipeline forgiving), but an indexed series is always matched **by SKU**
    so a mis-ordered input can never shift values between items.
    """
    if series is None:
        return pd.Series(fill, index=index, dtype="float64")
    if len(series) == 0:
        return pd.Series(fill, index=index, dtype="float64")

    cleaned = pd.to_numeric(series, errors="coerce")
    if isinstance(cleaned.index, pd.RangeIndex) and len(cleaned) == len(index):
        cleaned = pd.Series(cleaned.to_numpy(), index=index, dtype="float64")
        return cleaned.fillna(fill)

    cleaned = cleaned.copy()
    cleaned.index = cleaned.index.astype("string")
    return cleaned.reindex(index).fillna(fill)


def _align_optional_to_universe(
    series: pd.Series | None,
    index: pd.Index,
) -> pd.Series:
    """Align a series that may legitimately be missing (``NaN`` means absent)."""
    if series is None or len(series) == 0:
        return pd.Series(np.nan, index=index, dtype="float64")

    cleaned = pd.to_numeric(series, errors="coerce")
    if isinstance(cleaned.index, pd.RangeIndex) and len(cleaned) == len(index):
        return pd.Series(cleaned.to_numpy(), index=index, dtype="float64")

    cleaned = cleaned.copy()
    cleaned.index = cleaned.index.astype("string")
    return cleaned.reindex(index)


def aggregate_family_demand(
    family_key: pd.Series,
    target_demand: pd.Series,
    *,
    average: pd.Series | None = None,
    calculated_order: pd.Series | None = None,
    branch_stock: pd.Series | None = None,
    warehouse_stock: pd.Series | None = None,
) -> pd.DataFrame:
    """Pool demand and stock for every exact product family.

    The rows are aligned by index, so the result can be assigned directly back
    onto the catalogue.  ``Family_Target`` is the sum of the per-card
    ``Target_Demand`` values -- the same target the pipeline already uses
    (monthly average + ROP + safety stock).  ``Family_Average_Sum`` and
    ``Family_Calculated_Sum`` are retained for diagnostics and for the buyer's
    audit trail.

    ``Family_Net_Need`` is the only quantity the aggregation rule consumes:
    it is ``Family_Target - Family_Stock`` floored at zero.  A family whose
    stock covers its target therefore produces a zero net need for every
    sibling, not a separate order on each card.
    """

    index = target_demand.index
    if len(index) == 0:
        return pd.DataFrame(
            columns=[
                "Family_Group_Size",
                "Family_Target",
                "Family_Average_Sum",
                "Family_Calculated_Sum",
                "Family_Branch_Stock",
                "Family_Warehouse_Stock",
                "Family_Stock",
                "Family_Net_Need",
            ],
            index=index,
        )

    def _number(series: pd.Series | None) -> pd.Series:
        if series is None:
            return pd.Series(0.0, index=index, dtype="float64")
        return (
            pd.to_numeric(series.reindex(index), errors="coerce")
            .fillna(0.0)
            .astype("float64")
        )

    keys = family_key.reindex(index).astype("string").fillna("").str.strip()
    # An empty identity must never pool unrelated no-name cards together.
    empty_keys = keys.eq("")
    if bool(empty_keys.any()):
        keys = keys.copy()
        replacement = [
            f"__row_{position}"
            for position, is_empty in enumerate(empty_keys.to_numpy())
            if bool(is_empty)
        ]
        keys.loc[empty_keys] = replacement

    frame = pd.DataFrame(
        {
            "Family_Key": keys,
            "Target_Demand": _number(target_demand).clip(lower=0.0),
            "Average": _number(average),
            "Calculated_Order": _number(calculated_order).clip(lower=0.0),
            "Branch_Stock": _number(branch_stock),
            "Warehouse_Stock": _number(warehouse_stock),
        },
        index=index,
    )
    grouped = frame.groupby("Family_Key", sort=False)
    result = pd.DataFrame(index=index)
    result["Family_Group_Size"] = (
        grouped["Target_Demand"].transform("size").astype("int64")
    )
    result["Family_Target"] = grouped["Target_Demand"].transform("sum")
    result["Family_Average_Sum"] = grouped["Average"].transform("sum")
    result["Family_Calculated_Sum"] = grouped[
        "Calculated_Order"
    ].transform("sum")
    result["Family_Branch_Stock"] = grouped["Branch_Stock"].transform("sum")
    result["Family_Warehouse_Stock"] = grouped[
        "Warehouse_Stock"
    ].transform("sum")
    result["Family_Stock"] = (
        result["Family_Branch_Stock"] + result["Family_Warehouse_Stock"]
    )
    result["Family_Net_Need"] = (
        result["Family_Target"] - result["Family_Stock"]
    ).clip(lower=0.0)
    return result


def build_demand_spine(
    universe: pd.Series,
    *,
    erp_average: pd.Series | None = None,
    erp_std_dev: pd.Series | None = None,
    recent_sales: pd.Series | None = None,
    recent_sales_frame: pd.DataFrame | None = None,
    shortage_frame: pd.DataFrame | None = None,
    recent_sigma: pd.Series | None = None,
    recent_observations: pd.Series | None = None,
    recent_days: int = DAYS_PER_MONTH,
    order_date: date | datetime | None = None,
    panel_block: pd.DataFrame | None = None,
    panel_branch: str = "",
    cv_fallback: float = 0.25,
    source_mode: str = "auto",
    shortage_universe: pd.Index | None = None,
) -> DemandSpine:
    """Build the monthly demand and the monthly standard deviation.

    Parameters
    ----------
    universe:
        The catalogue -- one SKU per row.  It defines the index of the
        result and therefore the order of the final export.
    erp_average:
        The ERP's ``المتوسط`` (monthly rate, packs), indexed by SKU.
    erp_std_dev:
        The ERP's ``Monthly_StdDev`` (monthly standard deviation), indexed
        by SKU.  Missing values fall through to the next source.
    recent_sales:
        The **sum** of the recent sales report per SKU, in packs, over the
        whole window (not yet rescaled).
    recent_sales_frame:
        The raw recent-sales ledger.  In shortage mode it supplies the
        last-four-month average used when the uploaded ``المتوسط`` is zero
        or missing.  The fallback is available to every catalogue item with
        real recent sales, even when the shortage report omitted that item.
    shortage_frame:
        The raw shortage report.  When it carries month-labelled sales
        columns (``مبيعات أغسطس`` ...), their last-four-month average is the
        preferred fallback for a zero/missing ``المتوسط``.  The historical
        panel is used the same way when the shortage report has no such
        columns.
    recent_sigma:
        The real monthly standard deviation measured from the recent sales
        report's monthly totals (see :func:`recent_monthly_statistics`).
    recent_observations:
        How many monthly totals fed ``recent_sigma``.
    recent_days:
        How many calendar days the recent sales report covers.  Used to
        rescale it to a monthly rate.
    order_date:
        The order date.  It anchors the shortage fallback's four-month
        window.  Without it the fallback is not applied.
    shortage_universe:
        SKUs present in the shortage report.  The historical-panel fallback
        is restricted to those items, because the panel covers a much wider
        catalogue.  The recent-sales fallback is intentionally not restricted:
        an item with actual recent sales must still receive a demand figure
        even when the uploaded shortage report omitted it.
    panel_block:
        One branch's block of the historical sales panel (see
        :meth:`core.ingestion.SalesPanel.block`).
    cv_fallback:
        The coefficient of variation used only when no real standard
        deviation can be computed.  It is applied to the ERP monthly average
        (``المتوسط``), not to the final demand, and defaults to 25%.
    source_mode:
        ``auto``     -- the maximum of every available signal;
        ``panel``    -- the panel, with the recent sales as a safety net;
        ``erp``      -- the ERP average, with the recent sales as a safety net;
        ``shortage`` -- the raw shortage-sheet ``المتوسط`` exactly, with no
                        historical blend or day/month rescaling.  A zero or
                        missing value falls back to the last four calendar
                        months of the shortage report's own month-labelled
                        sales columns (or the historical panel when those
                        columns are absent), then to the recent-sales ledger.
    """
    index = pd.Index(universe.astype("string"), name="الكود")

    erp = _align_to_universe(erp_average, index).clip(lower=0.0)
    recent = _align_to_universe(recent_sales, index).clip(lower=0.0)

    # -- the historical panel ------------------------------------------------
    panel_mean = pd.Series(np.nan, index=index, dtype="float64")
    panel_sigma = pd.Series(np.nan, index=index, dtype="float64")
    panel_observations = pd.Series(0, index=index, dtype="int64")
    panel_months = 0
    panel_used = False

    # In shortage mode the panel is not a demand candidate.  Its raw month
    # columns are read by the four-month fallback above, so no panel summary
    # is needed there.  ERP mode deliberately does not consult it.
    if (
        panel_block is not None
        and not panel_block.empty
        and source_mode not in ("erp", "shortage")
    ):
        statistics = panel_monthly_statistics(panel_block)
        if not statistics.empty:
            statistics.index = statistics.index.astype("string")
            panel_mean = statistics["Panel_Mean"].reindex(index)
            panel_sigma = statistics["Panel_Sigma"].reindex(index)
            panel_observations = (
                statistics["Panel_Observations"]
                .reindex(index)
                .fillna(0)
                .astype("int64")
            )
            panel_months = count_panel_months(panel_block)
            panel_used = True

    # -- the recent sales report, rescaled to a monthly rate -----------------
    scale = DAYS_PER_MONTH / max(1, int(recent_days))
    recent_monthly = recent * scale

    # -- the demand itself ---------------------------------------------------
    if source_mode == "shortage":
        # Exact shortage-sheet average. No panel blend, no recent-sales blend
        # and no day/month rescaling. ``erp_average`` is the raw uploaded
        # المتوسط series.  A zero/NaN average is the one exception.
        demand = erp.copy()

        # Preferred fallback: the average of the last four calendar months
        # read from month-labelled sales columns.  The uploaded shortage
        # report wins when it carries columns such as ``مبيعات أغسطس``;
        # the historical panel fills any item the report leaves at zero.
        four_month_shortage = monthly_sales_average(
            shortage_frame,
            order_date=order_date,
            months=4,
        )
        four_month_panel = monthly_sales_average(
            panel_block,
            order_date=order_date,
            months=4,
        )

        fallback_mean = _align_to_universe(
            four_month_shortage, index
        ).clip(lower=0.0)
        panel_mean_four = _align_to_universe(
            four_month_panel, index
        ).clip(lower=0.0)
        if shortage_universe is not None:
            in_shortage = pd.Series(
                index.isin(shortage_universe),
                index=index,
                dtype=bool,
            )
            panel_mean_four = panel_mean_four.where(in_shortage, 0.0)
        fallback_mean = fallback_mean.where(
            fallback_mean > 0, panel_mean_four
        )

        # The recent ledger is the **last** resort, never the first: it is
        # used only for an item the four-month columns still leave at zero.
        # It is intentionally not restricted to the shortage report, because
        # an item with actual recent sales must still receive a demand figure
        # even when the uploaded shortage sheet omitted it.
        recent_fallback = _align_to_universe(
            shortage_recent_average(
                recent_sales_frame,
                order_date=order_date,
                months=4,
            ),
            index,
        ).clip(lower=0.0)
        fallback_mean = fallback_mean.where(
            fallback_mean > 0, recent_fallback
        )

        needs_fallback = demand.isna() | (demand <= 0)
        demand = demand.where(~needs_fallback, fallback_mean)
        demand = demand.fillna(0.0).clip(lower=0.0)
        source = pd.Series(SOURCE_NONE, index=index, dtype="string")
        source = source.mask(demand > 0, SOURCE_SHORTAGE)
    else:
        if source_mode == "panel":
            candidates = pd.concat([panel_mean, recent_monthly], axis=1)
        elif source_mode == "erp":
            candidates = pd.concat([erp, recent_monthly], axis=1)
        else:  # auto
            candidates = pd.concat([panel_mean, erp, recent_monthly], axis=1)

        demand = candidates.max(axis=1, skipna=True)
        demand = demand.fillna(0.0).clip(lower=0.0)

        # -- which signal won ------------------------------------------------
        has_panel = panel_mean.notna()
        has_erp = erp > 0
        has_recent = recent_monthly > 0

        source = pd.Series(SOURCE_NONE, index=index, dtype="string")
        source = source.mask(has_panel & (demand == panel_mean), SOURCE_PANEL)
        source = source.mask(
            (~has_panel | (demand != panel_mean)) & has_erp & (demand == erp),
            SOURCE_ERP,
        )
        source = source.mask(
            (~has_panel | (demand != panel_mean))
            & (~has_erp | (demand != erp))
            & has_recent
            & (demand == recent_monthly),
            SOURCE_RECENT,
        )

    # -- the standard deviation ------------------------------------------------
    # The chain is: the real deviation of the recent sales report's monthly
    # totals, then the ERP's own deviation, then the panel's sample deviation,
    # then the coefficient of variation.  A deviation of **zero** carries no
    # information (it usually means "the item never moved"), so it is treated
    # as absent and the next source is used instead.
    provided = _align_optional_to_universe(erp_std_dev, index)
    recent_sigma_aligned = _align_optional_to_universe(recent_sigma, index)
    recent_obs_aligned = (
        _align_to_universe(recent_observations, index).round().astype("int64")
    )

    fallback_sigma = (erp.clip(lower=0.0) * float(cv_fallback)).fillna(0.0).clip(lower=0.0)
    sigma = fallback_sigma.copy()
    sigma_source = pd.Series(SIGMA_SOURCE_FALLBACK, index=index, dtype="string")
    sigma_observations = pd.Series(0, index=index, dtype="int64")

    usable_panel_sigma = panel_sigma.where(panel_sigma.notna() & (panel_sigma > 0))
    panel_mask = usable_panel_sigma.notna()
    sigma = sigma.mask(panel_mask, usable_panel_sigma)
    sigma_source = sigma_source.mask(panel_mask, SIGMA_SOURCE_PANEL)
    sigma_observations = sigma_observations.mask(
        panel_mask, panel_observations.astype("int64")
    )

    usable_erp_sigma = provided.where(provided.notna() & (provided > 0))
    erp_mask = usable_erp_sigma.notna()
    sigma = sigma.mask(erp_mask, usable_erp_sigma)
    sigma_source = sigma_source.mask(erp_mask, SIGMA_SOURCE_ERP)
    sigma_observations = sigma_observations.mask(erp_mask, 0)

    usable_recent_sigma = recent_sigma_aligned.where(
        recent_sigma_aligned.notna() & (recent_sigma_aligned > 0)
    )
    recent_mask = usable_recent_sigma.notna()
    sigma = sigma.mask(recent_mask, usable_recent_sigma)
    sigma_source = sigma_source.mask(recent_mask, SIGMA_SOURCE_RECENT)
    sigma_observations = sigma_observations.mask(
        recent_mask, recent_obs_aligned
    )

    sigma = sigma.fillna(0.0).clip(lower=0.0)

    result = pd.DataFrame(index=index)
    result["Demand"] = demand.astype("float64")
    result["Monthly_Mean"] = erp.astype("float64")
    result["Panel_Mean"] = panel_mean.astype("float64")
    result["Recent_Monthly"] = recent_monthly.astype("float64")
    result["Recent_Sigma"] = recent_sigma_aligned.astype("float64")
    result["Monthly_Sigma"] = sigma.astype("float64")
    result["Sigma_Observations"] = sigma_observations.astype("int64")
    result["Sigma_Source"] = sigma_source.astype("string")
    result["Demand_Source"] = source

    return DemandSpine(
        frame=result,
        panel_available=panel_used,
        panel_branch=panel_branch,
        panel_months=panel_months,
        recent_days=int(recent_days),
    )
