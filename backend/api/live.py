"""Bounded live YOLO frame streaming with short-lived authenticated tickets."""
import asyncio
import json
import secrets
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select
from config import settings
from database import AIModel, AsyncSessionLocal
from security import inference_limit
from services.live_detector import LiveDetector
from services.activity_reports import ActivityReporter

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='visionx-live')
_tickets = {}
_sessions = 0
MODES = {'general','human','ship','container','port_monitor'}

@router.post('/live/ticket', dependencies=[Depends(inference_limit)])
async def live_ticket():
    now = time.monotonic()
    for key in list(_tickets):
        if _tickets[key] < now:
            del _tickets[key]
    if len(_tickets) >= 100:
        raise HTTPException(429, 'Too many live-session requests')
    token = secrets.token_urlsafe(32)
    _tickets[token] = now + 30
    return {'ticket': token}

async def model_files():
    files = {kind:getattr(settings,f'{kind}_model') for kind in ('general','human','ship','container')}
    async with AsyncSessionLocal() as db:
        records = (await db.execute(select(AIModel).where(AIModel.is_active == True,AIModel.is_default == True))).scalars()
        for record in records:
            if record.model_type in files:
                files[record.model_type] = record.filename
    return files

@router.websocket('/live')
async def live_camera_ws(ws: WebSocket, mode: str = Query('general'),
                         confidence: float = Query(.5), track: bool = Query(True), ticket: str = Query(''), camera_started_at: str = Query(''), pose: bool = Query(True)):
    global _sessions
    origin = ws.headers.get('origin')
    same_origin = ('https' if ws.url.scheme=='wss' else 'http')+'://'+ws.headers.get('host','')
    if origin and origin not in settings.cors_origins and origin != same_origin:
        await ws.close(code=1008,reason='Origin not allowed');return
    expires = _tickets.pop(ticket,0)
    if settings.auth_enabled and expires < time.monotonic():
        await ws.close(code=1008,reason='Sign in and request a new live-session ticket');return
    if mode not in MODES or not .1 <= confidence <= .95:
        await ws.close(code=1008,reason='Invalid mode or confidence');return
    if _sessions >= 2:
        await ws.close(code=1013,reason='Live detection is busy; try again shortly');return
    _sessions += 1
    future = None
    reporter = None
    report_task = None
    loop = asyncio.get_running_loop()
    async def cpu(fn,*args):
        nonlocal future
        future = loop.run_in_executor(_executor,fn,*args)
        return await asyncio.wait_for(asyncio.shield(future),settings.inference_timeout)
    try:
        await ws.accept()
        files = await model_files()
        engine = await cpu(LiveDetector,mode,files,track,pose)
        camera_time = None
        if camera_started_at:
            try:
                from services.activity_reports import IST
                parsed = datetime.fromisoformat(camera_started_at.replace('Z','+00:00'))
                if parsed.tzinfo is not None:
                    camera_time = parsed.astimezone(IST).isoformat(timespec='seconds')
            except ValueError:
                pass
        reporter = ActivityReporter(camera_started_at=camera_time)
        async def publish_reports():
            while True:
                await asyncio.sleep(1)
                report = reporter.due()
                if report:
                    await ws.send_json({'type':'report','report':report,'monitoring':reporter.status()})
        report_task = asyncio.create_task(publish_reports())
        await ws.send_json({'type':'ready','mode':mode,'tracking':track,'warnings':engine.warnings,'monitoring':reporter.status()})
        started = time.monotonic()
        while time.monotonic()-started < 3600:
            text = await asyncio.wait_for(ws.receive_text(),60)
            if len(text) > 3 * 1024 * 1024:
                await ws.close(code=1009,reason='Frame too large');break
            try:
                msg = json.loads(text)
                if not isinstance(msg,dict):
                    raise ValueError('Invalid message')
                if msg.get('type') == 'ping':
                    await ws.send_json({'type':'pong'});continue
                if msg.get('type') == 'stop':
                    report_task.cancel()
                    report = reporter.flush(partial=True,reason='Detection stopped')
                    if report:
                        await ws.send_json({'type':'report','report':report})
                    reporter = None
                    await ws.send_json({'type':'stopped'})
                    await ws.close(code=1000)
                    break
                if msg.get('type') == 'config':
                    next_mode, next_conf = msg.get('mode',mode),msg.get('confidence',confidence)
                    next_track = msg.get('track',track)
                    next_pose = msg.get('pose',pose)
                    if next_mode not in MODES or not isinstance(next_conf,(int,float)) or not .1 <= next_conf <= .95 or not isinstance(next_track,bool) or not isinstance(next_pose,bool):
                        raise ValueError('Invalid live configuration')
                    if next_mode != mode or next_track != track or next_pose != pose:
                        reporter.reset_tracking('Detection mode or tracking changed')
                        try:
                            engine = await cpu(LiveDetector,next_mode,files,next_track,next_pose)
                        except (ValueError, FileNotFoundError) as exc:
                            await ws.send_json({'type':'error','error':str(exc),'recoverable':False})
                            await ws.close(code=1008)
                            return
                    mode,confidence,track,pose = next_mode,next_conf,next_track,next_pose
                    await ws.send_json({'type':'config_ack','mode':mode,'warnings':engine.warnings});continue
                if msg.get('type') != 'frame':
                    raise ValueError('Expected a camera frame')
                start = time.perf_counter()
                result = await cpu(engine.process,msg.get('frame'),confidence)
                elapsed = time.perf_counter()-start
                result.update(inference_time=round(elapsed*1000,1),fps=round(1/max(elapsed,.001),1))
                report = reporter.due()
                if report:
                    await ws.send_json({'type':'report','report':report})
                result['monitoring'] = reporter.ingest(result)
                await ws.send_json(result)
                # No more than 15 frames/sec per connection. Client waits for each reply.
                await asyncio.sleep(max(0,1/15-elapsed))
            except (ValueError,TypeError) as exc:
                await ws.send_json({'type':'error','error':str(exc),'recoverable':True})
        else:
            await ws.close(code=1000,reason='Session ended after one hour; reconnect')
    except WebSocketDisconnect:
        pass
    except (ValueError,FileNotFoundError) as exc:
        await ws.send_json({'type':'error','error':str(exc),'recoverable':False})
        await ws.close(code=1008)
    except asyncio.TimeoutError:
        try:
            await ws.send_json({'type':'error','error':'Live session timed out. Restart detection.','recoverable':False})
            await ws.close(code=1011)
        except RuntimeError:
            pass
    except Exception:
        logger.exception('Live camera session failed')
        try:
            await ws.send_json({'type':'error','error':'Live model failed. Check installed weights and server logs.','recoverable':False})
            await ws.close(code=1011)
        except RuntimeError:
            pass
    finally:
        if report_task is not None:
            report_task.cancel()
            try:
                await report_task
            except (asyncio.CancelledError, Exception):
                pass
        if reporter is not None:
            try:
                reporter.flush(partial=True,reason='Live connection ended')
            except Exception:
                logger.exception('Could not save final activity report')
        # Keep admission occupied until an already-running native inference finishes.
        if future is not None and not future.done():
            try:
                await asyncio.shield(future)
            except Exception:
                pass
        _sessions -= 1
