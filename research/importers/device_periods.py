"""Load research/device_periods.csv into the WHOOP database and tag every cycle with its strap.

Usage:
    python3 -m research.importers.device_periods [--db research/data/whoop.sqlite] [--csv research/device_periods.csv]

The export does not say which strap recorded a day, and the WHOOP 4.0 -> 5.0 switch is not visible as
a clean step in every metric, so the periods are kept by hand in a small CSV (dates only, no health
data, so it is committed). Dates are local calendar days, inclusive; an empty end means "still worn".

Creates the table `device_periods` and the view `cycles_with_device`, which adds a `device` column to
`cycles` (NULL for days outside every period). Overlapping periods are rejected, since a day must map
to exactly one strap for the per-device comparisons in Phase 2.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "whoop.sqlite"
DEFAULT_CSV = ROOT / "device_periods.csv"


def read_periods(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        periods = [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]
    spans = []
    for p in periods:
        start = date.fromisoformat(p["start"])
        end = date.fromisoformat(p["end"]) if p["end"] else date.max
        if end < start:
            raise ValueError(f"{p['device']}: end {p['end']} is before start {p['start']}")
        spans.append((start, end, p["device"]))
    spans.sort()
    for (s1, e1, d1), (s2, _, d2) in zip(spans, spans[1:]):
        if s2 <= e1:
            raise ValueError(f"periods overlap: {d1} until {e1} and {d2} from {s2}")
    return periods


def load(db_path: Path, csv_path: Path) -> int:
    periods = read_periods(csv_path)
    db = sqlite3.connect(db_path)
    try:
        with db:
            db.execute("DROP TABLE IF EXISTS device_periods")
            db.execute("CREATE TABLE device_periods (device TEXT, start TEXT, end TEXT, source TEXT, note TEXT)")
            db.executemany("INSERT INTO device_periods VALUES (?, ?, ?, ?, ?)",
                           [(p["device"], p["start"], p["end"] or None, p.get("source"), p.get("note"))
                            for p in periods])
            db.execute("DROP VIEW IF EXISTS cycles_with_device")
            db.execute("""
                CREATE VIEW cycles_with_device AS
                SELECT c.*, d.device
                FROM cycles c
                LEFT JOIN device_periods d
                  ON substr(c.cycle_start_local, 1, 10) >= d.start
                 AND (d.end IS NULL OR substr(c.cycle_start_local, 1, 10) <= d.end)
            """)
    finally:
        db.close()
    return len(periods)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"{args.db} not found; import a WHOOP export first.", file=sys.stderr)
        return 1
    n = load(args.db, args.csv)
    print(f"Loaded {n} device periods into {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
