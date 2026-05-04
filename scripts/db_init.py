import sqlite3
from pathlib import Path


DDL = r'''
-- Medash SQLite schema
--
-- This schema is paired with loader scripts in scripts/ that populate each
-- table. For each table below, comments describe where fields come from and
-- how values are derived, when applicable.
--
-- Loader scripts by step:
--   1) scripts/load_withings_bodycomp.py
--   2) scripts/load_garmin_activities.py
--   3) scripts/load_garmin_sleep.py
--   4) scripts/load_garmin_daily_summary.py
--   5) scripts/load_garmin_15min.py
--   6) scripts/load_journal.py
--   7) scripts/load_org.py
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Reset during iteration
DROP TABLE IF EXISTS garmin_activity_attr;
DROP TABLE IF EXISTS garmin_activity_detail;
DROP TABLE IF EXISTS garmin_activity_hr_zone;
DROP TABLE IF EXISTS garmin_activity;
DROP TABLE IF EXISTS garmin_activity_stream;
DROP TABLE IF EXISTS withings_bodycomp;
DROP TABLE IF EXISTS withings_measure;
DROP TABLE IF EXISTS withings_measure_group;
DROP TABLE IF EXISTS sleep_nightly;
DROP TABLE IF EXISTS garmin_daily_summary;
DROP TABLE IF EXISTS garmin_steps_15min;
DROP TABLE IF EXISTS garmin_15min;
DROP TABLE IF EXISTS journal_todo_fts;
DROP TABLE IF EXISTS journal_todo;
DROP TABLE IF EXISTS journal_entry;
DROP TABLE IF EXISTS org_row;

-- Garmin activity (high-level summary per activity)
-- Source: Garmin get_activities_by_date (range). Inserted by load_garmin_activities.py
-- Mapping/derivations:
--   - type_key: from activityType.typeKey (or activityTypeName fallback).
--   - duration_s: summary.duration
--   - distance_m: summary.distance (NULL for non-distance activities)
--   - training_effect_aer/_ana: aerobicTrainingEffect / anaerobicTrainingEffect
--   - hr_zone_secs_1..5: summary.hrTimeInZone_*
--   - max_hr: summary.maxHR
--   - run_type (running): 'interval' if >=4 laps and >=4 laps not ~1.00 km (0.98–1.02 km); else 'steady'
--   - device_id: summary.deviceId
--   - summary_json: full summary JSON blob
CREATE TABLE garmin_activity (
  activity_id           INTEGER PRIMARY KEY,
  type_key              TEXT,
  start_time_local      TEXT,
  start_time_gmt        TEXT,
  duration_s            REAL,
  distance_m            REAL,
  training_effect_aer   REAL,
  training_effect_ana   REAL,
  hr_zone_secs_1        REAL,
  hr_zone_secs_2        REAL,
  hr_zone_secs_3        REAL,
  hr_zone_secs_4        REAL,
  hr_zone_secs_5        REAL,
  max_hr                REAL,
  run_type              TEXT,
  device_id             INTEGER,
  summary_json          TEXT NOT NULL
);
CREATE INDEX garmin_activity_idx_type_time ON garmin_activity(type_key, start_time_local);

-- Garmin activity details (JSON payloads per activity)
-- Source: multiple endpoints: get_activity_details/splits/typed_splits/split_summaries/weather/hr_zones/sets
-- Notes:
--   - metrics_count: details.metricsCount or totalMetricsCount
--   - metric_descriptors_json: list of descriptor objects (keys, units, indices)
--   - detail_metrics_json: list of rows; each row has 'metrics' array aligned to descriptors
--   - splits_json, typed_splits_json, split_summaries_json: raw JSON
--   - weather_json: raw JSON
--   - hr_zones_json: list with {zoneNumber, secsInZone, zoneLowBoundary}
--   - exercise_sets_json: raw JSON for strength sets
CREATE TABLE garmin_activity_detail (
  activity_id              INTEGER PRIMARY KEY REFERENCES garmin_activity(activity_id) ON DELETE CASCADE,
  metrics_count            INTEGER,
  metric_descriptors_json  TEXT,
  detail_metrics_json      TEXT,
  splits_json              TEXT,
  typed_splits_json        TEXT,
  split_summaries_json     TEXT,
  weather_json             TEXT,
  hr_zones_json            TEXT,
  exercise_sets_json       TEXT
);

-- Flexible per-activity attributes (key/value)
-- Source: select summary fields for breathwork/non-running (respiration/stress), and derived metrics
-- Examples:
--   - avgRespirationRate, minRespirationRate, maxRespirationRate
--   - avgStress, startStress, endStress, differenceStress
--   - Derived HRV (breathwork): hrv_rmssd_ms, hrv_sdnn_ms, hrv_pnn50_pct, hrv_ibi_ms_mean/min/max
CREATE TABLE garmin_activity_attr (
  activity_id  INTEGER NOT NULL REFERENCES garmin_activity(activity_id) ON DELETE CASCADE,
  key          TEXT NOT NULL,
  value_num    REAL,
  value_text   TEXT,
  PRIMARY KEY (activity_id, key)
);
CREATE INDEX garmin_activity_attr_idx_key ON garmin_activity_attr(key);

-- Per-activity HR zones (normalized rows), from get_activity_hr_in_timezones
CREATE TABLE garmin_activity_hr_zone (
  activity_id   INTEGER NOT NULL REFERENCES garmin_activity(activity_id) ON DELETE CASCADE,
  zone_number   INTEGER NOT NULL,
  secs_in_zone  REAL,
  low_boundary  INTEGER,
  PRIMARY KEY (activity_id, zone_number)
);

-- Withings body composition
-- Source: Withings measure_get_meas (category=REAL). Inserted by load_withings_bodycomp.py
-- Mapping of Withings MeasureType to columns:
--   weight_kg        ← WEIGHT
--   fat_ratio        ← FAT_RATIO (percent)
--   fat_mass_kg      ← FAT_MASS_WEIGHT
--   fat_free_mass_kg ← FAT_FREE_MASS
--   muscle_mass_kg   ← MUSCLE_MASS
--   bone_mass_kg     ← BONE_MASS
--   hydration_pct    ← HYDRATION (percent)
--   pwv_mps          ← PULSE_WAVE_VELOCITY (m/s)
--   heart_rate_bpm   ← HEART_RATE (bpm)
-- ts_utc is the group timestamp (UTC ISO). raw_json stores original group payload.
CREATE TABLE withings_bodycomp (
  id               INTEGER PRIMARY KEY,
  ts_utc           TEXT NOT NULL,
  weight_kg        REAL,
  fat_ratio        REAL,
  fat_mass_kg      REAL,
  fat_free_mass_kg REAL,
  muscle_mass_kg   REAL,
  bone_mass_kg     REAL,
  hydration_pct    REAL,
  pwv_mps          REAL,
  heart_rate_bpm   REAL,
  raw_json         TEXT
);
CREATE INDEX withings_bodycomp_idx_ts ON withings_bodycomp(ts_utc);

-- Sleep nightly aggregates
-- Source: Garmin get_sleep_data(date). Inserted by load_garmin_sleep.py
-- Derivations:
--   - start/end_time_local: epoch ms → UTC ISO
--   - time_in_bed_s = (end_gmt - start_gmt) seconds; duration_s mirrors this
--   - time_asleep_s = dailySleepDTO.sleepTimeSeconds; sleep_efficiency = asleep/in_bed
--   - deep/light/rem/awake seconds from dailySleepDTO; *_pct = seconds / sum
--   - hr_min/hr_avg/hr_max from sleepHeartRate samples (list or dict formats)
--   - resting_heart_rate from payload.restingHeartRate
--   - resp_avg/min/max from dailySleepDTO respiration averages
--   - spo2_avg/min from dailySleepDTO SpO2 averages
--   - bb_start/bb_end from per-sample sleepBodyBattery; bb_delta = end - start; fallback to bodyBatteryChange
--   - latency_s/waso_s/wakeup_count from sleepLevels (codes: 0=deep,1=light,2=rem,3=awake),
--     with latency = initial awake before first sleep; waso = awake after onset; wakeups = count of awake blocks
--   - sleep_score from sleepScores.overall.value when present
CREATE TABLE sleep_nightly (
  id                    INTEGER PRIMARY KEY,
  date_for              TEXT NOT NULL,
  start_time_local      TEXT,
  end_time_local        TEXT,
  duration_s            REAL,
  time_in_bed_s         REAL,
  time_asleep_s         REAL,
  sleep_efficiency      REAL,
  latency_s             REAL,
  waso_s                REAL,
  wakeup_count          INTEGER,
  deep_s                REAL, light_s REAL, rem_s REAL, awake_s REAL,
  deep_pct              REAL, light_pct REAL, rem_pct REAL, awake_pct REAL,
  hr_min                REAL, hr_avg REAL, hr_max REAL,
  resting_heart_rate    REAL,
  resp_avg              REAL, resp_min REAL, resp_max REAL,
  spo2_avg              REAL, spo2_min REAL, spo2_time_below_90_s REAL,
  sleep_stress_avg      REAL,
  bb_start              REAL, bb_end REAL, bb_delta REAL,
  sleep_score           REAL,
  device_id             INTEGER,
  source                TEXT DEFAULT 'garmin',
  raw_json              TEXT
);
CREATE INDEX sleep_nightly_idx_date ON sleep_nightly(date_for);

-- Garmin daily summary
-- Source: get_user_summary, get_stats, get_heart_rates, get_stress_data, get_intensity_minutes_data, get_floors
-- Derivations:
--   - avg_stress from stress.avgStressLevel
--   - stress_duration_s approximated from stressValuesArray by computing seconds/sample across window and summing >0 samples
--   - intensity_minutes_total = moderate_minutes + 2*vigorous_minutes (Garmin weighting)
--   - floors_up/floors_down from get_floors (may be NULL)
CREATE TABLE garmin_daily_summary (
  date_for                TEXT PRIMARY KEY,
  total_steps             INTEGER,
  total_distance_m        REAL,
  total_kcal              REAL,
  active_kcal             REAL,
  bmr_kcal                REAL,
  rest_hr                 REAL,
  min_hr                  REAL,
  max_hr                  REAL,
  avg_stress              REAL,
  stress_duration_s       INTEGER,
  intensity_minutes_total INTEGER,
  moderate_minutes        INTEGER,
  vigorous_minutes        INTEGER,
  floors_up               INTEGER,
  floors_down             INTEGER,
  raw_json                TEXT
);

-- Unified 15-min intraday (steps/stress/body_battery/HR/respiration)
-- Source: steps (get_steps_data), stress (get_all_day_stress or get_stress_data),
--         heart (get_heart_rates), respiration (get_respiration_data)
-- Bucketing:
--   - 96 local buckets aligned to 00/15/30/45 for each date
--   - steps placed by ordinal (15-min blocks)
--   - stress_mean/body_battery_mean/hr_mean/resp_mean computed by averaging all
--     samples whose timestamps fall within each bucket; body battery values are
--     taken from the numeric part of array entries (e.g., [ts,'MEASURED',value,...])
-- Anchoring: sampling timestamps are anchored to startTimestampGMT (ISO) for day window
CREATE TABLE garmin_15min (
  date_for           TEXT NOT NULL,
  start_local        TEXT NOT NULL,   -- aligned to 00/15/30/45 (local time)
  steps              INTEGER,
  stress_mean        REAL,            -- mean of stress index (1-100) within bucket
  body_battery_mean  REAL,            -- mean body battery (0-100) within bucket
  hr_mean            REAL,            -- mean heart rate (bpm) within bucket
  resp_mean          REAL,            -- mean respiration (breaths/min) within bucket
  activity_level     TEXT,            -- from steps interval, if available (sedentary/sleeping/etc.)
  source             TEXT DEFAULT 'garmin',
  PRIMARY KEY (date_for, start_local)
);
CREATE INDEX garmin_15min_idx_date ON garmin_15min(date_for);

-- Journal entries and todos, loaded from memory-bank/journal_entries.jsonl
-- Notes: todo_all_completed and journal_todo.completed are stored as INTEGER 0/1;
-- an FTS5 table mirrors todo text and is maintained by triggers.
CREATE TABLE journal_entry (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  date_created       TEXT NOT NULL,
  created_time       TEXT,
  date_for           TEXT NOT NULL,
  happiness          REAL,
  todo_total         INTEGER,
  todo_completed     INTEGER,
  todo_all_completed INTEGER,
  agenda_text        TEXT
);
CREATE TABLE journal_todo (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id      INTEGER NOT NULL REFERENCES journal_entry(id) ON DELETE CASCADE,
  idx           INTEGER,
  label         TEXT,
  text          TEXT NOT NULL,
  completed     INTEGER,
  clock_time    TEXT,
  duration_min  INTEGER
);
CREATE VIRTUAL TABLE journal_todo_fts USING fts5(text, content='journal_todo', content_rowid='id', tokenize='unicode61');
CREATE TRIGGER journal_todo_ai AFTER INSERT ON journal_todo BEGIN
  INSERT INTO journal_todo_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER journal_todo_ad AFTER DELETE ON journal_todo BEGIN
  INSERT INTO journal_todo_fts(journal_todo_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER journal_todo_au AFTER UPDATE ON journal_todo BEGIN
  INSERT INTO journal_todo_fts(journal_todo_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO journal_todo_fts(rowid, text) VALUES (new.id, new.text);
END;

-- Org rows from memory-bank/org_tables.jsonl; sets_json aggregates setN fields,
-- metrics_json collects other non-core fields, heading_path_json stores ancestry.
CREATE TABLE org_row (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  exercise_title    TEXT NOT NULL,
  scheme            TEXT,
  date              TEXT NOT NULL,
  delta             TEXT,
  weight            REAL,
  time_sec          REAL,
  sum               REAL,
  comment           TEXT,
  heading_path_json TEXT NOT NULL,
  sets_json         TEXT,
  metrics_json      TEXT
);
CREATE INDEX org_row_idx ON org_row(exercise_title, date);
'''


def main() -> None:
    db_path = Path('data/medash.sqlite')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(DDL)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        print("Recreated DB:", db_path)
        print("Tables:", ", ".join(tables))
    finally:
        con.close()


if __name__ == '__main__':
    main()
