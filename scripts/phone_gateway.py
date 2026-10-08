"""HTTPS LAN gateway to the one loopback ML server, including binary WebSockets."""
import asyncio
import anyio
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

BACKEND = 'http://127.0.0.1:8000'
HOP = {'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer',
       'transfer-encoding','upgrade','x-forwarded-for','x-forwarded-host','x-forwarded-proto'}


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=httpx.Timeout(150,connect=5),trust_env=False) as client:
        app.state.client=client
        yield


app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)


@app.api_route('/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD'])
async def relay_http(path:str,request:Request):
    headers={k:v for k,v in request.headers.items() if k.lower() not in HOP}
    headers['x-forwarded-proto']=request.url.scheme
    # Backend validates the original phone Origin against this retained Host.
    try:
        upstream=request.app.state.client.build_request(request.method,
            BACKEND+'/'+path,params=request.query_params.multi_items(),headers=headers,content=request.stream())
        reply=await request.app.state.client.send(upstream,stream=True)
    except httpx.HTTPError:
        return JSONResponse({'detail':'Laptop ML server is offline. Run Run-TransitOpt.bat start.'},status_code=502)
    return StreamingResponse(reply.aiter_raw(),status_code=reply.status_code,
        headers={k:v for k,v in reply.headers.items() if k.lower() not in HOP},
        background=BackgroundTask(reply.aclose))


@app.websocket('/api/analyze/live')
async def relay_live(socket:WebSocket):
    origin=socket.headers.get('origin')
    expected=('https' if socket.url.scheme=='wss' else 'http')+'://'+socket.headers.get('host','')
    if origin and origin!=expected:
        await socket.close(code=1008,reason='Origin not allowed');return
    headers={'Authorization':socket.headers['authorization']} if 'authorization' in socket.headers else {}
    tasks=[]
    try:
        # Original external origin was validated above; the internal hop is loopback.
        async with connect('ws://127.0.0.1:8000/api/analyze/live?'+socket.url.query,
            origin=BACKEND,additional_headers=headers,proxy=None,max_size=8*1024*1024,
            max_queue=2,compression=None,open_timeout=10) as upstream:
            await socket.accept()
            async def to_backend():
                while True:
                    event=await socket.receive()
                    if event['type']=='websocket.disconnect':return
                    if event.get('bytes') is not None:await upstream.send(event['bytes'])
                    elif event.get('text') is not None:await upstream.send(event['text'])
            async def to_phone():
                async for message in upstream:
                    if isinstance(message,bytes):await socket.send_bytes(message)
                    else:await socket.send_text(message)
            tasks=[asyncio.create_task(to_backend()),asyncio.create_task(to_phone())]
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
    except InvalidHandshake:
        await socket.close(code=1008,reason='ML server rejected the live session')
    except (ConnectionClosed,WebSocketDisconnect,OSError,RuntimeError):
        pass
    except asyncio.CancelledError:
        pass
    finally:
        with anyio.CancelScope(shield=True):
            for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            try:await socket.close()
            except (RuntimeError,WebSocketDisconnect):pass
