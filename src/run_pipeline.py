"""Audit inputs and rebuild the analytical database, reports and figures in order."""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from build_staging import ROOT, SOURCE_NAMES


def pipeline_steps(input_dir, database, reports_dir, figures_dir, config):
    steps = [('audit_' + Path(name).stem, ['src/audit_data.py', '--input', str(input_dir/name),
              '--output', str(reports_dir/(Path(name).stem+'_audit.json')), '--duplicates'])
             for name in SOURCE_NAMES]
    for script, report in (('build_staging', 'staging_build'), ('build_funnel', 'funnel_build'),
                           ('build_analysis', 'user_analysis'), ('build_cohorts', 'cohort_analysis'),
                           ('build_experiment', 'experiment_baseline')):
        arguments = [f'src/{script}.py', '--database', str(database), '--report', str(reports_dir/(report+'.json'))]
        arguments += ['--input-dir', str(input_dir)] if script == 'build_staging' else ['--config', str(config)]
        steps.append((script, arguments))
    for script, report, figure in (
        ('plot_segments', 'user_analysis', 'cart_conversion_by_segment'),
        ('plot_cohorts', 'cohort_analysis', 'repeat_purchase_cohorts'),
        ('plot_experiment', 'experiment_baseline', 'experiment_design'),
    ):
        steps.append((script, [f'src/{script}.py', '--report', str(reports_dir/(report+'.json')),
                              '--output', str(figures_dir/(figure+'.png'))]))
    return steps


def validate_paths(input_dir, database, reports_dir, figures_dir, config):
    raw = ROOT/'data/raw'
    for target in (database, reports_dir, figures_dir):
        if target.is_relative_to(raw) or target.is_relative_to(input_dir):
            raise ValueError('Write derived outputs outside raw/input directories.')
    if database.suffix != '.duckdb' or not config.is_file():
        raise ValueError('Use a .duckdb output and an existing analytical configuration.')
    for name in SOURCE_NAMES:
        if not (input_dir/name).is_file():
            raise ValueError(f'Missing source file: {name}')
    if database.is_relative_to(reports_dir) or database.is_relative_to(figures_dir):
        raise ValueError('Keep the database outside report and figure directories.')
    if reports_dir == figures_dir or reports_dir.is_relative_to(figures_dir) or figures_dir.is_relative_to(reports_dir):
        raise ValueError('Use separate report and figure directories.')


def run_pipeline(input_dir, database, reports_dir, figures_dir, config):
    input_dir, database, reports_dir, figures_dir, config = (
        path.resolve() for path in (input_dir, database, reports_dir, figures_dir, config))
    validate_paths(input_dir, database, reports_dir, figures_dir, config)
    reports_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir/'pipeline_build.json'
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running',
              'database': str(database), 'config': str(config), 'steps': []}
    def save():
        report_path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    save()
    for name, arguments in pipeline_steps(input_dir, database, reports_dir, figures_dir, config):
        print(f'\nPipeline: {name}', flush=True)
        start = time.monotonic()
        result = subprocess.run([sys.executable, *arguments], cwd=ROOT, check=False)
        report['steps'].append({'name': name, 'returncode': result.returncode,
                                'seconds': round(time.monotonic()-start, 3)})
        if result.returncode:
            report.update(status='failed', failed_step=name)
            save()
            raise RuntimeError(f'{name} failed; downstream stages were not run. See {report_path}')
        save()
    report.update(status='complete', completed_at_utc=datetime.now(timezone.utc).isoformat())
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=ROOT/'data/raw')
    parser.add_argument('--database', type=Path, default=ROOT/'data/processed/shop.duckdb')
    parser.add_argument('--reports-dir', type=Path, default=ROOT/'data/reports')
    parser.add_argument('--figures-dir', type=Path, default=ROOT/'docs/img')
    parser.add_argument('--config', type=Path, default=ROOT/'config/analysis.toml')
    args = parser.parse_args()
    try:
        report = run_pipeline(args.input_dir, args.database, args.reports_dir, args.figures_dir, args.config)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Pipeline failed: {error}', file=sys.stderr)
        return 1
    print(f"Completed {len(report['steps'])} stages. BI export/provisioning are separate commands.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
