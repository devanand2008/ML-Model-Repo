"""Phone TLS identity, encrypted gateway plumbing and authentication preservation."""
import asyncio
import sys
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import phone_gateway
from phone_tls import generate
from prepare_phone_auth import prepare
from dotenv import dotenv_values


def test_certificate_contains_private_lan_address_and_preserves_ca(tmp_path):
    first=generate('192.168.1.25',tmp_path)
    certificate=x509.load_pem_x509_certificate((tmp_path/'server.crt').read_bytes())
    names=certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert str(names.get_values_for_type(x509.IPAddress)[0])=='192.168.1.25'
    assert ExtendedKeyUsageOID.SERVER_AUTH in certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert generate('192.168.1.26',tmp_path)==first
    assert (tmp_path/'address.txt').read_text()=='192.168.1.26'


def test_phone_setup_replaces_weak_password_but_preserves_custom_password(tmp_path):
    env=tmp_path/'.env';env.write_text('AUTH_ENABLED=false\nADMIN_PASSWORD=changeme\nDATABASE_URL=sqlite+aiosqlite:///demo.db\n')
    prepare(env);values=dotenv_values(env)
    assert values['AUTH_ENABLED']=='true'
    assert len(values['ADMIN_PASSWORD'])>=24
    assert values['DATABASE_URL']=='sqlite+aiosqlite:///demo.db'
    prepare(env);assert dotenv_values(env)['ADMIN_PASSWORD']==values['ADMIN_PASSWORD']


def test_https_http_relay_preserves_auth_and_original_origin():
    seen=[]
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):yield b'{"routes":[]}'
    def backend(request):
        seen.append(request)
        assert request.headers['authorization']=='Basic test-token'
        assert request.headers['host']=='192.168.1.25:8443'
        assert request.headers['origin']=='https://192.168.1.25:8443'
        assert request.headers['x-forwarded-proto']=='https'
        return httpx.Response(200,stream=Bytes(),headers={'content-type':'application/json'})
    with TestClient(phone_gateway.app,base_url='https://192.168.1.25:8443') as client:
        original=phone_gateway.app.state.client
        upstream=httpx.AsyncClient(transport=httpx.MockTransport(backend))
        phone_gateway.app.state.client=upstream
        reply=client.post('/api/public/navigation/monitor',json={'routes':[]},headers={
            'Authorization':'Basic test-token','Origin':'https://192.168.1.25:8443'})
        assert reply.status_code==200
        assert seen[0].content==b'{"routes":[]}'
        phone_gateway.app.state.client=original
        asyncio.run(upstream.aclose())


def test_phone_websocket_passes_binary_frames_and_rejects_foreign_origin(monkeypatch):
    received=[]
    class Stream:
        def __init__(self):self.responses=asyncio.Queue()
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,message):received.append(message);await self.responses.put('{"type":"detection"}')
        def __aiter__(self):return self
        async def __anext__(self):return await self.responses.get()
    def connect(url,**kwargs):
        assert 'ticket=one-time' in url
        assert kwargs['origin']=='http://127.0.0.1:8000'
        return Stream()
    monkeypatch.setattr(phone_gateway,'connect',connect)
    with TestClient(phone_gateway.app,base_url='https://192.168.1.25:8443') as client:
        with client.websocket_connect('wss://192.168.1.25:8443/api/analyze/live?ticket=one-time',headers={
            'origin':'https://192.168.1.25:8443'}) as ws:
            ws.send_bytes(b'jpeg frame');assert ws.receive_json()['type']=='detection'
        assert received==[b'jpeg frame']
        from starlette.websockets import WebSocketDisconnect
        import pytest
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('wss://192.168.1.25:8443/api/analyze/live',headers={'origin':'https://untrusted.example'}):pass
