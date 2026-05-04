from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Org table rows into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    p.add_argument("--src", type=Path, default=Path("memory-bank/org_tables.jsonl"), help="JSONL source path")
    return p.parse_args()


def _to_float(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) else None


def _as_date(s: Any) -> Optional[date]:
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
    return out


def main() -> None:
    args = parse_args()

    today = date.today()
    start = today - timedelta(days=args.days - 1)

    items = load_jsonl(args.src)
    filtered: List[Dict[str, Any]] = []
    for obj in items:
        d = _as_date(obj.get("date"))
        if d is None:
            continue
        if start <= d <= today:
            filtered.append(obj)

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    # Idempotent within window
    cur.execute("DELETE FROM org_row WHERE date >= ? AND date <= ?", (start.isoformat(), today.isoformat()))

    for obj in filtered:
        exercise_title = obj.get("exercise_title")
        if not isinstance(exercise_title, str) or not exercise_title:
            continue
        scheme = obj.get("scheme")
        scheme = str(scheme) if scheme is not None else None
        dstr = str(obj.get("date"))
        delta = obj.get("delta")
        delta = str(delta) if delta is not None else None
        weight = _to_float(obj.get("weight"))
        time_sec = _to_float(obj.get("time"))
        sum_val = _to_float(obj.get("sum"))
        comment = obj.get("comment")
        if comment is None and "" in obj:
            c2 = obj.get("")
            comment = c2 if isinstance(c2, str) else comment

        heading_path = obj.get("heading_path")
        if not isinstance(heading_path, list):
            heading_path = []
        heading_path_json = json.dumps(heading_path, ensure_ascii=False)

        # sets_json: any key like setN (N int)
        sets: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.startswith("set"):
                try:
                    int(k[3:]) if k.startswith("set") else None
                    sets[k] = v
                except Exception:
                    pass
        sets_json = json.dumps(sets, ensure_ascii=False) if sets else None

        # metrics_json: any leftover key that isn't core, isn't set*, isn't heading_path
        metrics: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("date", "delta", "weight", "time", "sum", "comment", "exercise_title", "scheme", "heading_path", ""):
                continue
            if isinstance(k, str) and k.startswith("set"):
                continue
            metrics[k] = v
        metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics else None

        cur.execute(
            """
            INSERT INTO org_row (
              exercise_title, scheme, date, delta, weight, time_sec, sum, comment, heading_path_json, sets_json, metrics_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                exercise_title,
                scheme,
                dstr,
                delta,
                weight,
                time_sec,
                sum_val,
                comment,
                heading_path_json,
                sets_json,
                metrics_json,
            ),
        )

    con.commit()

    # Validation: show a few recent rows
    for r in cur.execute(
        "SELECT exercise_title, scheme, date, weight, time_sec, sum, substr(heading_path_json,1,60) FROM org_row ORDER BY date DESC, exercise_title LIMIT 10"
    ):
        print(r)
    con.close()


if __name__ == "__main__":
    main()
