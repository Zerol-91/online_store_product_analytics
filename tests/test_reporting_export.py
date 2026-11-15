"""Check reporting keys, type fidelity, stale-source rejection, and local configuration."""

import json
import sys
import tempfile
import tomllib
import unittest
from decimal import Decimal
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from export_to_postgres import (ALLOWED_TABLES, REPORT_FILES, load_reports, postgres_type,
                                prepare_snapshots, row_digest, validate_rows)
from local_config import initialize_env, read_env, SECRET_KEYS

ROOT = Path(__file__).resolve().parents[1]


class ReportingExportTests(unittest.TestCase):
    def test_type_mapping_preserves_decimal_and_large_integer_precision(self):
        self.assertEqual(postgres_type('DECIMAL(38,6)'), 'NUMERIC(38,6)')
        self.assertEqual(postgres_type('HUGEINT'), 'NUMERIC(39,0)')
        self.assertEqual(postgres_type('DATE'), 'DATE')
        self.assertEqual(postgres_type('BOOLEAN'), 'BOOLEAN')
        with self.assertRaises(ValueError):
            postgres_type('INTEGER[]')

    def snapshot(self):
        return {'name': 'fixture', 'columns': [('key', 'INTEGER'), ('value', 'NUMERIC(38,6)')],
                'key': ['key'], 'required': [], 'rows': [(2, Decimal('12.500000')), (1, None)]}

    def test_nullable_outcomes_and_order_independent_digest(self):
        first = self.snapshot()
        validate_rows(first)
        second = first | {'rows': list(reversed(first['rows']))}
        self.assertEqual(row_digest(first), row_digest(second))

    def test_invalid_keys_and_nonfinite_values_are_rejected(self):
        for rows in [[(1, None), (1, Decimal('1'))], [(None, Decimal('1'))], [(1, float('nan'))]]:
            with self.assertRaises(ValueError):
                validate_rows(self.snapshot() | {'rows': rows})

    def test_environment_generation_never_overwrites_existing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            self.assertTrue(initialize_env(path))
            original = path.read_bytes()
            values = read_env(path)
            self.assertTrue(all(len(values[key]) >= 20 for key in SECRET_KEYS))
            self.assertEqual(len({values[key] for key in SECRET_KEYS}), len(SECRET_KEYS))
            self.assertFalse(initialize_env(path))
            self.assertEqual(path.read_bytes(), original)

    def test_empty_example_secrets_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError, 'Generate a local'):
            read_env(ROOT/'.env.example')

    def test_stale_report_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as c:
            c.execute('CREATE TABLE stg_events AS SELECT 1 AS event_id')
            fingerprint = str(c.execute('SELECT BIT_XOR(HASH(t)) FROM stg_events t').fetchone()[0])
            report = {'checks': {'fixture': True}, 'fingerprints': {'stg_events': fingerprint}}
            for filename in REPORT_FILES.values():
                (Path(directory)/filename).write_text(json.dumps(report), encoding='utf-8')
            c.execute('UPDATE stg_events SET event_id=2')
            with self.assertRaisesRegex(ValueError, 'Stale funnel report'):
                load_reports(c, Path(directory))

    def test_unvalidated_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as c:
            (Path(directory)/REPORT_FILES['funnel']).write_text(json.dumps({'checks': {'fixture': False}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unvalidated'):
                load_reports(c, Path(directory))

    def test_manifest_does_not_allow_raw_or_user_level_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'reporting.toml'
            config.write_text('schema="reporting"\nmax_rows_per_table=1000\n[[tables]]\nname="stg_events"\nkey=["user_id"]\nrequired=[]\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'selected reporting marts'):
                prepare_snapshots(Path(directory)/'missing.duckdb', Path(directory), config)
        manifest = tomllib.loads((ROOT/'config/reporting.toml').read_text(encoding='utf-8'))
        self.assertEqual({item['name'] for item in manifest['tables']}, ALLOWED_TABLES)


if __name__ == '__main__':
    unittest.main()
