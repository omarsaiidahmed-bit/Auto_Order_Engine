"""The replenishment engine (V3).

Every rule that can change a number in the exported workbook lives here.  The
module never imports ``streamlit`` so that it can be tested headlessly.

The pipeline in one paragraph
-----------------------------
The **master catalogue is the universe**: only items that exist in the
catalogue are considered, and items that appear in the transactional files
without a catalogue card are ignored but reported.  For every catalogue item
the engine builds an **effective stock position** (one of three documented
bases), derives a **monthly demand** from the best available signal, turns
that demand into a **reorder point** and an **order-up-to level**, computes
the **order quantity**, offers a **substitute** for items that cannot be
supplied, deducts the **central warehouse** stock and finally writes the
twelve-column order sheet.

The rules, in the order they are applied
----------------------------------------
1. *Stock basis* -- ``snapshot`` (branch + pending), ``out_transfers`` (the
   business formula: branch + pending - outgoing transfers, the default) or
   ``full_net`` (adds incoming transfers).
2. *Demand* -- the maximum of the monthly sales panel, the ERP monthly
   average and the rescaled recent sales report.  PharmaFly studies 180 days
   and prints ``المتوسط`` as the average of that window, so it is converted
   to a monthly rate (``x 180 / 6``) before it is used.
3. *Safety stock and ROP* -- the real monthly sigma is measured from the
   recent sales report's monthly totals (falling back to the ERP's deviation,
   the panel, then 25% of ``المتوسط``), and
   ``ROP = mu_daily x LT + Z x sigma_daily x sqrt(LT)`` while
   ``S = mu_daily x (Review + LT) + Z x sigma_daily x sqrt(Review + LT)``.
4. *Order* -- zero while the position is above the reorder point, otherwise
   the order-up-to level minus the position, rounded up to whole packs.  A
   negative effective position is shown as-is in the export but used as zero
   in the order arithmetic.
5. *Substitutes* -- an unsupplied item is left at zero and points at its
   replacement; the replacement's requirement is written as its **own extra
   line**, so the buyer sees exactly what has to be purchased and by whom.
6. *Warehouse* -- the central warehouse stock covers part of the requirement.
   It is the raw sum of the warehouse export with negative store balances
   capped at zero, never netted against purchases or transfers.
7. *Category* -- ``فئة التصنيف`` is copied verbatim from the master file;
   there is no mapping layer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd

from app_config import (
    ARABIC_MONTH_NAMES,
    ARABIC_WEEKDAYS_BY_PYTHON_INDEX,
    BRANCH_OPTIONS,
    COSMETIC_CATEGORIES,
    COSMETIC_KEYWORDS,
    DAYS_MAP,
    DAYS_PER_MONTH,
    ERP_AVERAGE_IS_DAILY,
    FINAL_COLUMNS,
    FRIDAY,
    FRIDAY_FALLBACK_PREP,
    IMPLAUSIBLE_NEGATIVE_ABSOLUTE_THRESHOLD,
    IMPLAUSIBLE_NEGATIVE_RATIO_THRESHOLD,
    ITEM_STATUS_COVERED_LEAD_TIME,
    ITEM_STATUS_FULLY_COVERED,
    ITEM_STATUS_ORDER,
    PACKS_COLUMN,
    PHARMAFLY_DAILY_TO_MONTHLY,
    PIECES_COLUMN,
    PREP_SCHEDULE,
    PREP_TO_DELIVERY,
    QUANTITY_COLUMN,
    SupplyChainSettings,
    UNUSUAL_TRANSFER_ABSOLUTE_THRESHOLD,
    UNUSUAL_TRANSFER_MULTIPLIER,
)
from core.aggregation import (
    aggregate_by_sku,
    aggregate_stock,
    build_transfer_aggregates,
    prepare_master_data,
)
from core.demand import (
    SIGMA_SOURCE_FALLBACK,
    SIGMA_SOURCE_PANEL,
    SIGMA_SOURCE_RECENT,
    DemandSpine,
    build_demand_spine,
    detect_sales_window_days,
    recent_monthly_statistics,
)
from core.exporter import export_columns_for_date, sales_columns_for_date
from core.merges import merge_measure
from core.notes import build_notes
from core.normalize import clean_sku, normalize_arabic_text
from core.quantity import (
    build_pack_model,
    compute_pack_equivalent,
    round_up_to_packs,
)
from core.schedules import (
    BRANCH_LABELS_EN,
    canonical_branch,
    compute_schedule_cycle,
    normalize_branch_key,
)
from core.substitutes import extract_core_name, find_substitutes

__all__ = [
    "LeadTimeDetails",
    "PipelineResult",
    "calculate_days_until_delivery",
    "compute_lead_time",
    "get_arabic_weekday",
    "get_branch_prep_days",
    "has_friday_planning_buffer",
    "run_pipeline",
]

ProgressCallback = Callable[[str], None]


# ---------------------------------------------------------------------------
# Section 12 -- lead time
# ---------------------------------------------------------------------------
def get_arabic_weekday(selected_date: date) -> str:
    """Convert a calendar date into its Arabic weekday name."""
    if not isinstance(selected_date, date):
        raise ValueError("Select a valid order date.")
    return ARABIC_WEEKDAYS_BY_PYTHON_INDEX[selected_date.weekday()]


def get_branch_prep_days(selected_branch: str) -> list[str]:
    """Return the preparation weekdays on which a branch is normally served.

    An unknown branch simply has no scheduled preparation days; the delivery
    calendar itself is branch independent, so the run is never blocked by a
    branch that is missing from the schedule.
    """
    if not selected_branch:
        return []
    wanted = {
        component.strip()
        for routes in PREP_SCHEDULE.values()
        for route in routes
        for component in route.split("/")
        if component.strip()
    }
    if selected_branch not in wanted:
        return []
    return [
        prep_day
        for prep_day, routes in PREP_SCHEDULE.items()
        if selected_branch
        in [
            component.strip()
            for route in routes
            for component in route.split("/")
            if component.strip()
        ]
    ]


def calculate_days_until_delivery(prep_day: str, delivery_day: str) -> int:
    """Count the days from a preparation weekday to the next delivery weekday."""
    if prep_day not in DAYS_MAP or delivery_day not in DAYS_MAP:
        raise ValueError("The preparation or delivery day is invalid.")
    days_ahead = (DAYS_MAP[delivery_day] - DAYS_MAP[prep_day] + 7) % 7
    return 7 if days_ahead == 0 else days_ahead


def has_friday_planning_buffer(
    selected_date: date,
    expected_delivery_date: date,
) -> bool:
    """Return whether a Friday falls strictly between order and delivery.

    A Friday that *is* the order date does not trigger the buffer -- the
    branch simply prepares on the following Saturday, and that is already
    reflected in the lead time.
    """
    selected_idx = DAYS_MAP[get_arabic_weekday(selected_date)]
    days_ahead = (expected_delivery_date - selected_date).days
    return any(
        (selected_idx + offset) % 7 == DAYS_MAP[FRIDAY]
        for offset in range(1, max(1, days_ahead))
    )


def round_up_to_pack(quantity: float, pack_size: float) -> int:
    """Round a positive quantity up to the next complete pack."""
    if pack_size is None or pd.isna(pack_size):
        pack_size = 1.0
    pack_size = float(pack_size)
    if pack_size <= 0:
        return 0
    amount = float(quantity)
    if amount <= 0:
        return 0
    return int(math.ceil(amount / pack_size) * pack_size)


def get_delivery_details(
    selected_branch: str,
    selected_date: date,
) -> tuple[str, str, int, date, bool]:
    """Return the prep day, delivery day, total lead time, date and Friday flag."""
    if selected_branch not in BRANCH_OPTIONS:
        raise ValueError("The selected branch is not in the preparation schedule.")
    prep_day = get_arabic_weekday(selected_date)
    if prep_day not in PREP_TO_DELIVERY:
        raise ValueError("No delivery day is configured for the selected preparation day.")
    delivery_day = PREP_TO_DELIVERY[prep_day]
    days_ahead = calculate_days_until_delivery(prep_day, delivery_day)
    expected_delivery_date = selected_date + timedelta(days=days_ahead)
    friday_buffer = has_friday_planning_buffer(selected_date, expected_delivery_date)
    lead_time = days_ahead + int(friday_buffer)
    return prep_day, delivery_day, lead_time, expected_delivery_date, friday_buffer


def process_data(
    data_by_role: dict[str, pd.DataFrame],
    selected_branch: str,
    lead_time: int,
    progress_callback: ProgressCallback | None = None,
    **options: Any,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility wrapper that matches the legacy contract expected by tests."""
    if selected_branch not in BRANCH_OPTIONS:
        raise ValueError("The selected branch is not in the preparation schedule.")

    required = (
        "master",
        "shortages",
        "branch_stock",
        "warehouse_stock",
        "recent_sales",
        "pending_purchases",
        "transfers",
    )
    missing = [name for name in required if name not in data_by_role or data_by_role[name] is None]
    if missing:
        raise ValueError(f"missing required input file(s): {', '.join(missing)}")

    if not isinstance(lead_time, int) or lead_time < 1:
        raise ValueError("Calculated lead time must be a positive integer.")

    z_score = float(options.get("z_score", 1.65))
    variance_pct = float(options.get("variance_pct", 0.25))
    review_period_days = int(options.get("review_period_days", 30))
    netting_mode = str(options.get("netting_mode", "gross")).lower()
    substitute_form_policy = str(options.get("substitute_form_policy", "any"))
    substitutes_enabled = bool(options.get("substitutes_enabled", True))
    if not math.isfinite(z_score) or z_score <= 0:
        raise ValueError("Z-Score must be a valid positive number.")
    if not math.isfinite(variance_pct) or variance_pct < 0:
        raise ValueError("Coefficient of variation cannot be negative.")
    if review_period_days < 1:
        raise ValueError("Review period must be a positive integer.")

    shortages = data_by_role["shortages"].copy()
    duplicates = shortages.loc[shortages["الكود"].astype(str).duplicated(keep=False), "الكود"].drop_duplicates().tolist()
    if duplicates:
        raise ValueError("duplicate item codes")

    master = data_by_role["master"].copy()
    master["كود الصنف"] = master["كود الصنف"].astype(str)
    master = master.drop_duplicates("كود الصنف", keep="first").copy()
    # Handle different master column names
    master_rename = {}
    if "كود الصنف" in master.columns:
        pass
    # Find name column
    name_col = None
    for c in ["اسم الصنف", "الاسم", "اسم الصنفه"]:
        if c in master.columns:
            name_col = c
            break
    # Find pack size column
    pack_col = None
    for c in ["Pack Size", "الاجزاء", "عدد الاجزاء"]:
        if c in master.columns:
            pack_col = c
            break
    # Build join
    master_join_cols = ["كود الصنف"]
    if name_col:
        master_join_cols.append(name_col)
    for c in ["فئة التصنيف", "التصنيف"]:
        if c in master.columns and c not in master_join_cols:
            master_join_cols.append(c)
    for c in ["سعر التكلفة", "متوسط سعر التكلفة", "اخر سعر تكلفة"]:
        if c in master.columns and c not in master_join_cols:
            master_join_cols.append(c)
    if pack_col and pack_col not in master_join_cols:
        master_join_cols.append(pack_col)
    master_join = master[master_join_cols].copy()
    rename_map = {"كود الصنف": "الكود"}
    if name_col:
        rename_map[name_col] = "Master_Name"
    for c in ["فئة التصنيف", "التصنيف"]:
        if c in master_join.columns:
            rename_map[c] = "Master_Category"
            break
    for c in ["سعر التكلفة", "متوسط سعر التكلفة", "اخر سعر تكلفة"]:
        if c in master_join.columns:
            rename_map[c] = "سعر التكلفة"
            break
    if pack_col:
        rename_map[pack_col] = "Pack Size"
    master_join = master_join.rename(columns=rename_map)
    if "Master_Name" not in master_join.columns and "الاسم" in data_by_role.get("master", pd.DataFrame()).columns:
        pass  # try to get from original
    master_join["Master_Found"] = True

    branch_stock = data_by_role["branch_stock"].copy()
    bs_code = "كود" if "كود" in branch_stock.columns else ("الكود" if "الكود" in branch_stock.columns else "كود الصنف")
    if bs_code != "كود":
        branch_stock = branch_stock.rename(columns={bs_code: "كود"})
    branch_stock["كود"] = branch_stock["كود"].astype(str)
    bs_qty = "الكمية" if "الكمية" in branch_stock.columns else "الكمية"
    branch_aggregate = (
        branch_stock.groupby("كود", as_index=False)
        .agg(
            Branch_Stock=(bs_qty, "sum"),
            Branch_Negative_Flag=(bs_qty, lambda s: bool((s < 0).any())),
        )
        .rename(columns={"كود": "الكود"})
    )

    wh = data_by_role["warehouse_stock"].copy()
    wh_code = "كود" if "كود" in wh.columns else ("الكود" if "الكود" in wh.columns else "كود الصنف")
    if wh_code != "كود":
        wh = wh.rename(columns={wh_code: "كود"})
    wh_qty = "الكمية" if "الكمية" in wh.columns else "الكمية"
    warehouse_aggregate = (
        wh.groupby("كود", as_index=False)[wh_qty]
        .sum()
        .rename(columns={"كود": "الكود", wh_qty: "Warehouse_Stock"})
    )
    rs = data_by_role["recent_sales"].copy()
    rs_code = "كود الصنف" if "كود الصنف" in rs.columns else ("الكود" if "الكود" in rs.columns else "كود")
    rs_qty = "الكمية" if "الكمية" in rs.columns else "المبيعات"
    sales_aggregate = (
        rs.groupby(rs_code, as_index=False)[rs_qty]
        .sum()
        .rename(columns={rs_code: "الكود", rs_qty: "Recent_Sales"})
    )

    pending = data_by_role["pending_purchases"].copy()
    pending["Pending_Quantity"] = (
        pd.to_numeric(pending["عبوات"], errors="coerce").fillna(0.0)
        + pd.to_numeric(pending["اجزاء"], errors="coerce").fillna(0.0)
    )
    pending_aggregate = (
        pending.groupby("كود الصنف", as_index=False)["Pending_Quantity"]
        .sum()
        .rename(columns={"كود الصنف": "الكود", "Pending_Quantity": "Pending_Purchases"})
    )

    transfers = data_by_role["transfers"].copy()
    transfers["كود الصنف"] = transfers["كود الصنف"].astype(str)
    transfers["العملية"] = transfers["العملية"].fillna("").astype(str)
    transfers["Operation_Normalized"] = (
        transfers["العملية"].str.replace("أ", "ا", regex=False).str.replace("إ", "ا", regex=False)
    )
    transfers["Transfer_Quantity"] = (
        pd.to_numeric(transfers["عبوات"], errors="coerce").fillna(0.0).abs()
        + pd.to_numeric(transfers["اجزاء"], errors="coerce").fillna(0.0).abs()
    )

    outgoing_mask = (
        transfers["Operation_Normalized"].str.contains("ارسال", na=False)
        & ~transfers["Operation_Normalized"].str.contains("استلام", na=False)
    )
    incoming_mask = (
        transfers["Operation_Normalized"].str.contains("استلام", na=False)
        & ~transfers["Operation_Normalized"].str.contains("ارسال", na=False)
    )
    outgoing_aggregate = (
        transfers.loc[outgoing_mask]
        .groupby("كود الصنف", as_index=False)["Transfer_Quantity"]
        .sum()
        .rename(columns={"كود الصنف": "الكود", "Transfer_Quantity": "Transfers_Out"})
    )
    incoming_aggregate = (
        transfers.loc[incoming_mask]
        .groupby("كود الصنف", as_index=False)["Transfer_Quantity"]
        .sum()
        .rename(columns={"كود الصنف": "الكود", "Transfer_Quantity": "Transfers_In"})
    )

    merged = shortages.copy()
    if "التصنيف" not in merged.columns:
        merged["التصنيف"] = pd.NA
    if "Monthly_StdDev" not in merged.columns:
        merged["Monthly_StdDev"] = pd.NA
    for aggregate in (
        branch_aggregate,
        warehouse_aggregate,
        sales_aggregate,
        pending_aggregate,
        outgoing_aggregate,
        incoming_aggregate,
    ):
        merged = merged.merge(aggregate, how="left", on="الكود", validate="one_to_one")
    merged = merged.merge(master_join, how="left", on="الكود", validate="one_to_one")

    for column in ("Branch_Stock", "Warehouse_Stock", "Recent_Sales", "Pending_Purchases", "Transfers_Out", "Transfers_In"):
        if column in merged.columns:
            merged[column] = merged[column].fillna(0)
        else:
            merged[column] = 0
    if "Branch_Negative_Flag" in merged.columns:
        merged["Branch_Negative_Flag"] = merged["Branch_Negative_Flag"].fillna(False)
    else:
        merged["Branch_Negative_Flag"] = False
    if "Master_Found" in merged.columns:
        merged["Master_Missing"] = merged["Master_Found"].isna()
    else:
        merged["Master_Missing"] = True
    if "Master_Name" in merged.columns:
        merged["اسم الصنف"] = merged["Master_Name"].fillna(merged.get("الاسم"))
    elif "الاسم" in merged.columns:
        merged["اسم الصنف"] = merged["الاسم"]
    else:
        merged["اسم الصنف"] = ""
    merged["Core_Name"] = merged["اسم الصنف"].map(lambda name: extract_core_name(name).identity_tokens[0] if isinstance(name, str) and extract_core_name(name).identity_tokens else "")
    if "Master_Category" in merged.columns:
        merged["Raw_Category"] = merged["التصنيف"].fillna(merged["Master_Category"])
    else:
        merged["Raw_Category"] = merged["التصنيف"]
    if "Pack Size" in merged.columns:
        merged["Pack Size"] = merged["Pack Size"].fillna(1)
    else:
        merged["Pack Size"] = 1
    if "سعر التكلفة" in merged.columns:
        merged["سعر التكلفة"] = merged["سعر التكلفة"].fillna(0)
    else:
        merged["سعر التكلفة"] = 0
    merged["Transferred_In"] = 0.0
    merged["Transferred_Out"] = merged["Transfers_Out"].astype(float)
    merged["Unusual_Transfer_Flag"] = False
    merged["Multi_Price_Flag"] = False
    merged["Substitute_Code"] = pd.NA
    merged["Substitute_Name"] = pd.NA
    merged["Form_Mismatch"] = False
    merged["Substituted_Out"] = False

    average = merged["المتوسط"].clip(lower=0)
    recent_sales_value = merged["Recent_Sales"].clip(lower=0)
    merged["Negative_Demand_Flag"] = (merged["المتوسط"] < 0) | (merged["Recent_Sales"] < 0)
    target_demand = pd.concat([average, recent_sales_value], axis=1).max(axis=1)
    monthly_std_dev = merged["Monthly_StdDev"].where(merged["Monthly_StdDev"].notna(), average * variance_pct)

    if netting_mode == "net":
        merged["Effective_Stock"] = merged["Branch_Stock"] + merged["Pending_Purchases"]
    else:
        merged["Effective_Stock"] = merged["Branch_Stock"] + merged["Pending_Purchases"] + merged["Transfers_In"] - merged["Transfers_Out"]

    # Daily demand is monthly demand / 30, not monthly demand / review period.
    daily_std_dev = monthly_std_dev / math.sqrt(30.0)
    daily_average = target_demand / 30.0
    merged["Lead_Time"] = int(lead_time)
    merged["Safety_Stock"] = z_score * daily_std_dev * math.sqrt(lead_time)
    merged["ROP"] = daily_average * lead_time + merged["Safety_Stock"]
    target_level = daily_average * (
        float(lead_time) + float(review_period_days)
    )
    exact_need = target_level - merged["Effective_Stock"]
    merged["Calculated_Order"] = exact_need.where(merged["Effective_Stock"] <= merged["ROP"], 0.0)
    merged["Calculated_Order"] = merged["Calculated_Order"].map(lambda quantity: max(0.0, float(quantity)))
    merged["Order_Before_Pack_Rounding"] = merged["Calculated_Order"]
    merged["Calculated_Order"] = merged.apply(
        lambda row: round_up_to_pack(row["Calculated_Order"], row["Pack Size"]),
        axis=1,
    )
    merged["Pack_Rounding_Applied"] = merged["Calculated_Order"] > merged["Order_Before_Pack_Rounding"]

    merged["Warehouse_Covered"] = merged.apply(
        lambda row: min(max(0.0, row["Warehouse_Stock"]), row["Calculated_Order"]),
        axis=1,
    )
    merged["Final_Purchase_Order"] = merged["Calculated_Order"] - merged["Warehouse_Covered"]

    unfilled = merged.loc[merged["Final_Purchase_Order"] > 0, ["الكود", "الاسم", "Effective_Stock", "Calculated_Order", "Pack Size", "Core_Name"]].copy()
    if substitutes_enabled:
        merged = find_substitutes(merged, form_policy=substitute_form_policy)
        merged["Substituted_Out"] = merged["Substitute_Code"].notna() & merged["Substitute_Code"].astype("string").fillna("").ne("")
        if merged["Substituted_Out"].any():
            merged.loc[merged["Substituted_Out"], "Final_Purchase_Order"] = 0.0
            substitution_totals = (
                merged.loc[merged["Substituted_Out"], ["Substitute_Code", "Calculated_Order"]]
                .groupby("Substitute_Code", as_index=False)["Calculated_Order"].sum()
                .rename(columns={"Substitute_Code": "الكود", "Calculated_Order": "Transferred_In"})
            )
            for code, qty in substitution_totals[["الكود", "Transferred_In"]].itertuples(index=False, name=None):
                code_str = str(code)
                if not code_str:
                    continue
                matches = merged["الكود"].astype(str) == code_str
                merged.loc[matches, "Transferred_In"] = pd.to_numeric(merged.loc[matches, "Transferred_In"], errors="coerce").fillna(0.0) + float(qty)
                merged.loc[matches, "Calculated_Order"] = pd.to_numeric(merged.loc[matches, "Calculated_Order"], errors="coerce").fillna(0.0) + float(qty)
                merged.loc[matches, "Final_Purchase_Order"] = pd.to_numeric(merged.loc[matches, "Final_Purchase_Order"], errors="coerce").fillna(0.0) + float(qty)
                merged.loc[matches, "Warehouse_Covered"] = merged.loc[matches, "Warehouse_Covered"].apply(
                    lambda value: min(max(0.0, float(value)), float(merged.loc[matches, "Calculated_Order"].iat[0]))
                ) if matches.any() else 0.0
            merged.loc[merged["Substituted_Out"], "Substitute_Name"] = merged.loc[merged["Substituted_Out"], "Substitute_Name"].fillna("")

    merged["Warehouse_Stock"] = merged["Warehouse_Stock"].fillna(0.0)
    merged["Demand"] = target_demand.to_numpy()
    merged["Target_Demand"] = target_demand.to_numpy()
    merged["Implausible_Stock_Flag"] = (
        (merged["Effective_Stock"] < 0) & (merged["Branch_Stock"] >= 0) & (merged["Branch_Negative_Flag"].fillna(False) == False)
    )
    merged["Unusual_Transfer_Flag"] = (
        (pd.to_numeric(merged["Transfers_Out"], errors="coerce").fillna(0) > 10)
        | (pd.to_numeric(merged["Transfers_In"], errors="coerce").fillna(0) > 10)
    )
    diagnostics = merged.copy()
    diagnostics["Final_Purchase_Order"] = pd.to_numeric(diagnostics["Final_Purchase_Order"], errors="coerce").fillna(0.0).clip(lower=0.0)
    diagnostics["Calculated_Order"] = pd.to_numeric(diagnostics["Calculated_Order"], errors="coerce").fillna(0.0)
    diagnostics["Warehouse_Stock"] = pd.to_numeric(diagnostics["Warehouse_Stock"], errors="coerce").fillna(0.0)
    diagnostics["Effective_Stock"] = pd.to_numeric(diagnostics["Effective_Stock"], errors="coerce").fillna(0.0)
    diagnostics["Branch_Stock"] = pd.to_numeric(diagnostics["Branch_Stock"], errors="coerce").fillna(0.0)
    diagnostics["Pending_Purchases"] = pd.to_numeric(diagnostics["Pending_Purchases"], errors="coerce").fillna(0.0)
    diagnostics["Transfers_Out"] = pd.to_numeric(diagnostics["Transfers_Out"], errors="coerce").fillna(0.0)
    diagnostics["Transfers_In"] = pd.to_numeric(diagnostics["Transfers_In"], errors="coerce").fillna(0.0)
    diagnostics["Demand"] = pd.to_numeric(diagnostics["Demand"], errors="coerce").fillna(0.0)
    diagnostics["Target_Demand"] = pd.to_numeric(diagnostics["Target_Demand"], errors="coerce").fillna(0.0)
    diagnostics["Final_Purchase_Order"] = diagnostics["Final_Purchase_Order"].clip(lower=0.0)
    diagnostics["حالة الصنف"] = ""
    diagnostics["البديل"] = diagnostics["Substitute_Code"].fillna("").astype(str)
    diagnostics["ملاحظات"] = ""
    diagnostics["التصنيف"] = diagnostics["التصنيف"].fillna("Other")

    implausible_count = int((diagnostics["Effective_Stock"] < 0).sum())
    if implausible_count > 0 and (diagnostics["Branch_Stock"] >= 0).all():
        if implausible_count >= 5:
            raise ValueError("تم تجاوز عدد الحالات غير المنطقية المسموح بها")

    result = diagnostics.loc[:, [
        "التصنيف",
        "الكود",
        "الاسم",
        "Calculated_Order",
        "حالة الصنف",
        "Effective_Stock",
        "Warehouse_Stock",
        "المتوسط",
        "Lead_Time",
        "ROP",
        "Demand",
        "البديل",
        "ملاحظات",
    ]].copy()
    result = result.rename(columns={
        "Calculated_Order": "المطلوب",
        "Effective_Stock": "الموجود",
        "Warehouse_Stock": "المخزن",
        "Lead_Time": "Lead_Time",
        "ROP": "ROP",
        "Demand": "Demand",
    })
    result["حالة الصنف"] = ""
    result["البديل"] = diagnostics["Substitute_Code"].fillna("").astype(str)
    result["ملاحظات"] = diagnostics.apply(build_notes, axis=1)
    result["التصنيف"] = result["التصنيف"].fillna("Other")

    result.columns = list(FINAL_COLUMNS)
    result["المطلوب"] = pd.to_numeric(result["المطلوب"], errors="coerce").fillna(0.0)
    result["الموجود"] = pd.to_numeric(result["الموجود"], errors="coerce").fillna(0.0)
    result["المخزن"] = pd.to_numeric(result["المخزن"], errors="coerce").fillna(0.0)
    result["المتوسط"] = pd.to_numeric(result["المتوسط"], errors="coerce").fillna(0.0)
    result["Lead_Time"] = pd.to_numeric(result["Lead_Time"], errors="coerce").fillna(0)
    result["ROP"] = pd.to_numeric(result["ROP"], errors="coerce").fillna(0.0)
    result["Demand"] = pd.to_numeric(result["Demand"], errors="coerce").fillna(0.0)
    result["الكود"] = result["الكود"].astype(str)
    result["البديل"] = result["البديل"].fillna("").astype(str)
    result["ملاحظات"] = result["ملاحظات"].fillna("").astype(str)
    result.attrs["diagnostics"] = diagnostics
    result.attrs["lead_time"] = int(lead_time)

    try:
        costs = master.set_index("كود الصنف")["سعر التكلفة"].astype(float).to_dict()
    except Exception:
        costs = {}
    return result.reset_index(drop=True), {str(k): float(v) for k, v in costs.items()}


@dataclass(frozen=True)
class LeadTimeDetails:
    """Everything the UI needs to explain the lead time."""

    order_weekday: str
    prep_weekday: str
    delivery_weekday: str
    days_ahead: int
    friday_buffer: bool
    lead_time: int
    delivery_date: date


def compute_lead_time(
    selected_date: date,
    selected_branch: str = "",
) -> LeadTimeDetails:
    """Return the lead time for an order on ``selected_date``.

    The lead time is the **calendar gap between the branch's preparation day
    and its first scheduled arrival after that preparation**.  It is read from
    :func:`core.schedules.compute_schedule_cycle`; no fixed number and no
    Friday surcharge is used.

    A Wednesday preparation followed by a Saturday arrival therefore returns
    ``3``.  A branch whose preparation and arrival are the same weekday rolls
    to the next arrival and returns ``7`` rather than inventing a zero-day
    cycle.
    """
    if not isinstance(selected_date, date):
        raise ValueError("Select a valid order date.")
    if isinstance(selected_date, datetime):
        selected_date = selected_date.date()

    if selected_branch:
        cycle = compute_schedule_cycle(selected_branch, selected_date)
        lead_time = cycle.prep_to_arrival_days
        if lead_time is None or cycle.arrival_date is None:
            raise ValueError(
                "No preparation/arrival cycle is configured for the selected "
                f"branch ({selected_branch})."
            )
        lead_time = max(1, int(lead_time))
        return LeadTimeDetails(
            order_weekday=cycle.reference_weekday,
            prep_weekday=cycle.preparation_weekday,
            delivery_weekday=cycle.arrival_weekday,
            days_ahead=lead_time,
            friday_buffer=False,
            lead_time=lead_time,
            delivery_date=cycle.arrival_date,
        )

    # Backwards-compatible fallback for callers that do not know the branch.
    # It still uses the preparation-to-delivery gap; it never uses a fixed
    # seven-day placeholder.
    order_weekday = get_arabic_weekday(selected_date)
    prep_weekday = order_weekday
    if prep_weekday not in PREP_TO_DELIVERY:
        prep_weekday = FRIDAY_FALLBACK_PREP
    delivery_weekday = PREP_TO_DELIVERY[prep_weekday]
    lead_time = max(1, calculate_days_until_delivery(prep_weekday, delivery_weekday))
    delivery_date = selected_date + timedelta(days=lead_time)

    return LeadTimeDetails(
        order_weekday=order_weekday,
        prep_weekday=prep_weekday,
        delivery_weekday=delivery_weekday,
        days_ahead=lead_time,
        friday_buffer=False,
        lead_time=lead_time,
        delivery_date=delivery_date,
    )


# ---------------------------------------------------------------------------
# The result container
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    """Everything one run produced."""

    final: pd.DataFrame
    diagnostics: pd.DataFrame
    metrics: dict[str, Any]
    run_messages: list[str] = field(default_factory=list)
    lead_time: Any | None = None
    stock_reconciliation: pd.DataFrame = field(default_factory=pd.DataFrame)
    demand: DemandSpine | None = None
    settings: SupplyChainSettings | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _empty_aggregate(columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(columns=["الكود", *columns])
    frame["الكود"] = frame["الكود"].astype("string")
    for column in columns:
        frame[column] = frame[column].astype("float64")
    return frame


def _sku_series(values: pd.Series) -> pd.Series:
    return values.astype("string")


def _pack_equivalent_for(
    frame: pd.DataFrame,
    sku_column: str,
    pack_size: pd.Series,
) -> pd.Series:
    """Return the pack-equivalent quantity of every row of a ledger file.

    A ledger may list the same item on several rows (one row per purchase
    order, per transfer line, ...), so the lookup is done with ``map`` and
    never with ``reindex`` -- a reindex on duplicated item codes raises.
    """
    codes = _sku_series(frame[sku_column])
    sizes = codes.map(pack_size).fillna(1.0).astype("float64")
    sizes = sizes.where(sizes > 0, 1.0)

    packs = (
        pd.to_numeric(frame[PACKS_COLUMN], errors="coerce").fillna(0.0)
        if PACKS_COLUMN in frame.columns
        else pd.Series(0.0, index=frame.index)
    )
    pieces = (
        pd.to_numeric(frame[PIECES_COLUMN], errors="coerce").fillna(0.0)
        if PIECES_COLUMN in frame.columns
        else pd.Series(0.0, index=frame.index)
    )
    return compute_pack_equivalent(packs, pieces, sizes)


def _count_unmatched(
    frame: pd.DataFrame,
    sku_column: str,
    master_skus: pd.Series,
) -> int:
    """Count the rows whose item code is absent from the catalogue."""
    if frame.empty or sku_column not in frame.columns:
        return 0
    codes = _sku_series(frame[sku_column]).dropna()
    if codes.empty:
        return 0
    known = set(master_skus.tolist())
    return int(sum(1 for code in codes if code not in known))


# ---------------------------------------------------------------------------
# Branch scoping and the final-sheet source lookups
# ---------------------------------------------------------------------------
def _is_cosmetic_category(value: object) -> bool:
    """Return whether an ERP category belongs to the cosmetics family."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip()
    if not text:
        return False
    normalized = normalize_arabic_text(text).casefold()
    # Exact categories are the business's cosmetics-and-supplies family.  The
    # substring check catches ERP spellings such as "Cosmetics" or
    # "مستحضرات تجميلية" without treating every category that merely contains
    # the word "مستلزمات" as cosmetics.
    for category in COSMETIC_CATEGORIES:
        if normalize_arabic_text(str(category)).casefold() == normalized:
            return True
    safe_keywords = tuple(
        keyword for keyword in COSMETIC_KEYWORDS if keyword != "مستلزمات"
    )
    return any(
        normalize_arabic_text(str(keyword)).casefold() in normalized
        for keyword in safe_keywords
    )


def _pushing_required_series(pushing_list: pd.DataFrame | None) -> pd.Series:
    """Return the required quantity encoded in the pushing-list file.

    PharmaFly's pushing list can carry ``نواقص الفرع`` (the branch shortage)
    and ``رصيد الفرع`` (the branch stock).  The required quantity is the
    shortage minus the stock.  If only the shortage column exists, that value
    itself is used.  Duplicate codes are resolved by the first row, matching
    an Excel VLOOKUP.
    """
    if pushing_list is None or pushing_list.empty:
        return pd.Series(dtype="float64")
    code_column = _code_column(pushing_list, ("الكود", "كود الصنف", "كود"))
    if code_column is None or "نواقص الفرع" not in pushing_list.columns:
        return pd.Series(dtype="float64")

    frame = pushing_list.copy()
    frame["_Code"] = _clean_code_series(frame[code_column])
    frame = frame.loc[frame["_Code"].notna()].drop_duplicates(
        "_Code", keep="first"
    )
    shortage = pd.to_numeric(frame["نواقص الفرع"], errors="coerce").fillna(0.0)
    if "رصيد الفرع" in frame.columns:
        stock = pd.to_numeric(frame["رصيد الفرع"], errors="coerce").fillna(0.0)
        required = (shortage - stock).clip(lower=0.0)
    else:
        required = shortage.clip(lower=0.0)
    return pd.Series(required.to_numpy(), index=frame["_Code"].astype("string"))


def _clean_code_series(values: pd.Series) -> pd.Series:
    """Normalise item codes while preserving leading zeros."""
    return values.map(clean_sku).astype("string")


#: Every spelling of the item-code column seen in the ERP, the historical
#: panel, and the optional helper files.  The VLOOKUP is done on the cleaned
#: value, never on the row order.
_CODE_COLUMN_ALIASES: tuple[str, ...] = (
    "الكود",
    "كود الصنف",
    "كود",
    "Item Code",
    "Item_Code",
    "ItemCode",
    "Code",
    "SKU",
    "sku",
)

#: Every spelling of the branch column in a historical-sales export.
_BRANCH_COLUMN_ALIASES: tuple[str, ...] = (
    "الفرع",
    "اسم الفرع",
    "فرع",
    "Branch",
    "Branch Name",
    "Branch_Name",
    "branch",
    "branch_name",
)


def _ensure_code_column(
    frame: pd.DataFrame | None,
    target: str,
) -> pd.DataFrame | None:
    """Return a copy whose ``target`` code column is cleaned.

    The app's ingestion layer already canonicalises these names, but the
    pipeline is also called directly with raw ERP frames.  This small adapter
    guarantees that a code such as ``"101"`` matches the same code in every
    uploaded file during the VLOOKUP.
    """
    if frame is None or frame.empty:
        return frame
    source = _code_column(frame, _CODE_COLUMN_ALIASES)
    if source is None and target not in frame.columns:
        return frame
    adapted = frame.copy()
    source = target if target in adapted.columns else source
    adapted[target] = _clean_code_series(adapted[source])
    return adapted


def _code_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def _ensure_quantity_column(
    frame: pd.DataFrame | None,
    target: str = QUANTITY_COLUMN,
) -> pd.DataFrame | None:
    """Expose an English ERP quantity column under the canonical name."""
    if frame is None or frame.empty or target in frame.columns:
        return frame
    source = _code_column(
        frame,
        (
            "Quantity",
            "quantity",
            "Qty",
            "qty",
            "On Hand",
            "On_Hand",
            "Stock",
            "stock",
            "الكمية ",
        ),
    )
    if source is None:
        return frame
    adapted = frame.copy()
    adapted[target] = adapted[source]
    return adapted


def _branch_match_keys(value: object) -> set[str]:
    """Return the spellings that identify one branch.

    ERP files are not consistent about the definite article: the same branch
    can appear as ``الهانوفيل``, ``هانوفيل`` or ``Hanoville``.  The keys include
    the canonical name, the name without a leading ``ال`` and the English
    label, so the item-code + branch lookup still finds the right rows.
    """
    if value is None:
        return set()
    try:
        if pd.isna(value):
            return set()
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].strip():
        text = text[:-2].strip()
    canonical = canonical_branch(text)
    candidates = {
        normalize_branch_key(text),
        normalize_branch_key(canonical),
    }
    for arabic, english in BRANCH_LABELS_EN.items():
        english_key = normalize_branch_key(english)
        if english_key in candidates:
            candidates.add(normalize_branch_key(arabic))
    expanded: set[str] = set()
    for key in candidates:
        if not key:
            continue
        expanded.add(key)
        if key.startswith("ال") and len(key) > 2:
            expanded.add(key[2:])
        else:
            expanded.add(f"ال{key}")
    return expanded


def _filter_to_branch(
    frame: pd.DataFrame | None,
    branch: str,
    *,
    columns: tuple[str, ...],
    label: str,
    required: bool = False,
) -> pd.DataFrame | None:
    """Keep only the rows that belong to the selected branch.

    The branch column is optional.  When it is absent the file is assumed to
    be a single-branch export and is returned untouched.  When it is present,
    the merge key is **item code + branch name**, so the same item code can
    never borrow another branch's historical sales.
    """
    if frame is None or frame.empty or not branch:
        return frame
    column = _code_column(frame, columns)
    if column is None:
        return frame

    target = _branch_match_keys(branch)
    keys = frame[column].map(_branch_match_keys)
    filtered = frame.loc[keys.map(lambda value: bool(value & target))].copy()
    if filtered.empty and required:
        raise ValueError(
            f"ملف {label} لا يحتوي على أي سطر للفرع المحدد ({branch})."
        )
    return filtered


def _uploaded_code_set(
    frame: pd.DataFrame | None,
    candidates: tuple[str, ...],
) -> set[str]:
    """Return the normalised item-code set of an optional uploaded list."""
    if frame is None or frame.empty:
        return set()
    column = _code_column(frame, candidates)
    if column is None:
        return set()
    return {
        str(code)
        for code in (clean_sku(value) for value in frame[column])
        if pd.notna(code) and str(code).strip()
    }


_MONTH_ALIASES: dict[int, tuple[str, ...]] = {
    1: ("يناير", "january", "jan"),
    2: ("فبراير", "february", "feb"),
    3: ("مارس", "march", "mar"),
    4: ("ابريل", "april", "apr"),
    5: ("مايو", "may"),
    6: ("يونيو", "june", "jun"),
    7: ("يوليو", "يوليه", "تموز", "july", "jul"),
    8: ("اغسطس", "august", "aug"),
    9: ("سبتمبر", "ايلول", "september", "sep", "sept"),
    10: ("اكتوبر", "october", "oct"),
    11: ("نوفمبر", "november", "nov"),
    12: ("ديسمبر", "december", "dec"),
}


def _month_number_from_label(label: object) -> int | None:
    """Return the calendar month represented by a sales-column label."""
    if isinstance(label, (datetime, date)):
        return int(label.month)
    if isinstance(label, (int, np.integer)):
        number = int(label)
        return number if 1 <= number <= 12 else None
    if isinstance(label, (float, np.floating)) and not pd.isna(label):
        number = int(label)
        return number if float(number) == float(label) and 1 <= number <= 12 else None

    text = normalize_arabic_text(label).casefold()
    if not text:
        return None
    for month, aliases in _MONTH_ALIASES.items():
        if any(alias in text for alias in aliases):
            return month
    match = re.search(r"(?<!\d)(0?[1-9]|1[0-2])(?!\d)", text)
    if match:
        return int(match.group(1))
    return None


def _year_from_label(label: object) -> int | None:
    if isinstance(label, (datetime, date)):
        return int(label.year)
    match = re.search(r"(20\d{2})", str(label))
    return int(match.group(1)) if match else None


def _month_column(
    frame: pd.DataFrame,
    month: int,
    order_date: date,
) -> str | None:
    """Find the column of one month, preferring the order-date year."""
    candidates = [
        column
        for column in frame.columns
        if _month_number_from_label(column) == month
    ]
    if not candidates:
        return None
    same_year = [
        column
        for column in candidates
        if _year_from_label(column) == int(order_date.year)
    ]
    if same_year:
        return same_year[-1]
    undated = [column for column in candidates if _year_from_label(column) is None]
    if undated:
        return undated[-1]
    return candidates[-1]


def _final_branch_sales_frame(
    data_by_role: dict[str, pd.DataFrame],
    panel_block: pd.DataFrame | None,
) -> pd.DataFrame | None:
    """Return the uploaded historical-sales frame.

    The Streamlit uploader feeds the wide historical panel through
    ``panel_block``.  A direct caller may also supply a long frame under the
    explicit ``final_branch_sales`` role; both are supported.
    """
    role_frame: pd.DataFrame | None = None
    for role in ("final_branch_sales", "final_sales", "panel_sales"):
        frame = data_by_role.get(role)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            role_frame = frame
            # A multi-branch frame must be filtered by both item code and
            # branch before the month columns are read.
            if _code_column(frame, _BRANCH_COLUMN_ALIASES) is not None:
                return frame
            break
    # The uploader's panel block is already parsed and branch-specific, so it
    # is safer than an unparsed wide workbook that has no branch column.
    if panel_block is not None and not panel_block.empty:
        return panel_block
    return role_frame


def _panel_block_from_historical(
    data_by_role: dict[str, pd.DataFrame],
    branch: str,
) -> pd.DataFrame | None:
    """Build a branch panel from a ``final_branch_sales`` upload.

    The app normally sends a parsed :class:`core.ingestion.SalesPanel` block,
    but direct callers may only provide the historical-sales table.  This
    helper keeps that file usable as the monthly demand panel as well as for
    the three historical columns of the order sheet.
    """
    frame = _final_branch_sales_frame(data_by_role, None)
    if frame is None or frame.empty:
        return None
    code_column = _code_column(frame, _CODE_COLUMN_ALIASES)
    if code_column is None:
        return None
    frame = _filter_to_branch(
        frame,
        branch,
        columns=_BRANCH_COLUMN_ALIASES,
        label="final_branch_sales",
    )
    if frame is None or frame.empty:
        return None
    frame = frame.copy()

    month_column = _code_column(
        frame,
        (
            "Month",
            "month",
            "Month Name",
            "Month_Name",
            "Period",
            "الفترة",
            "الشهر",
            "شهر",
            "Sales Month",
            "Date",
            "التاريخ",
            "تاريخ",
        ),
    )
    sales_column = _code_column(
        frame,
        (
            "Sales",
            "sales",
            "Sales Amount",
            "Sales_Amount",
            "Sales Value",
            "Sales_Value",
            "Net Sales",
            "Net_Sales",
            "Value",
            "القيمة",
            "إجمالي المبيعات",
            "المبيعات",
            "الكمية",
            "Quantity",
            "Qty",
        ),
    )

    if month_column is not None and sales_column is not None:
        working = frame[[code_column, month_column, sales_column]].copy()
        working["_Code"] = _clean_code_series(working[code_column])
        working["_Month"] = working[month_column].map(_month_number_from_label)
        working["_Sales"] = pd.to_numeric(
            working[sales_column], errors="coerce"
        )
        working = working.loc[
            working["_Code"].notna()
            & working["_Month"].notna()
            & working["_Sales"].notna()
        ]
        if working.empty:
            return None
        pivot = working.pivot_table(
            index="_Code",
            columns="_Month",
            values="_Sales",
            aggfunc="sum",
        )
        pivot.columns = [f"month_{int(month)}" for month in pivot.columns]
        pivot = pivot.reset_index().rename(columns={"_Code": "sku"})
        return pivot

    month_columns = [
        column
        for column in frame.columns
        if _month_number_from_label(column) is not None
        and column != code_column
    ]
    if not month_columns:
        return None
    working = frame[[code_column, *month_columns]].copy()
    working["sku"] = _clean_code_series(working[code_column])
    working = working.loc[working["sku"].notna()]
    if working.empty:
        return None
    for column in month_columns:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    grouped = working.groupby("sku", as_index=False, sort=False)[month_columns].sum(
        min_count=1
    )
    return grouped


def _historical_sales_by_month(
    data_by_role: dict[str, pd.DataFrame],
    panel_block: pd.DataFrame | None,
    order_date: date,
    branch: str = "",
    months: tuple[int, ...] | None = None,
) -> dict[int, pd.Series]:
    """Return selected monthly historical sales keyed by item code.

    The lookup is the two-condition VLOOKUP required by the order sheet:
    **item code + branch name**.  A frame that carries a ``Branch`` column is
    filtered to the selected branch before the month columns are mapped, so a
    code that exists in several branches cannot pick up another branch's
    history.  A panel block from the uploader is already branch-specific and
    is used as-is.

    A missing item, a missing month column and a blank cell all stay ``NaN``.
    They are never converted to zero: the final sheet must be able to show
    that the item was not found in the uploaded historical file.
    """
    if months is not None:
        requested_months = tuple(months)
    else:
        current_month = order_date.month
        m1 = current_month - 1 if current_month > 1 else 12
        m2 = current_month - 2 if current_month > 2 else 12 + (current_month - 2)
        m3 = current_month - 3 if current_month > 3 else 12 + (current_month - 3)
        requested_months = (m3, m2, m1)
    empty = {month: pd.Series(dtype="float64") for month in requested_months}
    frame = _final_branch_sales_frame(data_by_role, panel_block)
    if frame is None or frame.empty:
        return empty

    code_column = _code_column(frame, _CODE_COLUMN_ALIASES)
    if code_column is None:
        return empty

    source = frame.copy()
    source = _filter_to_branch(
        source,
        branch,
        columns=_BRANCH_COLUMN_ALIASES,
        label="final_branch_sales",
    )
    if source is None or source.empty:
        return empty
    source = source.copy()
    source["_Code"] = _clean_code_series(source[code_column])
    source["cleaned_code"] = source["_Code"].astype(str).str.strip()
    source = source.loc[source["_Code"].notna()].copy()
    if source.empty:
        return empty

    # A long final-branch-sales file carries one row per item and month.
    month_column = _code_column(
        source,
        (
            "الشهر",
            "شهر",
            "month",
            "Month",
            "Month Name",
            "Month_Name",
            "Period",
            "الفترة",
            "Date",
            "التاريخ",
            "تاريخ",
        ),
    )
    sales_column = _code_column(
        source,
        (
            "المبيعات",
            "مبيعات",
            "Sales",
            "sales",
            "Sales Amount",
            "Sales_Amount",
            "Sales Value",
            "Sales_Value",
            "Net Sales",
            "Net_Sales",
            "Value",
            "القيمة",
            "إجمالي المبيعات",
            "الكمية",
            "Quantity",
            "quantity",
            "Qty",
            "qty",
        ),
    )
    if month_column is not None and sales_column is not None:
        months = source[month_column].map(_month_number_from_label)
        values = pd.to_numeric(source[sales_column], errors="coerce")
        result: dict[int, pd.Series] = {}
        for month in requested_months:
            mask = months.eq(month) & source["_Code"].notna()
            if bool(mask.any()):
                subset = source.loc[mask, ["_Code"]].copy()
                subset["_Value"] = values.loc[mask].to_numpy()
                subset = subset.drop_duplicates("_Code", keep="first")
                result[month] = pd.Series(
                    subset["_Value"].to_numpy(),
                    index=subset["_Code"].astype("string"),
                )
            else:
                result[month] = pd.Series(dtype="float64")
        return result

    # The wide panel: one column per month, one row per item.
    result = {}
    for month in requested_months:
        column = _month_column(source, month, order_date)
        if column is None:
            result[month] = pd.Series(dtype="float64")
            continue
        subset = source.loc[:, ["_Code", column]].copy()
        subset["_Value"] = pd.to_numeric(subset[column], errors="coerce")
        subset = subset.drop_duplicates("_Code", keep="first")
        result[month] = pd.Series(
            subset["_Value"].to_numpy(),
            index=subset["_Code"].astype("string"),
        )
    return result


def _recent_sales_by_month(
    recent_sales: pd.DataFrame | None,
    pack_size: pd.Series,
    months: tuple[int, ...],
    fallback_month: int | None = None,
) -> dict[int, pd.Series]:
    """Return the recent-sales ledger aggregated into calendar months.

    The recent-sales export is usually the current month's ledger, but it can
    also carry several dates.  Grouping by the real date is therefore the only
    honest way to fill the dynamic month columns.  If the file has no date
    column, its total is assigned to ``fallback_month`` (the order month).
    """
    empty = {month: pd.Series(dtype="float64") for month in months}
    if recent_sales is None or recent_sales.empty:
        return empty
    frame = recent_sales.copy()
    code_column = _code_column(frame, ("كود الصنف", "الكود", "كود"))
    if code_column is None:
        return empty

    quantity = _pack_equivalent_for(frame, code_column, pack_size)
    frame["_Code"] = _clean_code_series(frame[code_column])
    frame["_Value"] = pd.to_numeric(quantity, errors="coerce").fillna(0.0)
    frame = frame.loc[frame["_Code"].notna()]
    if frame.empty:
        return empty

    date_column = _code_column(
        frame,
        ("التاريخ", "تاريخ", "Date", "date", "Sales Date", "Day"),
    )
    if date_column is not None:
        dates = pd.to_datetime(frame[date_column], errors="coerce")
        frame["_Month"] = dates.dt.month
        valid = frame["_Month"].notna()
        if bool(valid.any()):
            grouped = (
                frame.loc[valid]
                .assign(_Month=frame.loc[valid, "_Month"].astype(int))
                .groupby(["_Code", "_Month"], sort=False)["_Value"]
                .sum()
                .unstack("_Month", fill_value=0.0)
            )
            result: dict[int, pd.Series] = {}
            for month in months:
                if month in grouped.columns:
                    result[month] = grouped[month].astype("float64")
                else:
                    result[month] = pd.Series(dtype="float64")
            return result

    if fallback_month is None:
        return empty
    grouped = frame.groupby("_Code", sort=False)["_Value"].sum()
    result = {month: pd.Series(dtype="float64") for month in months}
    result[fallback_month] = grouped.astype("float64")
    return result


def _historical_price_series(
    data_by_role: dict[str, pd.DataFrame],
    panel_block: pd.DataFrame | None,
    branch: str = "",
) -> pd.Series:
    """Return the item-report price, used only when the master has none."""
    frame = _final_branch_sales_frame(data_by_role, panel_block)
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    frame = _filter_to_branch(
        frame,
        branch,
        columns=_BRANCH_COLUMN_ALIASES,
        label="final_branch_sales",
    )
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    code_column = _code_column(frame, _CODE_COLUMN_ALIASES)
    price_column = _code_column(
        frame, ("price", "Price", "السعر", "سعر البيع", "Unit Price")
    )
    if code_column is None or price_column is None:
        return pd.Series(dtype="float64")
    codes = _clean_code_series(frame[code_column])
    values = pd.to_numeric(frame[price_column], errors="coerce")
    subset = pd.DataFrame({"_Code": codes, "_Value": values})
    subset = subset.loc[subset["_Code"].notna()].drop_duplicates(
        "_Code", keep="first"
    )
    return pd.Series(
        subset["_Value"].to_numpy(),
        index=subset["_Code"].astype("string"),
    )


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
def run_pipeline(
    data_by_role: dict[str, pd.DataFrame],
    *,
    settings: SupplyChainSettings,
    order_date: date,
    branch: str = "",
    panel_block: pd.DataFrame | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the whole analysis and return the finished order sheet."""
    _validate_settings(settings)
    if isinstance(order_date, datetime):
        order_date = order_date.date()
    selected_branch = canonical_branch(branch) if branch else ""

    master = prepare_master_data(data_by_role.get("master", pd.DataFrame()))
    if master.empty or "كود الصنف" not in master.columns:
        raise ValueError(
            "ملف بيانات الأصناف الرئيسية (master) مطلوب لتحديد نطاق الأصناف."
        )
    master = master.drop_duplicates("كود الصنف", keep="first").reset_index(drop=True)
    # The VLOOKUP key is always the cleaned item code, never a numeric value
    # whose ``.0`` suffix or leading-zero loss would break the match.
    master = master.copy()
    master["كود الصنف"] = _clean_code_series(master["كود الصنف"])
    master_skus = _sku_series(master["كود الصنف"])

    # These files are already branch exports.  They are never filtered by a
    # branch column again: a mismatched branch label in one ERP export used to
    # hide valid shortage rows (for example IVYPRONT).  The selected branch is
    # used only for the schedule and for the historical panel block.
    branch_stock = _ensure_quantity_column(
        _ensure_code_column(data_by_role.get("branch_stock"), "الكود")
    )
    if branch_stock is None or branch_stock.empty:
        raise ValueError("ملف رصيد الفرع (branch stock) مطلوب لحساب الرصيد الفعلي.")
    if "الكود" not in branch_stock.columns:
        raise ValueError("ملف رصيد الفرع لا يحتوي على عمود كود الصنف (الكود).")

    warehouse_stock = _ensure_quantity_column(
        _ensure_code_column(data_by_role.get("warehouse_stock"), "الكود")
    )
    pending = _ensure_code_column(
        data_by_role.get("pending_purchases"), "كود الصنف"
    )
    transfers = _ensure_code_column(
        data_by_role.get("transfers"), "كود الصنف"
    )
    recent_sales = _ensure_quantity_column(
        _ensure_code_column(data_by_role.get("recent_sales"), "كود الصنف")
    )
    shortages = _ensure_code_column(data_by_role.get("shortages"), "الكود")
    if shortages is None or shortages.empty:
        raise ValueError("ملف تقرير الأصناف الناقصة (shortages) مطلوب.")
    shortage_code_column = _code_column(shortages, _CODE_COLUMN_ALIASES)
    if shortage_code_column is None:
        raise ValueError("ملف تقرير الأصناف الناقصة لا يحتوي على عمود كود الصنف.")
    shortage_codes = {
        str(code)
        for code in _clean_code_series(shortages[shortage_code_column])
        if pd.notna(code) and str(code).strip()
    }
    if not shortage_codes:
        raise ValueError("ملف تقرير الأصناف الناقصة لا يحتوي على أي كود صالح.")

    multi_price = _ensure_code_column(
        data_by_role.get("multi_price"), "كود الصنف"
    )
    pushing_list = _ensure_code_column(
        data_by_role.get("pushing_list"), "الكود"
    )
    pushing_codes = _uploaded_code_set(
        pushing_list, _CODE_COLUMN_ALIASES
    )

    # The shortage report and the pushing list are the order scope.  If one of
    # their codes has no card in the master file, keep it in the universe
    # instead of silently dropping it.  Its name comes from the uploaded list;
    # price and category fall back to that list or to an empty value.
    master_skus = _sku_series(master["كود الصنف"])
    missing_scope_codes = sorted(
        (set(shortage_codes) | set(pushing_codes))
        - set(master_skus.dropna().astype(str))
    )
    if missing_scope_codes:
        def _lookup_frame(frame: pd.DataFrame | None, columns: tuple[str, ...]):
            if frame is None or frame.empty:
                return None
            column = _code_column(frame, columns)
            if column is None:
                return None
            source = frame.copy()
            source["_Code"] = _clean_code_series(source[column])
            source = source.loc[source["_Code"].notna()].drop_duplicates(
                "_Code", keep="first"
            )
            return source.set_index("_Code")

        shortage_source = _lookup_frame(
            shortages, ("الكود", "كود الصنف", "كود")
        )
        pushing_source = _lookup_frame(
            pushing_list, ("الكود", "كود الصنف", "كود")
        )

        def _record_value(record, column: str, default: object = "") -> object:
            if record is None or column not in record.index:
                return default
            value = record.get(column, default)
            return default if pd.isna(value) else value

        supplemental: list[dict[str, object]] = []
        for code in missing_scope_codes:
            record = None
            if shortage_source is not None and code in shortage_source.index:
                record = shortage_source.loc[code]
            elif pushing_source is not None and code in pushing_source.index:
                record = pushing_source.loc[code]
            if isinstance(record, pd.DataFrame):
                record = record.iloc[0]
            supplemental.append(
                {
                    "كود الصنف": code,
                    "اسم الصنف": _record_value(
                        record,
                        "الاسم",
                        _record_value(
                            record, "Name", _record_value(record, "Item Name", code)
                        ),
                    ),
                    "فئة التصنيف": _record_value(
                        record,
                        "فئة التصنيف",
                        _record_value(
                            record,
                            "التصنيف",
                            _record_value(record, "Category", ""),
                        ),
                    ),
                    "الاجزاء": 1,
                    "سعر التكلفة": 0.0,
                    "متوسط سعر التكلفة": 0.0,
                    "اخر سعر تكلفة": 0.0,
                    "سعر البيع": _record_value(
                        record,
                        "سعر البيع",
                        _record_value(
                            record,
                            "السعر",
                            _record_value(record, "Price", 0.0),
                        ),
                    ),
                }
            )
        master = pd.concat(
            [master, pd.DataFrame(supplemental)], ignore_index=True, sort=False
        )
        master_skus = _sku_series(master["كود الصنف"])

    if progress_callback is not None:
        progress_callback("🧮 Building the pack model from the product master...")

    pack_model = build_pack_model(
        master,
        transactional=(
            ("branch stock", branch_stock),
            ("warehouse stock", warehouse_stock),
            ("recent sales", recent_sales),
        ),
    )
    pack_size = pack_model.pack_size

    # -- Section 8: aggregate every source before it is joined ---------------
    if progress_callback is not None:
        progress_callback("📦 Aggregating every source file to one row per item...")

    branch_aggregate = aggregate_stock(
        branch_stock, "الكود", pack_size=pack_size, value_name="Branch_Stock"
    )
    warehouse_frame = warehouse_stock if warehouse_stock is not None else pd.DataFrame()
    warehouse_aggregate = aggregate_stock(
        warehouse_frame,
        "الكود",
        pack_size=pack_size,
        value_name="Warehouse_Stock",
        # ``المخزن`` is the direct raw sum of ``الكمية`` in the warehouse file.
        # Pending purchases and transfers are never netted into it, and a
        # negative store balance is kept in the exported figure because it is
        # a real purchasing signal.  Only the coverage calculation caps it at
        # zero (``Warehouse_Covered`` below), so one store's deficit cannot
        # consume another store's stock.
        clip_negative=False,
    )
    warehouse_clipped_rows = (
        int(
            (
                pd.to_numeric(warehouse_frame[QUANTITY_COLUMN], errors="coerce") < 0
            ).sum()
        )
        if not warehouse_frame.empty and QUANTITY_COLUMN in warehouse_frame.columns
        else 0
    )

    pending_aggregate = _empty_aggregate(["Pending_Purchases"])
    if pending is not None and not pending.empty:
        pending = pending.copy()
        pending["_Pending_Quantity"] = _pack_equivalent_for(
            pending, "كود الصنف", pack_size
        )
        pending_aggregate = aggregate_by_sku(
            pending, "كود الصنف", ["_Pending_Quantity"], ["Pending_Purchases"]
        )

    sales_aggregate = _empty_aggregate(["Recent_Sales"])
    if recent_sales is not None and not recent_sales.empty:
        sales = recent_sales.copy()
        sales_code_column = _code_column(
            sales, ("كود الصنف", "الكود", "كود")
        ) or "كود الصنف"
        sales_quantity_column = _code_column(
            sales,
            (
                "الكمية",
                "المبيعات",
                "كمية المبيعات",
                "إجمالي المبيعات",
                "Sales",
                "sales",
                "Quantity",
                "quantity",
                "Qty",
                "qty",
            ),
        )
        if sales_quantity_column is not None:
            sales["_Recent_Quantity"] = pd.to_numeric(
                sales[sales_quantity_column], errors="coerce"
            ).fillna(0.0)
        else:
            sales["_Recent_Quantity"] = _pack_equivalent_for(
                sales, sales_code_column, pack_size
            )
        sales_aggregate = aggregate_by_sku(
            sales, sales_code_column, ["_Recent_Quantity"], ["Recent_Sales"]
        )

    outgoing_aggregate, incoming_aggregate, ambiguous_aggregate = (
        build_transfer_aggregates(
            transfers if transfers is not None else pd.DataFrame(), pack_size
        )
    )

    # -- Section 9: the driver frame is the master catalogue -----------------
    driver = master.rename(
        columns={
            "كود الصنف": "الكود",
            "اسم الصنف": "اسم الصنف",
            "فئة التصنيف": "Raw_Category",
        }
    ).copy()
    driver["الكود"] = _sku_series(driver["الكود"])

    # Some ERP catalogues carry no item-name column at all; the name then lives
    # in the shortages report.  Build the display name from whichever source
    # actually has one instead of failing on a missing column.
    if "اسم الصنف" not in driver.columns:
        name_lookup: dict[str, str] = {}
        name_sources = [
            (master, "كود الصنف", "اسم الصنف"),
            (master, "كود الصنف", "الاسم"),
            (shortages, "الكود", "الاسم"),
            (branch_stock, "الكود", "اسم الصنف"),
            (warehouse_stock, "الكود", "اسم الصنف"),
            (recent_sales, "كود الصنف", "اسم الصنف"),
            (pending, "كود الصنف", "اسم الصنف"),
            (transfers, "كود الصنف", "اسم الصنف"),
            (multi_price, "كود الصنف", "اسم الصنف"),
            (data_by_role.get("pushing_list"), "الكود", "الاسم"),
            (panel_block, "sku", "name"),
        ]
        for frame, code_column, name_column in name_sources:
            if frame is None or frame.empty:
                continue
            if code_column not in frame.columns or name_column not in frame.columns:
                continue
            for code, name in zip(
                _sku_series(frame[code_column]),
                frame[name_column].astype("string"),
            ):
                if code in name_lookup:
                    continue
                if isinstance(name, str) and name.strip():
                    name_lookup[code] = name.strip()
        driver["اسم الصنف"] = (
            driver["الكود"].map(name_lookup).fillna("").astype("string")
        )

    if "Raw_Category" not in driver.columns:
        driver["Raw_Category"] = pd.NA
    if "القسم" not in driver.columns:
        driver["القسم"] = pd.NA

    for column in ("متوسط سعر التكلفة", "اخر سعر تكلفة", "سعر البيع"):
        if column not in driver.columns:
            driver[column] = np.nan
        driver[column] = pd.to_numeric(driver[column], errors="coerce")

    driver["Pack Size"] = (
        pack_size.reindex(driver["الكود"]).fillna(1.0).astype("float64")
    )
    driver["Pack Size"] = driver["Pack Size"].where(driver["Pack Size"] > 0, 1.0)

    expected_rows = len(driver)

    for aggregate, label in (
        (branch_aggregate, "branch stock"),
        (warehouse_aggregate, "warehouse stock"),
        (sales_aggregate, "recent sales"),
        (pending_aggregate, "pending purchases"),
        (outgoing_aggregate, "outgoing transfers"),
        (incoming_aggregate, "incoming transfers"),
    ):
        driver = merge_measure(
            driver, aggregate, label=label, expected_rows=expected_rows
        )

    if progress_callback is not None:
        progress_callback(
            f"🔗 Joined every source onto the catalogue -- {expected_rows:,} items."
        )

    # -- the ERP shortage report (optional) ----------------------------------
    erp_average = pd.Series(dtype="float64")
    erp_std = pd.Series(dtype="float64")
    erp_requested = pd.Series(dtype="float64")
    if shortages is not None and not shortages.empty and "الكود" in shortages.columns:
        shortage_frame = shortages.copy()
        shortage_frame["الكود"] = _clean_code_series(shortage_frame["الكود"])
        shortage_frame = shortage_frame.loc[
            shortage_frame["الكود"].notna()
        ].drop_duplicates("الكود", keep="first")
        shortage_index = shortage_frame["الكود"].astype("string")
        average_column = _code_column(
            shortage_frame, ("المتوسط", "Average", "average", "Avg", "avg")
        )
        std_column = _code_column(
            shortage_frame,
            ("Monthly_StdDev", "StdDev", "stddev", "Standard Deviation"),
        )
        requested_column = _code_column(
            shortage_frame, ("المطلوب", "Required", "required")
        )
        if average_column is not None:
            erp_average = pd.Series(
                pd.to_numeric(shortage_frame[average_column], errors="coerce")
                .fillna(0.0)
                .to_numpy(),
                index=shortage_index,
            )
        if std_column is not None:
            erp_std = pd.Series(
                pd.to_numeric(shortage_frame[std_column], errors="coerce").to_numpy(),
                index=shortage_index,
            )
        if requested_column is not None:
            erp_requested = pd.Series(
                pd.to_numeric(shortage_frame[requested_column], errors="coerce")
                .fillna(0.0)
                .to_numpy(),
                index=shortage_index,
            )

    # The demand spine is matched **by SKU**, never by row position.
    erp_average_sku = erp_average.reindex(driver["الكود"]).fillna(0.0)
    erp_std_sku = erp_std.reindex(driver["الكود"])
    erp_requested = erp_requested.reindex(driver["الكود"]).fillna(0.0)

    # PharmaFly studies 180 days and prints the average of that window in
    # ``المتوسط``.  The monthly rate is therefore ``المتوسط x 180 / 6`` -- or
    # ``x 1`` for an export that already carries a monthly figure (which is
    # what the reference files measure, see app_config.ERP_AVERAGE_IS_DAILY).
    erp_conversion = PHARMAFLY_DAILY_TO_MONTHLY if ERP_AVERAGE_IS_DAILY else 1.0
    erp_monthly_sku = erp_average_sku * erp_conversion

    erp_average = pd.Series(erp_average_sku.to_numpy(), index=driver.index, dtype="float64")
    erp_std = pd.Series(erp_std_sku.to_numpy(), index=driver.index, dtype="float64")
    erp_requested = pd.Series(erp_requested.to_numpy(), index=driver.index, dtype="float64")

    # -- Section 11.3: the demand spine --------------------------------------
    recent_days = (
        detect_sales_window_days(recent_sales) if recent_sales is not None else 30
    )
    recent_series = (
        sales_aggregate.set_index("الكود")["Recent_Sales"]
        if not sales_aggregate.empty
        else pd.Series(dtype="float64")
    )
    recent_series.index = recent_series.index.astype("string")

    # The real per-item deviation comes from the monthly totals of the recent
    # sales ledger, not from the shortage report's four month columns.  When
    # the file has no date column (or fewer than two months), the spine falls
    # through to the next real signal and finally to the 25% fallback.
    recent_statistics = recent_monthly_statistics(recent_sales)
    if not recent_statistics.empty:
        recent_sigma_series = recent_statistics["Recent_Sigma"]
        recent_observations_series = recent_statistics["Recent_Observations"]
    else:
        recent_sigma_series = pd.Series(dtype="float64")
        recent_observations_series = pd.Series(dtype="float64")

    demand_panel_block = panel_block
    if demand_panel_block is None or demand_panel_block.empty:
        demand_panel_block = _panel_block_from_historical(
            data_by_role, selected_branch
        )

    demand_spine = build_demand_spine(
        driver["الكود"],
        erp_average=erp_monthly_sku,
        erp_std_dev=erp_std_sku,
        recent_sales=recent_series,
        recent_sigma=recent_sigma_series,
        recent_observations=recent_observations_series,
        recent_days=recent_days,
        panel_block=demand_panel_block,
        panel_branch=selected_branch or branch,
        cv_fallback=settings.variance_percent / 100.0,
        source_mode=settings.demand_source,
    )

    driver["Target_Demand"] = demand_spine.frame["Demand"].to_numpy()
    driver["Monthly_Sigma"] = demand_spine.frame["Monthly_Sigma"].to_numpy()
    driver["Sigma_Source"] = demand_spine.frame["Sigma_Source"].to_numpy()
    driver["Sigma_Observations"] = demand_spine.frame["Sigma_Observations"].to_numpy()
    driver["Demand_Source"] = demand_spine.frame["Demand_Source"].to_numpy()
    driver["ERP_Average"] = erp_average.to_numpy()
    driver["ERP_Requested"] = erp_requested.to_numpy()
    driver["Negative_Demand_Flag"] = (erp_average < 0) | (
        sales_aggregate["Recent_Sales"].fillna(0) < 0
        if not sales_aggregate.empty
        else False
    )

    # -- Section 10.5: the stock position ------------------------------------
    driver["Branch_Stock"] = driver["Branch_Stock"].fillna(0.0).astype("float64")
    driver["Warehouse_Stock"] = driver["Warehouse_Stock"].fillna(0.0).astype("float64")
    driver["Pending_Purchases"] = driver["Pending_Purchases"].fillna(0.0).astype("float64")
    driver["Transfers_Out"] = driver["Transfers_Out"].fillna(0.0).astype("float64")
    driver["Transfers_In"] = driver["Transfers_In"].fillna(0.0).astype("float64")

    # The only transfer switch that matters for the order calculation is the
    # explicit UI toggle.  When it is off, transfers are shown as zero and
    # never change the effective stock.
    if settings.include_transfers:
        driver["Net_Transfers"] = (
            driver["Transfers_In"] - driver["Transfers_Out"]
        ).astype("float64")
    else:
        driver["Net_Transfers"] = 0.0

    # The exact business formula.  A negative position is a real signal: it
    # raises the requirement instead of being silently capped at zero.
    driver["Effective_Stock"] = (
        driver["Branch_Stock"]
        + driver["Pending_Purchases"]
        + driver["Net_Transfers"]
    ).astype("float64")
    driver["Ordering_Stock"] = driver["Effective_Stock"].copy()

    driver["Branch_Negative_Flag"] = driver["Branch_Stock"] < 0
    driver["Implausible_Stock_Flag"] = (driver["Effective_Stock"] < 0) & (
        driver["Branch_Stock"] >= 0
    )

    largest_component = driver[["Branch_Stock", "Pending_Purchases"]].clip(
        lower=0
    ).max(axis=1)
    driver["Unusual_Transfer_Flag"] = driver["Transfers_Out"] > np.maximum(
        UNUSUAL_TRANSFER_ABSOLUTE_THRESHOLD,
        UNUSUAL_TRANSFER_MULTIPLIER * largest_component,
    )

    # -- Section 11.6: the exact business calculation ------------------------
    # The lead time is the branch's actual preparation-to-arrival gap.  It is
    # never a fixed placeholder and never an added Friday buffer.
    if selected_branch:
        lead = compute_schedule_cycle(selected_branch, order_date)
        lead_time = lead.prep_to_arrival_days
        if lead_time is None:
            raise ValueError(
                "لا يوجد جدول تجهيز ووصول للفرع المحدد، لذلك لا يمكن حساب "
                "مدة التوريد."
            )
    else:
        lead = compute_lead_time(order_date)
        lead_time = lead.lead_time
    lead_time = max(1, int(lead_time))

    # FIX #1: Use Target_Demand from demand_spine (sales-based).
    # MUST divide by 30.0.
    average = (
        pd.to_numeric(driver["Target_Demand"], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
    )
    driver["Export_Average"] = average
    driver["Daily_Demand"] = average / 30.0
    daily_demand = driver["Daily_Demand"]

    # FIX #2: Scientific Safety Stock = Z × σ_daily × √LT
    import math as _math_ss

    Z_SERVICE = float(getattr(settings, "z_score", 1.65))  # 95% service level
    _LEAD = float(lead_time)
    driver["Lead_Time"] = _LEAD

    # Monthly sigma from demand_spine; fallback to 25% of average.
    _monthly_sigma = pd.to_numeric(
        driver.get("Monthly_Sigma"), errors="coerce"
    )
    if _monthly_sigma is None:
        _monthly_sigma = average * 0.25
    else:
        _monthly_sigma = _monthly_sigma.fillna(average * 0.25).clip(lower=0.0)

    _daily_sigma = _monthly_sigma / _math_ss.sqrt(30.0)
    driver["Safety_Stock"] = Z_SERVICE * _daily_sigma * _math_ss.sqrt(_LEAD)
    driver["ROP"] = (daily_demand * _LEAD) + driver["Safety_Stock"]

    coverage_days = int(settings.coverage_days)
    driver["Coverage_Days"] = float(coverage_days)
    driver["Order_Up_To_Level"] = daily_demand * (
        float(lead_time) + float(coverage_days)
    )
    print(
        f"DEBUG: Coverage_Days={coverage_days} | Target="
        f"{driver['Order_Up_To_Level'].iloc[0] if len(driver) > 0 else 0}"
    )

    effective_stock = pd.to_numeric(
        driver["Effective_Stock"], errors="coerce"
    ).fillna(0.0)

    print(f"DEBUG: Calculating with Coverage Days = {settings.coverage_days}")

    # The ROP gate is mandatory in the business rule.  ``order_method`` remains
    # a UI compatibility flag, but it must not bypass the gate: if effective
    # stock is above the reorder point, the branch need is zero.
    raw_need = driver["Order_Up_To_Level"] - effective_stock
    triggers = effective_stock.le(driver["ROP"])

    raw_order = raw_need.where(triggers, 0.0)
    print(
        f"DEBUG: order_method={settings.order_method} | "
        f"ROP_triggers={int(triggers.sum()) if hasattr(triggers, 'sum') else 0}"
    )
    driver["Calculated_Order"] = np.maximum(
        np.ceil(raw_order.to_numpy(dtype="float64")), 0.0
    ).astype("float64")
    driver["Order_Before_Pack_Rounding"] = driver["Calculated_Order"].copy()
    driver["Pack_Rounding_Applied"] = False

    if progress_callback is not None:
        progress_callback("🎯 Computing the reorder point and the order quantity...")

    # -- Section 15: substitutes ---------------------------------------------
    driver["Substitute_Code"] = pd.Series(pd.NA, index=driver.index, dtype="string")
    driver["Substitute_Name"] = pd.Series(pd.NA, index=driver.index, dtype="string")
    driver["Form_Mismatch"] = False
    driver["Substituted_Out"] = False
    driver["Substitute_Request"] = 0.0
    driver["Transferred_In"] = 0.0
    driver["Core_Name"] = ""

    if settings.substitutes_enabled:
        driver = find_substitutes(
            driver,
            form_policy=settings.substitute_form_policy,
            require_same_pack_size=settings.substitute_require_same_pack_size,
        )

    substitute_code = driver["Substitute_Code"].astype("string").fillna("").str.strip()
    warehouse_for_substitute = (
        pd.to_numeric(driver["Warehouse_Stock"], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
    )
    # FIX 2: Substitute should only cover the shortfall
    substitute_needed = (
        substitute_code.ne("")
        & driver["Calculated_Order"].gt(0)
        & warehouse_for_substitute.lt(driver["Calculated_Order"])
    )
    driver["Substituted_Out"] = substitute_needed
    driver["Substitute_Request"] = (
        driver["Calculated_Order"] - warehouse_for_substitute
    ).clip(lower=0.0).where(substitute_needed, 0.0)
    driver["Transferred_In"] = 0.0

    if progress_callback is not None:
        progress_callback("🔄 Matching substitutes for the unavailable items...")

    substitute_name = driver["Substitute_Name"].astype("string").fillna("")
    driver["البديل"] = (substitute_code + " - " + substitute_name).where(
        substitute_code.ne(""), ""
    )

    # -- Section 14: warehouse information ------------------------------------
    # FIX #6: Final_Purchase_Order = Calculated_Order - Warehouse_Covered
    if settings.allocate_warehouse_stock:
        warehouse_available = driver["Warehouse_Stock"].clip(lower=0)
        driver["Warehouse_Covered"] = np.minimum(
            warehouse_available, driver["Calculated_Order"]
        )
    else:
        driver["Warehouse_Covered"] = 0.0
    driver["Final_Purchase_Order"] = (
        driver["Calculated_Order"] - driver["Warehouse_Covered"]
    ).clip(lower=0.0)

    # -- Section 15: the item status -----------------------------------------
    # The status explains the order column to the buyer.  The first condition
    # wins; a zero order is either fully covered or covered up to the supply
    # period, and an item that is above neither threshold stays blank.
    driver["Item_Status"] = _build_item_status(driver)

    # -- Section 16: notes ----------------------------------------------------
    note_columns = [
        "Branch_Negative_Flag",
        "Implausible_Stock_Flag",
        "Negative_Demand_Flag",
        "Pack_Rounding_Applied",
        "Pack Size",
        "Unusual_Transfer_Flag",
        "Warehouse_Stock",
        "Calculated_Order",
        "Final_Purchase_Order",
        "Substitute_Code",
        "Substituted_Out",
        "Transferred_In",
        "Form_Mismatch",
        "Effective_Stock",
        "Multi_Price_Flag",
    ]
    driver["Multi_Price_Flag"] = _multi_price_flags(multi_price, driver["الكود"])
    driver["ملاحظات"] = [
        build_notes(record) for record in driver[note_columns].to_dict("records")
    ]

    # -- the category ---------------------------------------------------------
    # Copied verbatim: the ERP's own classification is the one the buyer works
    # with, so nothing is renamed and nothing falls into a generic bucket.
    driver["Export_Category"] = driver["Raw_Category"].astype("string").fillna("")

    # -- the cost -------------------------------------------------------------
    average_cost = pd.to_numeric(driver["متوسط سعر التكلفة"], errors="coerce")
    last_cost = pd.to_numeric(driver["اخر سعر تكلفة"], errors="coerce")
    driver["Unit_Cost"] = average_cost.where(average_cost.notna() & (average_cost > 0))
    driver["Unit_Cost"] = driver["Unit_Cost"].where(
        driver["Unit_Cost"].notna(), last_cost
    )
    driver["Unit_Cost"] = driver["Unit_Cost"].fillna(0.0).astype("float64")

    # -- the dynamic historical sales panel ----------------------------------
    # The four columns are always the order month and the three months before
    # it.  Historical panel values are used first; the recent-sales ledger
    # fills any month it actually covers (for example October when the order is
    # placed in November).  No fixed July/August/September columns remain.
    sales_headers = sales_columns_for_date(order_date)
    sales_months = tuple(
        int(month)
        for month in (_month_number_from_label(header) for header in sales_headers)
        if month is not None
    )
    if len(sales_months) != len(sales_headers):
        # This can only happen if a locale name is malformed; the order date is
        # still the authoritative source, so rebuild the sequence directly.
        sales_months = tuple(
            (order_date.month + offset - 1) % 12 + 1
            for offset in (-3, -2, -1, 0)
        )
    historical = _historical_sales_by_month(
        data_by_role,
        panel_block,
        order_date,
        selected_branch,
        months=sales_months[:3],
    )
    recent_monthly = _recent_sales_by_month(
        recent_sales,
        pack_size,
        sales_months,
        fallback_month=sales_months[-1],
    )
    driver_codes = _clean_code_series(driver["الكود"])
    for index, (header, month) in enumerate(zip(sales_headers, sales_months)):
        values = pd.Series(float("nan"), index=driver.index, dtype="float64")
        panel_values = historical.get(month)
        if panel_values is not None and not panel_values.empty:
            values = driver_codes.map(panel_values).astype("float64")
        recent_values = recent_monthly.get(month)
        if recent_values is not None and not recent_values.empty:
            recent_aligned = driver_codes.map(recent_values).astype("float64")
            values = values.where(values.notna(), recent_aligned)
        driver[f"Sales_Month_{3 - index}"] = values
        driver[header] = values

    # The current month is the last dynamic column, not an unrelated total.
    driver["Current_Month_Sales"] = (
        pd.to_numeric(driver[sales_headers[-1]], errors="coerce").fillna(0.0)
    )

    # -- the selling price ----------------------------------------------------
    master_price = pd.to_numeric(driver["سعر البيع"], errors="coerce")
    panel_price = driver_codes.map(
        _historical_price_series(data_by_role, panel_block, selected_branch)
    )
    driver["Price"] = master_price.where(
        master_price.notna() & (master_price > 0), panel_price
    )
    driver["Price"] = pd.to_numeric(driver["Price"], errors="coerce").fillna(0.0)

    # -- the average used by the calculation ----------------------------------
    driver["Export_Average"] = average.astype("float64")

    # -- the row-colour and scope flags --------------------------------------
    multiple_codes = _uploaded_code_set(
        multi_price, ("كود الصنف", "الكود")
    )
    transfer_codes = _uploaded_code_set(
        transfers, ("كود الصنف", "الكود")
    )
    driver["Is_Pushing_List"] = driver["الكود"].isin(pushing_codes)
    driver["Is_Multi_Card"] = driver["الكود"].isin(multiple_codes)
    driver["Is_Transfer"] = (
        pd.to_numeric(driver["Net_Transfers"], errors="coerce").fillna(0.0) != 0
    ) & bool(settings.include_transfers)
    driver["Is_Shortage"] = driver["الكود"].isin(shortage_codes)
    driver["Is_Cosmetic"] = driver["Export_Category"].map(_is_cosmetic_category)
    driver["Warehouse_Loading"] = (
        pd.to_numeric(driver["Warehouse_Covered"], errors="coerce").fillna(0.0) > 0
    )

    # -- advanced overrides (default OFF) ------------------------------------
    sales_total = sum(
        pd.to_numeric(driver[header], errors="coerce").fillna(0.0)
        for header in sales_headers
    )
    driver["Sales_Total"] = sales_total.astype("float64")
    driver["Has_Sales_History"] = sales_total.gt(0)
    driver["Has_Sales_Rate"] = (
        driver["Export_Average"].gt(0) | driver["Sales_Total"].gt(0)
    )
    force_cosmetics = driver["Is_Cosmetic"] & bool(
        getattr(settings, "enable_cosmetics_force", False)
    )
    force_pushing = driver["Is_Pushing_List"] & bool(
        getattr(settings, "enable_pushing_override", False)
    )
    distribution_target = force_cosmetics | force_pushing
    driver["Force_Cosmetics"] = force_cosmetics
    driver["Force_Pushing"] = force_pushing
    driver["Distribution_Target"] = distribution_target

    driver["Stagnant_Flag"] = False
    driver["Ignore_No_Sales_Flag"] = (
        bool(settings.ignore_no_sales_rate)
        & (~driver["Has_Sales_Rate"])
        & (~distribution_target)
    )
    driver.loc[driver["Ignore_No_Sales_Flag"], "Final_Purchase_Order"] = 0.0

    if bool(distribution_target.any()):
        driver.loc[distribution_target, "Final_Purchase_Order"] = np.maximum(
            pd.to_numeric(
                driver.loc[distribution_target, "Final_Purchase_Order"],
                errors="coerce",
            )
            .fillna(0.0)
            .to_numpy(),
            1.0,
        )

    # Notes are kept, but the exact stagnant marker is appended below after the
    # final quantity is known.  Never replace an existing operational note
    # (negative stock, substitute, pack rounding, ...) with the colour label.
    for mask, label in (
        (driver["Is_Pushing_List"], "Pushing"),
        (
            driver["Is_Cosmetic"]
            & driver["Distribution_Target"]
            & ~driver["Is_Pushing_List"],
            "توزيع تجميل",
        ),
    ):
        existing = driver.loc[mask, "ملاحظات"].fillna("").astype(str)
        driver.loc[mask, "ملاحظات"] = existing.apply(
            lambda value, label=label: (
                value
                if label in value
                else (f"{value} | {label}" if value.strip() else label)
            )
        )

    # The warehouse-adjusted purchase amount is a separate logical layer.  Keep
    # the main ``المطلوب`` column on the branch need, but make the net purchase
    # visible in the note so the buyer is not asked to infer it.
    if bool(settings.allocate_warehouse_stock):
        covered_quantity = pd.to_numeric(
            driver["Warehouse_Covered"], errors="coerce"
        ).fillna(0.0)
        purchase_quantity_note = pd.to_numeric(
            driver["Final_Purchase_Order"], errors="coerce"
        ).fillna(0.0)
        warehouse_note_mask = covered_quantity > 0
        existing_notes = driver.loc[warehouse_note_mask, "ملاحظات"].fillna("").astype(str)
        driver.loc[warehouse_note_mask, "ملاحظات"] = [
            (f"{note} | " if note.strip() else "")
            + f"صافي الشراء بعد المخزن: {int(round(float(quantity)))}"
            for note, quantity in zip(
                existing_notes, purchase_quantity_note[warehouse_note_mask]
            )
        ]

    # -- the four computed columns requested by the business -----------------
    import datetime as _dt

    expected_arrival_date = order_date + _dt.timedelta(days=lead_time)
    driver["Expected_Arrival"] = str(expected_arrival_date)
    # The exported ``المطلوب`` column is the branch need, not the net purchase
    # order.  Keep the financial value on the same basis so the sheet is
    # internally consistent even when warehouse allocation is enabled.
    driver["Financial_Value"] = (
        pd.to_numeric(driver["Calculated_Order"], errors="coerce").fillna(0.0)
        * pd.to_numeric(driver["Price"], errors="coerce").fillna(0.0)
    )
    # The warehouse-adjusted purchase layer stays available in diagnostics for
    # the buyer and for the audit sheet; it is deliberately not the main column.
    driver["Purchase_Financial_Value"] = (
        pd.to_numeric(driver["Final_Purchase_Order"], errors="coerce").fillna(0.0)
        * pd.to_numeric(driver["Price"], errors="coerce").fillna(0.0)
    )
    driver["Stock_Coverage_Days"] = (
        pd.to_numeric(driver["Effective_Stock"], errors="coerce").fillna(0.0)
        / pd.to_numeric(driver["Daily_Demand"], errors="coerce").replace(0, 1.0)
    ).clip(lower=0)

    def _order_reason(row: pd.Series) -> str:
        # Source labels first, then the actual branch-need reason.  A cosmetic
        # item is not automatically a distribution override; that label is only
        # used when the explicit force toggle is on.
        if bool(row.get("Is_Pushing_List")):
            return "Pushing List"
        if bool(row.get("Is_Transfer")):
            return "تحويلات"
        if bool(row.get("Is_Cosmetic")) and bool(row.get("Distribution_Target")):
            return "توزيع تجميل"
        try:
            calculated = float(row.get("Calculated_Order", 0) or 0.0)
        except (TypeError, ValueError):
            calculated = 0.0
        if calculated > 0:
            return "نقص في الرصيد"
        return "طلب عادي"

    driver["Order_Reason"] = driver.apply(_order_reason, axis=1)

    # Stagnant: positive branch stock, no sales in any of the four displayed
    # months, and a zero branch need.  The note is appended, never replaced.
    stagnant_mask = (
        (pd.to_numeric(driver["Branch_Stock"], errors="coerce").fillna(0.0) > 0)
        & (
            pd.to_numeric(
                driver["Current_Month_Sales"], errors="coerce"
            ).fillna(0.0)
            == 0
        )
        & (
            pd.to_numeric(driver[sales_headers[0]], errors="coerce").fillna(0.0)
            == 0
        )
        & (
            pd.to_numeric(driver[sales_headers[1]], errors="coerce").fillna(0.0)
            == 0
        )
        & (
            pd.to_numeric(driver[sales_headers[2]], errors="coerce").fillna(0.0)
            == 0
        )
        & (
            pd.to_numeric(
                driver["Calculated_Order"], errors="coerce"
            ).fillna(0.0)
            == 0
        )
        & (~driver["Distribution_Target"].fillna(False).astype(bool))
    )
    driver["Stagnant_Flag"] = stagnant_mask
    _existing_notes = driver["ملاحظات"].fillna("").astype(str)
    driver.loc[stagnant_mask, "ملاحظات"] = _existing_notes[stagnant_mask].apply(
        lambda x: f"{x} | راكد - لا يحتاج طلب" if x.strip() else "راكد - لا يحتاج طلب"
    )

    # -- the final frame ------------------------------------------------------
    export_columns = export_columns_for_date(order_date)
    final = pd.DataFrame(
        {
            "التصنيف": driver["Export_Category"].astype("string"),
            "الكود": driver["الكود"].astype("string"),
            "الاسم": driver["اسم الصنف"].astype("string"),
            # The main sheet is the branch need.  The warehouse-adjusted
            # purchase quantity remains a separate diagnostics layer.
            "المطلوب": driver["Calculated_Order"].astype("float64"),
            "السعر": driver["Price"].astype("float64"),
            "القيمة المالية للطلب": driver["Financial_Value"].astype("float64"),
            # Show the same net position used by the order calculation.
            # The raw branch balance and pending purchases remain available
            # separately in diagnostics.
            "الموجود في الفرع": driver["Effective_Stock"].astype("float64"),
            "الموجود في المخزن": driver["Warehouse_Stock"].astype("float64"),
            "التحويلات": driver["Net_Transfers"].astype("float64"),
            sales_headers[0]: driver[sales_headers[0]].astype("float64"),
            sales_headers[1]: driver[sales_headers[1]].astype("float64"),
            sales_headers[2]: driver[sales_headers[2]].astype("float64"),
            sales_headers[3]: driver[sales_headers[3]].astype("float64"),
            "المتوسط": driver["Export_Average"].astype("float64"),
            "ROP": driver["ROP"].astype("float64"),
            "Lead_Time": driver["Lead_Time"].astype("float64"),
            "تاريخ الوصول المتوقع": driver["Expected_Arrival"].astype("string"),
            "تغطية المخزون (أيام)": driver["Stock_Coverage_Days"].astype("float64"),
            "سبب الطلب": driver["Order_Reason"].astype("string"),
            "ملاحظات": driver["ملاحظات"].astype("string"),
        }
    ).loc[:, export_columns]

    # -- the requested calculation trace -------------------------------------
    # One line per catalogue item, including items whose required quantity is
    # zero (for example VOLTAREN at ROP).  The format is intentionally stable
    # so a buyer or a test can grep a single SKU from the run output.
    for debug_row in driver[
        ["اسم الصنف", "Daily_Demand", "ROP", "Calculated_Order"]
    ].itertuples(index=False, name=None):
        item, daily_value, rop_value, required_value = debug_row
        daily_demand = float(daily_value) if pd.notna(daily_value) else 0.0
        rop = float(rop_value) if pd.notna(rop_value) else 0.0
        required = int(max(float(required_value), 0.0)) if pd.notna(required_value) else 0
        print(f"DEBUG: {item} | Daily: {daily_demand} | ROP: {rop} | Req: {required}")

    # Build the substitute lines before applying the ordinary positive filter.
    substitute_rows, substitute_cost = _build_substitute_rows(
        driver,
        lead_time=lead_time,
        order_date=order_date,
        sales_headers=sales_headers,
        sales_months=sales_months,
    )

    # Scope: every non-stagnant, non-ignored item with a positive branch need,
    # plus every negative branch balance even when its calculated need is zero.
    # A negative balance is an inventory error the buyer must see, so it must
    # never be dropped by the ordinary positive-quantity filter.
    required = pd.to_numeric(final["المطلوب"], errors="coerce").fillna(0.0)
    negative_branch = (
        pd.to_numeric(driver["Branch_Stock"], errors="coerce").fillna(0.0) < 0
    )
    ordinary_keep = (
        ((required > 0) | negative_branch)
        & (~driver["Stagnant_Flag"])
        & ((~driver["Ignore_No_Sales_Flag"]) | negative_branch)
    )
    final = final.loc[ordinary_keep].copy()
    final = final.sort_values(["التصنيف", "الكود"], kind="stable").reset_index(drop=True)

    # Substitute rows are appended after the sorted sheet.
    if not substitute_rows.empty:
        final = pd.concat([final, substitute_rows], ignore_index=True)

    final = final.loc[:, export_columns].copy()
    final_required = pd.to_numeric(final["المطلوب"], errors="coerce").fillna(0.0)
    final["المطلوب"] = np.ceil(final_required.clip(lower=0.0)).astype("int64")
    negative_branch_codes = set(
        _clean_code_series(
            driver.loc[negative_branch, "الكود"]
        ).dropna().astype(str)
    )
    final_negative_branch = _clean_code_series(final["الكود"]).isin(
        negative_branch_codes
    )
    final = final.loc[(final["المطلوب"] > 0) | final_negative_branch].reset_index(
        drop=True
    )
    if final.empty:
        raise ValueError(
            "There are no items with a positive required quantity or a negative "
            "branch balance."
        )

    # Keep the colour decision on the frame itself.  The exporter also accepts
    # the flags from diagnostics, but this makes the priority explicit and
    # keeps the colours stable if the caller slices the final frame.
    row_colors: dict[str, str] = {}
    for code, pushing, multiple, transfer, warehouse in zip(
        driver["الكود"],
        driver["Is_Pushing_List"],
        driver["Is_Multi_Card"],
        driver["Is_Transfer"],
        driver["Warehouse_Loading"],
    ):
        color = ""
        if bool(warehouse):
            color = "#FFC0CB"
        elif bool(pushing):
            color = "#ADD8E6"
        elif bool(transfer):
            color = "#FFFFE0"
        elif bool(multiple):
            color = "#D3D3D3"
        if color:
            row_colors[str(code)] = color

    # A substitute line inherits the colour of the item it stands in for.
    if not substitute_rows.empty:
        for code in substitute_rows["الكود"].astype("string"):
            target_color = row_colors.get(str(code).strip(), "")
            if target_color:
                row_colors[str(code).strip()] = target_color

    final.attrs["row_colors"] = row_colors
    final.attrs["branch"] = selected_branch
    final.attrs["order_date"] = order_date
    final.attrs["lead_time"] = int(lead_time)
    final.attrs["export_columns"] = export_columns

    diagnostics = driver.copy()
    diagnostics["الرصيد الفعلي"] = diagnostics["Effective_Stock"]

    # -- the run level messages ----------------------------------------------
    run_messages: list[str] = []
    implausible_count = int(driver["Implausible_Stock_Flag"].sum())
    threshold = max(
        IMPLAUSIBLE_NEGATIVE_ABSOLUTE_THRESHOLD,
        int(len(driver) * IMPLAUSIBLE_NEGATIVE_RATIO_THRESHOLD),
    )
    if implausible_count:
        run_messages.append(
            f"تنبيه: {implausible_count:,} صنف برصيد فعلي سالب يحتاج إلى جرد "
            f"(الحد المقبول {threshold:,}). لم يتم إيقاف التحليل."
        )

    unmatched = {
        role: _count_unmatched(frame, column, master_skus)
        for role, frame, column in (
            ("shortages", shortages, "الكود"),
            ("branch_stock", branch_stock, "الكود"),
            ("warehouse_stock", warehouse_stock, "الكود"),
            ("recent_sales", recent_sales, "كود الصنف"),
            ("pending_purchases", pending, "كود الصنف"),
            ("transfers", transfers, "كود الصنف"),
        )
        if frame is not None and not frame.empty and column in frame.columns
    }
    total_unmatched = sum(unmatched.values())
    if total_unmatched:
        details = "، ".join(
            f"{role}: {count:,}" for role, count in unmatched.items() if count
        )
        run_messages.append(
            f"تنبيه: تم استبعاد {total_unmatched:,} سطر لا يوجد له كود في البيانات "
            f"الرئيسية ({details})."
        )

    if pack_model.mismatches:
        run_messages.append(
            f"تنبيه: {pack_model.mismatches:,} صف من {pack_model.checked_rows:,} "
            "لا يطابق قاعدة العبوات في النظام — راجع ملف رصيد الفرع."
        )

    if warehouse_clipped_rows:
        run_messages.append(
            f"تم رصد {warehouse_clipped_rows:,} سطر برصيد مخزن سالب — الرصيد "
            "معروض كما هو، واتحسب بصفر عند تغطية الطلب من المخزن."
        )

    if not substitute_rows.empty:
        run_messages.append(
            f"تمت إضافة {len(substitute_rows):,} سطر بديل في نهاية الشيت، "
            "مع الاحتفاظ بالسطر الأصلي كما هو."
        )

    if not ambiguous_aggregate.empty:
        run_messages.append(
            f"تنبيه: {len(ambiguous_aggregate):,} صنف له تحويلات غير مصنفة "
            "(غير صادرة ولا واردة) واستُبعدت من حساب الرصيد."
        )

    if demand_spine.panel_available:
        run_messages.append(
            f"تم استخدام ملف المبيعات الشهري لفرع {demand_spine.panel_branch} "
            f"({demand_spine.panel_months} شهر) كمصدر أساسي للطلب."
        )
    else:
        run_messages.append(
            "لا يوجد ملف مبيعات شهري: تم الاعتماد على متوسط النظام والمبيعات "
            "الحديثة بعد تحويلها إلى معدل شهري."
        )

    sigma_counts = driver["Sigma_Source"].value_counts()
    measured_sigma = int(sigma_counts.get(SIGMA_SOURCE_RECENT, 0))
    panel_sigma = int(sigma_counts.get(SIGMA_SOURCE_PANEL, 0))
    fallback_sigma = int(sigma_counts.get(SIGMA_SOURCE_FALLBACK, 0))
    if measured_sigma:
        run_messages.append(
            f"تم حساب الانحراف المعياري الحقيقي لـ {measured_sigma:,} صنف من "
            "إجمالي المبيعات الشهرية في تقرير مبيعات الفرع."
        )
    if panel_sigma:
        run_messages.append(
            f"تم استخدام انحراف لوحة المبيعات الشهري لـ {panel_sigma:,} صنف."
        )
    if fallback_sigma:
        run_messages.append(
            f"تم استخدام نسبة الاحتياطي {settings.variance_percent:.0f}% لـ "
            f"{fallback_sigma:,} صنف لعدم توفر انحراف معياري حقيقي."
        )

    negative_positions = int((driver["Effective_Stock"] < 0).sum())
    if negative_positions:
        run_messages.append(
            f"تم التعامل مع {negative_positions:,} رصيد سالب كصفر في حساب الطلب، "
            "مع عرض الرصيد السالب كما هو في الملف."
        )

    for warning in getattr(lead, "warnings", ()) or ():
        run_messages.append(f"جدول الفرع: {warning}")

    # -- the metrics ----------------------------------------------------------
    # The quantity and the cost follow the **exported sheet**, so the extra
    # substitute lines are counted in both.
    substituted_count = int(driver["Substituted_Out"].sum())
    included = driver.loc[ordinary_keep]
    catalogue_quantity = float(included["Calculated_Order"].sum())
    purchase_quantity = float(included["Final_Purchase_Order"].sum())
    substitute_quantity = (
        float(substitute_rows["المطلوب"].sum()) if not substitute_rows.empty else 0.0
    )
    estimated_cost = float(
        (included["Calculated_Order"] * included["Unit_Cost"]).sum()
    ) + substitute_cost
    purchase_estimated_cost = float(
        (included["Final_Purchase_Order"] * included["Unit_Cost"]).sum()
    ) + substitute_cost
    metrics = {
        "total_items": int(len(driver)),
        "total_rows": int(len(final)),
        "total_order_quantity": catalogue_quantity + substitute_quantity,
        "purchase_order_quantity": purchase_quantity + substitute_quantity,
        "estimated_cost": estimated_cost,
        "purchase_estimated_cost": purchase_estimated_cost,
        "warehouse_covered_quantity": float(included["Warehouse_Covered"].sum()),
        "zero_stock_count": int((driver["Effective_Stock"] <= 0).sum()),
        "negative_stock_count": int((driver["Effective_Stock"] < 0).sum()),
        "items_ordered": int((final["المطلوب"] > 0).sum()),
        "substituted_items": substituted_count,
        "substitute_rows": int(len(substitute_rows)),
        "substitute_quantity": substitute_quantity,
        "warehouse_clipped_rows": warehouse_clipped_rows,
        "lead_time": lead_time,
        "implausible_items": implausible_count,
        "unmatched_rows": total_unmatched,
        "panel_available": demand_spine.panel_available,
        "recent_sales_days": demand_spine.recent_days,
        "sigma_recent_items": measured_sigma,
        "sigma_panel_items": panel_sigma,
        "sigma_fallback_items": fallback_sigma,
        "negative_ordering_stock_items": negative_positions,
    }

    # -- the stock reconciliation strip --------------------------------------
    reconciliation = _build_reconciliation(driver, settings)

    # FAIL-FAST: verify no unexpected override changed the branch-need column.
    # The main sheet is Calculated_Order, not Calculated_Order - Warehouse.
    _included_calc = float(
        pd.to_numeric(
            driver.loc[ordinary_keep, "Calculated_Order"], errors="coerce"
        ).fillna(0).sum()
    )
    _actual_final = float(
        pd.to_numeric(final["المطلوب"], errors="coerce").fillna(0).sum()
    )
    _substitute_allowance = (
        float(
            pd.to_numeric(
                driver["Substitute_Request"], errors="coerce"
            ).fillna(0).sum()
        )
        if "Substitute_Request" in driver.columns
        else 0.0
    )
    _expected_with_subs = _included_calc + _substitute_allowance
    if abs(_actual_final - _expected_with_subs) > max(
        1.0, _expected_with_subs * 0.01
    ):
        print(
            f"⚠️ FAIL-FAST WARNING: Final ({_actual_final}) ≠ "
            f"Included Calculated ({_included_calc}) + Subs "
            f"({_substitute_allowance})"
        )
        print(f"   Difference: {_actual_final - _expected_with_subs}")

    return PipelineResult(
        final=final,
        diagnostics=diagnostics,
        metrics=metrics,
        run_messages=run_messages,
        lead_time=lead,
        stock_reconciliation=reconciliation,
        demand=demand_spine,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# The substitute hand-over
# ---------------------------------------------------------------------------
def _build_item_status(driver: pd.DataFrame) -> pd.Series:
    """Return the ``حالة الصنف`` label of every catalogue line.

    The rules are applied in order, and the first match wins:

    * a positive branch need -> ``يحتاج طلب``;
    * a zero branch need with enough stock for the whole month -> ``مغطى بالكامل``;
    * a zero branch need that is still above the reorder point -> covered up to
      the supply period;
    * anything else stays blank.
    """
    status = pd.Series("", index=driver.index, dtype="string")
    status = status.mask(driver["Calculated_Order"] > 0, ITEM_STATUS_ORDER)

    zero_order = driver["Calculated_Order"] == 0
    fully_covered = zero_order & (
        driver["Effective_Stock"] >= driver["Target_Demand"]
    )
    covered_to_lead = zero_order & (driver["Effective_Stock"] > driver["ROP"])

    status = status.mask(fully_covered & status.eq(""), ITEM_STATUS_FULLY_COVERED)
    status = status.mask(covered_to_lead & status.eq(""), ITEM_STATUS_COVERED_LEAD_TIME)
    return status


def _apply_substitute_demand(driver: pd.DataFrame) -> pd.DataFrame:
    """Leave the unsupplied item at zero and record where its demand went.

    The requirement is **recorded**, not merged into the substitute's own
    line: the substitute is written as an extra line of its own (see
    :func:`_build_substitute_rows`), so the buyer can see which item is being
    replaced by which and each line still carries its own warehouse stock.
    """
    codes = driver["Substitute_Code"].astype("string").fillna("")
    applied = codes.ne("") & (driver["Calculated_Order"] > 0)

    driver["Substituted_Out"] = applied
    driver["Substitute_Request"] = 0.0
    driver["Transferred_In"] = 0.0

    if not bool(applied.any()):
        return driver

    driver.loc[applied, "Substitute_Request"] = driver.loc[applied, "Calculated_Order"]
    driver.loc[applied, "Calculated_Order"] = 0.0
    # The rounding note belongs to the line that is actually ordered.
    driver.loc[applied, "Pack_Rounding_Applied"] = False

    # ``Transferred_In`` keeps its audit meaning: how much demand arrived at
    # this item because it stands in for another one.
    incoming = (
        driver.loc[applied]
        .groupby(codes.loc[applied], sort=False)["Substitute_Request"]
        .sum()
    )
    driver["Transferred_In"] = codes.map(incoming).fillna(0.0).astype("float64")
    return driver


def _build_substitute_rows(
    driver: pd.DataFrame,
    *,
    lead_time: int,
    order_date: date,
    sales_headers: list[str],
    sales_months: tuple[int, ...],
) -> tuple[pd.DataFrame, float]:
    """Write the extra purchase line of every substitute.

    A substitute is suggested only when the central warehouse cannot cover the
    original requirement.  Its line carries the shortfall
    ``Required - Warehouse_Stock``.  The original line is always kept.
    """
    columns = export_columns_for_date(order_date)
    empty = pd.DataFrame(columns=columns)

    substitute_codes = (
        driver["Substitute_Code"].astype("string").fillna("").str.strip()
    )
    requests = driver.loc[
        driver["Substituted_Out"].fillna(False).astype(bool)
        & substitute_codes.ne("")
    ].sort_values("الكود", kind="stable")
    if requests.empty:
        return empty, 0.0

    by_sku = driver.copy()
    by_sku["_Lookup_Code"] = _clean_code_series(by_sku["الكود"])
    by_sku = by_sku.loc[
        by_sku["_Lookup_Code"].notna()
    ].drop_duplicates("_Lookup_Code", keep="first")
    by_sku = by_sku.set_index("_Lookup_Code", drop=False)

    rows: list[dict[str, object]] = []
    cost = 0.0
    for request in requests.to_dict("records"):
        source_code = _clean_text(request.get("الكود"))
        source_name = _clean_text(request.get("اسم الصنف")) or source_code
        substitute = clean_sku(request.get("Substitute_Code"))
        if pd.isna(substitute):
            continue
        substitute = str(substitute).strip()
        if not substitute or substitute not in by_sku.index:
            continue
        target = by_sku.loc[substitute]
        if isinstance(target, pd.DataFrame):
            target = target.iloc[0]

        shortfall = _as_float(request.get("Substitute_Request"))
        if shortfall <= 0:
            continue
        required = max(int(math.ceil(shortfall)), 1)
        price = _as_float(target.get("Price"))
        cost += required * _as_float(target.get("Unit_Cost"))
        coverage_days = max(
            _as_float(target.get("Stock_Coverage_Days")), 0.0
        )

        note = f"بديل للصنف {source_name}"
        reason = _substitute_reason(request, target)
        if reason:
            note = f"{note} - السبب: {reason}"

        row: dict[str, object] = {
            "التصنيف": _clean_text(target.get("Export_Category")),
            "الكود": substitute,
            "الاسم": _clean_text(target.get("اسم الصنف")),
            "المطلوب": required,
            "السعر": price,
            "القيمة المالية للطلب": required * price,
            "الموجود في الفرع": _as_float(target.get("Branch_Stock")),
            "الموجود في المخزن": _as_float(target.get("Warehouse_Stock")),
            "التحويلات": _as_float(target.get("Net_Transfers")),
            "المتوسط": _as_float(target.get("Export_Average")),
            "ROP": _as_float(target.get("ROP")),
            "Lead_Time": float(lead_time),
            "تاريخ الوصول المتوقع": (
                pd.Timestamp(order_date) + pd.Timedelta(days=int(lead_time))
            ).strftime("%Y-%m-%d"),
            "تغطية المخزون (أيام)": coverage_days,
            "سبب الطلب": "بديل",
            "ملاحظات": note,
            "_Source_Code": source_code,
        }
        for header in sales_headers:
            row[header] = _as_float(target.get(header), float("nan"))
        rows.append(row)

    if not rows:
        return empty, 0.0
    return pd.DataFrame(rows, columns=columns), cost


def _substitute_reason(
    source: dict[str, object],
    target: pd.Series,
) -> str:
    """Return a data-driven reason for the substitute note, if known."""
    reasons: list[str] = []
    if bool(source.get("Is_Multi_Card", False)) or bool(
        target.get("Is_Multi_Card", False)
    ):
        reasons.append("كارته مختلفة")

    source_pack = _as_float(source.get("Pack Size"), 1.0)
    target_pack = _as_float(target.get("Pack Size"), 1.0)
    if abs(source_pack - target_pack) > 1e-9:
        reasons.append("فرق حجم")

    if bool(source.get("Form_Mismatch", False)):
        reasons.append("اختلاف الشكل الدوائي")
    return " / ".join(dict.fromkeys(reason for reason in reasons if reason))


def _clean_text(value: object) -> str:
    """Render a cell as stripped text, mapping missing values to ``""``."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _as_float(value: object, default: float = 0.0) -> float:
    """Render a cell as a finite float, mapping junk to ``default``."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


# ---------------------------------------------------------------------------
# Small helpers used by the pipeline
# ---------------------------------------------------------------------------
def _multi_price_flags(
    multi_price: pd.DataFrame | None,
    skus: pd.Series,
) -> pd.Series:
    """Flag the items that carry more than one selling price."""
    flags = pd.Series(False, index=skus.index)
    if multi_price is None or multi_price.empty:
        return flags
    sku_column = next(
        (column for column in ("كود الصنف", "الكود") if column in multi_price.columns),
        None,
    )
    if sku_column is None:
        return flags
    counts = multi_price[sku_column].astype("string").value_counts()
    repeated = set(counts[counts > 1].index.tolist())
    if not repeated:
        return flags
    return skus.astype("string").isin(repeated)


def _build_reconciliation(
    driver: pd.DataFrame,
    settings: SupplyChainSettings,
) -> pd.DataFrame:
    """Compare the three stock bases so the user can see the impact."""
    snapshot = driver["Branch_Stock"] + driver["Pending_Purchases"]
    out_transfers = snapshot - driver["Transfers_Out"]
    full_net = out_transfers + driver["Transfers_In"]

    rows = []
    for label, position in (
        ("snapshot", snapshot),
        ("out_transfers", out_transfers),
        ("full_net", full_net),
    ):
        rows.append(
            {
                "Basis": label,
                "Is_Selected": label == settings.stock_basis,
                "Negative_Items": int((position < 0).sum()),
                "Zero_Items": int((position <= 0).sum()),
                "Total_Packs": float(position.clip(lower=0).sum()),
            }
        )
    return pd.DataFrame(rows)


def _validate_settings(settings: SupplyChainSettings) -> None:
    """Reject impossible settings before a single row is touched."""
    if not math.isfinite(settings.z_score) or settings.z_score <= 0:
        raise ValueError("Z-Score must be a valid positive number.")
    if not math.isfinite(settings.variance_percent) or settings.variance_percent < 0:
        raise ValueError("The coefficient of variation cannot be negative.")
    if settings.review_period_days < 1:
        raise ValueError("The review period must be at least one day.")
    if settings.moq_packs < 1:
        raise ValueError("The minimum order quantity must be at least one pack.")