"""Authenticate locally and call the project's Metabase API."""

import argparse
import getpass
import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from local_config import ROOT, read_env

SESSION_FILE = ROOT / 'metabase/local/session.json'


class MetabaseError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url, token=None):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('Use the local HTTP Metabase address without credentials or a path.')
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, payload=None, timeout=120):
        if not path.startswith('/api/'):
            raise ValueError('Use a Metabase API path.')
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['X-Metabase-Session'] = self.token
        request = urllib.request.Request(self.base_url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                content = response.read()
                return json.loads(content) if content else None
        except urllib.error.HTTPError as error:
            # API error bodies can echo connection credentials or SQL parameters.
            raise MetabaseError(f'{method} {path.split("?")[0]} returned HTTP {error.code}.') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            raise MetabaseError('Cannot reach local Metabase. Check services and retry.') from None

    def require_admin(self):
        user = self.request('GET', '/api/user/current')
        if not user.get('is_superuser'):
            raise MetabaseError('Dashboard provisioning requires a local administrator account.')


def local_url():
    return f"http://127.0.0.1:{read_env()['METABASE_PORT']}"


def authenticated_client(session_file=SESSION_FILE):
    url = local_url()
    if not session_file.is_file():
        raise MetabaseError('Run: uv run --locked python src/metabase_client.py login')
    session = json.loads(session_file.read_text(encoding='utf-8'))
    if session['base_url'] != url:
        raise MetabaseError('Service address changed; log in again.')
    client = Client(url, session['id'])
    client.require_admin()
    return client


def save_session(client):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump({'base_url': client.base_url, 'id': client.token}, handle)
    print('Local administrator session saved. Password was not saved.')


def login():
    client = Client(local_url())
    email = input('Metabase email: ').strip()
    password = getpass.getpass('Metabase password (hidden): ')
    session = client.request('POST', '/api/session', {'username': email, 'password': password})
    client.token = session['id']
    client.require_admin()
    save_session(client)


def initialize():
    client = Client(local_url())
    properties = client.request('GET', '/api/session/properties')
    token = properties.get('setup-token')
    if not token:
        raise MetabaseError('An account already exists. Use login; initialization never resets accounts.')
    email = input('New administrator email: ').strip()
    first_name = input('First name: ').strip()
    password = getpass.getpass('New password (hidden): ')
    session = client.request('POST', '/api/setup', {'token': token,
        'user': {'email': email, 'first_name': first_name, 'password': password},
        'prefs': {'site_name': 'Cosmetics store analytics', 'site_locale': 'en'}})
    client.token = session['id']
    client.require_admin()
    save_session(client)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('login', 'initialize', 'check'))
    args = parser.parse_args()
    try:
        if args.action == 'login':
            login()
        elif args.action == 'initialize':
            initialize()
        else:
            authenticated_client()
            print('Local administrator session is valid.')
    except (OSError, ValueError, KeyError, MetabaseError, EOFError) as error:
        print(f'Metabase authentication failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
