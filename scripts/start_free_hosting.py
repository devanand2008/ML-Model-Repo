"""Run the owned laptop bridge and free Cloudflare tunnel; reconnect Render on restart."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '.tools'
CONFIG = TOOLS / 'free-hosting.json'
STOP = TOOLS / 'free-hosting.stop'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def request(url, data=None, method=None, headers=None, timeout=30):
    supplied = {'User-Agent': 'TransitOpt-free-hosting', **(headers or {})}
    if data is not None:
        data = json.dumps(data).encode()
        supplied['Content-Type'] = 'application/json'
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=supplied), timeout=timeout) as reply:
        return json.load(reply)


def read_config():
    return json.loads(CONFIG.read_text())


def save_config(config):
    temporary = CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, indent=2))
    temporary.replace(CONFIG)


def render_request(path, data=None, method=None):
    import yaml
    cli = Path.home() / '.render' / 'cli.yaml'
    if not cli.exists():
        raise RuntimeError('Run the official Render CLI login to reconnect this service.')
    # The CLI key stays on this laptop. Never send it to Cloudflare or put it in Git.
    token = yaml.safe_load(cli.read_text())['api']['key']
    return request('https://api.render.com/v1' + path, data, method, {'Authorization': 'Bearer ' + token})


def install_cloudflared():
    destination = TOOLS / 'cloudflared-windows-amd64.exe'
    if destination.exists():
        return destination
    release = request('https://api.github.com/repos/cloudflare/cloudflared/releases/latest')
    asset = next(a for a in release['assets'] if a['name'] == destination.name)
    with urllib.request.urlopen(asset['browser_download_url'], timeout=90) as response:
        binary = response.read()
    if asset.get('digest') != 'sha256:' + hashlib.sha256(binary).hexdigest():
        raise RuntimeError('Cloudflare download checksum verification failed')
    destination.write_bytes(binary)
    return destination


def check_local_ml():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / '.env')
    if values.get('AUTH_ENABLED', 'true').lower() != 'true' or len(values.get('ADMIN_PASSWORD', '')) < 12:
        raise RuntimeError('Public hosting requires enabled authentication and a strong laptop admin password.')
    try:
        if request('http://127.0.0.1:8000/api/health', timeout=5).get('status') != 'ok':
            raise RuntimeError('Unexpected service on port 8000')
    except (OSError, urllib.error.URLError):
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'scripts/Start-VisionX.ps1'), 'start', '-NoBrowser'], cwd=ROOT, check=True)
    # Check the actual running server too: .env changes do not update a running process.
    try:
        request('http://127.0.0.1:8000/api/session', timeout=5)
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise RuntimeError('Could not verify laptop admin authentication') from None
    else:
        raise RuntimeError('The running ML server has authentication disabled. Restart it before public hosting.')


def supervise():
    TOOLS.mkdir(exist_ok=True)
    check_local_ml()
    config = read_config() if CONFIG.exists() else {'bridge_token': secrets.token_urlsafe(48)}
    save_config(config)
    try:
        request('http://127.0.0.1:8788/gateway/health', timeout=2)
    except OSError:
        pass
    else:
        print('Hosting bridge is already running. Website:', config.get('public_url', 'deployment pending'), flush=True)
        return
    STOP.unlink(missing_ok=True)
    binary = install_cloudflared()
    bridge = tunnel = None
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    try:
        with (logs / 'free-bridge.log').open('a') as bridge_log:
            environment = {**os.environ, 'GATEWAY_MODE': 'bridge', 'BRIDGE_TOKEN': config['bridge_token'], 'PORT': '8788'}
            bridge = subprocess.Popen([sys.executable, str(ROOT / 'scripts/free_gateway.py')], cwd=ROOT,
                env=environment, stdout=bridge_log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        for _ in range(30):
            if bridge.poll() is not None:
                raise RuntimeError('Bridge failed to start. See logs/free-bridge.log.')
            try:
                request('http://127.0.0.1:8788/gateway/health', timeout=2)
                break
            except OSError:
                time.sleep(1)
        while not STOP.exists():
            with (logs / 'free-tunnel.log').open('w') as tunnel_log:
                tunnel = subprocess.Popen([str(binary), 'tunnel', '--url', 'http://127.0.0.1:8788',
                    '--protocol', 'http2', '--no-autoupdate'], cwd=ROOT,
                    stdout=tunnel_log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            url = None
            for _ in range(90):
                if STOP.exists() or tunnel.poll() is not None:
                    break
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', (logs / 'free-tunnel.log').read_text(errors='replace'))
                if match:
                    url = match.group(0)
                    break
                time.sleep(1)
            if not url:
                raise RuntimeError('Cloudflare tunnel failed. See logs/free-tunnel.log.')
            config = read_config()
            config['tunnel_url'] = url
            save_config(config)
            print('Secure laptop connection ready. Website:', config.get('public_url', 'deployment pending'), flush=True)
            connected_service = None
            last_attempt = 0
            while not STOP.exists() and tunnel.poll() is None:
                if bridge.poll() is not None:
                    raise RuntimeError('Laptop bridge stopped. Run the launcher again.')
                config = read_config()
                service_id = config.get('service_id')
                if service_id and connected_service != service_id and time.monotonic() - last_attempt > 60:
                    last_attempt = time.monotonic()
                    try:
                        service = render_request('/services/' + service_id)
                        if service['serviceDetails']['plan'] != 'free':
                            raise RuntimeError('Refusing to modify a paid service')
                        if config.get('deployed_tunnel_url') != url:
                            render_request('/services/' + service_id + '/env-vars/TUNNEL_URL', {'value': url}, 'PUT')
                            render_request('/services/' + service_id + '/deploys', {'clearCache': 'do_not_clear'}, 'POST')
                            config['deployed_tunnel_url'] = url
                            save_config(config)
                            print('Render is reconnecting to the new laptop tunnel.', flush=True)
                        connected_service = service_id
                    except (OSError, ValueError, KeyError, RuntimeError):
                        print('Render reconnection needs attention. Check Render CLI login and run the launcher again.', flush=True)
                time.sleep(5)
            if tunnel.poll() is None:
                tunnel.terminate()
                tunnel.wait(timeout=15)
            tunnel = None
            if not STOP.exists():
                print('Tunnel stopped; reconnecting in 10 seconds.', flush=True)
                time.sleep(10)
    finally:
        # Stop only child processes owned by this supervisor. Keep the local ML app available.
        for process in (tunnel, bridge):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
        STOP.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status'], nargs='?', default='start')
    action = parser.parse_args().action
    if action == 'stop':
        TOOLS.mkdir(exist_ok=True)
        STOP.touch()
        print('Stopping the free public laptop connection; the local app stays running.')
    elif action == 'status':
        if CONFIG.exists():
            config = read_config()
            print('Website:', config.get('public_url', 'deployment pending'))
            try:
                print('Laptop bridge:', request('http://127.0.0.1:8788/gateway/health', timeout=3)['status'])
            except OSError:
                print('Laptop bridge: offline')
        else:
            print('Free hosting is not configured yet.')
    else:
        try:
            supervise()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print('Hosting startup failed:', type(error).__name__, '- check authentication, dependencies and logs.', flush=True)
            sys.exit(1)
