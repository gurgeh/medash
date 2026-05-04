from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load journal entries and todos into medash.sqlite")
    p.add_argument("--days", type=int, default=30, help="Days back from today (inclusive)")
    p.add_argument("--db", type=Path, default=Path("data/medash.sqlite"), help="SQLite DB path")
    p.add_argument("--src", type=Path, default=Path("memory-bank/journal_entries.jsonl"), help="JSONL source path")
    return p.parse_args()


def to_int_bool(x: Any) -> Optional[int]:
    if isinstance(x, bool):
        return 1 if x else 0
    if isinstance(x, (int, float)):
        return 1 if x else 0
    return None


def load_source(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def main() -> None:
    args = parse_args()
    today = date.today()
    start = today - timedelta(days=args.days - 1)

    items = load_source(args.src)
    # Filter by date_for within window
    def in_window(d: str) -> bool:
        try:
            dd = date.fromisoformat(d)
        except Exception:
            return False
        return start <= dd <= today

    filtered = [x for x in items if isinstance(x, dict) and in_window(str(x.get("date_for")))]

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    for obj in filtered:
        date_for = str(obj.get("date_for"))
        # Clear existing entry for this date_for to keep idempotent
        cur.execute("DELETE FROM journal_entry WHERE date_for=?", (date_for,))

        cur.execute(
            """
            INSERT INTO journal_entry (
              date_created, created_time, date_for, happiness, todo_total, todo_completed, todo_all_completed, agenda_text
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                str(obj.get("date_created")) if obj.get("date_created") is not None else None,
                str(obj.get("created_time")) if obj.get("created_time") is not None else None,
                date_for,
                float(obj.get("happiness")) if isinstance(obj.get("happiness"), (int, float)) else None,
                int(obj.get("todo_total")) if isinstance(obj.get("todo_total"), (int, float)) else None,
                int(obj.get("todo_completed")) if isinstance(obj.get("todo_completed"), (int, float)) else None,
                to_int_bool(obj.get("todo_all_completed")),
                None,
            ),
        )
        entry_id = cur.lastrowid

        # Insert todos
        cur.execute("DELETE FROM journal_todo WHERE entry_id=?", (entry_id,))
        todos = obj.get("todos") or []
        for idx, t in enumerate(todos):
            if not isinstance(t, dict):
                continue
            cur.execute(
                """
                INSERT INTO journal_todo (entry_id, idx, label, text, completed, clock_time, duration_min)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    entry_id,
                    idx,
                    t.get("label"),
                    t.get("text"),
                    to_int_bool(t.get("completed")),
                    t.get("clock_time"),
                    int(t.get("duration_min")) if isinstance(t.get("duration_min"), (int, float)) else None,
                ),
            )

    con.commit()

    # Validation: show a few entries and todos
    print("Entries (latest 5):")
    for r in cur.execute(
        "SELECT id, date_for, happiness, todo_total, todo_completed, todo_all_completed FROM journal_entry ORDER BY date_for DESC LIMIT 5"
    ):
        print(r)
    print("Todos (sample 10):")
    for r in cur.execute(
        "SELECT entry_id, idx, completed, text FROM journal_todo ORDER BY entry_id DESC, idx LIMIT 10"
    ):
        print(r)
    con.close()


if __name__ == "__main__":
    main()
