# Pharmacy Auto-Order System V3

Streamlit application that turns the PharmaFly Excel reports into a complete,
auditable replenishment workbook for a single branch.

```
streamlit run app.py
```

## Requirements

* Python 3.11+ (developed on 3.14)
* The packages in `requirements.txt`

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\streamlit run app.py
```

## Validation

```powershell
.\.venv\Scripts\python -m compileall -q app.py app_config.py core
```

No `tests/` directory is currently checked in, so there is no project pytest
suite to run. Use the command above for a syntax check, then verify a generated
workbook against the checks below.

## Layout

| Path | Purpose |
| --- | --- |
| `app.py` | Streamlit UI only — no business arithmetic |
| `app_config.py` | Every business constant (schedules, mappings, contracts) |
| `core/` | The business logic — never imports Streamlit |
| `tests/` | pytest suite |
| `company_logo.png` | The favicon, sidebar logo and hero logo |
| `generate_sop.py` | Builds the Arabic RTL SOP PDF |
| `Auto_Order_SOP.pdf` | Generated operating guide (do not edit by hand) |
| `assets/fonts/` | Tajawal fonts and the OFL licence used by the PDF |
| `tools/check_arabic_literals.py` | Guard against Arabic column-name typos |
| `docs/MASTER_BLUEPRINT.md` | The normative specification |
| `legacy/` | The preserved V1 application, for reference only |
| `installer/` | The built, unsigned Windows installer |

## The two pages

1. **تجهيز الطلبية** — the branded glass hero, branch and order date, the seven
   ERP uploaders (three required, four optional), the run button, the results
   preview, the editable order, the download and the audit panel.  The narrow
   right column carries the summaries and the active policy.
2. **مواعيد الطلبيات** — a read-only view of each branch's preparation days,
   delivery days and the Friday rule.

The logo is shown full-width at the top of the sidebar and again at the centre
of the hero, so the app has the same visual identity online and in the PDF.

### Required and optional files

Only three files are required: the master catalogue, the shortage report, and
the branch stock.  The other four ERP exports — central warehouse stock, branch
sales, purchases on order, and transfers — are optional and live in the
optional-files expander, together with the historical sales panel and the
helper files.  The run button stays disabled until the three required files are
present.

## The multi-sheet workbook (legacy description)

The workbook is split by category family: **Drugs**, **Cosmetics & Supplies**,
**Medical Cosmetics**, and **Other** (the ERP's placeholder and uncategorised
items).  Only families that contain rows get a worksheet; an empty family is
never written as an empty sheet.  Every sheet carries exactly these thirteen
columns in this order:

```
التصنيف, الكود, الاسم, المطلوب, حالة الصنف, الموجود, المخزن, المتوسط,
Lead_Time, ROP, Demand, البديل, ملاحظات
```

`المطلوب` is yellow when it is positive; `الموجود` is red when the effective
stock is zero or negative.  The raw `الموجود` is exported unchanged, so a
negative position stays visible even though the order calculation treats it as
zero.  No cell borders, no zebra striping, and no mention of Friday in the
notes.

## Recent sales input

Upload a transaction-level ledger with one row per sale:

* SKU: `كود الصنف`, `كود`, or `الكود`
* Quantity: `الكمية`, `المبيعات`, `كمية المبيعات`, or `إجمالي المبيعات`
* Date: `التاريخ`, `تاريخ البيع`, `تاريخ الفاتورة`, `تاريخ الحركة`, or `تاريخ الصرف`
* Optional: `عبوات`, `اجزاء`, `اسم الصنف`, `نوع المبيعات` / `بيان المبيعات`

The file is detected by its columns, not its name.  A file without a date is
treated as a one-month total, so it contributes to demand but not to the
measured monthly sigma; the 25% fallback is used instead.

## V3 calculation in one screen

```
Effective_Stock = Branch_Stock + Pending_Purchases - Transfers_Out
Ordering_Stock  = max(Effective_Stock, 0)

Demand = max(ERP المتوسط, recent sales monthly rate, optional panel mean)
         (shortage mode: المتوسط exactly; zero/NaN falls back to the last
          four calendar months of month-labelled sales columns / 4)

Monthly_Sigma = sample sigma of the recent report's monthly totals (n >= 2)
                else ERP-provided StdDev
                else sample sigma of the optional panel (n >= 3)
                else 25% of max(ERP المتوسط, 0)

Safety_Stock = Z * (Monthly_Sigma / sqrt(30)) * sqrt(Lead_Time), or 0 when Z is off
ROP          = (Demand / 30) * Lead_Time + Safety_Stock
Target_Demand = Demand + Safety_Stock
                + ROP when the "Enable ROP" toggle is ON
Calculated_Order = ceil(max(Target_Demand - Effective_Stock, 0))

Warehouse_Covered = min(floor(max(Warehouse_Stock, 0)), Calculated_Order)
Remaining         = Calculated_Order - Warehouse_Covered
Substitutes       = quantity covered by a same-name multi-price card
                    first, then by the official master substitute
Final_Purchase_Order = ceil(max(Remaining - Substitutes, 0))
```

When the ROP toggle is ON and the ROP order method is selected, the order is
raised only while `Effective_Stock <= ROP`. Turning the toggle OFF removes ROP
from the target and bypasses that gate.

A measured sigma of exactly zero means "no measurable dispersion" and falls
through to the next source.  The Friday buffer is part of `Lead_Time` and is
exported in that column; it is never written as a note.

## Standard operating procedure (PDF)

`generate_sop.py` builds `Auto_Order_SOP.pdf`, a 21-page Arabic RTL guide with
the company logo, a cover, a document-control page, a table of contents with
real page numbers and six sections: the system and its purpose, the employee
workflow, the seven input files and header handling, the supply-chain
mathematics, the output workbook, and troubleshooting/FAQ.

```powershell
.\.venv\Scripts\python generate_sop.py
.\.venv\Scripts\python generate_sop.py --output Auto_Order_SOP.pdf
```

The PDF uses the bundled Tajawal Regular/Bold fonts (OFL licensed) and is
generated locally; it does not call an online service.  Rebuild it whenever the
business rules or UI strings change.

## Windows build

The frozen application is built with PyInstaller from `AutoOrder.spec`; the
logo is bundled so the executable finds it even when its working directory is
not the project root.  The installer is compiled from `setup_installer.iss`:

```powershell
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean AutoOrder.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" setup_installer.iss
```

`dist\AutoOrder\AutoOrder.exe --selftest` checks the frozen imports, the logo
and workbook writing before the installer is shipped.  The installer is
unsigned, so Windows SmartScreen may ask for confirmation on first launch.

## Notes on behaviour

* The Friday buffer is part of `Lead_Time`; it is never written as a note in
  the workbook.
* Substitutes match on the exact core name — packaging is ignored, the
  strength never is. The demand waterfall is: own warehouse stock, then a
  same-name card from the multi-price sheet, then the official master
  substitute. The quantity covered by the two substitute steps is exported in
  the `Substitutes` column; only the remainder becomes `المطلوب`.
* Transfers are classified by token. `ارسال` subtracts, `استلام` adds, and
  `ارسال/استلام` is ambiguous: it is excluded from the stock equation and
  reported in the audit panel.
* If more than 1% of the rows end up with a negative balance that the branch
  stock cannot explain, the run stops and asks for the netting mode to be
  reviewed.

See `docs/DATA_ANALYSIS_AND_ARCHITECTURE.md` for the V3 architecture, and
`Auto_Order_SOP.pdf` for the operator-facing guide.

## SOP-aligned order and export behavior

The current workbook retains all catalogue items, including zero-order rows.
It contains a consolidated **Final Order** sheet, category-family sheets, and
a **Supply Breakdown** sheet. Cosmetics distribution rows are highlighted red.
The final sheet keeps the dynamic 21-column business contract; `المطلوب` is
the supplier quantity after any warehouse and substitute allocation, and
`Substitutes` records the quantity supplied by sibling/official substitute
warehouse stock. The breakdown separates
gross branch need, warehouse loading, supplier order, and branch transfers.
Optional audit columns are exported on a separate **Audit** sheet.

Planning lead time is six days plus the SOP Friday buffer. It is separate from
the schedule-based expected branch arrival date. The selected stock basis
controls whether incoming and outgoing transfers are included. Ordering
calculations use `max(effective stock, 0)`, while the original negative stock
remains visible in audit output.

```
Safety_Stock   = Z * (Monthly_Sigma / sqrt(30)) * sqrt(Lead_Time), or 0 when Z is off
ROP            = (Demand / 30) * Lead_Time + Safety_Stock
Target_Demand  = Demand + Safety_Stock
                 + ROP when the "Enable ROP" toggle is ON
Calculated_Order = ceil(max(Target_Demand - Ordering_Stock, 0))
ROP gate       = only when Enable ROP is ON and the ROP method is selected:
                 Calculated_Order = 0 while Ordering_Stock > ROP
Supplier order = rounded branch need less warehouse allocation
```
