from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def _iso_from_epoch_ms(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    # Represent as ISO 8601 in UTC for consistency
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _mean(vals: Iterable[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if isinstance(v, (int, float))]
    return (sum(xs) / len(xs)) if xs else None


def _extract_hr_stats(s: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    hr = s.get("sleepHeartRate")
    vals: List[float] = []
    if isinstance(hr, list):
        for e in hr:
            if isinstance(e, dict) and isinstance(e.get("value"), (int, float)):
                vals.append(float(e["value"]))
    elif isinstance(hr, dict):
        arr = hr.get("valuesArray") or []
        vals = [float(v) for v in arr if isinstance(v, (int, float))]
    if not vals:
        return None, None, None
    return min(vals), _mean(vals), max(vals)


def _extract_stress_avg(s: Dict[str, Any]) -> Optional[float]:
    st = s.get("sleepStress")
    if isinstance(st, list):
        vals = [float(e["value"]) for e in st if isinstance(e, dict) and isinstance(e.get("value"), (int, float))]
        return (sum(vals) / len(vals)) if vals else None
    if isinstance(st, dict):
        arr = st.get("valuesArray") or []
        return _mean(arr)
    return None


def _extract_bb_metrics(s: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    bb = s.get("sleepBodyBattery")
    seq: List[float] = []
    if isinstance(bb, list):
        seq = [float(e["value"]) for e in bb if isinstance(e, dict) and isinstance(e.get("value"), (int, float))]
    elif isinstance(bb, dict):
        arr = bb.get("valuesArray") or []
        seq = [float(v) for v in arr if isinstance(v, (int, float))]
    if not seq:
        delta = s.get("bodyBatteryChange")
        return None, None, float(delta) if isinstance(delta, (int, float)) else None
    start = seq[0]
    end = seq[-1]
    return start, end, end - start


def _extract_sleep_score(s: Dict[str, Any]) -> Optional[float]:
    ss = s.get("sleepScores") or {}
    ov = ss.get("overall") if isinstance(ss, dict) else None
    val = None if not isinstance(ov, dict) else ov.get("value")
    return float(val) if isinstance(val, (int, float)) else None


def _parse_gmt(ts: str) -> datetime:
    # Example: '2025-10-04T22:46:00.0' (no timezone marker). Treat as naive UTC.
    return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.0')


def _wake_metrics_from_levels(levels: Any) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    if not isinstance(levels, list) or not levels:
        return None, None, None
    # Map codes: 0=deep, 1=light, 2=rem, 3=awake (validated via sums vs daily)
    entries: List[Tuple[datetime, datetime, float]] = []
    for e in levels:
        if not isinstance(e, dict):
            continue
        st = e.get('startGMT'); en = e.get('endGMT'); code = e.get('activityLevel')
        if isinstance(st, str) and isinstance(en, str) and isinstance(code, (int, float)):
            try:
                entries.append((_parse_gmt(st), _parse_gmt(en), float(code)))
            except Exception:
                continue
    if not entries:
        return None, None, None
    entries.sort(key=lambda x: x[0])

    asleep_started = False
    latency = 0.0
    waso = 0.0
    wakeups = 0
    in_awake_block = False

    for st, en, code in entries:
        dur = (en - st).total_seconds()
        is_awake = (int(code) == 3)
        if not asleep_started:
            if is_awake:
                latency += dur
            else:
                asleep_started = True
        else:
            if is_awake:
                waso += dur
                if not in_awake_block:
                    wakeups += 1
                    in_awake_block = True
            else:
                in_awake_block = False

    return (latency if latency > 0 else 0.0), (waso if waso > 0 else 0.0), (wakeups if wakeups > 0 else 0)


def _extract_respiration_daily(daily: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    return (
        (float(daily.get("averageRespirationValue")) if isinstance(daily.get("averageRespirationValue"), (int, float)) else None),
        (float(daily.get("lowestRespirationValue")) if isinstance(daily.get("lowestRespirationValue"), (int, float)) else None),
        (float(daily.get("highestRespirationValue")) if isinstance(daily.get("highestRespirationValue"), (int, float)) else None),
    )


def _extract_spo2_daily(daily: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    return (
        (float(daily.get("averageSpO2Value")) if isinstance(daily.get("averageSpO2Value"), (int, float)) else None),
        (float(daily.get("lowestSpO2Value")) if isinstance(daily.get("lowestSpO2Value"), (int, float)) else None),
    )


def _pct(n: Optional[float], d: Optional[float]) -> Optional[float]:
    if not isinstance(n, (int, float)) or not isinstance(d, (int, float)) or d == 0:
        return None
    return float(n) / float(d)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Garmin sleep nightly into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    return p.parse_args()


def build_row(s: Dict[str, Any]) -> Dict[str, Any]:
    daily = s["dailySleepDTO"]
    date_for = daily.get("calendarDate")
    start_gmt = daily.get("sleepStartTimestampGMT")
    end_gmt = daily.get("sleepEndTimestampGMT")
    start_local = daily.get("sleepStartTimestampLocal")
    end_local = daily.get("sleepEndTimestampLocal")

    time_in_bed_s = (float(end_gmt) - float(start_gmt)) / 1000.0
    time_asleep_s = float(daily.get("sleepTimeSeconds"))
    duration_s = time_in_bed_s
    sleep_eff = time_asleep_s / time_in_bed_s if time_in_bed_s > 0 else None

    deep_s = float(daily.get("deepSleepSeconds"))
    light_s = float(daily.get("lightSleepSeconds"))
    rem_s = float(daily.get("remSleepSeconds"))
    awake_s = float(daily.get("awakeSleepSeconds"))
    denom = deep_s + light_s + rem_s + awake_s

    hr_min, hr_avg, hr_max = _extract_hr_stats(s)
    resp_avg, resp_min, resp_max = _extract_respiration_daily(daily)
    spo2_avg, spo2_min = _extract_spo2_daily(daily)
    stress_avg = _extract_stress_avg(s)
    bb_start, bb_end, bb_delta = _extract_bb_metrics(s)
    rhr = float(s.get("restingHeartRate")) if isinstance(s.get("restingHeartRate"), (int, float)) else None
    sleep_score = _extract_sleep_score(s)

    # Wake metrics
    levels = s.get('sleepLevels')
    latency_s, waso_s, wakeups = _wake_metrics_from_levels(levels)

    row = {
        "date_for": str(date_for),
        "start_time_local": _iso_from_epoch_ms(start_local),
        "end_time_local": _iso_from_epoch_ms(end_local),
        "duration_s": duration_s,
        "time_in_bed_s": time_in_bed_s,
        "time_asleep_s": time_asleep_s,
        "sleep_efficiency": sleep_eff,
        "latency_s": latency_s,
        "waso_s": waso_s,
        "wakeup_count": wakeups,
        "deep_s": deep_s,
        "light_s": light_s,
        "rem_s": rem_s,
        "awake_s": awake_s,
        "deep_pct": _pct(deep_s, denom),
        "light_pct": _pct(light_s, denom),
        "rem_pct": _pct(rem_s, denom),
        "awake_pct": _pct(awake_s, denom),
        "hr_min": hr_min,
        "hr_avg": hr_avg,
        "hr_max": hr_max,
        "resting_heart_rate": rhr,
        "resp_avg": resp_avg,
        "resp_min": resp_min,
        "resp_max": resp_max,
        "spo2_avg": spo2_avg,
        "spo2_min": spo2_min,
        "spo2_time_below_90_s": None,
        "sleep_stress_avg": stress_avg,
        "bb_start": bb_start,
        "bb_end": bb_end,
        "bb_delta": bb_delta,
        "sleep_score": sleep_score,
        "device_id": None,
        "source": "garmin",
    }
    return row


def insert_rows(db_path: Path, rows: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Overwrite per date_for to keep one row/night
    for mapped, raw in rows:
        cur.execute("DELETE FROM sleep_nightly WHERE date_for=? AND source='garmin'", (mapped["date_for"],))
        cols = [
            "date_for","start_time_local","end_time_local","duration_s","time_in_bed_s","time_asleep_s","sleep_efficiency",
            "latency_s","waso_s","wakeup_count",
            "deep_s","light_s","rem_s","awake_s",
            "deep_pct","light_pct","rem_pct","awake_pct",
            "hr_min","hr_avg","hr_max","resting_heart_rate",
            "resp_avg","resp_min","resp_max",
            "spo2_avg","spo2_min","spo2_time_below_90_s",
            "sleep_stress_avg","bb_start","bb_end","bb_delta","sleep_score","device_id","source","raw_json"
        ]
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT INTO sleep_nightly ({','.join(cols)}) VALUES ({placeholders})"
        cur.execute(sql, [mapped.get(c) for c in cols[:-1]] + [json.dumps(raw)])

    con.commit()

    # Validation: print 5 nights
    for r in cur.execute(
        "SELECT date_for, time_asleep_s, sleep_efficiency, latency_s, waso_s, wakeup_count, hr_min, hr_avg, hr_max FROM sleep_nightly ORDER BY date_for DESC LIMIT 5"
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
        s = g.get_sleep_data(ds)
        if not isinstance(s, dict) or not isinstance(s.get("dailySleepDTO"), dict):
            continue
        mapped = build_row(s)
        rows.append((mapped, s))

    # Sort by date_for ascending
    rows.sort(key=lambda x: x[0]["date_for"])
    insert_rows(args.db, rows)


if __name__ == "__main__":
    main()
