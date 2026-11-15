"""Validate staging against known source records and session boundaries."""

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
from audit_data import COLUMNS
from build_staging import build_staging


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.database = self.directory / "shop.duckdb"
        self.inputs = [self.directory / "oct.csv", self.directory / "nov.csv"]
        self.baseline = dict(zip(COLUMNS, [
            "2019-10-31 23:59:50 UTC", "view", "1", "10", "", "", "10.00", "100", "cross",
        ]))
        self.records = [
            [
                {},
                {"event_type": "cart", "event_time": "2019-10-31 23:59:55 UTC", "price": "0"},
                {"user_id": "200", "user_session": "shared"},
                {"user_id": "300", "user_session": "long", "event_type": "purchase",
                 "event_time": "2019-10-01 00:00:00 UTC", "price": "20"},
                {"user_id": "400", "user_session": ""},
                {"user_id": "401", "user_session": " "},
                {"user_id": "1.5", "user_session": "bad-user"},
                {"user_id": "500", "user_session": "bad-product", "product_id": "abc"},
            ],
            [
                {"event_type": "purchase", "event_time": "2019-11-01 01:00:10+01:00", "price": "12.50"},
                {"event_type": "purchase", "event_time": "2019-11-01 01:00:10+01:00", "price": "12.50"},
                {"user_session": "shared", "event_time": "2019-11-01 00:00:00 UTC"},
                {"user_id": "300", "user_session": "long", "event_type": "purchase",
                 "event_time": "2019-11-02 00:00:00 UTC", "price": "30"},
                {"user_id": "600", "user_session": "bad-time", "event_time": "bad"},
                {"user_id": "700", "user_session": "bad-price", "event_type": "purchase", "price": "NaN"},
                {"user_id": "800", "user_session": "negative", "event_type": "purchase", "price": "-2"},
                {"user_id": "900", "user_session": "unknown", "event_type": "custom"},
            ],
        ]
        for path, changes in zip(self.inputs, self.records):
            self.write_file(path, changes)

    def write_file(self, path, changes):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(self.baseline | change for change in changes)

    def build(self):
        with patch("sys.stdout"):
            return build_staging(self.inputs, self.database)

    def fetch(self, sql):
        with duckdb.connect(str(self.database), read_only=True) as connection:
            return connection.execute(sql).fetchall()

    def test_preserves_rows_flags_and_purchase_value(self):
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.inputs]
        result = self.build()
        self.assertEqual(result["staging"]["row_count"], 16)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["staging"]["rows_in_duplicate_groups"], 2)
        self.assertEqual(result["staging"]["invalid_user_ids"], 1)
        self.assertEqual(result["staging"]["invalid_product_ids"], 1)
        self.assertEqual(result["staging"]["missing_session_ids"], 2)
        self.assertEqual(result["staging"]["invalid_event_times"], 1)
        self.assertEqual(result["staging"]["invalid_prices"], 1)
        self.assertEqual(result["staging"]["nonpositive_prices"], 2)
        self.assertEqual(result["values"]["positive_purchase_value"], Decimal("75"))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.inputs])
        self.assertEqual(self.fetch("SELECT duplicate_group_size FROM stg_events WHERE user_session='cross' AND event_type='purchase'"), [(2,), (2,)])

    def test_keeps_cross_month_session_and_shared_tokens_separate(self):
        result = self.build()
        cross = self.fetch("SELECT event_count, duration_seconds, source_file_count, positive_purchase_value, purchase_timestamp_count FROM sessions WHERE user_session='cross'")[0]
        self.assertEqual(cross, (4, 20, 2, Decimal("25"), 1))
        self.assertEqual(self.fetch("SELECT COUNT(*) FROM sessions WHERE user_session='shared'"), [(2,)])
        self.assertEqual(result["sessions"]["tokens_shared_across_users"], 1)
        self.assertEqual(result["sessions"]["sessions_crossing_months"], 2)
        self.assertEqual(result["sessions"]["purchase_sessions_with_gap_over_24h"], 1)
        self.assertEqual(result["sessions"]["source_sessions_with_gap_over_30m"], 1)
        self.assertEqual(result["sessions"]["additional_fragments_at_30m"], 1)
        self.assertEqual(result["staging"]["session_eligible_events"], 12)

    def test_duplicate_definition_uses_raw_values_and_ignores_filename(self):
        self.write_file(self.inputs[0], [{}])
        self.write_file(self.inputs[1], [{}, {"price": "10.0"}])
        result = self.build()
        self.assertEqual(result["staging"]["row_count"], 3)
        self.assertEqual(result["staging"]["rows_in_duplicate_groups"], 2)
        self.assertEqual(self.fetch("""
            SELECT r.price, e.price, e.duplicate_group_size
            FROM raw_events r JOIN stg_events e USING (source_file, source_row_number)
            ORDER BY r.price
        """), [("10.0", Decimal("10"), 1), ("10.00", Decimal("10"), 2), ("10.00", Decimal("10"), 2)])

    def test_rebuild_is_repeatable(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first["fingerprints"], second["fingerprints"])
        self.assertEqual(first["staging"], second["staging"])
        self.assertEqual(first["sessions"], second["sessions"])
        self.assertEqual(self.fetch("SELECT COUNT(*) FROM source_files"), [(2,)])

    def test_failed_import_rolls_back_previous_build(self):
        first = self.build()
        with self.inputs[1].open("a", encoding="utf-8") as handle:
            handle.write("too,few,columns\n")
        with self.assertRaises(duckdb.InvalidInputException):
            self.build()
        fingerprint = self.fetch("SELECT BIT_XOR(HASH(t)) FROM stg_events AS t")[0][0]
        self.assertEqual(str(fingerprint), first["fingerprints"]["stg_events"])
        raw_fingerprint = self.fetch("SELECT BIT_XOR(HASH(t)) FROM raw_events AS t")[0][0]
        self.assertEqual(str(raw_fingerprint), first["fingerprints"]["raw_events"])

    def test_empty_sources_produce_empty_tables(self):
        for path in self.inputs:
            self.write_file(path, [])
        result = self.build()
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["staging"]["row_count"], 0)
        self.assertEqual(result["sessions"]["session_count"], 0)


if __name__ == "__main__":
    unittest.main()
