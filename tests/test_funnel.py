"""Check episode boundaries and sequence existence on known event histories."""

import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audit_data import COLUMNS
from build_funnel import build_funnel
from build_staging import build_staging


class FunnelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.database = self.directory / "shop.duckdb"
        self.origin = datetime(2019, 10, 31, 23, 30)

    def event(self, seconds, event_type, **changes):
        row = dict(zip(COLUMNS, [
            (self.origin + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S UTC"),
            event_type, "1", "10", "", "", "10.00", "100", "s1",
        ]))
        return row | changes

    def stage(self, rows):
        source = self.directory / "events.csv"
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        with patch("sys.stdout"):
            build_staging([source], self.database)

    def build(self, rows=None):
        if rows is not None:
            self.stage(rows)
        with patch("sys.stdout"):
            return build_funnel(self.database)

    def row(self, report, definition="episode_30m", rule="allow_equal"):
        return next(row for row in report["summary"] if row["session_definition"] == definition and row["timestamp_rule"] == rule)

    def fetch(self, sql):
        with duckdb.connect(str(self.database), read_only=True) as connection:
            return connection.execute(sql).fetchall()

    def test_30_minutes_and_month_boundary_do_not_split_but_larger_gap_does(self):
        report = self.build([
            self.event(0, "view"), self.event(1800, "cart"),
            self.event(1800, "cart"), self.event(3601, "purchase"),
        ])
        self.assertEqual(report["episode_count"], 2)
        self.assertEqual(self.fetch("SELECT episode_number, event_count FROM episodes ORDER BY episode_number"), [(1, 3), (2, 1)])
        self.assertEqual(self.row(report)["full_chain_units"], 0)
        self.assertEqual(self.row(report, "source_key")["full_chain_units"], 1)
        self.assertTrue(all(report["checks"].values()))

    def test_later_valid_chain_is_found_after_earlier_purchase_and_cart(self):
        report = self.build([
            self.event(0, "purchase"), self.event(60, "cart"), self.event(120, "view"),
            self.event(180, "cart"), self.event(240, "purchase"),
        ])
        self.assertEqual(self.row(report)["full_chain_units"], 1)
        self.assertEqual(self.row(report, rule="strict")["full_chain_units"], 1)
        self.assertEqual(self.fetch("SELECT cart_after_view_utc, purchase_after_view_cart_utc FROM episodes"),
            [(self.origin + timedelta(seconds=180), self.origin + timedelta(seconds=240))])

    def test_event_presence_in_reverse_order_is_not_a_funnel(self):
        report = self.build([self.event(0, "purchase"), self.event(60, "cart"), self.event(120, "view")])
        row = self.row(report)
        self.assertEqual((row["view_units"], row["cart_units"], row["purchase_units"]), (1, 1, 1))
        self.assertEqual((row["view_cart_units"], row["full_chain_units"], row["cart_purchase_units"]), (0, 0, 0))
        self.assertEqual(row["abandoned_cart_units"], 1)

    def test_equal_timestamps_are_order_independent_and_reported_as_sensitivity(self):
        report = self.build([self.event(0, kind) for kind in ("purchase", "view", "cart", "cart")])
        self.assertEqual(self.row(report)["full_chain_units"], 1)
        self.assertEqual(self.row(report, rule="strict")["full_chain_units"], 0)
        self.assertEqual(report["episode_count"], 1)
        self.assertEqual(self.fetch("SELECT event_count FROM episodes"), [(4,)])

    def test_cart_purchase_without_view_is_visible_outside_full_funnel(self):
        report = self.build([self.event(0, "cart"), self.event(60, "purchase")])
        row = self.row(report)
        self.assertEqual((row["full_chain_units"], row["cart_purchase_units"]), (0, 1))
        self.assertEqual(row["purchase_units_without_ordered_chain"], 1)
        self.assertIsNone(row["view_to_cart_rate"])
        self.assertEqual(row["cart_abandonment_rate"], 0)

    def test_different_users_and_source_tokens_never_merge(self):
        report = self.build([
            self.event(0, "view"), self.event(60, "cart"),
            self.event(120, "purchase", user_id="200"),
            self.event(120, "purchase", user_session="s2"),
        ])
        row = self.row(report)
        self.assertEqual(row["units"], 3)
        self.assertEqual(row["full_chain_units"], 0)
        self.assertEqual(row["purchase_units_without_cart"], 2)

    def test_ineligible_and_empty_sources_have_no_sessions_or_false_rates(self):
        report = self.build([self.event(0, "purchase", user_session="")])
        self.assertEqual(report["episode_count"], 0)
        self.assertEqual(report["coverage"]["purchase_events_excluded"], 1)
        self.assertEqual(self.row(report)["units"], 0)
        self.assertIsNone(self.row(report)["cart_to_purchase_rate"])
        report = self.build([])
        self.assertEqual(len(report["summary"]), 4)
        self.assertTrue(all(report["checks"].values()))

    def test_cart_at_observation_end_is_flagged(self):
        report = self.build([self.event(0, "cart", event_time="2020-02-29 23:40:00 UTC")])
        row = self.row(report)
        self.assertEqual(row["units_open_at_observation_end"], 1)
        self.assertEqual(row["abandoned_cart_units_open_at_end"], 1)

    def test_repeat_build_and_failed_validation_preserve_previous_result(self):
        first = self.build([self.event(0, "view"), self.event(60, "cart"), self.event(120, "purchase")])
        second = self.build()
        self.assertEqual(first["fingerprints"], second["fingerprints"])
        with duckdb.connect(str(self.database)) as connection:
            connection.execute("UPDATE stg_events SET event_type='remove_from_cart' WHERE event_type='purchase'")
        with patch("build_funnel.validate_funnel", side_effect=ValueError("test failure")):
            with self.assertRaisesRegex(ValueError, "test failure"):
                self.build()
        fingerprint = self.fetch("SELECT BIT_XOR(HASH(t)) FROM session_funnel t")[0][0]
        self.assertEqual(str(fingerprint), first["fingerprints"]["session_funnel"])

    def test_staging_rebuild_invalidates_downstream_tables(self):
        self.build([self.event(0, "view")])
        self.stage([self.event(0, "cart")])
        names = self.fetch("SELECT table_name FROM information_schema.tables WHERE table_name IN ('episodes', 'episode_events', 'session_funnel', 'funnel_summary')")
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
