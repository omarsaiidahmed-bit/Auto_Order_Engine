#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pharmacy Auto Order V2 — a bilingual Streamlit workspace.

The UI is intentionally thin: every calculation is delegated to ``core`` and
``app_config``.  This module owns presentation, upload orchestration, and the
session state that keeps a generated order available across reruns.
"""

from __future__ import annotations

import base64
import io
from dataclasses import replace
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from app_config import (
    BRANCH_LABELS_EN,
    BRANCH_OPTIONS,
    DEMAND_SOURCE_LABELS_AR,
    DEMAND_SOURCE_MODES,
    ORDER_METHOD_MODES,
    REQUIRED_ROLES,
    STOCK_BASIS_MODES,
    WEEKDAY_NAMES_EN,
    SupplyChainSettings,
)
from core.exporter import export_styled_excel
from core.ingestion import SalesPanel, load_and_detect, read_sales_panel
from core.schedules import (
    ARRIVAL_SCHEDULE,
    PREPARATION_SCHEDULE,
    SCHEDULE_WEEKDAYS,
    compute_schedule_cycle,
    schedule_for,
)
from core.supply_chain import PipelineResult, compute_lead_time, run_pipeline

APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "company_logo.png"
ARABIC_SOP = APP_DIR / "Auto_Order_SOP_Arabic.pdf"
ENGLISH_SOP = APP_DIR / "Auto_Order_SOP_English.pdf"
PREVIEW_ROW_LIMIT = 3_000

st.set_page_config(
    page_title="الأوتو أوردر الذكي",
    page_icon=str(LOGO_PATH) if LOGO_PATH.is_file() else "📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Language and copy
# ---------------------------------------------------------------------------
TEXT: dict[str, dict[str, str]] = {
    "ar": {
        "app_title": "الأوتو أوردر الذكي",
        "app_subtitle": "طلبية تعبئة واضحة لكل فرع",
        "language": "اللغة",
        "nav_order": "توليد الطلبية",
        "nav_schedules": "جداول الفروع",
        "nav_settings": "الإعدادات",
        "nav_help": "المساعدة والدليل",
        "navigation": "التنقل",
        "sidebar_ready": "جاهز للعمل",
        "sidebar_tagline": "سلسلة الإمداد الصيدلي",
        "sidebar_version": "الإصدار 2.0.0",
        "hero_eyebrow": "سلسلة إمداد الصيدليات · الإصدار 2.0",
        "hero_title": "طلبية واضحة. لكل فرع. وفي كل دورة.",
        "hero_subtitle": "ارفع ملفات ERP، راجع الأدلة والملاحظات، ثم نزّل طلبية جاهزة للفرع — بواجهة عربية.",
        "hero_branches": "51 فرعاً",
        "hero_files": "10 ملفات مصدر",
        "hero_langs": "عربي",
        "order_eyebrow": "01 · توليد الطلبية",
        "order_title": "أنشئ طلبية الفرع",
        "order_subtitle": "اختر الفرع والتاريخ، ثم ارفع الملفات الأساسية. الملفات الاختيارية تحسّن الدقة ولا تمنع التشغيل.",
        "context_title": "بيانات الطلبية",
        "context_subtitle": "الفرع والتاريخ يحددان الدورة التشغيلية؛ جدولا التجهيز والوصول منفصلان دائماً.",
        "branch": "الفرع",
        "order_date": "تاريخ الطلب",
        "next_prep": "يوم التجهيز القادم",
        "next_arrival": "أول وصول بعده",
        "schedule_separate": "التجهيز والوصول جدولان مستقلان ولا يُدمجان.",
        "uploads_title": "ملفات المصدر",
        "uploads_eyebrow": "إلزامي + اختياري",
        "uploads_subtitle": "ثلاثة ملفات إلزامية، وسبعة اختيارية. يتم التعرف على نوع الملف من أعمدته لا من اسمه.",
        "required": "إلزامي",
        "optional": "اختياري",
        "upload_master": "بيانات الأصناف الرئيسية",
        "upload_master_sub": "كود الصنف والاسم والتصنيف ومتوسط الطلب.",
        "upload_shortages": "تقرير النواقص",
        "upload_shortages_sub": "ما ينقص الفرع فعلياً اليوم.",
        "upload_branch_stock": "رصيد الفرع",
        "upload_branch_stock_sub": "الرصيد الموجود حالياً في الفرع المحدد.",
        "upload_warehouse": "رصيد المخزن المركزي",
        "upload_warehouse_sub": "رصيد مركزي متاح للتخصيص إن وجد.",
        "upload_recent_sales": "مبيعات الفرع الحديثة",
        "upload_recent_sales_sub": "حركة بيع حديثة أو ملخص شهري.",
        "upload_pending": "المشتريات تحت التوريد",
        "upload_pending_sub": "كميات تم طلبها ولم تُستلم بعد.",
        "upload_transfers": "تحويلات الفروع",
        "upload_transfers_sub": "كميات محوّلة خارج الفرع.",
        "upload_panel": "لوحة المبيعات التاريخية",
        "upload_panel_sub": "لوحة عريضة للطلب التاريخي حسب الفرع.",
        "upload_multi": "أصناف متعددة الأسعار",
        "upload_multi_sub": "أصناف لها أكثر من كارته أو سعر.",
        "upload_pushing": "Pushing List",
        "upload_pushing_sub": "أصناف أولوية يُراد دفعها للفرع.",
        "optional_expander": "الملفات الاختيارية · 7 ملفات",
        "optional_hint": "أضف ما يتوفر لديك. كل ملف إضافي يزيد دقة الطلب، لكنه لا يعطّل التوليد.",
        "generate": "توليد الطلبية",
        "generate_hint": "ارفع الملفات الأساسية الثلاثة لتفعيل زر التوليد.",
        "reading_files": "جاري قراءة الملفات…",
        "calculating": "جاري حساب الطلب والبدائل…",
        "generated": "تم توليد الطلبية",
        "processing_error": "خطأ في المعالجة",
        "technical_details": "تفاصيل تقنية",
        "missing_files": "الملفات الأساسية التالية لم تُقرأ بشكل صحيح: {files}",
        "panel_missing": "لوحة المبيعات لا تحتوي على فرع «{branch}» — تم الاعتماد على متوسط ERP والمبيعات الحديثة.",
        "role_master": "بيانات الأصناف الرئيسية",
        "role_shortages": "تقرير النواقص",
        "role_branch_stock": "رصيد الفرع",
        "result_success": "تم توليد الطلبية بنجاح — {count} صنفاً · الفرع: {branch}",
        "metric_total": "إجمالي الأصناف",
        "metric_required": "أصناف مطلوبة",
        "metric_warehouse": "تحميل من المخزن",
        "metric_categories": "تصنيفات",
        "run_notes": "ملاحظات التشغيل",
        "preview_title": "معاينة الطلبية النهائية",
        "preview_eyebrow": "مراجعة",
        "preview_columns": "أعمدة مختارة من أصل 21 عموداً في ملف Excel النهائي.",
        "legend_push": "Pushing List",
        "legend_multi": "أكثر من كارته",
        "legend_transfer": "تحويلات",
        "legend_warehouse": "تحميل من المخزن",
        "showing_preview": "عرض {shown} صنفاً مطلوباً من إجمالي {total} صنفاً — الملف النهائي يحتوي على كل الأصناف.",
        "preview_limit": "يتم عرض أول {limit} سطر فقط لتسريع الصفحة؛ كل الأصناف موجودة في ملف Excel.",
        "no_required": "لا توجد أصناف مطلوب شراؤها في هذه الطلبية.",
        "excel_error": "تعذر إنشاء ملف Excel المنسق: {error}",
        "download": "تنزيل ملف الطلبية النهائية",
        "download_caption": "ملف Excel منسق، مقسّم حسب عائلات التصنيف.",
        "item_search_label": "ابحث بالكود أو اسم الصنف",
        "item_search_placeholder": "اكتب كوداً أو جزءاً من الاسم…",
        "item_search_match": "{count} صنفاً يطابق البحث.",
        "item_search_none": "لا يوجد صنف يطابق البحث.",
        "download_missing": "تنزيل تقرير الأصناف المستبعدة",
        "missing_caption": "{count} صنفاً في تقرير الأصناف المستبعدة.",
        "schedules_eyebrow": "02 · جداول الفروع",
        "schedules_title": "اعرف دورة كل فرع",
        "schedules_subtitle": "ابحث عن فرع واعرض أيام التجهيز والوصول. الجدولان مستقلان تماماً: يوم التجهيز لا يُشتق منه يوم الوصول.",
        "schedules_rule": "التجهيز والوصول لا يُدمجان في جدول واحد. كل جدول يُقرأ ويُدار منفصلاً.",
        "search_label": "ابحث عن فرع",
        "search_placeholder": "اكتب اسم الفرع…",
        "search_match": "{count} فرعاً يطابق البحث.",
        "search_none": "لا يوجد فرع يطابق البحث.",
        "tab_prep": "جدول التجهيز",
        "tab_arrival": "جدول الوصول",
        "prep_caption": "أيام تجهيز الطلبيات حسب الفرع.",
        "arrival_caption": "أيام وصول الطلبيات حسب الفرع.",
        "branch_count": "{count} فرعاً",
        "total_branches": "الفروع",
        "no_branches": "لا توجد فروع",
        "table_view": "عرض جدولي",
        "table_day": "اليوم",
        "table_branches": "الفروع",
        "table_count": "العدد",
        "branch_detail": "تفاصيل الفرع",
        "branch_detail_hint": "اختر أي فرع لعرض دورته التشغيلية كاملة.",
        "prep_days": "أيام التجهيز",
        "arrival_days": "أيام الوصول",
        "nearest_prep": "أقرب يوم تجهيز",
        "first_arrival": "أول وصول بعده",
        "none": "لا يوجد",
        "schedule_note": "ملاحظة الجدول",
        "separation_note": "الوصول المعروض هو أول يوم وصول مجدول بعد التجهيز، وليس اسماً بديلاً ليوم التجهيز.",
        "settings_eyebrow": "03 · الإعدادات",
        "settings_title": "اضبط سياسة التخطيط",
        "settings_subtitle": "هذه القيم تُستخدم في التوليد القادم. التعديلات لا تغيّر الطلبية المحفوظة حتى تضغط حفظ.",
        "planning_policy": "سياسة التخطيط",
        "z_label": "معامل الأمان Z",
        "z_toggle": "تفعيل معامل الأمان Z",
        "z_toggle_help": "عند الإيقاف: مخزون الأمان = 0، والهدف = متوسط شيت النواقص.",
        "rop_toggle": "تفعيل نقطة إعادة الطلب (ROP)",
        "rop_toggle_help": "عند الإيقاف: لا تُضاف نقطة إعادة الطلب إلى هدف الطلب.",
        "z_help": "كلما زادت Z زاد مخزون الأمان.",
        "z_disabled": "معامل الأمان Z ونسبة التباين غير مفعّلين — مخزون الأمان = 0.",
        "review_label": "فترة التغطية (أيام)",
        "review_help": "عدد أيام التغطية المستخدمة في معادلة الهدف.",
        "variance_label": "نسبة التباين",
        "variance_help": "نسبة التباين المستخدمة عند غياب انحراف موثوق.",
        "stock_basis": "أساس الرصيد",
        "demand_source": "مصدر الطلب",
        "order_method": "طريقة الحساب",
        "pack_rounding": "تقريب لعدد عبوات كامل",
        "substitutes_enabled": "تفعيل البدائل",
        "allocate_warehouse": "خصم رصيد المخزن المركزي",
        "include_transfers": "تضمين التحويلات",
        "ignore_no_sales": "تجاهل الأصناف التي ليس لها معدل بيع",
        "save_settings": "حفظ الإعدادات",
        "saved_settings": "تم حفظ الإعدادات، وستُستخدم في التوليد القادم.",
        "active_settings": "الإعدادات النشطة",
        "active_z": "معامل الأمان Z",
        "active_rop": "نقطة إعادة الطلب",
        "active_review": "التغطية",
        "active_variance": "التباين",
        "active_basis": "الأساس",
        "active_demand": "المصدر",
        "active_method": "الطريقة",
        "active_substitutes": "البدائل",
        "active_transfers": "التحويلات",
        "active_ignore_no_sales": "تجاهل بلا معدل",
        "active_warehouse": "المخزن المركزي",
        "enabled": "مفعلة",
        "disabled": "معطلة",
        "deducted": "مخصوم",
        "not_deducted": "غير مخصوم",
        "settings_note": "الإعدادات محفوظة في جلسة التطبيق الحالية. راجع دليل SOP لشرح كل معامل.",
        "sop_eyebrow": "04 · المساعدة",
        "sop_title": "دليل التشغيل الكامل",
        "sop_subtitle": "نسختان مفصلتان بالأبيض والأسود: عربية من اليمين إلى اليسار، وإنجليزية من اليسار إلى اليمين. كل حقل وقاعدة مشروحة.",
        "sop_ar_title": "دليل التشغيل العربي",
        "sop_ar_desc": "دليل عربي كامل يشرح الواجهة، الملفات، المعادلات، وكل عمود في الطلبية.",
        "sop_en_title": "الدليل الإنجليزي",
        "sop_en_desc": "دليل إنجليزي يشرح الواجهة والملفات والمعادلات وكل عمود في الطلبية.",
        "sop_download_ar": "تحميل الدليل العربي",
        "sop_download_en": "تحميل الدليل الإنجليزي",
        "sop_size": "{size} · PDF",
        "sop_missing": "الملف غير موجود في مجلد التطبيق.",
        "sop_quick_title": "ابدأ من هنا",
        "sop_quick_sub": "ثلاث خطوات قصيرة قبل فتح الدليل الكامل.",
        "sop_quick_1_title": "قبل التشغيل",
        "sop_quick_1": "راجع الإعدادات المسموح بها، وثبّت الفرع، وجهّز الملفات الثلاثة الأساسية.",
        "sop_quick_2_title": "أثناء التوليد",
        "sop_quick_2": "ارفع الملفات، راجع معاينة الأصناف والملاحظات، ثم نزّل ملف Excel واحفظه باسم الفرع والتاريخ.",
        "sop_quick_3_title": "عند وجود مشكلة",
        "sop_quick_3": "راجع تقرير النواقص وأعمدة الملف، ثم استخدم قسم استكشاف الأخطاء في دليل التشغيل.",
        "sop_covers_title": "ماذا يغطي الدليل؟",
        "sop_covers_sub": "مرجع كامل للحقول والقواعد والألوان.",
        "sop_covers_1": "كل حقل في الملفات العشرة وكيف يُكتشف نوع الملف.",
        "sop_covers_2": "معادلات نقطة إعادة الطلب ومخزون الأمان وزمن التوريد والبدائل.",
        "sop_covers_3": "الأعمدة الثلاثة عشر، الألوان، قائمة التحقق، وأرشيف التدقيق.",
        "footer_note": "Auto Order V2.0 · واجهة عربية · الحسابات في core/",
    },
    "en": {
        "app_title": "Pharmacy Auto Order",
        "app_subtitle": "A clear replenishment order for every branch",
        "language": "Language / اللغة",
        "nav_order": "Order generation",
        "nav_schedules": "Branch schedules",
        "nav_settings": "Settings",
        "nav_help": "SOP & help",
        "navigation": "Workspace",
        "sidebar_ready": "Ready to work",
        "sidebar_tagline": "Pharmacy supply chain",
        "sidebar_version": "Version 2.0.0",
        "hero_eyebrow": "PHARMACY SUPPLY CHAIN · VERSION 2.0",
        "hero_title": "A clear order. Every branch. Every cycle.",
        "hero_subtitle": "Upload the ERP exports, review the evidence and notes, then download a branch-ready order — in Arabic or English.",
        "hero_branches": "51 branches",
        "hero_files": "10 source files",
        "hero_langs": "Arabic + English",
        "order_eyebrow": "01 · ORDER GENERATION",
        "order_title": "Generate a branch order",
        "order_subtitle": "Choose the branch and date, then upload the three required files. Optional files improve accuracy but never block a run.",
        "context_title": "Order context",
        "context_subtitle": "The branch and date drive the operational cycle; preparation and arrival are always separate schedules.",
        "branch": "Branch",
        "order_date": "Order date",
        "next_prep": "Next preparation",
        "next_arrival": "First arrival after it",
        "schedule_separate": "Preparation and arrival are independent schedules and are never merged.",
        "uploads_title": "Source files",
        "uploads_eyebrow": "Required + optional",
        "uploads_subtitle": "Three required files and seven optional files. The role is detected from the columns, not the file name.",
        "required": "Required",
        "optional": "Optional",
        "upload_master": "Master item catalogue",
        "upload_master_sub": "Item code, name, category and ERP demand.",
        "upload_shortages": "Shortage report",
        "upload_shortages_sub": "What the branch is short of today.",
        "upload_branch_stock": "Branch stock",
        "upload_branch_stock_sub": "Current on-hand balance for the selected branch.",
        "upload_warehouse": "Central warehouse stock",
        "upload_warehouse_sub": "Optional central stock available for allocation.",
        "upload_recent_sales": "Recent branch sales",
        "upload_recent_sales_sub": "Recent transaction or monthly sales.",
        "upload_pending": "Purchases on order",
        "upload_pending_sub": "Quantities ordered but not yet received.",
        "upload_transfers": "Branch transfers",
        "upload_transfers_sub": "Quantities transferred out of the branch.",
        "upload_panel": "Historical sales panel",
        "upload_panel_sub": "Optional wide historical demand panel by branch.",
        "upload_multi": "Multi-price items",
        "upload_multi_sub": "Items with more than one card or price.",
        "upload_pushing": "Pushing List",
        "upload_pushing_sub": "Priority items to push to the branch.",
        "optional_expander": "Optional files · 7 files",
        "optional_hint": "Add whatever you have. Each extra file improves accuracy but never blocks generation.",
        "generate": "Generate order",
        "generate_hint": "Upload the three required files to enable generation.",
        "reading_files": "Reading files…",
        "calculating": "Calculating demand and substitutes…",
        "generated": "Order generated",
        "processing_error": "Processing error",
        "technical_details": "Technical details",
        "missing_files": "These required files could not be read: {files}",
        "panel_missing": "The sales panel has no block for “{branch}” — ERP average and recent sales were used instead.",
        "role_master": "master catalogue",
        "role_shortages": "shortage report",
        "role_branch_stock": "branch stock",
        "result_success": "Order generated — {count:,} items · Branch: {branch}",
        "metric_total": "Items in export",
        "metric_required": "Items required",
        "metric_warehouse": "Warehouse loading",
        "metric_categories": "Categories",
        "run_notes": "Run notes",
        "preview_title": "Final order preview",
        "preview_eyebrow": "Review",
        "preview_columns": "Selected key columns; the Excel file carries the full 21-column contract.",
        "legend_push": "Pushing List",
        "legend_multi": "Multiple cards",
        "legend_transfer": "Transfers",
        "legend_warehouse": "Warehouse loading",
        "showing_preview": "Showing {shown} required items out of {total} total items — the final file contains every item.",
        "preview_limit": "Only the first {limit} rows are shown for speed; every item is in the Excel file.",
        "no_required": "No items need ordering in this run.",
        "excel_error": "Could not build the styled Excel file: {error}",
        "download": "Download Auto_Order_Final.xlsx",
        "download_caption": "A styled workbook split by category family.",
        "item_search_label": "Search by item code or name",
        "item_search_placeholder": "Type an item code or part of its name…",
        "item_search_match": "{count} items match your search.",
        "item_search_none": "No item matches your search.",
        "download_missing": "Download missing-items report (CSV)",
        "missing_caption": "{count} items in the missing-items report.",
        "schedules_eyebrow": "02 · BRANCH SCHEDULES",
        "schedules_title": "Know every branch cycle",
        "schedules_subtitle": "Search for a branch and inspect its preparation and arrival days. The two schedules are independent: preparation never implies an arrival day.",
        "schedules_rule": "Preparation and arrival are not merged. Each schedule is read and managed separately.",
        "search_label": "Find a branch",
        "search_placeholder": "Type a branch name in Arabic or English…",
        "search_match": "{count} branches match your search.",
        "search_none": "No branch matches your search.",
        "tab_prep": "Preparation schedule",
        "tab_arrival": "Arrival schedule",
        "prep_caption": "Order preparation days by branch.",
        "arrival_caption": "Order arrival days by branch.",
        "branch_count": "{count} branches",
        "total_branches": "Branches",
        "no_branches": "No branches",
        "table_view": "Table view",
        "table_day": "Day",
        "table_branches": "Branches",
        "table_count": "Count",
        "branch_detail": "Branch detail",
        "branch_detail_hint": "Choose any branch to see its full operational cycle.",
        "prep_days": "Preparation days",
        "arrival_days": "Arrival days",
        "nearest_prep": "Nearest preparation",
        "first_arrival": "First arrival after it",
        "none": "None",
        "schedule_note": "Schedule note",
        "separation_note": "The arrival shown is the first scheduled arrival after preparation, not another name for the preparation day.",
        "settings_eyebrow": "03 · SETTINGS",
        "settings_title": "Tune the planning policy",
        "settings_subtitle": "These values apply to the next run. Editing them does not change a saved order until you save.",
        "planning_policy": "Planning policy",
        "z_label": "Safety factor Z",
        "z_toggle": "Enable safety factor Z",
        "z_toggle_help": "When off: safety stock = 0 and the target is the shortage-sheet average.",
        "rop_toggle": "Enable reorder point (ROP)",
        "rop_toggle_help": "When off: the reorder point is not added to the target demand.",
        "z_help": "Higher Z means more safety stock.",
        "z_disabled": "Safety factor Z and variance are disabled — safety stock = 0.",
        "review_label": "Coverage days",
        "review_help": "Days of coverage used by the target-level formula.",
        "variance_label": "Variance percent",
        "variance_help": "Fallback dispersion when no reliable sigma is available.",
        "stock_basis": "Stock basis",
        "demand_source": "Demand source",
        "order_method": "Calculation method",
        "pack_rounding": "Round to whole packs",
        "substitutes_enabled": "Enable substitutes",
        "allocate_warehouse": "Deduct central warehouse stock",
        "include_transfers": "Include Transfers",
        "ignore_no_sales": "Ignore items with no sales rate",
        "save_settings": "Save settings",
        "saved_settings": "Settings saved; they will be used on the next run.",
        "active_settings": "Active settings",
        "active_z": "Z",
        "active_rop": "Reorder point",
        "active_review": "Coverage",
        "active_variance": "Variance",
        "active_basis": "Basis",
        "active_demand": "Source",
        "active_method": "Method",
        "active_substitutes": "Substitutes",
        "active_transfers": "Transfers",
        "active_ignore_no_sales": "Ignore no-sales",
        "active_warehouse": "Warehouse",
        "enabled": "enabled",
        "disabled": "disabled",
        "deducted": "deducted",
        "not_deducted": "not deducted",
        "settings_note": "Settings live in the current app session. See the SOP for the meaning of every parameter.",
        "sop_eyebrow": "04 · HELP",
        "sop_title": "The complete operating guide",
        "sop_subtitle": "Two detailed black-and-white editions: Arabic RTL and English LTR. Every field and rule is explained.",
        "sop_ar_title": "Arabic operating guide",
        "sop_ar_desc": "A complete RTL guide covering the interface, inputs, formulas and every output column.",
        "sop_en_title": "English operating guide",
        "sop_en_desc": "A complete LTR guide covering the interface, inputs, formulas and every output column.",
        "sop_download_ar": "Download Arabic guide",
        "sop_download_en": "Download English guide",
        "sop_size": "{size} · PDF",
        "sop_missing": "The file is missing from the application folder.",
        "sop_quick_title": "Start here",
        "sop_quick_sub": "Three short steps before opening the full guide.",
        "sop_quick_1_title": "Before the run",
        "sop_quick_1": "Review the allowed settings, fix the branch, and prepare the three core files.",
        "sop_quick_2_title": "During the run",
        "sop_quick_2": "Upload the files, review the item preview and notes, then download and archive the Excel file by branch and date.",
        "sop_quick_3_title": "If something fails",
        "sop_quick_3": "Check the shortage report and source columns, then use the troubleshooting chapter of the SOP.",
        "sop_covers_title": "What the guide covers",
        "sop_covers_sub": "A complete reference for fields, rules and colours.",
        "sop_covers_1": "Every field in the ten input files and how each role is detected.",
        "sop_covers_2": "ROP, safety stock, Lead_Time, substitutes and the full demand logic.",
        "sop_covers_3": "The thirteen output columns, colours, checklists and audit archive.",
        "footer_note": "Auto Order V2.0 · bilingual interface · calculations live in core/",
    },
}

STOCK_BASIS_LABELS = {
    "ar": {
        "out_transfers": "فرع + تحت التوريد − تحويلات صادرة",
        "snapshot": "فرع + تحت التوريد (لقطة حية)",
        "full_net": "فرع + تحت التوريد + وارد − صادر",
    },
    "en": {
        "out_transfers": "Branch + on-order − outgoing transfers",
        "snapshot": "Branch + on-order (live snapshot)",
        "full_net": "Branch + on-order + inbound − outbound",
    },
}
DEMAND_SOURCE_LABELS = {
    "ar": DEMAND_SOURCE_LABELS_AR,
    "en": {
        "shortage": "Shortage sheet average",
        "auto": "Automatic",
        "panel": "Historical sales panel",
        "erp": "ERP average",
    },
}
ORDER_METHOD_LABELS = {
    "ar": {"rop": "نقطة إعادة الطلب", "target": "المستوى المستهدف"},
    "en": {"rop": "ROP (reorder point)", "target": "Target level"},
}

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&display=swap');

* {
    font-family: 'Cairo', sans-serif !important;
}

/* Streamlit icons are Material ligatures; keep their own font. */
[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] span,
[data-testid="stExpanderToggleIcon"],
[data-testid="stExpanderToggleIcon"] span,
span.material-symbols-rounded,
span.material-symbols-outlined,
span[class*="material-symbols"],
span[class*="material-icons"],
.material-icons {
    font-family: "Material Symbols Rounded", "Material Icons", sans-serif !important;
}

:root {
    --ao-bg: #F4F7FB;
    --ao-surface: #FFFFFF;
    --ao-surface-2: #EEF4FA;
    --ao-primary: #4A7BA7;
    --ao-primary-deep: #315F85;
    --ao-primary-soft: #E4EFF8;
    --ao-text: #1F2937;
    --ao-muted: #64748B;
    --ao-border: #DCE8F2;
    --ao-border-strong: #C3D7E7;
    --ao-success: #2F6B5F;
    --ao-radius: 18px;
    --ao-shadow: 0 12px 32px rgba(47, 86, 120, 0.08);
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
    background: var(--ao-bg) !important;
    color: var(--ao-text);
}

.stApp {
    background:
        radial-gradient(circle at 8% 0%, rgba(184, 214, 236, 0.32), transparent 28rem),
        radial-gradient(circle at 94% 4%, rgba(213, 229, 242, 0.45), transparent 24rem),
        var(--ao-bg) !important;
}

[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stToolbar"] {
    display: none !important;
}

[data-testid="stStatusWidget"] {
    display: none !important;
}

.block-container {
    max-width: 1320px;
    padding-top: 1.35rem;
    padding-bottom: 3.2rem;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Cairo', sans-serif !important;
    color: var(--ao-text) !important;
    letter-spacing: 0 !important;
}

p, li, [data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] p {
    color: var(--ao-text);
}

[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
    color: var(--ao-muted) !important;
}

a { color: var(--ao-primary-deep) !important; }

hr { border-color: var(--ao-border) !important; }

/* Sidebar --------------------------------------------------------------- */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #EEF5FB 0%, #F8FBFE 100%) !important;
    border-inline-end: 1px solid var(--ao-border);
}

[data-testid="stSidebar"] .block-container {
    padding: 1.15rem 0.9rem 2rem;
}

.ao-side-brand {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.35rem 0.25rem 0.9rem;
}

.ao-side-brand img {
    width: 46px;
    height: 46px;
    object-fit: contain;
    border-radius: 13px;
    background: #FFFFFF;
    border: 1px solid var(--ao-border);
    padding: 4px;
    box-shadow: 0 5px 14px rgba(47, 86, 120, 0.10);
}

.ao-side-brand .ao-side-mark {
    width: 46px;
    height: 46px;
    display: grid;
    place-items: center;
    border-radius: 13px;
    background: var(--ao-primary);
    color: #FFFFFF;
    font-weight: 800;
    letter-spacing: 0;
}

.ao-side-brand strong {
    display: block;
    font-size: 0.98rem;
    line-height: 1.35;
    color: var(--ao-text);
}

.ao-side-brand span {
    display: block;
    font-size: 0.72rem;
    color: var(--ao-muted);
    line-height: 1.55;
}

.ao-side-label {
    margin: 0.25rem 0.2rem 0.35rem;
    color: var(--ao-muted);
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}

.ao-side-divider {
    height: 1px;
    margin: 0.65rem 0.2rem 0.85rem;
    background: var(--ao-border);
}

.ao-side-status {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin: 1.15rem 0.2rem 0.35rem;
    padding: 0.55rem 0.7rem;
    border: 1px solid var(--ao-border);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.72);
    color: var(--ao-muted);
    font-size: 0.75rem;
}

.ao-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #5A9A82;
    box-shadow: 0 0 0 4px rgba(90, 154, 130, 0.14);
}

.ao-side-footer {
    margin: 0.9rem 0.2rem 0;
    color: var(--ao-muted);
    font-size: 0.7rem;
    line-height: 1.7;
}

/* Navigation buttons */
[data-testid="stSidebar"] .stButton > button {
    justify-content: flex-start !important;
    text-align: start !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    color: #3E5E75 !important;
    min-height: 2.45rem !important;
    padding: 0.48rem 0.65rem !important;
    border-radius: 11px !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
    box-shadow: none !important;
}

[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255, 255, 255, 0.72) !important;
    border-color: var(--ao-border) !important;
    color: var(--ao-primary-deep) !important;
}

[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] {
    background: #FFFFFF !important;
    border-color: var(--ao-border-strong) !important;
    color: var(--ao-primary-deep) !important;
    box-shadow: 0 5px 15px rgba(47, 86, 120, 0.08) !important;
}

.st-key-language_choice [role="radiogroup"] {
    gap: 0.25rem;
}

.st-key-language_choice [role="radiogroup"] label {
    background: rgba(255, 255, 255, 0.62);
    border: 1px solid var(--ao-border);
    border-radius: 9px;
    padding: 0.35rem 0.55rem;
    font-size: 0.78rem;
}

.st-key-language_choice [role="radiogroup"] label:has(input:checked) {
    background: var(--ao-primary);
    border-color: var(--ao-primary);
}

.st-key-language_choice [role="radiogroup"] label:has(input:checked) p {
    color: #FFFFFF !important;
}

/* Hero and page headings ------------------------------------------------ */
.ao-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: clamp(1.2rem, 4vw, 3.5rem);
    padding: clamp(1.45rem, 3.2vw, 2.7rem);
    margin: 0.25rem 0 1.5rem;
    border: 1px solid var(--ao-border);
    border-radius: clamp(20px, 3vw, 28px);
    background:
        radial-gradient(circle at 5% 0%, rgba(255, 255, 255, 0.95), transparent 38%),
        linear-gradient(135deg, #E8F2FA 0%, #F6FAFE 52%, #EAF2F9 100%);
    box-shadow: 0 22px 55px rgba(47, 86, 120, 0.12);
    overflow: hidden;
}

.ao-hero-copy { flex: 1 1 620px; min-width: 0; }

.ao-eyebrow {
    display: inline-block;
    color: var(--ao-primary-deep);
    font-size: 0.73rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.ao-hero h1 {
    margin: 0.55rem 0 0.5rem;
    font-size: clamp(1.7rem, 3.4vw, 2.7rem);
    line-height: 1.35;
    font-weight: 800;
    color: #17364D !important;
    text-wrap: balance;
}

.ao-hero p {
    max-width: 820px;
    margin: 0;
    color: #4B6377;
    font-size: clamp(0.9rem, 1.25vw, 1.02rem);
    line-height: 1.95;
}

.ao-hero-badges, .ao-legend, .ao-chip-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
}

.ao-hero-badges { margin-top: 1.15rem; }

.ao-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.34rem 0.7rem;
    border: 1px solid #D2E3F0;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.78);
    color: #40617A;
    font-size: 0.76rem;
    font-weight: 600;
}

.ao-hero-mark {
    flex: 0 0 auto;
    display: grid;
    place-items: center;
    width: clamp(132px, 15vw, 178px);
    height: clamp(132px, 15vw, 178px);
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.78);
    border: 1px solid #D2E3F0;
    box-shadow: 0 18px 36px rgba(47, 86, 120, 0.12);
}

.ao-hero-mark img {
    width: 78%;
    height: 78%;
    object-fit: contain;
}

.ao-hero-mark .ao-mark-fallback {
    color: var(--ao-primary-deep);
    font-size: 2.2rem;
    font-weight: 800;
}

.ao-page-head {
    padding: 1.15rem 1.35rem 1.2rem;
    margin: 0 0 1.15rem;
    background: rgba(255, 255, 255, 0.9);
    border: 1px solid var(--ao-border);
    border-radius: var(--ao-radius);
    box-shadow: var(--ao-shadow);
}

.ao-page-head h1 {
    margin: 0.25rem 0 0.35rem;
    font-size: clamp(1.45rem, 2.4vw, 2rem);
    line-height: 1.4;
}

.ao-page-head p {
    max-width: 950px;
    margin: 0;
    color: var(--ao-muted);
    line-height: 1.8;
}

.ao-section-head {
    margin: 1.3rem 0 0.65rem;
}

.ao-section-head h2 {
    margin: 0.2rem 0 0.22rem;
    font-size: 1.25rem;
    line-height: 1.45;
}

.ao-section-head p {
    margin: 0;
    color: var(--ao-muted);
    font-size: 0.87rem;
    line-height: 1.75;
}

/* Cards, containers and forms ------------------------------------------ */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(255, 255, 255, 0.96) !important;
    border: 1px solid var(--ao-border) !important;
    border-radius: var(--ao-radius) !important;
    box-shadow: var(--ao-shadow);
}

[data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 0.15rem 0.2rem;
}

[data-testid="stForm"] {
    border: 0 !important;
    background: transparent !important;
}

.ao-mini-card {
    padding: 0.8rem 0.9rem;
    border: 1px solid var(--ao-border);
    border-radius: 14px;
    background: #F8FBFE;
}

.ao-mini-card .ao-mini-label {
    display: block;
    margin-bottom: 0.2rem;
    color: var(--ao-muted);
    font-size: 0.72rem;
    font-weight: 600;
}

.ao-mini-card .ao-mini-value {
    display: block;
    color: #234B68;
    font-size: 0.93rem;
    font-weight: 700;
    line-height: 1.6;
}

.ao-upload-head {
    display: flex;
    align-items: flex-start;
    gap: 0.55rem;
    min-height: 2.8rem;
}

.ao-step {
    flex: 0 0 auto;
    display: inline-grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border: 1px solid #C9DEEB;
    border-radius: 8px;
    background: var(--ao-primary-soft);
    color: var(--ao-primary-deep);
    font-size: 0.7rem;
    font-weight: 800;
}

.ao-upload-title {
    color: #24455D;
    font-size: 0.87rem;
    font-weight: 700;
    line-height: 1.55;
}

.ao-upload-sub {
    margin-top: 0.12rem;
    color: var(--ao-muted);
    font-size: 0.72rem;
    line-height: 1.55;
}

.ao-optional-head {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    min-height: 2.4rem;
    margin-bottom: 0.1rem;
}

.ao-optional-head .ao-step {
    width: 23px;
    height: 23px;
    border-radius: 7px;
}

/* File uploader: style only. Never set height, overflow or pointer-events;
   the native button and drop target must stay fully clickable. */
[data-testid="stFileUploader"] {
    margin-top: 0.35rem;
}

[data-testid="stFileUploaderDropzone"] {
    min-height: 8.2rem;
    padding: 0.85rem 0.8rem !important;
    background: #F8FBFE !important;
    border: 1.4px dashed #B9D2E3 !important;
    border-radius: 13px !important;
    transition: border-color 0.15s ease, background 0.15s ease;
}

[data-testid="stFileUploaderDropzone"]:hover {
    background: #F2F9FE !important;
    border-color: var(--ao-primary) !important;
}

[data-testid="stFileUploaderDropzone"] button {
    background: var(--ao-primary) !important;
    color: #FFFFFF !important;
    border: 0 !important;
    border-radius: 9px !important;
    padding: 0.34rem 0.72rem !important;
    font-size: 0.75rem !important;
    opacity: 1 !important;
    visibility: visible !important;
    pointer-events: auto !important;
    cursor: pointer !important;
}

[data-testid="stFileUploaderDropzone"] button:hover {
    background: var(--ao-primary-deep) !important;
}

[data-testid="stFileUploaderDropzone"] button:focus-visible {
    outline: 2px solid #8FB8D9 !important;
    outline-offset: 2px;
}

[data-testid="stFileUploaderDropzoneInstructions"] {
    color: var(--ao-muted) !important;
    font-size: 0.72rem !important;
    line-height: 1.5 !important;
}

[data-testid="stFileUploaderDropzone"] input[type="file"] {
    cursor: pointer !important;
}

/* Buttons */
.stButton > button,
.stDownloadButton > button {
    border-radius: 11px !important;
    min-height: 2.65rem;
    font-weight: 700 !important;
}

.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: var(--ao-primary) !important;
    border-color: var(--ao-primary) !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 18px rgba(74, 123, 167, 0.20);
}

.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: var(--ao-primary-deep) !important;
    border-color: var(--ao-primary-deep) !important;
}

.stButton > button:disabled {
    background: #E6EEF5 !important;
    border-color: #D6E3ED !important;
    color: #91A4B4 !important;
    box-shadow: none !important;
}

.stDownloadButton > button {
    background: #FFFFFF !important;
    border: 1px solid #B9D2E3 !important;
    color: var(--ao-primary-deep) !important;
}

.stDownloadButton > button:hover {
    background: var(--ao-primary-soft) !important;
    border-color: var(--ao-primary) !important;
    color: var(--ao-primary-deep) !important;
}

/* Metrics */
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.96);
    border: 1px solid var(--ao-border);
    border-radius: 15px;
    box-shadow: var(--ao-shadow);
    padding: 0.9rem 1rem;
}

[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
    color: var(--ao-muted) !important;
    font-size: 0.74rem !important;
}

[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div {
    color: #234B68 !important;
    font-size: 1.35rem !important;
    font-weight: 800 !important;
}

input[type="checkbox"], input[type="radio"] {
    accent-color: var(--ao-primary) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.3rem;
    padding: 0.3rem;
    border: 1px solid var(--ao-border);
    border-radius: 13px;
    background: #EAF2F8;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 9px;
    padding: 0.45rem 0.85rem;
    color: #587187;
    font-weight: 600;
}

.stTabs [aria-selected="true"] {
    background: #FFFFFF !important;
    color: var(--ao-primary-deep) !important;
    box-shadow: 0 4px 12px rgba(47, 86, 120, 0.10);
}

/* Expander and alerts */
[data-testid="stExpander"] {
    border: 1px solid var(--ao-border) !important;
    border-radius: 14px !important;
    background: rgba(255, 255, 255, 0.9) !important;
    overflow: hidden;
}

[data-testid="stExpander"] summary {
    color: #31536B;
    font-weight: 700;
}

[data-testid="stAlert"] {
    border-radius: 13px;
    border: 1px solid var(--ao-border);
}

/* Dataframe */
[data-testid="stDataFrame"] {
    border: 1px solid var(--ao-border);
    border-radius: 14px;
    overflow: hidden;
    background: #FFFFFF;
    box-shadow: var(--ao-shadow);
}

/* Legend */
.ao-legend {
    margin: 0.35rem 0 0.75rem;
    gap: 0.75rem;
    color: #50697D;
    font-size: 0.76rem;
}

.ao-legend span {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    white-space: nowrap;
}

.ao-swatch {
    display: inline-block;
    width: 11px;
    height: 11px;
    border: 1px solid rgba(31, 41, 55, 0.14);
    border-radius: 3px;
}

/* Branch schedules */
.ao-day-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 0.8rem;
    margin: 0.45rem 0 1.2rem;
}

.ao-day-card {
    padding: 0.9rem 0.95rem;
    border: 1px solid var(--ao-border);
    border-radius: 15px;
    background: rgba(255, 255, 255, 0.96);
    box-shadow: 0 8px 20px rgba(47, 86, 120, 0.06);
}

.ao-day-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.55rem;
    padding-bottom: 0.45rem;
    border-bottom: 1px solid #EAF1F7;
}

.ao-day-name {
    color: #24455D;
    font-size: 0.9rem;
    font-weight: 800;
}

.ao-day-count {
    color: var(--ao-muted);
    font-size: 0.7rem;
    white-space: nowrap;
}

.ao-chip-row { gap: 0.25rem; }

.ao-branch-chip {
    display: inline-flex;
    align-items: center;
    margin: 0.12rem 0;
    padding: 0.18rem 0.5rem;
    border: 1px solid #D3E5F1;
    border-radius: 999px;
    background: #F4F9FD;
    color: #31536B;
    font-size: 0.75rem;
    line-height: 1.65;
    overflow-wrap: anywhere;
}

.ao-empty {
    color: #8A9BAA;
    font-size: 0.78rem;
}

.ao-search-note {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    padding: 0.7rem 0.85rem;
    margin: 0.25rem 0 0.55rem;
    border: 1px solid #D4E6F2;
    border-radius: 12px;
    background: #F5FAFE;
    color: #3F6178;
    font-size: 0.8rem;
}

.ao-branch-banner {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.55rem;
    padding: 0.7rem 0.85rem;
    margin: 0.25rem 0 0.8rem;
    border: 1px solid var(--ao-border);
    border-radius: 13px;
    background: #F7FBFE;
}

.ao-branch-banner strong { color: #234B68; font-size: 1.02rem; }
.ao-branch-banner span { color: var(--ao-muted); font-size: 0.78rem; }

/* Settings chips and SOP cards */
.ao-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 0.3rem;
    padding: 0.38rem 0.65rem;
    border: 1px solid var(--ao-border);
    border-radius: 10px;
    background: #F8FBFE;
    color: #456176;
    font-size: 0.76rem;
}

.ao-chip b { color: #234B68; }

.ao-pdf-badge {
    display: inline-grid;
    place-items: center;
    width: 42px;
    height: 42px;
    border-radius: 11px;
    background: #E9F3FA;
    border: 1px solid #CDE1EF;
    color: var(--ao-primary-deep);
    font-size: 0.68rem;
    font-weight: 800;
}

.ao-sop-card-head {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    margin-bottom: 0.55rem;
}

.ao-sop-card-head strong {
    display: block;
    color: #234B68;
    font-size: 1rem;
}

.ao-sop-card-head span {
    display: block;
    color: var(--ao-muted);
    font-size: 0.72rem;
}

.ao-footer {
    margin-top: 2rem;
    padding-top: 0.85rem;
    border-top: 1px solid var(--ao-border);
    color: var(--ao-muted);
    font-size: 0.72rem;
    line-height: 1.7;
}

@media (max-width: 760px) {
    .ao-hero {
        display: block;
        padding: 1.35rem 1.05rem;
    }
    .ao-hero-mark {
        display: none;
    }
    .ao-hero h1 {
        font-size: 1.6rem;
    }
    .block-container {
        padding-top: 0.8rem;
    }
}

/* =======================================================================
   Neon dark theme (visual layer only -- no calculation lives here)
   ======================================================================= */
:root {
    --ao-bg: #1a1a2e;
    --ao-surface: #16213e;
    --ao-surface-2: #121a31;
    --ao-primary: #9d4edd;
    --ao-primary-deep: #7b2cbf;
    --ao-primary-soft: #2a1a4a;
    --ao-text: #e0e0e0;
    --ao-muted: #a7a9be;
    --ao-border: rgba(157, 78, 221, 0.38);
    --ao-border-strong: #9d4edd;
    --ao-success: #4ade80;
    --ao-radius: 18px;
    --ao-shadow: 0 0 18px rgba(157, 78, 221, 0.28);
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
    background-color: var(--ao-bg) !important;
    color: var(--ao-text) !important;
}

.stApp {
    background:
        radial-gradient(circle at 8% 0%, rgba(157, 78, 221, 0.22), transparent 30rem),
        radial-gradient(circle at 94% 4%, rgba(79, 70, 229, 0.18), transparent 26rem),
        var(--ao-bg) !important;
}

[data-testid="stHeader"] {
    background: transparent !important;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #16213e 0%, #1a1a2e 100%) !important;
    border-inline-end: 1px solid rgba(157, 78, 221, 0.45) !important;
}

h1, h2, h3, h4, h5, h6,
p, li, label, [data-testid="stMarkdownContainer"],
[data-testid="stWidgetLabel"] p {
    color: var(--ao-text) !important;
}

[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
    color: var(--ao-muted) !important;
}

a { color: #c77dff !important; }
hr { border-color: rgba(157, 78, 221, 0.35) !important; }

/* Metric cards: neon glow ------------------------------------------------ */
[data-testid="stMetric"] {
    background: linear-gradient(160deg, #16213e 0%, #1a1a2e 100%) !important;
    border: 1px solid #9d4edd !important;
    border-radius: 18px !important;
    box-shadow:
        0 0 10px rgba(157, 78, 221, 0.65),
        0 0 26px rgba(157, 78, 221, 0.35),
        inset 0 0 16px rgba(157, 78, 221, 0.14) !important;
    padding: 1rem 1.1rem !important;
}

[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
    color: #c9b8e8 !important;
    font-size: 0.76rem !important;
    letter-spacing: 0.02em;
}

[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div {
    color: #f1e6ff !important;
    font-size: 1.45rem !important;
    font-weight: 800 !important;
    text-shadow: 0 0 10px rgba(199, 125, 255, 0.75);
}

/* Buttons: rounded neon hover -------------------------------------------- */
.stButton > button,
.stDownloadButton > button {
    border-radius: 14px !important;
    border: 1px solid rgba(157, 78, 221, 0.75) !important;
    background: #16213e !important;
    color: #e0e0e0 !important;
    font-weight: 700 !important;
    transition: all 0.18s ease !important;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    border-color: #c77dff !important;
    color: #ffffff !important;
    box-shadow:
        0 0 12px rgba(157, 78, 221, 0.85),
        0 0 28px rgba(157, 78, 221, 0.45) !important;
    transform: translateY(-1px);
}

.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #7b2cbf, #9d4edd) !important;
    border-color: #c77dff !important;
    color: #ffffff !important;
    box-shadow: 0 0 14px rgba(157, 78, 221, 0.65) !important;
}

.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #9d4edd, #c77dff) !important;
    border-color: #e0b3ff !important;
    box-shadow:
        0 0 16px rgba(199, 125, 255, 0.9),
        0 0 34px rgba(157, 78, 221, 0.55) !important;
}

.stButton > button:disabled {
    background: #111827 !important;
    border-color: #2e2e5a !important;
    color: #6b7280 !important;
    box-shadow: none !important;
}

.stDownloadButton > button {
    background: linear-gradient(135deg, #16213e, #241b44) !important;
    border-color: rgba(157, 78, 221, 0.85) !important;
    color: #e9d5ff !important;
}

/* File uploader: rounded neon dropzone ----------------------------------- */
[data-testid="stFileUploaderDropzone"] {
    background: rgba(22, 33, 62, 0.92) !important;
    border: 2px dashed rgba(157, 78, 221, 0.75) !important;
    border-radius: 20px !important;
    transition: all 0.2s ease !important;
}

[data-testid="stFileUploaderDropzone"]:hover {
    border-color: #c77dff !important;
    box-shadow:
        0 0 14px rgba(157, 78, 221, 0.8),
        inset 0 0 20px rgba(157, 78, 221, 0.18) !important;
}

[data-testid="stFileUploaderDropzone"] button {
    background: linear-gradient(135deg, #7b2cbf, #9d4edd) !important;
    border: 0 !important;
    border-radius: 12px !important;
    color: #ffffff !important;
    box-shadow: 0 0 10px rgba(157, 78, 221, 0.6) !important;
}

[data-testid="stFileUploaderDropzone"] button:hover {
    background: linear-gradient(135deg, #9d4edd, #c77dff) !important;
    box-shadow: 0 0 16px rgba(199, 125, 255, 0.9) !important;
}

[data-testid="stFileUploaderDropzoneInstructions"] {
    color: var(--ao-muted) !important;
}

/* Inputs ---------------------------------------------------------------- */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
[data-baseweb="select"] > div,
[data-baseweb="input"] {
    background: #16213e !important;
    color: var(--ao-text) !important;
    border-color: rgba(157, 78, 221, 0.55) !important;
    border-radius: 12px !important;
}

.stTextInput input:focus,
.stNumberInput input:focus,
.stTextArea textarea:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: #c77dff !important;
    box-shadow:
        0 0 0 1px #9d4edd,
        0 0 12px rgba(157, 78, 221, 0.55) !important;
}

input[type="checkbox"], input[type="radio"] {
    accent-color: var(--ao-primary) !important;
}

/* Tabs, expander, alerts, dataframe ------------------------------------- */
.stTabs [data-baseweb="tab-list"] {
    background: #121a31 !important;
    border-color: rgba(157, 78, 221, 0.45) !important;
}

.stTabs [data-baseweb="tab"] {
    color: #b9a8d9 !important;
    border-radius: 10px !important;
}

.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #2a1a4a, #16213e) !important;
    color: #f1e6ff !important;
    box-shadow: 0 0 10px rgba(157, 78, 221, 0.55) !important;
}

[data-testid="stExpander"] {
    background: #16213e !important;
    border-color: rgba(157, 78, 221, 0.45) !important;
}

[data-testid="stExpander"] summary {
    color: #e0c8ff !important;
}

[data-testid="stAlert"] {
    background: #16213e !important;
    border-color: rgba(157, 78, 221, 0.5) !important;
    color: var(--ao-text) !important;
}

[data-testid="stDataFrame"] {
    background: #16213e !important;
    border-color: rgba(157, 78, 221, 0.55) !important;
    box-shadow: 0 0 14px rgba(157, 78, 221, 0.25) !important;
}

[data-testid="stDataFrame"] * {
    color: var(--ao-text);
}

/* Existing light cards and chips ---------------------------------------- */
.ao-hero, .ao-page-head, .ao-day-card, .ao-mini-card,
.ao-optional-head, .ao-upload-head {
    background: linear-gradient(160deg, #16213e, #1a1a2e) !important;
    border-color: rgba(157, 78, 221, 0.45) !important;
    color: var(--ao-text) !important;
}

.ao-hero h1, .ao-sop-card-head strong,
.ao-day-name, .ao-mini-card strong {
    color: #f1e6ff !important;
}

.ao-swatch {
    border-color: rgba(255, 255, 255, 0.25) !important;
}

.ao-footer {
    border-top-color: rgba(157, 78, 221, 0.35) !important;
    color: var(--ao-muted) !important;
}

.ao-side-brand img {
    background: #16213e !important;
    border-color: rgba(157, 78, 221, 0.45) !important;
}

.ao-search-note, .ao-upload-sub, .ao-day-count {
    color: var(--ao-muted) !important;
}

.ao-branch-chip {
    background: #241b44 !important;
    border-color: rgba(157, 78, 221, 0.55) !important;
    color: #e0c8ff !important;
}

.ao-branch-banner {
    background: linear-gradient(135deg, #241b44, #16213e) !important;
    border-color: rgba(157, 78, 221, 0.55) !important;
}

.ao-branch-banner h2, .ao-branch-banner strong {
    color: #f1e6ff !important;
}

.ao-eyebrow { color: #c77dff !important; }

.stMarkdown code {
    background: #241b44 !important;
    color: #e9d5ff !important;
}
</style>
"""

RTL_CSS = """
html, body, .stApp, [data-testid="stSidebar"] {
    direction: rtl;
}
.ao-hero, .ao-page-head, .ao-section-head, .ao-day-card, .ao-branch-banner,
.ao-mini-card, .ao-upload-head, .ao-optional-head, .ao-legend,
.ao-search-note, .ao-sop-card-head, .ao-footer, .ao-upload-sub {
    text-align: right;
}
.ao-hero-badges, .ao-legend, .ao-chip-row { justify-content: flex-start; }
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] p {
    text-align: start;
}
.ao-eyebrow { letter-spacing: 0; }
.st-key-language_choice [role="radiogroup"] label {
    text-align: right;
}
[data-testid="stFileUploaderDropzone"] button {
    font-size: 0 !important;
}
[data-testid="stFileUploaderDropzone"] button > div {
    display: none !important;
}
[data-testid="stFileUploaderDropzone"] button::after {
    content: "اختيار ملف";
    font-family: 'Cairo', sans-serif !important;
    font-size: 0.75rem;
    font-weight: 700;
}
"""

LTR_CSS = """
html, body, .stApp, [data-testid="stSidebar"] {
    direction: ltr;
}
.ao-hero, .ao-page-head, .ao-section-head, .ao-day-card, .ao-branch-banner,
.ao-mini-card, .ao-upload-head, .ao-optional-head, .ao-legend,
.ao-search-note, .ao-sop-card-head, .ao-footer, .ao-upload-sub {
    text-align: left;
}
.ao-hero-badges, .ao-legend, .ao-chip-row { justify-content: flex-start; }
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] p {
    text-align: start;
}
[data-testid="stFileUploaderDropzone"] button {
    font-size: 0 !important;
}
[data-testid="stFileUploaderDropzone"] button > div {
    display: none !important;
}
[data-testid="stFileUploaderDropzone"] button::after {
    content: "Browse files";
    font-family: 'Cairo', sans-serif !important;
    font-size: 0.75rem;
    font-weight: 700;
}
"""


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def lang() -> str:
    """The interface is Arabic-only."""
    return "ar"


def tr(key: str, **values) -> str:
    """Return the Arabic UI text for a key."""
    text = TEXT["ar"].get(key) or key
    return text.format(**values) if values else text


def direction() -> str:
    return "rtl" if lang() == "ar" else "ltr"


def weekday_label(day: str) -> str:
    if lang() == "en":
        return WEEKDAY_NAMES_EN.get(day, day)
    return day


def branch_label(branch: str) -> str:
    if lang() == "en":
        return BRANCH_LABELS_EN.get(branch, branch)
    return branch


def role_label(role: str) -> str:
    return tr(f"role_{role}")


def mode_label(kind: str, value: str) -> str:
    tables = {
        "stock": STOCK_BASIS_LABELS,
        "demand": DEMAND_SOURCE_LABELS,
        "method": ORDER_METHOD_LABELS,
    }
    return tables[kind].get(lang(), tables[kind]["ar"]).get(value, value)


def branch_choice_label(branch: str) -> str:
    """Arabic branch label for selectboxes."""
    return branch


BRANCH_CHOICES = [branch_choice_label(branch) for branch in BRANCH_OPTIONS]
BRANCH_BY_CHOICE = dict(zip(BRANCH_CHOICES, BRANCH_OPTIONS))

STOCK_CHOICES = [
    STOCK_BASIS_LABELS["ar"][value] for value in STOCK_BASIS_MODES
]
STOCK_BY_CHOICE = dict(zip(STOCK_CHOICES, STOCK_BASIS_MODES))
DEMAND_CHOICES = [
    DEMAND_SOURCE_LABELS["ar"][value] for value in DEMAND_SOURCE_MODES
]
DEMAND_BY_CHOICE = dict(zip(DEMAND_CHOICES, DEMAND_SOURCE_MODES))

for _key, _default in (
    ("result_final", None),
    ("result_diagnostics", None),
    ("result_messages", []),
    ("result_context", {}),
    ("result_highlights", {}),
    ("result_bytes", None),
    ("settings", SupplyChainSettings()),
    ("language", "ar"),
    ("nav_page", "order"),
    ("order_branch_choice", BRANCH_CHOICES[0]),
    ("order_date", date.today()),
    ("schedule_branch_choice", BRANCH_CHOICES[0]),
):
    st.session_state.setdefault(_key, _default)


def date_label(weekday: str, value: date | None) -> str:
    if value is None:
        return "—"
    return f"{weekday_label(weekday)} · {value:%Y-%m-%d}"


def inject_css() -> None:
    direction_css = RTL_CSS if lang() == "ar" else LTR_CSS
    st.markdown(BASE_CSS.replace("</style>", direction_css + "</style>"), unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=2)
def _logo_data_uri(path: str, modified_ns: int) -> str:
    candidate = Path(path)
    if modified_ns <= 0 or not candidate.is_file():
        return ""
    return base64.b64encode(candidate.read_bytes()).decode("ascii")


@st.cache_data(show_spinner=False, max_entries=4)
def _pdf_bytes(path: str, modified_ns: int) -> bytes:
    candidate = Path(path)
    if modified_ns <= 0 or not candidate.is_file():
        return b""
    return candidate.read_bytes()


def _file_stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return 0, 0
    return stat.st_mtime_ns, stat.st_size


def logo_html() -> str:
    stamp, _ = _file_stamp(LOGO_PATH)
    uri = _logo_data_uri(str(LOGO_PATH), stamp)
    if uri:
        return f'<img src="data:image/png;base64,{uri}" alt="Auto Order">'
    return '<span class="ao-side-mark">AO</span>'


def hero_html() -> str:
    stamp, _ = _file_stamp(LOGO_PATH)
    uri = _logo_data_uri(str(LOGO_PATH), stamp)
    mark = (
        f'<img src="data:image/png;base64,{uri}" alt="{escape(tr("app_title"))}">'
        if uri else '<span class="ao-mark-fallback">AO</span>'
    )
    return f"""
    <section class="ao-hero" dir="{direction()}">
      <div class="ao-hero-copy">
        <span class="ao-eyebrow">{escape(tr("hero_eyebrow"))}</span>
        <h1>{escape(tr("hero_title"))}</h1>
        <p>{escape(tr("hero_subtitle"))}</p>
        <div class="ao-hero-badges">
          <span class="ao-badge">{escape(tr("hero_branches"))}</span>
          <span class="ao-badge">{escape(tr("hero_files"))}</span>
          <span class="ao-badge">{escape(tr("hero_langs"))}</span>
        </div>
      </div>
      <div class="ao-hero-mark">{mark}</div>
    </section>
    """


def page_head(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""<section class="ao-page-head" dir="{direction()}">
          <span class="ao-eyebrow">{escape(eyebrow)}</span>
          <h1>{escape(title)}</h1>
          <p>{escape(subtitle)}</p>
        </section>""",
        unsafe_allow_html=True,
    )


def section_head(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""<div class="ao-section-head" dir="{direction()}">
          <span class="ao-eyebrow">{escape(eyebrow)}</span>
          <h2>{escape(title)}</h2>
          <p>{escape(subtitle)}</p>
        </div>""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Backend adapters (kept from the working V2 interface)
# ---------------------------------------------------------------------------
class MissingInputs(Exception):
    """Raised internally when a required upload cannot be used."""


@st.cache_data(show_spinner=False, max_entries=64)
def _read_table(payload: bytes, filename: str) -> tuple[str, pd.DataFrame]:
    return load_and_detect(payload, filename)


@st.cache_data(show_spinner=False, max_entries=8)
def _read_panel(payload: bytes, filename: str) -> SalesPanel:
    return read_sales_panel(payload, filename)


def _payload(uploaded) -> tuple[bytes, str]:
    if uploaded is None:
        return b"", ""
    uploaded.seek(0)
    return uploaded.getvalue(), getattr(uploaded, "name", "upload.xlsx")


def load_uploads(uploads: dict) -> tuple[dict[str, pd.DataFrame], SalesPanel | None, list[str]]:
    """Convert Streamlit uploads to DataFrames for the backend."""
    data_by_role: dict[str, pd.DataFrame] = {}
    panel: SalesPanel | None = None
    problems: list[str] = []

    for role, uploaded in uploads.items():
        payload, filename = _payload(uploaded)
        if not payload:
            continue
        try:
            # The UI uploader key is ``panel`` (see the 08 uploader below).
            # ``panel_sales`` is the backend role name used by older callers;
            # accept both so the historical panel is parsed by the panel
            # reader instead of being rejected by load_and_detect().
            if role in {"panel", "panel_sales"}:
                panel = _read_panel(payload, filename)
                continue
            detected, frame = _read_table(payload, filename)
            data_by_role[detected] = frame
        except Exception as error:  # surfaced to the user
            problems.append(f"{filename}: {error}")

    return data_by_role, panel, problems


def _resolve_panel_branch(panel: SalesPanel | None, branch: str) -> str | None:
    if panel is None:
        return None
    branches = panel.branches()
    if branch in branches:
        return branch
    try:
        from core.schedules import canonical_branch

        target = canonical_branch(branch)
        for name in branches:
            if canonical_branch(name) == target:
                return name
    except Exception:
        pass
    return None


def _normalise_code(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _uploaded_codes(frame: pd.DataFrame | None, candidates: tuple[str, ...]) -> set[str]:
    if frame is None or frame.empty:
        return set()
    for column in candidates:
        if column in frame.columns:
            return {
                code
                for code in (_normalise_code(value) for value in frame[column].dropna())
                if code
            }
    return set()


def _branch_matches(branch: str, query: str) -> bool:
    if not query:
        return True
    needle = query.strip().casefold()
    haystack = f"{branch} {BRANCH_LABELS_EN.get(branch, '')}".casefold()
    return needle in haystack


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        f"""<div class="ao-side-brand">
          {logo_html()}
          <div><strong>{escape(tr("app_title"))}</strong>
          <span>{escape(tr("sidebar_tagline"))} · V2.0</span></div>
        </div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ao-side-divider"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="ao-side-label">{escape(tr("navigation"))}</div>', unsafe_allow_html=True)
    page = st.session_state.get("nav_page", "order")
    nav_items = [
        ("order", "nav_order", "01"),
        ("schedules", "nav_schedules", "02"),
        ("settings", "nav_settings", "03"),
        ("help", "nav_help", "04"),
    ]

    def _navigate(page_key: str) -> None:
        st.session_state.nav_page = page_key

    for nav_key, label_key, number in nav_items:
        st.button(
            f"{number}  {tr(label_key)}",
            key=f"nav_{nav_key}",
            use_container_width=True,
            type="primary" if page == nav_key else "secondary",
            on_click=_navigate,
            args=(nav_key,),
        )

    st.markdown(
        f'<div class="ao-side-status"><span class="ao-dot"></span>'
        f'{escape(tr("sidebar_ready"))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="ao-side-footer">{escape(tr("sidebar_version"))}<br>'
        f'{escape(tr("sidebar_tagline"))}</div>',
        unsafe_allow_html=True,
    )


# The language radio is rendered before this point, so the stylesheet always
# sees the language the user just selected in the same rerun.
inject_css()


# ---------------------------------------------------------------------------
# Order generation page
# ---------------------------------------------------------------------------
def upload_head(number: str, title: str, subtitle: str, *, optional: bool = False) -> None:
    st.markdown(
        f"""<div class="{'ao-optional-head' if optional else 'ao-upload-head'}">
          <span class="ao-step">{escape(number)}</span>
          <div><div class="ao-upload-title">{escape(title)}</div>
          <div class="ao-upload-sub">{escape(subtitle)}</div></div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_order_page() -> None:
    st.markdown(hero_html(), unsafe_allow_html=True)
    section_head(tr("order_eyebrow"), tr("order_title"), tr("order_subtitle"))

    with st.container(border=True):
        st.markdown(
            f"""<div class="ao-section-head" dir="{direction()}">
              <h2>{escape(tr("context_title"))}</h2>
              <p>{escape(tr("context_subtitle"))}</p>
            </div>""",
            unsafe_allow_html=True,
        )
        c_branch, c_date = st.columns([1.25, 1])
        with c_branch:
            branch_choice = st.selectbox(
                tr("branch"),
                BRANCH_CHOICES,
                key="order_branch_choice",
            )
            selected_branch = BRANCH_BY_CHOICE[branch_choice]
        with c_date:
            order_date = st.date_input(tr("order_date"), key="order_date")

        cycle = compute_schedule_cycle(selected_branch, order_date)
        p_col, a_col = st.columns(2)
        with p_col:
            st.markdown(
                f"""<div class="ao-mini-card"><span class="ao-mini-label">{escape(tr("next_prep"))}</span>
                <span class="ao-mini-value">{escape(date_label(cycle.preparation_weekday, cycle.preparation_date))}</span></div>""",
                unsafe_allow_html=True,
            )
        with a_col:
            st.markdown(
                f"""<div class="ao-mini-card"><span class="ao-mini-label">{escape(tr("next_arrival"))}</span>
                <span class="ao-mini-value">{escape(date_label(cycle.arrival_weekday, cycle.arrival_date))}</span></div>""",
                unsafe_allow_html=True,
            )
        st.caption(tr("schedule_separate"))

    section_head(tr("uploads_eyebrow"), tr("uploads_title"), tr("uploads_subtitle"))

    specs = [
        ("master", "01", "upload_master", "upload_master_sub", True, ["xlsx", "xls", "csv"]),
        ("short", "02", "upload_shortages", "upload_shortages_sub", True, ["xlsx", "xls", "csv"]),
        ("bstock", "03", "upload_branch_stock", "upload_branch_stock_sub", True, ["xlsx", "xls", "csv"]),
        ("wstock", "04", "upload_warehouse", "upload_warehouse_sub", False, ["xlsx", "xls", "csv"]),
        ("rsales", "05", "upload_recent_sales", "upload_recent_sales_sub", False, ["xlsx", "xls", "csv"]),
        ("ppur", "06", "upload_pending", "upload_pending_sub", False, ["xlsx", "xls", "csv"]),
        ("trans", "07", "upload_transfers", "upload_transfers_sub", False, ["xlsx", "xls", "csv"]),
        ("panel", "08", "upload_panel", "upload_panel_sub", False, ["xlsx", "xls"]),
        ("mprice", "09", "upload_multi", "upload_multi_sub", False, ["xlsx", "xls", "csv"]),
        ("push", "10", "upload_pushing", "upload_pushing_sub", False, ["xlsx", "xls", "csv"]),
    ]

    uploaded: dict[str, object] = {}
    required_specs = [spec for spec in specs if spec[4]]
    optional_specs = [spec for spec in specs if not spec[4]]

    # The uploader widget keys are UI names; the pipeline role names differ.
    # Keep the mapping explicit so the button reflects the three required inputs
    # (master, shortage report, branch stock) rather than the backend roles
    # ``master`` / ``shortages`` / ``branch_stock``.
    required_upload_keys = ("master", "short", "bstock")

    columns = st.columns(3, gap="medium")
    for column, spec in zip(columns, required_specs):
        key, number, title_key, subtitle_key, _, types = spec
        with column:
            with st.container(border=True):
                upload_head(number, tr(title_key), tr(subtitle_key))
                uploaded[key] = st.file_uploader(
                    tr(title_key),
                    type=types,
                    key=key,
                    label_visibility="collapsed",
                    help=tr(subtitle_key),
                )

    with st.expander(tr("optional_expander"), expanded=False):
        st.caption(tr("optional_hint"))
        optional_columns = st.columns(2, gap="medium")
        for index, spec in enumerate(optional_specs):
            key, number, title_key, subtitle_key, _, types = spec
            with optional_columns[index % 2]:
                upload_head(number, tr(title_key), tr(subtitle_key), optional=True)
                uploaded[key] = st.file_uploader(
                    tr(title_key),
                    type=types,
                    key=key,
                    label_visibility="collapsed",
                    help=tr(subtitle_key),
                )

    required_ok = all(uploaded.get(key) is not None for key in required_upload_keys)
    if not required_ok:
        st.caption(tr("generate_hint"))

    if st.button(
        f"▶  {tr('generate')}",
        type="primary",
        use_container_width=True,
        disabled=not required_ok,
        key="generate_order",
    ):
        st.session_state.result_final = None
        st.session_state.result_diagnostics = None
        st.session_state.result_messages = []
        st.session_state.result_context = {}
        st.session_state.result_highlights = {}
        st.session_state.result_bytes = None
        st.session_state.result_missing = None

        progress = st.progress(0.0, text=tr("reading_files"))
        try:
            data_by_role, panel, problems = load_uploads(uploaded)
            for problem in problems:
                st.warning(problem)

            missing = [role for role in REQUIRED_ROLES if role not in data_by_role]
            if missing:
                progress.empty()
                separator = "، " if lang() == "ar" else ", "
                st.error(tr("missing_files", files=separator.join(role_label(role) for role in missing)))
                raise MissingInputs()

            progress.progress(0.35, text=tr("calculating"))
            panel_branch = _resolve_panel_branch(panel, selected_branch)
            panel_block = panel.block(panel_branch) if panel_branch else None
            if panel is not None and panel_branch is None:
                st.warning(tr("panel_missing", branch=branch_label(selected_branch)))

            settings = st.session_state.get("settings") or SupplyChainSettings()
            result = run_pipeline(
                data_by_role,
                settings=settings,
                order_date=order_date,
                branch=panel_branch or selected_branch,
                panel_block=panel_block,
            )

            final_df = result.final
            st.session_state.result_final = final_df
            st.session_state.result_diagnostics = result.diagnostics
            st.session_state.result_messages = list(result.run_messages)
            st.session_state.result_missing = result.missing_items
            st.session_state.result_context = {
                "branch": panel_branch or selected_branch,
                "order_date": order_date,
                "total": len(final_df),
            }
            diagnostics = result.diagnostics
            warehouse_codes: set[str] = set()
            transfer_codes: set[str] = set()
            if diagnostics is not None and not diagnostics.empty and "الكود" in diagnostics.columns:
                diagnostics_codes = diagnostics["الكود"].map(_normalise_code)
                if "Warehouse_Loading" in diagnostics.columns:
                    warehouse_codes = set(
                        diagnostics_codes[
                            diagnostics["Warehouse_Loading"].fillna(False).astype(bool)
                        ]
                    )
                if "Is_Transfer" in diagnostics.columns:
                    transfer_codes = set(
                        diagnostics_codes[
                            diagnostics["Is_Transfer"].fillna(False).astype(bool)
                        ]
                    )
            st.session_state.result_highlights = {
                "pushing": _uploaded_codes(data_by_role.get("pushing_list"), ("الكود", "كود الصنف")),
                "multi": _uploaded_codes(data_by_role.get("multi_price"), ("كود الصنف", "الكود")),
                "transfer": transfer_codes or _uploaded_codes(data_by_role.get("transfers"), ("كود الصنف", "الكود")),
                "warehouse": warehouse_codes,
            }
            progress.progress(1.0, text=tr("generated"))
        except MissingInputs:
            progress.empty()
        except Exception as error:  # noqa: BLE001 - shown in the UI
            progress.empty()
            st.error(f"{tr('processing_error')}: {error}")
            with st.expander(tr("technical_details")):
                import traceback

                st.code(traceback.format_exc())

    final_df = st.session_state.get("result_final")
    if final_df is None or final_df.empty:
        if final_df is not None:
            st.info(tr("no_required"))
        return

    context = st.session_state.get("result_context") or {}
    branch_name = context.get("branch") or selected_branch
    st.success(tr("result_success", count=len(final_df), branch=branch_label(branch_name)))

    required_series = pd.to_numeric(final_df.get("المطلوب", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    notes_series = final_df.get("ملاحظات", pd.Series("", index=final_df.index)).astype(str)
    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric(tr("metric_total"), f"{len(final_df):,}")
    metric_2.metric(tr("metric_required"), f"{int((required_series > 0).sum()):,}")
    metric_3.metric(tr("metric_warehouse"), f"{int(notes_series.str.contains('المخزن').sum()):,}")
    metric_4.metric(tr("metric_categories"), f"{final_df.get('التصنيف', pd.Series(dtype=str)).nunique():,}")

    messages = st.session_state.get("result_messages") or []
    if messages:
        with st.expander(tr("run_notes")):
            for message in messages[:20]:
                st.write(f"• {message}")

    section_head(tr("preview_eyebrow"), tr("preview_title"), tr("preview_columns"))

    sales_columns = [
        column for column in final_df.columns if str(column).startswith("مبيعات ")
    ]
    display_columns = [
        ("الكود", "الكود"),
        ("التصنيف", "التصنيف"),
        ("الاسم", "الاسم"),
        ("المطلوب", "المطلوب"),
        ("القيمة المالية للطلب", "القيمة المالية للطلب"),
        ("الموجود في الفرع", "الموجود في الفرع"),
        ("الموجود في المخزن", "الموجود في المخزن"),
        ("التحويلات", "التحويلات"),
        *[(column, column) for column in sales_columns],
        ("المتوسط", "المتوسط"),
        ("ROP", "نقطة إعادة الطلب"),
        ("Substitutes", "Substitutes"),
        ("Lead_Time", "زمن التوريد"),
        ("تاريخ الوصول المتوقع", "تاريخ الوصول المتوقع"),
        ("تغطية المخزون (أيام)", "تغطية المخزون (أيام)"),
        ("سبب الطلب", "سبب الطلب"),
        ("ملاحظات", "ملاحظات"),
    ]
    available = [(source, target) for source, target in display_columns if source in final_df.columns]
    preview = final_df[[source for source, _ in available]].rename(
        columns={source: target for source, target in available}
    )
    required_column = "المطلوب"
    code_column = "الكود"
    notes_column = "ملاحظات"

    if required_column in preview.columns:
        required_mask = pd.to_numeric(preview[required_column], errors="coerce").fillna(0.0) > 0
        reason_column = "سبب الطلب"
        if reason_column in preview.columns:
            replaced_mask = (
                preview[reason_column]
                .fillna("")
                .astype(str)
                .str.strip()
                .isin(
                    {
                        "مستبدل بصنف آخر",
                        "رصيد كافي في الفرع",
                        "رصيد كافي في المخزن",
                    }
                )
            )
        else:
            replaced_mask = pd.Series(False, index=preview.index)
        shown = preview[required_mask | replaced_mask].copy()
    else:
        shown = preview.copy()

    highlights = st.session_state.get("result_highlights") or {}
    pushing_codes = highlights.get("pushing", set())
    multi_codes = highlights.get("multi", set())
    transfer_codes = highlights.get("transfer", set())
    warehouse_codes = highlights.get("warehouse", set())

    def row_style(row: pd.Series) -> list[str]:
        code = _normalise_code(row.get(code_column, ""))
        if code in warehouse_codes:
            color = "rgba(255, 192, 203, 0.35)"
        elif code in pushing_codes:
            color = "rgba(173, 216, 230, 0.32)"
        elif code in transfer_codes:
            color = "rgba(255, 255, 224, 0.28)"
        elif code in multi_codes:
            color = "rgba(211, 211, 211, 0.22)"
        else:
            color = ""
        return [f"background-color: {color}" if color else "" for _ in row]

    legend = (
        ("rgba(173, 216, 230, 0.75)", tr("legend_push")),
        ("rgba(211, 211, 211, 0.65)", tr("legend_multi")),
        ("rgba(255, 255, 224, 0.70)", tr("legend_transfer")),
        ("rgba(255, 192, 203, 0.78)", tr("legend_warehouse")),
    )
    st.markdown(
        '<div class="ao-legend">'
        + "".join(
            f'<span><i class="ao-swatch" style="background:{color}"></i>{escape(label)}</span>'
            for color, label in legend
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    # Live search by item code or name.  It filters the preview only; the
    # Excel file and the missing-items report still contain every item.
    item_query = st.text_input(
        tr("item_search_label"),
        placeholder=tr("item_search_placeholder"),
        key="item_search",
    ).strip()
    if item_query:
        code_text = shown[code_column].astype(str)
        name_column = "Name" if lang() == "en" else "الاسم"
        name_text = (
            shown[name_column].astype(str)
            if name_column in shown.columns
            else pd.Series("", index=shown.index)
        )
        match_mask = code_text.str.contains(
            item_query, case=False, na=False, regex=False
        ) | name_text.str.contains(
            item_query, case=False, na=False, regex=False
        )
        shown = shown.loc[match_mask].copy()
        if shown.empty:
            st.info(tr("item_search_none"))
        else:
            st.caption(
                tr("item_search_match", count=f"{len(shown):,}")
            )

    st.caption(tr("showing_preview", shown=f"{len(shown):,}", total=f"{len(preview):,}"))

    if shown.empty:
        if not item_query:
            st.info(tr("no_required"))
    else:
        visible = shown.head(PREVIEW_ROW_LIMIT)
        if len(shown) > PREVIEW_ROW_LIMIT:
            st.caption(tr("preview_limit", limit=f"{PREVIEW_ROW_LIMIT:,}"))
        try:
            st.dataframe(
                visible.style.apply(row_style, axis=1),
                use_container_width=True,
                height=440,
                hide_index=True,
            )
        except Exception:
            st.dataframe(visible, use_container_width=True, height=440, hide_index=True)

    excel_bytes = st.session_state.get("result_bytes")
    if not excel_bytes:
        try:
            excel_bytes = export_styled_excel(
                final_df,
                diagnostics=st.session_state.get("result_diagnostics"),
            ).getvalue()
        except Exception as error:  # noqa: BLE001
            st.warning(tr("excel_error", error=error))
            buffer = io.BytesIO()
            fallback_df = final_df.rename(
                columns={"ROP": "نقطة إعادة الطلب", "Lead_Time": "زمن التوريد"}
            )
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                fallback_df.to_excel(
                    writer, index=False, sheet_name="الطلبية النهائية"
                )
            excel_bytes = buffer.getvalue()
        st.session_state.result_bytes = excel_bytes

    if excel_bytes:
        st.download_button(
            tr("download"),
            data=excel_bytes,
            file_name="الطلبية_النهائية.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_final",
        )
        st.caption(tr("download_caption"))

    missing_items = st.session_state.get("result_missing")
    if isinstance(missing_items, pd.DataFrame) and not missing_items.empty:
        st.download_button(
            tr("download_missing"),
            data=missing_items.to_csv(index=False).encode("utf-8-sig"),
            file_name="Missing_Items_Report.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_missing",
        )
        st.caption(
            tr("missing_caption", count=f"{len(missing_items):,}")
        )


# ---------------------------------------------------------------------------
# Branch schedules page
# ---------------------------------------------------------------------------
def schedule_card(day: str, branches: tuple[str, ...], matching: set[str]) -> str:
    visible = [branch for branch in branches if branch in matching]
    if visible:
        chips = "".join(
            f'<span class="ao-branch-chip" title="{escape(branch)}">{escape(branch_label(branch))}</span>'
            for branch in visible
        )
    else:
        chips = f'<span class="ao-empty">{escape(tr("no_branches"))}</span>'
    return (
        '<div class="ao-day-card">'
        '<div class="ao-day-head">'
        f'<span class="ao-day-name">{escape(weekday_label(day))}</span>'
        f'<span class="ao-day-count">{escape(tr("branch_count", count=len(visible)))}</span>'
        '</div>'
        f'<div class="ao-chip-row">{chips}</div>'
        '</div>'
    )


def render_schedule_grid(day_map: dict[str, tuple[str, ...]], matching: set[str]) -> None:
    cards = "".join(schedule_card(day, day_map[day], matching) for day in SCHEDULE_WEEKDAYS)
    st.markdown(f'<div class="ao-day-grid" dir="{direction()}">{cards}</div>', unsafe_allow_html=True)


def table_for_schedule(day_map: dict[str, tuple[str, ...]], matching: set[str]) -> pd.DataFrame:
    rows = []
    for day in SCHEDULE_WEEKDAYS:
        visible = [branch_label(branch) for branch in day_map[day] if branch in matching]
        rows.append(
            {
                tr("table_day"): weekday_label(day),
                tr("table_branches"): "، ".join(visible) if visible else tr("none"),
                tr("table_count"): len(visible),
            }
        )
    return pd.DataFrame(rows)


def render_schedules_page() -> None:
    page_head(tr("schedules_eyebrow"), tr("schedules_title"), tr("schedules_subtitle"))
    st.caption(tr("schedules_rule"))

    total_branches = len({branch for day in SCHEDULE_WEEKDAYS for branch in PREPARATION_SCHEDULE[day]})
    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric(tr("total_branches"), f"{total_branches}")
    metric_2.metric(tr("prep_days"), f"{len(SCHEDULE_WEEKDAYS)}")
    metric_3.metric(tr("arrival_days"), f"{len(SCHEDULE_WEEKDAYS)}")

    search_query = st.text_input(
        tr("search_label"),
        placeholder=tr("search_placeholder"),
        key="branch_search",
    )
    matching = {
        branch
        for day in SCHEDULE_WEEKDAYS
        for branch in set(PREPARATION_SCHEDULE[day]) | set(ARRIVAL_SCHEDULE[day])
        if _branch_matches(branch, search_query)
    }
    if search_query:
        if matching:
            st.markdown(
                f'<div class="ao-search-note">{escape(tr("search_match", count=len(matching)))}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(tr("search_none"))

    prep_tab, arrival_tab = st.tabs([tr("tab_prep"), tr("tab_arrival")])
    with prep_tab:
        st.caption(tr("prep_caption"))
        render_schedule_grid(PREPARATION_SCHEDULE, matching)
        with st.expander(tr("table_view")):
            st.dataframe(table_for_schedule(PREPARATION_SCHEDULE, matching), use_container_width=True, hide_index=True)
    with arrival_tab:
        st.caption(tr("arrival_caption"))
        render_schedule_grid(ARRIVAL_SCHEDULE, matching)
        with st.expander(tr("table_view")):
            st.dataframe(table_for_schedule(ARRIVAL_SCHEDULE, matching), use_container_width=True, hide_index=True)

    section_head(tr("branch_detail"), tr("branch_detail"), tr("branch_detail_hint"))
    schedule_branch_choice = st.selectbox(
        tr("branch"),
        BRANCH_CHOICES,
        key="schedule_branch_choice",
    )
    schedule_branch = BRANCH_BY_CHOICE[schedule_branch_choice]
    info = schedule_for(schedule_branch)
    secondary = "دورة الفرع"
    st.markdown(
        f'<div class="ao-branch-banner"><strong>{escape(branch_label(schedule_branch))}</strong>'
        f'<span>{escape(secondary)}</span></div>',
        unsafe_allow_html=True,
    )
    prep_days = " · ".join(weekday_label(day) for day in info.prep_days) or tr("none")
    arrival_days = " · ".join(weekday_label(day) for day in info.arrival_days) or tr("none")
    prep_col, arrival_col = st.columns(2)
    prep_col.metric(tr("prep_days"), prep_days)
    arrival_col.metric(tr("arrival_days"), arrival_days)

    cycle = compute_schedule_cycle(schedule_branch, date.today())
    c3, c4 = st.columns(2)
    c3.metric(tr("nearest_prep"), date_label(cycle.preparation_weekday, cycle.preparation_date))
    c4.metric(tr("first_arrival"), date_label(cycle.arrival_weekday, cycle.arrival_date))
    st.caption(tr("separation_note"))

    for warning in info.warnings:
        st.warning(warning)
    if cycle.warnings:
        with st.expander(tr("schedule_note")):
            for warning in cycle.warnings:
                st.write(f"• {warning}")


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------
def render_settings_page() -> None:
    page_head(tr("settings_eyebrow"), tr("settings_title"), tr("settings_subtitle"))
    current = st.session_state.get("settings") or SupplyChainSettings()

    with st.container(border=True):
        section_head(tr("settings_eyebrow"), tr("planning_policy"), tr("settings_note"))

        # Outside the form on purpose: form widgets do not rerun until submit,
        # so a toggle inside the form could not immediately disable Z/variance.
        toggle_column, rop_column, _ = st.columns([1, 1, 1], gap="large")
        with toggle_column:
            enable_z_score = st.toggle(
                tr("z_toggle"),
                value=bool(current.enable_z_score),
                help=tr("z_toggle_help"),
                key="cfg_enable_z",
            )
        with rop_column:
            enable_rop = st.toggle(
                tr("rop_toggle"),
                value=bool(getattr(current, "enable_rop", True)),
                help=tr("rop_toggle_help"),
                key="cfg_enable_rop",
            )

        with st.form("settings_form", clear_on_submit=False):
            left, right = st.columns(2, gap="large")
            with left:
                z_score = st.number_input(
                    tr("z_label"),
                    min_value=0.0,
                    max_value=5.0,
                    value=float(current.z_score),
                    step=0.05,
                    format="%.2f",
                    help=tr("z_help"),
                    key="cfg_z",
                    disabled=not enable_z_score,
                )
                review_period = st.slider(
                    tr("review_label"),
                    1,
                    90,
                    int(current.review_period_days),
                    help=tr("review_help"),
                    key="cfg_review",
                )
                coverage_days = int(review_period)
                variance = st.slider(
                    tr("variance_label"),
                    0,
                    100,
                    int(round(current.variance_percent)),
                    help=tr("variance_help"),
                    key="cfg_variance",
                    disabled=not enable_z_score,
                )
                if not enable_z_score:
                    st.caption(tr("z_disabled"))
            with right:
                stock_choice = st.selectbox(
                    tr("stock_basis"),
                    STOCK_CHOICES,
                    index=STOCK_CHOICES.index(
                        next(choice for choice, value in STOCK_BY_CHOICE.items() if value == current.stock_basis)
                    ),
                    key="cfg_stock_choice",
                )
                stock_basis = STOCK_BY_CHOICE[stock_choice]
                demand_choice = st.selectbox(
                    tr("demand_source"),
                    DEMAND_CHOICES,
                    index=DEMAND_CHOICES.index(
                        next(choice for choice, value in DEMAND_BY_CHOICE.items() if value == current.demand_source)
                    ),
                    key="cfg_demand_choice",
                )
                demand_source = DEMAND_BY_CHOICE[demand_choice]
                method_labels = ORDER_METHOD_LABELS["ar"]
                order_method = st.radio(
                    tr("order_method"),
                    [method_labels["rop"], method_labels["target"]],
                    index=0 if current.order_method == "rop" else 1,
                    horizontal=True,
                    key="cfg_order_method",
                )
                order_method = (
                    "rop" if order_method == method_labels["rop"] else "target"
                )

            st.markdown('<div class="ao-side-divider"></div>', unsafe_allow_html=True)
            toggle_1, toggle_2, toggle_3 = st.columns(3)
            pack_rounding = toggle_1.checkbox(
                tr("pack_rounding"), value=bool(current.pack_rounding), key="cfg_pack"
            )
            substitutes_enabled = toggle_2.checkbox(
                tr("substitutes_enabled"), value=bool(current.substitutes_enabled), key="cfg_substitutes"
            )
            allocate_warehouse = toggle_3.checkbox(
                tr("allocate_warehouse"),
                value=bool(current.allocate_warehouse_stock),
                key="cfg_warehouse",
            )
            toggle_4, toggle_5 = st.columns(2)
            include_transfers = toggle_4.checkbox(
                tr("include_transfers"),
                value=bool(current.include_transfers),
                key="cfg_include_transfers",
            )
            ignore_no_sales = toggle_5.checkbox(
                tr("ignore_no_sales"),
                value=bool(current.ignore_no_sales_rate),
                key="cfg_ignore_no_sales",
            )
            st.subheader("⚠️ خيارات متقدمة")
            toggle_6, toggle_7 = st.columns(2)
            enable_cosmetics_force = toggle_6.checkbox(
                "تفعيل دفع التجميل",
                value=bool(current.enable_cosmetics_force),
                help="إذا كان مفعلاً، يتم توزيع التجميل حتى لو كانت مبيعاته صفراً.",
                key="cfg_enable_cosmetics_force",
            )
            enable_pushing_override = toggle_7.checkbox(
                "تجاوز Pushing List",
                value=bool(current.enable_pushing_override),
                help="إذا كان مفعلاً، تتحكم Pushing List في الكمية المطلوبة.",
                key="cfg_enable_pushing_override",
            )
            submitted = st.form_submit_button(tr("save_settings"), type="primary", use_container_width=True)

    if submitted:
        st.session_state.settings = replace(
            current,
            enable_z_score=bool(enable_z_score),
            enable_rop=bool(enable_rop),
            z_score=float(z_score),
            review_period_days=int(coverage_days),
            variance_percent=float(variance),
            stock_basis=stock_basis,
            demand_source=demand_source,
            order_method=order_method,
            pack_rounding=bool(pack_rounding),
            substitutes_enabled=bool(substitutes_enabled),
            allocate_warehouse_stock=bool(allocate_warehouse),
            include_transfers=bool(include_transfers),
            ignore_no_sales_rate=bool(ignore_no_sales),
            enable_cosmetics_force=bool(enable_cosmetics_force),
            enable_pushing_override=bool(enable_pushing_override),
        )
        # The generated workbook must never survive a settings change.
        st.session_state.result_bytes = None
        st.session_state.result_final = None
        st.session_state.result_diagnostics = None
        st.session_state.result_missing = None
        st.success(tr("saved_settings"))

    active = st.session_state.get("settings") or SupplyChainSettings()
    section_head(tr("active_settings"), tr("active_settings"), tr("settings_note"))
    chips = [
        (
            tr("active_z"),
            f"{active.z_score:.2f}" if active.enable_z_score else tr("disabled"),
        ),
        (
            tr("active_rop"),
            tr("enabled") if getattr(active, "enable_rop", True) else tr("disabled"),
        ),
        (tr("active_review"), f"{active.coverage_days} " + ("days" if lang() == "en" else "يوم")),
        (
            tr("active_variance"),
            f"{active.variance_percent:.0f}%" if active.enable_z_score else tr("disabled"),
        ),
        (tr("active_basis"), mode_label("stock", active.stock_basis)),
        (tr("active_demand"), mode_label("demand", active.demand_source)),
        (tr("active_method"), mode_label("method", active.order_method)),
        (
            tr("active_substitutes"),
            tr("enabled") if active.substitutes_enabled else tr("disabled"),
        ),
        (
            tr("active_transfers"),
            tr("enabled") if active.include_transfers else tr("disabled"),
        ),
        (
            tr("active_ignore_no_sales"),
            tr("enabled") if active.ignore_no_sales_rate else tr("disabled"),
        ),
        (
            tr("active_warehouse"),
            tr("deducted") if active.allocate_warehouse_stock else tr("not_deducted"),
        ),
    ]
    st.markdown(
        '<div class="ao-chip-row">'
        + "".join(f'<span class="ao-chip">{escape(label)}: <b>{escape(value)}</b></span>' for label, value in chips)
        + "</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# SOP / help page
# ---------------------------------------------------------------------------
def pdf_card(path: Path, title: str, description: str, download_label: str, key: str) -> None:
    stamp, _ = _file_stamp(path)
    payload = _pdf_bytes(str(path), stamp)
    with st.container(border=True):
        st.markdown(
            f"""<div class="ao-sop-card-head"><span class="ao-pdf-badge">PDF</span>
              <div><strong>{escape(title)}</strong>
              <span>{escape(description)}</span></div></div>""",
            unsafe_allow_html=True,
        )
        if payload:
            st.caption(tr("sop_size", size=f"{len(payload) / 1024:,.0f} KB"))
            st.download_button(
                download_label,
                data=payload,
                file_name=path.name,
                mime="application/pdf",
                use_container_width=True,
                key=key,
            )
        else:
            st.warning(tr("sop_missing"))


def render_help_page() -> None:
    page_head(tr("sop_eyebrow"), tr("sop_title"), tr("sop_subtitle"))
    arabic_col, english_col = st.columns(2, gap="large")
    with arabic_col:
        pdf_card(ARABIC_SOP, tr("sop_ar_title"), tr("sop_ar_desc"), tr("sop_download_ar"), "sop_ar_download")
    with english_col:
        pdf_card(ENGLISH_SOP, tr("sop_en_title"), tr("sop_en_desc"), tr("sop_download_en"), "sop_en_download")

    section_head(tr("sop_quick_title"), tr("sop_quick_title"), tr("sop_quick_sub"))
    quick_columns = st.columns(3, gap="medium")
    for column, number, title_key, body_key in zip(
        quick_columns,
        ("1", "2", "3"),
        ("sop_quick_1_title", "sop_quick_2_title", "sop_quick_3_title"),
        ("sop_quick_1", "sop_quick_2", "sop_quick_3"),
    ):
        with column:
            with st.container(border=True):
                upload_head(number, tr(title_key), tr(body_key), optional=True)

    section_head(tr("sop_covers_title"), tr("sop_covers_title"), tr("sop_covers_sub"))
    st.markdown(
        f"""<div class="ao-mini-card" dir="{direction()}">
          <ul>
            <li>{escape(tr("sop_covers_1"))}</li>
            <li>{escape(tr("sop_covers_2"))}</li>
            <li>{escape(tr("sop_covers_3"))}</li>
          </ul>
        </div>""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
if page == "order":
    render_order_page()
elif page == "schedules":
    render_schedules_page()
elif page == "settings":
    render_settings_page()
else:
    render_help_page()

st.markdown(
    f'<div class="ao-footer" dir="{direction()}">{escape(tr("footer_note"))}</div>',
    unsafe_allow_html=True,
)
