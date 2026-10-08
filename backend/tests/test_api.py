import os
import sys
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="visionx-test-"))
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + (TEST_ROOT / 'test.db').as_posix()
os.environ['UPLOAD_DIR'] = str(TEST_ROOT / 'uploads')
os.environ['OUTPUT_DIR'] = str(TEST_ROOT / 'outputs')
os.environ['REPORT_DIR'] = str(TEST_ROOT / 'reports')
os.environ['AUTH_ENABLED'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from main import app
from config import settings
from security import attempts

@pytest.fixture
def client():
    attempts.clear()
    with TestClient(app) as c:
        yield c

def test_health_models_and_schema(client):
    assert client.get('/api/health').status_code == 200
    models = client.get('/api/models').json()['models']
    assert len(models) >= 4
    assert models[0]['metrics'].get('mAP50') is None
    assert '/api/analyze/webcam' in client.get('/openapi.json').json()['paths']

def test_local_dashboard_origin(client):
    origin = 'http://127.0.0.1:8000'
    response = client.get('/api/session', headers={'Origin': origin})
    assert response.status_code == 200
    assert response.headers.get('access-control-allow-origin') == origin
    preflight = client.options('/api/analyze/live/ticket', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization'})
    assert preflight.status_code == 200
    assert preflight.headers.get('access-control-allow-origin') == origin

def test_invalid_inputs(client):
    assert client.post('/api/analyze/image', files={'file': ('x.exe', b'x')}).status_code == 400
    assert client.post('/api/analyze/image', files={'file': ('x.png', b'broken')}).status_code == 400
    assert client.post('/api/analyze/image', data={'confidence': 2}, files={'file': ('x.png', b'x')}).status_code == 422
    assert not list(settings.upload_dir.rglob('*.png'))

def test_model_type_cannot_escape_storage(client):
    r = client.post('/api/models/upload', data={'name':'bad','model_type':'../../escape'}, files={'file':('x.pt',b'bad')})
    assert r.status_code == 422

def test_authentication(client):
    settings.auth_enabled = True
    try:
        assert client.get('/api/history').status_code == 401
        assert client.get('/api/history', auth=(settings.admin_username,settings.admin_password)).status_code == 200
    finally:
        settings.auth_enabled = False

def test_real_image_inference_and_fallback(client):
    from ultralytics.utils import ASSETS
    data = (ASSETS / 'bus.jpg').read_bytes()
    result = client.post('/api/analyze/image', files={'file':('bus.jpg',data)}, data={'confidence': .5})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['counts'].get('person',0) > 0
    assert body['image_width'] > 0
    assert body['annotated_image'].startswith('data:image/')
    fallback = client.post('/api/analyze/container', files={'file':('bus.jpg',data)}).json()
    assert fallback['condition']['total_containers'] is None
    assert fallback['condition']['good'] is None
    assert fallback['warnings']
    combined = client.post('/api/analyze/combined', files={'file':('bus.jpg',data)}).json()
    assert combined['containers'] == 0
    assert len(combined['detections']) == sum(combined['counts'].values())
    assert not list(settings.upload_dir.rglob('*.jpg'))

def test_corrupt_video_cleans_upload(client):
    response = client.post('/api/analyze/video', files={'file':('broken.mp4',b'broken')})
    assert response.status_code == 400
    assert not list(settings.upload_dir.rglob('*.mp4'))

def test_real_video_tracking():
    from ultralytics.utils import ASSETS
    from services.video_processor import process_video
    frame = cv2.resize(cv2.imread(str(ASSETS / 'bus.jpg')), (320, 416))
    source, output = TEST_ROOT/'clip.avi', TEST_ROOT/'annotated.mp4'
    writer = cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'MJPG'),5,(320,416))
    for _ in range(3):
        writer.write(frame)
    writer.release()
    result = process_video(str(source),str(output),'yolo26n.pt',class_filter=[0])
    assert result['processed_frames'] == 3
    assert result['unique_count'] > 0
    assert set(result['class_counts']) == {'person'}
    assert output.stat().st_size > 0

def test_background_video_progress(client):
    import time
    from ultralytics.utils import ASSETS
    frame = cv2.resize(cv2.imread(str(ASSETS/'bus.jpg')), (160,208))
    path = TEST_ROOT/'async.avi'
    writer = cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),5,(160,208))
    writer.write(frame);writer.write(frame);writer.release()
    response=client.post('/api/analyze/video',files={'file':('clip.avi',path.read_bytes())},data={'background':'true','analyzer_type':'human'})
    assert response.status_code == 200, response.text
    job_id=response.json()['job_id']
    for _ in range(100):
        job=client.get(f'/api/analyze/video/jobs/{job_id}').json()
        if job['status'] in {'complete','failed'}:
            break
        time.sleep(.1)
    assert job['status']=='complete', job
    assert job['progress']==100
    assert job['result']['image_width']==160
    assert client.get(job['result']['download_url']).status_code==200

def test_pose_and_webcam_endpoint(client):
    from ultralytics.utils import ASSETS
    response=client.post('/api/analyze/webcam',files={'file':('bus.jpg',(ASSETS/'bus.jpg').read_bytes())},data={'pose_mode':'true'})
    assert response.status_code==200, response.text
    result=response.json()
    assert result['keypoints']
    assert len(result['keypoints'][0])==17
    assert result['model_info']['filename'].endswith('-pose.pt')

def test_rate_limit_and_origin(client):
    r=client.post('/api/analyze/image',headers={'Origin':'https://untrusted.invalid'},files={'file':('x.jpg',b'bad')})
    assert r.status_code==403
    for _ in range(31):
        r=client.post('/api/analyze/image',files={'file':('x.exe',b'bad')})
    assert r.status_code==429

def test_dataset_validation(tmp_path):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'training'))
    from prepare_dataset import prepare
    (tmp_path/'raw/images').mkdir(parents=True)
    (tmp_path/'raw/labels').mkdir(parents=True)
    for i in range(5):
        cv2.imwrite(str(tmp_path/f'raw/images/{i}.png'),np.full((16,16,3),i*20,dtype=np.uint8))
        (tmp_path/f'raw/labels/{i}.txt').write_text('0 0.5 0.5 0.4 0.4')
    result=prepare(tmp_path/'raw',tmp_path/'out',['container'])
    assert result=={'train':3,'val':1,'test':1}
    (tmp_path/'raw/labels/0.txt').write_text('0 0.9 0.9 0.5 0.5')
    with pytest.raises(ValueError,match='Invalid normalized box'):
        prepare(tmp_path/'raw',tmp_path/'other',['container'])

def test_model_lifecycle(client):
    from models.registry import resolve_model_path
    baseline = next(m for m in client.get('/api/models').json()['models'] if m['model_type']=='general' and m['is_default'])
    bad=client.post('/api/models/upload',files={'file':('broken.pt',b'not a checkpoint')},data={'name':'Broken','model_type':'general'})
    assert bad.status_code==400
    weights=Path(resolve_model_path('yolo26n.pt')).read_bytes()
    response=client.post('/api/models/upload',files={'file':('trusted.pt',weights)},data={'name':'Lifecycle test','model_type':'general','version':'test-1','dataset_info':'{"name":"COCO pretrained"}'})
    assert response.status_code==200,response.text
    model_id=response.json()['model_id']
    stored=settings.weights_dir/response.json()['filename']
    try:
        assert stored.exists()
        assert client.patch(f'/api/models/{model_id}',data={'name':'Renamed','confidence_threshold':.65}).status_code==200
        detail=client.get(f'/api/models/{model_id}').json()
        assert detail['name']=='Renamed' and detail['confidence_threshold']==.65
        assert client.delete(f'/api/models/{model_id}').status_code==400
    finally:
        assert client.patch(f"/api/models/{baseline['id']}",data={'is_default':'true'}).status_code==200
        assert client.delete(f'/api/models/{model_id}').status_code==200
    assert not stored.exists()

def test_live_stream_tracking_and_config(client):
    import base64
    from ultralytics.utils import ASSETS
    frame = cv2.resize(cv2.imread(str(ASSETS/'bus.jpg')), (320,416))
    encoded = base64.b64encode(cv2.imencode('.jpg',frame)[1]).decode()
    before = len(client.get('/api/history').json()['items'])
    with client.websocket_connect('/api/analyze/live?mode=human&track=true') as ws:
        assert ws.receive_json()['type']=='ready'
        ws.send_json({'type':'frame','frame':encoded})
        first=ws.receive_json()
        assert first['type']=='detection', first
        assert first['counts']['person']>0
        assert first['unique_count']>0
        assert first['pose_enabled'] is True
        assert all(len(d['keypoints'])==17 for d in first['detections'])
        assert all('pose_observations' in d for d in first['detections'])
        assert all('action_estimates' in d for d in first['detections'])
        assert first['fps']>0
        assert first['annotated_frame'].startswith('data:image/jpeg;base64,')
        ids={d['track_id'] for d in first['detections']}
        ws.send_json({'type':'frame','frame':encoded})
        second=ws.receive_json()
        assert {d['track_id'] for d in second['detections']}==ids
        assert second['unique_count']==first['unique_count']
        ws.send_json({'type':'config','pose':False})
        assert ws.receive_json()['type']=='config_ack'
        ws.send_json({'type':'frame','frame':encoded})
        boxes_only=ws.receive_json()
        assert boxes_only['pose_enabled'] is False
        assert all('keypoints' not in d for d in boxes_only['detections'])
        # Corrupt frames report a recoverable error and the same connection remains usable.
        ws.send_json({'type':'frame','frame':'broken'})
        assert ws.receive_json()['recoverable'] is True
        ws.send_json({'type':'config','mode':'port_monitor','confidence':.5,'track':False})
        assert ws.receive_json()['type']=='config_ack'
        ws.send_json({'type':'frame','frame':encoded})
        port=ws.receive_json()
        assert port['port_summary']['containers'] is None
        assert port['warnings']
        assert port['tracking'] is False
        assert port['unique_count']==0
        assert first['monitoring']['recent_actions']
        ws.send_json({'type':'stop'})
        report=ws.receive_json()
        assert report['type']=='report'
        assert report['report']['partial'] is True
        assert ws.receive_json()['type']=='stopped'
    downloaded=client.get(report['report']['download_url'])
    assert downloaded.status_code==200
    assert 'person' in downloaded.text and 'TIMESTAMPED OBSERVATIONS' in downloaded.text
    assert any(r['id']==report['report']['id'] for r in client.get('/api/reports').json()['reports'])
    assert client.get('/api/reports/invalid/download').status_code==400
    settings.auth_enabled=True
    try:
        assert client.get(report['report']['download_url']).status_code==401
        assert client.get('/api/reports').status_code==401
    finally:
        settings.auth_enabled=False
    assert len(client.get('/api/history').json()['items'])==before

def test_live_binary_fast_frames_and_speed_changes(client, monkeypatch):
    from ultralytics.utils import ASSETS
    from services import live_detector
    frame = cv2.resize(cv2.imread(str(ASSETS/'bus.jpg')), (320,416))
    jpeg = cv2.imencode('.jpg',frame)[1].tobytes()

    # Metadata-only clients must skip the expensive annotation/JPEG return path.
    def unexpected_annotation(*args, **kwargs):
        raise AssertionError('Fast live frames should not render or encode an image')
    monkeypatch.setattr(live_detector, 'draw_detections', unexpected_annotation)
    monkeypatch.setattr(live_detector, 'ndarray_to_base64', unexpected_annotation)
    with client.websocket_connect('/api/analyze/live?mode=human&inference_size=320&annotated=false') as ws:
        ready = ws.receive_json()
        assert ready['type']=='ready' and ready['inference_size']==320
        assert ready['max_fps']==settings.live_max_fps
        ws.send_bytes(jpeg)
        first = ws.receive_json()
        assert first['type']=='detection' and first['counts']['person']>0
        assert first['frame_width']==320 and first['frame_height']==416
        assert first['inference_size']==320 and 'annotated_frame' not in first
        assert all(len(d['keypoints'])==17 for d in first['detections'])
        ids = {d['track_id'] for d in first['detections']}
        ws.send_bytes(jpeg)
        second = ws.receive_json()
        assert {d['track_id'] for d in second['detections']}==ids
        assert second['trajectories']
        assert all(len(p['points'])>=2 for p in second['trajectories'])
        ws.send_json({'type':'config','inference_size':416,'annotated':False,'config_id':7})
        ack = ws.receive_json()
        assert ack['type']=='config_ack' and ack['config_id']==7
        assert ack['inference_size']==416 and ack['tracking'] is True and ack['pose_enabled'] is True
        ws.send_bytes(jpeg)
        balanced = ws.receive_json()
        assert balanced['inference_size']==416 and 'annotated_frame' not in balanced
        assert balanced['unique_count']>=first['unique_count']
        assert any(len(p['points'])>=3 for p in balanced['trajectories'])
        for invalid in (0, 8000, True, '320'):
            ws.send_json({'type':'config','inference_size':invalid})
            assert ws.receive_json()['recoverable'] is True
        ws.send_bytes(b'broken jpeg')
        assert ws.receive_json()['recoverable'] is True
        ws.send_bytes(jpeg)
        assert ws.receive_json()['type']=='detection'

def test_live_binary_limits_and_invalid_size(client):
    from starlette.websockets import WebSocketDisconnect
    from services.live_detector import MAX_FRAME_BYTES
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/analyze/live?inference_size=4096'):
            pass
    with client.websocket_connect('/api/analyze/live?annotated=false') as ws:
        assert ws.receive_json()['type']=='ready'
        ws.send_bytes(b'x'*(MAX_FRAME_BYTES+1))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code==1009

def test_ten_minute_activity_reports(monkeypatch,tmp_path):
    from datetime import datetime
    from services.activity_reports import ActivityReporter, IST
    monkeypatch.setattr(settings,'report_dir',tmp_path)
    tick=[0.]
    reporter=ActivityReporter(clock=lambda:tick[0],wall_clock=datetime(2026,10,1,10,0,tzinfo=IST))
    def observe(x=0,visible=True):
        result={'detections':[{'class':'person','track_id':7,'bbox':[x,0,20,30]}] if visible else [],
                'mode':'general','models':['yolo26n.pt'],'frame_width':640,'frame_height':480}
        reporter.ingest(result)
        return result
    for step in range(10):
        tick[0]=step*.5
        observe(step*12)
    assert any(e['action']=='moving' for e in reporter.events)
    for step in range(10,25):
        tick[0]=step*.5
        observe(108)
    assert any(e['action']=='stationary' for e in reporter.events)
    tick[0]=16
    observe(visible=False)
    assert any('No longer detected' in e['action'] for e in reporter.events)
    tick[0]=599.9
    assert reporter.due() is None
    tick[0]=600
    first=reporter.due()
    assert first['duration_seconds']==600 and first['partial'] is False
    assert first['started_at']=='2026-10-01T10:00:00+05:30'
    assert first['ended_at']=='2026-10-01T10:10:00+05:30'
    text=(tmp_path/first['file_name']).read_text(encoding='utf-8')
    assert 'moving' in text and 'stationary' in text and 'person' in text
    assert reporter.due() is None
    tick[0]=601
    observe()
    tick[0]=1200
    second=reporter.due()
    assert second['sequence']==2 and second['frames_analyzed']==1
    assert second['started_at']==first['ended_at']
    tick[0]=1201
    observe()
    tick[0]=1202
    partial=reporter.flush(partial=True,reason='Detection stopped')
    assert partial['partial'] is True and partial['duration_seconds']==2
    assert len(list(tmp_path.glob('*.txt')))==3

def test_pose_observations_and_report_stability(monkeypatch,tmp_path):
    from services.pose_activity import pose_observations
    from services.activity_reports import ActivityReporter
    points=[[0,0,0] for _ in range(17)]
    points[5]=[100,100,.9];points[11]=[100,200,.9];points[9]=[110,50,.9]
    points[13]=[100,250,.9];points[15]=[150,250,.9]
    assert pose_observations(points)==['left hand above shoulder','left knee bent']
    points[9][2]=.1;points[15][2]=.1
    assert pose_observations(points)==[]
    monkeypatch.setattr(settings,'report_dir',tmp_path)
    tick=[0.]
    reporter=ActivityReporter(clock=lambda:tick[0])
    def frame(labels):
        reporter.ingest({'mode':'human','models':['yolo26n-pose.pt'],'frame_width':640,'frame_height':480,
            'detections':[{'class':'person','track_id':1,'bbox':[0,0,50,100],'pose_observations':labels}]})
    frame(['left hand above shoulder'])
    tick[0]=.3;frame([])
    assert not any(e['action'].startswith('Pose estimate') for e in reporter.events)
    tick[0]=.5;frame(['left hand above shoulder'])
    tick[0]=1.5;frame(['left hand above shoulder'])
    assert sum(e['action'].startswith('Pose estimate') for e in reporter.events)==1
    tick[0]=2;frame(['left hand above shoulder'])
    assert sum(e['action'].startswith('Pose estimate') for e in reporter.events)==1
    report=reporter.flush(partial=True)
    assert 'Pose estimate: left hand above shoulder' in (tmp_path/report['file_name']).read_text(encoding='utf-8')

def test_posture_and_temporal_waving():
    from services.pose_activity import posture_observations, PoseActionEstimator
    points=[[0,0,0] for _ in range(17)]
    for i,xy in {5:(100,100),6:(150,100),11:(100,200),12:(150,200),13:(100,270),14:(150,270),15:(100,340),16:(150,340),9:(100,70)}.items():
        points[i]=[*xy,.95]
    assert posture_observations(points)==['Standing posture (estimate)']
    seated=[p[:] for p in points]
    for i,xy in {13:(170,200),14:(220,200),15:(170,270),16:(220,270)}.items():
        seated[i]=[*xy,.95]
    assert posture_observations(seated)==['Sitting posture (estimate)']
    seated[15][2]=.1
    assert posture_observations(seated)==[]
    tick=[0.]
    estimator=PoseActionEstimator(clock=lambda:tick[0])
    # A stationary raised hand must never produce a wave label.
    for step in range(15):
        tick[0]=step*.1
        assert not any('waving' in s for s in estimator.observe(1,points))
    assert 'Standing posture (estimate)' in estimator.observe(1,points)
    # Repeated wrist reversals followed by stable confirmation create a gesture estimate.
    labels=[]
    for step,x in enumerate([100,140,180,140,100,140,180]*4):
        tick[0]=2+step*.1;points[9][0]=x
        labels += estimator.observe(1,points)
    assert 'Left hand waving (estimate)' in labels
    assert not any('waving' in s for s in estimator.observe(2,points))
    points[9][2]=.1
    tick[0]+=2
    assert not any('waving' in s for s in estimator.observe(1,points))
    assert estimator.observe(None,points)==['Standing posture (estimate)']

def test_live_security_and_validation(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/analyze/live?mode=invalid'):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/analyze/live',headers={'origin':'https://untrusted.invalid'}):
            pass
    settings.auth_enabled=True
    try:
        assert client.post('/api/analyze/live/ticket').status_code==401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/analyze/live'):
                pass
        response=client.post('/api/analyze/live/ticket',auth=(settings.admin_username,settings.admin_password))
        assert response.status_code==200
        ticket=response.json()['ticket']
        with client.websocket_connect(f'/api/analyze/live?ticket={ticket}') as ws:
            assert ws.receive_json()['type']=='ready'
            ws.send_json({'type':'ping'})
            assert ws.receive_json()['type']=='pong'
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f'/api/analyze/live?ticket={ticket}'):
                pass
    finally:
        settings.auth_enabled=False

def test_live_container_weights_required(client):
    with client.websocket_connect('/api/analyze/live?mode=container') as ws:
        error=ws.receive_json()
        assert error['recoverable'] is False
        assert 'container model not installed' in error['error']
