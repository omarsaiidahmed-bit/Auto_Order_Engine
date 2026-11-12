"""The substitute engine (Version 2.0.0).

Two rules coexist:

* **Same-name substitution** (authoritative new rule): if an item has a
  substitute with the *same name*, has a sales rate, and zero warehouse
  availability, the original row is **kept** and a new substitute row is
  **appended** at the bottom.  No claim of therapeutic equivalence is made
  solely from similar names; the match is exact by normalized item name.
* **Core-name substitution** (legacy): still available for compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from app_config import DEFAULT_SUBSTITUTE_FORM_POLICY, SUBSTITUTE_FORM_POLICIES
from core.normalize import normalize_arabic_text, normalize_key

__all__ = [
    "ProductIdentity",
    "build_identity_series",
    "extract_core_name",
    "find_same_name_substitutes",
    "find_substitutes",
    "forms_are_compatible",
]


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------
FORM_ALIASES: dict[str, str] = {
    "TAB": "TABLET",
    "TABS": "TABLET",
    "TABLET": "TABLET",
    "TABLETS": "TABLET",
    "CAP": "CAPSULE",
    "CAPS": "CAPSULE",
    "CAPSULE": "CAPSULE",
    "CAPSULES": "CAPSULE",
    "STRIP": "STRIP",
    "STRIPS": "STRIP",
    "SUPP": "SUPPOSITORY",
    "SUPPS": "SUPPOSITORY",
    "SUPPOS": "SUPPOSITORY",
    "SUPPOSITORY": "SUPPOSITORY",
    "SUPPOSITORIES": "SUPPOSITORY",
    "SACH": "SACHET",
    "SACHET": "SACHET",
    "SACHETS": "SACHET",
    "SYR": "SYRUP",
    "SYRP": "SYRUP",
    "SYRUP": "SYRUP",
    "SUSP": "SUSPENSION",
    "SUSPENSION": "SUSPENSION",
    "SUSPN": "SUSPENSION",
    "CREAM": "CREAM",
    "CREAMS": "CREAM",
    "OINT": "OINTMENT",
    "OINTMENT": "OINTMENT",
    "GEL": "GEL",
    "GELS": "GEL",
    "LOT": "LOTION",
    "LOTION": "LOTION",
    "LOTIONS": "LOTION",
    "DROPS": "DROPS",
    "DROP": "DROPS",
    "INJ": "INJECTION",
    "INJECTION": "INJECTION",
    "INJECTIONS": "INJECTION",
    "SOL": "SOLUTION",
    "SOLUTION": "SOLUTION",
    "SOLN": "SOLUTION",
    "AMP": "AMPOULE",
    "AMPOULE": "AMPOULE",
    "AMPOULES": "AMPOULE",
    "VIAL": "VIAL",
    "VIALS": "VIAL",
    "SPRAY": "SPRAY",
    "PATCH": "PATCH",
    "PATCHES": "PATCH",
    "FOAM": "FOAM",
    "POW": "POWDER",
    "POWDER": "POWDER",
    "GRAN": "GRANULES",
    "GRANULES": "GRANULES",
    "NEB": "NEBULE",
    "NEBULE": "NEBULE",
    "NEBULES": "NEBULE",
    "ORAL": "ORAL",
    "TOP": "TOPICAL",
    "TOPICAL": "TOPICAL",
}

_FORM_KEY = {
    "TABLET": "SOLID_ORAL",
    "CAPSULE": "SOLID_ORAL",
    "STRIP": "SOLID_ORAL",
    "SACHET": "POWDER_ORAL",
    "GRANULES": "POWDER_ORAL",
    "POWDER": "POWDER_ORAL",
    "SYRUP": "LIQUID_ORAL",
    "SUSPENSION": "LIQUID_ORAL",
    "SOLUTION": "LIQUID_ORAL",
    "DROPS": "LIQUID_ORAL",
    "NEBULE": "INHALATION",
    "CREAM": "TOPICAL",
    "OINTMENT": "TOPICAL",
    "GEL": "TOPICAL",
    "LOTION": "TOPICAL",
    "SUPPOSITORY": "RECTAL_VAGINAL",
    "INJECTION": "PARENTERAL",
    "AMPOULE": "PARENTERAL",
    "VIAL": "PARENTERAL",
    "SPRAY": "MISC",
    "PATCH": "MISC",
    "FOAM": "MISC",
}

_COMPATIBLE_FORMS: set[frozenset[str]] = {
    frozenset({"LIQUID_ORAL", "SOLID_ORAL"}),
}

FORM_TOKEN_RE = re.compile(r"\b(" + "|".join(sorted(FORM_ALIASES, key=len, reverse=True)) + r")\b")
STRENGTH_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(MCG|UG|ΜG|MG|G|ML|IU|%|MEQ|MMOL)")
GLUED_STRENGTH_RE = re.compile(r"([A-Z]+)(\d+(?:\.\d+)?(?:MCG|UG|MG|G|ML|IU|%))")
PACK_COUNT_RE = re.compile(r"\b(\d+)\s*(TAB|TABS|CAP|CAPS|STRIP|STRIPS)\b")
MANUFACTURER_PARENS_RE = re.compile(r"\([^()]*\)")
TRAILING_PRICE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(LE|EGP|L\.E)\b", re.IGNORECASE)
EXTRA_WHITESPACE_RE = re.compile(r"\s+")

PROMO_TOKENS = {
    "PROMO",
    "OFFER",
    "FREE",
    "GIFT",
    "NEW",
    "PACK",
    "VALUE",
    "ECONOMY",
    "FAMILY",
    "BUNDLE",
}
NOISE_TOKENS = {"THE", "A", "AN", "AND", "OF", "FOR", "WITH"}


@dataclass(frozen=True)
class ProductIdentity:
    """The normalised identity of one product name."""

    original_name: str
    normalized_name: str
    tokens: tuple[str, ...]
    identity_tokens: tuple[str, ...]
    strength_tokens: frozenset[str]
    form_tokens: frozenset[str]
    core_key: tuple[tuple[str, ...], frozenset[str]]


def _strip_noise(name: str) -> str:
    text = name.upper()
    text = MANUFACTURER_PARENS_RE.sub(" ", text)
    text = TRAILING_PRICE_RE.sub(" ", text)
    text = text.replace("-", " ")
    text = GLUED_STRENGTH_RE.sub(r"\1 \2", text)
    text = EXTRA_WHITESPACE_RE.sub(" ", text).strip()
    return text


def _merge_pack_count(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isdigit() and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt in {"TAB", "TABS", "CAP", "CAPS", "STRIP", "STRIPS"}:
                i += 2
                continue
        merged.append(token)
        i += 1
    return merged


def _classify(tokens: Sequence[str]) -> tuple[list[str], frozenset[str], frozenset[str]]:
    identity: list[str] = []
    strengths: set[str] = set()
    forms: set[str] = set()
    for token in tokens:
        if not token:
            continue
        if token in PROMO_TOKENS or token in NOISE_TOKENS:
            continue
        match = STRENGTH_TOKEN_RE.fullmatch(token) or STRENGTH_TOKEN_RE.match(token)
        if match and len(match.group(0)) == len(token):
            strengths.add(token)
            continue
        if token in FORM_ALIASES or FORM_TOKEN_RE.fullmatch(token):
            canonical = FORM_ALIASES.get(token, token)
            forms.add(canonical)
            continue
        identity.append(token)
    return identity, frozenset(strengths), frozenset(forms)


def build_identity_series(names: pd.Series) -> pd.Series:
    """Return a :class:`ProductIdentity` for each name."""
    identities = []
    for name in names:
        identities.append(extract_core_name(name))
    return pd.Series(identities, index=names.index)


def extract_core_name(name: object) -> ProductIdentity:
    """Normalise ``name`` into a :class:`ProductIdentity`."""
    original = "" if name is None else str(name)
    stripped = _strip_noise(original)
    tokens = stripped.split()
    tokens = _merge_pack_count(tokens)
    identity_tokens, strength_tokens, form_tokens = _classify(tokens)
    identity_key = tuple(sorted(set(identity_tokens)))
    core_key = (identity_key, frozenset(strength_tokens))
    normalized = " ".join(tokens)
    return ProductIdentity(
        original_name=original,
        normalized_name=normalized,
        tokens=tuple(tokens),
        identity_tokens=tuple(identity_tokens),
        strength_tokens=strength_tokens,
        form_tokens=form_tokens,
        core_key=core_key,
    )


def forms_are_compatible(form_a: str, form_b: str, policy: str = DEFAULT_SUBSTITUTE_FORM_POLICY) -> bool:
    """Return True when the two dosage forms may be substituted for each other."""
    if policy == "identical":
        return form_a == form_b
    if policy == "any":
        return True
    if form_a == form_b:
        return True
    key_a = _FORM_KEY.get(form_a)
    key_b = _FORM_KEY.get(form_b)
    if key_a is None or key_b is None:
        return form_a == form_b
    if key_a == key_b:
        return True
    return {key_a, key_b} in _COMPATIBLE_FORMS


def find_same_name_substitutes(
    driver: pd.DataFrame,
    *,
    name_column: str = "اسم الصنف",
) -> pd.DataFrame:
    """Attach a same-name substitute for items that have zero warehouse
    availability and a sales rate, without replacing the original row."""
    if driver is None or driver.empty:
        return driver
    if name_column not in driver.columns:
        return driver
    frame = driver.copy()
    frame["_name_key"] = frame[name_column].apply(
        lambda v: normalize_key(v) if v is not None and str(v).strip() else ""
    )
    if "الكود" in frame.columns:
        frame["_code"] = frame["الكود"].astype("string")
    else:
        frame["_code"] = ""
    for col in ("Warehouse_Stock", "Branch_Stock", "Target_Demand", "ERP_Average"):
        if col not in frame.columns:
            frame[col] = 0.0
    for col in ("Warehouse_Stock", "Branch_Stock", "Target_Demand", "ERP_Average"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)

    frame["SameName_Substitute_Code"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["SameName_Substitute_Name"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["SameName_Substitute_Original"] = pd.Series(pd.NA, index=frame.index, dtype="string")

    for name_key, group in frame.groupby("_name_key"):
        if not name_key or len(group) < 2:
            continue
        originals = group[(group["Warehouse_Stock"] <= 0) & ((group["Target_Demand"] > 0) | (group["ERP_Average"] > 0))]
        if originals.empty:
            continue
        substitutes = group[~group.index.isin(originals.index)].copy()
        if substitutes.empty:
            continue
        substitutes["_score"] = (
            (substitutes["Branch_Stock"] > 0).astype(int) * 3
            + (substitutes["Warehouse_Stock"] > 0).astype(int) * 2
            + ((substitutes["Target_Demand"] > 0) | (substitutes["ERP_Average"] > 0)).astype(int)
        )
        substitutes = substitutes.sort_values("_score", ascending=False)
        for orig_idx in originals.index:
            if pd.notna(frame.at[orig_idx, "SameName_Substitute_Code"]):
                continue
            for _, sub_row in substitutes.iterrows():
                frame.at[orig_idx, "SameName_Substitute_Code"] = str(sub_row["الكود"]) if "الكود" in sub_row else ""
                frame.at[orig_idx, "SameName_Substitute_Name"] = str(sub_row[name_column])
                frame.at[orig_idx, "SameName_Substitute_Original"] = str(frame.at[orig_idx, name_column])
                break

    driver["SameName_Substitute_Code"] = frame["SameName_Substitute_Code"]
    driver["SameName_Substitute_Name"] = frame["SameName_Substitute_Name"]
    driver["SameName_Substitute_Original"] = frame["SameName_Substitute_Original"]
    return driver


def find_substitutes(
    driver: pd.DataFrame,
    *,
    form_policy: str = DEFAULT_SUBSTITUTE_FORM_POLICY,
    require_same_pack_size: bool = False,
    include_warehouse: bool = False,
) -> pd.DataFrame:
    """Attach a core-name substitute to items with effective stock <= 0.

    When ``include_warehouse`` is true, a card whose central-warehouse stock is
    positive is considered an official substitute even if its branch stock is
    zero.  The waterfall in :mod:`core.supply_chain` still decides whether the
    substitute's warehouse actually covers the remaining demand.
    """
    if driver is None or driver.empty or "الكود" not in driver.columns:
        return driver
    if "اسم الصنف" not in driver.columns:
        return driver

    work = driver.copy()
    if "Effective_Stock" not in work.columns:
        work["Effective_Stock"] = 0.0
    work["Effective_Stock"] = pd.to_numeric(work["Effective_Stock"], errors="coerce").fillna(0.0)
    if "Pack Size" not in work.columns:
        work["Pack Size"] = 1.0
    work["Pack Size"] = pd.to_numeric(work["Pack Size"], errors="coerce").fillna(1.0)
    if "Warehouse_Stock" not in work.columns:
        work["Warehouse_Stock"] = 0.0
    work["Warehouse_Stock"] = pd.to_numeric(
        work["Warehouse_Stock"], errors="coerce"
    ).fillna(0.0)

    identities = build_identity_series(work["اسم الصنف"])
    work["Core_Name"] = identities.apply(lambda identity: identity.core_key)
    work["Form_Signature"] = identities.apply(lambda identity: identity.form_tokens)

    candidates = work.copy()
    candidates["Available"] = candidates["Effective_Stock"] > 0
    if include_warehouse:
        candidates["Available"] = candidates["Available"] | (
            candidates["Warehouse_Stock"] > 0
        )
    available = candidates[candidates["Available"]].copy()
    if available.empty:
        return driver

    sort_columns = ["Core_Name", "Effective_Stock"]
    sort_ascending = [True, True]
    if include_warehouse:
        sort_columns = ["Core_Name", "Warehouse_Stock", "Effective_Stock"]
        sort_ascending = [True, False, False]
    best = (
        available.sort_values(
            sort_columns, ascending=sort_ascending, kind="stable"
        )
        .drop_duplicates("Core_Name", keep="first")[
            [
                "Core_Name",
                "الكود",
                "اسم الصنف",
                "Form_Signature",
                "Pack Size",
            ]
        ]
        .rename(
            columns={
                "الكود": "Best_Substitute_Code",
                "اسم الصنف": "Best_Substitute_Name",
                "Form_Signature": "Best_Form_Signature",
                "Pack Size": "Best_Pack_Size",
            }
        )
    )

    work = work.merge(best, how="left", on="Core_Name", validate="many_to_one")

    candidate = work["Best_Substitute_Code"].astype("string")
    same_item = candidate.fillna("").eq(work["الكود"].astype("string").fillna(""))
    if "Warehouse_Stock" in work.columns and "Calculated_Order" in work.columns:
        required = pd.to_numeric(
            work["Calculated_Order"], errors="coerce"
        ).fillna(0.0)
        warehouse = pd.to_numeric(
            work["Warehouse_Stock"], errors="coerce"
        ).fillna(0.0)
        needs = required.gt(0) & warehouse.lt(required)
    else:
        needs = work["Effective_Stock"].le(0)

    compatible = pd.Series(True, index=work.index)
    mismatch = pd.Series(False, index=work.index)
    memo: dict[tuple[frozenset[str], frozenset[str]], bool] = {}

    for index, row_forms, candidate_forms in zip(
        work.index, work["Form_Signature"], work["Best_Form_Signature"]
    ):
        if not isinstance(candidate_forms, frozenset):
            continue
        left = row_forms if isinstance(row_forms, frozenset) else frozenset()
        key = (left, candidate_forms)
        if key not in memo:
            memo[key] = forms_are_compatible(left, candidate_forms, policy=form_policy)
        compatible.loc[index] = memo[key]
        if left != candidate_forms:
            mismatch.loc[index] = True

    pack_size_ok = pd.Series(True, index=work.index)
    if require_same_pack_size:
        own = pd.to_numeric(work.get("Pack Size", 1.0), errors="coerce").fillna(1.0)
        other = pd.to_numeric(work["Best_Pack_Size"], errors="coerce").fillna(1.0)
        pack_size_ok = (own - other).abs() < 1e-9

    valid = (
        needs
        & candidate.notna()
        & (~same_item)
        & compatible
        & pack_size_ok
    )

    work.loc[valid, "Substitute_Code"] = candidate.loc[valid]
    work.loc[valid, "Substitute_Name"] = work.loc[valid, "Best_Substitute_Name"]
    work.loc[valid, "Form_Mismatch"] = mismatch.loc[valid]

    return work.drop(
        columns=[
            "Best_Substitute_Code",
            "Best_Substitute_Name",
            "Best_Form_Signature",
            "Best_Pack_Size",
        ]
    )
