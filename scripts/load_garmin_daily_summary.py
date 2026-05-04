from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def _mean(xs: Iterable[Optional[float]]) -> Optional[float]:
    vals = [float(x) for x in xs if isinstance(x, (int, float))]
    return (sum(vals) / len(vals)) if vals else None


def _secs_per_sample_from_window(start_ms: Optional[int], end_ms: Optional[int], n: int) -> Optional[float]:
    if not isinstance(start_ms, (int, float)) or not isinstance(end_ms, (int, float)) or n <= 0:
        return None
    span_s = (float(end_ms) - float(start_ms)) / 1000.0
    if span_s <= 0:
        return None
    return span_s / float(n)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Garmin daily summary into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    return p.parse_args()


def build_row(ds: str, g) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    user_summary = g.get_user_summary(ds)
    stats = g.get_stats(ds)
    heart = g.get_heart_rates(ds)
    stress = g.get_stress_data(ds)
    intensity = g.get_intensity_minutes_data(ds)
    floors = g.get_floors(ds)

    # Steps and distance
    total_steps = user_summary.get("totalSteps") if isinstance(user_summary, dict) else None
    total_distance_m = user_summary.get("totalDistanceMeters") if isinstance(user_summary, dict) else None

    # Calories
    total_kcal = user_summary.get("totalKilocalories") if isinstance(user_summary, dict) else None
    active_kcal = user_summary.get("activeKilocalories") if isinstance(user_summary, dict) else None
    bmr_kcal = user_summary.get("bmrKilocalories") if isinstance(user_summary, dict) else None

    # Heart rate daily
    rest_hr = None
    min_hr = None
    max_hr = None
    if isinstance(heart, dict):
        rest_hr = heart.get("restingHeartRate")
        min_hr = heart.get("minHeartRate")
        max_hr = heart.get("maxHeartRate")

    # Stress daily
    avg_stress = None
    stress_duration_s = None
    if isinstance(stress, dict):
        avg_stress = stress.get("avgStressLevel")
        arr = stress.get("stressValuesArray")
        start_gmt = stress.get("startTimestampGMT")
        end_gmt = stress.get("endTimestampGMT")
        if isinstance(arr, list) and isinstance(start_gmt, (int, float)) and isinstance(end_gmt, (int, float)):
            spc = _secs_per_sample_from_window(int(start_gmt), int(end_gmt), len(arr))
            if isinstance(spc, (int, float)):
                stress_duration_s = sum(spc for v in arr if isinstance(v, (int, float)) and v > 0)

    # Intensity minutes
    moderate_minutes = None
    vigorous_minutes = None
    intensity_minutes_total = None
    if isinstance(intensity, dict):
        moderate_minutes = intensity.get("moderateMinutes")
        vigorous_minutes = intensity.get("vigorousMinutes")
        if isinstance(moderate_minutes, (int, float)) or isinstance(vigorous_minutes, (int, float)):
            m = float(moderate_minutes or 0)
            v = float(vigorous_minutes or 0)
            intensity_minutes_total = int(m + 2 * v)

    # Floors
    floors_up = None
    floors_down = None
    if isinstance(floors, dict):
        floors_up = floors.get("floorsClimbed")
        floors_down = floors.get("floorsDescended")

    row = {
        "date_for": ds,
        "total_steps": total_steps,
        "total_distance_m": total_distance_m,
        "total_kcal": total_kcal,
        "active_kcal": active_kcal,
        "bmr_kcal": bmr_kcal,
        "rest_hr": rest_hr,
        "min_hr": min_hr,
        "max_hr": max_hr,
        "avg_stress": avg_stress,
        "stress_duration_s": int(stress_duration_s) if isinstance(stress_duration_s, (int, float)) else None,
        "intensity_minutes_total": intensity_minutes_total,
        "moderate_minutes": moderate_minutes,
        "vigorous_minutes": vigorous_minutes,
        "floors_up": floors_up,
        "floors_down": floors_down,
    }

    raw = {
        "user_summary": user_summary,
        "stats": stats,
        "heart_rate": heart,
        "stress": stress,
        "intensity": intensity,
        "floors": floors,
    }
    return row, raw


def insert_rows(db_path: Path, rows: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    sql = (
        "INSERT OR REPLACE INTO garmin_daily_summary (date_for, total_steps, total_distance_m, total_kcal, active_kcal, bmr_kcal, "
        "rest_hr, min_hr, max_hr, avg_stress, stress_duration_s, intensity_minutes_total, moderate_minutes, vigorous_minutes, floors_up, floors_down, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    for mapped, raw in rows:
        cur.execute(sql, (
            mapped["date_for"],
            mapped.get("total_steps"),
            mapped.get("total_distance_m"),
            mapped.get("total_kcal"),
            mapped.get("active_kcal"),
            mapped.get("bmr_kcal"),
            mapped.get("rest_hr"),
            mapped.get("min_hr"),
            mapped.get("max_hr"),
            mapped.get("avg_stress"),
            mapped.get("stress_duration_s"),
            mapped.get("intensity_minutes_total"),
            mapped.get("moderate_minutes"),
            mapped.get("vigorous_minutes"),
            mapped.get("floors_up"),
            mapped.get("floors_down"),
            json.dumps(raw),
        ))
    con.commit()

    # Validation: print 5 days
    for r in cur.execute(
        "SELECT date_for, total_steps, total_kcal, rest_hr, min_hr, max_hr, avg_stress, intensity_minutes_total, floors_up, floors_down FROM garmin_daily_summary ORDER BY date_for DESC LIMIT 5"
    ):
        print(r)
    con.close()


def main() -> None:
    load_dotenv()
    args = parse_args()
    client = GarminClient.from_env()
    client.login()
    g = client._client

    today = date.today()
    rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for i in range(args.days):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        mapped, raw = build_row(ds, g)
        rows.append((mapped, raw))
    rows.sort(key=lambda x: x[0]["date_for"])
    insert_rows(args.db, rows)


if __name__ == "__main__":
    main()
