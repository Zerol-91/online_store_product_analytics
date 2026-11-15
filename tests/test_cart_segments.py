"""Check first-cart pricing, calibration dates, and history-only visitor status."""

import csv
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audit_data import COLUMNS
from build_analysis import prepare_parameters, build_user_models, build_segment_models, build_analysis
from build_funnel import build_funnel
from build_staging import build_staging


class CartSegmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.database = self.directory / 'shop.duckdb'
        self.settings = {
            'inactivity_minutes': 30, 'horizon_days': 7, 'primary_timestamp_rule': 'allow_equal',
            'observation_start_utc': datetime(2019, 10, 1), 'analysis_start_utc': datetime(2019, 11, 1),
            'observation_end_exclusive_utc': datetime(2020, 3, 1),
            'price_reference_start_utc': datetime(2019, 10, 1),
            'price_reference_end_exclusive_utc': datetime(2019, 11, 1),
            'alpha': 0.05, 'planned_comparisons': 2,
        }

    def event(self, user, time, kind='cart', price='1', product='1', session='s1'):
        return dict(zip(COLUMNS, [time+' UTC', kind, product, '10', '', '', price, str(user), session]))

    def build(self, rows):
        reference = [self.event(1000+i, '2019-10-15 12:00:00', price=str(price)) for i, price in enumerate([1, 4, 10])]
        source = self.directory / 'events.csv'
        with source.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(reference + rows)
        with patch('sys.stdout'):
            build_staging([source], self.database)
            build_funnel(self.database)
        with duckdb.connect(str(self.database)) as connection:
            prepare_parameters(connection, self.settings)
            build_user_models(connection)
            return build_segment_models(connection, self.settings)

    def fetch(self, sql):
        with duckdb.connect(str(self.database), read_only=True) as connection:
            return connection.execute(sql).fetchall()

    def test_reference_ignores_later_prices_and_boundaries_are_inclusive(self):
        result = self.build([
            self.event(1, '2019-11-01 00:00:00', price='3'),
            self.event(2, '2019-11-01 00:00:00', price='6'),
            self.event(3, '2019-11-01 00:00:00', price='6.01'),
            self.event(4, '2019-11-01 00:00:00', price='999'),
        ])
        self.assertEqual(result['thresholds']['reference_priced_episodes'], 3)
        self.assertEqual(result['thresholds']['low_upper'], Decimal('3'))
        self.assertEqual(result['thresholds']['middle_upper'], Decimal('6'))
        self.assertEqual(self.fetch('SELECT user_id,price_band FROM cart_segments WHERE is_analysis_period ORDER BY user_id'),
                         [(1, 'low'), (2, 'middle'), (3, 'high'), (4, 'high')])

    def test_first_cart_price_does_not_use_later_cart_or_purchase(self):
        self.build([
            self.event(1, '2019-11-01 00:00:00', price='0'),
            self.event(1, '2019-11-01 00:01:00', kind='purchase', price='100'),
            self.event(1, '2019-11-01 00:02:00', price='100'),
        ])
        self.assertEqual(self.fetch('SELECT entry_price,price_band,converted FROM cart_segments WHERE is_analysis_period'),
                         [(None, 'unknown', True)])

    def test_tied_items_use_product_medians_without_duplicate_weight(self):
        self.build([
            self.event(1, '2019-11-01 00:00:00', price='1', product='1'),
            self.event(1, '2019-11-01 00:00:00', price='1', product='1'),
            self.event(1, '2019-11-01 00:00:00', price='1', product='1'),
            self.event(1, '2019-11-01 00:00:00', price='9', product='2'),
        ])
        self.assertEqual(self.fetch('SELECT entry_price,priced_entry_items FROM cart_segments WHERE is_analysis_period'), [(Decimal('5'), 2)])

    def test_user_can_contribute_to_first_and_returning_groups(self):
        result = self.build([
            self.event(1, '2019-11-01 00:00:00'),
            self.event(1, '2019-11-02 00:00:00', session='s2'),
            self.event(1, '2019-11-02 00:01:00', kind='purchase', session='s2'),
        ])
        self.assertEqual(self.fetch("SELECT segment,episodes,conversions FROM cart_segment_users WHERE family='visitor_type' ORDER BY segment"),
                         [('first_observed', 1, 0), ('returning', 1, 1)])
        self.assertTrue(all(result['checks'].values()))

    def test_prior_sessionless_activity_marks_returning(self):
        self.build([
            self.event(1, '2019-10-20 00:00:00', kind='view', session=''),
            self.event(1, '2019-11-01 00:00:00'),
        ])
        self.assertEqual(self.fetch('SELECT visitor_type FROM cart_segments WHERE is_analysis_period'), [('returning',)])

    def test_full_builder_repeatability_threshold_guard_and_upstream_invalidation(self):
        self.build([
            self.event(1, '2019-11-01 00:00:00', kind='view'),
            self.event(1, '2019-11-01 00:01:00'),
            self.event(1, '2019-11-01 00:02:00', kind='purchase'),
        ])
        config = self.directory / 'analysis.toml'
        original = (Path(__file__).resolve().parents[1] / 'config/analysis.toml').read_text(encoding='utf-8')
        config.write_text(original.replace('middle_upper = 6.03', 'middle_upper = 6.00'), encoding='utf-8')
        with patch('sys.stdout'):
            first = build_analysis(self.database, config)
            second = build_analysis(self.database, config)
        self.assertEqual(first['fingerprints'], second['fingerprints'])
        config.write_text(config.read_text(encoding='utf-8').replace('low_upper = 3.00', 'low_upper = 2.00'), encoding='utf-8')
        with patch('sys.stdout'), self.assertRaisesRegex(ValueError, 'threshold changed'):
            build_analysis(self.database, config)
        self.assertEqual(str(self.fetch('SELECT BIT_XOR(HASH(t)) FROM cart_segments t')[0][0]), first['fingerprints']['cart_segments'])
        with patch('sys.stdout'):
            build_funnel(self.database)
        self.assertEqual(self.fetch("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'cart_%' OR table_name='price_thresholds'"), [])
        self.assertEqual(self.fetch('SELECT COUNT(*) FROM users'), [(4,)])
        with patch('sys.stdout'):
            build_staging([self.directory / 'events.csv'], self.database)
        self.assertEqual(self.fetch("SELECT table_name FROM information_schema.tables WHERE table_name IN ('users','user_funnel','user_funnel_summary')"), [])


if __name__ == '__main__':
    unittest.main()
