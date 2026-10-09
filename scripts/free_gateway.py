"""Small cloud website and token-protected laptop bridge. No ML imports here."""
import asyncio
import anyio
import base64
import os
import posixpath
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

HOP = {'host', 'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'x-forwarded-for',
       'x-forwarded-host', 'x-forwarded-proto', 'x-transitopt-bridge'}
LIMIT = 101 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


def validated_target(target, bridge):
    parsed = urlsplit(target)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Invalid gateway target')
    if bridge:
        if target.rstrip('/') != 'http://127.0.0.1:8000':
            raise ValueError('Laptop bridge must use the loopback ML server')
    elif parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.trycloudflare.com') or parsed.port not in (None, 443):
        raise ValueError('Cloud gateway requires an HTTPS Cloudflare Quick Tunnel')
    return target.rstrip('/')


def create_app(*, target=None, token=None, bridge=None, static_dir=None, public_admin=None, admin_authorization=None):
    bridge = os.getenv('GATEWAY_MODE') == 'bridge' if bridge is None else bridge
    target = validated_target(target or ('http://127.0.0.1:8000' if bridge else os.environ['TUNNEL_URL']), bridge)
    token = token or os.environ['BRIDGE_TOKEN']
    if len(token) < 32:
        raise ValueError('BRIDGE_TOKEN must have at least 32 characters')
    public_admin = (os.getenv('PUBLIC_ADMIN_ENABLED', 'false').lower() == 'true' if public_admin is None else public_admin) and not bridge
    admin_authorization = admin_authorization or os.getenv('UPSTREAM_ADMIN_AUTHORIZATION', '')
    if public_admin:
        try:
            scheme, encoded = admin_authorization.split(' ', 1)
            username, password = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
            if scheme != 'Basic' or not username or len(password) < 12:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError('Public admin requires a strong server-side upstream credential') from None
    static = Path(static_dir or ROOT / 'frontend' / 'dist').resolve()
    public_origin = os.getenv('PUBLIC_ORIGIN') or ('https://' + os.environ['RENDER_EXTERNAL_HOSTNAME'] if 'RENDER_EXTERNAL_HOSTNAME' in os.environ else None)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), trust_env=False, follow_redirects=False) as client:
            app.state.client = client
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def allowed(request):
        if bridge:
            return secrets.compare_digest(request.headers.get('x-transitopt-bridge', '').encode(), token.encode())
        origin = request.headers.get('origin')
        expected = public_origin or str(request.url).split(request.headers.get('host', ''))[0] + request.headers.get('host', '')
        # Render's TLS terminates before the container; only its configured public origin is trusted.
        return not origin or origin == expected

    def headers(request):
        result = {k: v for k, v in request.headers.items() if k.lower() not in HOP and k.lower() != 'origin'}
        result['origin'] = target
        if not bridge:
            result['x-transitopt-bridge'] = token
            if public_admin:
                result['authorization'] = admin_authorization
        return result

    @app.get('/gateway/health')
    async def health():
        return {'status': 'ok', 'hosting': 'laptop-bridge' if bridge else 'free-hybrid'}

    @app.get('/gateway/status')
    async def status(request: Request):
        if bridge or not allowed(request):
            return JSONResponse({'detail': 'Forbidden'}, status_code=403)
        try:
            response = await app.state.client.get(target + '/api/health', headers={'x-transitopt-bridge': token}, timeout=10)
            online = response.status_code == 200 and response.json().get('status') == 'ok'
        except (httpx.HTTPError, ValueError):
            online = False
        return JSONResponse({'hosting': 'free-hybrid', 'ml_online': online, 'public_admin': public_admin}, headers={'Cache-Control': 'no-store'})

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def relay(path: str, request: Request):
        if not allowed(request):
            return JSONResponse({'detail': 'Forbidden'}, status_code=403)
        canonical = path
        for _ in range(3):
            canonical = unquote(canonical)
        canonical = posixpath.normpath('/' + canonical).rstrip('/')
        if public_admin and request.method not in {'GET', 'HEAD', 'OPTIONS'} and canonical == '/api/models/upload':
            return JSONResponse({'detail': 'Model checkpoint uploads are available only on the laptop app. Model files can execute code when loaded.'}, status_code=403)
        if not (path.startswith('api/') or path == 'openapi.json'):
            if bridge or request.method not in {'GET', 'HEAD'}:
                return JSONResponse({'detail': 'Not found'}, status_code=404)
            file = (static / path).resolve()
            if not file.is_relative_to(static):
                return JSONResponse({'detail': 'Not found'}, status_code=404)
            if file.is_file():
                return FileResponse(file)
            if path.startswith('assets/'):
                return JSONResponse({'detail': 'Not found'}, status_code=404)
            return FileResponse(static / 'index.html', headers={'Cache-Control': 'no-cache'})
        try:
            length = int(request.headers.get('content-length', '0'))
            if length < 0 or length > LIMIT:
                return JSONResponse({'detail': 'Upload too large'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)
        async def body():
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > LIMIT:
                    raise ValueError('Upload too large')
                yield chunk
        try:
            url = httpx.URL(target + '/' + path, query=request.url.query.encode())
            upstream = app.state.client.build_request(request.method, url, headers=headers(request), content=body())
            reply = await app.state.client.send(upstream, stream=True)
        except ValueError:
            return JSONResponse({'detail': 'Upload too large'}, status_code=413)
        except httpx.HTTPError:
            return JSONResponse({'detail': 'Laptop ML is disconnected. On the laptop, run Start-Free-Hosting.bat.'}, status_code=503)
        return StreamingResponse(reply.aiter_raw(), status_code=reply.status_code,
            headers={k: v for k, v in reply.headers.items() if k.lower() not in HOP}, background=BackgroundTask(reply.aclose))

    @app.websocket('/api/analyze/live')
    async def live(socket: WebSocket):
        if not allowed(socket):
            await socket.close(code=1008, reason='Forbidden')
            return
        tasks = []
        try:
            address = target.replace('https:', 'wss:').replace('http:', 'ws:') + '/api/analyze/live?' + socket.url.query
            forwarded = headers(socket)
            forwarded.pop('origin', None)
            # Upstream negotiates its own WebSocket headers.
            forwarded = {k: v for k, v in forwarded.items() if not k.lower().startswith('sec-websocket-')}
            async with connect(address, origin=target, additional_headers=forwarded, proxy=None,
                max_size=8*1024*1024, max_queue=2, compression=None, open_timeout=20) as upstream:
                await socket.accept()
                async def to_backend():
                    while True:
                        event = await socket.receive()
                        if event['type'] == 'websocket.disconnect':
                            return
                        message = event.get('bytes') if event.get('bytes') is not None else event.get('text')
                        if message is not None:
                            await upstream.send(message)
                async def to_browser():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await socket.send_bytes(message)
                        else:
                            await socket.send_text(message)
                tasks = [asyncio.create_task(to_backend()), asyncio.create_task(to_browser())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except InvalidHandshake:
            await socket.close(code=1008, reason='ML server rejected this session')
        except (ConnectionClosed, WebSocketDisconnect, OSError, RuntimeError):
            pass
        except asyncio.CancelledError:
            pass
        finally:
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    await socket.close()
                except (RuntimeError, WebSocketDisconnect):
                    pass
    return app


if __name__ == '__main__':
    import uvicorn
    bridge = os.getenv('GATEWAY_MODE') == 'bridge'
    uvicorn.run(create_app(), host='127.0.0.1' if bridge else '0.0.0.0',
                port=int(os.getenv('PORT', '8788' if bridge else '10000')), access_log=False,
                proxy_headers=False)
