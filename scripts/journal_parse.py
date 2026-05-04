import re
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


HEADING_RE = re.compile(r"^\*\*\s+<(?P<ymd>\d{4}-\d{2}-\d{2})\s+\w+(?:\s+(?P<hh>\d{1,2})[:.](?P<mm>\d{2}))?[^>]*>")
TOP_YEAR_RE = re.compile(r"^\*\s+20\d{2}\b")
TOP_ANY_RE = re.compile(r"^\*\s+")
HAPPY_RE = re.compile(r"^:-\)\s+(?P<score>\d+(?:[\.,]\d+)?)\s*$")
SUBHEAD_RE = re.compile(r"^\*{3,}\s+(?P<title>.+?)\s*$", re.IGNORECASE)
AGENDA_HEAD_RE = re.compile(r"^\*{3,}\s+Agenda\b", re.IGNORECASE)
TOP_TODO_RE = re.compile(r"^-\s*\[(?P<mark>[Xx\s])\]\s*(?P<text>.*)$")
TIME_BRACKET_RE = re.compile(r"\[(?P<time>\d{1,2}[:.]\d{2})\]")
DURATION_RE = re.compile(r"\b(?P<mins>\d{1,3})\s*m(?:in)?\b", re.IGNORECASE)
DURATION_H_RE = re.compile(r"\b(?P<hours>\d{1,2})\s*h\b", re.IGNORECASE)

KEYWORDS = [
    (re.compile(r"^Bastu\b", re.IGNORECASE), "Bastu"),
    (re.compile(r"^Meditera\b", re.IGNORECASE), "Meditera"),
    (re.compile(r"^(Morgonstretch|Stretch)\b", re.IGNORECASE), "Stretch"),
    (re.compile(r"^Kalldusch\b", re.IGNORECASE), "Kalldusch"),
    (re.compile(r"^Fasta\b", re.IGNORECASE), "Fasta"),
    (re.compile(r"^Tzu\b", re.IGNORECASE), "Tzu"),
]


@dataclass
class Entry:
    created_date: date
    created_time: Optional[Tuple[int, int]]  # (hh, mm)
    happiness: Optional[float]
    agenda_lines: List[str]


def parse_heading(line: str) -> Optional[Tuple[date, Optional[Tuple[int, int]]]]:
    m = HEADING_RE.match(line)
    if not m:
        return None
    ymd = m.group("ymd")
    hh = m.group("hh")
    mm = m.group("mm")
    d = datetime.strptime(ymd, "%Y-%m-%d").date()
    t: Optional[Tuple[int, int]] = None
    if hh and mm:
        t = (int(hh), int(mm))
    return d, t


def normalize_time_token(tok: str) -> str:
    tok = tok.replace(".", ":")
    hh, mm = tok.split(":")
    return f"{int(hh):02d}:{int(mm):02d}"


def extract_keywords(text: str) -> Optional[str]:
    for rx, label in KEYWORDS:
        if rx.search(text):
            return label
    return None


def parse_file(path: Path) -> List[Entry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: List[Entry] = []

    i = 0
    in_year = False
    while i < len(lines):
        # Track top-level year sections
        if TOP_ANY_RE.match(lines[i]):
            in_year = bool(TOP_YEAR_RE.match(lines[i]))

        head = parse_heading(lines[i]) if in_year else None
        if not head:
            i += 1
            continue
        created_d, created_t = head
        happiness: Optional[float] = None
        agenda_lines: List[str] = []

        # scan within this section until next heading or EOF
        i += 1
        # optional happiness line right after heading (allow blank lines before it)
        j = i
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j < len(lines):
            hm = HAPPY_RE.match(lines[j].strip())
            if hm:
                raw = hm.group("score").replace(",", ".")
                happiness = float(raw)
                i = j + 1
        # find Agenda subheading within this entry
        # we continue scanning until next top-level date heading '** ...'
        in_agenda = False
        while i < len(lines):
            if parse_heading(lines[i]):
                break  # next entry begins
            sh = SUBHEAD_RE.match(lines[i])
            if sh:
                in_agenda = bool(AGENDA_HEAD_RE.match(lines[i]))
                i += 1
                continue
            if in_agenda:
                # only accept top-level todo lines (no leading spaces)
                if lines[i].startswith("- ") or lines[i].startswith("-["):
                    agenda_lines.append(lines[i])
            i += 1

        entries.append(Entry(created_d, created_t, happiness, agenda_lines))

    return entries


def extract_duration_min(text: str) -> Optional[int]:
    # Return minutes based on the first duration-like token in the text
    first_pos = None
    minutes_val: Optional[int] = None

    # Search hours and minutes; choose earliest occurrence
    for m in DURATION_H_RE.finditer(text):
        pos = m.start()
        val = int(m.group("hours")) * 60
        if first_pos is None or pos < first_pos:
            first_pos, minutes_val = pos, val
        break  # first hours token is enough
    for m in DURATION_RE.finditer(text):
        pos = m.start()
        val = int(m.group("mins"))
        if first_pos is None or pos < first_pos:
            first_pos, minutes_val = pos, val
        break  # first minutes token is enough

    return minutes_val


def assign_dates_for(entries: List[Entry]) -> List[date]:
    # Determine date_for per entry according to rules
    by_day: Dict[date, List[int]] = {}
    for idx, e in enumerate(entries):
        by_day.setdefault(e.created_date, []).append(idx)

    result: List[date] = [e.created_date for e in entries]
    for d, idxs in by_day.items():
        if len(idxs) == 1:
            result[idxs[0]] = d + timedelta(days=1)
        else:
            # sort by time (None treated as (0,0))
            idxs.sort(key=lambda k: entries[k].created_time or (0, 0))
            # earlier -> today, others -> tomorrow
            first = True
            for k in idxs:
                if first:
                    result[k] = d
                    first = False
                else:
                    result[k] = d + timedelta(days=1)
    return result


def main() -> None:
    src = Path("org/journal.org")
    out_jsonl = Path("memory-bank/journal_events.jsonl")
    out_csv = Path("memory-bank/journal_events.csv")
    out_entries = Path("memory-bank/journal_entries.jsonl")
    rows: List[Dict[str, Any]] = []
    entry_objs: List[Dict[str, Any]] = []

    entries = parse_file(src)
    pertains = assign_dates_for(entries)

    for e, date_for in zip(entries, pertains):
        # compute todo counts over all top-level agenda items
        todo_items: List[Tuple[bool, str]] = []
        for line in e.agenda_lines:
            m = TOP_TODO_RE.match(line)
            if m:
                completed = m.group("mark").strip().lower() == "x"
                txt = m.group("text").strip()
                # exclude indented subitems already by start-of-line check
                todo_items.append((completed, txt))
        total = len(todo_items)
        completed_count = sum(1 for c, _ in todo_items if c)
        all_completed = total > 0 and completed_count == total

        # now build rows and collect all todos for the entry
        todos_for_entry: List[Dict[str, Any]] = []
        for completed, txt in todo_items:
            label = extract_keywords(txt)
            tmatch = TIME_BRACKET_RE.search(txt)
            clock_time = None
            if tmatch:
                clock_time = normalize_time_token(tmatch.group("time"))
            duration_min = extract_duration_min(txt)

            row: Dict[str, Any] = {
                "date_created": e.created_date.isoformat(),
                "created_time": None if not e.created_time else f"{e.created_time[0]:02d}:{e.created_time[1]:02d}",
                "date_for": date_for.isoformat(),
                "happiness": e.happiness,
                "todo_total": total,
                "todo_completed": completed_count,
                "todo_all_completed": all_completed,
                "label": label,
                "text": txt,
                "completed": completed,
                "clock_time": clock_time,
                "duration_min": duration_min,
            }
            if label:
                rows.append(row)
            todos_for_entry.append({
                "label": label,
                "text": txt,
                "completed": completed,
                "clock_time": clock_time,
                "duration_min": duration_min,
            })

        # build per-entry object (with list of tracked todos)
        entry_objs.append({
            "date_created": e.created_date.isoformat(),
            "created_time": None if not e.created_time else f"{e.created_time[0]:02d}:{e.created_time[1]:02d}",
            "date_for": date_for.isoformat(),
            "happiness": e.happiness,
            "todo_total": total,
            "todo_completed": completed_count,
            "todo_all_completed": all_completed,
            "todos": todos_for_entry,
        })

    # Write JSONL
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            import json

            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write CSV
    import csv

    keys = [
        "date_created",
        "created_time",
        "date_for",
        "happiness",
        "todo_total",
        "todo_completed",
        "todo_all_completed",
        "label",
        "text",
        "completed",
        "clock_time",
        "duration_min",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Write per-entry JSONL
    out_entries.parent.mkdir(parents=True, exist_ok=True)
    with out_entries.open("w", encoding="utf-8") as f:
        for obj in entry_objs:
            import json
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(f"Wrote {out_jsonl} ({len(rows)} rows), {out_csv} and {out_entries} ({len(entry_objs)} entries)")


if __name__ == "__main__":
    main()
