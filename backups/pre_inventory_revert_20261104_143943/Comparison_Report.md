# Auto Order V2 vs Manual — Comparison & Code Audit Report

Generated: 2026-11-04 14:36

> **Scope note:** The V2 workbook in `SOP & Standards` is the pre-fix snapshot. The code fixes below were applied after that snapshot, so the comparison numbers describe the old output. Re-run the pipeline to produce the corrected workbook. No Streamlit process was started and no source workbook was modified.

## 1. Executive Summary (Arabic)

### 1.1 الأرقام الرئيسية

| المؤشر | ملف V2 | الملف اليدوي | الفرق |
|---|---:|---:|---:|
| عدد الصفوف | 2,478 | 3,292 | -814 |
| عدد الأكواد الفريدة | 2,467 | 3,292 | -825 |
| إجمالي الكمية المطلوبة | 3,597 | 2,935 | +662 |
| إجمالي القيمة المالية | 950,945.69 | 644,639.19 | +306,306.50 |
| الأكواد المشتركة | 1,640 | 1,640 | — |
| أكواد في V2 فقط | 827 | — | — |
| أكواد في اليدوي فقط | — | 1,652 | — |

القيمة المالية في V2 أعلى بنسبة **+47.5%** والكمية أعلى بنسبة **+22.6%**. هذا ليس خطأً حسابياً بحد ذاته: V2 يستخدم ROP وTarget وLead Time بينما اليدوي يستخدم قواعد VLOOKUP أبسط، كما أن V2 يضيف أسطر بدائل وبنود Pushing/Cosmetics.

### 1.2 لماذا تختلف الأرقام؟

- **1,652** كوداً موجود في اليدوي وغير موجود في V2. التصنيف غير المتداخل: **1,112** بطلب صفر (ليست نواقص أصلاً)، **25** بلا مبيعات (راكد)، **155** يغطيها مخزن الفرع بالكامل، و**360** بطلب موجب ومخزون غير كافٍ — هذه هي الحالات التي تحتاج مراجعة ماستر/نطاق قبل اعتبارها نقصاً حقيقياً.
- **827** كوداً أضافه V2. أهم الأسباب: Pushing List، توزيع التجميل، نقص لم يلتقطه اليدوي، وأسطر البدائل.
- **30** صفاً مشتركاً فيه فرق كميات كبير. أهم 30 حالة موضحة في القسم 4 مع السبب الرياضي/البياني لكل حالة.
- **تحذير مقارنة:** V2 يضم أسطر بدائل متكررة لنفس كود الصنف البديل؛ عدد صفوف V2 2,478 بينما الأكواد الفريدة 2,467، أي 11 صفاً إضافياً. المقارنة في هذا التقرير تُجمّع V2 حسب الكود.

## 2. Data & Method

- V2 source: `Auto_Order_Final.xlsx` — sheets: Final Order; used `Final Order`.
- Manual source: `نواقص جناكليس 3.11.2026.xlsx` — sheets: ادوية, ميديكال, مستحضرات, اصفار مستحضرات, D, Sheet3; header row 2.
- Codes were trimmed, `.0` suffixes removed, whitespace removed, and leading zeroes dropped from numeric codes.
- V2 rows were aggregated by code for the comparison; substitute rows can otherwise double-count the target SKU.
- Manual financial value = `المطلوب × السعر`; V2 financial value = `القيمة المالية للطلب`.
- The comparison is observational: the raw ERP input files were not present in this folder, so the pipeline could not be re-run to regenerate V2.

## 3. Headline Comparison

### 3.1 V2 reason distribution (pre-fix snapshot)

| V2 Reason     |   Rows |   Quantity |   Financial Value |
|---------------|--------|------------|-------------------|
| توزيع تجميل   |  1,167 |      1,403 |          397490   |
| نقص في الرصيد |    702 |      1,429 |          351579   |
| Pushing List  |    446 |        509 |          150959   |
| بديل          |    163 |        256 |           50917.5 |

### 3.2 Coverage

| Segment | Codes |
|---|---:|
| Manual only | 1,652 |
| V2 only | 827 |
| Both | 1,640 |

## 4. The "Smoking Guns" — Top 30 Quantity Mismatches

The table below is the highest absolute quantity gap among shared codes. The explanation is derived from the visible columns (warehouse, average, reason, notes); it is not an assumption about an invisible file.

|   Code | Item                                    |   Manual Qty |   V2 Qty |   Gap (V2 - Manual) |   Price |   V2 Warehouse | Why                                                                                                                                                     |
|--------|-----------------------------------------|--------------|----------|---------------------|---------|----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
|  36395 | DIXY 5ML سرنجة ادوية للاطفال            |          100 |       28 |                 -72 |     7   |           0    | V2's ROP/Target produced a lower quantity than the manual rule; the difference is demand/coverage assumptions, not a missing SKU.                       |
|  10219 | OTRIVIN ADULT NASAL DROP 4O1            |           50 |       72 |                  22 |    24   |        6256    | V2 demand average is 93.08/month vs manual 56.00; the higher average raises the ROP and Target.                                                         |
|  47230 | ICOSALIP 1 GM 20 CAP 12I2               |            0 |       21 |                  21 |   276   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  34547 | ZURCAL 40 MG 14TAB 1STRIP 9Z1           |           20 |        1 |                 -19 |    96   |        1533    | V2 created a 1-unit forced distribution line; manual ordered the full branch quantity instead of a minimum display quantity.                            |
|  77268 | SODIUM CHLORIDE 0.9% جبتو بالكاب        |            0 |       16 |                  16 |    35   |           4    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  47459 | BETADERM 30GM CREAM 2A3 ##              |            0 |       16 |                  16 |    23   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  73118 | DICLOPRO SR 75 MG ID 20TAB 8D3 ##       |            0 |       10 |                  10 |    58   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  77769 | SODIUM CHLORIDE 0.9 % 500 ML MUP        |            0 |       10 |                  10 |    40   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  49699 | SODIUM CHLORIDE 0.9% 500ML انترا بالكاب |            0 |       10 |                  10 |    29.5 |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  71982 | SODIUM CHLORIDE 9%المتحدون بالكاب       |            0 |        9 |                   9 |    26   |           7    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  41428 | DECANCIT SR 20 T B5                     |           20 |       11 |                  -9 |    42   |           2.5  | V2 netted warehouse stock (2.5) from the purchase layer; the manual quantity is gross of the central warehouse.                                         |
|  16512 | CANDY-C HONEY&LEMON 12 LOZENGES 8C3     |           10 |        1 |                  -9 |    54   |           0    | V2 created a 1-unit forced distribution line; manual ordered the full branch quantity instead of a minimum display quantity.                            |
|  77854 | MINALAX 30 TAB 11M5##                   |           10 |        2 |                  -8 |    54   |          14    | V2 netted warehouse stock (14) from the purchase layer; the manual quantity is gross of the central warehouse.                                          |
|  76514 | GLUCOPHAGE 1000 XR 30TAB 3G2            |           10 |        2 |                  -8 |   150   |         915    | V2 line is a substitute shortfall for another SKU; the manual sheet has no separate substitute line, so the two quantities are not directly comparable. |
|  78603 | MEDIPHA B12 30 FILMS 11M2               |            0 |        7 |                   7 |   195   |         317    | V2 line is a substitute shortfall for another SKU; the manual sheet has no separate substitute line, so the two quantities are not directly comparable. |
|  45795 | OMEGA A I T 30 CAP 11O3                 |            0 |        7 |                   7 |   135   |           1.67 | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  52876 | MEDIPHA B12 30 FILMS 11M2               |            0 |        7 |                   7 |   135   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  37316 | DIXY 10MLسرنجة ادوية للاطفال            |            0 |        7 |                   7 |    10   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  74224 | SIRDALUD 4MG 30T 9S2##                  |           10 |        3 |                  -7 |   105   |         567    | V2 netted warehouse stock (567) from the purchase layer; the manual quantity is gross of the central warehouse.                                         |
|  66160 | PEDIAMIL 1 400GM 6H13                   |            0 |        6 |                   6 |   385   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  78163 | OMEGAL ULTRA 30 CAP 11O4                |            0 |        6 |                   6 |   270   |         332    | V2 line is a substitute shortfall for another SKU; the manual sheet has no separate substitute line, so the two quantities are not directly comparable. |
|  55138 | OMEGAL ULTRA 30 CAP 11O4                |            0 |        6 |                   6 |   240   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  23673 | STERI-STRIP 1IN*5IN 1548                |            1 |        7 |                   6 |   235   |           0    | V2's ROP/Target produced a higher quantity than the manual rule; the difference is demand/coverage assumptions, not a missing SKU.                      |
|  78799 | OMEGA A I T 30 CAP 11O3                 |            0 |        6 |                   6 |   175   |         250    | V2 line is a substitute shortfall for another SKU; the manual sheet has no separate substitute line, so the two quantities are not directly comparable. |
|  50233 | MAXILASE SYRUP 200ML 3M2##              |            0 |        6 |                   6 |    97   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  73478 | VONASPIRE 20MG 28 TAB 9V4##             |            0 |        5 |                   5 |   208   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  76900 | MAXI CARE CREAM 75 GM 2D2               |            0 |        5 |                   5 |   173   |         915    | V2 line is a substitute shortfall for another SKU; the manual sheet has no separate substitute line, so the two quantities are not directly comparable. |
|  76502 | LIMITLESS B COMPLEX  30 ODF 4L5         |            0 |        5 |                   5 |   150   |           0    | V2 line is a substitute shortfall for another SKU; the manual sheet has no separate substitute line, so the two quantities are not directly comparable. |
|  50293 | LIMITLESS B COMPLEX  30 ODF 4L5         |            0 |        5 |                   5 |   135   |          -3    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |
|  42893 | MELACRYST 3 MG 20FILM 11M2              |            0 |        5 |                   5 |    90   |           0    | Manual omitted the item (0 request); V2 triggered a need from its ROP/Target calculation.                                                               |

## 5. Items V2 Included but Manual Missed — Top 30 by Value

|   Code | Item                                                                    |   V2 Qty |   Price |   V2 Value | V2 Reason     | Why V2 included it                                                         |
|--------|-------------------------------------------------------------------------|----------|---------|------------|---------------|----------------------------------------------------------------------------|
|  35866 | SUPLASYN 60MG 1VIAL (R1)                                                |        1 |    6000 |       6000 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  68067 | P R I O R I N N 90 CAPS                                                 |        2 |    2650 |       5300 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  28569 | Q U E S T R A N  50 S A C H                                             |        1 |    4950 |       4950 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  31783 | M O V E F R E E A D V A N C E D1 2 0 C A P                              |        1 |    3750 |       3750 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|   7509 | NEOCELL COLLAGEN JOINT COMPLEX 120CAP 11N2                              |        1 |    2500 |       2500 | Pushing List  | Pushing-list item: V2 exposes a priority item the manual sheet missed.     |
|  30951 | C O L C H I C I N E 1 MG 60TI M P                                       |        1 |    2200 |       2200 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  34241 | M E T H Y C O B A L 500MG 10AMP I M P                                   |        1 |    2200 |       2200 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|   7508 | NEOCELL MARINE COLLAGEN 120CAP 11N2                                     |        1 |    1750 |       1750 | Pushing List  | Pushing-list item: V2 exposes a priority item the manual sheet missed.     |
|  36288 | VICHY LIFTACTIV NIGHT SUPREME 50ML                                      |        1 |    1700 |       1700 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  70753 | XXX                                                                     |        1 |    1700 |       1700 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  53974 | ROSSMAX AUTOMATIC BLOOD PRESSUR MONITOR Z1 قياس شاحن موبيل              |        1 |    1695 |       1695 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  73475 | NEOCELL GRASSFED COLLAGEN C & BIOTIN  90TAB 11N2                        |        1 |    1690 |       1690 | Pushing List  | Pushing-list item: V2 exposes a priority item the manual sheet missed.     |
|  54487 | SEMI DI LINO REPARATIVE MASK 200ML                                      |        2 |     749 |       1498 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  77251 | DR.ALTHEA 345 RELIEF CREAM MIST 100ML                                   |        1 |    1400 |       1400 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  10802 | SEMI DI LINO SHAMPOO FOR RECONSTRUCTION DAMAGED HAIR 250ML للشعر التالف |        2 |     699 |       1398 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  75379 | SPIRIVA 30CAP 4S1+جهاز                                                  |        2 |     669 |       1338 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  48828 | K18 HAIR MASK 50ML                                                      |        1 |    1200 |       1200 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  36524 | A G I O L A X 250GM G R A N U L E S I M P                               |        1 |    1150 |       1150 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  12425 | METOJECT 50 MG/M SYRINGE 12.5 MG 11M1                                   |        2 |     560 |       1120 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  36254 | VICHY LIFTACTIV SUPREME EYES 15ML                                       |        1 |    1100 |       1100 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  52562 | VITACARE ADV TEDDY VITES 60 GUMMIES 9V3                                 |        1 |    1099 |       1099 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  52563 | VITACARE VIT D3 10000IU 90 CAP 9V3                                      |        1 |    1099 |       1099 | بديل          | Substitute line added by V2 for a shortfall; manual has no equivalent row. |
|  77061 | VONASPIRE 20MG 30 TAB 9V4##                                             |        5 |     219 |       1095 | بديل          | Substitute line added by V2 for a shortfall; manual has no equivalent row. |
|  77615 | GRASSBERG D3+K2 60TAB                                                   |        1 |    1090 |       1090 | Pushing List  | Pushing-list item: V2 exposes a priority item the manual sheet missed.     |
|  12450 | DOPPEL HERZ AKTIV IRON DIRECT 30SACH 5A3                                |        1 |    1050 |       1050 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  48590 | LIFE MAGNESIUM CITRATE 100 MG 100 CAP 12L13                             |        1 |    1040 |       1040 | Pushing List  | Pushing-list item: V2 exposes a priority item the manual sheet missed.     |
|  75837 | AVENE SUNCARE FLUID SPF50 50ML (1+1)OFFER                               |        1 |    1025 |       1025 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|  33252 | LA ROCHE PIGMENTCLAR EYES 15ML                                          |        1 |    1020 |       1020 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |
|   7704 | L A S I X 5 0 0 M G 1 0 T A B B 1 4  ا ل م د و رC 1 1                   |        1 |    1000 |       1000 | نقص في الرصيد | V2 detected a shortage/ROP trigger that the manual VLOOKUP process missed. |
|  62865 | URIAGE HYSEAC HYDRA 40 ML                                               |        1 |     999 |        999 | توزيع تجميل   | Cosmetics distribution override: V2 exposes a forced cosmetics line.       |

## 6. Items Manual Over-Ordered vs V2 — Top 30 by Value

|   Code | Item                                         |   Manual Qty |   V2 Qty |   Price |   Manual Over-Order Value | Why                                                                                             |
|--------|----------------------------------------------|--------------|----------|---------|---------------------------|-------------------------------------------------------------------------------------------------|
|  34547 | ZURCAL 40 MG 14TAB 1STRIP 9Z1                |           20 |        1 |      96 |                      1824 | V2 capped a forced distribution line at 1; manual over-ordered.                                 |
|  75139 | CH ALPHA PLUS 10 SACH 5A2                    |            5 |        1 |     395 |                      1580 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  67857 | CAPIXY SPRAY INTENSE TONIC 125ML Z1(RED)     |            3 |        1 |     700 |                      1400 | V2 capped a forced distribution line at 1; manual over-ordered.                                 |
|  76514 | GLUCOPHAGE 1000 XR 30TAB 3G2                 |           10 |        2 |     150 |                      1200 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  77566 | THREESIXFIVE 365 REJUVENE EYE CREAM 20GM     |            3 |        1 |     580 |                      1160 | V2 capped a forced distribution line at 1; manual over-ordered.                                 |
|  49861 | LANTUS 100 I.U/ ML 5 CART (R1)               |            2 |        1 |    1107 |                      1107 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  74919 | MIXTANE 30TAB 11M5                           |            5 |        1 |     270 |                      1080 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  48102 | NASONEX SPRAY G12                            |           20 |       15 |     157 |                       785 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  10868 | PLAQUENIL 200MG 60TAB.D9                     |            5 |        2 |     246 |                       738 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  74224 | SIRDALUD 4MG 30T 9S2##                       |           10 |        3 |     105 |                       735 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  49214 | PULMICORT 0.25MG/ML 20NEBULIZER AMP 4P1      |            2 |        1 |     564 |                       564 | V2 uses a lower sales average (1.54 vs 2.00); the manual request is above the statistical need. |
|  61345 | DENTAL FLOSS ORAL B SATIN MINT               |            5 |        3 |     260 |                       520 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  36395 | DIXY 5ML سرنجة ادوية للاطفال                 |          100 |       28 |       7 |                       504 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  62143 | جوانتى فحص علبه L                            |            5 |        3 |     250 |                       500 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  16512 | CANDY-C HONEY&LEMON 12 LOZENGES 8C3          |           10 |        1 |      54 |                       486 | V2 capped a forced distribution line at 1; manual over-ordered.                                 |
|  77854 | MINALAX 30 TAB 11M5##                        |           10 |        2 |      54 |                       432 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  48756 | HYDROQUINE 200MG 20TAB. C3                   |           10 |        5 |      82 |                       410 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  79047 | ROTADIGEST LACTASE 9000 30CAP 9R2            |            2 |        1 |     390 |                       390 | V2 uses a lower sales average (0.77 vs 1.00); the manual request is above the statistical need. |
|  48948 | NANO TREAT OILY SKIN CLEANSER ADVANCED 200ML |           10 |        8 |     190 |                       380 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  41428 | DECANCIT SR 20 T B5                          |           20 |       11 |      42 |                       378 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  53122 | NAVILIPO EYE DROPS 10ML 4M2                  |            3 |        2 |     375 |                       375 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  34972 | RENICLAIR 15MG SPRAY 9R1                     |            5 |        4 |     370 |                       370 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  51696 | MOXAVIDEX 400MG 10TAB 11M10                  |            3 |        1 |     184 |                       368 | V2 capped a forced distribution line at 1; manual over-ordered.                                 |
|  53525 | DAFLON 1000 MG 30 TAB 8D1                    |            2 |        1 |     354 |                       354 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  49692 | MENTOPLEX 20CAP 4M2                          |            5 |        3 |     170 |                       340 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  49370 | BRIVAFUTAL 100MG 30TAB 8B4                   |            3 |        2 |     327 |                       327 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  76546 | URSOFALK 20 CAP 9U1                          |            5 |        3 |     162 |                       324 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  77070 | CAPIXY ADVANCE REPAIR SHAMPOO 250ML(NEW)     |            5 |        4 |     320 |                       320 | V2's ROP/Target is below the manual request; the manual rule over-ordered.                      |
|  73911 | ISOLEUVAL 20CAP 12I12                        |            3 |        2 |     320 |                       320 | V2 uses a lower sales average (2.31 vs 3.00); the manual request is above the statistical need. |
|  52163 | NANO TREAT VOLUMIZING SHAMPOO 200/300ML      |            2 |        1 |     299 |                       299 | V2 capped a forced distribution line at 1; manual over-ordered.                                 |

## 7. Items Manual Included but V2 Excluded — Top 30 by Value

|   Code | Item                                                       |   Manual Qty |   Price |   Manual Value |   Monthly Avg |   Warehouse | Why V2 excluded it                                                                                                                     |
|--------|------------------------------------------------------------|--------------|---------|----------------|---------------|-------------|----------------------------------------------------------------------------------------------------------------------------------------|
|  47835 | OZEMPIC 1MG 1PEN                                           |            3 |    4000 |          12000 |             5 |      194    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  47723 | TRESIBA 100ML (R1)                                         |           10 |     550 |           5500 |            19 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  20926 | CONTROLOC 40MG 14TAB 8C28                                  |           20 |     188 |           3760 |            67 |     1846    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  55220 | APIDRA SOLO STAR 300 UNIT 5PEN (R1)                        |            3 |     952 |           2856 |             4 |       93    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  56916 | NEXIUM 40MG 28 TAB 11N4 مصرى                               |            5 |     488 |           2440 |            18 |      153    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  54059 | BRILIQUE 90MG 56 TAB 8B4                                   |            2 |    1064 |           2128 |             2 |       63    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  70316 | JANUMET 50/1000 MG 56TAB 12I15                             |            3 |     674 |           2022 |             6 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  39423 | ACCU-CHEK INSTANT 50ST                                     |            3 |     670 |           2010 |             2 |       56    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  49900 | CELEBREX 200MG 15CAP 8C7                                   |           10 |     198 |           1980 |            19 |      186    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  74054 | MEDICUBE ZERO PORE 70PADS 155G                             |            1 |    1600 |           1600 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  51690 | NOW ORG SPIRULINA 1000MG 120 TAB 4N6                       |            1 |    1500 |           1500 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  71793 | BIOSIL 60CAP OFFER بدلا من 1780                            |            1 |    1500 |           1500 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  54657 | CELIMAX RETINAL SHOT TIGHTENING BOOSTER FOR FIRM SKIN 30ML |            1 |    1500 |           1500 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  42611 | ZYROVAZET 10/20MG 30TAB 9Z2                                |            5 |     294 |           1470 |            12 |      179.33 | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  69532 | NOW PSYLLIUM HUSK 500MG 200VEG CAP 4N6                     |            1 |    1400 |           1400 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  31181 | EXFORGE HCT 10/160/25 14TAB 2E3                            |            5 |     270 |           1350 |            11 |      393    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  65652 | METHYLTECHNO 1000MG 30FILMS 11M4                           |           10 |     135 |           1350 |            25 |      541    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  61504 | NOW ZINC PICOLINATE 50MG 120CAPS 4N6                       |            1 |    1300 |           1300 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  75726 | ARENCIA PDRN FACE AND EYE MOISTURIZER BOOSTER SHOT 30ML    |            1 |    1250 |           1250 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  48502 | AROMALOCK 2.5 MG 30 TAB 8A6                                |            2 |     621 |           1242 |             1 |        1    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  57722 | RYZODEG 100 IU PEN                                         |            2 |     618 |           1236 |             6 |      323    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  70581 | FLUGENIL 600MG 10 VAG SUPP 2I4                             |            2 |     590 |           1180 |             2 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  36779 | ECTONEX KIDS 20ML SPRAY 5B6                                |            3 |     390 |           1170 |             5 |      103    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  66543 | PEDIAMIL AC 350GM 6H13                                     |            3 |     385 |           1155 |             6 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  59736 | LOREAL PRO LONGER CREAM LEAVE IN 150ML                     |            1 |    1050 |           1050 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  44021 | RAKOTY PILLOW وسادة طبية كونتور كبيرة                      |            1 |    1000 |           1000 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  77048 | URSO PLUS-20CAP 9U1                                        |            5 |     200 |           1000 |             7 |      366    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |
|  46710 | BIODERMA PHOTODERM CREAM SPF50 40ML                        |            1 |     999 |            999 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  73517 | URIAGE CICA DAILY GEL-CREAM 40ML                           |            1 |     989 |            989 |             1 |        0    | Not present in the V2 snapshot: missing master/scope data, or V2 calculated zero after its ROP/Target test; needs a master-data check. |
|  44507 | MELLITOFIX TRIO 25/5/1000 30 TAB 11M3                      |            2 |     486 |            972 |             3 |      131    | Warehouse stock covers the manual request; V2's purchase layer is zero, so the row is absent from the net export.                      |

## 8. Code Audit Findings (English)

### 8.1 Critical logic defects found

1. **Main `المطلوب` was mapped to `Final_Purchase_Order`.** `Final_Purchase_Order` is the warehouse-adjusted purchase layer. When `allocate_warehouse_stock` is ON, the sheet therefore showed the net purchase, not the branch need. This directly violates the requirement that the branch see its full shortfall.
2. **`Financial_Value` was calculated on `Final_Purchase_Order`.** The money column followed the net purchase layer, so it understated the branch need whenever warehouse stock covered part of the order.
3. **The exporter dropped zero-need rows with negative branch stock.** `_normalise_numbers` filtered only `المطلوب > 0`, so an item such as the user's TRESIBA example with a negative branch balance and no calculated order could disappear from the exception list.
4. **The pipeline filter also required a positive quantity.** Even if the exporter were fixed, the final frame had already removed negative-balance rows with zero need.
5. **The `سبب الطلب` label was wrong for normal cosmetics.** `_order_reason` checked `Is_Cosmetic` before `Calculated_Order`, so every cosmetic row was labelled `توزيع تجميل` even when it was an ordinary ROP shortage. This inflated the apparent size of the distribution override.
6. **Pushing/Cosmetics notes overwrote operational notes.** The code assigned `"Pushing"` / `"توزيع تجميل"` directly to `ملاحظات`, erasing negative-stock, substitute, and pack-rounding warnings.
7. **Stagnant detection used the purchase layer, not the branch need.** `Stagnant_Flag` was based on `Final_Purchase_Order == 0`. Once the main column changes to `Calculated_Order`, the flag must follow the branch need.
8. **The legacy `process_data` compatibility wrapper still exposed `Final_Purchase_Order` as `المطلوب`.** It is not used by Streamlit, but it would reproduce the same bug for any caller that imports it.
9. **The optional `target` order method bypassed the ROP gate.** It set `triggers = True`, so the pipeline could order above the reorder point. The true rule is `Effective Stock <= ROP`; the gate must be mandatory regardless of the UI mode.
10. **Two diagnostics still followed the purchase layer.** `Item_Status` and the per-SKU debug trace used `Final_Purchase_Order`, so the audit labels could disagree with the main `المطلوب` column.
11. **The legacy `process_data` wrapper used the review period as the daily-demand divisor and added safety stock to the target again.** It now uses monthly demand / 30 and a clean `Target - Effective Stock`.

### 8.2 What was already correct

- `Daily_Demand = Target_Demand / 30`, `ROP = Daily_Demand × Lead_Time + Safety_Stock`, and `Target = Daily_Demand × (Lead_Time + Coverage_Days)` were already present in `run_pipeline`.
- `Warehouse_Covered = min(max(Warehouse_Stock, 0), Calculated_Order)` and `Final_Purchase_Order = Calculated_Order - Warehouse_Covered` were correct as a separate purchase layer.
- Substitute rows were already based on the shortfall: `Substitute_Request = Calculated_Order - Warehouse_Stock`, and `_build_substitute_rows` writes only that shortfall, not the full requirement.
- The exporter already recomputed `القيمة المالية للطلب` from the exported quantity and price instead of copying a stale source money column.

### 8.3 Exact fixes applied

#### `core/supply_chain.py`

- `Financial_Value` now uses `Calculated_Order × Price`; a separate `Purchase_Financial_Value` keeps the warehouse-adjusted layer.
- The exported `المطلوب` now uses `Calculated_Order`, not `Final_Purchase_Order`.
- The final scope is `(Calculated_Order > 0) | (Branch_Stock < 0)`, and the final positive filter preserves negative branch balances.
- `Stagnant_Flag` now follows `Calculated_Order == 0` and excludes explicit distribution targets.
- `Distribution_Target` / `Force_Cosmetics` / `Force_Pushing` are explicit diagnostic columns; distribution no longer changes the branch-need column.
- Pushing/Cosmetics labels are appended to existing notes instead of replacing them.
- When warehouse allocation is ON, `ملاحظات` shows `صافي الشراء بعد المخزن`; the main `المطلوب` column still shows the full branch need.
- `_order_reason` now labels a cosmetic row as `توزيع تجميل` only when the explicit distribution target is active; ordinary cosmetics are `نقص في الرصيد`.
- Metrics now expose both the branch-need total (`estimated_cost`, `total_order_quantity`) and the purchase layer (`purchase_estimated_cost`, `purchase_order_quantity`, `warehouse_covered_quantity`).
- The fail-fast check compares the final `المطلوب` against the included `Calculated_Order` plus substitute allowance, not against a warehouse deduction.
- The ROP gate is now mandatory; the `target` UI mode no longer bypasses it.
- `Item_Status` and the debug trace now follow `Calculated_Order`.
- The legacy `process_data` wrapper now uses monthly demand / 30, the `Target - Effective Stock` need, and maps `Calculated_Order` to `المطلوب`.

#### `core/exporter.py`

- `_frame_from_diagnostics` now prefers `Calculated_Order` before `Final_Purchase_Order` when rebuilding the 20-column contract.
- `_normalise_numbers` now keeps `(المطلوب > 0) | (الموجود في الفرع < 0)`; negative branch balances are visible exceptions.
- `القيمة المالية للطلب` remains recomputed from the exported `المطلوب`, so the money column is always consistent with the quantity column.

### 8.4 Impact on the numbers

- When warehouse allocation is ON, the corrected sheet will show the full branch need; the purchase layer will show the lower net quantity. The current pre-fix snapshot can therefore understate `المطلوب` and `القيمة المالية` for warehouse-covered rows.
- Negative-balance items that previously vanished will appear with `المطلوب = 0` and a negative `الموجود في الفرع`; this is intentional and is an inventory exception, not an order.
- Ordinary cosmetics will no longer be counted as distribution overrides. The pre-fix reason table overstates the cosmetics override.
- The financial total will change again after re-running the pipeline because the main quantity basis changed; the pre-fix total is not the corrected total.

## 9. Business Value (Arabic) — 5 نقاط للإدارة

1. **رؤية النقص الحقيقي للفرع:** العمود `المطلوب` أصبح يعبّر عن احتياج الفرع الفعلي من ROP/Target، وليس عن الكمية المتبقية بعد خصم المخزن؛ أي أن الصيدلي يرى الحقيقة كاملة قبل قرار الشراء.
2. **فصل مسؤولية المخزن عن مسؤولية الفرع:** طبقة الشراء (`Final_Purchase_Order`) تبقى منفصلة، فيمكن للمخزن أن يغطي جزءاً من الاحتياج دون أن يختفي النقص من تقرير الفرع.
3. **عدم إخفاء الأرصدة السالبة:** أي صنف برصيد سالب يظهر كاستثناء حتى لو كان احتياجه صفراً، وهذا يمنع أخطاء الجرد من التحول إلى نواقص صامتة.
4. **قرار شراء مبني على احتمال النفاد:** V2 يستخدم متوسط المبيعات وLead Time وSafety Stock وCoverage Days، بدلاً من VLOOKUP ثابت؛ النتيجة كمية قابلة للتفسير وليست تقديراً يدوياً.
5. **توفير وشفافية مالية:** حساب القيمة على `Calculated_Order × Price` يجعل التكلفة مطابقة للكمية المعروضة، ويفصل تكلفة الاحتياج عن تكلفة الشراء الصافي، مما يسهل مراجعة الميزانية قبل الاعتماد.

## 10. Caveats & Next Steps

1. Re-run the Streamlit pipeline with the same ERP inputs to regenerate `Auto_Order_Final.xlsx` after the fixes; the current workbook is the old snapshot.
2. Confirm the master-data scope for the manual-only items that are not stagnant and not warehouse-covered; those are the only cases that may indicate a true missing-SKU problem.
3. Review the substitute rows separately: they are intentionally extra lines, so row counts and code counts will differ.
4. Validate the negative-branch exceptions with the branch pharmacist before using them as purchase orders.
5. If management wants the net purchase in the same workbook, add a second sheet named `Purchase Layer` sourced from `Final_Purchase_Order`; do not overwrite the main `المطلوب` column.

## 11. Files

- Report: `C:\Users\omars\OneDrive\Desktop\Auto_Order_V\Comparison_Report.md`
- Modified code: `core/supply_chain.py`, `core/exporter.py`
- Comparison script: `compare_outputs.py`
