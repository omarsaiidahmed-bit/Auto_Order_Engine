"""The audit and reconciliation panel.

The audit data is produced in the **same run** as the analysis, so the numbers
shown here can never disagree with the exported file.

Six panels are built:

``summary``
    the headline counts of the run.
``negatives``
    every item whose effective position went negative, with the components
    that produced it.
``transfer_vocabulary``
    every distinct movement label of the transfer ledger and how it was
    classified -- the proof that ``ارسال`` is outgoing and ``استقبال`` is
    incoming.
``reconciliation``
    the difference between the ERP's own ``الكمية الموجودة`` and the
    computed effective position.
``substitutes``
    every item whose demand was moved onto a replacement.
``stock_bases``
    the measured effect of the three stock bases.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app_config import (
    OPERATION_AMBIGUOUS,
    OPERATION_INCOMING,
    OPERATION_OUTGOING,
    OPERATION_UNKNOWN,
)
from core.aggregation import (
    classify_operations,
    detect_transfer_sign_convention,
    transfer_magnitudes,
)
from core.normalize import normalize_operation

__all__ = ["build_audit_report", "explain_item"]


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _transfer_vocabulary(transfers: pd.DataFrame | None) -> pd.DataFrame:
    """Panel -- every distinct operation value and how it was classified."""
    columns = [
        "Operation_Label",
        "Operation_Class",
        "Rows",
        "Items",
        "Packs",
        "Pieces",
        "Magnitude",
    ]
    if transfers is None or transfers.empty:
        return _empty_frame(columns)

    frame = transfers.copy()
    frame["Operation_Label"] = frame["العملية"].astype("string").map(normalize_operation)
    frame["Operation_Class"] = classify_operations(frame)
    frame["Magnitude"] = transfer_magnitudes(frame)

    vocabulary = (
        frame.groupby(["Operation_Label", "Operation_Class"], as_index=False, sort=False)
        .agg(
            Rows=("Magnitude", "size"),
            Items=("كود الصنف", "nunique"),
            Packs=("عبوات", "sum"),
            Pieces=("اجزاء", "sum"),
            Magnitude=("Magnitude", "sum"),
        )
        .sort_values("Magnitude", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    return vocabulary


def _demand_sources(diagnostics: pd.DataFrame) -> pd.DataFrame:
    """How many items took their demand from each signal."""
    columns = ["Demand_Source", "Items", "Total_Demand"]
    if diagnostics.empty or "Demand_Source" not in diagnostics.columns:
        return _empty_frame(columns)
    grouped = (
        diagnostics.groupby("Demand_Source", as_index=False, sort=False)
        .agg(Items=("Demand_Source", "size"), Total_Demand=("Target_Demand", "sum"))
        .sort_values("Items", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    return grouped


def build_audit_report(
    data_by_role: dict[str, pd.DataFrame],
    diagnostics: pd.DataFrame,
    *,
    stock_basis: str = "out_transfers",
    substitute_form_policy: str = "compatible",
    stock_reconciliation: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build every panel of the audit view."""
    total_items = int(len(diagnostics))

    negatives_mask = diagnostics["Effective_Stock"] < 0
    implausible_mask = diagnostics["Implausible_Stock_Flag"].astype(bool)

    negatives = diagnostics.loc[
        negatives_mask,
        [
            "الكود",
            "اسم الصنف",
            "Branch_Stock",
            "Pending_Purchases",
            "Transfers_In",
            "Transfers_Out",
            "Effective_Stock",
            "Warehouse_Stock",
            "Core_Name",
        ],
    ].copy()
    negatives = negatives.sort_values(
        "Effective_Stock", ascending=True, kind="stable"
    ).reset_index(drop=True)

    baseline = data_by_role.get("shortages")
    reconciliation = _empty_frame(
        ["الكود", "اسم الصنف", "ERP_Mالموجود", "Effective_Stock", "Difference"]
    )
    if baseline is not None and not baseline.empty and "الموجود" in baseline.columns:
        erp = baseline.loc[:, ["الكود", "الاسم", "الموجود"]].copy()
        erp["الكود"] = erp["الكود"].astype("string")
        erp = erp.rename(columns={"الاسم": "اسم الصنف", "الموجود": "ERP_Mالموجود"})
        computed = diagnostics.loc[:, ["الكود", "اسم الصنف", "Effective_Stock"]].copy()
        computed["الكود"] = computed["الكود"].astype("string")
        merged = erp.merge(computed, how="left", on="الكود", validate="one_to_one")
        merged["ERP_Mالموجود"] = pd.to_numeric(
            merged["ERP_Mالموجود"], errors="coerce"
        ).fillna(0)
        merged["Difference"] = merged["Effective_Stock"] - merged["ERP_Mالموجود"]
        reconciliation = merged.loc[
            merged["Difference"].abs() > 0.5
        ].sort_values("Difference", ascending=True, kind="stable").reset_index(drop=True)

    substitutes = _empty_frame(
        [
            "الكود",
            "اسم الصنف",
            "Substitute_Code",
            "Substitute_Name",
            "Substitutes",
            "Transferred_In",
        ]
    )
    has_substitute = diagnostics["Substitute_Code"].notna() & diagnostics[
        "Substitute_Code"
    ].astype("string").fillna("").ne("")
    if bool(has_substitute.any()):
        substitutes = diagnostics.loc[
            has_substitute,
            [
                "الكود",
                "اسم الصنف",
                "Substitute_Code",
                "Substitute_Name",
                "Substitutes",
                "Transferred_In",
            ],
        ].sort_values("Substitutes", ascending=False, kind="stable").reset_index(
            drop=True
        )

    transfers = data_by_role.get("transfers")
    vocabulary = _transfer_vocabulary(transfers)

    outgoing_rows = None
    if transfers is not None and not transfers.empty:
        outgoing_rows = transfers.loc[classify_operations(transfers) == OPERATION_OUTGOING]
    sign_convention = (
        detect_transfer_sign_convention(outgoing_rows)
        if outgoing_rows is not None
        else "unsigned"
    )

    ambiguous_rows = (
        vocabulary.loc[
            vocabulary["Operation_Class"].isin([OPERATION_AMBIGUOUS, OPERATION_UNKNOWN])
        ]
        if not vocabulary.empty
        else _empty_frame(list(vocabulary.columns))
    )

    class_rows = (
        vocabulary.groupby("Operation_Class")["Rows"].sum().to_dict()
        if not vocabulary.empty
        else {}
    )

    summary = {
        "total_items": total_items,
        "negative_branch_items": int(diagnostics["Branch_Negative_Flag"].fillna(False).sum()),
        "negative_position_items": int(negatives_mask.sum()),
        "implausible_position_items": int(implausible_mask.sum()),
        "outgoing_transfers": float(diagnostics["Transfers_Out"].sum()),
        "incoming_transfers": float(diagnostics["Transfers_In"].sum()),
        "outgoing_transfer_rows": int(class_rows.get(OPERATION_OUTGOING, 0)),
        "incoming_transfer_rows": int(class_rows.get(OPERATION_INCOMING, 0)),
        "ambiguous_transfer_rows": int(
            class_rows.get(OPERATION_AMBIGUOUS, 0)
            + class_rows.get(OPERATION_UNKNOWN, 0)
        ),
        "pending_purchases": float(diagnostics["Pending_Purchases"].sum()),
        "stock_basis": stock_basis,
        "sign_convention": sign_convention,
        "substitute_form_policy": substitute_form_policy,
        "substitutes_used": int(has_substitute.sum()),
        "quantity_transferred": float(diagnostics["Transferred_In"].sum()),
        "zero_warehouse_items": int((diagnostics["Warehouse_Stock"] <= 0).sum()),
        "items_ordered": int((diagnostics["Final_Purchase_Order"] > 0).sum()),
    }

    return {
        "summary": summary,
        "negatives": negatives,
        "transfer_vocabulary": vocabulary,
        "ambiguous_transfers": ambiguous_rows,
        "reconciliation": reconciliation,
        "substitutes": substitutes,
        "demand_sources": _demand_sources(diagnostics),
        "stock_bases": (
            stock_reconciliation
            if stock_reconciliation is not None and not stock_reconciliation.empty
            else _empty_frame(
                ["Basis", "Is_Selected", "Negative_Items", "Zero_Items", "Total_Packs"]
            )
        ),
    }


def explain_item(diagnostics: pd.DataFrame, sku: str) -> dict[str, Any] | None:
    """Return the full derivation of one item."""
    if diagnostics.empty:
        return None
    codes = diagnostics["الكود"].astype("string")
    matches = diagnostics.loc[codes == str(sku)]
    if matches.empty:
        return None
    row = matches.iloc[0]

    def number(key: str) -> float:
        try:
            value = row.get(key, 0)
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def text(key: str) -> str:
        value = row.get(key, "")
        return "" if value is None or pd.isna(value) else str(value)

    return {
        "الكود": text("الكود"),
        "الاسم": text("اسم الصنف"),
        "التصنيف": text("Export_Category"),
        "Branch_Stock": number("Branch_Stock"),
        "Pending_Purchases": number("Pending_Purchases"),
        "Transfers_In": number("Transfers_In"),
        "Transfers_Out": number("Transfers_Out"),
        "Effective_Stock": number("Effective_Stock"),
        "Target_Demand": number("Target_Demand"),
        "Monthly_Sigma": number("Monthly_Sigma"),
        "Demand_Source": text("Demand_Source"),
        "Safety_Stock": number("Safety_Stock"),
        "ROP": number("ROP"),
        "Order_Up_To_Level": number("Order_Up_To_Level"),
        "Calculated_Order": number("Calculated_Order"),
        "Pack Size": number("Pack Size"),
        "Order_Before_Pack_Rounding": number("Order_Before_Pack_Rounding"),
        "Warehouse_Stock": number("Warehouse_Stock"),
        "Warehouse_Covered": number("Warehouse_Covered"),
        "Final_Purchase_Order": number("Final_Purchase_Order"),
        "Core_Name": text("Core_Name"),
        "Substitute_Code": text("Substitute_Code"),
        "Transferred_In": number("Transferred_In"),
        "Lead_Time": number("Lead_Time"),
    }
