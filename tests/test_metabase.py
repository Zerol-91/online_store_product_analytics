"""Validate reporting declarations and SQL parameter handling without local services."""

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from metabase_client import Client
from setup_metabase import card_payload, entity_id, load_manifest, unique_match
from validate_metabase import equal_rows, render_sql


class DashboardTests(unittest.TestCase):
    def test_manifest_has_nonoverlapping_layout_and_exact_sql_files(self):
        manifest = load_manifest()
        files = {path.stem for path in (Path(__file__).resolve().parents[1]/'metabase/sql').glob('*.sql')}
        self.assertEqual(files, {card['key'] for card in manifest['cards']})
        self.assertEqual(len(manifest['cards']), 14)

    def test_ambiguous_objects_fail_instead_of_updating_arbitrarily(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            unique_match([{'id': 1}, {'id': 2}], lambda _: True, 'card')

    def test_identifiers_are_stable_and_valid_nanoids(self):
        self.assertEqual(entity_id('weekly_curves'), entity_id('weekly_curves'))
        self.assertNotEqual(entity_id('weekly_curves'), entity_id('weekly_intervals'))
        self.assertRegex(entity_id('weekly_curves'), r'^[A-Za-z0-9_-]{21}$')

    def test_template_values_are_bound_without_sql_interpolation(self):
        query = 'SELECT * FROM reporting.t WHERE rule={{rule}} [[AND month={{month}}]];'
        sql, parameters = render_sql(query, {'rule': "x'; DELETE FROM reporting.t; --"})
        self.assertEqual(sql, 'SELECT * FROM reporting.t WHERE rule=%s ;')
        self.assertEqual(len(parameters), 1)
        sql, parameters = render_sql(query, {'rule': 'allow_equal', 'month': '2020-02'})
        self.assertEqual(parameters, ['allow_equal', '2020-02'])
        self.assertIn('AND month=%s', sql)
        with self.assertRaises(ValueError):
            render_sql(query, {})
        self.assertEqual(render_sql('-- 95% interval\nSELECT {{rule}}', {'rule': 'strict'})[0],
                         '-- 95%% interval\nSELECT %s')

    def test_missing_followup_is_not_equal_to_zero(self):
        self.assertTrue(equal_rows([(Decimal('0.1234'), None)], [[0.1234, None]]))
        self.assertFalse(equal_rows([(None,)], [[0]]))
        self.assertFalse(equal_rows([(1,)], []))
        self.assertFalse(equal_rows([(1,)], [[1, 2]]))

    def test_only_loopback_urls_can_receive_credentials(self):
        for url in ('https://example.com', 'http://localhost.evil', 'http://u:p@localhost:3000',
                    'http://127.0.0.1:3000/api', 'http://localhost:3000?token=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Client(url)
        self.assertEqual(Client('http://127.0.0.1:3000').base_url, 'http://127.0.0.1:3000')

    def test_filters_cannot_change_fixed_black_friday_populations(self):
        manifest = load_manifest()
        for card in manifest['cards']:
            payload = card_payload(card, 2, 3)
            tags = payload['dataset_query']['native']['template-tags']
            if card['key'] in ('weekly_curves', 'weekly_intervals', 'repeat_30d', 'conditional_value'):
                self.assertEqual(tags, {})
            if 'timestamp_rule' in tags:
                self.assertEqual(tags['timestamp_rule']['default'], 'allow_equal')
                self.assertTrue(tags['timestamp_rule']['required'])

    def test_overlapping_layout_is_rejected(self):
        manifest = load_manifest()
        for key in ('row', 'col', 'width', 'height'):
            manifest['cards'][1][key] = manifest['cards'][0][key]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'dashboard.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                load_manifest(path)


if __name__ == '__main__':
    unittest.main()
