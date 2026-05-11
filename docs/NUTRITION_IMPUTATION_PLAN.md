# Nutrition Missing-Day Imputation Plan

## Status
- ✅ Imputation structure scaffold has been created (migration + script + skill reference update).
- ✅ Separate imputed table exists in plan: `health.nutrition_daily_imputed`.
- ✅ Initial script scaffold exists: `skills/meal-auto-log-postgres/scripts/impute_missing_days.py`.
- ⏭️ Next phase: add partial-day detection and user confirmation loop before finalizing questionable days.

## Goal
Fill nutrition gaps for fully missed days with a transparent rolling average, while keeping imputed data separated from true meal logs.

## Decision (initial)
- Method: `rolling_avg`
- Window: prior **7 recorded days** (configurable)
- Scope: full-day totals only (kcal/protein/carbs/fat)
- Guardrail: never overwrite days with real meal entries
- Auditability: store imputed totals in a separate table with metadata

## Data model
Imputed rows are written to:
- `health.nutrition_daily_imputed`

Columns include:
- `day_date`
- `calories_kcal`, `protein_g`, `carbs_g`, `fat_g`
- `source_window_days`, `source_days_count`
- `source_range_start`, `source_range_end`
- `method`, `note`, timestamps

## Script scaffold
- `skills/meal-auto-log-postgres/scripts/impute_missing_days.py`

### Example dry-run
```bash
python3 skills/meal-auto-log-postgres/scripts/impute_missing_days.py \
  --start-date 2026-04-01 \
  --end-date 2026-04-14 \
  --window-days 7 \
  --timezone America/New_York \
  --dry-run
```

### Example write
```bash
python3 skills/meal-auto-log-postgres/scripts/impute_missing_days.py \
  --start-date 2026-04-01 \
  --end-date 2026-04-14 \
  --window-days 7 \
  --timezone America/New_York
```

## Future operating approach (agreed)
1. **Missing-day imputation (auto):**
   - If a day has zero logged meals, impute full-day macros from rolling average (default 7-day window, configurable).
   - Store in `health.nutrition_daily_imputed` with `method=rolling_avg` and source metadata.

2. **Partial-day detection (flag, not auto-fill):**
   - Detect likely partial days using rules such as:
     - only 1 meal logged,
     - daily calories below configurable floor,
     - expected meal slots missing (breakfast/lunch/dinner pattern).
   - Mark day as `needs_confirmation` (future table/flag extension).

3. **User confirmation loop (human-in-the-loop):**
   - Send concise prompt: “This day looks partial—did you miss a meal?”
   - If user confirms complete: mark as confirmed and do not alter.
   - If user adds/corrects meals: upsert meals, recompute day totals, clear partial flag.

4. **Nightly cadence:**
   - Run after end-of-day buffer (e.g., 03:10 ET):
     1) detect partial days,
     2) notify user for confirmation,
     3) impute only truly missing days.

## Next step options
1. Add nightly cron (e.g., 03:10 ET) to run partial-day detection + missing-day imputation.
2. Add report output (which days were imputed, flagged partial, and confirmed by user).
3. Add policy thresholds in config (window size, kcal floor, meal-count floor, reminder timing).
