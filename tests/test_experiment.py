"""Check single-user experimental entry and complete post-cart outcomes."""

import csv
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audit_data import COLUMNS
from build_staging import build_staging
from build_experiment import build_experiment, TABLES


class ExperimentBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.database=self.directory/'shop.duckdb'
        self.source=self.directory/'events.csv'

    def event(self,user,time,kind='cart',price='10',session='s1'):
        return dict(zip(COLUMNS,[time+' UTC',kind,'1','10','','',price,str(user),session]))

    def build(self,rows):
        with self.source.open('w',encoding='utf-8',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        with patch('sys.stdout'):
            build_staging([self.source],self.database)
            return build_experiment(self.database)

    def fetch(self,sql):
        with duckdb.connect(str(self.database),read_only=True) as c:
            return c.execute(sql).fetchall()

    def test_october_history_does_not_prevent_new_experimental_entry(self):
        report=self.build([self.event(1,'2019-10-01 00:00:00'),self.event(1,'2019-11-01 00:00:00'),
                           self.event(1,'2019-11-03 00:00:00')])
        self.assertEqual(report['coverage']['mature_users_with_preperiod_cart'],1)
        self.assertEqual(self.fetch('SELECT entry_utc,had_cart_before_period FROM cart_experiment_users'),[(datetime(2019,11,1),True)])
        self.assertEqual(self.fetch('SELECT SUM(enrolled_users) FROM cart_experiment_daily'),[(1,)])
        self.assertTrue(all(report['checks'].values()))

    def test_deadline_is_inclusive_and_later_outcome_excluded(self):
        self.build([self.event(1,'2019-11-01 00:00:00'),self.event(2,'2019-11-01 00:00:00'),
                    self.event(1,'2019-11-08 00:00:00','purchase','20'),
                    self.event(2,'2019-11-08 00:00:01','purchase','30')])
        self.assertEqual(self.fetch('SELECT user_id,converted,positive_purchase_value FROM cart_experiment_users ORDER BY user_id'),
                         [(1,True,Decimal('20')),(2,False,Decimal('0'))])

    def test_missing_sessions_and_multiple_purchases_remain_in_user_outcome(self):
        self.build([self.event(1,'2019-11-01 00:00:00',session=''),
                    self.event(1,'2019-11-02 00:00:00','purchase','20',session=''),
                    self.event(1,'2019-11-03 00:00:00','purchase','5',session='s2')])
        self.assertEqual(self.fetch('SELECT converted,positive_purchase_value FROM cart_experiment_users'),[(True,Decimal('25'))])

    def test_equal_timestamp_rule_has_explicit_strict_sensitivity(self):
        self.build([self.event(1,'2019-11-01 00:00:00'),self.event(1,'2019-11-01 00:00:00','purchase')])
        self.assertEqual(self.fetch('SELECT converted,strict_converted,strict_positive_purchase_value FROM cart_experiment_users'),[(True,False,Decimal('0'))])

    def test_duplicates_preserve_value_without_duplicate_enrollment(self):
        rows=[self.event(1,'2019-11-01 00:00:00'),self.event(1,'2019-11-02 00:00:00','purchase','10')]
        self.build(rows+rows)
        self.assertEqual(self.fetch('SELECT converted,positive_purchase_value FROM cart_experiment_users'),[(True,Decimal('20'))])

    def test_incomplete_followup_is_not_a_failed_conversion(self):
        self.build([self.event(1,'2020-02-23 00:00:00'),self.event(1,'2020-02-23 01:00:00','purchase'),
                    self.event(2,'2020-02-22 23:59:59')])
        self.assertEqual(self.fetch('SELECT user_id,has_complete_window,converted,positive_purchase_value FROM cart_experiment_users ORDER BY user_id'),
                         [(1,False,None,None),(2,True,False,Decimal('0'))])

    def test_purchases_before_cart_and_nonpositive_prices(self):
        self.build([self.event(1,'2019-11-01 00:00:00','purchase','100'),self.event(1,'2019-11-02 00:00:00'),
                    self.event(1,'2019-11-03 00:00:00','purchase','-1')])
        self.assertEqual(self.fetch('SELECT converted,positive_purchase_value FROM cart_experiment_users'),[(True,Decimal('0'))])

    def test_empty_baseline_has_two_null_rates(self):
        report=self.build([])
        self.assertTrue(all(report['checks'].values()))
        self.assertEqual(len(report['summary']),2)
        self.assertTrue(all(x['conversion_rate'] is None for x in report['summary']))

    def test_repeat_build_rollback_and_staging_invalidation(self):
        first=self.build([self.event(1,'2019-11-01 00:00:00'),self.event(1,'2019-11-02 00:00:00','purchase')])
        with patch('sys.stdout'):
            second=build_experiment(self.database)
        self.assertEqual(first['fingerprints'],second['fingerprints'])
        with duckdb.connect(str(self.database)) as c:
            c.execute("UPDATE stg_events SET price=20 WHERE event_type='purchase'")
        with patch('sys.stdout'),patch('build_experiment.validate_baseline',side_effect=ValueError('forced')):
            with self.assertRaisesRegex(ValueError,'forced'):
                build_experiment(self.database)
        self.assertEqual(str(self.fetch('SELECT BIT_XOR(HASH(t)) FROM cart_experiment_users t')[0][0]),first['fingerprints']['cart_experiment_users'])
        with patch('sys.stdout'):
            build_staging([self.source],self.database)
        names="','".join(TABLES)
        self.assertEqual(self.fetch(f"SELECT table_name FROM information_schema.tables WHERE table_name IN ('{names}')"),[])

    def test_design_table_reconciles_with_report_and_marks_insufficient_traffic(self):
        report=self.build([self.event(1,'2019-11-01 00:00:00'),self.event(2,'2019-11-01 00:00:00'),
                           self.event(1,'2019-11-02 00:00:00','purchase')])
        self.assertTrue(all(report['design_checks'].values()))
        self.assertEqual(self.fetch('SELECT COUNT(*),COUNT(*) FILTER(WHERE is_primary) FROM experiment_scenarios'),[(4,1)])
        self.assertEqual(report['design']['primary']['replay']['status'],'insufficient_history')
        self.assertFalse(report['design']['primary']['within_study_budget'])

    def test_late_planning_failure_rolls_back_baseline_and_scenario_tables(self):
        first=self.build([self.event(1,'2019-11-01 00:00:00'),self.event(2,'2019-11-01 00:00:00'),
                          self.event(1,'2019-11-02 00:00:00','purchase')])
        with duckdb.connect(str(self.database)) as c:
            c.execute("UPDATE stg_events SET price=20 WHERE event_type='purchase'")
        with patch('sys.stdout'),patch('build_experiment.validate_design',side_effect=ValueError('late failure')):
            with self.assertRaisesRegex(ValueError,'late failure'):
                build_experiment(self.database)
        for table in TABLES:
            self.assertEqual(str(self.fetch(f'SELECT BIT_XOR(HASH(t)) FROM {table} t')[0][0]),first['fingerprints'][table])


if __name__=='__main__':
    unittest.main()
