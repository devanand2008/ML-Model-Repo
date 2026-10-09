import io
import sys
import urllib.error
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import start_free_hosting as hosting


def test_transport_selection_allows_quic_and_binds_metrics_to_loopback():
    args = hosting.tunnel_arguments(Path('cloudflared.exe'))
    assert args[args.index('--protocol') + 1] == 'auto'
    assert args[args.index('--metrics') + 1] == '127.0.0.1:8789'
    assert args[args.index('--url') + 1] == 'http://127.0.0.1:8788'


def test_readiness_requires_a_successful_edge_connection(monkeypatch):
    class Reply(io.BytesIO):
        status = 200
    monkeypatch.setattr(hosting.urllib.request, 'urlopen', lambda *args, **kwargs: Reply(b'ready'))
    assert hosting.tunnel_ready()
    def disconnected(*args, **kwargs):
        raise urllib.error.HTTPError(hosting.TUNNEL_READY_URL, 503, 'no edge connection', {}, None)
    monkeypatch.setattr(hosting.urllib.request, 'urlopen', disconnected)
    assert not hosting.tunnel_ready()
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError('connection refused')
    monkeypatch.setattr(hosting.urllib.request, 'urlopen', unavailable)
    assert not hosting.tunnel_ready()


def test_safe_connection_checks_retry_but_deploy_posts_are_not_replayed(monkeypatch):
    calls = []
    monkeypatch.setattr(hosting.time, 'sleep', lambda _: None)
    def intermittent(message, **kwargs):
        calls.append(message.get_method())
        if len(calls) == 1:
            raise urllib.error.URLError('TLS connection reset')
        return io.BytesIO(b'{"status":"ok"}')
    monkeypatch.setattr(hosting.urllib.request, 'urlopen', intermittent)
    assert hosting.request('https://test.example/health')['status'] == 'ok'
    assert calls == ['GET', 'GET']
    calls.clear()
    with pytest.raises(urllib.error.URLError):
        hosting.request('https://test.example/deploys', {}, 'POST')
    assert calls == ['POST']


def test_live_handoff_uses_private_bridge_token_without_render_account_access(monkeypatch):
    calls = []
    def capture(url, data, method, headers, timeout):
        calls.append((url, data, method, headers))
        return {'status': 'connected', 'ml_online': True}
    monkeypatch.setattr(hosting, 'request', capture)
    config = {'public_url': 'https://demo.onrender.com', 'bridge_token': 'private-connection-token'}
    hosting.publish_connection(config, 'https://new.trycloudflare.com')
    assert calls == [('https://demo.onrender.com/gateway/connection', {'target': 'https://new.trycloudflare.com'},
        'PUT', {'X-TransitOpt-Bridge': 'private-connection-token'})]
    config['public_url'] = 'https://evil.example'
    with pytest.raises(RuntimeError, match='configured HTTPS Render'):
        hosting.publish_connection(config, 'https://new.trycloudflare.com')
    assert len(calls) == 1
