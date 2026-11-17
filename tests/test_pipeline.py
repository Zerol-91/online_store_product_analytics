"""Verify pipeline path protection and failure propagation without rebuilding the source."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from build_staging import SOURCE_NAMES
from run_pipeline import pipeline_steps, run_pipeline, validate_paths


class PipelineTests(unittest.TestCase):
    def test_failed_stage_stops_before_downstream_and_invalidates_success_status(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sources = base/'input'
            sources.mkdir()
            for name in SOURCE_NAMES:
                (sources/name).write_text('fixture', encoding='utf-8')
            config = base/'analysis.toml'
            config.write_text('', encoding='utf-8')
            reports = base/'reports'
            reports.mkdir()
            (reports/'pipeline_build.json').write_text('{"status":"complete"}', encoding='utf-8')
            ok = type('Result', (), {'returncode': 0})()
            failure = type('Result', (), {'returncode': 7})()
            with patch('run_pipeline.subprocess.run', side_effect=[ok, failure]) as runner:
                with self.assertRaisesRegex(RuntimeError, 'downstream stages were not run'):
                    run_pipeline(sources, base/'shop.duckdb', reports, base/'figures', config)
                self.assertEqual(runner.call_count, 2)
            report = json.loads((reports/'pipeline_build.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['failed_step'], 'audit_2019-Nov')
            self.assertEqual(len(report['steps']), 2)

    def test_outputs_cannot_overwrite_raw_inputs_or_mix_artifact_directories(self):
        base = Path.cwd().resolve()
        for database, reports, figures in (
            (base/'data/raw/shop.duckdb', base/'data/reports', base/'docs/img'),
            (base/'data/processed/shop.duckdb', base/'data/raw/reports', base/'docs/img'),
            (base/'data/processed/shop.duckdb', base/'data/reports', base/'data/reports/figures'),
        ):
            with self.subTest(database=database, reports=reports), self.assertRaises(ValueError):
                validate_paths(base/'data/raw', database, reports, figures, base/'config/analysis.toml')

    def test_all_builders_share_requested_database_and_reports(self):
        base = Path('isolated')
        steps = pipeline_steps(base/'input', base/'shop.duckdb', base/'reports', base/'figures', base/'analysis.toml')
        builders = [args for name, args in steps if name.startswith('build_')]
        self.assertEqual(len(steps), 13)
        self.assertEqual(len(builders), 5)
        for arguments in builders:
            self.assertEqual(arguments[arguments.index('--database')+1], str(base/'shop.duckdb'))


if __name__ == '__main__':
    unittest.main()
