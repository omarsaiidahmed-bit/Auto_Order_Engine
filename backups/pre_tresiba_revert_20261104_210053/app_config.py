"""Configuration constants for the Pharmacy Auto-Order Engine (V3).

This module holds **business data only** -- no logic and no ``streamlit`` import.

Design rules for V3
-------------------
* **Nothing is branch specific.**  There is no hard-coded branch name, no
  hard-coded SKU and no hard-coded category list that assumes one ERP export.
  The category tree maps the *observed* ERP vocabulary and falls back to
  ``أخرى`` for anything unknown, so a new branch folder works untouched.
* **Everything is measured, not assumed.**  The constants below were derived
  from a full read of a real branch export (78,803 catalogue rows).
* **The canonical unit is the pack** (``عبوة``).  ``الكمية`` in the ERP is a
  *pack-equivalent*:  ``الكمية = عبوات + اجزاء ÷ master's اججزاء``.
  See :mod:`core.quantity`.

Run the app with::

    streamlit run app.py
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# ---------------------------------------------------------------------------
# Section 1 -- Weekday calendar
# ---------------------------------------------------------------------------

DAYS_MAP: dict[str, int] = {
    "السبت": 0,
    "الأحد": 1,
    "الاثنين": 2,
    "الثلاثاء": 3,
    "الأربعاء": 4,
    "الخميس": 5,
    "الجمعة": 6,
}

ARABIC_WEEKDAYS_BY_PYTHON_INDEX: tuple[str, ...] = (
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)

WEEKDAY_NAMES_EN: dict[str, str] = {
    "السبت": "Saturday",
    "الأحد": "Sunday",
    "الاثنين": "Monday",
    "الثلاثاء": "Tuesday",
    "الأربعاء": "Wednesday",
    "الخميس": "Thursday",
    "الجمعة": "Friday",
}

FRIDAY = "الجمعة"

#: The replenishment cycle PharmaFly actually plans with: 48 hours of waiting
#: for the supplier plus four days of reordering, i.e. **six calendar days**
#: between the order and the receipt.  The Friday buffer is added on top of
#: this figure, never inside it.
PHARMAFLY_LEAD_TIME_DAYS = 6

#: The preparation -> delivery map exactly as issued by the business.  It is
#: kept for the routine calendar shown in the interface only; the lead time
#: that drives the reorder point is :data:`PHARMAFLY_LEAD_TIME_DAYS`.
#: Friday is absent by design: Friday is not a preparation day.
PREP_TO_DELIVERY: dict[str, str] = {
    "السبت": "الاثنين",
    "الأحد": "الثلاثاء",
    "الاثنين": "الأربعاء",
    "الثلاثاء": "الخميس",
    "الأربعاء": "السبت",
    "الخميس": "الأحد",
}

#: When the order date falls on Friday the branch does not prepare, so the
#: preparation effectively happens on the following Saturday.
FRIDAY_FALLBACK_PREP = "السبت"

#: Branch preparation weekdays (used only to *display* the routine schedule).
PREP_SCHEDULE: dict[str, list[str]] = {
    "السبت": [
        "العصافرة / ميامي",
        "كريم / جناكليس",
        "الملك حفني / باكوس",
        "اسكوت / سيدي بشر",
        "ابن الوليد / شعراوي",
        "محمد نجيب / النقل والهندسة",
        "الإقبال / المندرة",
        "السيوف / زيزينيا",
        "سيدي جابر / الأكاديمية",
    ],
    "الأحد": [
        "سموحة / الدخيلة",
        "الواحد وعشرين",
        "العجمي / بوابة 8",
        "الإبراهيمية / العروبة",
        "فاروس / البيطاش",
        "الهانوفيل / كيروسيز",
        "علي ابن أبي طالب / رشدي",
        "الوزان / مراقيا",
        "الوزارة / المعسكر",
    ],
    "الاثنين": [
        "الجندي المجهول",
        "كريم / فلمنج",
        "الملك حفني / باكوس",
        "فيكتوريا / الانباتكلا",
        "الشاطبي / بورسعيد",
        "المبرة / محرم بك",
        "الكورنيش / المرور",
        "محطة الرمل / المشير",
        "يوبانيو",
        "الرأس السوداء / المنشية",
    ],
    "الثلاثاء": [
        "العصافرة / ميامي",
        "جناكليس",
        "الملك حفني / باكوس",
        "اسكوت / سيدي بشر",
        "ابن الوليد / شعراوي",
        "محمد نجيب / النقل والهندسة",
        "الإقبال / المندرة",
        "السيوف / زيزينيا",
        "سيدي جابر / الأكاديمية",
    ],
    "الأربعاء": [
        "سموحة / الدخيلة",
        "كريم / الواحد وعشرين",
        "العجمي / بوابة 8",
        "الإبراهيمية / العروبة",
        "فاروس / البيطاش",
        "الهانوفيل / كيروسيز",
        "علي ابن أبي طالب / رشدي",
        "الوزان / مراقيا",
        "الوزارة / المعسكر",
    ],
    "الخميس": [
        "الجندي المجهول",
        "جليم",
        "فلمنج",
        "فيكتوريا / الانباتكلا",
        "الشاطبي / بورسعيد",
        "المبرة / محرم بك",
        "الكورنيش / المرور",
        "محطة الرمل / المشير",
        "يوبانيو",
        "الرأس السوداء / المنشية",
    ],
    "الجمعة": [],
}

BRANCH_LABELS_EN: dict[str, str] = {
    "العصافرة": "Al-Asafra",
    "ميامي": "Miami",
    "كريم": "Karim",
    "جناكليس": "Gnaklees",
    "الملك حفني": "El-Malek Hefni",
    "باكوس": "Bakous",
    "اسكوت": "Escot",
    "سيدي بشر": "Sidi Bishr",
    "ابن الوليد": "Ibn Al-Waleed",
    "شعراوي": "Shaarawy",
    "محمد نجيب": "Mohamed Naguib",
    "النقل والهندسة": "Transport and Engineering",
    "الإقبال": "El-Iqbal",
    "المندرة": "Mandara",
    "السيوف": "El-Seyouf",
    "زيزينيا": "Zezenia",
    "سيدي جابر": "Sidi Gaber",
    "الأكاديمية": "Academy",
    "سموحة": "Smouha",
    "الدخيلة": "Dekheila",
    "الواحد وعشرين": "El-Wahed Weshreen",
    "العجمي": "Agami",
    "بوابة 8": "Gate 8",
    "الإبراهيمية": "Ibrahimia",
    "العروبة": "Orouba",
    "فاروس": "Pharos",
    "البيطاش": "Bitash",
    "الهانوفيل": "Hanoville",
    "كيروسيز": "Kerosiz",
    "علي ابن أبي طالب": "Ali Ibn Abi Talib",
    "رشدي": "Roshdy",
    "الوزان": "El-Wazzan",
    "مراقيا": "Meraqia",
    "الوزارة": "Ministry",
    "المعسكر": "Camp",
    "الجندي المجهول": "Unknown Soldier",
    "فلمنج": "Fleming",
    "فيكتوريا": "Victoria",
    "الانباتكلا": "Enbatakla",
    "الشاطبي": "Shatby",
    "بورسعيد": "Port Said",
    "المبرة": "Mabaret",
    "محرم بك": "Moharram Bek",
    "الكورنيش": "Corniche",
    "المرور": "Traffic",
    "محطة الرمل": "Raml Station",
    "المشير": "Marshal",
    "يوبانيو": "Yobanio",
    "الرأس السوداء": "Ras El-Soda",
    "المنشية": "Mansheya",
    "جليم": "Gleem",
    "بوالينو": "Boalino",
    "المعرض": "Al-Maarid",
}


def _build_branch_options() -> list[str]:
    """Derive the branch list from the preparation schedule."""
    options: dict[str, None] = {}
    for routes in PREP_SCHEDULE.values():
        for route in routes:
            for branch in route.split("/"):
                cleaned = branch.strip()
                if cleaned:
                    options.setdefault(cleaned, None)
    return list(options)


BRANCH_OPTIONS: list[str] = _build_branch_options()

# ---------------------------------------------------------------------------
# Section 2 -- Categories
# ---------------------------------------------------------------------------
# There is **no** category mapping and no category tree.  The ERP already ships
# a curated classification in the master file, so ``فئة التصنيف`` is copied to
# the order sheet exactly as received -- including the ``xxxx`` placeholders
# and the ``ء`` value, because renaming a category would break the link back to
# PharmaFly.  A new branch folder therefore needs no configuration at all.

# ---------------------------------------------------------------------------
# Section 3 -- Column contracts
# ---------------------------------------------------------------------------

#: The master's pack-size column (pieces per pack).  NOTE: this literal is
#: ``الاجزاء`` (with a leading ``ال``) and is **different** from the
#: transactional pieces column ``اجزاء`` (without it).  They are kept as
#: separate constants so the two can never be confused.
MASTER_PACK_SIZE_COLUMN = "الاجزاء"
PIECES_COLUMN = "اجزاء"
PACKS_COLUMN = "عبوات"
QUANTITY_COLUMN = "الكمية"
SKU_COLUMN = "الكود"
MASTER_SKU_COLUMN = "كود الصنف"

#: The ERP values that identify a *central* (non-branch) warehouse.
CENTRAL_WAREHOUSE_MARKERS: tuple[str, ...] = (
    "المخازن والاداره",
    "المخازن والادارة",
    "المخزن",
)

#: Values that identify the ERP's main storage location inside a branch.
MAIN_LOCATION_MARKERS: tuple[str, ...] = ("main", "main ")

# ---------------------------------------------------------------------------
# Section 4 -- File roles
# ---------------------------------------------------------------------------
# Each role declares the canonical columns, the aliases that may carry them,
# the numeric columns and whether the role is mandatory.  Roles are detected
# from the *content* of a workbook (column signature) so any branch folder
# works without renaming anything.

FILE_SPECS: dict[str, dict[str, object]] = {
    "master": {
        "label_en": "Product master data",
        "label_ar": "بيانات الأصناف الرئيسية",
        "sku": MASTER_SKU_COLUMN,
        "mandatory": True,
        "columns": [MASTER_SKU_COLUMN],
        "aliases": {
            MASTER_SKU_COLUMN: ["كود", "الكود", "كود الصنفه", "ملف بيانات الاصناف", "ملف بيانات الأصناف", "بيانات الأصناف"],
            "اسم الصنف": ["الاسم", "اسم الصنف ", "الاسم التفصيلي"],
            "فئة التصنيف": ["التصنيف", "الفئة", "فئه التصنيف"],
            "القسم": ["القسم "],
            "سعر البيع": ["السعر", "سعر البيع "],
            "سعر التكلفة": ["متوسط سعر التكلفة", "اخر سعر تكلفة", "آخر سعر تكلفة"],
            "متوسط سعر التكلفة": ["المتوسط سعر التكلفة", "متوسط سعر التكلفة "],
            "اخر سعر تكلفة": ["آخر سعر تكلفة", "اخر سعر تكلفه"],
            MASTER_PACK_SIZE_COLUMN: ["الاجزاء ", "الاجزا ء", "حجم العبوة", "Pack Size", "عدد الاجزاء"],
        },
        "optional": [
            "فئة التصنيف",
            "القسم",
            "سعر البيع",
            "سعر التكلفة",
            "متوسط سعر التكلفة",
            "اخر سعر تكلفة",
            MASTER_PACK_SIZE_COLUMN,
        ],
        "numeric": [
            "سعر البيع",
            "سعر التكلفة",
            "متوسط سعر التكلفة",
            "اخر سعر تكلفة",
            MASTER_PACK_SIZE_COLUMN,
        ],
        "blank_as_zero": [],
    },
    "shortages": {
        "label_en": "Shortage / requisition report",
        "label_ar": "تقرير الأصناف الناقصة",
        "sku": SKU_COLUMN,
        "mandatory": True,
        "columns": [SKU_COLUMN],
        "aliases": {
            SKU_COLUMN: ["كود", "كود الصنف", "الكود"],
            "الاسم": ["اسم الصنف"],
            "المطلوب": ["الكمية المطلوبة", "الطلب", "المطلوب "],
            "الموجود": ["الكمية الموجودة", "الرصيد", "رصيد الفرع"],
            "المتوسط": [
                "المتوسط الشهرى",
                "المتوسط الشهري",
                "المتوسط",
                "متوسط الاستهلاك الشهري",
            ],
            "Monthly_StdDev": [
                "الانحراف المعياري",
                "الانحراف المعيارى",
                "الانحراف المعياري الشهري",
                "التباين",
                "Variance",
                "Monthly Variance",
                "Monthly_StdDev",
                "Monthly StdDev",
            ],
        },
        "optional": [
            "الاسم",
            "المطلوب",
            "الموجود",
            "المتوسط",
            "Monthly_StdDev",
        ],
        "numeric": ["المطلوب", "الموجود", "المتوسط", "Monthly_StdDev"],
        "blank_as_zero": ["المطلوب", "الموجود", "المتوسط"],
    },
    "branch_stock": {
        "label_en": "Branch stock",
        "label_ar": "رصيد الفرع",
        "sku": SKU_COLUMN,
        "mandatory": True,
        "columns": [SKU_COLUMN, QUANTITY_COLUMN],
        "aliases": {
            SKU_COLUMN: ["كود", "كود الصنف", "الكود"],
            QUANTITY_COLUMN: ["الرصيد", "الموجود", "رصيد الفرع", "الكمية "],
            PACKS_COLUMN: ["عدد العبوات"],
            PIECES_COLUMN: ["أجزاء", "الكمية الجزئية"],
            "الفرع": ["اسم الفرع"],
            "المخزن": ["اسم المخزن"],
            "اسم الصنف": ["الاسم"],
            "فئة التصنيف": ["التصنيف"],
        },
        "optional": [
            PACKS_COLUMN,
            PIECES_COLUMN,
            "الفرع",
            "المخزن",
            "اسم الصنف",
            "فئة التصنيف",
        ],
        "numeric": [QUANTITY_COLUMN, PACKS_COLUMN, PIECES_COLUMN],
        "blank_as_zero": [PACKS_COLUMN, PIECES_COLUMN],
    },
    "warehouse_stock": {
        "label_en": "Central warehouse stock",
        "label_ar": "رصيد المخزن المركزي",
        "sku": SKU_COLUMN,
        "mandatory": False,
        "columns": [SKU_COLUMN, QUANTITY_COLUMN],
        "aliases": {
            SKU_COLUMN: ["كود", "كود الصنف", "الكود"],
            QUANTITY_COLUMN: ["الرصيد", "الموجود", "رصيد المخزن", "الكمية "],
            PACKS_COLUMN: ["عدد العبوات"],
            PIECES_COLUMN: ["أجزاء", "الكمية الجزئية"],
            "الفرع": ["اسم الفرع"],
            "المخزن": ["اسم المخزن"],
            "اسم الصنف": ["الاسم"],
            "فئة التصنيف": ["التصنيف"],
        },
        "optional": [
            PACKS_COLUMN,
            PIECES_COLUMN,
            "الفرع",
            "المخزن",
            "اسم الصنف",
            "فئة التصنيف",
        ],
        "numeric": [QUANTITY_COLUMN, PACKS_COLUMN, PIECES_COLUMN],
        "blank_as_zero": [PACKS_COLUMN, PIECES_COLUMN],
    },
    "recent_sales": {
        "label_en": "Recent branch sales",
        "label_ar": "تقرير مبيعات الفرع",
        "sku": "كود الصنف",
        "mandatory": False,
        "columns": ["كود الصنف", QUANTITY_COLUMN],
        "aliases": {
            "كود الصنف": ["كود", "الكود"],
            QUANTITY_COLUMN: ["المبيعات", "كمية المبيعات", "إجمالي المبيعات", "الكمية "],
            PACKS_COLUMN: ["عدد العبوات"],
            PIECES_COLUMN: ["أجزاء", "الكمية الجزئية"],
            "اسم الصنف": ["الاسم"],
            "مبيعات": ["نوع المبيعات", "بيان المبيعات"],
            "التاريخ": [
                "تاريخ البيع",
                "تاريخ الفاتورة",
                "تاريخ الحركة",
                "تاريخ الصرف",
            ],
        },
        "optional": [
            PACKS_COLUMN,
            PIECES_COLUMN,
            "اسم الصنف",
            "مبيعات",
            "التاريخ",
        ],
        "numeric": [QUANTITY_COLUMN, PACKS_COLUMN, PIECES_COLUMN],
        "blank_as_zero": [PACKS_COLUMN, PIECES_COLUMN],
    },
    "pending_purchases": {
        "label_en": "Pending purchases (on order)",
        "label_ar": "المشتريات تحت التوريد",
        "sku": "كود الصنف",
        "mandatory": False,
        "columns": ["كود الصنف"],
        "aliases": {
            "كود الصنف": ["كود", "الكود"],
            PACKS_COLUMN: ["عدد العبوات"],
            PIECES_COLUMN: ["أجزاء", "الكمية الجزئية"],
            "اسم الصنف": ["الاسم"],
            "من فرع": ["من فرع "],
            "الي فرع": ["الي فرع ", "إلى فرع"],
        },
        "optional": [
            PACKS_COLUMN,
            PIECES_COLUMN,
            "اسم الصنف",
            "من فرع",
            "الي فرع",
        ],
        "numeric": [PACKS_COLUMN, PIECES_COLUMN],
        "blank_as_zero": [PACKS_COLUMN, PIECES_COLUMN],
    },
    "transfers": {
        "label_en": "Inter-branch transfers",
        "label_ar": "تحويلات الفروع",
        "sku": "كود الصنف",
        "mandatory": False,
        "columns": ["كود الصنف", "العملية"],
        "aliases": {
            "كود الصنف": ["كود", "الكود"],
            "العملية": ["نوع العملية", "العمليات"],
            PACKS_COLUMN: ["عدد العبوات"],
            PIECES_COLUMN: ["أجزاء", "الكمية الجزئية"],
            "اسم الصنف": ["الاسم"],
        },
        "optional": [PACKS_COLUMN, PIECES_COLUMN, "اسم الصنف"],
        "numeric": [PACKS_COLUMN, PIECES_COLUMN],
        "blank_as_zero": [PACKS_COLUMN, PIECES_COLUMN],
    },
    "panel_sales": {
        "label_en": "Historical sales panel (branch x month)",
        "label_ar": "ملف المبيعات التاريخي (فرع × شهر)",
        "sku": "كود الصنف",
        "mandatory": False,
        "columns": [],
        "aliases": {},
        "optional": [],
        "numeric": [],
        "blank_as_zero": [],
    },
    "multi_price": {
        "label_en": "Items with more than one price",
        "label_ar": "أصناف لها أكثر من سعر",
        "sku": "كود الصنف",
        "mandatory": False,
        "columns": ["كود الصنف"],
        "aliases": {
            "كود الصنف": ["كود", "الكود"],
            "اسم الصنف": ["الاسم"],
            "سعر البيع": ["السعر"],
        },
        "optional": ["اسم الصنف", "سعر البيع"],
        "numeric": ["سعر البيع"],
        "blank_as_zero": [],
    },
    "pushing_list": {
        "label_en": "Pushing list",
        "label_ar": "قائمة الدفع",
        "sku": SKU_COLUMN,
        "mandatory": False,
        "columns": [SKU_COLUMN],
        "aliases": {
            SKU_COLUMN: ["كود", "كود الصنف", "الكود"],
            "الاسم": ["اسم الصنف"],
            "نواقص الفرع": ["نواقص"],
            "رصيد الفرع": ["الرصيد"],
        },
        "optional": ["الاسم", "نواقص الفرع", "رصيد الفرع"],
        "numeric": ["نواقص الفرع", "رصيد الفرع"],
        "blank_as_zero": [],
    },
}

#: The three files that must be present before the analysis can run.
REQUIRED_ROLES: tuple[str, ...] = ("master", "shortages", "branch_stock")

#: The seven ERP exports.  The first three are required; the rest are optional.
CORE_ROLES: tuple[str, ...] = (
    "master",
    "shortages",
    "branch_stock",
    "warehouse_stock",
    "recent_sales",
    "pending_purchases",
    "transfers",
)

#: Every uploader shown inside the optional-files expander.  The four optional
#: ERP exports come first, followed by the extra helper files.
OPTIONAL_ROLES: tuple[str, ...] = (
    "warehouse_stock",
    "recent_sales",
    "pending_purchases",
    "transfers",
    "panel_sales",
    "multi_price",
    "pushing_list",
)

UPLOAD_LABELS: dict[str, str] = {
    "master": "1. بيانات الأصناف الرئيسية",
    "shortages": "2. تقرير الأصناف الناقصة",
    "branch_stock": "3. رصيد الفرع",
    "warehouse_stock": "4. رصيد المخزن المركزي",
    "recent_sales": "5. تقرير مبيعات الفرع",
    "pending_purchases": "6. المشتريات تحت التوريد",
    "transfers": "7. تحويلات الفروع",
    "panel_sales": "ملف المبيعات التاريخي (اختياري)",
    "multi_price": "أصناف متعددة الأسعار (اختياري)",
    "pushing_list": "قائمة الدفع (اختياري)",
}

#: English labels -- used in the exception messages so a support engineer can
#: read them without changing the Arabic interface.
UPLOAD_LABELS_EN: dict[str, str] = {
    role: str(spec.get("label_en", role)) for role, spec in FILE_SPECS.items()
}

# ---------------------------------------------------------------------------
# Section 5 -- Transfer semantics
# ---------------------------------------------------------------------------
# The ERP writes exactly two movement descriptions.  ``ارسال`` is outgoing and
# ``استقبال`` is incoming -- note that ``استقبال`` contains neither
# ``ارسال`` nor ``استلام``, so the incoming token must be listed explicitly.

TRANSFER_OUT_TOKENS: tuple[str, ...] = ("ارسال", "إرسال", "صادر", "تحويل صادر")
TRANSFER_IN_TOKENS: tuple[str, ...] = ("استقبال", "استلام", "وارد", "تحويل وارد")

OPERATION_OUTGOING = "outgoing"
OPERATION_INCOMING = "incoming"
OPERATION_AMBIGUOUS = "ambiguous"
OPERATION_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Section 6 -- Business rules
# ---------------------------------------------------------------------------

#: How the effective stock position is built.
#:
#: ``out_transfers``  branch stock + pending purchases - outgoing transfers
#:                    (the rule issued by the business).
#: ``snapshot``       branch stock + pending purchases.  The branch export is a
#:                    live snapshot that is already net of the posted transfer
#:                    ledger, so subtracting the ledger again double counts.
#: ``full_net``       branch stock + pending purchases + incoming - outgoing.
STOCK_BASIS_MODES: tuple[str, ...] = ("out_transfers", "snapshot", "full_net")
DEFAULT_STOCK_BASIS = "out_transfers"

STOCK_BASIS_LABELS_AR: dict[str, str] = {
    "out_transfers": "رصيد الفرع + تحت التوريد − التحويلات الصادرة",
    "snapshot": "رصيد الفرع + تحت التوريد (لقطة حية)",
    "full_net": "رصيد الفرع + تحت التوريد + الوارد − الصادر",
}

#: Where the monthly demand comes from.
DEMAND_SOURCE_MODES: tuple[str, ...] = ("auto", "panel", "erp")
DEFAULT_DEMAND_SOURCE = "auto"

DEMAND_SOURCE_LABELS_AR: dict[str, str] = {
    "auto": "تلقائي (الأعلى من المبيعات الشهري ومتوسط النظام والمبيعات الحديثة)",
    "panel": "ملف المبيعات الشهري فقط",
    "erp": "متوسط النظام + المبيعات الحديثة",
}

#: How the order quantity is derived from the reorder point.
#:
#: ``rop``     (s, S) -- the order is placed only when the effective stock is
#:             at or below the reorder point, and it is sized to cover the
#:             review period plus the lead time.
#: ``target``  the order always covers the whole monthly demand:
#:             ``Calculated_Order = Target_Demand - Effective_Stock``.  This is
#:             the ERP's Target Level rule and it keeps an item that is only
#:             slightly below its demand visible on the order sheet.
ORDER_METHOD_MODES: tuple[str, ...] = ("rop", "target")
DEFAULT_ORDER_METHOD = "rop"

#: The ``حالة الصنف`` vocabulary (see :func:`core.supply_chain.run_pipeline`).
ITEM_STATUS_ORDER = "يحتاج طلب"
ITEM_STATUS_FULLY_COVERED = "مغطى بالكامل"
ITEM_STATUS_COVERED_LEAD_TIME = "مغطى حتى فترة التوريد"

#: Substitute form policy.
SUBSTITUTE_FORM_POLICIES: tuple[str, ...] = ("compatible", "identical", "any")
DEFAULT_SUBSTITUTE_FORM_POLICY = "compatible"

#: The days used to convert a monthly rate into a daily rate.
DAYS_PER_MONTH = 30

#: Gregorian month labels used by the dynamic sales columns.  The lookup in
#: :mod:`core.supply_chain` normalises the ERP's spelling variants (for
#: example ``اغسطس`` without a hamza), but the exported header uses the
#: standard Arabic spelling below.
ARABIC_MONTH_NAMES: dict[int, str] = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
}

#: PharmaFly builds its shortage report on a **180-day sales study** and prints
#: the resulting figure in ``المتوسط``.  The study covers six months, so the
#: monthly demand is ``المتوسط x 180 / 6`` -- that is, ``المتوسط x 30``.
PHARMAFLY_STUDY_DAYS = 180
PHARMAFLY_STUDY_MONTHS = 6
PHARMAFLY_DAILY_TO_MONTHLY = PHARMAFLY_STUDY_DAYS / PHARMAFLY_STUDY_MONTHS

#: Whether the ERP prints ``المتوسط`` as a *per-day* average.
#:
#: ``True``  -- a daily rate: it is multiplied by
#:              :data:`PHARMAFLY_DAILY_TO_MONTHLY` before it is used.
#: ``False`` -- already a monthly rate, used as it stands.
#:
#: The real exports measure as **monthly**: the shortage line of
#: ``DOLIPRANE 1000MG`` reports ``المتوسط 154``, ``الموجود 55.5`` and
#: ``المطلوب 98``, and ``154 - 55.5 = 98.5``.  The ERP's own requisition is
#: therefore ``المتوسط - الموجود``, and the column is already monthly.  Set
#: this to ``True`` only for an ERP instance that really prints a daily rate.
ERP_AVERAGE_IS_DAILY = False

#: The measured coefficient of variation of monthly demand (sigma / mean) taken
#: from a real five-month branch panel.  Kept for reference; the business now
#: prefers the conservative :data:`DEFAULT_CV_FALLBACK`.
MEASURED_CV = 0.44

#: The fallback coefficient of variation used **only** when no real standard
#: deviation can be computed from the recent sales report (or the optional
#: monthly panel).  The business standard is 25% of the ERP monthly average
#: (``المتوسط``), not 25% of the final demand.
DEFAULT_CV_FALLBACK = 0.25

#: How many of the most recent calendar months the recent sales report is
#: reduced to before the per-item standard deviation is computed.
RECENT_SIGMA_MONTHS = 3

#: A per-item sigma needs at least this many monthly observations.  With one
#: month there is no dispersion to measure, so the 25% fallback is used.
RECENT_SIGMA_MIN_MONTHS = 2

#: Number of monthly observations required before a per-item standard
#: deviation from the optional monthly panel is trusted.
MIN_SIGMA_OBSERVATIONS = 3

#: Upper bound on the share of the catalogue that may show an impossible
#: negative balance.  Beyond it the run is *flagged loudly* but never aborted
#: (the business asked for negative balances to be reported, not hidden).
IMPLAUSIBLE_NEGATIVE_ABSOLUTE_THRESHOLD = 5
IMPLAUSIBLE_NEGATIVE_RATIO_THRESHOLD = 0.01

UNUSUAL_TRANSFER_ABSOLUTE_THRESHOLD = 10
UNUSUAL_TRANSFER_MULTIPLIER = 3

#: Tolerance used when checking ``الكمية`` against the pack arithmetic.
QUANTITY_TOLERANCE = 1e-6

# ---------------------------------------------------------------------------
# Section 7 -- Export contract
# ---------------------------------------------------------------------------

FINAL_COLUMNS: list[str] = [
    "التصنيف",
    "الكود",
    "الاسم",
    "المطلوب",
    "حالة الصنف",
    "الموجود",
    "المخزن",
    "المتوسط",
    "Lead_Time",
    "ROP",
    "Demand",
    "البديل",
    "ملاحظات",
]

#: The order workbook is split into one worksheet per business family.  Excel
#: forbids ``/`` in a sheet name, so the cosmetics + medical-supplies family is
#: called ``Cosmetics & Supplies``.  ``Other`` is the safety net for the ERP's
#: placeholder categories (``xxxx``, ``ء``) and for any category a future
#: export introduces; the export never silently invents a family.
EXPORT_FAMILY_DRUGS = "Drugs"
EXPORT_FAMILY_COSMETICS = "Cosmetics & Supplies"
EXPORT_FAMILY_MEDICAL_COSMETICS = "Medical Cosmetics"
EXPORT_FAMILY_OTHER = "Other"

EXPORT_FAMILY_ORDER: tuple[str, ...] = (
    EXPORT_FAMILY_DRUGS,
    EXPORT_FAMILY_COSMETICS,
    EXPORT_FAMILY_MEDICAL_COSMETICS,
    EXPORT_FAMILY_OTHER,
)

#: Raw ``فئة التصنيف`` -> worksheet family.  This is deliberately a **business**
#: mapping, not a data cleaning step: the category itself is still copied
#: verbatim to the export; only the worksheet is chosen here.  Everything not
#: listed falls into :data:`EXPORT_FAMILY_OTHER`.
CATEGORY_FAMILY_MAP: dict[str, str] = {
    # -- pharmaceutical forms ------------------------------------------------
    "TABLETS + CAPSULES": EXPORT_FAMILY_DRUGS,
    "CREAMS&oint&gel": EXPORT_FAMILY_DRUGS,
    "SYRUPS + SUSP": EXPORT_FAMILY_DRUGS,
    "INJECTIONS": EXPORT_FAMILY_DRUGS,
    "DROPS": EXPORT_FAMILY_DRUGS,
    "SACHETS + GRANULES": EXPORT_FAMILY_DRUGS,
    "LOTIONS + Pow": EXPORT_FAMILY_DRUGS,
    "SUPPOSITORIES": EXPORT_FAMILY_DRUGS,
    "injection antibiotics": EXPORT_FAMILY_DRUGS,
    "MOUTH WASHES": EXPORT_FAMILY_DRUGS,
    "insulin": EXPORT_FAMILY_DRUGS,
    "oral inhalation": EXPORT_FAMILY_DRUGS,
    "refrigerator": EXPORT_FAMILY_DRUGS,
    "vaccine": EXPORT_FAMILY_DRUGS,
    "banned": EXPORT_FAMILY_DRUGS,
    "pseudoephedrine": EXPORT_FAMILY_DRUGS,
    "البان": EXPORT_FAMILY_DRUGS,
    "gym": EXPORT_FAMILY_DRUGS,
    "محلول وريدى": EXPORT_FAMILY_DRUGS,
    "Misused": EXPORT_FAMILY_DRUGS,
    "spray": EXPORT_FAMILY_DRUGS,
    # -- cosmetics + medical supplies ---------------------------------------
    "مستحضرات تجميل": EXPORT_FAMILY_COSMETICS,
    "مستلزمات طبيه": EXPORT_FAMILY_COSMETICS,
    "مستلزمات أطفال": EXPORT_FAMILY_COSMETICS,
    "حفاضات وورقيات": EXPORT_FAMILY_COSMETICS,
    "صبغات": EXPORT_FAMILY_COSMETICS,
    "مبيدات + منظفات": EXPORT_FAMILY_COSMETICS,
    "برفان": EXPORT_FAMILY_COSMETICS,
    # -- the ERP's dedicated medical-cosmetics family -----------------------
    "Medical Cosmetics": EXPORT_FAMILY_MEDICAL_COSMETICS,
}

#: The legacy single-sheet name, kept so older callers and tests keep working.
EXPORT_SHEET_NAME = "الطلب النهائي"

AUDIT_EXPORT_COLUMNS: list[str] = [
    "رصيد الفرع",
    "مشتريات تحت التوريد",
    "تحويلات صادرة",
    "تحويلات واردة",
]

NUMERIC_EXPORT_COLUMNS: list[str] = [
    "المطلوب",
    "الموجود",
    "المخزن",
    "المتوسط",
    "Lead_Time",
    "ROP",
    "Demand",
]

INTEGER_EXPORT_COLUMNS: list[str] = [
    "المطلوب",
    "الموجود",
    "المخزن",
    "Lead_Time",
]

#: ``المتوسط`` is the ERP's own consumption average and is frequently
#: fractional; casting it to an integer would erase it, so it keeps two
#: decimals like the other statistical columns.
FLOAT_EXPORT_COLUMNS: list[str] = ["المتوسط", "ROP", "Demand"]

EXPORT_HEADER_BACKGROUND = "#1F4E78"
EXPORT_ORDER_FILL = "#FFF2CC"
EXPORT_STOCK_FILL = "#FCE4D6"

EXCEL_CHUNK_SIZE = 5000

# ---------------------------------------------------------------------------
# Section 8 -- Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplyChainSettings:
    """Every knob the user can turn, in one immutable object.

    The object is hashable and free of Streamlit types so it can be passed
    straight into the cached pipeline.
    """

    z_score: float = 1.65
    variance_percent: float = DEFAULT_CV_FALLBACK * 100.0
    review_period_days: int = 30
    stock_basis: str = DEFAULT_STOCK_BASIS
    demand_source: str = DEFAULT_DEMAND_SOURCE
    order_method: str = DEFAULT_ORDER_METHOD
    pack_rounding: bool = True
    moq_packs: int = 1
    substitutes_enabled: bool = True
    substitute_form_policy: str = DEFAULT_SUBSTITUTE_FORM_POLICY
    substitute_require_same_pack_size: bool = False
    requested_quantity_as_floor: bool = False
    allocate_warehouse_stock: bool = True
    include_transfers: bool = True
    ignore_no_sales_rate: bool = False
    enable_cosmetics_force: bool = False
    enable_pushing_override: bool = False
    export_audit_columns: bool = False

    @property
    def coverage_days(self) -> int:
        """The configured review period in days."""
        return int(self.review_period_days)

    def replaced(self, **changes: object) -> "SupplyChainSettings":
        """Return a copy with ``changes`` applied."""
        return replace(self, **changes)  # type: ignore[arg-type]


SETTINGS_DEFAULTS: dict[str, object] = {
    "z_score": 1.65,
    "variance_percent": DEFAULT_CV_FALLBACK * 100.0,
    "review_period_days": 30,
    "stock_basis": DEFAULT_STOCK_BASIS,
    "demand_source": DEFAULT_DEMAND_SOURCE,
    "order_method": DEFAULT_ORDER_METHOD,
    "pack_rounding": True,
    "moq_packs": 1,
    "substitutes_enabled": True,
    "substitute_form_policy": DEFAULT_SUBSTITUTE_FORM_POLICY,
    "substitute_require_same_pack_size": False,
    "requested_quantity_as_floor": False,
    "allocate_warehouse_stock": True,
    "include_transfers": True,
    "ignore_no_sales_rate": False,
    "enable_cosmetics_force": False,
    "enable_pushing_override": False,
    "export_audit_columns": False,
}

# ---------------------------------------------------------------------------
# Section 9 -- Preview limits
# ---------------------------------------------------------------------------

PREVIEW_PAGE_SIZE = 100
PREVIEW_ROW_LIMIT = 500
MAX_EDITABLE_ROWS = 500

__all__ = [
    "ARABIC_WEEKDAYS_BY_PYTHON_INDEX",
    "AUDIT_EXPORT_COLUMNS",
    "BRANCH_LABELS_EN",
    "BRANCH_OPTIONS",
    "CATEGORY_FAMILY_MAP",
    "CORE_ROLES",
    "DAYS_MAP",
    "DAYS_PER_MONTH",
    "DEFAULT_CV_FALLBACK",
    "DEMAND_SOURCE_LABELS_AR",
    "DEMAND_SOURCE_MODES",
    "DEFAULT_DEMAND_SOURCE",
    "DEFAULT_ORDER_METHOD",
    "DEFAULT_STOCK_BASIS",
    "DEFAULT_SUBSTITUTE_FORM_POLICY",
    "ERP_AVERAGE_IS_DAILY",
    "EXPORT_FAMILY_COSMETICS",
    "EXPORT_FAMILY_DRUGS",
    "EXPORT_FAMILY_MEDICAL_COSMETICS",
    "EXPORT_FAMILY_ORDER",
    "EXPORT_FAMILY_OTHER",
    "EXPORT_ORDER_FILL",
    "EXPORT_SHEET_NAME",
    "EXPORT_STOCK_FILL",
    "FILE_SPECS",
    "FINAL_COLUMNS",
    "FRIDAY",
    "FRIDAY_FALLBACK_PREP",
    "IMPLAUSIBLE_NEGATIVE_ABSOLUTE_THRESHOLD",
    "IMPLAUSIBLE_NEGATIVE_RATIO_THRESHOLD",
    "ITEM_STATUS_COVERED_LEAD_TIME",
    "ITEM_STATUS_FULLY_COVERED",
    "ITEM_STATUS_ORDER",
    "MASTER_PACK_SIZE_COLUMN",
    "MEASURED_CV",
    "MIN_SIGMA_OBSERVATIONS",
    "NUMERIC_EXPORT_COLUMNS",
    "OPERATION_AMBIGUOUS",
    "OPERATION_INCOMING",
    "OPERATION_OUTGOING",
    "OPERATION_UNKNOWN",
    "ORDER_METHOD_MODES",
    "OPTIONAL_ROLES",
    "PACKS_COLUMN",
    "PHARMAFLY_DAILY_TO_MONTHLY",
    "PHARMAFLY_LEAD_TIME_DAYS",
    "PHARMAFLY_STUDY_DAYS",
    "PHARMAFLY_STUDY_MONTHS",
    "PIECES_COLUMN",
    "PREP_SCHEDULE",
    "PREP_TO_DELIVERY",
    "PREVIEW_PAGE_SIZE",
    "PREVIEW_ROW_LIMIT",
    "QUANTITY_COLUMN",
    "QUANTITY_TOLERANCE",
    "RECENT_SIGMA_MIN_MONTHS",
    "RECENT_SIGMA_MONTHS",
    "REQUIRED_ROLES",
    "SETTINGS_DEFAULTS",
    "STOCK_BASIS_LABELS_AR",
    "STOCK_BASIS_MODES",
    "SUBSTITUTE_FORM_POLICIES",
    "SupplyChainSettings",
    "UNUSUAL_TRANSFER_ABSOLUTE_THRESHOLD",
    "UNUSUAL_TRANSFER_MULTIPLIER",
    "UPLOAD_LABELS",
    "WEEKDAY_NAMES_EN",
]
COSMETIC_CATEGORIES = frozenset({'Medical Cosmetics','مستحضرات تجميل','مستلزمات طبيه','مستلزمات طبية','مستلزمات أطفال','حفاضات وورقيات','صبغات','مبيدات + منظفات','برفان'})
COSMETIC_KEYWORDS = ('cosmetic','تجميل','تجميلية','مستلزمات','حفاضات','صبغ','برفان','شامبو','منظف')

SUGGESTED_COVERAGE_DAYS = 30
SHORTAGE_COMPARISON_DAYS = 30
HISTORY_STUDY_DAYS = 90
TRANSFER_LOOKBACK_DAYS = 10
TRANSFER_COMPENSATION_MIN_BRANCH_STOCK = 3.0

FINAL_ORDER_SHEET = 'Final Order'
PUSHING_LIST_SHEET = 'Pushing List'
MULTIPLE_CARDS_SHEET = 'Multiple Cards'
FINAL_BRANCH_SALES_SHEET = 'Final Branch Sales'
COSMETICS_DISTRIBUTION_SHEET = 'Cosmetics Distribution'
NOTES_SHEET = 'Notes'
