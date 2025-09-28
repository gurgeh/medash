# Garmin Data Inventory

Generated on 2025-09-28

Date ranges: last 7 days and last 30 days (inclusive of today).

## Time Series With Recent Values
For each metric: the interval and how many days returned data.
- Steps (15-min intervals) — 15-min intervals: week 7/7 days, month 30/30 days
- Heart rate — per-day (variable sampling): week 7/7 days, month 30/30 days
- Sleep — per-day: week 7/7 days, month 30/30 days
- Stress — per-day: week 7/7 days, month 30/30 days
- SpO2 — per-day: week 7/7 days, month 30/30 days
- Respiration — per-day: week 7/7 days, month 30/30 days
- Intensity minutes — per-day: week 7/7 days, month 30/30 days
- Resting HR (RHR) — per-day: week 7/7 days, month 30/30 days
- HRV — per-day: week 0/7 days, month 0/30 days
- Floors — per-day: week 7/7 days, month 30/30 days
- Hydration — per-day: week 7/7 days, month 30/30 days
- Daily weigh-ins — per-day: week 7/7 days, month 30/30 days
- User summary — per-day: week 7/7 days, month 30/30 days
- Stats — per-day: week 7/7 days, month 30/30 days
- Stats + body — per-day: week 7/7 days, month 30/30 days
- Body Battery events — per-day events: week 0/7 days, month 0/30 days
- Training readiness — per-day: week 0/7 days, month 0/30 days
- Training status — per-day: week 7/7 days, month 30/30 days
- Max metrics — per-day: week 1/7 days, month 6/30 days

## Range-Based Metrics (last 30 days)
- Daily steps (totals) — daily totals over range: week data=True
- Body Battery — time series over range: month data=True
- Body composition — range (weight/body comp): month data=True
- Weigh-ins — range (entries): month data=True
- Endurance score — range: month data=True
- Hill score — range: month data=True
- Race predictions — range: available=True

## Activities (Events) — Last 30 Days
Total activities: 19
- indoor_rowing: 2 in last 30 days (details available: splits, weather, HR-in-timezones, gear, exercise sets, full activity details)
- running: 7 in last 30 days (details available: splits, weather, HR-in-timezones, gear, exercise sets, full activity details)
- strength_training: 10 in last 30 days (details available: splits, weather, HR-in-timezones, gear, exercise sets, full activity details)

## Suggested Extra Metadata To Store
- Source device IDs, names, and firmware versions
- Timestamps with timezone offsets and device timezone
- Aggregation granularities used (e.g., 1s HR, 15-min steps, daily totals)
- Units (metric/imperial) and measurement system from user settings
- Activity-level fields: lap/split summaries, training effect/load, VO2max, weather, gear, course
- Data quality flags and missing-data markers (days without data)
- Any Garmin-specific IDs needed to re-fetch details later
