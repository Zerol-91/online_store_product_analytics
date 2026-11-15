"""Check purchase proxies, complete follow-up, and calendar cohort semantics."""

import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audit_data import COLUMNS
from build_cohorts import build_cohorts, cohort_settings, MARTS, REPORTING
from build_funnel import build_funnel
from build_staging import build_staging

ROOT = Path(__file__).resolve().parents[1]


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.database = self.directory / "shop.duckdb"
        self.source = self.directory / "events.csv"
        self.config = self.directory / "analysis.toml"
        self.config.write_text((ROOT / "config/analysis.toml").read_text(encoding="utf-8"), encoding="utf-8")

    def event(self, user, time, kind="purchase", price="10", product="1", session="s1"):
        if isinstance(time, datetime):
            time = time.strftime("%Y-%m-%d %H:%M:%S")
        return dict(zip(COLUMNS, [time + " UTC", kind, product, "10", "", "", price, str(user), session]))

    def build(self, rows):
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        with patch("sys.stdout"):
            build_staging([self.source], self.database)
            build_funnel(self.database)
            return build_cohorts(self.database, self.config)

    def fetch(self, query):
        with duckdb.connect(str(self.database), read_only=True) as c:
            return c.execute(query).fetchall()

    def test_items_duplicates_and_later_purchase_rows_in_initial_episode_are_not_repeats(self):
        rows = [self.event(1, "2019-11-01 00:00:00"), self.event(1, "2019-11-01 00:00:00"),
                self.event(1, "2019-11-01 00:00:00", price="20", product="2"),
                self.event(1, "2019-11-01 00:02:00", price="5")]
        report = self.build(rows)
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["audit"]["multi_timestamp_episodes"], 1)
        self.assertEqual(self.fetch("SELECT first_repeat_utc,purchase_episode_count FROM buyer_history"), [(None, 1)])
        self.assertEqual(self.fetch("SELECT repeated,total_positive_purchase_value,repeat_positive_purchase_value FROM buyer_outcomes WHERE horizon_days=30"),
                         [(False, Decimal("45"), Decimal("0"))])

    def test_inclusive_deadlines_and_value_windows(self):
        start = datetime(2019, 11, 1)
        rows = [self.event(u, start) for u in (1, 2, 3)]
        rows += [self.event(1, start + timedelta(days=30), price="20"),
                 self.event(2, start + timedelta(days=30, seconds=1), price="20"),
                 self.event(3, start + timedelta(days=60), price="30")]
        self.build(rows)
        self.assertEqual(self.fetch("SELECT user_id,repeated,total_positive_purchase_value FROM buyer_outcomes WHERE horizon_days=30 ORDER BY user_id"),
                         [(1, True, Decimal("30")), (2, False, Decimal("10")), (3, False, Decimal("10"))])
        self.assertEqual(self.fetch("SELECT repeated FROM buyer_outcomes WHERE horizon_days=60 ORDER BY user_id"), [(True,), (True,), (True,)])

    def test_maturity_requires_deadline_before_exclusive_end(self):
        self.build([self.event(1, "2020-01-01 00:00:00"), self.event(2, "2019-12-31 23:59:59")])
        self.assertEqual(self.fetch("SELECT user_id,has_complete_window,repeated FROM buyer_outcomes WHERE horizon_days=60 ORDER BY user_id"),
                         [(1, False, None), (2, True, False)])
        self.assertEqual(self.fetch("SELECT total_positive_purchase_value FROM buyer_outcomes WHERE user_id=1 AND horizon_days=60"), [(None,)])
        self.assertEqual(self.fetch("SELECT eligible_users,repeat_rate FROM cohort_summary WHERE cohort_id='month_2020_01' AND horizon_days=30 AND population='common_horizon'"), [(0, None)])
        self.assertEqual(self.fetch("SELECT eligible_users FROM cohort_summary WHERE cohort_id='month_2020_01' AND horizon_days=30 AND population='horizon_mature'"), [(1,)])

    def test_simultaneous_initial_episodes_and_overlap_sensitivity(self):
        self.build([
            self.event(1, "2019-11-01 00:00:00", session="a"),
            self.event(1, "2019-11-01 00:00:00", session="b"),
            self.event(2, "2019-11-02 00:00:00", session="a"),
            self.event(2, "2019-11-02 00:10:00", session="b"),
            self.event(2, "2019-11-02 00:20:00", kind="view", session="a"),
            self.event(2, "2019-11-02 00:40:00", session="a"),
            self.event(3, "2019-11-03 00:00:00"),
        ])
        self.assertEqual(self.fetch("SELECT first_repeat_utc,initial_episode_count FROM buyer_history WHERE user_id=1"), [(None, 2)])
        self.assertEqual(self.fetch("SELECT COUNT(*) FROM buyer_history WHERE has_overlapping_purchase_episodes"), [(2,)])
        self.assertEqual(self.fetch("SELECT eligible_users,repeat_users FROM cohort_summary WHERE cohort_id='month_2019_11' AND horizon_days=60 AND population='common_horizon'"), [(3, 1)])
        self.assertEqual(self.fetch("SELECT eligible_users,repeat_users FROM cohort_summary WHERE cohort_id='month_2019_11' AND horizon_days=60 AND population='common_horizon_no_overlap'"), [(1, 0)])

    def test_october_first_purchases_do_not_reenter_november_cohorts(self):
        self.build([self.event(1, "2019-10-15 00:00:00"), self.event(1, "2019-11-29 00:00:00")])
        self.assertEqual(self.fetch("SELECT COUNT(*) FROM cohort_memberships"), [(0,)])
        self.assertEqual(self.fetch("SELECT first_purchase_utc FROM buyer_history"), [(datetime(2019, 10, 15),)])

    def test_week_boundaries_and_day_sensitivity_overlap_are_explicit(self):
        self.build([self.event(1, "2019-11-25 00:00:00"), self.event(2, "2019-12-02 00:00:00"),
                    self.event(3, "2019-11-29 12:00:00")])
        self.assertEqual(self.fetch("SELECT user_id,cohort_id FROM cohort_memberships WHERE cohort_id IN ('black_friday_week','post_black_friday','black_friday_day') ORDER BY user_id,cohort_id"),
                         [(1, "black_friday_week"), (2, "post_black_friday"), (3, "black_friday_day"), (3, "black_friday_week")])

    def test_monthly_repurchase_is_not_elapsed_thirty_days(self):
        self.build([self.event(1, "2019-11-30 23:59:00"), self.event(1, "2019-12-01 00:31:00"),
                    self.event(2, "2020-01-31 23:59:00"), self.event(2, "2020-02-01 00:31:00"),
                    self.event(3, "2019-11-30 23:59:00"), self.event(3, "2019-12-01 00:01:00")])
        self.assertEqual(self.fetch("SELECT repeat_users,repeat_rate FROM monthly_repurchase WHERE cohort_id='month_2019_11' AND month_age=1"), [(1, 0.5)])
        self.assertEqual(self.fetch("SELECT repeat_users,repeat_rate FROM monthly_repurchase WHERE cohort_id='month_2020_01' AND month_age=2"), [(None, None)])
        self.assertEqual(self.fetch("SELECT has_complete_month,repeat_users FROM monthly_repurchase WHERE cohort_id='month_2020_01' AND month_age=1"), [(True, 1)])

    def test_value_uses_event_deadline_when_initial_episode_spans_it(self):
        self.config.write_text(self.config.read_text(encoding="utf-8").replace("horizons_days = [30, 60]", "horizons_days = [1, 2]"), encoding="utf-8")
        start = datetime(2019, 11, 1)
        rows = [self.event(1, start)]
        rows += [self.event(1, start + timedelta(minutes=20*i), kind="view") for i in range(1, 73)]
        rows += [self.event(1, start + timedelta(days=1, minutes=1), price="100")]
        self.build(rows)
        self.assertEqual(self.fetch("SELECT horizon_days,repeated,total_positive_purchase_value FROM buyer_outcomes ORDER BY horizon_days"),
                         [(1, False, Decimal("10")), (2, False, Decimal("110"))])

    def test_empty_history_has_null_rates_and_valid_grids(self):
        report = self.build([])
        self.assertTrue(all(report["checks"].values()))
        self.assertTrue(all(row["repeat_rate"] is None for row in report["summary"]))

    def test_nonpositive_prices_preserve_purchase_and_repeat_behavior(self):
        self.build([self.event(1, "2019-11-01 00:00:00", price="-1"),
                    self.event(1, "2019-11-02 00:00:00", price="0")])
        self.assertEqual(self.fetch("SELECT repeated,total_positive_purchase_value FROM buyer_outcomes WHERE horizon_days=30"),
                         [(True, Decimal("0"))])

    def test_uncovered_purchase_stops_build(self):
        with self.assertRaisesRegex(ValueError, "purchase_source_coverage"):
            self.build([self.event(1, "2019-11-01 00:00:00", session="")])

    def test_rebuild_rollback_and_upstream_invalidation(self):
        first = self.build([self.event(1, "2019-11-11 00:00:00"), self.event(1, "2019-11-12 00:00:00")])
        with patch("sys.stdout"):
            second = build_cohorts(self.database, self.config)
        self.assertEqual(first["fingerprints"], second["fingerprints"])
        with duckdb.connect(str(self.database)) as c:
            c.execute("UPDATE episode_events SET price=20 WHERE event_type='purchase'")
        with patch("sys.stdout"), patch("build_cohorts.validate_models", side_effect=ValueError("forced")):
            with self.assertRaisesRegex(ValueError, "forced"):
                build_cohorts(self.database, self.config)
        self.assertEqual(str(self.fetch("SELECT BIT_XOR(HASH(t)) FROM purchase_episodes t")[0][0]), first["fingerprints"]["purchase_episodes"])
        with patch("sys.stdout"):
            build_funnel(self.database)
        names = "','".join(MARTS + REPORTING)
        self.assertEqual(self.fetch(f"SELECT table_name FROM information_schema.tables WHERE table_name IN ('{names}')"), [])
        with patch("sys.stdout"):
            build_cohorts(self.database, self.config)
            build_staging([self.source], self.database)
        self.assertEqual(self.fetch(f"SELECT table_name FROM information_schema.tables WHERE table_name IN ('{names}')"), [])

    def test_invalid_config_rejects_duplicate_horizons_and_overlapping_weeks(self):
        text = self.config.read_text(encoding="utf-8")
        self.config.write_text(text.replace("horizons_days = [30, 60]", "horizons_days = [30, 30]"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "distinct"):
            cohort_settings(self.config)
        self.config.write_text(text.replace('start_utc = "2019-11-18T00:00:00"', 'start_utc = "2019-11-17T00:00:00"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            cohort_settings(self.config)


if __name__ == "__main__":
    unittest.main()
