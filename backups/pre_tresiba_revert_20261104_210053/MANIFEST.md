# Revert to pre-Tresiba stable state — 2026-11-04 21:00

## Target
Code state as it was at **2026-11-03 21:31** — immediately before the Tresiba
inventory discussion and before any `opencode`/Copilot audit changes.

## Restored files

| File | Source of truth | Snapshot time | SHA-256 |
|---|---|---|---|
| `core/supply_chain.py` | VS Code Local History `-4f43b8b7/wWlk.py` | 2026-11-03 21:31:50 | `F170530BECDA5FB4D435394F0FA4EC7615DEBCC445A4C9152606C6C874449556` |
| `core/exporter.py` | VS Code Local History `22567ad9/8iYs.py` | 2026-11-03 21:31:48 | `BADE4785596411FC251804266236F351B9CADD2DEF8927A8D2D1D5AB4B8CBA75` |
| `app.py` | `%TEMP%\auto_order_backup_before_final\app.py` (11-02 21:36) + the 9 recorded edits from 11-02 21:44 → 11-03 14:11 | reconstructed to 2026-11-03 21:31 | `F518B4AD982F4747929A8819E395F2466BAA433DD2BF4D1511880335B5219947` |
| `app_config.py` | VS Code Local History `-2f987d1c/q7rF.py` (11-02 21:27:59) + the 2 recorded Pushing-Override edits of 11-03 14:07 | reconstructed to 2026-11-03 21:31 | `474F4823F2A0DC8625505D667DA93F88FE65F357D077B34A80887A6C43B74618` |

`app.py` / `app_config.py` had no single VS Code snapshot at 21:31 (they were
edited outside VS Code), so they were rebuilt by replaying every recorded edit
from `opencode.db` onto the last full saved copies. All replayed `oldString`
anchors matched exactly once.

## Current-state backup (pre-revert)
This folder also contains the four files exactly as they were before the
revert, plus `README.md`, and `*_target_vs_current.diff` files.

## What this removes
- Tresiba-era inventory/audit changes in `supply_chain.py` and `exporter.py`
  (137/55 and 66/8 line diffs).
- Copilot's 2026-11-04 17:00–20:28 changes:
  `review_period_days 30→21`, `SUGGESTED_COVERAGE_DAYS 30→21`,
  `include_transfers True→False`, `coverage_days` docstring.
- Copilot's 2026-11-04 20:43 rollback of `app.py` to the stale 2026-11-01 build.

## Verification performed
- `py_compile` OK on all four files.
- `SupplyChainSettings`: review 21, coverage 21, transfers off,
  `enable_cosmetics_force`/`enable_pushing_override` present (default off).
- Pipeline with the Hanoville input set:
  - Pushing List input = 446 rows (the "~450" list).
  - `enable_pushing_override=True`: 791 final rows, required sum 1275,
    export bytes 84,387 — Excel generated successfully.
- Streamlit AppTest: 0 exceptions; Pushing List uploader present
  ("قائمة الدفع"); settings page exposes **Pushing List Override** and
  **Force Push للتجميل**; results page renders **تنزيل Auto_Order_Final.xlsx**.
