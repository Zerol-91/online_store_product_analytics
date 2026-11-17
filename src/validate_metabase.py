"""Compare saved Metabase questions and dashboard filters with PostgreSQL."""

import json
import math
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal

import psycopg

from local_config import ROOT, connection_parameters, read_env
from metabase_client import MetabaseError, authenticated_client
from setup_metabase import REPORT, entity_id, load_manifest


def render_sql(query, values):
    query = query.replace('%', '%%')
    def optional(match):
        tags = re.findall(r'\{\{(\w+)\}\}', match[1])
        return match[1] if all(values.get(tag) is not None for tag in tags) else ''
    query = re.sub(r'\[\[(.*?)\]\]', optional, query, flags=re.S)
    parameters = []
    def variable(match):
        value = values.get(match[1])
        if value is None:
            raise ValueError('Missing required SQL template value.')
        parameters.append(value)
        return '%s'
    return re.sub(r'\{\{(\w+)\}\}', variable, query), parameters


def equal_rows(expected, observed):
    if len(expected) != len(observed):
        return False
    for first, second in zip(expected, observed):
        if len(first) != len(second):
            return False
        for left, right in zip(first, second):
            if isinstance(left, (int, float, Decimal)) and not isinstance(left, bool):
                if not isinstance(right, (int, float)) or not math.isclose(float(left), float(right),
                                                                         rel_tol=1e-10, abs_tol=1e-10):
                    return False
            elif left != right:
                return False
    return True


def card_parameters(values):
    return [{'id': entity_id(tag), 'type': 'category', 'target': ['variable', ['template-tag', tag]], 'value': value}
            for tag, value in values.items() if value is not None]


def validate(client, manifest, report, values):
    dashboard = client.request('GET', f"/api/dashboard/{report['dashboard_id']}")
    results = []
    with psycopg.connect(**connection_parameters(values, 'analytics_reader')) as connection:
        for card in manifest['cards']:
            card_id = report['cards'][card['key']]
            layouts = [item for item in dashboard['dashcards'] if item.get('card_id') == card_id]
            if len(layouts) != 1:
                raise ValueError('Expected exactly one dashboard instance of each card.')
            layout = layouts[0]
            expected_mappings = [{'parameter_id': parameter, 'card_id': card_id,
                'target': ['variable', ['template-tag', tag]]} for tag, parameter in card.get('filters', {}).items()]
            if layout.get('parameter_mappings', []) != expected_mappings:
                raise ValueError('Dashboard parameter mappings differ from the declared population filters.')
            cases = [{'timestamp_rule': 'allow_equal'}] if 'timestamp_rule' in card.get('filters', {}) else [{}]
            if 'timestamp_rule' in card.get('filters', {}):
                cases.append({'timestamp_rule': 'strict'})
            if 'first_purchase_month' in card.get('filters', {}):
                cases.extend({'first_purchase_month': month} for month in ('2019-11', '2019-12', '2020-01', '2020-02'))
            query = (ROOT/'metabase/sql'/f"{card['key']}.sql").read_text(encoding='utf-8')
            for case in cases:
                rendered, bindings = render_sql(query, case)
                cursor = connection.execute(rendered, bindings)
                expected = cursor.fetchall()
                names = [column.name for column in cursor.description]
                result = client.request('POST', f'/api/card/{card_id}/query',
                                        {'parameters': card_parameters(case), 'ignore_cache': True})
                if result.get('status') != 'completed' or not equal_rows(expected, result['data']['rows']):
                    raise ValueError('Metabase/PostgreSQL result mismatch: ' + card['key'])
                if [column['name'] for column in result['data']['cols']] != names:
                    raise ValueError('Metabase result column mismatch: ' + card['key'])
                dashboard_parameters = [{'id': parameter, 'type': 'string/=', 'value': [case[tag]]}
                    for tag, parameter in card.get('filters', {}).items() if case.get(tag) is not None]
                endpoint = (f"/api/dashboard/{report['dashboard_id']}/dashcard/{layout['id']}"
                            f'/card/{card_id}/query')
                shown = client.request('POST', endpoint, {'parameters': dashboard_parameters, 'ignore_cache': True})
                if shown.get('status') != 'completed' or not equal_rows(expected, shown['data']['rows']):
                    raise ValueError('Dashboard filter result mismatch: ' + card['key'])
                results.append({'card': card['key'], 'filters': case, 'rows': len(expected),
                                'question_matches': True, 'dashboard_matches': True})
    return {'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'cases': results,
            'all_checks_passed': True}


def main():
    try:
        report = json.loads(REPORT.read_text(encoding='utf-8'))
        result = validate(authenticated_client(), load_manifest(), report, read_env())
        destination = ROOT/'data/reports/metabase_validation.json'
        destination.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, MetabaseError, psycopg.Error) as error:
        message = error.diag.message_primary if isinstance(error, psycopg.Error) and error.diag.message_primary else str(error)
        print(f'Metabase validation failed: {message}', file=sys.stderr)
        return 1
    print(f"Verified {len(result['cases'])} question and dashboard cases against PostgreSQL.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
