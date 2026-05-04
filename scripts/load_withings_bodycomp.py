from __future__ import annotations

from datetime import datetime, timedelta, timezone
import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from dotenv import load_dotenv
from withings_api.common import MeasureType, MeasureGetMeasGroupCategory

from src.withings_client import WithingsClient


def _as_type_id(mtype: Any) -> int:
    if isinstance(mtype, MeasureType):
        return int(mtype.value)
    return int(mtype)


def _iter_measures(measures: Iterable[Any]) -> Iterable[Dict[str, Any]]:
    for m in measures or []:
        if isinstance(m, dict):
            yield m
        else:
            yield {
                "type": getattr(m, "type", None),
                "value": getattr(m, "value", None),
                "unit": getattr(m, "unit", None),
            }


def decode_measures(measures: Iterable[Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for m in _iter_measures(measures):
        mtype = _as_type_id(m.get("type"))
        val = m.get("value")
        unit = m.get("unit")  # power of 10 exponent
        if val is None or unit is None:
            continue
        scaled = float(val) * (10 ** float(unit))
        try:
            key = MeasureType(mtype).name.lower()
        except Exception:
            key = f"type_{mtype}"
        out[key] = scaled
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Withings body composition into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Number of days back from now (UTC)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    return p.parse_args()


def fetch_bodycomp(start: datetime, end: datetime) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    client = WithingsClient.from_tokens_file()
    resp = client.api.measure_get_meas(
        startdate=start,
        enddate=end,
        category=MeasureGetMeasGroupCategory.REAL,
        lastupdate=None,
    )
    groups = getattr(resp, "measuregrps", []) or []

    rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for g in groups:
        dval = getattr(g, "date", 0)
        if hasattr(dval, "int_timestamp"):
            ts = int(dval.int_timestamp)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            ts = int(dval)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        measures = getattr(g, "measures", []) or []
        decoded = decode_measures(measures)

        # Map Withings measure keys -> DB columns
        mapped = {
            "ts_utc": dt.isoformat(),
            "weight_kg": decoded.get("weight"),
            "fat_ratio": decoded.get("fat_ratio"),
            "fat_mass_kg": decoded.get("fat_mass_weight"),
            "fat_free_mass_kg": decoded.get("fat_free_mass"),
            "muscle_mass_kg": decoded.get("muscle_mass"),
            "bone_mass_kg": decoded.get("bone_mass"),
            "hydration_pct": decoded.get("hydration"),
            "pwv_mps": decoded.get("pulse_wave_velocity"),
            "heart_rate_bpm": decoded.get("heart_rate"),
        }

        # Raw group payload (normalized)
        raw = {
            "date": ts,
            "category": getattr(g, "category", None),
            "attrib": getattr(g, "attrib", None),
            "measures": list(_iter_measures(measures)),
        }

        rows.append((mapped, raw))

    # Sort ascending by timestamp for deterministic inserts
    rows.sort(key=lambda x: x[0]["ts_utc"])
    return rows


def insert_rows(db_path: Path, rows: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    if rows:
        start_ts = rows[0][0]["ts_utc"]
        end_ts = rows[-1][0]["ts_utc"]
        cur.execute(
            "DELETE FROM withings_bodycomp WHERE ts_utc BETWEEN ? AND ?",
            (start_ts, end_ts),
        )

    sql = (
        "INSERT INTO withings_bodycomp (ts_utc, weight_kg, fat_ratio, fat_mass_kg, "
        "fat_free_mass_kg, muscle_mass_kg, bone_mass_kg, hydration_pct, pwv_mps, "
        "heart_rate_bpm, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    )
    for mapped, raw in rows:
        cur.execute(
            sql,
            (
                mapped["ts_utc"],
                mapped["weight_kg"],
                mapped["fat_ratio"],
                mapped["fat_mass_kg"],
                mapped["fat_free_mass_kg"],
                mapped["muscle_mass_kg"],
                mapped["bone_mass_kg"],
                mapped["hydration_pct"],
                mapped["pwv_mps"],
                mapped["heart_rate_bpm"],
                json.dumps(raw),
            ),
        )
    con.commit()

    # Validation: print first 5 rows in inserted range
    if rows:
        start_ts = rows[0][0]["ts_utc"]
        end_ts = rows[-1][0]["ts_utc"]
        print("Inserted rows:")
        for r in cur.execute(
            "SELECT ts_utc, weight_kg, fat_ratio, pwv_mps, heart_rate_bpm "
            "FROM withings_bodycomp WHERE ts_utc BETWEEN ? AND ? ORDER BY ts_utc LIMIT 5",
            (start_ts, end_ts),
        ):
            print(r)

        # NULL scan for key columns
        cols = [
            "weight_kg",
            "fat_ratio",
            "fat_mass_kg",
            "fat_free_mass_kg",
            "muscle_mass_kg",
            "bone_mass_kg",
            "hydration_pct",
            "pwv_mps",
            "heart_rate_bpm",
        ]
        total = cur.execute(
            "SELECT COUNT(*) FROM withings_bodycomp WHERE ts_utc BETWEEN ? AND ?",
            (start_ts, end_ts),
        ).fetchone()[0]
        print(f"Range total: {total}")
        for c in cols:
            nulls = cur.execute(
                f"SELECT COUNT(*) FROM withings_bodycomp WHERE ts_utc BETWEEN ? AND ? AND {c} IS NULL",
                (start_ts, end_ts),
            ).fetchone()[0]
            print(f"NULLs {c}: {nulls}")

    con.close()


def main() -> None:
    load_dotenv()
    args = parse_args()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=args.days)
    rows = fetch_bodycomp(start, now)
    print(f"Fetched groups: {len(rows)} in range {start.isoformat()} .. {now.isoformat()}")
    insert_rows(args.db, rows)


if __name__ == "__main__":
    main()
