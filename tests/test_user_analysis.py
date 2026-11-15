"""Check user-window eligibility and outcomes across session boundaries."""

import csv
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audit_data import COLUMNS
from build_analysis import prepare_parameters, build_user_models, validate_user_models, build_analysis
from build_staging import build_staging


class UserAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.database = self.directory / "shop.duckdb"
        self.settings = {
            "inactivity_minutes": 30, "horizon_days": 7,
            "observation_start_utc": datetime(2019, 10, 1),
            "analysis_start_utc": datetime(2019, 11, 1),
            "observation_end_exclusive_utc": datetime(2020, 3, 1),
        }

    def event(self, user, timestamp, kind, session="s1"):
        return dict(zip(COLUMNS, [timestamp + " UTC", kind, "1", "10", "", "", "10", str(user), session]))

    def build(self, rows):
        source = self.directory / "events.csv"
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        with patch("sys.stdout"):
            build_staging([source], self.database)
        with duckdb.connect(str(self.database)) as connection:
            prepare_parameters(connection, self.settings)
            build_user_models(connection)
            return validate_user_models(connection)

    def test_purchase_at_deadline_qualifies_across_sessions(self):
        result = self.build([
            self.event(1, "2019-11-01 12:00:00", "view", "a"),
            self.event(1, "2019-11-03 12:00:00", "cart", "b"),
            self.event(1, "2019-11-08 12:00:00", "purchase", "c"),
        ])
        primary = next(r for r in result["summary"] if r["population"] == "post_warmup" and r["timestamp_rule"] == "allow_equal")
        self.assertEqual((primary["view_users"], primary["cart_users"], primary["full_chain_users"]), (1, 1, 1))
        self.assertTrue(all(result["checks"].values()))

    def test_purchase_after_deadline_is_not_counted(self):
        result = self.build([
            self.event(1, "2019-11-01 12:00:00", "view"),
            self.event(1, "2019-11-03 12:00:00", "cart"),
            self.event(1, "2019-11-08 12:00:01", "purchase"),
        ])
        primary = next(r for r in result["summary"] if r["population"] == "post_warmup" and r["timestamp_rule"] == "allow_equal")
        self.assertEqual(primary["full_chain_users"], 0)
        self.assertEqual(primary["purchase_users"], 0)

    def test_incomplete_users_are_excluded_without_reanchoring_old_users(self):
        result = self.build([
            self.event(1, "2020-02-23 00:00:00", "view"),
            self.event(2, "2020-02-22 23:59:59", "view"),
            self.event(3, "2019-10-15 00:00:00", "view"),
            self.event(3, "2019-11-01 00:00:00", "view"),
            self.event(4, "2019-11-01 00:00:00", "cart"),
        ])
        self.assertEqual(result["coverage"]["incomplete_window_users"], 1)
        self.assertEqual(result["coverage"]["first_view_before_analysis"], 1)
        self.assertEqual(result["coverage"]["primary_eligible_users"], 1)
        self.assertEqual(result["coverage"]["users_without_view"], 1)

    def test_missing_session_does_not_hide_user_history(self):
        result = self.build([
            self.event(1, "2019-10-01 00:00:00", "purchase", ""),
            self.event(1, "2019-11-01 00:00:00", "view", ""),
            self.event(1, "2019-11-02 00:00:00", "cart", ""),
            self.event(1, "2019-11-03 00:00:00", "purchase", ""),
        ])
        self.assertEqual(result["coverage"]["primary_users_with_earlier_activity"], 1)
        self.assertEqual(result["coverage"]["primary_users_with_purchase_before_view"], 1)
        primary = next(r for r in result["summary"] if r["population"] == "post_warmup" and r["timestamp_rule"] == "allow_equal")
        self.assertEqual(primary["full_chain_users"], 1)

    def test_empty_source_has_four_empty_summary_rows(self):
        result = self.build([])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(len(result["summary"]), 4)
        self.assertTrue(all(r["view_users"] == 0 and r["view_to_purchase_rate"] is None for r in result["summary"]))

    def test_builder_repeatability_rollback_and_upstream_invalidation(self):
        self.build([
            self.event(1, "2019-11-01 00:00:00", "view"),
            self.event(1, "2019-11-02 00:00:00", "cart"),
            self.event(1, "2019-11-03 00:00:00", "purchase"),
        ])
        with patch("sys.stdout"):
            first = build_analysis(self.database, include_segments=False)
            second = build_analysis(self.database, include_segments=False)
        self.assertEqual(first["fingerprints"], second["fingerprints"])
        with duckdb.connect(str(self.database)) as connection:
            connection.execute("UPDATE stg_events SET event_type='view' WHERE event_type='purchase'")
        with patch("sys.stdout"), patch("build_analysis.validate_user_models", return_value={"checks": {"forced": False}}):
            with self.assertRaisesRegex(ValueError, "forced"):
                build_analysis(self.database, include_segments=False)
        with duckdb.connect(str(self.database), read_only=True) as connection:
            fingerprint = connection.execute("SELECT BIT_XOR(HASH(t)) FROM user_funnel t").fetchone()[0]
        self.assertEqual(str(fingerprint), first["fingerprints"]["user_funnel"])
        with patch("sys.stdout"):
            build_staging([self.directory / "events.csv"], self.database)
        with duckdb.connect(str(self.database), read_only=True) as connection:
            names = connection.execute("SELECT table_name FROM information_schema.tables WHERE table_name IN ('users','user_funnel','user_funnel_summary')").fetchall()
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
