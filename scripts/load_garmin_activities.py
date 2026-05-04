from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def _iso(d: date) -> str:
    return d.isoformat()


def _type_key(a: Dict[str, Any]) -> Optional[str]:
    at = a.get("activityType")
    if isinstance(at, dict):
        return at.get("typeKey") or at.get("typeId") or at.get("typeName")
    if isinstance(at, str):
        return at
    name = a.get("activityTypeName")
    if isinstance(name, str):
        return name
    return None


def _run_type_from_laps(splits: Dict[str, Any], split_summaries: Dict[str, Any]) -> str:
    laps: List[Dict[str, Any]] = []
    if isinstance(splits, dict):
        lst = splits.get("lapDTOs")
        if isinstance(lst, list):
            laps = [x for x in lst if isinstance(x, dict)]
    if not laps and isinstance(split_summaries, dict):
        lst = split_summaries.get("splitSummaries")
        if isinstance(lst, list):
            laps = [x for x in lst if isinstance(x, dict)]

    if not laps:
        return "steady"

    # Count laps not around 1 km (0.98–1.02 km)
    non_one_k = 0
    for lap in laps:
        dist = lap.get("distance") or lap.get("distanceMeters")
        if isinstance(dist, (int, float)):
            if not (980.0 <= float(dist) <= 1020.0):
                non_one_k += 1

    if len(laps) >= 4 and non_one_k >= 4:
        return "interval"
    return "steady"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Garmin activities into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    return p.parse_args()


def insert_activity(cur: sqlite3.Cursor, a: Dict[str, Any], run_type: Optional[str]) -> None:
    aid = int(a.get("activityId"))
    tkey = _type_key(a)
    start_local = a.get("startTimeLocal") or a.get("startTimeGMT")
    start_gmt = a.get("startTimeGMT")
    duration = a.get("duration")
    distance = a.get("distance")
    tea = a.get("aerobicTrainingEffect")
    ten = a.get("anaerobicTrainingEffect")
    max_hr = a.get("maxHR")
    device_id = a.get("deviceId")

    # hrTimeInZone_1..5 if present
    zones = [
        a.get("hrTimeInZone_1"),
        a.get("hrTimeInZone_2"),
        a.get("hrTimeInZone_3"),
        a.get("hrTimeInZone_4"),
        a.get("hrTimeInZone_5"),
    ]

    cur.execute(
        """
        INSERT OR REPLACE INTO garmin_activity (
            activity_id, type_key, start_time_local, start_time_gmt, duration_s, distance_m,
            training_effect_aer, training_effect_ana,
            hr_zone_secs_1, hr_zone_secs_2, hr_zone_secs_3, hr_zone_secs_4, hr_zone_secs_5,
            max_hr, run_type, device_id, summary_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            aid,
            tkey,
            start_local,
            start_gmt,
            duration,
            distance,
            tea,
            ten,
            zones[0],
            zones[1],
            zones[2],
            zones[3],
            zones[4],
            max_hr,
            run_type,
            device_id,
            json.dumps(a),
        ),
    )


def insert_details(cur: sqlite3.Cursor, aid: int, gclient) -> None:
    details = gclient.get_activity_details(aid)
    splits = gclient.get_activity_splits(aid)
    typed_splits = gclient.get_activity_typed_splits(aid)
    split_summaries = gclient.get_activity_split_summaries(aid)
    weather = gclient.get_activity_weather(aid)
    hr_zones = gclient.get_activity_hr_in_timezones(aid)
    sets = gclient.get_activity_exercise_sets(aid)

    metrics_count = None
    if isinstance(details, dict):
        metrics_count = details.get("metricsCount") or details.get("totalMetricsCount")

    cur.execute(
        """
        INSERT OR REPLACE INTO garmin_activity_detail (
            activity_id, metrics_count, metric_descriptors_json, detail_metrics_json,
            splits_json, typed_splits_json, split_summaries_json, weather_json, hr_zones_json, exercise_sets_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            aid,
            metrics_count,
            json.dumps(details.get("metricDescriptors") if isinstance(details, dict) else None),
            json.dumps(details.get("activityDetailMetrics") if isinstance(details, dict) else None),
            json.dumps(splits),
            json.dumps(typed_splits),
            json.dumps(split_summaries),
            json.dumps(weather),
            json.dumps(hr_zones),
            json.dumps(sets),
        ),
    )

    # Normalize HR zones table: clear then insert
    cur.execute("DELETE FROM garmin_activity_hr_zone WHERE activity_id=?", (aid,))
    if isinstance(hr_zones, list):
        for z in hr_zones:
            if isinstance(z, dict):
                cur.execute(
                    "INSERT INTO garmin_activity_hr_zone (activity_id, zone_number, secs_in_zone, low_boundary) VALUES (?,?,?,?)",
                    (
                        aid,
                        z.get("zoneNumber"),
                        z.get("secsInZone"),
                        z.get("zoneLowBoundary"),
                    ),
                )


def _extract_series(details: Dict[str, Any], key: str) -> List[Optional[float]]:
    descs = details.get("metricDescriptors") or []
    idx = None
    for d in descs:
        if isinstance(d, dict) and d.get("key") == key:
            idx = d.get("metricsIndex")
            break
    if idx is None:
        return []
    ser: List[Optional[float]] = []
    for e in details.get("activityDetailMetrics", []) or []:
        if isinstance(e, dict):
            m = e.get("metrics")
            if isinstance(m, list) and idx < len(m):
                v = m[idx]
                ser.append(v if isinstance(v, (int, float)) else None)
    return ser


def _extract_dev_indices(details: Dict[str, Any]) -> List[int]:
    out: List[int] = []
    for d in details.get("metricDescriptors", []) or []:
        if isinstance(d, dict) and isinstance(d.get("key"), str) and d["key"].startswith("connectIQDeveloperField"):
            idx = d.get("metricsIndex")
            if isinstance(idx, int):
                out.append(idx)
    return out


def _compute_hrv_metrics(details: Dict[str, Any]) -> Dict[str, float]:
    # Try to locate IBI (ms) as a developer field whose mean is in [300, 2000]
    hr_series = _extract_series(details, "directHeartRate")
    dev_indices = _extract_dev_indices(details)
    ibi_idx: Optional[int] = None
    best_err = None
    for di in dev_indices:
        ser = []
        for e in details.get("activityDetailMetrics", []) or []:
            m = e.get("metrics") if isinstance(e, dict) else None
            v = m[di] if isinstance(m, list) and di < len(m) else None
            ser.append(v if isinstance(v, (int, float)) else None)
        vals = [v for v in ser if isinstance(v, (int, float))]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        if 300.0 <= mean <= 2000.0:
            # Compare against HR-derived IBI
            pairs: List[Tuple[float, float]] = []
            for v, hr in zip(ser, hr_series):
                if isinstance(v, (int, float)) and isinstance(hr, (int, float)) and hr > 0:
                    pairs.append((float(v), 60000.0 / float(hr)))
            if not pairs:
                continue
            # Mean absolute percentage error
            mape = sum(abs(a - b) / b for a, b in pairs) / len(pairs)
            if best_err is None or mape < best_err:
                best_err = mape
                ibi_idx = di

    # Build IBI series, fallback to HR-derived if needed
    ibi_series: List[float] = []
    if ibi_idx is not None:
        for e in details.get("activityDetailMetrics", []) or []:
            m = e.get("metrics") if isinstance(e, dict) else None
            v = m[ibi_idx] if isinstance(m, list) and ibi_idx < len(m) else None
            if isinstance(v, (int, float)):
                ibi_series.append(float(v))
    else:
        for hr in hr_series:
            if isinstance(hr, (int, float)) and hr > 0:
                ibi_series.append(60000.0 / float(hr))

    if len(ibi_series) < 3:
        return {}

    # Compute HRV metrics from IBI
    diffs: List[float] = []
    for i in range(1, len(ibi_series)):
        diffs.append(ibi_series[i] - ibi_series[i - 1])
    sq = [d * d for d in diffs]
    rmssd = (sum(sq) / len(sq)) ** 0.5
    mean_ibi = sum(ibi_series) / len(ibi_series)
    sdnn = (sum((x - mean_ibi) ** 2 for x in ibi_series) / len(ibi_series)) ** 0.5
    pnn50 = 100.0 * (sum(1 for d in diffs if abs(d) > 50.0) / len(diffs)) if diffs else 0.0

    metrics = {
        "hrv_rmssd_ms": rmssd,
        "hrv_sdnn_ms": sdnn,
        "hrv_pnn50_pct": pnn50,
        "hrv_ibi_ms_mean": mean_ibi,
        "hrv_ibi_ms_min": min(ibi_series),
        "hrv_ibi_ms_max": max(ibi_series),
    }
    return metrics


def insert_attrs(cur: sqlite3.Cursor, aid: int, a: Dict[str, Any], details: Optional[Dict[str, Any]] = None) -> None:
    keys = [
        "avgRespirationRate",
        "minRespirationRate",
        "maxRespirationRate",
        "avgStress",
        "startStress",
        "endStress",
        "differenceStress",
    ]
    cur.execute("DELETE FROM garmin_activity_attr WHERE activity_id=?", (aid,))
    for k in keys:
        v = a.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            cur.execute(
                "INSERT INTO garmin_activity_attr (activity_id, key, value_num) VALUES (?,?,?)",
                (aid, k, float(v)),
            )
        else:
            cur.execute(
                "INSERT INTO garmin_activity_attr (activity_id, key, value_text) VALUES (?,?,?)",
                (aid, k, str(v)),
            )

    # HRV metrics derived from detail metrics (for breathwork/HRV-like activities)
    if isinstance(details, dict):
        hrv = _compute_hrv_metrics(details)
        for k, v in hrv.items():
            cur.execute(
                "INSERT INTO garmin_activity_attr (activity_id, key, value_num) VALUES (?,?,?)",
                (aid, k, float(v)),
            )


def main() -> None:
    load_dotenv()
    args = parse_args()

    client = GarminClient.from_env()
    client.login()
    g = client._client

    today = date.today()
    start = (today - timedelta(days=args.days - 1)).isoformat()
    end = today.isoformat()

    acts: List[Dict[str, Any]] = g.get_activities_by_date(start, end)

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    for a in acts:
        aid = int(a.get("activityId"))
        # Derive run_type using splits/summaries for running activities; else None/steady
        run_type: Optional[str] = None
        tkey = _type_key(a) or ""
        if isinstance(tkey, str) and tkey.lower() == "running":
            splits = g.get_activity_splits(aid)
            split_summaries = g.get_activity_split_summaries(aid)
            run_type = _run_type_from_laps(splits, split_summaries)
        insert_activity(cur, a, run_type)
        # Fetch details once and use for both detail insert and HRV derivation
        details = g.get_activity_details(aid)
        splits = g.get_activity_splits(aid)
        typed_splits = g.get_activity_typed_splits(aid)
        split_summaries = g.get_activity_split_summaries(aid)
        weather = g.get_activity_weather(aid)
        hr_zones = g.get_activity_hr_in_timezones(aid)
        sets = g.get_activity_exercise_sets(aid)

        metrics_count = None
        if isinstance(details, dict):
            metrics_count = details.get("metricsCount") or details.get("totalMetricsCount")

        cur.execute(
            """
            INSERT OR REPLACE INTO garmin_activity_detail (
                activity_id, metrics_count, metric_descriptors_json, detail_metrics_json,
                splits_json, typed_splits_json, split_summaries_json, weather_json, hr_zones_json, exercise_sets_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                aid,
                metrics_count,
                json.dumps(details.get("metricDescriptors") if isinstance(details, dict) else None),
                json.dumps(details.get("activityDetailMetrics") if isinstance(details, dict) else None),
                json.dumps(splits),
                json.dumps(typed_splits),
                json.dumps(split_summaries),
                json.dumps(weather),
                json.dumps(hr_zones),
                json.dumps(sets),
            ),
        )

        # Normalize HR zones table for this activity
        cur.execute("DELETE FROM garmin_activity_hr_zone WHERE activity_id=?", (aid,))
        if isinstance(hr_zones, list):
            for z in hr_zones:
                if isinstance(z, dict):
                    cur.execute(
                        "INSERT INTO garmin_activity_hr_zone (activity_id, zone_number, secs_in_zone, low_boundary) VALUES (?,?,?,?)",
                        (
                            aid,
                            z.get("zoneNumber"),
                            z.get("secsInZone"),
                            z.get("zoneLowBoundary"),
                        ),
                    )

        insert_attrs(cur, aid, a, details)

    con.commit()

    # Validation: print 3 recent running rows
    for row in cur.execute(
        """
        SELECT activity_id, type_key, distance_m, duration_s, training_effect_aer, training_effect_ana, max_hr
        FROM garmin_activity
        WHERE type_key='running'
        ORDER BY start_time_local DESC
        LIMIT 3
        """
    ):
        print(row)

    con.close()


if __name__ == "__main__":
    main()
