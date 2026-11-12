"""The notes vocabulary for the exported ``ملاحظات`` column.

The tests pin an exact, stable vocabulary and expect every note to be a
single module-level constant.  Friday is intentionally absent from the note
text, because it is a planning detail rather than a purchasing signal.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

__all__ = [
    "NOTE_CONSTANTS",
    "NOTE_FORM_MISMATCH",
    "NOTE_IMPLAUSIBLE_STOCK",
    "NOTE_MANUAL_EDIT",
    "NOTE_MASTER_MISSING",
    "NOTE_MULTI_PRICE",
    "NOTE_NEGATIVE_BRANCH",
    "NOTE_NEGATIVE_DEMAND",
    "NOTE_PACK_ROUNDING",
    "NOTE_SUBSTITUTE_AVAILABLE",
    "NOTE_SUBSTITUTE_ROW",
    "NOTE_TRANSFERS_EXCEED_STOCK",
    "NOTE_UNUSUAL_TRANSFERS",
    "NOTE_WAREHOUSE_MISSING",
    "NOTE_WAREHOUSE_SHORT",
    "build_notes",
    "join_notes",
]

NOTE_NEGATIVE_BRANCH = "تنبيه: رصيد الفرع سالب"
NOTE_IMPLAUSIBLE_STOCK = "تنبيه: رصيد غير منطقي"
NOTE_TRANSFERS_EXCEED_STOCK = "تنبيه: التحويلات الصادرة أكبر من الرصيد المتاح"
NOTE_WAREHOUSE_MISSING = "غير متوفر بالمخزن - يجب الشراء"
NOTE_WAREHOUSE_SHORT = "تم تغطية جزء من الطلب من المخزن، وشراء الباقي"
NOTE_SUBSTITUTE_AVAILABLE = "تم استبداله بالصنف: {sku}"
NOTE_SUBSTITUTE_ROW = "طلب بديل للصنف: {sku}"
NOTE_SUBSTITUTE_ROW_AR = "هذا بديل للصنف {name} الذي له معدل بيع ومش متوفر حالياً في المخزن"
NOTE_SUBSTITUTE_ROW_EN = "This is a substitute for {name} which has a sales rate and is currently unavailable in the warehouse"
NOTE_NEGATIVE_DEMAND = "تنبيه: استُبعدت قيمة طلب سالبة من الحساب"
NOTE_PACK_ROUNDING = "تم التقريب إلى عبوة كاملة (حجم العبوة: {pack})"
NOTE_FORM_MISMATCH = "تنبيه: البديل يختلف في الشكل الدوائي"
NOTE_UNUSUAL_TRANSFERS = "تنبيه: كمية تحويلات غير معتادة - راجع سجل التحويلات"
NOTE_MULTI_PRICE = "تنبيه: الصنف له أكثر من سعر بيع"
NOTE_MASTER_MISSING = "تنبيه: الصنف غير موجود في البيانات الرئيسية"
NOTE_MANUAL_EDIT = "تم تعديل الكمية يدويًا"

NOTE_CONSTANTS = {
    "NOTE_NEGATIVE_BRANCH": NOTE_NEGATIVE_BRANCH,
    "NOTE_IMPLAUSIBLE_STOCK": NOTE_IMPLAUSIBLE_STOCK,
    "NOTE_TRANSFERS_EXCEED_STOCK": NOTE_TRANSFERS_EXCEED_STOCK,
    "NOTE_WAREHOUSE_MISSING": NOTE_WAREHOUSE_MISSING,
    "NOTE_WAREHOUSE_SHORT": NOTE_WAREHOUSE_SHORT,
    "NOTE_SUBSTITUTE_AVAILABLE": NOTE_SUBSTITUTE_AVAILABLE,
    "NOTE_SUBSTITUTE_ROW": NOTE_SUBSTITUTE_ROW,
    "NOTE_SUBSTITUTE_ROW_AR": NOTE_SUBSTITUTE_ROW_AR,
    "NOTE_SUBSTITUTE_ROW_EN": NOTE_SUBSTITUTE_ROW_EN,
    "NOTE_NEGATIVE_DEMAND": NOTE_NEGATIVE_DEMAND,
    "NOTE_PACK_ROUNDING": NOTE_PACK_ROUNDING,
    "NOTE_FORM_MISMATCH": NOTE_FORM_MISMATCH,
    "NOTE_UNUSUAL_TRANSFERS": NOTE_UNUSUAL_TRANSFERS,
    "NOTE_MULTI_PRICE": NOTE_MULTI_PRICE,
    "NOTE_MASTER_MISSING": NOTE_MASTER_MISSING,
    "NOTE_MANUAL_EDIT": NOTE_MANUAL_EDIT,
}

_NOTE_SEPARATOR = "؛ "


def join_notes(parts: list[str]) -> str:
    """Join note fragments with the Arabic semicolon, dropping duplicates."""
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    return _NOTE_SEPARATOR.join(unique)


def _flag(record: Mapping[str, Any], key: str) -> bool:
    """Read a boolean flag from a result row."""
    try:
        return bool(record.get(key, False))
    except (TypeError, ValueError):
        return False


def _number(record: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    """Read a numeric field from a result row."""
    try:
        value = record.get(key, default)
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(record: Mapping[str, Any], key: str) -> str:
    """Read a text field from a result row."""
    value = record.get(key, "")
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def build_notes(row: Mapping[str, Any]) -> str:
    """Build the note string for one finished result row."""
    notes: list[str] = []

    if _flag(row, "Branch_Negative_Flag"):
        notes.append(NOTE_NEGATIVE_BRANCH)
    if _flag(row, "Implausible_Stock_Flag"):
        notes.append(NOTE_IMPLAUSIBLE_STOCK)
    if _number(row, "Effective_Stock") < 0:
        notes.append(NOTE_TRANSFERS_EXCEED_STOCK)
    if _flag(row, "Negative_Demand_Flag"):
        notes.append(NOTE_NEGATIVE_DEMAND)

    final_order = _number(row, "Final_Purchase_Order")
    calculated_order = _number(row, "Calculated_Order")
    warehouse_stock = _number(row, "Warehouse_Stock")
    order_to_check = max(final_order, calculated_order)
    if order_to_check > 0:
        if warehouse_stock <= 0:
            notes.append(NOTE_WAREHOUSE_MISSING)
        elif warehouse_stock < calculated_order:
            notes.append(NOTE_WAREHOUSE_SHORT)

    if _flag(row, "Master_Missing"):
        notes.append(NOTE_MASTER_MISSING)

    substitute_code = _text(row, "Substitute_Code")
    substituted_out = _flag(row, "Substituted_Out")
    if substitute_code and substituted_out:
        notes.append(NOTE_SUBSTITUTE_AVAILABLE.format(sku=substitute_code))
    if _flag(row, "Form_Mismatch"):
        notes.append(NOTE_FORM_MISMATCH)
    if _flag(row, "Pack_Rounding_Applied"):
        pack_size = _text(row, "Pack Size") or "1"
        notes.append(NOTE_PACK_ROUNDING.format(pack=pack_size))
    if _flag(row, "Unusual_Transfer_Flag"):
        notes.append(NOTE_UNUSUAL_TRANSFERS)
    if _flag(row, "Multi_Price_Flag"):
        notes.append(NOTE_MULTI_PRICE)

    return join_notes(notes)
