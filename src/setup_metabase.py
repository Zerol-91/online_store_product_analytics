"""Create or update the local reporting dashboard from versioned declarations."""

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from export_to_postgres import prepare_snapshots
from local_config import ROOT, connection_parameters, read_env
from metabase_client import Client, MetabaseError, authenticated_client

MANIFEST = ROOT / 'metabase/dashboard.json'
REPORT = ROOT / 'data/reports/metabase_dashboard.json'
COLLECTION_DESCRIPTION = 'Reproducible reporting for the cosmetics-store portfolio.'


def entity_id(key):
    digest = hashlib.sha256(('cosmetics-store-analytics:' + key).encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()[:21]


def load_manifest(path=MANIFEST):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    keys = [card['key'] for card in manifest['cards']]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate card keys.')
    parameter_ids = {item['id'] for item in manifest['parameters']}
    rectangles = []
    for card in manifest['cards']:
        if not re.fullmatch(r'[a-z][a-z0-9_]*', card['key']):
            raise ValueError('Invalid SQL card key.')
        query = (ROOT / 'metabase/sql' / (card['key'] + '.sql')).read_text(encoding='utf-8')
        tags = set(re.findall(r'\{\{(\w+)\}\}', query))
        if tags != set(card.get('filters', {})) or not set(card.get('filters', {}).values()) <= parameter_ids:
            raise ValueError('SQL template tags and dashboard mappings must match.')
        if not query.startswith('--') or not re.search(r'\bSELECT\b', query):
            raise ValueError('Document and select from a reporting mart.')
        rectangles.append((card['row'], card['col'], card['width'], card['height']))
    for item in manifest['text']:
        rectangles.append((item['row'], item.get('col', 0), item.get('width', 24), item['height']))
    for i, (row, col, width, height) in enumerate(rectangles):
        if min(row, col) < 0 or min(width, height) < 1 or col + width > 24:
            raise ValueError('Invalid dashboard geometry.')
        for other_row, other_col, other_width, other_height in rectangles[:i]:
            if (row < other_row + other_height and other_row < row + height
                    and col < other_col + other_width and other_col < col + width):
                raise ValueError('Overlapping dashboard cards.')
    return manifest


def template_tags(card):
    return {name: {'id': entity_id(name), 'name': name, 'display-name': name.replace('_', ' ').title(),
                   'type': 'text', **({'default': 'allow_equal', 'required': True}
                                      if name == 'timestamp_rule' else {})}
            for name in card.get('filters', {})}


def column_settings(card):
    titles = {'first_purchase_month': 'First-purchase month', 'cohort_users': 'Cohort users',
        'm1': 'M1 repeat rate', 'm2': 'M2 repeat rate', 'ci_low': '95% CI lower', 'ci_high': '95% CI upper',
        'cart_episodes': 'Cart episodes', 'converted_episodes': 'Converted episodes', 'users': 'Users',
        'conversion': 'Conversion', 'highlighted_conversion': 'High price', 'unknown_conversion': 'Unknown price',
        'repeat_rate': 'Repeat rate', 'difference_pp': 'Difference (pp)',
        'ci_low_pp': '97.5% CI lower (pp)', 'ci_high_pp': '97.5% CI upper (pp)',
        'adjusted_p_value': 'Adjusted p', 'assumed_uplift_pp': 'Assumed uplift (pp)',
        'users_per_arm': 'Users per arm', 'replay_total_days': 'Replay total days',
        'eligible_users': 'Scenario users', 'additional_converted_users': 'Additional converted users',
        'conditional_value': 'Conditional value (source units)', 'follow_up': 'Follow-up'}
    columns = {name: {'column_title': title} for name, title in titles.items()}
    for name in card.get('percent', []):
        columns.setdefault(name, {}).update({'number_style': 'percent', 'decimals': 2})
    return {json.dumps(['name', name], separators=(',', ':')): settings for name, settings in columns.items()}


def visualization(card):
    settings = {'column_settings': column_settings(card), 'portfolio.card_key': card['key']}
    if card['display'] == 'scalar':
        settings.update({'scalar.decimals': 2, 'scalar.separator_style': ',.'})
    elif card['display'] in ('bar', 'line'):
        dimensions = [card['dimension']] + ([card['breakout']] if card.get('breakout') else [])
        settings.update({'graph.dimensions': dimensions, 'graph.metrics': [card['metric']],
            'graph.colors': ['#334E68', '#829AB1', '#B45309', '#52606D'],
            'graph.y_axis.auto_range': True, 'graph.y_axis.min': 0,
            'graph.y_axis.title_text': 'Conversion' if card['metric'] == 'conversion' else
                'Cumulative repeat rate' if card['display'] == 'line' else 'Episodes',
            'graph.x_axis.title_text': 'Days since first observed purchase' if card['display'] == 'line' else '',
            'graph.show_values': card['display'] == 'bar', 'graph.show_goal': False})
        if card.get('horizontal'):
            settings['series_settings'] = {card['metric']: {'color': '#486581'}}
            settings['graph.x_axis.scale'] = 'ordinal'
            settings['graph.y_axis.scale'] = 'linear'
            settings['graph.x_axis.axis_enabled'] = True
            settings['graph.y_axis.axis_enabled'] = True
            if card.get('axis_max') is not None:
                settings.update({'graph.y_axis.auto_range': False, 'graph.y_axis.max': card['axis_max']})
            if card['key'] == 'price_segments':
                settings.update({'graph.metrics': ['conversion', 'highlighted_conversion', 'unknown_conversion'],
                    'stackable.stack_type': 'stacked', 'graph.show_stack_values': 'total', 'graph.show_legend': False,
                    'series_settings': {'conversion': {'color': '#486581', 'title': 'Low / Middle'},
                        'highlighted_conversion': {'color': '#B45309', 'title': 'High'},
                        'unknown_conversion': {'color': '#9AA5B1', 'title': 'Unknown'}}})
                for name in ('highlighted_conversion', 'unknown_conversion'):
                    settings['column_settings'][json.dumps(['name', name], separators=(',', ':'))].update(
                        {'number_style': 'percent', 'decimals': 2})
        if card['display'] == 'line':
            settings.update({'graph.y_axis.max': 0.25, 'graph.show_values': False,
                             'graph.y_axis.auto_range': False,
                             'graph.x_axis.scale': 'linear', 'line.interpolate': 'linear'})
    elif card['display'] == 'table':
        settings['table.cell_column'] = None
        settings['table.column_widths'] = []
        if card['key'] == 'calendar_cohorts':
            settings['table.column_formatting'] = [{'columns': ['m1', 'm2'], 'type': 'range',
                'colors': ['#F0F4F8', '#486581'], 'min_type': 'custom', 'max_type': 'custom',
                'min_value': 0, 'max_value': 0.12}]
    return settings


def card_payload(card, database_id, collection_id):
    query = (ROOT / 'metabase/sql' / (card['key'] + '.sql')).read_text(encoding='utf-8')
    return {'name': card['name'], 'description': card['description'],
        'collection_id': collection_id, 'display': 'row' if card.get('horizontal') else card['display'],
        'visualization_settings': visualization(card),
        'dataset_query': {'database': database_id, 'type': 'native',
                          'native': {'query': query, 'template-tags': template_tags(card)}}}


def unique_match(items, predicate, label):
    matches = [item for item in items if predicate(item)]
    if len(matches) > 1:
        raise ValueError(f'Ambiguous {label}; resolve duplicate objects before provisioning.')
    return matches[0] if matches else None


def native_sql(query):
    if isinstance(query.get('native'), dict):
        return query['native'].get('query')
    stages = query.get('stages', [])
    return stages[0].get('native') if len(stages) == 1 else None


def ensure_database(client, manifest, values):
    databases = client.request('GET', '/api/database')['data']
    existing = unique_match(databases, lambda row: row['name'] == manifest['database'], 'reporting database')
    details = {'host': 'postgres', 'port': 5432, 'dbname': 'analytics', 'user': 'analytics_reader',
        'password': values['ANALYTICS_READER_PASSWORD'], 'ssl': False,
        'schema-filters-type': 'inclusion', 'schema-filters-patterns': 'reporting',
        'advanced-options': True, 'use-conn-pool': True}
    payload = {'name': manifest['database'], 'engine': 'postgres', 'details': details, 'is_full_sync': False}
    if existing:
        current = client.request('GET', f"/api/database/{existing['id']}")
        if current['engine'] != 'postgres' or any(current['details'].get(key) != details[key]
                for key in ('host', 'dbname', 'user')):
            raise ValueError('Existing reporting connection points elsewhere; review it before updating.')
        return client.request('PUT', f"/api/database/{existing['id']}", payload)['id']
    return client.request('POST', '/api/database', payload)['id']


def ensure_collection(client, manifest):
    existing = unique_match(client.request('GET', '/api/collection'),
        lambda row: row['name'] == manifest['collection'], 'project collection')
    if existing:
        if existing.get('description') != COLLECTION_DESCRIPTION:
            raise ValueError('Collection name is already in use by unrelated content.')
        return existing['id']
    return client.request('POST', '/api/collection',
        {'name': manifest['collection'], 'description': COLLECTION_DESCRIPTION})['id']


def ensure_cards(client, manifest, database_id, collection_id):
    existing_cards = client.request('GET', '/api/card')
    ids = {}
    for card in manifest['cards']:
        existing = unique_match(existing_cards, lambda item:
            item.get('visualization_settings', {}).get('portfolio.card_key') == card['key']
            and item.get('collection_id') == collection_id,
                                'card ' + card['key'])
        payload = card_payload(card, database_id, collection_id)
        if not existing:
            # Adopt only an exact initial question in this owned collection.
            existing = unique_match(existing_cards, lambda item: item['name'] == card['name']
                and item.get('collection_id') == collection_id
                and item.get('description') == card['description']
                and item.get('dataset_query', {}).get('database') == database_id
                and native_sql(item.get('dataset_query', {})) ==
                    payload['dataset_query']['native']['query'], 'initial project card')
        if existing:
            if existing.get('collection_id') != collection_id:
                raise ValueError('Managed card was moved outside its collection; review before updating.')
            result = client.request('PUT', f"/api/card/{existing['id']}", payload)
        else:
            if any(item['name'] == card['name'] and item.get('collection_id') == collection_id for item in existing_cards):
                raise ValueError('An unrelated card has the same project name.')
            result = client.request('POST', '/api/card', payload)
        ids[card['key']] = result['id']
    return ids


def ensure_dashboard(client, manifest, collection_id, ids):
    dashboards = client.request('GET', '/api/dashboard')
    if isinstance(dashboards, dict):
        dashboards = dashboards['data']
    existing = unique_match(dashboards, lambda item: item['name'] == manifest['name']
                            and item.get('collection_id') == collection_id, 'project dashboard')
    payload = {key: manifest[key] for key in ('name', 'description', 'parameters')}
    payload['collection_id'] = collection_id
    dashboard_id = existing['id'] if existing else client.request('POST', '/api/dashboard', payload)['id']
    current = client.request('GET', f'/api/dashboard/{dashboard_id}')
    existing_layout = current.get('dashcards', [])
    text_keys = {item['key'] for item in manifest['text']}
    if any((item.get('card_id') not in ids.values() if item.get('card_id') else
            item.get('visualization_settings', {}).get('portfolio.text_key') not in text_keys)
           for item in existing_layout):
        raise ValueError('Dashboard contains extra cards; preserving them requires a layout review.')
    layout = []
    for index, card in enumerate(manifest['cards']):
        found = unique_match(existing_layout, lambda item: item.get('card_id') == ids[card['key']], 'dashboard card')
        mappings = [{'parameter_id': parameter, 'card_id': ids[card['key']],
                     'target': ['variable', ['template-tag', tag]]}
                    for tag, parameter in card.get('filters', {}).items()]
        layout.append({'id': found['id'] if found else -index - 1, 'card_id': ids[card['key']],
            'row': card['row'], 'col': card['col'], 'size_x': card['width'], 'size_y': card['height'],
            'parameter_mappings': mappings, 'visualization_settings': {}})
    for index, item in enumerate(manifest['text'], len(layout)):
        found = unique_match(existing_layout, lambda row:
            row.get('visualization_settings', {}).get('portfolio.text_key') == item['key'], 'dashboard text')
        layout.append({'id': found['id'] if found else -index - 1, 'card_id': None,
            'row': item['row'], 'col': item.get('col', 0), 'size_x': item.get('width', 24), 'size_y': item['height'],
            'parameter_mappings': [], 'visualization_settings': {'virtual_card': {'display': 'text',
                'dataset_query': {}, 'visualization_settings': {}}, 'text': item['text'],
                'portfolio.text_key': item['key']}})
    client.request('PUT', f'/api/dashboard/{dashboard_id}', payload | {'width': 'full'})
    client.request('PUT', f'/api/dashboard/{dashboard_id}/cards', {'cards': layout})
    saved = client.request('GET', f'/api/dashboard/{dashboard_id}')
    if len(saved['dashcards']) != len(layout) or saved['parameters'] != manifest['parameters']:
        raise ValueError('Dashboard layout or parameter round-trip mismatch.')
    return dashboard_id


def verify_reporting(values):
    snapshots, _ = prepare_snapshots(ROOT/'data/processed/shop.duckdb', ROOT/'data/reports',
                                      ROOT/'config/reporting.toml')
    with psycopg.connect(**connection_parameters(values, 'analytics_reader')) as connection:
        for snapshot in snapshots:
            rows = connection.execute('SELECT * FROM reporting.' + snapshot['name']).fetchall()
            names = [name for name, _ in snapshot['columns']]
            indices = [names.index(name) for name in snapshot['key']]
            key = lambda row: tuple(row[index] for index in indices)
            if sorted(rows, key=key) != sorted(snapshot['rows'], key=key):
                raise ValueError('PostgreSQL snapshot is stale; run export_to_postgres.py first.')
    return len(snapshots)


def provision(client, manifest, values):
    properties = client.request('GET', '/api/session/properties')
    if properties['version']['tag'] != manifest['version']:
        raise ValueError('Metabase version differs from the verified dashboard API version.')
    client.require_admin()
    # Serialize HTTP upserts across concurrent local provisioning processes.
    with psycopg.connect(**connection_parameters(values, 'analytics_reader'), autocommit=True) as lock:
        if not lock.execute("SELECT pg_try_advisory_lock(hashtext('cosmetics_metabase_provision'))").fetchone()[0]:
            raise ValueError('Another dashboard provisioning process is running.')
        database_id = ensure_database(client, manifest, values)
        collection_id = ensure_collection(client, manifest)
        ids = ensure_cards(client, manifest, database_id, collection_id)
        dashboard_id = ensure_dashboard(client, manifest, collection_id, ids)
    return {'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'metabase_version': manifest['version'],
            'database_id': database_id, 'collection_id': collection_id, 'dashboard_id': dashboard_id,
            'dashboard_url': f'{client.base_url}/dashboard/{dashboard_id}', 'cards': ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args()
    try:
        manifest, values = load_manifest(args.manifest), read_env()
        client = authenticated_client()
        verified = verify_reporting(values)
        report = provision(client, manifest, values)
        report['verified_reporting_tables'] = verified
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, MetabaseError, psycopg.Error) as error:
        message = error.diag.message_primary if isinstance(error, psycopg.Error) and error.diag.message_primary else str(error)
        print(f'Metabase provisioning failed: {message}', file=sys.stderr)
        return 1
    print('Dashboard ready: ' + report['dashboard_url'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
