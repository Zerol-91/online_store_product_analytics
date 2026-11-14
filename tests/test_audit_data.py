"""Check profiling against small, deliberately imperfect synthetic events."""

import csv
import hashlib
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audit_data import COLUMNS, ROOT, audit_csv, main


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "events.csv"

    def write_events(self, changes):
        baseline = dict(zip(COLUMNS, [
            "2019-10-01 00:00:00 UTC", "view", "1", "10", "", "", "12.50", "100", "s1",
        ]))
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(baseline | change for change in changes)

    def test_counts_invalid_values_and_preserves_all_rows(self):
        self.write_events([
            {}, {},
            {"event_type": "cart", "price": "0"},
            {"event_type": "purchase", "price": "-2"},
            {"event_type": "unknown", "event_time": "not-a-date", "price": "oops"},
            {"event_type": "", "event_time": "", "price": "", "user_session": " "},
            {"event_type": "purchase", "price": "NaN"},
            {"event_type": "purchase", "price": "Infinity"},
            {"event_time": "2019-11-01 01:00:00+01:00"},
        ])
        before = self.source.read_bytes()
        report = audit_csv(self.source, include_duplicates=True)
        summary = report["summary"]
        for field, expected in {
            "row_count": 9, "invalid_event_time": 1, "missing_event_time": 1,
            "invalid_price": 3, "missing_price": 1, "zero_price": 1,
            "negative_price": 1, "unexpected_event_type": 1,
            "missing_event_type": 1, "missing_user_session": 1, "missing_brand": 9,
        }.items():
            self.assertEqual(summary[field], expected, field)
        self.assertEqual(summary["last_event_utc"], "2019-11-01T00:00:00+00:00")
        self.assertEqual(sum(row["row_count"] for row in report["by_event_type"]), 9)
        self.assertEqual(sum(row["row_count"] for row in report["by_day"]), 9)
        self.assertEqual(report["by_day"][0], {"event_date_utc": None, "row_count": 2})
        duplicate_view = next(row for row in report["duplicate_sensitivity"] if row["event_type"] == "view")
        self.assertEqual(duplicate_view["duplicate_rows"], 1)
        self.assertEqual(duplicate_view["rows_in_duplicate_groups"], 2)
        self.assertEqual(Decimal(duplicate_view["positive_price_value_before_dedup"]), Decimal("37.50"))
        self.assertEqual(Decimal(duplicate_view["positive_price_value_after_dedup"]), Decimal("25.00"))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(report["source"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(audit_csv(self.source)["summary"], summary)

    def test_empty_file_with_header_reports_zero_rows(self):
        self.write_events([])
        report = audit_csv(self.source, include_duplicates=True)
        summary = report["summary"]
        self.assertEqual(summary["row_count"], 0)
        self.assertIsNone(summary["first_event_utc"])
        self.assertEqual(report["by_day"], [])
        self.assertEqual(report["duplicate_sensitivity"], [])

    def test_duplicate_purchase_sensitivity_uses_all_source_fields(self):
        self.write_events([
            {"event_type": "purchase", "price": "12.50"},
            {"event_type": "purchase", "price": "12.50"},
            {"event_type": "purchase", "price": "12.50", "user_session": "s2"},
        ])
        result = audit_csv(self.source, include_duplicates=True)["duplicate_sensitivity"][0]
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["unique_rows"], 2)
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(Decimal(result["positive_price_value_before_dedup"]), Decimal("37.50"))
        self.assertEqual(Decimal(result["positive_price_value_after_dedup"]), Decimal("25.00"))

    def test_unexpected_header_fails(self):
        self.source.write_text("event_time,event_type\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected CSV header"):
            audit_csv(self.source)

    def test_malformed_row_is_not_silently_skipped(self):
        self.write_events([{}])
        with self.source.open("a", encoding="utf-8") as handle:
            handle.write("too,few,columns\n")
        with self.assertRaises(duckdb.InvalidInputException):
            audit_csv(self.source)

    def test_cli_creates_report_and_handles_missing_input(self):
        self.write_events([{}])
        output = Path(self.temporary.name) / "report.json"
        with patch("sys.stdout"):
            self.assertEqual(main(["--input", str(self.source), "--output", str(output)]), 0)
        self.assertTrue(output.is_file())
        with patch("sys.stderr"):
            self.assertEqual(main(["--input", str(self.source.with_name("missing.csv"))]), 1)

    def test_cli_rejects_output_in_raw_directory(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit) as error:
            main(["--output", str(ROOT / "data/raw/report.json")])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
