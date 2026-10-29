#!/usr/bin/python3
"""Recover the demo origin after three failed probes; never touch GPU jobs."""
import json
import pathlib
import subprocess
import urllib.request

STATE = pathlib.Path('/var/lib/joymedia-demo-health/state.json')
FUNNEL_ENABLED = pathlib.Path('/etc/joymedia-demo-funnel-enabled')


def funnel_healthy():
    try:
        result = subprocess.run(
            ['/usr/local/bin/tailscale', 'status', '--json'],
            capture_output=True, check=True, timeout=15,
        )
        status = json.loads(result.stdout)
        return status.get('BackendState') == 'Running' and status.get('Self', {}).get('Online') is True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def probe(url, host=None, ping=False, ready=False):
    try:
        request = urllib.request.Request(url, headers={'Host': host} if host else {})
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read(262144)
            return response.status == 200 and (ready or (
                json.loads(body).get('message') == 'pong' if ping else b'<html' in body.lower()
            ))
    except Exception:
        return False


def recover(service):
    print(f'Recovering {service} after three failed health checks', flush=True)
    subprocess.run(['systemctl', 'restart', service], check=True, timeout=60)


def main():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    use_funnel = FUNNEL_ENABLED.exists()
    checks = {
        'web': probe('http://127.0.0.1:18080/api/method/ping', 'demo.localhost', ping=True),
        'proxy': probe('http://127.0.0.1:18081/joymedia/projects'),
        'tunnel': funnel_healthy() if use_funnel else probe('http://127.0.0.1:20241/ready', ready=True),
    }
    for name, healthy in checks.items():
        state[name] = 0 if healthy else state.get(name, 0) + 1
    # Recover the application first. A bad upstream alone must not restart nginx.
    if state['web'] >= 3:
        recover('joymedia-demo-web.service')
        state['web'] = 0
    elif checks['web'] and state['proxy'] >= 3:
        recover('joymedia-demo-proxy.service')
        state['proxy'] = 0
    if state['tunnel'] >= 3:
        recover('joymedia-tailscaled.service' if use_funnel else 'joymedia-demo-tunnel.service')
        state['tunnel'] = 0
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state) + '\n')
    temporary.replace(STATE)
    print(json.dumps({'healthy': checks, 'consecutive_failures': state}), flush=True)


if __name__ == '__main__':
    main()
