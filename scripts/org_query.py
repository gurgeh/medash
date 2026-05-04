from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Browse org_row entries by exercise and date range")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    p.add_argument("--exercise", type=str, default=None, help="Exercise title (exact or substring if --contains)")
    p.add_argument("--contains", action="store_true", help="Match exercise substring instead of exact")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive) if --start/--end not provided")
    p.add_argument("--start", type=str, default=None, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=20, help="Max rows to print")
    p.add_argument("--show-sets", action="store_true", help="Print sets_json column")
    p.add_argument("--show-metrics", action="store_true", help="Print metrics_json column")
    p.add_argument("--list-exercises", action="store_true", help="List distinct exercises in range and exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.start and args.end:
        start = args.start
        end = args.end
    else:
        today = date.today()
        start = (today - timedelta(days=args.days - 1)).isoformat()
        end = today.isoformat()

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    if args.list_exercises:
        if args.exercise:
            if args.contains:
                rows = cur.execute(
                    "SELECT DISTINCT exercise_title FROM org_row WHERE date BETWEEN ? AND ? AND exercise_title LIKE ? ORDER BY exercise_title",
                    (start, end, f"%{args.exercise}%"),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT DISTINCT exercise_title FROM org_row WHERE date BETWEEN ? AND ? AND exercise_title=? ORDER BY exercise_title",
                    (start, end, args.exercise),
                ).fetchall()
        else:
            rows = cur.execute(
                "SELECT DISTINCT exercise_title FROM org_row WHERE date BETWEEN ? AND ? ORDER BY exercise_title",
                (start, end),
            ).fetchall()
        print("Exercises (distinct):")
        for (name,) in rows:
            print("-", name)
        con.close()
        return

    sql = (
        "SELECT exercise_title, scheme, date, weight, time_sec, sum, comment, sets_json, metrics_json "
        "FROM org_row WHERE date BETWEEN ? AND ?"
    )
    params: list[object] = [start, end]
    if args.exercise:
        if args.contains:
            sql += " AND exercise_title LIKE ?"
            params.append(f"%{args.exercise}%")
        else:
            sql += " AND exercise_title=?"
            params.append(args.exercise)
    sql += " ORDER BY date DESC, exercise_title LIMIT ?"
    params.append(args.limit)

    for row in cur.execute(sql, params):
        (title, scheme, d, weight, time_sec, s, comment, sets_json, metrics_json) = row
        print(f"{d} — {title} [{scheme}] weight={weight} time_sec={time_sec} sum={s}")
        if comment:
            print(f"  comment: {comment}")
        if args.show_sets and sets_json:
            print("  sets:", sets_json)
        if args.show_metrics and metrics_json:
            print("  metrics:", metrics_json)

    con.close()


if __name__ == "__main__":
    main()
