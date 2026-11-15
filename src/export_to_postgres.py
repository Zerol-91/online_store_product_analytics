"""Publish validated reporting snapshots to the local analytics database."""

import argparse
import hashlib
import json
import math
import re
import sys
import tomllib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import psycopg
from psycopg import sql

from local_config import ROOT, connection_parameters, read_env

REPORT_FILES = {'funnel': 'funnel_build.json', 'user_analysis': 'user_analysis.json',
                'cohort': 'cohort_analysis.json', 'experiment': 'experiment_baseline.json'}
ALLOWED_TABLES = {'funnel_summary', 'user_funnel_summary', 'cart_segment_summary', 'cohort_summary',
                  'cohort_curves', 'monthly_repurchase', 'cart_experiment_summary',
                  'cart_experiment_daily', 'experiment_scenarios'}


def postgres_type(duck_type):
    name = str(duck_type)
    types = {'BOOLEAN': 'BOOLEAN', 'TINYINT': 'SMALLINT', 'SMALLINT': 'SMALLINT',
             'INTEGER': 'INTEGER', 'BIGINT': 'BIGINT', 'HUGEINT': 'NUMERIC(39,0)',
             'UTINYINT': 'SMALLINT', 'USMALLINT': 'INTEGER', 'UINTEGER': 'BIGINT',
             'UBIGINT': 'NUMERIC(20,0)', 'UHUGEINT': 'NUMERIC(39,0)',
             'FLOAT': 'REAL', 'DOUBLE': 'DOUBLE PRECISION', 'VARCHAR': 'TEXT',
             'DATE': 'DATE', 'TIMESTAMP': 'TIMESTAMP WITHOUT TIME ZONE',
             'TIMESTAMP WITH TIME ZONE': 'TIMESTAMP WITH TIME ZONE'}
    if name in types:
        return types[name]
    if re.fullmatch(r'DECIMAL\(\d+,\d+\)', name):
        return name.replace('DECIMAL', 'NUMERIC')
    raise ValueError(f'Unsupported export type: {name}')


def validate_rows(snapshot):
    names = [name for name, _ in snapshot['columns']]
    key_positions = [names.index(name) for name in snapshot['key']]
    required_positions = [names.index(name) for name in set(snapshot['key'] + snapshot['required'])]
    seen = set()
    for row in snapshot['rows']:
        if any(row[index] is None for index in required_positions):
            raise ValueError(f"Required NULL in {snapshot['name']}.")
        key = tuple(row[index] for index in key_positions)
        if key in seen:
            raise ValueError(f"Duplicate reporting key in {snapshot['name']}.")
        seen.add(key)
        if any(isinstance(value, (float, Decimal)) and not math.isfinite(value) for value in row):
            raise ValueError(f"Non-finite reporting value in {snapshot['name']}.")


def fingerprint_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def row_digest(snapshot):
    names = [name for name, _ in snapshot['columns']]
    positions = [names.index(name) for name in snapshot['key']]
    rows = sorted(snapshot['rows'], key=lambda row: tuple(row[p] for p in positions))
    payload = [[fingerprint_value(value) for value in row] for row in rows]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def snapshot_from_records(name, key, columns, records, required=()):
    return {'name': name, 'key': list(key), 'required': list(required), 'columns': list(columns),
            'rows': [tuple(row[column] for column, _ in columns) for row in records]}


def load_reports(connection, directory):
    reports = {}
    verified = {}
    for name, filename in REPORT_FILES.items():
        report = json.loads((directory/filename).read_text(encoding='utf-8'))
        if not report['checks'] or not all(report['checks'].values()):
            raise ValueError(f'Unvalidated source report: {name}.')
        for section in ('design_checks',):
            if section in report and not all(report[section].values()):
                raise ValueError(f'Unvalidated {section}: {name}.')
        if name == 'user_analysis' and not all(report['segments']['checks'].values()):
            raise ValueError('Unvalidated segment report.')
        expected = dict(report['fingerprints'])
        expected.update(report.get('upstream_fingerprints', {}))
        if 'staging_fingerprint' in report:
            expected['stg_events'] = report['staging_fingerprint']
        for table, fingerprint in expected.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]*', table):
                raise ValueError('Invalid source fingerprint table.')
            if table not in verified:
                verified[table] = str(connection.execute(f'SELECT BIT_XOR(HASH(t)) FROM {table} t').fetchone()[0])
            if verified[table] != fingerprint:
                raise ValueError(f'Stale {name} report; rebuild {table} and its report before export.')
        reports[name] = report
    return reports, verified


def report_snapshots(reports):
    snapshots = []
    rate_columns = [('estimate', 'DOUBLE PRECISION'), ('eligible_users', 'BIGINT'),
                    ('converted_users', 'BIGINT'), ('confidence_level', 'DOUBLE PRECISION'),
                    ('standard_error', 'DOUBLE PRECISION'), ('ci_low', 'DOUBLE PRECISION'),
                    ('ci_high', 'DOUBLE PRECISION'), ('inference_status', 'TEXT')]
    estimates = reports['user_analysis']['segments']['statistics']['estimates']
    columns = [('family', 'TEXT'), ('segment', 'TEXT'), ('estimate', 'DOUBLE PRECISION'),
               ('clusters', 'BIGINT'), ('episodes', 'BIGINT'), ('conversions', 'BIGINT'),
               ('confidence_level', 'DOUBLE PRECISION'), ('standard_error', 'DOUBLE PRECISION'),
               ('ci_low', 'DOUBLE PRECISION'), ('ci_high', 'DOUBLE PRECISION'), ('inference_status', 'TEXT')]
    snapshots.append(snapshot_from_records('cart_segment_estimates', ('family', 'segment'), columns, estimates,
                                           ('clusters', 'episodes', 'conversions')))
    columns = [('family', 'TEXT'), ('group_a', 'TEXT'), ('group_b', 'TEXT'),
               ('estimate', 'DOUBLE PRECISION'), ('clusters', 'BIGINT'), ('rate_a', 'DOUBLE PRECISION'),
               ('rate_b', 'DOUBLE PRECISION'), ('confidence_level', 'DOUBLE PRECISION'),
               ('standard_error', 'DOUBLE PRECISION'), ('ci_low', 'DOUBLE PRECISION'),
               ('ci_high', 'DOUBLE PRECISION'), ('p_value', 'DOUBLE PRECISION'),
               ('adjusted_p_value', 'DOUBLE PRECISION'), ('inference_status', 'TEXT')]
    contrasts = reports['user_analysis']['segments']['statistics']['contrasts']
    snapshots.append(snapshot_from_records('cart_segment_contrasts', ('family', 'group_a', 'group_b'), columns, contrasts))
    for report, table, keys in (
        (reports['cohort'], 'cohort_rate_intervals', [('cohort_id', 'TEXT'), ('horizon_days', 'INTEGER'), ('population', 'TEXT')]),
        (reports['experiment'], 'cart_experiment_rate_intervals', [('timestamp_rule', 'TEXT')]),
    ):
        records = [row | {'eligible_users': row['episodes'], 'converted_users': row['conversions']}
                   for row in report['rate_intervals']]
        snapshots.append(snapshot_from_records(table, [key for key, _ in keys], keys+rate_columns, records,
                                               ('eligible_users', 'converted_users', 'inference_status')))
    metadata = []
    for name, report in reports.items():
        settings = report['settings']
        staging = report.get('staging_fingerprint', report.get('upstream_fingerprints', {}).get('stg_events'))
        metadata.append({'report_name': name, 'completed_at_utc': datetime.fromisoformat(report['completed_at_utc']),
            'observation_start_utc': datetime.fromisoformat(settings['observation_start_utc']),
            'observation_end_exclusive_utc': datetime.fromisoformat(settings['observation_end_exclusive_utc']),
            'analysis_start_utc': datetime.fromisoformat(settings.get('analysis_start_utc', settings.get('entry_start_utc', settings['observation_start_utc']))),
            'staging_fingerprint': staging, 'settings_json': json.dumps(settings, sort_keys=True)})
    columns = [('report_name', 'TEXT'), ('completed_at_utc', 'TIMESTAMP WITH TIME ZONE'),
               ('observation_start_utc', 'TIMESTAMP WITHOUT TIME ZONE'),
               ('observation_end_exclusive_utc', 'TIMESTAMP WITHOUT TIME ZONE'),
               ('analysis_start_utc', 'TIMESTAMP WITHOUT TIME ZONE'),
               ('staging_fingerprint', 'TEXT'), ('settings_json', 'TEXT')]
    snapshots.append(snapshot_from_records('report_metadata', ('report_name',), columns, metadata,
                                           ('completed_at_utc', 'staging_fingerprint')))
    return snapshots


def prepare_snapshots(database, reports_dir, config):
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['schema'] != 'reporting' or not 0 < settings['max_rows_per_table'] <= 100000:
        raise ValueError('Use the reporting schema and bounded aggregate exports.')
    names = [item['name'] for item in settings['tables']]
    if len(set(names)) != len(names) or set(names) != ALLOWED_TABLES:
        raise ValueError('Export exactly the selected reporting marts; raw/user-level tables are not allowed.')
    snapshots = []
    with duckdb.connect(str(database), read_only=True, config={'memory_limit': '1GB', 'threads': '2'}) as c:
        c.execute('SET enable_progress_bar = false')
        reports, fingerprints = load_reports(c, reports_dir)
        for item in settings['tables']:
            count = c.execute(f"SELECT COUNT(*) FROM {item['name']}").fetchone()[0]
            if count > settings['max_rows_per_table']:
                raise ValueError('Reporting export exceeds its row limit.')
            result = c.execute(f"SELECT * FROM {item['name']}")
            columns = [(column[0], postgres_type(column[1])) for column in result.description]
            snapshots.append(item | {'columns': columns, 'rows': result.fetchall()})
    snapshots.extend(report_snapshots(reports))
    for snapshot in snapshots:
        validate_rows(snapshot)
    return snapshots, fingerprints


def load_table(connection, snapshot):
    target = sql.Identifier('reporting', snapshot['name'])
    names = [name for name, _ in snapshot['columns']]
    required = set(snapshot['key']+snapshot['required'])
    definitions = [sql.SQL('{} {}{}').format(sql.Identifier(name), sql.SQL(kind),
                    sql.SQL(' NOT NULL' if name in required else '')) for name, kind in snapshot['columns']]
    definitions.append(sql.SQL('PRIMARY KEY ({})').format(sql.SQL(',').join(map(sql.Identifier, snapshot['key']))))
    connection.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {} ({})').format(target, sql.SQL(',').join(definitions)))
    existing = connection.execute('''SELECT attname, format_type(atttypid, atttypmod)
        FROM pg_attribute WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped
        ORDER BY attnum''', [f"reporting.{snapshot['name']}"]).fetchall()
    normalize_type = lambda value: value.upper().replace(' ', '')
    if [(name, normalize_type(kind)) for name, kind in existing] != [
            (name, normalize_type(kind)) for name, kind in snapshot['columns']]:
        raise ValueError(f"Reporting schema changed for {snapshot['name']}; review migration first.")
    connection.execute(sql.SQL('TRUNCATE TABLE {}').format(target))
    with connection.cursor().copy(sql.SQL('COPY {} ({}) FROM STDIN').format(target, sql.SQL(',').join(map(sql.Identifier, names)))) as copy:
        for row in snapshot['rows']:
            copy.write_row(row)
    ordering = sql.SQL(',').join(map(sql.Identifier, snapshot['key']))
    exported = connection.execute(sql.SQL('SELECT * FROM {} ORDER BY {}').format(target, ordering)).fetchall()
    indices = [names.index(key) for key in snapshot['key']]
    expected = sorted(snapshot['rows'], key=lambda row: tuple(row[index] for index in indices))
    if exported != expected:
        raise ValueError(f"PostgreSQL round-trip mismatch: {snapshot['name']}.")
    return {'table': snapshot['name'], 'rows': len(exported), 'source_digest': row_digest(snapshot),
            'round_trip_equal': True}


def publish_snapshots(snapshots, parameters):
    with psycopg.connect(**parameters) as connection:
        database, role = connection.execute('SELECT CURRENT_DATABASE(), CURRENT_USER').fetchone()
        if (database, role) != ('analytics', 'analytics_loader'):
            raise ValueError('Publish only as analytics_loader into analytics.')
        connection.execute("SET TIME ZONE 'UTC'")
        connection.execute("SET LOCAL lock_timeout = '10s'")
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('online_store_reporting_export'))")
        results = [load_table(connection, snapshot) for snapshot in snapshots]
    return results


def export_reporting(database=ROOT/'data/processed/shop.duckdb', reports_dir=ROOT/'data/reports',
                     config=ROOT/'config/reporting.toml', env_path=ROOT/'.env'):
    database = database.resolve()
    if not database.is_file() or database.suffix != '.duckdb' or database.is_relative_to(ROOT/'data/raw'):
        raise ValueError('Use a built DuckDB outside data/raw/.')
    snapshots, fingerprints = prepare_snapshots(database, reports_dir, config)
    results = publish_snapshots(snapshots, connection_parameters(read_env(env_path)))
    return {'completed_at_utc': datetime.now(timezone.utc).isoformat(),
            'target_database': 'analytics', 'target_schema': 'reporting',
            'verified_source_fingerprints': fingerprints, 'tables': results,
            'total_rows': sum(row['rows'] for row in results),
            'runtime': {'duckdb': duckdb.__version__, 'psycopg': psycopg.__version__}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT/'data/processed/shop.duckdb')
    parser.add_argument('--reports-dir', type=Path, default=ROOT/'data/reports')
    parser.add_argument('--config', type=Path, default=ROOT/'config/reporting.toml')
    parser.add_argument('--env-file', type=Path, default=ROOT/'.env')
    parser.add_argument('--report', type=Path, default=ROOT/'data/reports/postgres_export.json')
    args = parser.parse_args()
    if args.report.suffix != '.json' or args.report.resolve().is_relative_to(ROOT/'data/raw'):
        parser.error('Write a JSON report outside data/raw/.')
    try:
        report = export_reporting(args.database, args.reports_dir, args.config, args.env_file)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, duckdb.Error, psycopg.Error) as error:
        message = error.diag.message_primary if isinstance(error, psycopg.Error) and error.diag.message_primary else str(error)
        print(f'Reporting export failed: {message}', file=sys.stderr)
        return 1
    print(f"Published {len(report['tables'])} tables / {report['total_rows']} rows; report: {args.report}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
