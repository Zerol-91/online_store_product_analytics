"""Exercise the actual local PostgreSQL instance when explicitly enabled."""

import copy
import os
import sys
import unittest
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from export_to_postgres import prepare_snapshots, publish_snapshots
from local_config import ROOT, read_env, connection_parameters


@unittest.skipUnless(os.environ.get('RUN_LOCAL_POSTGRES_TESTS') == '1', 'Enable RUN_LOCAL_POSTGRES_TESTS for local integration checks.')
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = read_env()
        cls.snapshots, _ = prepare_snapshots(ROOT/'data/processed/shop.duckdb', ROOT/'data/reports', ROOT/'config/reporting.toml')
        cls.parameters = connection_parameters(cls.values)
        cls.first = publish_snapshots(cls.snapshots, cls.parameters)

    def test_repeat_export_has_identical_row_counts_and_digests(self):
        second = publish_snapshots(self.snapshots, self.parameters)
        self.assertEqual(self.first, second)
        self.assertEqual(len(second), 14)
        with psycopg.connect(**self.parameters) as c:
            for result in second:
                count = c.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier('reporting', result['table']))).fetchone()[0]
                self.assertEqual(count, result['rows'])

    def test_late_failure_restores_every_previously_published_table(self):
        broken = copy.deepcopy(self.snapshots)
        first = broken[0]
        index = [name for name, _ in first['columns']].index('units')
        changed = list(first['rows'][0])
        changed[index] += 1
        first['rows'][0] = tuple(changed)
        final = broken[-1]
        final['columns'] = [(name+'_invalid' if name == 'settings_json' else name, kind) for name, kind in final['columns']]
        with self.assertRaisesRegex(ValueError, 'Reporting schema changed'):
            publish_snapshots(broken, self.parameters)
        with psycopg.connect(**self.parameters) as c:
            for snapshot in self.snapshots:
                columns = [name for name, _ in snapshot['columns']]
                indices = [columns.index(key) for key in snapshot['key']]
                expected = sorted(snapshot['rows'], key=lambda row: tuple(row[i] for i in indices))
                actual = c.execute(sql.SQL('SELECT * FROM {} ORDER BY {}').format(
                    sql.Identifier('reporting', snapshot['name']),
                    sql.SQL(',').join(map(sql.Identifier, snapshot['key'])))).fetchall()
                self.assertEqual(actual, expected, snapshot['name'])

    def test_reporting_reader_cannot_write_or_open_application_database(self):
        with psycopg.connect(**connection_parameters(self.values, 'analytics_reader')) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reporting.report_metadata').fetchone()[0], 4)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with c.transaction():
                    c.execute("DELETE FROM reporting.report_metadata WHERE report_name='funnel'")
        with self.assertRaises(psycopg.Error):
            psycopg.connect(**connection_parameters(self.values, 'analytics_reader', 'metabase_app'))

    def test_application_role_is_isolated_from_analytics_database(self):
        with psycopg.connect(**connection_parameters(self.values, 'metabase_app', 'metabase_app')) as c:
            self.assertEqual(c.execute('SELECT CURRENT_DATABASE()').fetchone()[0], 'metabase_app')
        with self.assertRaises(psycopg.Error):
            psycopg.connect(**connection_parameters(self.values, 'metabase_app', 'analytics'))

    def test_large_integer_and_decimal_boundaries_survive_copy(self):
        from decimal import Decimal
        integer = 2**127-1
        amount = Decimal('12345678901234567890123456789012.123456')
        with psycopg.connect(**self.parameters) as c:
            c.execute('CREATE TEMP TABLE numeric_boundary (counter NUMERIC(39,0), amount NUMERIC(38,6), missing NUMERIC(38,6)) ON COMMIT DROP')
            with c.cursor().copy('COPY numeric_boundary FROM STDIN') as transfer:
                transfer.write_row((integer, amount, None))
            actual = c.execute('SELECT * FROM numeric_boundary').fetchone()
            self.assertEqual(actual, (integer, amount, None))


if __name__ == '__main__':
    unittest.main()
