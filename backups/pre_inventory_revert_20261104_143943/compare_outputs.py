"""Compare the Auto Order V2 export with the manual pharmacy order workbook.

The script is intentionally read-only with respect to the two source workbooks.
It writes only ``Comparison_Report.md`` and prints the key numbers to stdout.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
INPUT_DIRS = (ROOT, ROOT / "SOP & Standards")


def find_input(filename: str) -> Path:
    """Find a source workbook in the project root or the SOP archive folder."""
    for directory in INPUT_DIRS:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find input workbook: {filename}")


V2_FILE = find_input("Auto_Order_Final.xlsx")
MANUAL_FILE = find_input("نواقص جناكليس 3.11.2026.xlsx")
REPORT_FILE = ROOT / "Comparison_Report.md"

V2_SHEET = "Final Order"
MANUAL_HEADER_ROW = 1  # row 0 is the merged title row


def normalise_code(value: Any) -> str:
    """Standardise SKU codes across both workbooks.

    Rules required by the business: trim, remove a trailing ``.0``, remove
    whitespace, and drop leading zeroes from purely numeric codes.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower().endswith(".0"):
        text = text[:-2]
    text = re.sub(r"\s+", "", text)
    if text.isdigit():
        text = text.lstrip("0") or "0"
    return text


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def join_unique(values: pd.Series) -> str:
    seen: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            seen.append(text)
    return " / ".join(seen)


def load_manual() -> tuple[pd.DataFrame, list[str]]:
    xl = pd.ExcelFile(MANUAL_FILE)
    frames: list[pd.DataFrame] = []
    for sheet in xl.sheet_names:
        frame = pd.read_excel(MANUAL_FILE, sheet_name=sheet, header=MANUAL_HEADER_ROW)
        frame = frame.dropna(how="all").copy()
        if "الكود" not in frame.columns:
            continue
        frame = frame[frame["الكود"].notna()].copy()
        if frame.empty:
            continue
        frame["sheet"] = sheet
        frames.append(frame)
    if not frames:
        raise ValueError("No usable manual sheets were found.")
    manual = pd.concat(frames, ignore_index=True)
    manual["code"] = manual["الكود"].map(normalise_code)
    manual = manual[manual["code"].ne("")].copy()
    for column in ("المطلوب", "السعر", "الموجود", "المتوسط", "المخزن"):
        if column not in manual.columns:
            manual[column] = 0.0
        manual[column] = numeric(manual[column])
    manual["manual_financial"] = manual["المطلوب"] * manual["السعر"]
    manual["name"] = manual["الاسم"].map(clean_text)
    manual["category"] = manual["التصنيف"].map(clean_text)
    manual["notes"] = manual["ملاحظات"].map(clean_text)
    return manual, xl.sheet_names


def load_v2() -> tuple[pd.DataFrame, list[str]]:
    xl = pd.ExcelFile(V2_FILE)
    sheet = V2_SHEET if V2_SHEET in xl.sheet_names else xl.sheet_names[0]
    v2 = pd.read_excel(V2_FILE, sheet_name=sheet)
    v2["code"] = v2["الكود"].map(normalise_code)
    v2 = v2[v2["code"].ne("")].copy()
    for column in (
        "المطلوب",
        "السعر",
        "القيمة المالية للطلب",
        "الموجود في الفرع",
        "الموجود في المخزن",
        "المتوسط",
        "ROP",
    ):
        if column not in v2.columns:
            v2[column] = 0.0
        v2[column] = numeric(v2[column])
    v2["name"] = v2["الاسم"].map(clean_text)
    v2["reason"] = v2["سبب الطلب"].map(clean_text)
    v2["notes"] = v2["ملاحظات"].map(clean_text)
    return v2, xl.sheet_names


def aggregate_manual(manual: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        manual.groupby("code", as_index=False)
        .agg(
            manual_name=("name", "first"),
            manual_category=("category", "first"),
            manual_required=("المطلوب", "sum"),
            manual_price=("السعر", "first"),
            manual_financial=("manual_financial", "sum"),
            manual_branch=("الموجود", "first"),
            manual_average=("المتوسط", "first"),
            manual_warehouse=("المخزن", "first"),
            manual_notes=("notes", join_unique),
            manual_sheets=("sheet", join_unique),
            manual_rows=("code", "size"),
        )
    )
    return grouped


def aggregate_v2(v2: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        v2.groupby("code", as_index=False)
        .agg(
            v2_name=("name", "first"),
            v2_required=("المطلوب", "sum"),
            v2_price=("السعر", "first"),
            v2_financial=("القيمة المالية للطلب", "sum"),
            v2_branch=("الموجود في الفرع", "first"),
            v2_warehouse=("الموجود في المخزن", "first"),
            v2_average=("المتوسط", "first"),
            v2_rop=("ROP", "first"),
            v2_reason=("reason", join_unique),
            v2_notes=("notes", join_unique),
            v2_rows=("code", "size"),
        )
    )
    return grouped


def classify_manual_only(row: pd.Series) -> str:
    required = float(row.get("manual_required", 0.0) or 0.0)
    average = float(row.get("manual_average", 0.0) or 0.0)
    warehouse = float(row.get("manual_warehouse", 0.0) or 0.0)
    if required <= 0:
        return "Manual row has no positive request (not a missed order)."
    if average <= 0:
        return "Stagnant / no sales history: 0 demand with stock, excluded by V2."
    if warehouse >= required:
        return (
            "Warehouse stock covers the manual request; V2's purchase layer is "
            "zero, so the row is absent from the net export."
        )
    return (
        "Not present in the V2 snapshot: missing master/scope data, or V2 "
        "calculated zero after its ROP/Target test; needs a master-data check."
    )


def classify_v2_only(row: pd.Series) -> str:
    reason = clean_text(row.get("v2_reason", ""))
    notes = clean_text(row.get("v2_notes", ""))
    if "بديل" in reason or "بديل" in notes:
        return "Substitute line added by V2 for a shortfall; manual has no equivalent row."
    if "Pushing" in reason:
        return "Pushing-list item: V2 exposes a priority item the manual sheet missed."
    if "تجميل" in reason:
        return "Cosmetics distribution override: V2 exposes a forced cosmetics line."
    if "تحويلات" in reason:
        return "Transfer-driven line: V2 includes a branch transfer that the manual sheet missed."
    return "V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed."


def explain_mismatch(row: pd.Series) -> str:
    manual_qty = float(row.get("manual_required", 0.0) or 0.0)
    v2_qty = float(row.get("v2_required", 0.0) or 0.0)
    manual_avg = float(row.get("manual_average", 0.0) or 0.0)
    v2_avg = float(row.get("v2_average", 0.0) or 0.0)
    warehouse = float(row.get("v2_warehouse", 0.0) or 0.0)
    reason = clean_text(row.get("v2_reason", ""))
    notes = clean_text(row.get("v2_notes", ""))

    if "بديل" in reason or "بديل" in notes:
        return (
            "V2 line is a substitute shortfall for another SKU; the manual sheet "
            "has no separate substitute line, so the two quantities are not "
            "directly comparable."
        )
    if manual_qty <= 0 < v2_qty:
        return (
            "Manual omitted the item (0 request); V2 triggered a need from its "
            "ROP/Target calculation."
        )
    if v2_qty == 1 and manual_qty > 1 and ("Pushing" in reason or "تجميل" in reason):
        return (
            "V2 created a 1-unit forced distribution line; manual ordered the "
            "full branch quantity instead of a minimum display quantity."
        )
    if warehouse > 0 and v2_qty < manual_qty:
        return (
            f"V2 netted warehouse stock ({warehouse:g}) from the purchase layer; "
            "the manual quantity is gross of the central warehouse."
        )
    if manual_avg > 0 and v2_avg > manual_avg * 1.20:
        return (
            f"V2 demand average is {v2_avg:.2f}/month vs manual {manual_avg:.2f}; "
            "the higher average raises the ROP and Target."
        )
    if manual_avg > 0 and v2_avg < manual_avg * 0.80:
        return (
            f"V2 demand average is {v2_avg:.2f}/month vs manual {manual_avg:.2f}; "
            "the lower average lowers the ROP and Target."
        )
    if v2_qty < manual_qty:
        return (
            "V2's ROP/Target produced a lower quantity than the manual rule; the "
            "difference is demand/coverage assumptions, not a missing SKU."
        )
    return (
        "V2's ROP/Target produced a higher quantity than the manual rule; the "
        "difference is demand/coverage assumptions, not a missing SKU."
    )


def explain_over_order(row: pd.Series) -> str:
    manual_qty = float(row.get("manual_required", 0.0) or 0.0)
    v2_qty = float(row.get("v2_required", 0.0) or 0.0)
    manual_avg = float(row.get("manual_average", 0.0) or 0.0)
    v2_avg = float(row.get("v2_average", 0.0) or 0.0)
    reason = clean_text(row.get("v2_reason", ""))
    if v2_qty == 1 and manual_qty > 1 and ("Pushing" in reason or "تجميل" in reason):
        return "V2 capped a forced distribution line at 1; manual over-ordered."
    if manual_avg > 0 and v2_avg < manual_avg * 0.80:
        return (
            f"V2 uses a lower sales average ({v2_avg:.2f} vs {manual_avg:.2f}); "
            "the manual request is above the statistical need."
        )
    return "V2's ROP/Target is below the manual request; the manual rule over-ordered."


def md_table(frame: pd.DataFrame, columns: list[str], rename: dict[str, str] | None = None) -> str:
    view = frame.loc[:, columns].copy()
    if rename:
        view = view.rename(columns=rename)
    for column in view.columns:
        if pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].map(lambda value: f"{value:,.2f}")
        elif pd.api.types.is_integer_dtype(view[column]):
            view[column] = view[column].map(lambda value: f"{value:,}")
    return view.to_markdown(index=False, tablefmt="github")


def pct(value: float, base: float) -> str:
    if not base:
        return "n/a"
    return f"{(value / base - 1.0) * 100:+.1f}%"


def build_report(
    manual: pd.DataFrame,
    v2: pd.DataFrame,
    manual_agg: pd.DataFrame,
    v2_agg: pd.DataFrame,
    manual_sheets: list[str],
    v2_sheets: list[str],
) -> str:
    merged = manual_agg.merge(v2_agg, on="code", how="outer", indicator=True)
    merged["manual_name"] = merged["manual_name"].fillna("")
    merged["v2_name"] = merged["v2_name"].fillna("")
    merged["manual_required"] = merged["manual_required"].fillna(0.0)
    merged["v2_required"] = merged["v2_required"].fillna(0.0)
    merged["manual_financial"] = merged["manual_financial"].fillna(0.0)
    merged["v2_financial"] = merged["v2_financial"].fillna(0.0)
    merged["manual_price"] = merged["manual_price"].fillna(0.0)
    merged["v2_price"] = merged["v2_price"].fillna(0.0)
    merged["manual_branch"] = merged["manual_branch"].fillna(0.0)
    merged["v2_branch"] = merged["v2_branch"].fillna(0.0)
    merged["manual_warehouse"] = merged["manual_warehouse"].fillna(0.0)
    merged["v2_warehouse"] = merged["v2_warehouse"].fillna(0.0)
    merged["manual_average"] = merged["manual_average"].fillna(0.0)
    merged["v2_average"] = merged["v2_average"].fillna(0.0)
    merged["v2_reason"] = merged["v2_reason"].fillna("")
    merged["v2_notes"] = merged["v2_notes"].fillna("")
    merged["manual_notes"] = merged["manual_notes"].fillna("")
    merged["manual_sheets"] = merged["manual_sheets"].fillna("")
    merged["v2_rows"] = merged["v2_rows"].fillna(0).astype(int)
    merged["manual_rows"] = merged["manual_rows"].fillna(0).astype(int)

    manual_only = merged[merged["_merge"].eq("left_only")].copy()
    v2_only = merged[merged["_merge"].eq("right_only")].copy()
    inner = merged[merged["_merge"].eq("both")].copy()
    inner["quantity_gap"] = inner["v2_required"] - inner["manual_required"]
    inner["abs_gap"] = inner["quantity_gap"].abs()
    inner["value_gap"] = inner["v2_financial"] - inner["manual_financial"]

    manual_only["reason_category"] = manual_only.apply(classify_manual_only, axis=1)
    v2_only["reason_category"] = v2_only.apply(classify_v2_only, axis=1)
    inner["explanation"] = inner.apply(explain_mismatch, axis=1)

    manual_financial = float(manual["manual_financial"].sum())
    v2_financial = float(v2["القيمة المالية للطلب"].sum())
    manual_qty = float(manual["المطلوب"].sum())
    v2_qty = float(v2["المطلوب"].sum())
    manual_codes = int(manual_agg["code"].nunique())
    v2_codes = int(v2_agg["code"].nunique())
    intersection = int(len(inner))
    manual_only_count = int(len(manual_only))
    v2_only_count = int(len(v2_only))
    v2_duplicate_rows = int(len(v2) - v2_codes)
    manual_duplicate_rows = int(len(manual) - manual_codes)

    manual_only_positive = manual_only[manual_only["manual_required"] > 0]
    manual_only_stagnant = manual_only[
        (manual_only["manual_required"] > 0) & (manual_only["manual_average"] <= 0)
    ]
    manual_only_warehouse = manual_only[
        (manual_only["manual_required"] > 0)
        & (manual_only["manual_average"] > 0)
        & (manual_only["manual_warehouse"] >= manual_only["manual_required"])
    ]
    manual_only_no_request = manual_only[manual_only["manual_required"] <= 0]
    manual_only_remaining = manual_only[
        (manual_only["manual_required"] > 0)
        & (manual_only["manual_average"] > 0)
        & (manual_only["manual_warehouse"] < manual_only["manual_required"])
    ]

    v2_only_positive = v2_only[v2_only["v2_required"] > 0].copy()
    v2_only_positive["value"] = v2_only_positive["v2_financial"]
    v2_only_positive = v2_only_positive.sort_values("value", ascending=False)
    v2_only_top = v2_only_positive.head(30)

    manual_only_positive = manual_only_positive.copy()
    manual_only_positive["value"] = manual_only_positive["manual_financial"]
    manual_only_top = manual_only_positive.sort_values(
        "value", ascending=False
    ).head(30)

    smoking = inner[inner["abs_gap"] > 0].sort_values(
        ["abs_gap", "value_gap"], ascending=False
    ).head(30)

    over_ordered = inner[
        (inner["manual_required"] > inner["v2_required"])
        & (inner["manual_financial"] > 0)
    ].copy()
    over_ordered["manual_over_value"] = (
        over_ordered["manual_required"] - over_ordered["v2_required"]
    ) * over_ordered["manual_price"].where(
        over_ordered["manual_price"] > 0, over_ordered["v2_price"]
    )
    over_ordered["explanation"] = over_ordered.apply(explain_over_order, axis=1)
    over_ordered_top = over_ordered.sort_values(
        "manual_over_value", ascending=False
    ).head(30)

    reason_counts = (
        v2.groupby("reason", dropna=False)
        .agg(rows=("code", "size"), quantity=("المطلوب", "sum"), value=("القيمة المالية للطلب", "sum"))
        .sort_values("value", ascending=False)
        .reset_index()
    )
    reason_counts["reason"] = reason_counts["reason"].replace("", "(blank)")

    top_smoking_table = md_table(
        smoking,
        [
            "code",
            "manual_name",
            "manual_required",
            "v2_required",
            "quantity_gap",
            "manual_price",
            "v2_warehouse",
            "explanation",
        ],
        {
            "code": "Code",
            "manual_name": "Item",
            "manual_required": "Manual Qty",
            "v2_required": "V2 Qty",
            "quantity_gap": "Gap (V2 - Manual)",
            "manual_price": "Price",
            "v2_warehouse": "V2 Warehouse",
            "explanation": "Why",
        },
    )
    v2_only_table = md_table(
        v2_only_top,
        ["code", "v2_name", "v2_required", "v2_price", "v2_financial", "v2_reason", "reason_category"],
        {
            "code": "Code",
            "v2_name": "Item",
            "v2_required": "V2 Qty",
            "v2_price": "Price",
            "v2_financial": "V2 Value",
            "v2_reason": "V2 Reason",
            "reason_category": "Why V2 included it",
        },
    )
    manual_only_table = md_table(
        manual_only_top,
        ["code", "manual_name", "manual_required", "manual_price", "manual_financial", "manual_average", "manual_warehouse", "reason_category"],
        {
            "code": "Code",
            "manual_name": "Item",
            "manual_required": "Manual Qty",
            "manual_price": "Price",
            "manual_financial": "Manual Value",
            "manual_average": "Monthly Avg",
            "manual_warehouse": "Warehouse",
            "reason_category": "Why V2 excluded it",
        },
    )
    over_table = md_table(
        over_ordered_top,
        ["code", "manual_name", "manual_required", "v2_required", "manual_price", "manual_over_value", "explanation"],
        {
            "code": "Code",
            "manual_name": "Item",
            "manual_required": "Manual Qty",
            "v2_required": "V2 Qty",
            "manual_price": "Price",
            "manual_over_value": "Manual Over-Order Value",
            "explanation": "Why",
        },
    )
    reason_table = md_table(
        reason_counts,
        ["reason", "rows", "quantity", "value"],
        {
            "reason": "V2 Reason",
            "rows": "Rows",
            "quantity": "Quantity",
            "value": "Financial Value",
        },
    )

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append("# Auto Order V2 vs Manual — Comparison & Code Audit Report")
    lines.append("")
    lines.append(f"Generated: {generated}")
    lines.append("")
    lines.append("> **Scope note:** The V2 workbook in `SOP & Standards` is the pre-fix snapshot. "
                 "The code fixes below were applied after that snapshot, so the comparison "
                 "numbers describe the old output. Re-run the pipeline to produce the corrected "
                 "workbook. No Streamlit process was started and no source workbook was modified.")
    lines.append("")
    lines.append("## 1. Executive Summary (Arabic)")
    lines.append("")
    lines.append("### 1.1 الأرقام الرئيسية")
    lines.append("")
    lines.append("| المؤشر | ملف V2 | الملف اليدوي | الفرق |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| عدد الصفوف | {len(v2):,} | {len(manual):,} | {len(v2) - len(manual):+,} |")
    lines.append(f"| عدد الأكواد الفريدة | {v2_codes:,} | {manual_codes:,} | {v2_codes - manual_codes:+,} |")
    lines.append(f"| إجمالي الكمية المطلوبة | {v2_qty:,.0f} | {manual_qty:,.0f} | {v2_qty - manual_qty:+,.0f} |")
    lines.append(f"| إجمالي القيمة المالية | {v2_financial:,.2f} | {manual_financial:,.2f} | {v2_financial - manual_financial:+,.2f} |")
    lines.append(f"| الأكواد المشتركة | {intersection:,} | {intersection:,} | — |")
    lines.append(f"| أكواد في V2 فقط | {v2_only_count:,} | — | — |")
    lines.append(f"| أكواد في اليدوي فقط | — | {manual_only_count:,} | — |")
    lines.append("")
    lines.append(
        f"القيمة المالية في V2 أعلى بنسبة **{pct(v2_financial, manual_financial)}** "
        f"والكمية أعلى بنسبة **{pct(v2_qty, manual_qty)}**. هذا ليس خطأً حسابياً "
        "بحد ذاته: V2 يستخدم ROP وTarget وLead Time بينما اليدوي يستخدم قواعد "
        "VLOOKUP أبسط، كما أن V2 يضيف أسطر بدائل وبنود Pushing/Cosmetics."
    )
    lines.append("")
    lines.append("### 1.2 لماذا تختلف الأرقام؟")
    lines.append("")
    lines.append(
        f"- **{manual_only_count:,}** كوداً موجود في اليدوي وغير موجود في V2. "
        f"التصنيف غير المتداخل: **{len(manual_only_no_request):,}** بطلب صفر "
        f"(ليست نواقص أصلاً)، **{len(manual_only_stagnant):,}** بلا مبيعات (راكد)، "
        f"**{len(manual_only_warehouse):,}** يغطيها مخزن الفرع بالكامل، "
        f"و**{len(manual_only_remaining):,}** بطلب موجب ومخزون غير كافٍ — "
        "هذه هي الحالات التي تحتاج مراجعة ماستر/نطاق قبل اعتبارها نقصاً حقيقياً."
    )
    lines.append(
        f"- **{v2_only_count:,}** كوداً أضافه V2. أهم الأسباب: "
        "Pushing List، توزيع التجميل، نقص لم يلتقطه اليدوي، وأسطر البدائل."
    )
    lines.append(
        f"- **{len(smoking):,}** صفاً مشتركاً فيه فرق كميات كبير. "
        "أهم 30 حالة موضحة في القسم 4 مع السبب الرياضي/البياني لكل حالة."
    )
    lines.append(
        "- **تحذير مقارنة:** V2 يضم أسطر بدائل متكررة لنفس كود الصنف البديل؛ "
        f"عدد صفوف V2 {len(v2):,} بينما الأكواد الفريدة {v2_codes:,}، أي "
        f"{v2_duplicate_rows:,} صفاً إضافياً. المقارنة في هذا التقرير تُجمّع V2 حسب الكود."
    )
    lines.append("")
    lines.append("## 2. Data & Method")
    lines.append("")
    lines.append(f"- V2 source: `{V2_FILE.name}` — sheets: {', '.join(v2_sheets)}; used `{V2_SHEET}`.")
    lines.append(f"- Manual source: `{MANUAL_FILE.name}` — sheets: {', '.join(manual_sheets)}; header row {MANUAL_HEADER_ROW + 1}.")
    lines.append("- Codes were trimmed, `.0` suffixes removed, whitespace removed, and leading zeroes dropped from numeric codes.")
    lines.append("- V2 rows were aggregated by code for the comparison; substitute rows can otherwise double-count the target SKU.")
    lines.append("- Manual financial value = `المطلوب × السعر`; V2 financial value = `القيمة المالية للطلب`.")
    lines.append("- The comparison is observational: the raw ERP input files were not present in this folder, so the pipeline could not be re-run to regenerate V2.")
    lines.append("")
    lines.append("## 3. Headline Comparison")
    lines.append("")
    lines.append("### 3.1 V2 reason distribution (pre-fix snapshot)")
    lines.append("")
    lines.append(reason_table)
    lines.append("")
    lines.append("### 3.2 Coverage")
    lines.append("")
    lines.append("| Segment | Codes |")
    lines.append("|---|---:|")
    lines.append(f"| Manual only | {manual_only_count:,} |")
    lines.append(f"| V2 only | {v2_only_count:,} |")
    lines.append(f"| Both | {intersection:,} |")
    lines.append("")
    lines.append("## 4. The \"Smoking Guns\" — Top 30 Quantity Mismatches")
    lines.append("")
    lines.append(
        "The table below is the highest absolute quantity gap among shared codes. "
        "The explanation is derived from the visible columns (warehouse, average, "
        "reason, notes); it is not an assumption about an invisible file."
    )
    lines.append("")
    lines.append(top_smoking_table)
    lines.append("")
    lines.append("## 5. Items V2 Included but Manual Missed — Top 30 by Value")
    lines.append("")
    lines.append(v2_only_table)
    lines.append("")
    lines.append("## 6. Items Manual Over-Ordered vs V2 — Top 30 by Value")
    lines.append("")
    lines.append(over_table)
    lines.append("")
    lines.append("## 7. Items Manual Included but V2 Excluded — Top 30 by Value")
    lines.append("")
    lines.append(manual_only_table)
    lines.append("")
    lines.append("## 8. Code Audit Findings (English)")
    lines.append("")
    lines.append("### 8.1 Critical logic defects found")
    lines.append("")
    lines.append("1. **Main `المطلوب` was mapped to `Final_Purchase_Order`.** "
                 "`Final_Purchase_Order` is the warehouse-adjusted purchase layer. "
                 "When `allocate_warehouse_stock` is ON, the sheet therefore showed "
                 "the net purchase, not the branch need. This directly violates the "
                 "requirement that the branch see its full shortfall.")
    lines.append("2. **`Financial_Value` was calculated on `Final_Purchase_Order`.** "
                 "The money column followed the net purchase layer, so it understated "
                 "the branch need whenever warehouse stock covered part of the order.")
    lines.append("3. **The exporter dropped zero-need rows with negative branch stock.** "
                 "`_normalise_numbers` filtered only `المطلوب > 0`, so an item such as the "
                 "user's TRESIBA example with a negative branch balance and no calculated "
                 "order could disappear from the exception list.")
    lines.append("4. **The pipeline filter also required a positive quantity.** "
                 "Even if the exporter were fixed, the final frame had already removed "
                 "negative-balance rows with zero need.")
    lines.append("5. **The `سبب الطلب` label was wrong for normal cosmetics.** "
                 "`_order_reason` checked `Is_Cosmetic` before `Calculated_Order`, so every "
                 "cosmetic row was labelled `توزيع تجميل` even when it was an ordinary ROP "
                 "shortage. This inflated the apparent size of the distribution override.")
    lines.append("6. **Pushing/Cosmetics notes overwrote operational notes.** "
                 "The code assigned `\"Pushing\"` / `\"توزيع تجميل\"` directly to `ملاحظات`, "
                 "erasing negative-stock, substitute, and pack-rounding warnings.")
    lines.append("7. **Stagnant detection used the purchase layer, not the branch need.** "
                 "`Stagnant_Flag` was based on `Final_Purchase_Order == 0`. Once the main "
                 "column changes to `Calculated_Order`, the flag must follow the branch need.")
    lines.append("8. **The legacy `process_data` compatibility wrapper still exposed "
                 "`Final_Purchase_Order` as `المطلوب`.** It is not used by Streamlit, but it "
                 "would reproduce the same bug for any caller that imports it.")
    lines.append("9. **The optional `target` order method bypassed the ROP gate.** "
                 "It set `triggers = True`, so the pipeline could order above the reorder "
                 "point. The true rule is `Effective Stock <= ROP`; the gate must be "
                 "mandatory regardless of the UI mode.")
    lines.append("10. **Two diagnostics still followed the purchase layer.** "
                 "`Item_Status` and the per-SKU debug trace used `Final_Purchase_Order`, "
                 "so the audit labels could disagree with the main `المطلوب` column.")
    lines.append("11. **The legacy `process_data` wrapper used the review period as the "
                 "daily-demand divisor and added safety stock to the target again.** "
                 "It now uses monthly demand / 30 and a clean `Target - Effective Stock`.")
    lines.append("")
    lines.append("### 8.2 What was already correct")
    lines.append("")
    lines.append("- `Daily_Demand = Target_Demand / 30`, `ROP = Daily_Demand × Lead_Time + Safety_Stock`, "
                 "and `Target = Daily_Demand × (Lead_Time + Coverage_Days)` were already present in "
                 "`run_pipeline`.")
    lines.append("- `Warehouse_Covered = min(max(Warehouse_Stock, 0), Calculated_Order)` and "
                 "`Final_Purchase_Order = Calculated_Order - Warehouse_Covered` were correct as a "
                 "separate purchase layer.")
    lines.append("- Substitute rows were already based on the shortfall: "
                 "`Substitute_Request = Calculated_Order - Warehouse_Stock`, and "
                 "`_build_substitute_rows` writes only that shortfall, not the full requirement.")
    lines.append("- The exporter already recomputed `القيمة المالية للطلب` from the exported quantity "
                 "and price instead of copying a stale source money column.")
    lines.append("")
    lines.append("### 8.3 Exact fixes applied")
    lines.append("")
    lines.append("#### `core/supply_chain.py`")
    lines.append("")
    lines.append("- `Financial_Value` now uses `Calculated_Order × Price`; a separate "
                 "`Purchase_Financial_Value` keeps the warehouse-adjusted layer.")
    lines.append("- The exported `المطلوب` now uses `Calculated_Order`, not `Final_Purchase_Order`.")
    lines.append("- The final scope is `(Calculated_Order > 0) | (Branch_Stock < 0)`, "
                 "and the final positive filter preserves negative branch balances.")
    lines.append("- `Stagnant_Flag` now follows `Calculated_Order == 0` and excludes explicit "
                 "distribution targets.")
    lines.append("- `Distribution_Target` / `Force_Cosmetics` / `Force_Pushing` are explicit "
                 "diagnostic columns; distribution no longer changes the branch-need column.")
    lines.append("- Pushing/Cosmetics labels are appended to existing notes instead of replacing them.")
    lines.append("- When warehouse allocation is ON, `ملاحظات` shows `صافي الشراء بعد المخزن`; "
                 "the main `المطلوب` column still shows the full branch need.")
    lines.append("- `_order_reason` now labels a cosmetic row as `توزيع تجميل` only when the "
                 "explicit distribution target is active; ordinary cosmetics are `نقص في الرصيد`.")
    lines.append("- Metrics now expose both the branch-need total (`estimated_cost`, "
                 "`total_order_quantity`) and the purchase layer (`purchase_estimated_cost`, "
                 "`purchase_order_quantity`, `warehouse_covered_quantity`).")
    lines.append("- The fail-fast check compares the final `المطلوب` against the included "
                 "`Calculated_Order` plus substitute allowance, not against a warehouse deduction.")
    lines.append("- The ROP gate is now mandatory; the `target` UI mode no longer bypasses it.")
    lines.append("- `Item_Status` and the debug trace now follow `Calculated_Order`.")
    lines.append("- The legacy `process_data` wrapper now uses monthly demand / 30, the "
                 "`Target - Effective Stock` need, and maps `Calculated_Order` to `المطلوب`.")
    lines.append("")
    lines.append("#### `core/exporter.py`")
    lines.append("")
    lines.append("- `_frame_from_diagnostics` now prefers `Calculated_Order` before "
                 "`Final_Purchase_Order` when rebuilding the 20-column contract.")
    lines.append("- `_normalise_numbers` now keeps `(المطلوب > 0) | (الموجود في الفرع < 0)`; "
                 "negative branch balances are visible exceptions.")
    lines.append("- `القيمة المالية للطلب` remains recomputed from the exported `المطلوب`, "
                 "so the money column is always consistent with the quantity column.")
    lines.append("")
    lines.append("### 8.4 Impact on the numbers")
    lines.append("")
    lines.append("- When warehouse allocation is ON, the corrected sheet will show the full "
                 "branch need; the purchase layer will show the lower net quantity. The current "
                 "pre-fix snapshot can therefore understate `المطلوب` and `القيمة المالية` for "
                 "warehouse-covered rows.")
    lines.append("- Negative-balance items that previously vanished will appear with `المطلوب = 0` "
                 "and a negative `الموجود في الفرع`; this is intentional and is an inventory exception, "
                 "not an order.")
    lines.append("- Ordinary cosmetics will no longer be counted as distribution overrides. "
                 "The pre-fix reason table overstates the cosmetics override.")
    lines.append("- The financial total will change again after re-running the pipeline because "
                 "the main quantity basis changed; the pre-fix total is not the corrected total.")
    lines.append("")
    lines.append("## 9. Business Value (Arabic) — 5 نقاط للإدارة")
    lines.append("")
    lines.append("1. **رؤية النقص الحقيقي للفرع:** العمود `المطلوب` أصبح يعبّر عن احتياج الفرع "
                 "الفعلي من ROP/Target، وليس عن الكمية المتبقية بعد خصم المخزن؛ أي أن الصيدلي يرى "
                 "الحقيقة كاملة قبل قرار الشراء.")
    lines.append("2. **فصل مسؤولية المخزن عن مسؤولية الفرع:** طبقة الشراء (`Final_Purchase_Order`) "
                 "تبقى منفصلة، فيمكن للمخزن أن يغطي جزءاً من الاحتياج دون أن يختفي النقص من تقرير الفرع.")
    lines.append("3. **عدم إخفاء الأرصدة السالبة:** أي صنف برصيد سالب يظهر كاستثناء حتى لو كان "
                 "احتياجه صفراً، وهذا يمنع أخطاء الجرد من التحول إلى نواقص صامتة.")
    lines.append("4. **قرار شراء مبني على احتمال النفاد:** V2 يستخدم متوسط المبيعات وLead Time "
                 "وSafety Stock وCoverage Days، بدلاً من VLOOKUP ثابت؛ النتيجة كمية قابلة للتفسير "
                 "وليست تقديراً يدوياً.")
    lines.append("5. **توفير وشفافية مالية:** حساب القيمة على `Calculated_Order × Price` يجعل "
                 "التكلفة مطابقة للكمية المعروضة، ويفصل تكلفة الاحتياج عن تكلفة الشراء الصافي، "
                 "مما يسهل مراجعة الميزانية قبل الاعتماد.")
    lines.append("")
    lines.append("## 10. Caveats & Next Steps")
    lines.append("")
    lines.append("1. Re-run the Streamlit pipeline with the same ERP inputs to regenerate "
                 "`Auto_Order_Final.xlsx` after the fixes; the current workbook is the old snapshot.")
    lines.append("2. Confirm the master-data scope for the manual-only items that are not stagnant "
                 "and not warehouse-covered; those are the only cases that may indicate a true "
                 "missing-SKU problem.")
    lines.append("3. Review the substitute rows separately: they are intentionally extra lines, "
                 "so row counts and code counts will differ.")
    lines.append("4. Validate the negative-branch exceptions with the branch pharmacist before "
                 "using them as purchase orders.")
    lines.append("5. If management wants the net purchase in the same workbook, add a second "
                 "sheet named `Purchase Layer` sourced from `Final_Purchase_Order`; do not "
                 "overwrite the main `المطلوب` column.")
    lines.append("")
    lines.append("## 11. Files")
    lines.append("")
    lines.append(f"- Report: `{REPORT_FILE}`")
    lines.append("- Modified code: `core/supply_chain.py`, `core/exporter.py`")
    lines.append("- Comparison script: `compare_outputs.py`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    manual, manual_sheets = load_manual()
    v2, v2_sheets = load_v2()
    manual_agg = aggregate_manual(manual)
    v2_agg = aggregate_v2(v2)
    report = build_report(manual, v2, manual_agg, v2_agg, manual_sheets, v2_sheets)
    REPORT_FILE.write_text(report, encoding="utf-8")

    manual_financial = float(manual["manual_financial"].sum())
    v2_financial = float(v2["القيمة المالية للطلب"].sum())
    print(f"Manual rows: {len(manual):,}; unique codes: {manual_agg['code'].nunique():,}")
    print(f"V2 rows: {len(v2):,}; unique codes: {v2_agg['code'].nunique():,}")
    print(f"Manual financial: {manual_financial:,.2f}")
    print(f"V2 financial: {v2_financial:,.2f}")
    print(f"Report written: {REPORT_FILE}")


if __name__ == "__main__":
    main()
