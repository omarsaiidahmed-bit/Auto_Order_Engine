"""Value normalisation helpers.

Everything that turns raw ERP text into a comparable value lives here so the
same rule is applied to categories, item names, item codes and operations.

Three things are handled defensively because real exports contain them:

* Arabic-Indic (``٠١٢٣``) and Persian (``۰۱۲۳``) digits.
* Excel's trailing ``.0`` on integer item codes.
* Arabic letter variants (``أ``/``إ``/``ا`` and ``ى``/``ي``).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

__all__ = [
    "ARABIC_DIGITS",
    "PERSIAN_DIGITS",
    "ARABIC_LETTER_NORMALIZATION",
    "clean_sku",
    "clean_text_column",
    "clean_text_value",
    "normalize_arabic_text",
    "normalize_operation",
    "normalize_key",
    "parse_date_series",
    "parse_numeric_column",
    "to_numeric_series",
]

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

#: ``أ``/``إ``/``آ`` -> ``ا`` and ``ى`` -> ``ي`` and ``ؤ`` -> ``و`` and ``ئ`` -> ``ي``.
ARABIC_LETTER_NORMALIZATION = str.maketrans(
    {
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
    }
)

_TRAILING_FLOAT = re.compile(r"\.0+$")
_TATWEEL = "\u0640"
_KEY_STRIP_RE = re.compile(r"[\s\-_./,()\[\]{}'\"]+")

#: ``2026/10/03`` -- the year comes first.
_YEAR_FIRST_DATE_RE = re.compile(r"^\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")
#: ``03/10/2026`` -- the day comes first.
_DAY_FIRST_DATE_RE = re.compile(r"^\s*\d{1,2}[-/.]\d{1,2}[-/.]\d{4}")


def clean_sku(value: Any) -> Any:
    """Normalise an item code into a trimmed text identifier.

    Only a *trailing* ``.0`` is removed (Excel writes integer codes as
    floats).  Leading zeros are preserved because a SKU is an identifier and
    never a measure.
    """
    if value is None:
        return pd.NA
    try:
        if pd.isna(value):
            return pd.NA
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    text = text.translate(ARABIC_DIGITS).translate(PERSIAN_DIGITS)
    text = _TRAILING_FLOAT.sub("", text)
    return text if text else pd.NA


def clean_text_value(value: Any) -> Any:
    """Return a trimmed string, mapping blanks to ``pd.NA``."""
    if value is None:
        return pd.NA
    try:
        if pd.isna(value):
            return pd.NA
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else pd.NA


def clean_text_column(series: pd.Series) -> pd.Series:
    """Trim a text column and represent empty strings as missing values."""
    return series.astype("string").str.strip().replace("", pd.NA)


def normalize_arabic_text(value: Any) -> str:
    """Normalise Arabic text for *comparison* (not for display).

    Applies digit unification, Arabic letter variants, tatweel removal and
    whitespace collapsing.  The result is a comparison key; it is never shown
    to the user.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    text = text.translate(ARABIC_DIGITS).translate(PERSIAN_DIGITS)
    text = text.translate(ARABIC_LETTER_NORMALIZATION)
    text = text.replace(_TATWEEL, "")
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split())


def normalize_key(value: Any) -> str:
    """Return a case-insensitive, punctuation-free comparison key."""
    text = normalize_arabic_text(value).casefold()
    text = _KEY_STRIP_RE.sub("", text)
    return text


def _normalise_numeric_text(series: pd.Series) -> pd.Series:
    """Strip separators and convert Arabic/Persian digits to ASCII."""
    return (
        series.astype("string")
        .str.strip()
        .str.translate(ARABIC_DIGITS)
        .str.translate(PERSIAN_DIGITS)
        .str.replace("\u066c", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("\u066b", ".", regex=False)
        .replace("", pd.NA)
    )


def parse_numeric_column(
    series: pd.Series,
    column_name: str,
    *,
    fill_missing: bool = True,
) -> pd.Series:
    """Parse a numeric column, raising on values that cannot be interpreted.

    Blank cells become ``0`` when ``fill_missing`` is true, otherwise ``NaN``.
    Non-empty values that fail to parse are a hard error -- they are never
    silently converted to zero.
    """
    normalised = _normalise_numeric_text(series)
    values = pd.to_numeric(normalised, errors="coerce")
    invalid = normalised.notna() & values.isna()
    non_finite = values.isin([float("inf"), float("-inf")])
    if bool(invalid.any()) or bool(non_finite.any()):
        bad_rows = invalid | non_finite
        examples = series.loc[bad_rows].head(5).tolist()
        raise ValueError(
            f"Invalid numeric values in column '{column_name}': {examples}"
        )
    return values.fillna(0) if fill_missing else values


def to_numeric_series(series: pd.Series) -> pd.Series:
    """Coerce to numeric without raising; non-numeric becomes ``NaN``."""
    return pd.to_numeric(_normalise_numeric_text(series), errors="coerce")


def parse_date_series(series: pd.Series) -> pd.Series:
    """Parse a date column, deciding the day/month order **from the data**.

    A fixed ``dayfirst`` flag is a trap: the ERP writes ``2026/10/03`` and a
    day-first reader turns it into the 3rd of October, which stretches a
    twenty-day report into a three-hundred-and-thirty-five-day one and
    silently divides the demand by eleven.  The order is therefore detected
    by looking at the values themselves.

    Excel serial numbers (a bare number in a date column) are recognised as
    well and converted from the 1899-12-30 origin.
    """
    if series is None:
        return pd.Series(dtype="datetime64[ns]")

    raw = series.astype("string").str.strip()
    if raw.eq("").any():
        raw = raw.mask(raw.eq(""), pd.NA)

    year_first = int(raw.str.match(_YEAR_FIRST_DATE_RE, na=False).sum())
    day_first = int(raw.str.match(_DAY_FIRST_DATE_RE, na=False).sum())

    if year_first == 0 and day_first == 0:
        # no recognisable text date -- maybe an Excel serial number
        numeric = pd.to_numeric(raw, errors="coerce")
        if numeric.notna().sum() and numeric.between(20000, 60000).sum() >= numeric.notna().sum() / 2:
            return pd.to_datetime(numeric, unit="D", origin="1899-12-30", errors="coerce")
        return pd.to_datetime(raw, format="mixed", errors="coerce")

    use_day_first = day_first > year_first
    parsed = pd.to_datetime(raw, format="mixed", dayfirst=use_day_first, errors="coerce")

    # whatever the first pass could not read is retried the other way round
    missing = parsed.isna() & raw.notna()
    if bool(missing.any()):
        retry = pd.to_datetime(
            raw[missing], format="mixed", dayfirst=not use_day_first, errors="coerce"
        )
        parsed.loc[missing] = retry
    return parsed


def normalize_operation(value: Any) -> str:
    """Normalise a transfer ``العملية`` label for token matching."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip().translate(ARABIC_LETTER_NORMALIZATION)
    text = text.replace(_TATWEEL, "")
    return " ".join(text.split())
