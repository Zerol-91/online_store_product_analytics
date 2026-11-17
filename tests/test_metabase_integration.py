"""Opt-in checks against the authenticated local Metabase and PostgreSQL."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from local_config import read_env
from metabase_client import authenticated_client
from setup_metabase import load_manifest, provision, verify_reporting
from validate_metabase import validate


@unittest.skipUnless(os.environ.get('RUN_LOCAL_METABASE_TESTS') == '1', 'requires local Metabase login and PostgreSQL')
class MetabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client, cls.values, cls.manifest = authenticated_client(), read_env(), load_manifest()
        verify_reporting(cls.values)

    def test_repeated_provision_preserves_ids_layout_and_unrelated_objects(self):
        before = {item['id'] for item in self.client.request('GET', '/api/card')}
        first = provision(self.client, self.manifest, self.values)
        layout = self.client.request('GET', f"/api/dashboard/{first['dashboard_id']}")
        second = provision(self.client, self.manifest, self.values)
        self.assertEqual(first['cards'], second['cards'])
        self.assertEqual(first['dashboard_id'], second['dashboard_id'])
        self.assertEqual(first['collection_id'], second['collection_id'])
        self.assertEqual(first['database_id'], second['database_id'])
        after = {item['id'] for item in self.client.request('GET', '/api/card')}
        self.assertEqual(after, before | set(first['cards'].values()))
        updated = self.client.request('GET', f"/api/dashboard/{second['dashboard_id']}")
        self.assertEqual({item['id'] for item in layout['dashcards']}, {item['id'] for item in updated['dashcards']})

    def test_saved_queries_and_dashboard_filters_match_postgres(self):
        report = provision(self.client, self.manifest, self.values)
        result = validate(self.client, self.manifest, report, self.values)
        self.assertEqual(len(result['cases']), 21)
        self.assertTrue(result['all_checks_passed'])


if __name__ == '__main__':
    unittest.main()
