"""Initialize credentials and manage the project's local Compose services."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from local_config import ROOT, initialize_env, read_env


def docker_executable():
    located = shutil.which('docker')
    if located:
        return located
    candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker/resources/bin/docker.exe'
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError('Docker CLI not found. Start Docker Desktop and check its installation path.')


def compose_arguments(action):
    command = [docker_executable(), 'compose', '--env-file', str(ROOT/'.env'), '-f', str(ROOT/'compose.yaml')]
    arguments = {'up': ['up', '-d', '--wait', '--wait-timeout', '240'],
                 'status': ['ps'], 'config': ['config', '--quiet'], 'stop': ['stop']}
    return command + arguments[action]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'up', 'status', 'config', 'stop'))
    args = parser.parse_args()
    try:
        if args.action == 'init':
            created = initialize_env()
            print('Created local .env with generated credentials.' if created else 'Existing .env retained.')
        else:
            read_env()
            arguments = compose_arguments(args.action)
            environment = os.environ.copy()
            environment['PATH'] = str(Path(arguments[0]).parent) + os.pathsep + environment.get('PATH', '')
            subprocess.run(arguments, cwd=ROOT, env=environment, check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Local service command failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
