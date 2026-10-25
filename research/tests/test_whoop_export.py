"""Tests for research.importers.whoop_export, on synthetic exports only (never real health data).

Run from the repo root:  python3 -m unittest discover -s research/tests -t .
"""

import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from research.importers import whoop_export as we

DE_CYCLES = (
    "Startzeit des Zyklus,Endzeit des Zyklus,Zeitzone des Zyklus,Erholungswert %,"
    "Ruheherzfrequenz (Schläge pro Minute),Herzfrequenzvariabilität (ms),Hauttemperatur (Celsius),"
    "Blutsauerstoff %,Tagesbelastung,Beginn des Schlafs,Beginn des Aufwachens,Schlafdauer (Min.)\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,67,55,71.5,33.24,96.1,10.4,"
    "2025-03-01 23:30:00,2025-03-02 07:12:00,450\n"
    "2025-07-01 22:40:00,,UTC+02:00,,,,,,,,,\n"
)
DE_SLEEPS = (
    "Startzeit des Zyklus,Endzeit des Zyklus,Zeitzone des Zyklus,Beginn des Schlafs,"
    "Beginn des Aufwachens,Schlafleistung %,Nickerchen\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,2025-03-01 23:30:00,2025-03-02 07:12:00,88,false\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,2025-03-02 14:00:00,2025-03-02 14:25:00,,true\n"
)
DE_JOURNAL = (
    "Startzeit des Zyklus,Endzeit des Zyklus,Zeitzone des Zyklus,Fragetext,Beantwortet mit Ja,Anmerkungen\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,Koffein?,true,\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,Koffein?,true,\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,Alkohol?,false,\n"
)
EN_WORKOUTS = (
    "Cycle start time,Cycle end time,Cycle timezone,Workout start time,Workout end time,Duration (min),"
    "Activity name,Activity Strain,Max HR (bpm),HR Zone 1 %,GPS enabled\n"
    "2025-03-01 23:10:00,2025-03-02 22:55:00,UTC+01:00,2025-03-02 17:00:00,2025-03-02 18:00:00,60,"
    "Running,12.3,181,10,true\n"
)


class NormalizeTests(unittest.TestCase):
    def test_german_headers_map_to_noop_keys(self):
        self.assertEqual(we.normalize_header("Erholungswert %"), "recovery_score_pct")
        self.assertEqual(we.normalize_header("Ruheherzfrequenz (Schläge pro Minute)"), "resting_heart_rate_bpm")
        self.assertEqual(we.normalize_header("Schlafbeständigkeit %"), "sleep_consistency_pct")
        self.assertEqual(we.normalize_header("﻿Startzeit des Zyklus"), "cycle_start_time")

    def test_english_headers(self):
        self.assertEqual(we.normalize_header("Cycle start time"), "cycle_start_time")
        self.assertEqual(we.normalize_header("Heart rate variability (ms)"), "heart_rate_variability_ms")
        self.assertEqual(we.normalize_header("Answered yes/no"), "answered_yes")

    def test_offset_and_utc(self):
        self.assertEqual(we.to_utc("2025-03-01 23:10:00", we.parse_offset("UTC+01:00")), "2025-03-01T22:10:00Z")
        self.assertEqual(we.to_utc("2025-07-01 00:30:00", we.parse_offset("UTC+02:00")), "2025-06-30T22:30:00Z")
        self.assertEqual(we.to_utc("2025-07-01 00:30:00", we.parse_offset("UTC-05:30")), "2025-07-01T06:00:00Z")
        self.assertIsNone(we.parse_offset("Europe/Berlin"))
        self.assertIsNone(we.to_utc("", we.parse_offset("UTC+01:00")))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "out" / "whoop.sqlite"

    def make_zip(self):
        path = self.tmp / "export.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("my_whoop_data/physiologische_zyklen.csv", DE_CYCLES.encode("utf-8-sig"))
            z.writestr("my_whoop_data/Schlaf.csv", DE_SLEEPS)
            z.writestr("my_whoop_data/logbuch_eintraege.csv", DE_JOURNAL)
            z.writestr("my_whoop_data/workouts.csv", EN_WORKOUTS)
            z.writestr("__MACOSX/my_whoop_data/._Schlaf.csv", b"\x00\x05\x16\x07 junk")
        return path

    def query(self, sql):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql).fetchall()

    def test_imports_all_four_tables(self):
        stats = we.import_export(self.make_zip(), self.db)
        self.assertEqual(stats, {"cycles": (2, 2), "sleeps": (2, 2), "journal": (3, 2), "workouts": (1, 1)})

    def test_values_and_units(self):
        we.import_export(self.make_zip(), self.db)
        row = self.query("SELECT cycle_start_utc, cycle_start_local, tz_offset_min, recovery_score_pct, "
                         "heart_rate_variability_ms, skin_temp_celsius, sleep_onset_utc FROM cycles "
                         "WHERE cycle_start_local = '2025-03-01 23:10:00'")[0]
        self.assertEqual(row, ("2025-03-01T22:10:00Z", "2025-03-01 23:10:00", 60, 67.0, 71.5, 33.24,
                               "2025-03-01T22:30:00Z"))

    def test_open_cycle_keeps_nulls(self):
        we.import_export(self.make_zip(), self.db)
        row = self.query("SELECT cycle_end_utc, recovery_score_pct FROM cycles WHERE tz_offset_min = 120")[0]
        self.assertEqual(row, (None, None))

    def test_naps_and_journal(self):
        we.import_export(self.make_zip(), self.db)
        self.assertEqual(self.query("SELECT nap, COUNT(*) FROM sleeps GROUP BY nap ORDER BY nap"), [(0, 1), (1, 1)])
        self.assertEqual(self.query("SELECT question_text, answered_yes FROM journal ORDER BY question_text"),
                         [("Alkohol?", 0), ("Koffein?", 1)])

    def test_english_workout(self):
        we.import_export(self.make_zip(), self.db)
        self.assertEqual(self.query("SELECT activity_name, activity_strain, gps_enabled, workout_start_utc FROM workouts"),
                         [("Running", 12.3, 1, "2025-03-02T16:00:00Z")])

    def test_reimport_is_idempotent(self):
        src = self.make_zip()
        we.import_export(src, self.db)
        stats = we.import_export(src, self.db)
        self.assertEqual(stats["cycles"], (2, 2))
        self.assertEqual(self.query("SELECT COUNT(*) FROM imports"), [(8,)])

    def test_directory_source(self):
        d = self.tmp / "dir"
        d.mkdir()
        (d / "Schlaf.csv").write_text(DE_SLEEPS, encoding="utf-8")
        (d / "unrelated.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.assertEqual(we.import_export(d, self.db), {"sleeps": (2, 2)})


if __name__ == "__main__":
    unittest.main()
