"""Tests for research.importers.device_periods (synthetic data only)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.importers import device_periods as dp
from research.importers import whoop_export as we

CYCLES = (
    "Cycle start time,Cycle end time,Cycle timezone,Recovery score %\n"
    "2025-12-06 23:00:00,2025-12-07 22:00:00,UTC+01:00,50\n"
    "2025-12-07 22:00:00,2025-12-08 22:00:00,UTC+01:00,60\n"
    "2026-10-01 22:00:00,2026-10-02 22:00:00,UTC+02:00,70\n"
)


class DevicePeriodTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "whoop.sqlite"
        (self.tmp / "export").mkdir()
        (self.tmp / "export" / "physiological_cycles.csv").write_text(CYCLES, encoding="utf-8")
        we.import_export(self.tmp / "export", self.db)

    def write_csv(self, body):
        path = self.tmp / "periods.csv"
        path.write_text("device,start,end,source,note\n" + body, encoding="utf-8")
        return path

    def test_cycles_get_their_device_by_local_start_day(self):
        dp.load(self.db, self.write_csv("WHOOP 4.0,2024-11-18,2025-12-06,estimate,\n"
                                        "WHOOP 5.0,2025-12-07,2026-09-18,estimate,\n"))
        with sqlite3.connect(self.db) as db:
            rows = db.execute("SELECT substr(cycle_start_local,1,10), device FROM cycles_with_device "
                              "ORDER BY 1").fetchall()
        self.assertEqual(rows, [("2025-12-06", "WHOOP 4.0"), ("2025-12-07", "WHOOP 5.0"), ("2026-10-01", None)])

    def test_open_ended_period(self):
        dp.load(self.db, self.write_csv("WHOOP 4.0,2026-09-25,,user,\n"))
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT device FROM cycles_with_device WHERE cycle_start_local LIKE '2026-10-01%'")
                             .fetchone(), ("WHOOP 4.0",))

    def test_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            dp.read_periods(self.write_csv("WHOOP 4.0,2025-01-01,2025-12-07,user,\nWHOOP 5.0,2025-12-07,,user,\n"))

    def test_reversed_period_is_rejected(self):
        with self.assertRaises(ValueError):
            dp.read_periods(self.write_csv("WHOOP 4.0,2025-12-07,2025-01-01,user,\n"))

    def test_view_survives_reimport(self):
        dp.load(self.db, self.write_csv("WHOOP 5.0,2025-12-07,,user,\n"))
        we.import_export(self.tmp / "export", self.db)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(device) FROM cycles_with_device").fetchone(), (2,))


if __name__ == "__main__":
    unittest.main()
