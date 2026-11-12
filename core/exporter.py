"""The final Auto Order Excel writer.

The export contract is the 21-column order requested by the business:

``التصنيف``, ``الكود``, ``الاسم``, ``المطلوب``, ``السعر``,
``القيمة المالية للطلب``, ``الموجود في الفرع``, ``الموجود في المخزن``,
``التحويلات``, four dynamic monthly-sales columns, ``المتوسط``, ``ROP``,
``Substitutes``, ``Lead_Time``, ``تاريخ الوصول المتوقع``,
``تغطية المخزون (أيام)``, ``سبب الطلب`` and ``ملاحظات``.

The monthly columns are generated from the order date.  For an order on
2 November 2026, for example, the four columns are August, September, October
and November.  Historical cells remain blank -- never zero -- when the item
was not present in the uploaded historical-sales source.

Row colours are applied cell by cell so they survive Excel filters:

* pink / ``#FFC0CB`` -- warehouse loading (highest priority)
* blue / ``#ADD8E6`` -- pushing list
* yellow / ``#FFFFE0`` -- transfers
* grey / ``#D3D3D3`` -- more than one card / price

The workbook is written with ``constant_memory`` because a full catalogue can
contain tens of thousands of rows.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Callable, Iterable

import pandas as pd

from app_config import (
    ARABIC_MONTH_NAMES,
    EXCEL_CHUNK_SIZE,
    EXPORT_HEADER_BACKGROUND,
)
from core.normalize import clean_sku

__all__ = [
    "COLOR_MULTIPLE_CARDS",
    "COLOR_PUSHING",
    "COLOR_TRANSFER",
    "COLOR_WAREHOUSE",
    "EXPORT_COLUMNS",
    "build_export_columns",
    "export_columns_for_date",
    "export_styled_excel",
    "sales_columns_for_date",
]

ProgressCallback = Callable[[str], None]

COLOR_PUSHING = "#ADD8E6"
COLOR_MULTIPLE_CARDS = "#D3D3D3"
COLOR_TRANSFER = "#FFFFE0"
COLOR_WAREHOUSE = "#FFC0CB"

_FIXED_COLUMNS = [
    "التصنيف",
    "الكود",
    "الاسم",
    "المطلوب",
    "السعر",
    "القيمة المالية للطلب",
    "الموجود في الفرع",
    "الموجود في المخزن",
    "التحويلات",
]
_TRAILING_COLUMNS = [
    "المتوسط",
    "ROP",
    "Substitutes",
    "Lead_Time",
    "تاريخ الوصول المتوقع",
    "تغطية المخزون (أيام)",
    "سبب الطلب",
    "ملاحظات",
]

# The workbook is an Arabic deliverable.  These two internal calculation
# columns keep their stable English names inside the DataFrame, but the
# visible Excel header must be Arabic like every other header.
_ARABIC_HEADERS = {
    "ROP": "نقطة إعادة الطلب",
    "Lead_Time": "زمن التوريد",
}


def _month_sequence(order_date: date) -> tuple[int, int, int, int]:
    """Return the order month and the three months before it, in order."""
    months: list[int] = []
    for offset in (-3, -2, -1, 0):
        month = order_date.month + offset
        while month <= 0:
            month += 12
        while month > 12:
            month -= 12
        months.append(month)
    return tuple(months)  # type: ignore[return-value]


def sales_columns_for_date(order_date: date | datetime | None = None) -> list[str]:
    """Return the four dynamic sales headers for ``order_date``."""
    selected = order_date or date.today()
    if isinstance(selected, datetime):
        selected = selected.date()
    return [
        f"مبيعات {ARABIC_MONTH_NAMES[month]}"
        for month in _month_sequence(selected)
    ]


def export_columns_for_date(order_date: date | datetime | None = None) -> list[str]:
    """Return the exact dynamic export contract for an order date."""
    return [*_FIXED_COLUMNS, *sales_columns_for_date(order_date), *_TRAILING_COLUMNS]


#: Fallback export contract used by older callers.
EXPORT_COLUMNS: list[str] = [
    "التصنيف",
    "الكود",
    "الاسم",
    "المطلوب",
    "السعر",
    "القيمة المالية للطلب",
    "الموجود في الفرع",
    "الموجود في المخزن",
    "التحويلات",
    "مبيعات يوليو",
    "مبيعات أغسطس",
    "مبيعات سبتمبر",
    "مبيعات الشهر الحالي",
    "المتوسط",
    "ROP",
    "Substitutes",
    "Lead_Time",
    "تاريخ الوصول المتوقع",
    "تغطية المخزون (أيام)",
    "سبب الطلب",
    "ملاحظات",
]


def build_export_columns(
    include_audit_columns: bool = False,
    order_date: date | datetime | None = None,
) -> list[str]:
    """Return the exact export contract of the final sheet.

    ``include_audit_columns`` is retained for callers of the old API.  Audit
    figures are written to a separate worksheet, never appended to the final
    sheet, because the final sheet must stay a single stable contract.
    """
    return export_columns_for_date(order_date)


# ---------------------------------------------------------------------------
# Building / normalising the export frame
# ---------------------------------------------------------------------------


def _normalise_code(value: object) -> str:
    code = clean_sku(value)
    return "" if pd.isna(code) else str(code)


def _normalise_code_series(values: pd.Series) -> pd.Series:
    return values.map(_normalise_code).astype("string")


def _first_present(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _numeric(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _is_sales_column(column: str) -> bool:
    return str(column).startswith("مبيعات ") or column == "مبيعات الشهر الحالي"


def _fixed_for_frame() -> set[str]:
    return set(_FIXED_COLUMNS) | set(_TRAILING_COLUMNS)


def _expected_columns(
    data: pd.DataFrame | None,
    diagnostics: pd.DataFrame | None = None,
) -> list[str]:
    """Resolve the dynamic export contract for a frame."""
    for frame in (data, diagnostics):
        if frame is None:
            continue
        stored = frame.attrs.get("export_columns")
        if isinstance(stored, (list, tuple)) and stored:
            return [str(column) for column in stored]
        order_date = frame.attrs.get("order_date")
        if isinstance(order_date, (date, datetime)):
            return export_columns_for_date(order_date)
    if data is not None and list(data.columns) == list(EXPORT_COLUMNS):
        return list(EXPORT_COLUMNS)
    if data is not None:
        sales = [column for column in data.columns if _is_sales_column(str(column))]
        if len(sales) == 4 and _fixed_for_frame().issubset(set(data.columns)):
            # The frame itself already carries a valid dynamic contract.
            return [str(column) for column in data.columns]
    return list(EXPORT_COLUMNS)


def _format_date(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return ""
    parsed = pd.to_datetime(text, errors="coerce")
    if not pd.isna(parsed):
        return pd.Timestamp(parsed).strftime("%Y-%m-%d")
    return text


def _frame_from_diagnostics(
    diagnostics: pd.DataFrame,
    order_date: date | datetime | None = None,
) -> pd.DataFrame:
    """Rebuild the dynamic export contract from a rich diagnostics frame."""
    source = diagnostics.copy()
    selected = order_date
    if not isinstance(selected, (date, datetime)):
        selected = source.attrs.get("order_date")
    if not isinstance(selected, (date, datetime)):
        selected = date.today()

    result = pd.DataFrame(index=source.index)
    category = _first_present(
        source, ("التصنيف", "Export_Category", "Raw_Category", "Master_Category")
    )
    code = _first_present(source, ("الكود", "كود الصنف", "كود"))
    name = _first_present(source, ("الاسم", "اسم الصنف", "Master_Name"))
    required = _first_present(
        source, ("المطلوب", "Final_Purchase_Order", "Calculated_Order")
    )
    substitutes = _first_present(
        source, ("Substitutes", "Substitute_Deduction", "Transferred_In")
    )
    price = _first_present(source, ("السعر", "سعر البيع", "Price", "Unit_Cost"))
    branch = _first_present(source, ("الموجود في الفرع", "Branch_Stock", "الموجود"))
    warehouse = _first_present(
        source, ("الموجود في المخزن", "المخزن", "Warehouse_Stock")
    )
    transfers = _first_present(
        source, ("التحويلات", "Net_Transfers")
    )
    average = _first_present(source, ("المتوسط", "Export_Average", "ERP_Average"))
    rop = _first_present(source, ("ROP",))
    lead = _first_present(source, ("Lead_Time",))
    arrival = _first_present(source, ("تاريخ الوصول المتوقع", "Arrival_Date"))
    coverage = _first_present(
        source,
        ("تغطية المخزون (أيام)", "Coverage_Days_Current", "Stock_Coverage_Days"),
    )
    reason = _first_present(source, ("سبب الطلب", "Order_Reason", "Reason"))
    notes = _first_present(source, ("ملاحظات", "Notes"))

    result["التصنيف"] = (
        source[category].astype("string")
        if category
        else pd.Series("", index=source.index, dtype="string")
    )
    result["الكود"] = source[code] if code else pd.Series("", index=source.index)
    result["الاسم"] = (
        source[name].astype("string")
        if name
        else pd.Series("", index=source.index, dtype="string")
    )
    result["المطلوب"] = _numeric(source, required).fillna(0.0)
    result["السعر"] = _numeric(source, price).fillna(0.0)
    result["القيمة المالية للطلب"] = (
        result["المطلوب"].clip(lower=0.0) * result["السعر"].fillna(0.0)
    )
    result["الموجود في الفرع"] = _numeric(source, branch).fillna(0.0)
    result["الموجود في المخزن"] = _numeric(source, warehouse).fillna(0.0)
    result["التحويلات"] = _numeric(source, transfers).fillna(0.0)

    sales_headers = sales_columns_for_date(selected)
    sales_aliases = (
        ("Sales_Month_3", "Sales_July", "July_Sales"),
        ("Sales_Month_2", "Sales_August", "August_Sales"),
        ("Sales_Month_1", "Sales_September", "September_Sales"),
        ("مبيعات الشهر الحالي", "Current_Month_Sales", "Recent_Sales"),
    )
    for header, aliases in zip(sales_headers, sales_aliases):
        column = _first_present(source, (header, *aliases))
        result[header] = _numeric(source, column)

    result["المتوسط"] = _numeric(source, average).fillna(0.0)
    result["ROP"] = _numeric(source, rop).fillna(0.0)
    result["Substitutes"] = _numeric(source, substitutes).fillna(0.0)
    result["Lead_Time"] = _numeric(source, lead).fillna(0.0)
    daily = _numeric(source, _first_present(source, ("Daily_Demand",)))
    if arrival is not None:
        result["تاريخ الوصول المتوقع"] = source[arrival].map(_format_date)
    else:
        base = pd.Timestamp(selected)
        result["تاريخ الوصول المتوقع"] = (
            result["Lead_Time"].fillna(0.0).map(
                lambda value: (base + timedelta(days=max(int(value), 0))).strftime(
                    "%Y-%m-%d"
                )
            )
        )
    if coverage is not None:
        result["تغطية المخزون (أيام)"] = _numeric(source, coverage).fillna(0.0)
    else:
        result["تغطية المخزون (أيام)"] = (
            result["الموجود في الفرع"]
            / daily.where(daily > 0)
        ).fillna(0.0)
    result["سبب الطلب"] = (
        source[reason].fillna("").astype("string")
        if reason
        else pd.Series("", index=source.index, dtype="string")
    )
    result["ملاحظات"] = (
        source[notes].fillna("").astype("string")
        if notes
        else pd.Series("", index=source.index, dtype="string")
    )
    return result.loc[:, export_columns_for_date(selected)]


def _coerce_export_frame(
    data: pd.DataFrame,
    diagnostics: pd.DataFrame | None,
) -> pd.DataFrame:
    """Return a frame with exactly the dynamic export columns."""
    if not isinstance(data, pd.DataFrame) or data.empty:
        if diagnostics is not None and not diagnostics.empty:
            return _frame_from_diagnostics(diagnostics).reset_index(drop=True)
        raise ValueError("There are no items to export.")

    expected = _expected_columns(data, diagnostics)
    if list(data.columns) == expected:
        return data.copy().reset_index(drop=True)

    if set(expected).issubset(data.columns):
        return data.loc[:, expected].copy().reset_index(drop=True)

    if diagnostics is not None and not diagnostics.empty:
        return _frame_from_diagnostics(diagnostics).reset_index(drop=True)

    missing = [column for column in expected if column not in data.columns]
    raise ValueError(
        "The export columns do not match the required dynamic order. "
        f"Missing: {', '.join(missing) or 'unknown'}."
    )


def _normalise_numbers(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce numeric columns, compute money, and drop non-positive lines."""
    frame = frame.copy()
    sales_columns = [column for column in frame.columns if _is_sales_column(str(column))]
    numeric_columns = [
        "المطلوب",
        "السعر",
        "القيمة المالية للطلب",
        "الموجود في الفرع",
        "الموجود في المخزن",
        "التحويلات",
        *sales_columns,
        "المتوسط",
        "ROP",
        "Substitutes",
        "Lead_Time",
        "تغطية المخزون (أيام)",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    required = pd.to_numeric(frame["المطلوب"], errors="coerce").fillna(0.0)
    frame["المطلوب"] = required.map(
        lambda value: int(math.ceil(max(float(value), 0.0)))
    ).astype("int64")

    # The financial value is a real formula, not a copied source column.
    frame["القيمة المالية للطلب"] = (
        frame["المطلوب"].astype("float64")
        * pd.to_numeric(frame["السعر"], errors="coerce").fillna(0.0)
    )

    # Future rows are filtered only after the money formula is calculated.
    # A replaced original and a substitute covered by branch/warehouse stock
    # are kept at zero so the buyer can see both sides of the replacement.
    # Keep those rows even though their required quantity is zero.
    zero_keep_reasons = {
        "مستبدل بصنف آخر",
        "رصيد كافي في الفرع",
        "رصيد كافي في المخزن",
    }
    if "سبب الطلب" in frame.columns:
        replaced = (
            frame["سبب الطلب"].fillna("").astype(str).str.strip()
            .isin(zero_keep_reasons)
        )
    else:
        replaced = pd.Series(False, index=frame.index)
    frame = frame.loc[(frame["المطلوب"] > 0) | replaced].copy()
    if frame.empty:
        raise ValueError("There are no items with a positive required quantity.")

    # System figures: a missing value means "not available", but the column
    # is still numeric, so zero is the honest empty value.
    for column in (
        "السعر",
        "الموجود في الفرع",
        "الموجود في المخزن",
        "التحويلات",
        "المتوسط",
        "ROP",
        "Substitutes",
        "Lead_Time",
        "تغطية المخزون (أيام)",
    ):
        if column in frame.columns:
            frame[column] = frame[column].fillna(0.0)

    # Historical sales are intentionally left as NaN.  Do not fill them with
    # zero: the buyer must be able to distinguish "no sale" from "no match".
    for column in sales_columns:
        frame[column] = frame[column].astype("float64")

    frame["Lead_Time"] = frame["Lead_Time"].clip(lower=0.0)
    frame["تغطية المخزون (أيام)"] = frame[
        "تغطية المخزون (أيام)"
    ].clip(lower=0.0)
    frame["تاريخ الوصول المتوقع"] = frame["تاريخ الوصول المتوقع"].map(_format_date)
    frame["سبب الطلب"] = frame["سبب الطلب"].fillna("").astype("string")
    frame["ملاحظات"] = frame["ملاحظات"].fillna("").astype("string")

    # Item codes stay integers whenever the source really carries integers.
    codes = pd.to_numeric(frame["الكود"], errors="coerce")
    integral = codes.notna() & codes.map(
        lambda value: float(value).is_integer() if pd.notna(value) else False
    )
    frame["الكود"] = [
        int(code) if is_integer else _normalise_code(raw)
        for code, is_integer, raw in zip(codes, integral, frame["الكود"])
    ]

    frame["التصنيف"] = frame["التصنيف"].fillna("").astype("string")
    frame["الاسم"] = frame["الاسم"].fillna("").astype("string")
    return frame.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Row colours
# ---------------------------------------------------------------------------


def _code_set(values: Iterable[object] | None) -> set[str]:
    if values is None:
        return set()
    return {code for code in (_normalise_code(value) for value in values) if code}


def _diagnostics_flags(
    codes: pd.Series,
    diagnostics: pd.DataFrame | None,
) -> pd.DataFrame:
    """Return boolean colour flags aligned with the export rows."""
    flags = pd.DataFrame(
        {
            "warehouse": False,
            "pushing": False,
            "transfer": False,
            "multiple": False,
        },
        index=codes.index,
    )
    if diagnostics is None or diagnostics.empty or "الكود" not in diagnostics.columns:
        return flags

    diagnostic = diagnostics.copy()
    diagnostic["_Code"] = _normalise_code_series(diagnostic["الكود"])
    diagnostic = diagnostic.loc[diagnostic["_Code"].ne("")]
    diagnostic = diagnostic.drop_duplicates("_Code", keep="first").set_index("_Code")

    def flag(column: str) -> pd.Series:
        if column not in diagnostic.columns:
            return pd.Series(False, index=codes.index)
        values = codes.map(diagnostic[column]).fillna(False)
        return values.astype(bool)

    flags["pushing"] = flag("Is_Pushing_List").to_numpy()
    flags["multiple"] = flag("Is_Multi_Card").to_numpy()
    flags["transfer"] = flag("Is_Transfer").to_numpy()
    if "Warehouse_Loading" in diagnostic.columns:
        flags["warehouse"] = flag("Warehouse_Loading").to_numpy()
    elif "Warehouse_Covered" in diagnostic.columns:
        covered = codes.map(
            pd.to_numeric(diagnostic["Warehouse_Covered"], errors="coerce")
        ).fillna(0.0)
        flags["warehouse"] = (covered > 0).to_numpy()
    return flags


def _row_colours(
    data: pd.DataFrame,
    diagnostics: pd.DataFrame | None,
    *,
    pushing_codes: Iterable[object] | None = None,
    multi_codes: Iterable[object] | None = None,
    transfer_codes: Iterable[object] | None = None,
    warehouse_codes: Iterable[object] | None = None,
) -> pd.Series:
    """Return the fill colour of every row, following the exact priority.

    Pink (warehouse) > blue (pushing) > yellow (transfers) > grey (multi-card).
    """
    codes = _normalise_code_series(data["الكود"])

    stored = data.attrs.get("row_colors")
    if isinstance(stored, dict):
        return pd.Series(
            [stored.get(code, "") for code in codes], index=data.index, dtype="object"
        )

    flags = _diagnostics_flags(codes, diagnostics)

    if pushing_codes is not None:
        flags["pushing"] = codes.isin(_code_set(pushing_codes)).to_numpy()
    if multi_codes is not None:
        flags["multiple"] = codes.isin(_code_set(multi_codes)).to_numpy()
    if transfer_codes is not None:
        flags["transfer"] = codes.isin(_code_set(transfer_codes)).to_numpy()
    if warehouse_codes is not None:
        flags["warehouse"] = codes.isin(_code_set(warehouse_codes)).to_numpy()

    colours = pd.Series("", index=data.index, dtype="object")
    # The later assignment wins.  Keep warehouse last so pink is absolute.
    colours = colours.mask(flags["multiple"], COLOR_MULTIPLE_CARDS)
    colours = colours.mask(flags["transfer"], COLOR_TRANSFER)
    colours = colours.mask(flags["pushing"], COLOR_PUSHING)
    colours = colours.mask(flags["warehouse"], COLOR_WAREHOUSE)
    return colours


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _write_sheet(
    worksheet,
    workbook,
    frame: pd.DataFrame,
    colours: pd.Series,
    *,
    sheet_name: str,
    progress_callback: ProgressCallback | None,
) -> int:
    """Write one fully formatted worksheet and return its row count."""
    columns = list(frame.columns)
    sales_columns = [column for column in columns if _is_sales_column(str(column))]
    integer_columns = {"المطلوب", "Substitutes", "Lead_Time"}
    float_columns = {
        "السعر",
        "القيمة المالية للطلب",
        "الموجود في الفرع",
        "الموجود في المخزن",
        "التحويلات",
        *sales_columns,
        "المتوسط",
        "ROP",
        "تغطية المخزون (أيام)",
    }

    header_format = workbook.add_format(
        {
            "bg_color": EXPORT_HEADER_BACKGROUND,
            "font_color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "valign": "vcenter",
            "border": 0,
        }
    )

    format_cache: dict[tuple[str, str], object] = {}

    def cell_format(kind: str, colour: str):
        key = (kind, colour)
        if key in format_cache:
            return format_cache[key]
        properties: dict[str, object] = {"border": 0}
        if colour:
            properties["bg_color"] = colour
        if kind == "integer":
            properties["num_format"] = "#,##0"
        elif kind == "float":
            properties["num_format"] = "#,##0.00"
        elif kind == "money":
            properties["num_format"] = "#,##0.00"
        elif kind == "code":
            properties["num_format"] = "0"
        elif kind == "date":
            properties["num_format"] = "yyyy-mm-dd"
            properties["align"] = "center"
        format_cache[key] = workbook.add_format(properties)
        return format_cache[key]

    worksheet.right_to_left()
    worksheet.freeze_panes(1, 0)
    worksheet.set_default_row(18)

    widths: dict[str, int] = {
        "التصنيف": 18,
        "الكود": 12,
        "الاسم": 40,
        "المطلوب": 12,
        "السعر": 12,
        "القيمة المالية للطلب": 20,
        "الموجود في الفرع": 16,
        "الموجود في المخزن": 16,
        "التحويلات": 14,
        "المتوسط": 12,
        "ROP": 12,
        "Substitutes": 14,
        "Lead_Time": 12,
        "تاريخ الوصول المتوقع": 20,
        "تغطية المخزون (أيام)": 24,
        "سبب الطلب": 24,
        "ملاحظات": 54,
    }
    for column in sales_columns:
        widths[column] = 15

    column_formats: dict[str, object] = {}
    for column in columns:
        if column == "الكود":
            column_formats[column] = cell_format("code", "")
        elif column in integer_columns:
            column_formats[column] = cell_format("integer", "")
        elif column == "القيمة المالية للطلب":
            column_formats[column] = cell_format("money", "")
        elif column == "تاريخ الوصول المتوقع":
            column_formats[column] = cell_format("date", "")
        elif column in float_columns:
            column_formats[column] = cell_format("float", "")
        else:
            column_formats[column] = cell_format("text", "")

    for index, column in enumerate(columns):
        worksheet.set_column(index, index, widths.get(column, 17), column_formats[column])

    header_labels = [_ARABIC_HEADERS.get(column, column) for column in columns]
    worksheet.write_row(0, 0, header_labels, header_format)
    worksheet.autofilter(0, 0, len(frame), len(columns) - 1)

    def integral(value: object) -> bool:
        try:
            return float(value).is_integer()
        except (TypeError, ValueError):
            return False

    required_index = columns.index("المطلوب")
    lead_index = columns.index("Lead_Time")
    for row_number, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        position = row_number - 1
        colour = str(colours.iloc[position]) if position < len(colours) else ""

        # Fast path for ordinary uncoloured rows with integral quantities.
        simple = (
            not colour
            and integral(row[required_index])
            and integral(row[lead_index])
        )
        if simple:
            worksheet.write_row(
                row_number,
                0,
                [None if _is_missing(value) else value for value in row],
            )
        else:
            for column_index, column in enumerate(columns):
                value = row[column_index]
                if _is_missing(value):
                    worksheet.write_blank(
                        row_number,
                        column_index,
                        None,
                        cell_format("text", colour),
                    )
                    continue

                if column == "الكود":
                    if isinstance(value, int):
                        worksheet.write_number(
                            row_number,
                            column_index,
                            value,
                            cell_format("code", colour),
                        )
                    else:
                        worksheet.write_string(
                            row_number,
                            column_index,
                            str(value),
                            cell_format("text", colour),
                        )
                elif column in integer_columns:
                    number = float(value)
                    if number.is_integer():
                        worksheet.write_number(
                            row_number,
                            column_index,
                            int(number),
                            cell_format("integer", colour),
                        )
                    else:
                        worksheet.write_number(
                            row_number,
                            column_index,
                            number,
                            cell_format("float", colour),
                        )
                elif column == "القيمة المالية للطلب":
                    worksheet.write_number(
                        row_number,
                        column_index,
                        float(value),
                        cell_format("money", colour),
                    )
                elif column in float_columns:
                    worksheet.write_number(
                        row_number,
                        column_index,
                        float(value),
                        cell_format("float", colour),
                    )
                elif column == "تاريخ الوصول المتوقع":
                    worksheet.write_string(
                        row_number,
                        column_index,
                        _format_date(value),
                        cell_format("date", colour),
                    )
                else:
                    worksheet.write_string(
                        row_number,
                        column_index,
                        str(value),
                        cell_format("text", colour),
                    )

        if progress_callback is not None and (
            row_number % EXCEL_CHUNK_SIZE == 0 or row_number == len(frame)
        ):
            progress_callback(
                f"✍️ Writing {row_number:,} of {len(frame):,} items to "
                f"'{sheet_name}'."
            )

    return len(frame)


def _write_audit_sheet(
    writer: pd.ExcelWriter,
    data: pd.DataFrame,
    diagnostics: pd.DataFrame | None,
) -> None:
    """Write the optional stock audit to its own sheet."""
    if diagnostics is None or diagnostics.empty or "الكود" not in diagnostics.columns:
        return

    source = diagnostics.copy()
    source["_Code"] = _normalise_code_series(source["الكود"])
    source = source.drop_duplicates("_Code", keep="first").set_index("_Code")
    export_codes = _normalise_code_series(data["الكود"])
    audit = pd.DataFrame(index=data.index)
    audit["الكود"] = data["الكود"].to_numpy()
    for target, origin in (
        ("رصيد الفرع", "Branch_Stock"),
        ("مشتريات تحت التوريد", "Pending_Purchases"),
        ("تحويلات واردة", "Transfers_In"),
        ("تحويلات صادرة", "Transfers_Out"),
    ):
        if origin in source.columns:
            audit[target] = (
                export_codes.map(pd.to_numeric(source[origin], errors="coerce"))
                .fillna(0.0)
                .to_numpy()
            )
        else:
            audit[target] = 0.0
    audit.to_excel(writer, sheet_name="التدقيق", index=False)


def export_styled_excel(
    data: pd.DataFrame,
    *,
    diagnostics: pd.DataFrame | None = None,
    include_audit_columns: bool = False,
    progress_callback: ProgressCallback | None = None,
    pushing_codes: Iterable[object] | None = None,
    multi_codes: Iterable[object] | None = None,
    transfer_codes: Iterable[object] | None = None,
    warehouse_codes: Iterable[object] | None = None,
) -> BytesIO:
    """Write the final dynamic-column order workbook.

    Parameters
    ----------
    data:
        The dynamic final frame.  A rich diagnostics frame is accepted as a
        compatibility fallback.
    diagnostics:
        Optional pipeline diagnostics for row colours and the audit sheet.
    include_audit_columns:
        Write stock components to a separate ``Audit`` worksheet.  The final
        sheet always keeps the same stable contract.
    progress_callback:
        Receives user-facing progress messages.
    pushing_codes, multi_codes, transfer_codes, warehouse_codes:
        Optional explicit colour overrides.
    """
    if progress_callback is not None:
        progress_callback("🧾 Preparing the final order sheet...")

    export_data = _coerce_export_frame(data, diagnostics)
    export_data = _normalise_numbers(export_data)
    colours = _row_colours(
        export_data,
        diagnostics,
        pushing_codes=pushing_codes,
        multi_codes=multi_codes,
        transfer_codes=transfer_codes,
        warehouse_codes=warehouse_codes,
    )

    output = BytesIO()
    workbook_options = {
        "options": {
            "constant_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
        }
    }
    with pd.ExcelWriter(
        output,
        engine="xlsxwriter",
        engine_kwargs=workbook_options,
    ) as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet("الطلبية النهائية")
        written_rows = _write_sheet(
            worksheet,
            workbook,
            export_data,
            colours,
            sheet_name="الطلبية النهائية",
            progress_callback=progress_callback,
        )
        if written_rows == 0:
            raise ValueError("The generated workbook has no order rows.")
        if include_audit_columns:
            _write_audit_sheet(writer, export_data, diagnostics)

    output.seek(0)
    if output.getbuffer().nbytes == 0:
        raise ValueError("The generated Excel workbook is empty.")
    return output
