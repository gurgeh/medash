import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from orgparse import load as org_load


TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|[-+ ]+\|\s*$")
DATE_CELL_RE = re.compile(r"<(?P<date>\d{4}-\d{2}-\d{2})[^>]*>")
MMSS_RE = re.compile(r"^(?P<m>\d+):(?P<s>\d{2})$")
MM_DOT_SS_RE = re.compile(r"^(?P<m>\d+)\.(?P<s>\d{2})$")


IGNORE_HEADINGS = {
    "a",
    "b",
    "c",
    "d",
    "max",
    "mid",
    "hyper",
    "hyper10",
    "5x5",
    "volym",
    "rpt",
    "misc",
    "hypertrofi",
    "hypertrophy",
    "logg",
    "kortlogg",
    "standard",
}

# Entire sections to ignore (skip any tables under these headings)
IGNORED_SECTIONS = {"rekord", "lopning", "löpning", "tillskott"}


def norm_title(s: str) -> str:
    t = s.strip().lower()
    t = t.replace("å", "a").replace("ä", "a").replace("ö", "o")
    return t


def is_numeric_heading(title: str) -> bool:
    t = norm_title(title)
    # Numeric or patterns used in rowing, e.g., 1234321, 10x500, 8x(1:00/1:00), 45 rodd, 2000 -> 500
    if re.fullmatch(r"[0-9x:+\-\s()/.><]+", t):
        return True
    # Zone patterns like Zon2 / Zone 2
    if re.fullmatch(r"(zon|zone)\s*\d+", t):
        return True
    return False


def is_scheme_heading(title: str) -> bool:
    # User-defined schemes start with a leading ':' (e.g., ':5x5', ':tempo')
    return title.lstrip().startswith(":")


def strip_scheme_prefix(title: str) -> str:
    t = title.lstrip()
    return t[1:].lstrip() if t.startswith(":") else title


def normalize_header(h: str) -> str:
    t = h.strip().strip().lower()
    # Canonical mappings
    if t == "datum":
        return "date"
    if t in ("öka", "oka", "delta"):
        return "delta"
    if t == "vikt":
        return "weight"
    if t in ("tid", "time"):
        return "time"
    if t in ("kommentar", "kommentarer", "comment", "kommentarer"):
        return "comment"
    if t in ("∑", "sum", "sigma"):
        return "sum"
    if re.fullmatch(r"set\s*\d+", t):
        return t.replace(" ", "")
    # Generic slugify
    t = re.sub(r"\s+", "_", t)
    t = t.replace("å", "a").replace("ä", "a").replace("ö", "o")
    t = re.sub(r"[^a-z0-9_]+", "", t)
    return t


def parse_time_cell(v: str) -> Any:
    v = v.strip()
    if not v:
        return None
    m = MMSS_RE.match(v)
    if m:
        return int(m.group("m")) * 60 + int(m.group("s"))
    m = MM_DOT_SS_RE.match(v)
    if m:
        return int(m.group("m")) * 60 + int(m.group("s"))
    # Fallback: numeric
    try:
        if ":" not in v:
            return float(v) if "." in v else int(v)
    except Exception:
        pass
    return v


def parse_numeric(v: str) -> Any:
    v = v.strip()
    if v == "" or v == "-":
        return None
    # Accept ints or floats
    try:
        if re.fullmatch(r"[-+]?\d+", v):
            return int(v)
        if re.fullmatch(r"[-+]?\d*\.\d+", v):
            return float(v)
    except Exception:
        return v
    return v


def split_cells(line: str) -> List[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in inner.split("|")]


ALIAS_TITLE = {
    "test": "Landmine, circle",
}


def resolve_titles(node) -> Tuple[str, Optional[str], List[str]]:
    # exercise_title, scheme (merged), path
    # Build path by walking up via parent
    path_nodes = []
    cur = node
    while cur is not None:
        path_nodes.append(cur)
        cur = cur.parent
    path_nodes = list(reversed(path_nodes))
    if path_nodes and path_nodes[0].is_root():
        path_nodes = path_nodes[1:]
    titles = [n.heading.strip() for n in path_nodes]
    exercise_title = None
    scheme: Optional[str] = None
    # Walk upward from current node toward root
    for i in range(len(titles) - 1, -1, -1):
        t = titles[i].strip()
        tl = norm_title(t)
        if tl in IGNORE_HEADINGS or is_numeric_heading(tl) or is_scheme_heading(t):
            # candidate for intensity/workout marker if closest to table
            if i == len(titles) - 1:
                # immediate heading above table
                if tl in IGNORE_HEADINGS:
                    scheme = t
                elif is_numeric_heading(tl):
                    scheme = t
                elif is_scheme_heading(t):
                    scheme = strip_scheme_prefix(t)
            continue
        exercise_title = t
        break
    if exercise_title is None:
        # fallback to the node's own title
        exercise_title = titles[-1]
    # Apply alias mapping
    nt = norm_title(exercise_title)
    if nt in ALIAS_TITLE:
        exercise_title = ALIAS_TITLE[nt]
    return exercise_title, scheme, titles


def coerce_row(headers: List[str], cells: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i, key in enumerate(headers):
        val = cells[i] if i < len(cells) else ""
        if key == "date":
            m = DATE_CELL_RE.search(val)
            out[key] = m.group("date") if m else val or None
        elif key == "time":
            out[key] = parse_time_cell(val)
        elif key in ("weight", "sum") or key.startswith("set"):
            out[key] = parse_numeric(val)
        elif key == "delta":
            out[key] = val or None
        elif key == "comment":
            out[key] = val
        else:
            # Try numeric, else keep string
            parsed = parse_numeric(val)
            out[key] = parsed
    return out


def extract_tables_from_node(node) -> Iterable[Dict[str, Any]]:
    lines = node.body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if TABLE_ROW_RE.match(line):
            block: List[str] = []
            while i < len(lines) and TABLE_ROW_RE.match(lines[i]):
                if not TABLE_SEP_RE.match(lines[i]):
                    block.append(lines[i])
                i += 1
            if not block:
                continue
            header_cells = split_cells(block[0])
            headers = [normalize_header(h) for h in header_cells]
            for row_line in block[1:]:
                row_cells = split_cells(row_line)
                yield coerce_row(headers, row_cells)
            continue
        i += 1


def main() -> None:
    src = os.environ.get("ORG_FILE", "org/styrka.org")
    out_dir = Path("memory-bank")
    out_dir.mkdir(parents=True, exist_ok=True)
    root = org_load(src)

    rows: List[Dict[str, Any]] = []
    for node in root[1:]:  # skip document root
        exercise_title, scheme, titles = resolve_titles(node)
        # Skip entire sections if any heading matches IGNORED_SECTIONS
        titles_norm = [norm_title(t) for t in titles]
        if any(t in IGNORED_SECTIONS for t in titles_norm):
            continue
        for rec in extract_tables_from_node(node):
            rec["exercise_title"] = exercise_title
            rec["scheme"] = scheme
            rec["heading_path"] = titles
            rows.append(rec)

    # Write JSONL
    jsonl_path = out_dir / "org_tables.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write CSV with a union of keys
    all_keys: List[str] = []
    seen: set = set()
    # Preferred order
    preferred = [
        "exercise_title",
        "scheme",
        "date",
        "delta",
        "weight",
        "time",
        "sum",
        "comment",
    ]
    for k in preferred:
        if k not in seen:
            seen.add(k)
            all_keys.append(k)
    # Collect remaining keys from data rows
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                all_keys.append(k)

    csv_path = out_dir / "org_tables.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {jsonl_path} and {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
