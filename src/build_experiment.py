"""Build the historical user-level seven-day post-cart baseline."""

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import duckdb

from build_funnel import read_settings
from build_staging import ROOT, SQL_ROOT, query_rows
from segment_statistics import cluster_rate
from experiment_design import plan_experiment, proportion_power

BASELINE_TABLES = ('cart_experiment_users', 'cart_experiment_summary', 'cart_experiment_daily')
TABLES = BASELINE_TABLES + ('experiment_scenarios',)


def read_experiment_settings(config):
    settings = read_settings(config)
    document = tomllib.loads(config.read_text(encoding='utf-8'))
    settings.update(document['experiment'])
    if settings['population'] != 'all_period_cart_users':
        raise ValueError('Use the selected all-period-cart-user population.')
    settings['entry_start_utc'] = datetime.fromisoformat(document['analysis']['start_utc'])
    if settings['entry_start_utc'].tzinfo is not None or not settings['observation_start_utc'] <= settings['entry_start_utc'] < settings['observation_end_exclusive_utc']:
        raise ValueError('Use a UTC entry period inside observation.')
    if type(settings['horizon_days']) is not int or settings['horizon_days'] <= 0:
        raise ValueError('Use a positive integer outcome horizon.')
    if not 0 < settings['alpha'] < 1 or not 0 < settings['power'] < 1 or settings['treatment_share'] != 0.5:
        raise ValueError('Use valid alpha/power and the selected 50/50 allocation.')
    uplifts = settings['scenario_uplifts_absolute']
    if (not uplifts or uplifts != sorted(set(uplifts)) or uplifts[0] != 0
            or any(not isinstance(x, (int, float)) or not 0 <= x < 1 for x in uplifts)
            or settings['primary_mde_absolute'] <= 0 or settings['primary_mde_absolute'] not in uplifts):
        raise ValueError('Use distinct increasing scenario uplifts, a zero reference, and a positive primary MDE.')
    for key in ('study_budget_days', 'minimum_enrollment_days', 'scenario_population'):
        if type(settings[key]) is not int or settings[key] <= 0:
            raise ValueError(f'{key} must be a positive integer.')
    if (settings['minimum_enrollment_days'] < 7 or settings['minimum_enrollment_days'] % 7
            or settings['study_budget_days'] < settings['minimum_enrollment_days'] + settings['horizon_days']):
        raise ValueError('Use complete enrollment weeks within the study budget.')
    if settings['value_assumption'] != 'constant_value_per_converted_user':
        raise ValueError('Use the selected conditional-value scenario assumption.')
    return settings


def prepare_parameters(c, settings):
    c.execute('''CREATE TEMP TABLE experiment_parameters AS SELECT
        ?::TIMESTAMP AS entry_start_utc, ?::TIMESTAMP AS observation_end_exclusive_utc,
        ?::INTEGER AS horizon_days''', [settings['entry_start_utc'], settings['observation_end_exclusive_utc'], settings['horizon_days']])


def validate_baseline(c):
    coverage = query_rows(c, '''SELECT COUNT(*) AS period_cart_users,
        COUNT(*) FILTER(WHERE has_complete_window) AS mature_users,
        COUNT(*) FILTER(WHERE NOT has_complete_window) AS incomplete_users,
        COUNT(*) FILTER(WHERE has_complete_window AND had_cart_before_period) AS mature_users_with_preperiod_cart
        FROM cart_experiment_users''')[0]
    checks = {
        'user_key_unique': c.execute('SELECT COUNT(*)=COUNT(DISTINCT user_id) FROM cart_experiment_users').fetchone()[0],
        'summary_key_unique': c.execute('SELECT COUNT(*)=2 AND COUNT(DISTINCT timestamp_rule)=2 FROM cart_experiment_summary').fetchone()[0],
        'daily_key_unique': c.execute('SELECT COUNT(*)=COUNT(DISTINCT entry_date_utc) FROM cart_experiment_daily').fetchone()[0],
        'required_user_fields': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_users
            WHERE user_id IS NULL OR first_observed_cart_utc IS NULL OR entry_utc IS NULL OR deadline_utc IS NULL
                OR has_complete_window IS NULL OR had_cart_before_period IS NULL''').fetchone()[0],
        'population_matches_source': c.execute('''SELECT (SELECT COUNT(DISTINCT user_id) FROM stg_events CROSS JOIN experiment_parameters p
            WHERE event_type='cart' AND NOT is_invalid_user_id AND NOT is_invalid_event_time
                AND event_time_utc>=p.entry_start_utc AND event_time_utc<p.observation_end_exclusive_utc)
            = (SELECT COUNT(*) FROM cart_experiment_users)''').fetchone()[0],
        'entry_is_first_eligible_cart': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_users u
            WHERE NOT EXISTS(SELECT 1 FROM stg_events e WHERE e.user_id=u.user_id AND e.event_type='cart'
                AND NOT e.is_invalid_user_id AND NOT e.is_invalid_event_time AND e.event_time_utc=u.entry_utc)
            OR EXISTS(SELECT 1 FROM stg_events e CROSS JOIN experiment_parameters p
                WHERE e.user_id=u.user_id AND e.event_type='cart' AND NOT e.is_invalid_user_id AND NOT e.is_invalid_event_time
                    AND e.event_time_utc>=p.entry_start_utc AND e.event_time_utc<u.entry_utc)''').fetchone()[0],
        'maturity_consistent': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_users CROSS JOIN experiment_parameters p
            WHERE has_complete_window<>(deadline_utc<p.observation_end_exclusive_utc)
                OR entry_utc<p.entry_start_utc OR entry_utc>=p.observation_end_exclusive_utc''').fetchone()[0],
        'immature_outcomes_null': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_users WHERE NOT has_complete_window
            AND (converted IS NOT NULL OR strict_converted IS NOT NULL OR positive_purchase_value IS NOT NULL OR strict_positive_purchase_value IS NOT NULL)''').fetchone()[0],
        'mature_outcomes_present': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_users WHERE has_complete_window
            AND (converted IS NULL OR strict_converted IS NULL OR positive_purchase_value IS NULL OR strict_positive_purchase_value IS NULL
                OR positive_purchase_value<0 OR strict_positive_purchase_value<0 OR strict_positive_purchase_value>positive_purchase_value
                OR (strict_converted AND NOT converted))''').fetchone()[0],
        'outcome_timestamp_bounds': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_users
            WHERE purchase_utc<entry_utc OR purchase_utc>deadline_utc OR strict_purchase_utc<=entry_utc OR strict_purchase_utc>deadline_utc''').fetchone()[0],
        'daily_counts_reconcile': c.execute('''SELECT COALESCE(SUM(enrolled_users),0)=(SELECT COUNT(*) FROM cart_experiment_users)
            AND COALESCE(SUM(mature_users),0)=(SELECT COUNT(*) FROM cart_experiment_users WHERE has_complete_window)
            FROM cart_experiment_daily''').fetchone()[0],
        'summary_counts_reconcile': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_summary
            WHERE eligible_users<>(SELECT COUNT(*) FROM cart_experiment_users WHERE has_complete_window)
                OR converted_users>eligible_users OR (eligible_users=0 AND conversion_rate IS NOT NULL)''').fetchone()[0],
        'summary_values_reconcile': c.execute('''SELECT COUNT(*)=0 FROM cart_experiment_summary s
            WHERE s.positive_purchase_value IS DISTINCT FROM
                (SELECT SUM(CASE WHEN s.timestamp_rule='allow_equal' THEN u.positive_purchase_value ELSE u.strict_positive_purchase_value END)
                 FROM cart_experiment_users u WHERE u.has_complete_window)''').fetchone()[0],
    }
    failures = [key for key, passed in checks.items() if not passed]
    if failures:
        raise ValueError('Experiment baseline validation failed: '+', '.join(failures))
    return {'coverage': coverage, 'checks': checks}


def store_design(c, design):
    c.execute('''CREATE TEMP TABLE experiment_planning_input (
        absolute_uplift DOUBLE, scenario_conversion DOUBLE, is_primary BOOLEAN,
        n_per_group BIGINT, total_users BIGINT, achieved_power DOUBLE,
        historical_enrollment_days INTEGER, historical_followup_days INTEGER,
        historical_total_days INTEGER, historical_readout_date DATE, replay_status VARCHAR,
        within_study_budget BOOLEAN, scenario_population BIGINT,
        additional_converted_users DOUBLE, assumed_value_per_converted_user DOUBLE,
        scenario_value_per_user DOUBLE, additional_positive_purchase_value DOUBLE)''')
    rows = []
    for row in design['scenarios']:
        replay = row['replay']
        rows.append([row['absolute_uplift'], row['scenario_conversion'], row['is_primary'],
            row['n_per_group'], row['total_users'], row['achieved_power'], replay['enrollment_days'],
            replay.get('followup_days'), replay['total_days'], replay.get('readout_date'), replay['status'],
            row['within_study_budget'], row['population'], row['additional_converted_users'],
            row['assumed_value_per_converted_user'], row['scenario_value_per_user'],
            row['additional_positive_purchase_value']])
    if rows:
        c.executemany('INSERT INTO experiment_planning_input VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    c.execute((SQL_ROOT/'03_reporting/experiment_scenarios.sql').read_text(encoding='utf-8'))


def validate_design(c, design, settings):
    count = len(design['scenarios'])
    checks = {
        'scenario_row_count': c.execute('SELECT COUNT(*) FROM experiment_scenarios').fetchone()[0] == count,
        'scenario_key_unique': c.execute('SELECT COUNT(*)=COUNT(DISTINCT absolute_uplift) FROM experiment_scenarios').fetchone()[0],
        'scenario_required_fields': c.execute('''SELECT COUNT(*)=0 FROM experiment_scenarios
            WHERE absolute_uplift IS NULL OR scenario_conversion IS NULL OR is_primary IS NULL
                OR scenario_population IS NULL OR additional_positive_purchase_value IS NULL OR replay_status IS NULL''').fetchone()[0],
    }
    if design['status'] == 'planned':
        checks.update({
            'one_primary_scenario': c.execute('SELECT COUNT(*)=1 FROM experiment_scenarios WHERE is_primary').fetchone()[0],
            'scenario_grid_complete': count == len(settings['scenario_uplifts_absolute']),
            'zero_uplift_reference': c.execute('''SELECT COUNT(*)=1 FROM experiment_scenarios WHERE absolute_uplift=0
                AND additional_converted_users=0 AND additional_positive_purchase_value=0 AND n_per_group IS NULL''').fetchone()[0],
            'sample_allocation_and_power': all(row['total_users'] == 2*row['n_per_group']
                and row['achieved_power'] >= settings['power']
                and proportion_power(design['baseline_conversion'], row['absolute_uplift'], row['n_per_group']-1, settings['alpha']) < settings['power']
                for row in design['scenarios'] if row['absolute_uplift'] > 0),
            'scenario_value_identity': all(abs(row['scenario_value_per_user']
                - row['scenario_conversion']*row['assumed_value_per_converted_user']) < 1e-10 for row in design['scenarios']),
            'replay_outcome_window': all(row['replay']['total_days']
                == row['replay']['enrollment_days'] + settings['horizon_days']
                for row in design['scenarios'] if row['replay']['total_days'] is not None),
        })
    failures = [key for key, passed in checks.items() if not passed]
    if failures:
        raise ValueError('Experiment planning validation failed: '+', '.join(failures))
    return checks


def build_experiment(database, config=ROOT / 'config/analysis.toml'):
    database = database.resolve()
    if not database.is_file() or database.suffix != '.duckdb' or database.is_relative_to(ROOT / 'data/raw'):
        raise ValueError('Build staging first; use a .duckdb outside data/raw/.')
    settings = read_experiment_settings(config)
    temporary = database.parent / (database.stem+'_tmp')
    temporary.mkdir(exist_ok=True)
    with duckdb.connect(str(database), config={'memory_limit':'1GB', 'threads':'2',
            'temp_directory':str(temporary), 'preserve_insertion_order':'false'}) as c:
        source_fingerprint = str(c.execute('SELECT BIT_XOR(HASH(t)) FROM stg_events t').fetchone()[0])
        prepare_parameters(c, settings)
        c.execute('BEGIN TRANSACTION')
        try:
            print('Building user-level post-cart baseline...', flush=True)
            c.execute((SQL_ROOT/'02_marts/cart_experiment_users.sql').read_text(encoding='utf-8'))
            for name in BASELINE_TABLES[1:]:
                c.execute((SQL_ROOT/f'03_reporting/{name}.sql').read_text(encoding='utf-8'))
            result = validate_baseline(c)
            summary = query_rows(c, 'SELECT * FROM cart_experiment_summary ORDER BY timestamp_rule')
            daily = query_rows(c, 'SELECT * FROM cart_experiment_daily ORDER BY entry_date_utc')
            intervals = []
            for row in summary:
                n, y = row['eligible_users'], row['converted_users'] or 0
                estimate = cluster_rate([1]*y+[0]*(n-y), [1]*n, settings['alpha'])
                if estimate['estimate'] != row['conversion_rate']:
                    raise ValueError('Baseline interval does not reconcile with SQL.')
                intervals.append({'timestamp_rule':row['timestamp_rule'], **estimate})
            design = plan_experiment(summary, daily, settings)
            store_design(c, design)
            design_checks = validate_design(c, design, settings)
            fingerprints = {table:str(c.execute(f'SELECT BIT_XOR(HASH(t)) FROM {table} t').fetchone()[0]) for table in TABLES}
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise
    return {'completed_at_utc':datetime.now(timezone.utc).isoformat(), 'settings':settings,
            'runtime':{'python':sys.version.split()[0], 'duckdb':duckdb.__version__,
                       'numpy':version('numpy'), 'scipy':version('scipy')},
            'staging_fingerprint':source_fingerprint, 'fingerprints':fingerprints,
            'summary':summary, 'daily_enrollments':daily, 'rate_intervals':intervals,
            'design':design, 'design_checks':design_checks, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/processed/shop.duckdb')
    parser.add_argument('--config',type=Path,default=ROOT/'config/analysis.toml')
    parser.add_argument('--report',type=Path,default=ROOT/'data/reports/experiment_baseline.json')
    args = parser.parse_args()
    if args.report.suffix != '.json' or args.report.resolve().is_relative_to(ROOT/'data/raw'):
        parser.error('Write a JSON report outside data/raw/.')
    try:
        report = build_experiment(args.database,args.config)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,default=str)+'\n',encoding='utf-8')
    except (OSError,ValueError,KeyError,duckdb.Error) as error:
        print(f'Experiment baseline failed: {error}',file=sys.stderr)
        return 1
    print(f"Mature cart users: {report['coverage']['mature_users']:,}; report: {args.report}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
