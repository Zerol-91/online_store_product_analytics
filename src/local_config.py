"""Read the project's flat local environment file without exposing credentials."""

import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {'POSTGRES_PORT': '5433', 'METABASE_PORT': '3000', 'ANALYTICS_HOST': '127.0.0.1'}
SECRET_KEYS = ('POSTGRES_ADMIN_PASSWORD', 'ANALYTICS_LOADER_PASSWORD',
               'ANALYTICS_READER_PASSWORD', 'METABASE_DB_PASSWORD', 'METABASE_ENCRYPTION_SECRET_KEY')


def read_env(path=ROOT / '.env'):
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in values:
            raise ValueError('Use one KEY=value per line and unique environment keys.')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[key] = value
    for key in DEFAULTS:
        values.setdefault(key, DEFAULTS[key])
    for key in SECRET_KEYS:
        if len(values.get(key, '')) < 20 or 'CHANGE_ME' in values[key].upper():
            raise ValueError(f'Generate a local {key}; do not use the empty example file.')
    for key in ('POSTGRES_PORT', 'METABASE_PORT'):
        if not values[key].isdigit() or not 1 <= int(values[key]) <= 65535:
            raise ValueError(f'{key} must be a valid TCP port.')
    return values


def initialize_env(path=ROOT / '.env'):
    if path.exists():
        read_env(path)
        return False
    values = DEFAULTS | {key: secrets.token_urlsafe(32) for key in SECRET_KEYS}
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    return True


def connection_parameters(values, role='analytics_loader', database='analytics'):
    password_key = {'analytics_loader': 'ANALYTICS_LOADER_PASSWORD',
                    'analytics_reader': 'ANALYTICS_READER_PASSWORD',
                    'postgres': 'POSTGRES_ADMIN_PASSWORD', 'metabase_app': 'METABASE_DB_PASSWORD'}[role]
    return {'host': values['ANALYTICS_HOST'], 'port': int(values['POSTGRES_PORT']),
            'dbname': database, 'user': role, 'password': values[password_key], 'connect_timeout': 10}
