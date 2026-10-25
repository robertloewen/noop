"""Import a WHOOP data export (ZIP or folder of CSVs) into a local SQLite database.

Usage:
    python3 -m research.importers.whoop_export <export.zip|export-dir> [--db research/data/whoop.sqlite]

The export ships four CSVs whose file and column names are localized (a German export has
physiologische_zyklen.csv, Schlaf.csv, Trainings.csv, logbuch_eintraege.csv). Headers are normalized
the way NOOP's own importer does (Packages/StrandImport/Sources/StrandImport/CSVParsing.swift):
lowercase, diacritics folded, "%" -> "pct", every other non-alphanumeric run -> "_", then foreign
names mapped onto the canonical English key. Keeping the same keys means a column here and in the app
mean the same thing.

Times in the export are local wall-clock times plus a "UTC+02:00" style offset per cycle. Both the
UTC instant and the local text are stored: UTC for joining against NOOP and the WHOOP API, local for
"which night was this".

Re-importing is idempotent: each table has a natural key and rows are upserted, so a newer export
simply overwrites the overlapping days. Nothing here touches the network.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import sys
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "whoop.sqlite"

# Localized header (normalized) -> canonical English key. German list mirrors foreignAliases in
# Packages/StrandImport/Sources/StrandImport/CSVParsing.swift, plus the headers this export added.
FOREIGN_ALIASES = {
    "startzeit_des_zyklus": "cycle_start_time",
    "endzeit_des_zyklus": "cycle_end_time",
    "zeitzone_des_zyklus": "cycle_timezone",
    "erholungswert_pct": "recovery_score_pct",
    "ruheherzfrequenz_schlage_pro_minute": "resting_heart_rate_bpm",
    "herzfrequenzvariabilitat_ms": "heart_rate_variability_ms",
    "hauttemperatur_celsius": "skin_temp_celsius",
    "blutsauerstoff_pct": "blood_oxygen_pct",
    "tagesbelastung": "day_strain",
    "verbrannte_energie_cal": "energy_burned_cal",
    "max_hf_schlage_pro_minute": "max_hr_bpm",
    "durchschnittliche_hf_schlage_pro_minute": "average_hr_bpm",
    "beginn_des_schlafs": "sleep_onset",
    "beginn_des_aufwachens": "wake_onset",
    "schlafleistung_pct": "sleep_performance_pct",
    "atemfrequenz_atemzuge_min": "respiratory_rate_rpm",
    "schlafdauer_min": "asleep_duration_min",
    "dauer_im_bett_min": "in_bed_duration_min",
    "dauer_des_leichtschlafs_min": "light_sleep_duration_min",
    "dauer_des_tiefschlafs_min": "deep_sws_duration_min",
    "dauer_des_rem_schlafs_min": "rem_duration_min",
    "dauer_des_aufwachens_min": "awake_duration_min",
    "schlafbedarf_min": "sleep_need_min",
    "schlafdefizit_min": "sleep_debt_min",
    "schlafeffizienz_pct": "sleep_efficiency_pct",
    "schlafbestandigkeit_pct": "sleep_consistency_pct",
    "nickerchen": "nap",
    "startzeit_des_trainings": "workout_start_time",
    "endzeit_des_trainings": "workout_end_time",
    "dauer_min": "duration_min",
    "name_der_aktivitat": "activity_name",
    "aktivitatsbelastung": "activity_strain",
    "hf_zone_1_pct": "hr_zone_1_pct",
    "hf_zone_2_pct": "hr_zone_2_pct",
    "hf_zone_3_pct": "hr_zone_3_pct",
    "hf_zone_4_pct": "hr_zone_4_pct",
    "hf_zone_5_pct": "hr_zone_5_pct",
    "gps_aktiviert": "gps_enabled",
    "fragetext": "question_text",
    "beantwortet_mit_ja": "answered_yes",
    "anmerkungen": "notes",
    # English variants that differ from the canonical key.
    "resting_heart_rate": "resting_heart_rate_bpm",
    "heart_rate_variability_rmssd_ms": "heart_rate_variability_ms",
    "respiratory_rate": "respiratory_rate_rpm",
    "deep_sleep_duration_min": "deep_sws_duration_min",
    "average_heart_rate_bpm": "average_hr_bpm",
    "max_heart_rate_bpm": "max_hr_bpm",
    "answered_yes_no": "answered_yes",
}

FILE_KINDS = {
    "physiological_cycles.csv": "cycles",
    "physiologische_zyklen.csv": "cycles",
    "sleeps.csv": "sleeps",
    "schlaf.csv": "sleeps",
    "workouts.csv": "workouts",
    "trainings.csv": "workouts",
    "journal_entries.csv": "journal",
    "logbuch_eintraege.csv": "journal",
}

# Per table: natural key, timestamp columns (stored as *_utc + *_local), and typed value columns.
TABLES = {
    "cycles": {
        "key": ["cycle_start_utc"],
        "times": ["cycle_start_time", "cycle_end_time", "sleep_onset", "wake_onset"],
        "real": ["recovery_score_pct", "resting_heart_rate_bpm", "heart_rate_variability_ms",
                 "skin_temp_celsius", "blood_oxygen_pct", "day_strain", "energy_burned_cal",
                 "max_hr_bpm", "average_hr_bpm", "sleep_performance_pct", "respiratory_rate_rpm",
                 "asleep_duration_min", "in_bed_duration_min", "light_sleep_duration_min",
                 "deep_sws_duration_min", "rem_duration_min", "awake_duration_min", "sleep_need_min",
                 "sleep_debt_min", "sleep_efficiency_pct", "sleep_consistency_pct"],
        "bool": [],
        "text": [],
    },
    "sleeps": {
        "key": ["sleep_onset_utc"],
        "times": ["cycle_start_time", "cycle_end_time", "sleep_onset", "wake_onset"],
        "real": ["sleep_performance_pct", "respiratory_rate_rpm", "asleep_duration_min",
                 "in_bed_duration_min", "light_sleep_duration_min", "deep_sws_duration_min",
                 "rem_duration_min", "awake_duration_min", "sleep_need_min", "sleep_debt_min",
                 "sleep_efficiency_pct", "sleep_consistency_pct"],
        "bool": ["nap"],
        "text": [],
    },
    "workouts": {
        "key": ["workout_start_utc"],
        "times": ["cycle_start_time", "cycle_end_time", "workout_start_time", "workout_end_time"],
        "real": ["duration_min", "activity_strain", "energy_burned_cal", "max_hr_bpm", "average_hr_bpm",
                 "hr_zone_1_pct", "hr_zone_2_pct", "hr_zone_3_pct", "hr_zone_4_pct", "hr_zone_5_pct"],
        "bool": ["gps_enabled"],
        "text": ["activity_name"],
    },
    "journal": {
        "key": ["cycle_start_utc", "question_text"],
        "times": ["cycle_start_time", "cycle_end_time"],
        "real": [],
        "bool": ["answered_yes"],
        "text": ["question_text", "notes"],
    },
}


def normalize_header(header: str) -> str:
    folded = unicodedata.normalize("NFKD", header.strip().lstrip("﻿"))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower().replace("%", "pct")
    key = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    return FOREIGN_ALIASES.get(key, key)


def time_column(name: str) -> str:
    """'cycle_start_time' -> 'cycle_start', 'sleep_onset' -> 'sleep_onset'."""
    return name[: -len("_time")] if name.endswith("_time") else name


def parse_offset(text: str) -> timedelta | None:
    m = re.fullmatch(r"\s*(?:UTC|GMT)?\s*([+-])(\d{1,2}):?(\d{2})\s*", text or "")
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    return sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))


def to_utc(local: str, offset: timedelta | None) -> str | None:
    if not local or not local.strip() or offset is None:
        return None
    dt = datetime.strptime(local.strip(), "%Y-%m-%d %H:%M:%S")
    return (dt - offset).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_real(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    return float(text.replace(",", "."))


def to_bool(text: str) -> int | None:
    text = (text or "").strip().lower()
    if text in ("true", "ja", "yes", "1"):
        return 1
    if text in ("false", "nein", "no", "0"):
        return 0
    return None


def columns_for(kind: str) -> list[tuple[str, str]]:
    spec = TABLES[kind]
    cols: list[tuple[str, str]] = [("tz_offset_min", "INTEGER")]
    for t in spec["times"]:
        cols += [(time_column(t) + "_utc", "TEXT"), (time_column(t) + "_local", "TEXT")]
    cols += [(c, "REAL") for c in spec["real"]]
    cols += [(c, "INTEGER") for c in spec["bool"]]
    cols += [(c, "TEXT") for c in spec["text"] if (c, "TEXT") not in cols]
    return cols


def create_schema(db: sqlite3.Connection) -> None:
    for kind, spec in TABLES.items():
        cols = ",\n  ".join(f"{name} {typ}" for name, typ in columns_for(kind))
        db.execute(f"CREATE TABLE IF NOT EXISTS {kind} (\n  {cols},\n  PRIMARY KEY ({', '.join(spec['key'])})\n)")
    db.execute("""CREATE TABLE IF NOT EXISTS imports (
        imported_at TEXT, source TEXT, kind TEXT, file TEXT, rows_read INTEGER, rows_stored INTEGER)""")


def convert_row(kind: str, row: dict[str, str]) -> dict[str, object] | None:
    spec = TABLES[kind]
    offset = parse_offset(row.get("cycle_timezone", ""))
    out: dict[str, object] = {"tz_offset_min": int(offset.total_seconds() // 60) if offset is not None else None}
    for t in spec["times"]:
        local = (row.get(t) or "").strip() or None
        out[time_column(t) + "_local"] = local
        out[time_column(t) + "_utc"] = to_utc(local or "", offset)
    for c in spec["real"]:
        out[c] = to_real(row.get(c, ""))
    for c in spec["bool"]:
        out[c] = to_bool(row.get(c, ""))
    for c in spec["text"]:
        out[c] = (row.get(c) or "").strip() or None
    if any(out.get(k) is None for k in spec["key"]):
        return None  # no usable natural key, e.g. a cycle row without start time
    return out


def read_csv(text: str) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(text))
    header = [normalize_header(h) for h in next(reader, [])]
    return [dict(zip(header, values)) for values in reader if any(v.strip() for v in values)]


def iter_export(source: Path):
    """Yield (kind, filename, csv text) for every recognized CSV in a ZIP or directory."""
    if source.is_dir():
        files = [(p.name, p.read_bytes) for p in sorted(source.rglob("*.csv"))]
    else:
        zf = zipfile.ZipFile(source)
        files = [(Path(n).name, (lambda n=n: zf.read(n))) for n in sorted(zf.namelist())
                 if n.lower().endswith(".csv") and "__MACOSX" not in n and not Path(n).name.startswith("._")]
    for name, read in files:
        kind = FILE_KINDS.get(name.lower())
        if kind:
            yield kind, name, read().decode("utf-8-sig")


def import_export(source: Path, db_path: Path) -> dict[str, tuple[int, int]]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    stats: dict[str, tuple[int, int]] = {}
    try:
        with db:
            create_schema(db)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for kind, name, text in iter_export(source):
                rows = read_csv(text)
                converted = [r for r in (convert_row(kind, row) for row in rows) if r is not None]
                cols = [c for c, _ in columns_for(kind)]
                placeholders = ", ".join("?" for _ in cols)
                db.executemany(
                    f"INSERT OR REPLACE INTO {kind} ({', '.join(cols)}) VALUES ({placeholders})",
                    [[r[c] for c in cols] for r in converted],
                )
                stored = db.execute(f"SELECT COUNT(*) FROM {kind}").fetchone()[0]
                db.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?)",
                           (now, source.name, kind, name, len(rows), stored))
                stats[kind] = (len(rows), stored)
    finally:
        db.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path, help="WHOOP export .zip or extracted folder")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite file (default: {DEFAULT_DB})")
    args = ap.parse_args(argv)
    stats = import_export(args.source, args.db)
    if not stats:
        print("No WHOOP CSVs recognized in", args.source, file=sys.stderr)
        return 1
    for kind, (read, stored) in sorted(stats.items()):
        print(f"{kind:9} read {read:6}  rows in table {stored:6}")
    print("Database:", args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
