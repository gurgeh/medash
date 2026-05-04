# Medash ETL Plan (Last 30 Days, Per Table)

This is the working plan to populate each SQLite table in `data/medash.sqlite` starting with the last 30 days. After each table load, run validation checks (units, order of magnitude, NULL scans). Use two venvs to avoid dependency conflicts:

- Garmin: `.venv-garmin` with `garminconnect`, `python-dotenv`
- Withings: `.venv-withings` with `withings-api`, `python-dotenv`

Common flags/paths
- DB path: `data/medash.sqlite`
- Tokens: `secrets/garmin_tokens/` and `secrets/withings_tokens.json`
- Env: `.env` (GARMIN_*, WITHINGS_*)

## 1) Withings: `withings_bodycomp`

Goal: Insert body composition/weight rows for last 30 days.

Source and mapping
- Endpoint: Withings `measure_get_meas` for a 30-day range
- For each `measuregrp` (timestamp `date`):
  - `weight_kg`: MeasureType.WEIGHT (kg)
  - `fat_ratio`: FAT_RATIO (%)
  - `fat_mass_kg`: FAT_MASS_WEIGHT (kg)
  - `fat_free_mass_kg`: FAT_FREE_MASS (kg)
  - `muscle_mass_kg`: MUSCLE_MASS (kg)
  - `bone_mass_kg`: BONE_MASS (kg)
  - `hydration_pct`: HYDRATION (%)
  - `pwv_mps`: PULSE_WAVE_VELOCITY (m/s)
  - `heart_rate_bpm`: HEART_RATE (bpm)
  - `ts_utc` from group timestamp (UTC ISO)
  - `raw_json` store original group payload

Validation
- Print first 5 rows; confirm weight in kg (80–90 kg typical), fat_ratio ~ 10–30%, PWV in ~5–9 m/s.
- NULL scan per column; note measures you do not log (e.g., PWV/HR may be sparse). Do this scan for all the tables below as well.

## 2) Garmin Activities: `garmin_activity`, `garmin_activity_detail`, `garmin_activity_attr`, `garmin_activity_hr_zone`

Goal: Insert all activities for last 30 days; promote key running fields; capture detail JSON; derive `run_type`.

Process
- List activities: `get_activities_by_date(start, end)`
- For each activity `a`:
  - Insert `garmin_activity` row:
    - `activity_id` (int)
    - `type_key` from `activityType.typeKey` or best available
    - `start_time_local`, `start_time_gmt`
    - `duration_s` ← `duration`
    - `distance_m` ← `distance` (NULL for strength/row types that don’t use distance)
    - `training_effect_aer` ← `aerobicTrainingEffect`
    - `training_effect_ana` ← `anaerobicTrainingEffect`
    - `hr_zone_secs_1..5` if present from summary (hrTimeInZone_*), else NULL
    - `max_hr` ← `maxHR`
    - `run_type`: compute from `get_activity_splits`/`split_summaries`:
      - If at least 4 laps exist and >= than 4 are not ~1 km (`0.98–1.02` km), set `interval`; else `steady`; steady if insufficient laps.
    - `device_id` if present
    - `summary_json` = full summary
  - Insert `garmin_activity_detail`:
    - `metric_descriptors_json`, `detail_metrics_json`, `splits_json`, `typed_splits_json`, `split_summaries_json`, `weather_json`, `hr_zones_json`, `exercise_sets_json`
    - Skip `gear_json` (we removed it)
  - Insert `garmin_activity_hr_zone` rows from `get_activity_hr_in_timezones` (zoneNumber, secsInZone, zoneLowBoundary)
  - Insert `garmin_activity_attr` for non-running key metrics (e.g., breathwork):
    - `avgRespirationRate`, `minRespirationRate`, `maxRespirationRate`
    - `avgStress`, `startStress`, `endStress`, `differenceStress`

Validation
- Print 3 recent running rows; check `distance_m` OOM (2–10 km typical), `duration_s`, TEs.
- Derive `run_type` for a few known interval runs; sanity-check.
- NULL scan on `hr_zone_secs_*` and `max_hr`.
- Some activities will be rowing, even though we have specialized columns for running. Check what is stored there as well.
- At least one activity is HRV breathwork. Check that this gets stored as well.

## 3) Garmin Sleep: `sleep_nightly`

Goal: Insert one row per night for last 30 days.

Source and mapping
- Endpoint: `get_sleep_data(date)` for each date in the window (night aggregated in payload)
- For each night:
  - `date_for` = morning date the sleep pertains to
  - Times: `start_time_local`, `end_time_local`
  - Durations: `duration_s`, `time_in_bed_s`, `time_asleep_s`, `sleep_efficiency`
  - Stage durations and pct: deep/light/rem/awake
  - HR during sleep: `hr_min`, `hr_avg`, `hr_max`; `resting_heart_rate`
  - Respiration: `resp_avg`, `resp_min`, `resp_max`
  - SpO2: `spo2_avg`, `spo2_min`, `spo2_time_below_90_s` if epoch data allows
  - Stress: `sleep_stress_avg`
  - Body battery: `bb_start`, `bb_end`, `bb_delta` (overnight change)
  - `sleep_score` if present
  - `device_id`, `source='garmin'`, `raw_json`

Validation
- Print 5 nights; check stage distributions (~REM+light+deep ≈ time_asleep_s), efficiency ~ 0.7–0.95.
- NULL scan of respiration/SpO2 columns; note device limitations.

## 4) Garmin Daily Summary: `garmin_daily_summary`

Goal: Insert daily totals for last 30 days.

Source and mapping
- Combine `get_user_summary(date)`, `get_stats(date)`, stress/intensity endpoints as needed:
  - `date_for`
  - Steps: `total_steps`
  - Distance: `total_distance_m`
  - Calories: `total_kcal`, `active_kcal`, `bmr_kcal`
  - HR daily: `rest_hr`, `min_hr`, `max_hr`
  - Stress: `avg_stress`, `stress_duration_s`
  - Intensity minutes: `intensity_minutes_total`, `moderate_minutes`, `vigorous_minutes`
  - Floors: `floors_up`, `floors_down`
  - `raw_json` with merged daily payloads

Validation
- Print 5 days; steps and kcal plausible; HR min/max/REST align with activities.
- NULL scan to find fields not populated by device.

## 5) Garmin Intraday 15‑min: `garmin_15min`

Goal: One row per 15‑minute bucket (00/15/30/45) for last 30 days with mean values.

Bucketing rules (local time)
- Build buckets from local midnight at 15‑minute edges.
- Steps: copy 15‑minute blocks from `get_steps_data`; store `steps`, `activity_level`.
- Stress: from `get_stress_data`/`get_all_day_stress` (3‑min cadence arrays): average samples within the bucket → `stress_mean`.
- Body battery: same arrays: average within the bucket → `body_battery_mean`.
- Heart rate: `get_heart_rates` (irregular samples): average samples → `hr_mean`.
- Respiration: `get_respiration_data`: average samples → `resp_mean` (NULL where sparse).
- Buckets with no samples for a metric remain NULL.

Validation
- Print first/last bucket for 3 days; check means trends and non-zero coverage.
- For a full day, ensure 96 buckets; confirm distribution (sleep buckets populated with low HR, resp present mostly at night).

## 6) Journal: `journal_entry`, `journal_todo` (+ FTS)

Goal: Load last 30 days of entries and their todos from `memory-bank/journal_entries.jsonl`.

Process
- Filter by `date_for` within last 30 days.
- Insert `journal_entry` rows (counts, happiness, dates, created times), keep `agenda_text` NULL for now.
- Insert `journal_todo` rows from the `todos` array (label/text/completed/clock_time/duration_min). FTS triggers update.

Validation
- Print 5 entries and a few todos; confirm counts match (todo_total/completed).
- Run an FTS sample search (e.g., `Meditera`, `Bastu`) and confirm hits.

## 7) Org Tables: `org_row` from `memory-bank/org_tables.jsonl`

Goal: Load last 30 days of strength/rowing rows.

Process
- Filter by `date` within last 30 days.
- Insert rows:
  - `exercise_title`, `scheme`, `date`, `delta`, `weight`, `time_sec`, `sum`, `comment`
  - `heading_path_json` (full ancestry)
  - `sets_json` for setN columns; `metrics_json` for other headers (e.g., `sumo`, `axelpress`)

Validation
- Print 10 rows for common exercises (e.g., Bänkpress Hypertrofi); confirm weights and sets distribution.
- NULL scan to detect unused fields.

---

## Orchestration & Scripts (to add)

Create loader scripts (one per source) that accept a date range (default = last 30 days):
- `scripts/load_withings_bodycomp.py`
- `scripts/load_garmin_activities.py`
- `scripts/load_garmin_sleep.py`
- `scripts/load_garmin_daily_summary.py`
- `scripts/load_garmin_15min.py`
- `scripts/load_journal.py`
- `scripts/load_org.py`

Execution order
1) Garmin 15‑min (depends only on day endpoints)
2) Garmin daily summary
3) Sleep nightly
4) Activities (+ details, attrs, zones)
5) Withings bodycomp
6) Journal
7) Org tables

Environments
- Garmin scripts: `PYTHONPATH=. .venv-garmin/bin/python scripts/load_*.py --days 30`
- Withings scripts: `PYTHONPATH=. .venv-withings/bin/python scripts/load_withings_bodycomp.py --days 30`

---

## Post-load Validation Checklist (per table)

For each table run immediately after load:
1) Row sample (head/tail)
2) Unit/OOM spot-checks (distance in meters, weight in kg, stress/BB 0–100, HR bpm)
3) NULL scan per column to identify never-populated columns (consider dropping later)

Sample SQL snippets
- Row sample: `SELECT * FROM {table} ORDER BY ROWID LIMIT 5;`
- Tail: `SELECT * FROM {table} ORDER BY ROWID DESC LIMIT 5;`
- NULL scan example:
  ```sql
  SELECT 'stress_mean' AS col, COUNT(*) FILTER (WHERE stress_mean IS NULL) AS nulls, COUNT(*) AS total FROM garmin_15min
  UNION ALL
  SELECT 'resp_mean', COUNT(*) FILTER (WHERE resp_mean IS NULL), COUNT(*) FROM garmin_15min;
  ```
- Counts last 30 days:
  ```sql
  SELECT date_for, COUNT(*) FROM garmin_15min
  WHERE date_for >= date('now','-30 day')
  GROUP BY date_for ORDER BY date_for DESC;
  ```

Notes
- Timezone alignment: use Local timestamps from endpoints to bucket days and 15‑min edges consistently.
- Idempotency: use UPSERT (ON CONFLICT) by primary keys (e.g., `(date_for,start_local)` for 15‑min; `activity_id` for activities).
- Rate limiting: fetch per‑day loops to throttle if needed.
- Provenance: raw JSON fields available for backfills and audits.
