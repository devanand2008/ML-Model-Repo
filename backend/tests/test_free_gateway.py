import asyncio
import base64
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import free_gateway

TOKEN = 'test-bridge-secret-' + 'x' * 32
HOST = 'https://test.onrender.com'


def make(monkeypatch, tmp_path, bridge=False):
    monkeypatch.setenv('PUBLIC_ORIGIN', HOST)
    (tmp_path / 'index.html').write_text('<main>TransitOpt</main>')
    return free_gateway.create_app(target='http://127.0.0.1:8000' if bridge else 'https://demo.trycloudflare.com',
        token=TOKEN, bridge=bridge, static_dir=tmp_path)


def test_rejects_arbitrary_targets():
    for target in ['http://demo.trycloudflare.com', 'https://example.com', 'https://demo.trycloudflare.com@evil.com',
                   'https://demo.trycloudflare.com/path', 'https://demo.trycloudflare.com:8000']:
        with pytest.raises(ValueError):
            free_gateway.validated_target(target, False)


@pytest.mark.parametrize('bridge', [True, False])
def test_relay_keeps_user_auth_and_query_without_trusting_forwarded_headers(monkeypatch, tmp_path, bridge):
    app = make(monkeypatch, tmp_path, bridge)
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self): yield b'{"ok":true}'
    def backend(request):
        assert request.headers['authorization'] == 'Basic user-credentials'
        assert request.url.query == b'a=1&a=2'
        assert request.headers['origin'] == ('http://127.0.0.1:8000' if bridge else 'https://demo.trycloudflare.com')
        assert 'x-forwarded-for' not in request.headers
        assert ('x-transitopt-bridge' not in request.headers) if bridge else request.headers['x-transitopt-bridge'] == TOKEN
        return httpx.Response(200, stream=Bytes(), headers={'content-type': 'application/json'})
    with TestClient(app, base_url=HOST) as client:
        original = app.state.client
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(backend))
        app.state.client = upstream
        headers = {'Origin': HOST, 'Authorization': 'Basic user-credentials', 'X-Forwarded-For': 'spoofed'}
        if bridge: headers['X-TransitOpt-Bridge'] = TOKEN
        assert client.post('/api/example?a=1&a=2', json={'frame': 'sample'}, headers=headers).json() == {'ok': True}
        app.state.client = original
        asyncio.run(upstream.aclose())


def test_cloud_and_bridge_reject_bypass_and_oversized_uploads(monkeypatch, tmp_path):
    with TestClient(make(monkeypatch, tmp_path), base_url=HOST) as client:
        assert client.get('/').status_code == 200
        assert client.post('/api/example', headers={'Origin': 'https://evil.com'}).status_code == 403
        assert client.post('/api/example', headers={'Content-Length': str(free_gateway.LIMIT + 1)}).status_code == 413
        assert client.get('/assets/missing.js').status_code == 404
    with TestClient(make(monkeypatch, tmp_path, True), base_url=HOST) as client:
        assert client.get('/api/health').status_code == 403
        assert client.get('/api/health', headers={'X-TransitOpt-Bridge': 'wrong'}).status_code == 403
        assert client.get('/', headers={'X-TransitOpt-Bridge': TOKEN}).status_code == 404


def test_cloud_reports_disconnected_laptop_and_still_serves_website(monkeypatch, tmp_path):
    app = make(monkeypatch, tmp_path)
    def offline(request): raise httpx.ConnectError('offline')
    with TestClient(app, base_url=HOST) as client:
        original = app.state.client
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(offline))
        app.state.client = upstream
        assert client.get('/gateway/status').json()['ml_online'] is False
        assert client.get('/api/health').status_code == 503
        assert client.get('/passenger').status_code == 200
        app.state.client = original
        asyncio.run(upstream.aclose())


def test_websocket_preserves_binary_frames_and_rejects_foreign_origin(monkeypatch, tmp_path):
    received = []
    class Stream:
        def __init__(self): self.responses = asyncio.Queue()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send(self, message): received.append(message); await self.responses.put('{"type":"detection"}')
        def __aiter__(self): return self
        async def __anext__(self): return await self.responses.get()
    def connect(url, **kwargs):
        assert 'ticket=one-time' in url
        assert kwargs['additional_headers']['x-transitopt-bridge'] == TOKEN
        assert kwargs['origin'] == 'https://demo.trycloudflare.com'
        return Stream()
    monkeypatch.setattr(free_gateway, 'connect', connect)
    with TestClient(make(monkeypatch, tmp_path), base_url=HOST) as client:
        with client.websocket_connect('/api/analyze/live?ticket=one-time', headers={'Origin': HOST}) as ws:
            ws.send_bytes(b'jpeg'); assert ws.receive_json()['type'] == 'detection'
        assert received == [b'jpeg']
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/analyze/live', headers={'Origin': 'https://evil.com'}): pass


def test_public_admin_authenticates_anonymous_requests_only_on_the_cloud_hop(monkeypatch, tmp_path):
    credential = 'Basic ' + base64.b64encode(b'admin:server-secret-password').decode()
    monkeypatch.setenv('PUBLIC_ORIGIN', HOST)
    app = free_gateway.create_app(target='https://demo.trycloudflare.com', token=TOKEN,
        bridge=False, static_dir=tmp_path, public_admin=True, admin_authorization=credential)
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self): yield b'{"username":"admin"}'
    def backend(request):
        assert request.headers['authorization'] == credential
        assert request.headers['x-transitopt-bridge'] == TOKEN
        return httpx.Response(200, stream=Bytes(), headers={'content-type': 'application/json'})
    with TestClient(app, base_url=HOST) as client:
        original = app.state.client
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(backend))
        app.state.client = upstream
        for headers in ({}, {'Authorization': 'Basic stale-browser-credential'}):
            reply = client.get('/api/session', headers=headers)
            assert reply.json()['username'] == 'admin'
            assert credential not in reply.text and credential not in str(reply.headers)
        app.state.client = original
        asyncio.run(upstream.aclose())
    # A bridge never grants anonymous admin, even if cloud settings leaked into its environment.
    bridge = free_gateway.create_app(target='http://127.0.0.1:8000', token=TOKEN, bridge=True,
        static_dir=tmp_path, public_admin=True, admin_authorization=credential)
    with TestClient(bridge) as client:
        assert client.get('/api/session').status_code == 403


def test_public_admin_requires_a_server_secret_and_blocks_executable_model_uploads(monkeypatch, tmp_path):
    monkeypatch.delenv('UPSTREAM_ADMIN_AUTHORIZATION', raising=False)
    with pytest.raises(ValueError, match='server-side'):
        free_gateway.create_app(target='https://demo.trycloudflare.com', token=TOKEN, bridge=False, public_admin=True)
    credential = 'Basic ' + base64.b64encode(b'admin:server-secret-password').decode()
    app = free_gateway.create_app(target='https://demo.trycloudflare.com', token=TOKEN, bridge=False,
        static_dir=tmp_path, public_admin=True, admin_authorization=credential)
    with TestClient(app, base_url=HOST) as client:
        for path in ['/api/models/upload', '/api/models/upload/', '/api/models%2fupload', '/api/models%252fupload']:
            reply = client.post(path, content=b'untrusted model')
            assert reply.status_code == 403
            assert 'laptop' in reply.json()['detail']
