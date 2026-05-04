from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Garmin 15-min intraday aggregates into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    return p.parse_args()


def bucket_labels(ds: str) -> List[str]:
    # Local buckets as naive local times aligned to 00/15/30/45
    labels: List[str] = []
    base = datetime.fromisoformat(ds)
    for i in range(96):
        t = base + timedelta(minutes=15 * i)
        labels.append(t.strftime("%Y-%m-%d %H:%M:00"))
    return labels


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in values if isinstance(v, (int, float))]
    return (sum(xs) / len(xs)) if xs else None


def assign_by_ordinal(n: int) -> List[int]:
    # Map ordinal index -> bucket index best-effort (when data already 15-min blocks)
    out = list(range(96))
    if n >= 96:
        return out[:96]
    # If fewer than 96, spread as evenly as possible
    idxs = []
    for i in range(n):
        idx = int(round(i * 96.0 / n))
        idxs.append(min(95, idx))
    return idxs


def _parse_gmt_iso_ms(s: Optional[str]) -> Optional[int]:
    if not isinstance(s, str):
        return None
    # Example: '2025-10-03T22:00:00.0' (GMT)
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.0").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def stress_bb_bucket_means(payload: Dict[str, Any]) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    n_buckets = 96
    stress_means: List[Optional[float]] = [None] * n_buckets
    bb_means: List[Optional[float]] = [None] * n_buckets
    arr_s = payload.get("stressValuesArray")
    arr_bb = payload.get("bodyBatteryValuesArray")
    anchor_ms = _parse_gmt_iso_ms(payload.get("startTimestampGMT")) or _parse_gmt_iso_ms(payload.get("startTimestampLocal"))
    if anchor_ms is None:
        return stress_means, bb_means

    if isinstance(arr_s, list):
        buckets: List[List[float]] = [[] for _ in range(n_buckets)]
        for e in arr_s:
            ts = None; val = None
            if isinstance(e, (list, tuple)):
                ts = e[0] if len(e) > 0 else None
                val = e[1] if len(e) > 1 else None
            elif isinstance(e, dict):
                ts = e.get("t") or e.get("timestamp")
                val = e.get("value")
            if not isinstance(ts, (int, float)) or not isinstance(val, (int, float)):
                continue
            b = int((float(ts) - float(anchor_ms)) // 900000.0)
            if 0 <= b < n_buckets:
                buckets[b].append(float(val))
        stress_means = [mean(b) for b in buckets]

    if isinstance(arr_bb, list):
        buckets: List[List[float]] = [[] for _ in range(n_buckets)]
        for e in arr_bb:
            ts = None; val = None
            if isinstance(e, (list, tuple)):
                ts = e[0] if len(e) > 0 else None
                # value may be at index 2 (status at 1). Try 2 then 1
                v2 = e[2] if len(e) > 2 else None
                v1 = e[1] if len(e) > 1 else None
                val = v2 if isinstance(v2, (int, float)) else (v1 if isinstance(v1, (int, float)) else None)
            elif isinstance(e, dict):
                ts = e.get("t") or e.get("timestamp")
                val = e.get("value")
            if not isinstance(ts, (int, float)) or not isinstance(val, (int, float)):
                continue
            b = int((float(ts) - float(anchor_ms)) // 900000.0)
            if 0 <= b < n_buckets:
                buckets[b].append(float(val))
        bb_means = [mean(b) for b in buckets]
    return stress_means, bb_means


def heart_rate_bucket_means(payload: Dict[str, Any]) -> List[Optional[float]]:
    n_buckets = 96
    out: List[List[float]] = [[] for _ in range(n_buckets)]
    anchor_ms = _parse_gmt_iso_ms(payload.get("startTimestampGMT")) or _parse_gmt_iso_ms(payload.get("startTimestampLocal"))
    vals = payload.get("heartRateValues")
    if isinstance(anchor_ms, (int, float)) and isinstance(vals, list):
        for e in vals:
            ts = None; v = None
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                ts, v = e[0], e[1]
            elif isinstance(e, dict):
                ts = e.get("t") or e.get("timestamp")
                v = e.get("bpm") or e.get("value")
            if not isinstance(ts, (int, float)) or not isinstance(v, (int, float)):
                continue
            b = int((float(ts) - float(anchor_ms)) // 900000.0)
            if 0 <= b < n_buckets:
                out[b].append(float(v))
    return [mean(bucket) for bucket in out]


def respiration_bucket_means(payload: Dict[str, Any]) -> List[Optional[float]]:
    n_buckets = 96
    out: List[Optional[float]] = [None] * n_buckets
    arr = payload.get("respirationValuesArray")
    anchor_ms = _parse_gmt_iso_ms(payload.get("startTimestampGMT")) or _parse_gmt_iso_ms(payload.get("startTimestampLocal"))
    if isinstance(anchor_ms, (int, float)) and isinstance(arr, list) and len(arr) > 0:
        buckets: List[List[float]] = [[] for _ in range(n_buckets)]
        for e in arr:
            ts = None; v = None
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                ts, v = e[0], e[1]
            elif isinstance(e, dict):
                ts = e.get("t") or e.get("timestamp")
                v = e.get("value")
            if not isinstance(ts, (int, float)) or not isinstance(v, (int, float)):
                continue
            b = int((float(ts) - float(anchor_ms)) // 900000.0)
            if 0 <= b < n_buckets:
                buckets[b].append(float(v))
        out = [mean(b) for b in buckets]
    return out


def load_day(ds: str, g, con: sqlite3.Connection) -> None:
    labels = bucket_labels(ds)
    cur = con.cursor()
    cur.execute("DELETE FROM garmin_15min WHERE date_for=?", (ds,))

    # Fetch sources
    steps = g.get_steps_data(ds)
    # Prefer all-day stress endpoint if available; falls back to per-day stress
    try:
        stress = g.get_all_day_stress(ds)
    except Exception:
        stress = g.get_stress_data(ds)
    hr = g.get_heart_rates(ds)
    resp = g.get_respiration_data(ds)

    steps_values: List[Optional[int]] = [None] * 96
    steps_levels: List[Optional[str]] = [None] * 96
    if isinstance(steps, list) and len(steps) > 0:
        # Best-effort ordinal mapping when blocks are aligned to 15-min
        idxs = assign_by_ordinal(len(steps))
        for i, block in enumerate(steps[:96]):
            b = idxs[i] if i < len(idxs) else i
            val = block.get("steps") if isinstance(block, dict) else None
            lvl = block.get("activityLevel") if isinstance(block, dict) else None
            steps_values[b] = int(val) if isinstance(val, (int, float)) else None
            steps_levels[b] = str(lvl) if lvl is not None else steps_levels[b]

    stress_means, bb_means = ([], [])
    if isinstance(stress, dict):
        stress_means, bb_means = stress_bb_bucket_means(stress)
    else:
        stress_means = [None] * 96
        bb_means = [None] * 96

    hr_means = heart_rate_bucket_means(hr if isinstance(hr, dict) else {}) if isinstance(hr, dict) else [None] * 96
    resp_means = respiration_bucket_means(resp if isinstance(resp, dict) else {}) if isinstance(resp, dict) else [None] * 96

    sql = (
        "INSERT OR REPLACE INTO garmin_15min (date_for, start_local, steps, stress_mean, body_battery_mean, hr_mean, resp_mean, activity_level, source) "
        "VALUES (?,?,?,?,?,?,?,?, 'garmin')"
    )
    for i in range(96):
        cur.execute(
            sql,
            (
                ds,
                labels[i],
                steps_values[i],
                stress_means[i],
                bb_means[i],
                hr_means[i],
                resp_means[i],
                steps_levels[i],
            ),
        )
    con.commit()

    # Validation: show first/last bucket for this day
    print(ds, cur.execute(
        "SELECT start_local, steps, ROUND(stress_mean,1), ROUND(body_battery_mean,1), ROUND(hr_mean,1), ROUND(resp_mean,1) "
        "FROM garmin_15min WHERE date_for=? ORDER BY start_local LIMIT 1",
        (ds,)
    ).fetchone())
    print(ds, cur.execute(
        "SELECT start_local, steps, ROUND(stress_mean,1), ROUND(body_battery_mean,1), ROUND(hr_mean,1), ROUND(resp_mean,1) "
        "FROM garmin_15min WHERE date_for=? ORDER BY start_local DESC LIMIT 1",
        (ds,)
    ).fetchone())


def main() -> None:
    load_dotenv()
    args = parse_args()

    client = GarminClient.from_env()
    client.login()
    g = client._client

    con = sqlite3.connect(args.db)
    today = date.today()
    for i in range(args.days):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        load_day(ds, g, con)
    con.close()


if __name__ == "__main__":
    main()
