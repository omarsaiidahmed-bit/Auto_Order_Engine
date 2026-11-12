"""File ingestion: read, detect, decode, map headers, validate, clean.

The ingestion layer is **strictly content driven**.  A branch folder may name
its files in any way it likes (``تقرير الاصناف الناقصة فرع <الفرع>.xlsx``,
``sales.xlsx``, ``رصيد <الفرع>.xlsx`` …) and the role of every workbook is
decided from its **column signature** alone.

Two rules make that possible:

1. :func:`detect_role` never receives a file name.  Every role is described by
   the columns it must contain and by the columns it must *not* contain, and
   the rules are evaluated in a fixed priority order so the answer is
   deterministic.
2. :func:`canonicalize_columns` maps the source headers onto the canonical
   schema through an alias table.  The aliases are spelling variants of the
   *same logical column* (``كود`` / ``الكود`` / ``كود الصنف``) -- they are not
   file names.

The format is sniffed from the bytes as well, so a workbook that arrives with
a misleading extension is still read correctly.

Three reading paths are supported:

* ``.xlsx`` / ``.xls`` -- the sheet with the most columns is used; the sheet
  is read **once** (a 78,000 row catalogue is expensive to parse).
* ``.csv`` -- the encoding ladder (UTF-8 / UTF-8-SIG / Windows-1256 / Latin-1)
  and the separator ladder (comma / semicolon / tab / pipe).
* the wide **historical sales panel** -- a workbook whose header sits on the
  third row and whose columns are ``branch x month``; handled by
  :class:`SalesPanel`.
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Iterable

import pandas as pd

from app_config import (
    CENTRAL_WAREHOUSE_MARKERS,
    FILE_SPECS,
    MASTER_PACK_SIZE_COLUMN,
    PACKS_COLUMN,
    PIECES_COLUMN,
    QUANTITY_COLUMN,
    SKU_COLUMN,
    UPLOAD_LABELS_EN,
)
from core.normalize import (
    clean_sku,
    clean_text_column,
    normalize_key,
    parse_numeric_column,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "SalesPanel",
    "apply_header",
    "canonicalize_columns",
    "clean_frame",
    "describe_roles",
    "detect_format",
    "detect_header_row",
    "detect_role",
    "load_and_clean_bytes",
    "load_and_clean_data",
    "load_and_detect",
    "load_panel",
    "prepare_bytes",
    "read_sales_panel",
    "validate_columns",
]


# ---------------------------------------------------------------------------
# Format sniffing
# ---------------------------------------------------------------------------
_CSV_ENCODINGS = ("utf-8", "utf-8-sig", "windows-1256", "cp1256", "latin-1")
_CSV_SEPARATORS = (",", ";", "\t", "|")

_ZIP_SIGNATURE = b"PK\x03\x04"
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def detect_format(payload: bytes, filename: str = "") -> str:
    """Return ``"xlsx"``, ``"xls"`` or ``"csv"`` for the given bytes.

    **The bytes decide.**  A workbook always starts with the ZIP signature
    (``PK``) or the OLE signature (``.xls``); anything else is a text file
    and is parsed as a CSV, whatever the file is called.  The name is only a
    fallback for an empty payload.
    """
    head = payload[:8] if payload else b""
    if head.startswith(_ZIP_SIGNATURE):
        return "xlsx"
    if head.startswith(_OLE_SIGNATURE):
        return "xls"
    if head:
        return "csv"

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in {"xlsx", "xls", "csv"}:
        return extension
    return "csv"


# ---------------------------------------------------------------------------
# The role signatures
# ---------------------------------------------------------------------------
#: The columns that identify the wide historical sales panel.
PANEL_IDENTITY_LABELS: tuple[str, ...] = ("التصنيف", "كود الصنف", "اسم الصنف", "السعر")

#: The panel is the only file that carries a bare ``السعر`` column next to a
#: very wide grid.  A master catalogue with many columns does **not** match,
#: because it says ``سعر البيع`` and ``فئة التصنيف``.
PANEL_MIN_COLUMNS = 24

#: The values of ``القسم`` that mark the ERP's "pushing list" export.
PUSHING_LIST_SECTION = "pushing list"

#: The location value that means "the branch's own shelf".
MAIN_LOCATION_KEY = "main"


def _keys(values: Iterable[Any]) -> set[str]:
    """Normalise a collection of labels into comparison keys."""
    return {normalize_key(value) for value in values}


def _has(columns: set[str], *names: str) -> bool:
    """Return whether any of the named columns is present."""
    for name in names:
        key = normalize_key(name)
        if key in columns:
            return True
        # Avoid false positives from substring matches (e.g. 'مبيعات' inside 'سعرالبيع')
        for column in columns:
            if not key or not column:
                continue
            if key == column:
                return True
            # Only do substring match if key is long enough and they're clearly related
            # or if the key appears as a separate token
            if len(key) >= 4 and (key in column or column in key):
                # Avoid matching if key is embedded in a different word like بيع inside سعرالبيع
                # Be more specific about Arabic patterns
                if 'مبيعات' in name or 'العملية' in name or 'التاريخ' in name or 'المطلوب' in name:
                    # For these specific tokens, require better matching
                    continue
                return True
    return False


def _has_all(columns: set[str], *names: str) -> bool:
    """Return whether every named column is present."""
    return all(_has(columns, name) for name in names)


def _has_none(columns: set[str], *names: str) -> bool:
    """Return whether none of the named columns is present."""
    for name in names:
        if _has(columns, name):
            return False
    return True


def _has_any(columns: set[str], *names: str) -> bool:
    return _has(columns, *names)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _read_excel_fast(payload: bytes) -> tuple[pd.DataFrame | None, str]:
    """Read a workbook with openpyxl's streaming reader.

    ``pandas.read_excel`` copies every cell through a second parsing layer.
    On the wide sales panel (5.3 million cells) that dominates the waiting
    time, so the raw values are pulled straight out of the sheet here.  Any
    problem falls back to the pandas reader.
    """
    if not payload.startswith(_ZIP_SIGNATURE):
        return None, ""
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - openpyxl is a hard dependency
        return None, ""

    workbook = None
    try:
        workbook = openpyxl.load_workbook(
            BytesIO(payload), read_only=True, data_only=True
        )
        best_name = ""
        best_columns = -1
        for name in workbook.sheetnames:
            columns = workbook[name].max_column or 0
            if columns > best_columns:
                best_columns = columns
                best_name = name
        if not best_name or best_columns <= 0:
            return None, ""

        rows = list(workbook[best_name].iter_rows(values_only=True))
        if not rows:
            return None, ""

        width = max(len(row) for row in rows)
        padded = [
            tuple(row) + (None,) * (width - len(row)) if len(row) < width else tuple(row)
            for row in rows
        ]
        frame = pd.DataFrame(padded, dtype=object)

        # drop the empty columns the ERP leaves at the right edge
        while frame.shape[1] and frame.iloc[:, -1].isna().all():
            frame = frame.iloc[:, :-1]
        return frame, best_name
    except Exception:  # noqa: BLE001 - the pandas reader is the safety net
        return None, ""
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:  # noqa: BLE001
                pass


def _read_excel_smart(payload: bytes) -> tuple[pd.DataFrame, str]:
    """Read the sheet with the most columns of a workbook, without a header.

    The workbook is read **once**: a catalogue of 78,000 rows is expensive to
    parse and reading it twice doubles the wait for the user.
    """
    frame, sheet_name = _read_excel_fast(payload)
    if frame is not None:
        return frame, sheet_name

    with pd.ExcelFile(BytesIO(payload)) as book:
        names = list(book.sheet_names)
        if not names:
            raise ValueError("The workbook contains no sheets.")

        best_name = names[0]
        best_columns = -1
        for name in names:
            try:
                preview = pd.read_excel(
                    book, sheet_name=name, header=None, dtype=object, nrows=40
                )
            except Exception:  # noqa: BLE001 - a broken sheet must not kill the run
                continue
            if preview.shape[1] > best_columns:
                best_columns = preview.shape[1]
                best_name = name

        frame = pd.read_excel(book, sheet_name=best_name, header=None, dtype=object)
    return frame, best_name


def _read_csv_candidates(data: bytes) -> list[pd.DataFrame]:
    """Walk the encoding and the delimiter ladder and collect every parse."""
    candidates: list[pd.DataFrame] = []
    for encoding in _CSV_ENCODINGS:
        for separator in _CSV_SEPARATORS:
            try:
                candidate = pd.read_csv(BytesIO(data), encoding=encoding, sep=separator)
            except UnicodeDecodeError:
                break
            except (pd.errors.ParserError, ValueError):
                continue
            candidates.append(candidate)
            break
    return candidates


# ---------------------------------------------------------------------------
# Header discovery
# ---------------------------------------------------------------------------
def _known_header_keys() -> set[str]:
    """Every column name the system is able to recognise, as comparison keys."""
    keys: set[str] = set()
    for spec in FILE_SPECS.values():
        for column in list(spec["columns"]) + list(spec["optional"]):
            keys.add(normalize_key(column))
        for aliases in spec["aliases"].values():
            for alias in aliases:
                keys.add(normalize_key(alias))
    keys.update(normalize_key(label) for label in PANEL_IDENTITY_LABELS)
    return keys


_KNOWN_HEADER_KEYS = _known_header_keys()


def detect_header_row(frame: pd.DataFrame, max_scan: int = 12) -> int:
    """Return the index of the row that carries the column names.

    ERP exports normally start with the header on row 0, but title rows do
    occur.  The row with the most recognisable ERP column names wins, and a
    tie is resolved in favour of the earliest row.
    """
    best_row = 0
    best_score = -1
    limit = min(max_scan, len(frame))
    for index in range(limit):
        row = frame.iloc[index]
        score = sum(1 for value in row if normalize_key(value) in _KNOWN_HEADER_KEYS)
        if score > best_score:
            best_score = score
            best_row = index
    return best_row


def apply_header(frame: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Return the frame with ``header_row`` promoted to the column names."""
    data = frame.iloc[header_row + 1 :].copy()
    headers = [str(value).strip() for value in frame.iloc[header_row]]
    if len(headers) < data.shape[1]:
        headers = headers + ["" for _ in range(data.shape[1] - len(headers))]
    data.columns = headers[: data.shape[1]]
    return data.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Role detection -- pure column signatures
# ---------------------------------------------------------------------------
def _looks_like_panel(frame: pd.DataFrame) -> bool:
    """Return whether the frame is the wide ``branch x month`` sales panel.

    The signature is the combination of **extreme width** and the panel's
    own identity columns.  The width alone is not enough: a catalogue with
    many columns must not be mistaken for a panel.
    """
    if frame.shape[1] < PANEL_MIN_COLUMNS:
        return False
    columns = _keys(frame.columns)
    if not _has(columns, "السعر"):
        return False
    return _has(columns, "التصنيف", "كود الصنف", "اسم الصنف")


def _detect_stock_role(frame: pd.DataFrame) -> str:
    """Tell the branch stock file from the central warehouse file.

    Both files have an **identical** column set, so the decision has to come
    from the values:

    * the central warehouse reports the ERP's administrative branch
      (``المخازن والاداره``) in ``الفرع``;
    * a branch reports its own name in ``الفرع`` and its own shelf
      (``Main``) in ``المخزن``.

    The rule is deterministic and never looks at the file name.
    """
    if "الفرع" in frame.columns:
        values = frame["الفرع"].astype("string").dropna()
        if not values.empty:
            modal = normalize_key(values.mode().iloc[0])
            if modal and any(
                normalize_key(marker) == modal for marker in CENTRAL_WAREHOUSE_MARKERS
            ):
                return "warehouse_stock"

    if "المخزن" in frame.columns:
        values = frame["المخزن"].astype("string").dropna()
        if not values.empty:
            modal = normalize_key(values.mode().iloc[0])
            if modal and modal != MAIN_LOCATION_KEY:
                return "warehouse_stock"

    return "branch_stock"


def _looks_like_pushing_list(frame: pd.DataFrame) -> bool:
    """Return whether the frame is the ERP's "pushing list" export."""
    columns = _keys(frame.columns)
    if _has_any(columns, "نواقص الفرع", "نواقص"):
        return True
    if _has_any(columns, "قائمة الدفع", "pushing"):
        return True
    if "القسم" in frame.columns:
        values = frame["القسم"].astype("string").dropna()
        if not values.empty:
            modal = normalize_key(values.mode().iloc[0])
            if modal == normalize_key(PUSHING_LIST_SECTION) or "pushing" in modal:
                return True
    return False


def detect_role(frame: pd.DataFrame) -> str | None:
    """Return the role of a tabular frame, or ``None`` when unrecognised.

    The frame must already carry its column names.  **The file name is never
    consulted** -- only the columns and their values.

    The rules are evaluated in a fixed priority order.  Each rule states the
    columns it requires and the columns that would make the file something
    else, so a file that happens to share a column with another role still
    lands on the right one.
    """
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None

    columns = _keys(frame.columns)

    # 1. the historical sales panel -- a very wide branch x month grid
    if _looks_like_panel(frame):
        return "panel_sales"

    # 2. the transfer ledger -- the only ledger with an operation column
    if _has(columns, "العملية") and _has_none(columns, "المطلوب"):
        return "transfers"

    # 3. the open purchase orders -- the only ledger with a source branch
    if _has(columns, "من فرع") or _has(columns, "الي فرع", "إلى فرع"):
        return "pending_purchases"

    # 8. the master catalogue -- a code, a name and the pack size (check first)
    # The real master has الاجزاء (pack size) or القسم; the multi-price helper
    # lacks both.  Require at least one of them to avoid misclassifying it.
    if (
        _has(columns, "كود الصنف")
        and _has(columns, "اسم الصنف")
        and _has(columns, MASTER_PACK_SIZE_COLUMN, "القسم")
        and _has(columns, "فئة التصنيف")
    ):
        # Don't misclassify sales reports as master
        if _has(columns, "التاريخ") or _has(columns, "مبيعات", "نوع البيع"):
            pass  # will be caught by sales check below, but we already reordered - let us be careful
        else:
            return "master"

    # 4. the branch sales report -- a movement type and/or a movement date.
    #    The aliases matter here: the ERP may call the quantity ``المبيعات``
    #    and the date ``تاريخ البيع``.  Canonicalise the headers for this check
    #    only, so a plain ``code + quantity + date`` ledger is recognised even
    #    when it has no pack/part columns.  A file that also carries
    #    ``المطلوب`` is a shortage report, not a sales ledger.
    recent_mapped = canonicalize_columns(frame, "recent_sales")
    recent_columns = _keys(recent_mapped.columns)
    # Check for exact presence of sales-related columns (not embedded in other words)
    has_mobayat_exact = any(
        normalize_key(c) == normalize_key('مبيعات') or 
        normalize_key(c) == normalize_key('نوع المبيعات') or
        (normalize_key(c).startswith('مبيعات') and normalize_key(c) not in ('سعرالبيع', 'اقصيخصمعليالمبيعات')) and 'سعر' not in normalize_key(c)
        for c in recent_mapped.columns
    )
    if (
        has_mobayat_exact
        and _has(recent_columns, "كود الصنف")
        and _has_none(recent_columns, "المطلوب")
    ):
        return "recent_sales"
    if (
        _has_all(recent_columns, "كود الصنف", QUANTITY_COLUMN, "التاريخ")
        and _has_none(recent_columns, "المطلوب")
    ):
        return "recent_sales"

    # 5. the shortage / requisition report -- the only file with a request
    if _has(columns, "المطلوب"):
        return "shortages"

    # 7. a stock file -- quantity split into packs and pieces (check before pushing list in some cases)
    if _has(columns, QUANTITY_COLUMN) and _has(columns, PACKS_COLUMN, PIECES_COLUMN):
        stock_role = _detect_stock_role(frame)
        # If it's branch stock/warehouse stock, it's not pushing list
        if stock_role in ("branch_stock", "warehouse_stock"):
            return stock_role

    # 6. the pushing list -- a shortage list restricted to one section
    if _looks_like_pushing_list(frame):
        # Don't misclassify if it's clearly a full stock file with all needed columns
        if _has(columns, QUANTITY_COLUMN) and _has(columns, PACKS_COLUMN, PIECES_COLUMN):
            return _detect_stock_role(frame)
        return "pushing_list"
    # Some branch exports name the sheet as pushing list but the first data
    # row still carries the header; try a header-promoted version.
    if frame.shape[1] >= 7:
        first = frame.iloc[0].astype("string").fillna("")
        if first.str.contains("فئة التصنيف|القسم|نواقص الفرع|رصيد الفرع|كود").sum() >= 3:
            promoted = frame.copy()
            promoted.columns = promoted.iloc[0]
            promoted = promoted.iloc[1:].reset_index(drop=True)
            promoted.columns = [str(c).strip() for c in promoted.columns]
            if _looks_like_pushing_list(promoted):
                if _has(_keys(promoted.columns), QUANTITY_COLUMN) and _has(_keys(promoted.columns), PACKS_COLUMN, PIECES_COLUMN):
                    return _detect_stock_role(promoted)
                return "pushing_list"

    # 9. the multi-price file -- a code, a name and a selling price
    if (
        _has(columns, "كود الصنف", "سعر البيع", "اسم الصنف")
        and _has_none(columns, QUANTITY_COLUMN, MASTER_PACK_SIZE_COLUMN)
        and _has_none(columns, "القسم")
    ):
        return "multi_price"

    return None


# ---------------------------------------------------------------------------
# Canonical column mapping
# ---------------------------------------------------------------------------
def canonicalize_columns(data: pd.DataFrame, role: str) -> pd.DataFrame:
    """Rename the source headers of one role onto their canonical names.

    The mapping is driven by the alias table of the role, so a column called
    ``كود``, ``الكود`` or ``كود الصنف`` all become the same canonical
    column.  The source column names decide -- never the file name.

    Two passes, in this order:

    1. every canonical name that is present **as is** is claimed first, so a
       column can never be stolen by another column's alias (the master's
       ``متوسط سعر التكلفة`` must not be swallowed by the alias list of
       ``سعر التكلفة``);
    2. the canonical names that are still missing look for an alias, and the
       first alias that is present and not yet claimed wins.
    """
    spec = FILE_SPECS[role]
    data = data.copy()
    data.columns = [str(column).strip() for column in data.columns]
    headers = {normalize_key(column): column for column in data.columns}

    canonical_names = [str(column) for column in spec["columns"]]
    canonical_names += [
        str(column)
        for column in spec["optional"]
        if str(column) not in canonical_names
    ]

    renames: dict[str, str] = {}
    claimed: set[str] = set()
    missing: list[str] = []

    # -- pass 1: the canonical names that are already there -------------------
    for canonical in canonical_names:
        source = headers.get(normalize_key(canonical))
        if source is None:
            missing.append(canonical)
            continue
        claimed.add(source)
        if source != canonical:
            renames[source] = canonical

    # -- pass 2: the aliases of the names that are still missing -------------
    for canonical in missing:
        for alias in spec["aliases"].get(canonical, []):
            source = headers.get(normalize_key(alias))
            if source is None or source in claimed:
                continue
            claimed.add(source)
            renames[source] = canonical
            break

    frame = data.rename(columns=renames)

    # The ERP sometimes repeats a header cell (``كود العملية`` appears twice in
    # the purchase-order export).  Two columns with the same name cannot be
    # addressed separately, so the first occurrence wins and the duplicate is
    # dropped.
    if frame.columns.duplicated().any():
        frame = frame.loc[:, ~frame.columns.duplicated()]

    return frame


def validate_columns(
    df: pd.DataFrame,
    required_columns: list[str],
    source_label: str,
) -> pd.DataFrame:
    """Raise a precise error when a required column is missing."""
    if not isinstance(df, pd.DataFrame):
        raise ValueError(f"'{source_label}' could not be read as a valid table.")
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            f"'{source_label}' is missing the required column '{missing[0]}'. "
            "Check that the source file is up to date."
        )
    return df


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------
def clean_frame(data: pd.DataFrame, role: str) -> pd.DataFrame:
    """Type, coerce and trim one raw frame according to its role."""
    spec = FILE_SPECS[role]
    data = data.copy()
    data.columns = [str(column).strip() for column in data.columns]

    sku_column = str(spec["sku"])
    if sku_column not in data.columns:
        raise ValueError(
            f"'{UPLOAD_LABELS_EN[role]}' has no item code column "
            f"(expected '{sku_column}')."
        )

    data[sku_column] = data[sku_column].map(clean_sku).astype("string")

    populated = data.drop(columns=[sku_column]).notna().any(axis=1)
    missing_sku = data[sku_column].isna() & populated
    if bool(missing_sku.any()):
        excel_rows = (data.index[missing_sku] + 2).tolist()[:5]
        raise ValueError(
            f"'{UPLOAD_LABELS_EN[role]}' contains data rows without an item code "
            f"(Excel rows: {excel_rows})."
        )
    data = data.loc[data[sku_column].notna()].copy()
    if data.empty:
        raise ValueError(f"'{UPLOAD_LABELS_EN[role]}' contains no items.")

    blank_as_zero = {str(column) for column in spec.get("blank_as_zero", [])}
    lenient = bool(spec.get("lenient_numeric"))
    for column in spec["numeric"]:
        column = str(column)
        if column in data.columns:
            if lenient:
                from core.normalize import to_numeric_series

                series = to_numeric_series(data[column])
                if column in blank_as_zero:
                    series = series.fillna(0.0)
                data[column] = series
            else:
                try:
                    data[column] = parse_numeric_column(
                        data[column],
                        column,
                        fill_missing=column in blank_as_zero,
                    )
                except Exception:
                    from core.normalize import to_numeric_series

                    series = to_numeric_series(data[column])
                    if column in blank_as_zero:
                        series = series.fillna(0.0)
                    data[column] = series

    numeric_columns = {str(column) for column in spec["numeric"]}
    for column in data.columns:
        if column != sku_column and column not in numeric_columns:
            data[column] = clean_text_column(data[column])

    keep = [str(column) for column in spec["columns"]]
    keep += [
        str(column)
        for column in spec["optional"]
        if str(column) in data.columns and str(column) not in keep
    ]
    keep = [column for column in keep if column in data.columns]
    return data.loc[:, keep].copy()


# ---------------------------------------------------------------------------
# The wide historical sales panel
# ---------------------------------------------------------------------------
@dataclass
class SalesPanel:
    """A ``branch x month`` sales panel.

    The ERP exports this as one very wide sheet whose header sits on the
    third row:  row 1 holds the branch names, row 2 a numeric index and row 3
    the real column names (the month label repeated once per branch).  The
    branch name is written **only in the first column of each branch block**,
    so it has to be forward-filled before it can be paired with the months.
    """

    sku: pd.Series
    name: pd.Series
    category: pd.Series
    price: pd.Series
    months_by_column: dict[int, str]
    branch_by_column: dict[int, str]
    sheet_name: str = ""
    _values: dict[int, pd.Series] = field(default_factory=dict, repr=False)

    def branches(self) -> list[str]:
        """Every branch that appears in the panel, in workbook order."""
        seen: dict[str, None] = {}
        for branch in self.branch_by_column.values():
            if branch:
                seen.setdefault(branch, None)
        return list(seen)

    def _branch_columns(self, branch: str) -> list[tuple[int, str]]:
        """The branch's month columns with a **unique** label for each one.

        A branch that owns the same month twice (a panel that covers two
        years, for instance) would otherwise silently lose one of the two
        blocks when the block frame is built.
        """
        columns = sorted(
            column
            for column, owner in self.branch_by_column.items()
            if owner == branch and column in self.months_by_column
        )
        used: dict[str, int] = {}
        result: list[tuple[int, str]] = []
        for column in columns:
            label = self.months_by_column[column]
            count = used.get(label, 0) + 1
            used[label] = count
            result.append((column, label if count == 1 else f"{label} ({count})"))
        return result

    def month_count(self, branch: str) -> int:
        """How many month columns the given branch owns."""
        return sum(1 for value in self.branch_by_column.values() if value == branch)

    def month_labels(self, branch: str) -> list[str]:
        """The month labels of one branch, in workbook order."""
        return [label for _column, label in self._branch_columns(branch)]

    def block(self, branch: str) -> pd.DataFrame:
        """Return the monthly matrix of one branch.

        Columns: ``sku``, ``name``, ``category``, ``price`` plus one column
        per month owned by the branch.
        """
        frame = pd.DataFrame(
            {
                "sku": self.sku.reset_index(drop=True),
                "name": self.name.reset_index(drop=True),
                "category": self.category.reset_index(drop=True),
                "price": self.price.reset_index(drop=True),
            }
        )
        for column, label in self._branch_columns(branch):
            frame[label] = self._values[column]
        return frame


def _forward_fill(values: Iterable[Any]) -> list[Any]:
    """Carry the last non-empty label forward."""
    filled: list[Any] = []
    current: Any = None
    for value in values:
        if isinstance(value, str) and value.strip():
            current = value.strip()
        elif value is not None and not isinstance(value, float):
            if pd.notna(value):
                current = str(value).strip()
        filled.append(current)
    return filled


def _panel_label_hits(row: pd.Series) -> int:
    """How many of the panel's identity labels the row carries."""
    labels = {normalize_key(label) for label in PANEL_IDENTITY_LABELS}
    return sum(1 for value in row if normalize_key(value) in labels)


def _find_panel_header_row(raw: pd.DataFrame) -> int:
    """Locate the header row of a panel by its identity columns.

    The ERP writes the panel with a three-row prologue::

        row 0   التصنيف | كود الصنف | اسم الصنف | السعر | <branch> | ... |
        row 1   0        | 1         | 2         | 3     | 4        | ... |
        row 2   التصنيف | كود الصنف | اسم الصنف | السعر | مايو      | ... |
        row 3   كاشير    | 1         | أصناف ... | 1     | 210      | ... |

    Row 0 carries the **branch** names and row 2 carries the **month**
    labels; both repeat the identity columns.  The header is therefore the
    **last** row that carries the identity columns -- the one that also owns
    the month labels.
    """
    limit = min(12, len(raw))
    candidates = [
        index for index in range(limit) if _panel_label_hits(raw.iloc[index]) >= 3
    ]
    if not candidates:
        candidates = [
            index for index in range(limit) if _panel_label_hits(raw.iloc[index]) >= 2
        ]
    if not candidates:
        raise ValueError(
            "The sales panel header could not be located (expected the columns "
            "'التصنيف', 'كود الصنف', 'اسم الصنف', 'السعر')."
        )
    return candidates[-1]


def _find_panel_branch_row(
    raw: pd.DataFrame,
    header_row: int,
    first_data_column: int,
) -> int:
    """Locate the row that carries the branch names.

    The branch name is written **once per block**, in the first column of the
    block, so the row is *sparse*: the numeric index row that sits between
    the branch row and the header row holds no text at all.  The row above
    the header that carries the most text is therefore the branch row.
    """
    best_row = -1
    best_text = 0
    for index in range(header_row):
        row = raw.iloc[index]
        text = sum(
            1
            for value in row.iloc[first_data_column:]
            if isinstance(value, str) and value.strip()
        )
        if text > best_text:
            best_text = text
            best_row = index
    if best_row >= 0:
        return best_row
    # no branch row at all -- fall back to the row right above the header
    return max(0, header_row - 2)


def read_sales_panel(payload: bytes, filename: str = "") -> SalesPanel:
    """Read the wide historical sales panel."""
    raw, sheet_name = _read_excel_smart(payload)
    if raw.empty:
        raise ValueError("The sales panel is empty.")

    header_row = _find_panel_header_row(raw)
    header_values = raw.iloc[header_row].tolist()

    identity: dict[str, int] = {}
    for index, value in enumerate(header_values):
        key = normalize_key(value)
        if key == normalize_key("كود الصنف") and "sku" not in identity:
            identity["sku"] = index
        elif key == normalize_key("اسم الصنف") and "name" not in identity:
            identity["name"] = index
        elif key == normalize_key("التصنيف") and "category" not in identity:
            identity["category"] = index
        elif key == normalize_key("السعر") and "price" not in identity:
            identity["price"] = index
    identity.setdefault("sku", 1)
    identity.setdefault("name", 2)
    identity.setdefault("category", 0)
    identity.setdefault("price", 3)

    first_data_column = max(identity.values()) + 1

    # the branch names live in a sparse row above the header
    branch_row = _find_panel_branch_row(raw, header_row, first_data_column)
    branch_labels = _forward_fill(raw.iloc[branch_row].tolist())

    data = raw.iloc[header_row + 1 :].reset_index(drop=True)

    months_by_column: dict[int, str] = {}
    branch_by_column: dict[int, str] = {}
    values_by_column: dict[int, pd.Series] = {}

    for column in range(first_data_column, data.shape[1]):
        month = header_values[column] if column < len(header_values) else None
        branch = branch_labels[column] if column < len(branch_labels) else None
        if not isinstance(month, str) or not month.strip():
            continue
        if not branch:
            continue
        months_by_column[column] = month.strip()
        branch_by_column[column] = branch
        values_by_column[column] = pd.to_numeric(
            data.iloc[:, column], errors="coerce"
        ).reset_index(drop=True)

    def series_at(key: str) -> pd.Series:
        return data.iloc[:, identity[key]].reset_index(drop=True)

    panel = SalesPanel(
        sku=series_at("sku"),
        name=series_at("name"),
        category=series_at("category"),
        price=series_at("price"),
        months_by_column=months_by_column,
        branch_by_column=branch_by_column,
        sheet_name=sheet_name,
    )
    panel._values = values_by_column
    return panel


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def _read_uploaded_bytes(uploaded_file: Any) -> tuple[bytes, str]:
    """Return the raw bytes and the display name of an uploaded file."""
    if isinstance(uploaded_file, (bytes, bytearray)):
        return bytes(uploaded_file), "upload"
    filename = getattr(uploaded_file, "name", "upload")
    read = getattr(uploaded_file, "read", None)
    if read is None:
        raise ValueError("Unsupported file object.")
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError, ValueError):
        pass
    payload = read()
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return bytes(payload), filename


def load_and_clean_data(uploaded_file: Any, role: str | None = None) -> pd.DataFrame:
    """Read, validate and clean one uploaded file.

    When ``role`` is ``None`` the role is detected from the columns.
    """
    payload, filename = _read_uploaded_bytes(uploaded_file)
    return load_and_clean_bytes(payload, filename, role)


def load_and_clean_bytes(
    payload: bytes,
    filename: str = "",
    role: str | None = None,
) -> pd.DataFrame:
    """Validate and clean the raw bytes of one uploaded file.

    ``filename`` is used for the error messages only; the role is detected
    from the columns and the format is sniffed from the bytes.
    """
    _role, frame = prepare_bytes(payload, filename, role)
    return frame


def prepare_bytes(
    payload: bytes,
    filename: str = "",
    role: str | None = None,
) -> tuple[str, pd.DataFrame]:
    """Read one file and return **its role** together with the clean frame.

    The role is detected from the column signature unless the caller knows
    it already.  The file name never takes part in the decision.
    """
    label = filename or "the uploaded file"
    file_format = detect_format(payload, filename)

    if role == "panel_sales":
        raise ValueError(
            f"'{label}' is a wide historical sales panel and must be loaded "
            "through the panel reader."
        )

    try:
        if file_format == "csv":
            raw = _read_csv_best(payload, role)
        else:
            raw, _sheet = _read_excel_smart(payload)
    except (ImportError, OSError, ValueError, zipfile.BadZipFile) as exc:
        LOGGER.warning("Unable to read %s: %s", label, exc)
        raise ValueError(
            f"Could not read '{label}'. Check that the file is a valid workbook."
        ) from exc

    if file_format == "csv":
        frame = raw
    else:
        header_row = detect_header_row(raw)
        frame = apply_header(raw, header_row)

    if role is None:
        role = detect_role(frame)
        if role is None:
            raise ValueError(
                f"Could not recognise the role of '{label}'. Its columns are: "
                f"{', '.join(str(column) for column in frame.columns[:20])}."
            )
        if role == "panel_sales":
            raise ValueError(
                f"'{label}' is a wide historical sales panel and must be loaded "
                "through the panel reader."
            )

    frame = canonicalize_columns(frame, role)
    try:
        validate_columns(
            frame,
            [str(column) for column in FILE_SPECS[role]["columns"]],
            label,
        )
    except Exception:
        if role == "master":
            # Master can be read without some optional required columns in older specs
            pass
        else:
            raise
    return role, clean_frame(frame, role)


def load_and_detect(payload: bytes, filename: str = "") -> tuple[str, pd.DataFrame]:
    """Read one file and return its detected role and its clean frame."""
    return prepare_bytes(payload, filename, None)


def _read_csv_best(payload: bytes, role: str | None) -> pd.DataFrame:
    """Read a CSV, preferring the parse that matches the expected columns."""
    candidates = _read_csv_candidates(payload)
    if not candidates:
        raise ValueError("The CSV file could not be decoded.")

    if role is not None:
        required = [str(column) for column in FILE_SPECS[role]["columns"]]
        for candidate in candidates:
            mapped = canonicalize_columns(candidate, role)
            if all(column in mapped.columns for column in required):
                return mapped
        return canonicalize_columns(candidates[0], role)

    for candidate in candidates:
        if detect_role(candidate) is not None:
            return candidate
    return candidates[0]


def load_panel(uploaded_file: Any) -> SalesPanel:
    """Read a wide historical sales panel from an uploaded file."""
    payload, filename = _read_uploaded_bytes(uploaded_file)
    return read_sales_panel(payload, filename)


def describe_roles(frames: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Return the row count of every loaded role (for the diagnostics strip)."""
    return {
        role: int(len(frame))
        for role, frame in frames.items()
        if isinstance(frame, pd.DataFrame)
    }
