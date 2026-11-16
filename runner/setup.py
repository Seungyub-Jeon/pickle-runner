#!/usr/bin/env python3
"""Agent-readable onboarding. status is read-only; connect explicitly provisions CF."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import manage

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / '.runtime' / 'cloudflare-setup'


def domain(value):
    value = value.lower().rstrip('.')
    if len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.')) or '.' not in value:
        raise ValueError('Use a DNS name without URL, wildcard, port or path')
    return value


def configure(zone, hostname, preserve=()):
    zone, hostname = domain(zone), domain(hostname)
    if not hostname.endswith('.' + zone):
        raise ValueError('Choose a dedicated subdomain inside the selected zone')
    config = json.loads((manage.RUNTIME / 'config.json').read_text())
    hosts = sorted(set(domain(h) for h in preserve))
    if any(h == hostname or not (h == zone or h.endswith('.' + zone)) for h in hosts):
        raise ValueError('Preserved hosts must be other names in the same zone')
    desired = {'zone':zone, 'hostname':hostname, 'port':config['port'], 'preserve_hostnames':hosts}
    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STORE / 'settings.json'
    if (STORE / 'plan.json').exists() or (STORE / 'resources.json').exists():
        if not path.exists() or json.loads(path.read_text()) != desired:
            raise ValueError('Existing Cloudflare setup belongs to another configuration; keep it intact')
    manage.private_json(path, desired)
    return {'configured':True, 'hostname':hostname, 'next':'python3 runner/cloudflare_token.py prompt', 'cloudflare_changed':False}


def status():
    config_path = manage.RUNTIME / 'config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    result = {'platform_supported':sys.platform == 'darwin', 'python_supported':sys.version_info >= (3,9),
              'local_configured':bool(config), 'terminal_enabled':config.get('terminal_enabled', False),
              'cloudflared_installed':bool(shutil.which('cloudflared')),
              'cloudflare_configured':(STORE/'settings.json').exists(),
              'setup_token_present':(STORE/'api-token').exists(),
              'remote_config_present':(manage.RUNTIME/'client-remote.json').exists()}
    if not result['local_configured']:
        result['next'] = 'python3 runner/setup.py init'
    elif not result['cloudflare_configured']:
        result['next'] = 'Choose local-only use, or run setup.py cloudflare --zone YOUR_DOMAIN --hostname runner.YOUR_DOMAIN'
    elif result['setup_token_present']:
        result['next'] = 'Install cloudflared, run python3 runner/manage.py install, then python3 runner/setup.py connect'
    elif result['remote_config_present']:
        result['next'] = 'python3 runner/check_remote.py --config .runtime/pickle-runner/client-remote.json'
    else:
        result['next'] = 'python3 runner/cloudflare_token.py prompt'
    return result


class ConnectionFailure(ValueError):
    def __init__(self, stage, verified=None):
        super().__init__("Connection incomplete at " + stage)
        self.stage = stage
        self.checks = {}
        for name in ("no_credentials", "agent_only", "access_only", "both"):
            item = (verified or {}).get("checks", {}).get(name, {})
            if type(item.get("status")) is int and type(item.get("passed")) is bool:
                self.checks[name] = {"status": item["status"], "passed": item["passed"]}


def connect():
    stage, verified = "prerequisites", None
    try:
        stage = 'prerequisites'
        if sys.platform != 'darwin' or not shutil.which('cloudflared'):
            raise ValueError('macOS and an installed cloudflared are required')
        stage = 'local_health'
        from client import request
        local = json.loads((manage.RUNTIME/'client-local.json').read_text())
        code, health = request(local, 'GET', '/health')
        if code != 200 or health.get('service') != 'pickle-runner':
            raise ValueError('Start and verify the local runner before configuring Cloudflare')
        stage = 'load_checkpoint'
        from cloudflare_connect import Setup
        setup = Setup()
        stage = 'provision'
        setup.provision()
        stage = 'start_tunnel'
        setup.service()
        stage = 'tunnel_health'
        for unused in range(30):
            state = setup.api(setup.account + '/cfd_tunnel/' + setup.state['tunnel_id'])
            if state.get('status') == 'healthy':
                break
            time.sleep(1)
        else:
            raise ValueError('Tunnel is not healthy; DNS has not been published')
        stage = 'publish_dns'
        setup.publish()
        stage = 'remote_auth'
        from check_remote import check
        remote = json.loads((manage.RUNTIME/'client-remote.json').read_text())
        verified = None
        for unused in range(30):
            try:
                verified = check(remote)
                if verified['passed']:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(2)
        if not verified or not verified['passed']:
            raise ValueError('External authentication verification incomplete; inspect access policy and DNS')
        stage = 'credential_metadata'
        setup.credential_metadata()
        stage = 'remove_setup_token'
        (STORE/'api-token').unlink()
        return {'connected':True, 'checks':verified, 'setup_token_local_copy_removed':True,
                'note':'Revoking the issued management API token is a separate Cloudflare operation. Transfer client configuration privately.'}
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError):
        raise ConnectionFailure(stage, verified) from None

def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='status', choices=['status','init','cloudflare','connect'])
    parser.add_argument('--port', type=int, default=8796)
    parser.add_argument('--zone')
    parser.add_argument('--hostname')
    parser.add_argument('--preserve-host', action='append', default=[])
    args = parser.parse_args()
    try:
        if args.command == 'init':
            if not 1024 <= args.port <= 65535:
                raise ValueError('port must be 1024..65535')
            manage.initialize(args.port)
            result = status()
        elif args.command == 'cloudflare':
            if not args.zone or not args.hostname:
                parser.error('--zone and --hostname are required')
            result = configure(args.zone, args.hostname, args.preserve_host)
        elif args.command == 'connect':
            result = connect()
        else:
            result = status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ConnectionFailure as exc:
        print(json.dumps({'error':'setup_incomplete', 'stage':exc.stage, 'checks':exc.checks,
                          'next':'Inspect this stage in docs/SETUP.md, then retry python3 runner/setup.py connect'}))
        raise SystemExit(1)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError):
        # Provider exceptions and settings may contain credentials: no raw traceback.
        print(json.dumps({'error':'setup_incomplete','next':'Check local service, setup state and docs/SETUP.md; credentials were not printed'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
