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
from services.live_detector import LiveDetector, INFERENCE_SIZES, MAX_FRAME_BYTES
from services.activity_reports import ActivityReporter

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='visionx-live')
_tickets = {}
_sessions = 0
_stop_camera_requests = set()
_active_camera_sessions = set()
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
                         confidence: float = Query(.5), track: bool = Query(True), ticket: str = Query(''),
                         camera_started_at: str = Query(''), pose: bool = Query(True),
                         inference_size: int = Query(640), annotated: bool = Query(True),
                         camera_id: str = Query('')):
    global _sessions
    origin = ws.headers.get('origin')
    same_origin = ('https' if ws.url.scheme=='wss' else 'http')+'://'+ws.headers.get('host','')
    if origin and origin not in settings.cors_origins and origin != same_origin:
        await ws.close(code=1008,reason='Origin not allowed');return
    expires = _tickets.pop(ticket,0)
    if settings.auth_enabled and expires < time.monotonic():
        await ws.close(code=1008,reason='Sign in and request a new live-session ticket');return
    if mode not in MODES or not .1 <= confidence <= .95 or inference_size not in INFERENCE_SIZES:
        await ws.close(code=1008,reason='Invalid mode, confidence or inference size');return
    if _sessions >= 2:
        await ws.close(code=1013,reason='Live detection is busy; try again shortly');return
    _sessions += 1
    future = None
    reporter = None
    report_task = None
    camera_claimed = False
    loop = asyncio.get_running_loop()
    async def cpu(fn,*args):
        nonlocal future
        future = loop.run_in_executor(_executor,fn,*args)
        return await asyncio.wait_for(asyncio.shield(future),settings.inference_timeout)
    try:
        await ws.accept()
        transit_session_id = secrets.token_hex(8)
        from transit.mobility import SafetyFrameTracker
        safety_tracker = SafetyFrameTracker()
        safety_zone = None
        associated_role = None
        if camera_id:
            if camera_id in _active_camera_sessions:
                raise ValueError('This registered camera already has an active stream')
            from transit.vision import camera_for
            from transit.models import TransitCameraSetup
            async with AsyncSessionLocal() as transit_db:
                await camera_for(transit_db,camera_id)
                setup = await transit_db.get(TransitCameraSetup,camera_id)
                associated_role = setup.role if setup else None
                safety_zone = setup.safety_zone if setup and setup.role=='bus_interior' else None
            expected_mode = 'human' if associated_role == 'bus_interior' else 'general' if associated_role in {'road_traffic','bus_road'} else None
            if expected_mode and mode != expected_mode:
                raise ValueError(f'This {associated_role} camera requires {expected_mode} detection mode')
            _active_camera_sessions.add(camera_id)
            _stop_camera_requests.discard(camera_id)
            camera_claimed = True
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
        await ws.send_json({'type':'ready','mode':mode,'tracking':track,'pose_enabled':engine.pose,
                            'inference_size':inference_size,'max_fps':settings.live_max_fps,
                            'warnings':engine.warnings,'monitoring':reporter.status()})
        started = time.monotonic()
        last_frame_started = 0.
        last_transit_observation = 0.
        while time.monotonic()-started < 3600:
            if camera_id in _stop_camera_requests:
                await ws.send_json({'type':'stopped'})
                await ws.close(code=1000,reason='Camera stopped by head office')
                break
            message = await asyncio.wait_for(ws.receive(),60)
            if message['type'] == 'websocket.disconnect':
                raise WebSocketDisconnect(message.get('code',1000))
            binary_frame = message.get('bytes')
            text = message.get('text')
            if (binary_frame is not None and len(binary_frame) > MAX_FRAME_BYTES) or (text is not None and len(text) > 3 * 1024 * 1024):
                await ws.close(code=1009,reason='Frame too large');break
            try:
                # Binary JPEG avoids base64 expansion and JSON encoding on every capture.
                msg = {'type':'frame','frame':binary_frame} if binary_frame is not None else json.loads(text)
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
                    safety_tracker.reset()
                    next_mode, next_conf = msg.get('mode',mode),msg.get('confidence',confidence)
                    next_track = msg.get('track',track)
                    next_pose = msg.get('pose',pose)
                    next_size = msg.get('inference_size',inference_size)
                    next_annotated = msg.get('annotated',annotated)
                    if associated_role == 'bus_interior' and next_mode != 'human':
                        raise ValueError('A bus interior camera requires the configured human detector')
                    if associated_role in {'road_traffic','bus_road'} and next_mode != 'general':
                        raise ValueError('A road traffic camera requires the configured general detector')
                    if next_mode not in MODES or not isinstance(next_conf,(int,float)) or not .1 <= next_conf <= .95 or not isinstance(next_track,bool) or not isinstance(next_pose,bool) or type(next_size) is not int or next_size not in INFERENCE_SIZES or not isinstance(next_annotated,bool):
                        raise ValueError('Invalid live configuration')
                    if (next_mode,next_conf,next_track,next_pose,next_size) != (mode,confidence,track,pose,inference_size):
                        # Scene forecasts must not mix counts from different inference settings.
                        transit_session_id = secrets.token_hex(8)
                    if next_mode != mode or next_track != track or next_pose != pose:
                        reporter.reset_tracking('Detection mode or tracking changed')
                        try:
                            engine = await cpu(LiveDetector,next_mode,files,next_track,next_pose)
                        except (ValueError, FileNotFoundError) as exc:
                            await ws.send_json({'type':'error','error':str(exc),'recoverable':False})
                            await ws.close(code=1008)
                            return
                    mode,confidence,track,pose = next_mode,next_conf,next_track,next_pose
                    inference_size,annotated = next_size,next_annotated
                    await ws.send_json({'type':'config_ack','mode':mode,'tracking':track,
                                        'pose_enabled':engine.pose,'confidence':confidence,
                                        'inference_size':inference_size,'max_fps':settings.live_max_fps,
                                        'config_id':msg.get('config_id'),'warnings':engine.warnings});continue
                if msg.get('type') != 'frame':
                    raise ValueError('Expected a camera frame')
                # Pace frame starts only when inference can outpace the negotiated cap.
                # Slower models reply immediately, without an extra delay or queued frames.
                delay = 1/settings.live_max_fps - (time.perf_counter()-last_frame_started)
                if delay > 0:
                    await asyncio.sleep(delay)
                start = time.perf_counter()
                last_frame_started = start
                result = await cpu(engine.process,msg.get('frame'),confidence,inference_size,annotated)
                if camera_id:
                    result['safety_consecutive_frames'] = safety_tracker.update(result.get('detections',[]),
                        result.get('frame_width',0),result.get('frame_height',0),safety_zone)
                elapsed = time.perf_counter()-start
                result.update(inference_time=round(elapsed*1000,1),fps=round(1/max(elapsed,.001),1))
                if camera_id and time.monotonic()-last_transit_observation>=1:
                    from transit.vision import persist_observation
                    async with AsyncSessionLocal() as transit_db:
                        setup = await transit_db.get(TransitCameraSetup,camera_id)
                        next_zone = setup.safety_zone if setup and setup.role=='bus_interior' else None
                        if next_zone != safety_zone:
                            safety_tracker.reset()
                            result['safety_consecutive_frames'] = 0
                            safety_zone = next_zone
                        observation=await persist_observation(transit_db,result,camera_id,
                            'live-'+camera_id+'-'+transit_session_id,'browser_camera')
                    result['transit_observation']=observation
                    last_transit_observation=time.monotonic()
                report = reporter.due()
                if report:
                    await ws.send_json({'type':'report','report':report})
                result['monitoring'] = reporter.ingest(result)
                await ws.send_json(result)
            except (ValueError,TypeError) as exc:
                safety_tracker.reset()
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
        if camera_claimed:
            _active_camera_sessions.discard(camera_id)
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
