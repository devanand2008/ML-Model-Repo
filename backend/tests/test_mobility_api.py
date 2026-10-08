"""Connected GPS, bus-camera, safety review, geofencing and role boundaries."""
import asyncio
import base64
from datetime import timedelta
import os
import sys
import tempfile
import time
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="transit-mobility-test-"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///" + (_root / "mobility.db").as_posix())
os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from config import settings
from database import AsyncSessionLocal
from main import app
from transit.vision import persist_observation
from transit.mobility import latest_location, utc_now, SafetyFrameTracker
from transit.models import TransitOperatorAction
from sqlalchemy import select


def auth(username=None, password=None):
    text = f"{username or settings.admin_username}:{password or settings.admin_password}"
    return {"Authorization": "Basic " + base64.b64encode(text.encode()).decode()}


def test_shared_ml_feed_monitor_and_private_models(monkeypatch):
    from api import mobility
    camera={'id':'SIGNAL_TEST','name':'Signal test','latitude':11.67,'longitude':78.145,
        'coordinate_source':'operator_configured','prediction':{'available':False},
        'observation':{'fresh':True,'live':True,'source':'REAL_MODEL_DETECTION','score':90,
                       'category':'SEVERE','timestamp':'2026-10-08T12:00:00Z'}}
    async def cameras(*args):return [camera]
    monkeypatch.setattr(mobility,'nearby_cameras',cameras)
    with TestClient(app) as client:
        feed=client.get('/api/public/traffic/feed')
        assert feed.status_code==200
        assert feed.json()['alerts'][0]['camera_id']=='SIGNAL_TEST'
        assert 'detections' not in str(feed.json())
        assert client.get('/api/ml/overview').status_code==401
        overview=client.get('/api/ml/overview',headers=auth())
        assert overview.status_code==200,overview.text
        assert overview.json()['use_cases']==['road_traffic','bus_interior']
        assert client.put('/api/traffic/cameras/CAM01/location',json={'latitude':11.67,'longitude':78.145}).status_code==401
        located=client.put('/api/traffic/cameras/CAM01/location',headers=auth(),json={'latitude':11.67,'longitude':78.145})
        assert located.status_code==200,located.text
        assert located.json()['coordinate_source']=='operator_configured'
        assert client.put('/api/traffic/cameras/BUS_CAM_001/location',headers=auth(),json={'latitude':11.67,'longitude':78.145}).status_code==422
        body={'routes':[{'id':'chosen','geometry':[[78.14,11.67],[78.15,11.67]],
            'distance_km':1,'base_duration_minutes':4}], 'selected_route_id':'chosen'}
        monitor=client.post('/api/public/navigation/monitor',json=body)
        assert monitor.status_code==200,monitor.text
        assert monitor.json()['route_alerts']
        assert monitor.json()['selected_route_id']=='chosen'
        invalid={**body,'routes':[{**body['routes'][0],'geometry':[[999,11.67],[78.15,11.67]]}]}
        assert client.post('/api/public/navigation/monitor',json=invalid).status_code==422
        camera['observation']['live']=False
        assert client.get('/api/public/traffic/feed').json()['alerts']==[]


def test_public_privacy_and_gps_freshness():
    with TestClient(app) as client:
        public = client.get("/api/public/buses")
        assert public.status_code == 200
        assert public.json()["buses"]
        assert client.get("/api/alerts").status_code == 401
        assert client.get("/api/mobility/cameras").status_code == 401
        assert client.get("/api/vision/results/unknown").status_code in {401, 404}
        assert client.post("/api/buses/BUS005/location", json={"latitude": 11.6757,
            "longitude": 78.1402, "speed_kmh": 12}).status_code == 401
        updated = client.post("/api/buses/BUS005/location", headers=auth(), json={
            "latitude": 11.6757, "longitude": 78.1402, "accuracy_m": 8,
            "speed_kmh": 12, "source": "demo_simulation"})
        assert updated.status_code == 200, updated.text
        bus = client.get("/api/public/buses/BUS005").json()
        assert bus["tracking_status"] == "live"
        assert bus["location"]["source"] == "demo_simulation"
        assert "evidence" not in bus
        nearby = client.get("/api/navigation/nearby-buses?latitude=11.6757&longitude=78.1402&radius_km=1")
        assert nearby.status_code == 200
        assert any(item["id"] == "BUS005" for item in nearby.json()["buses"])
        cameras = client.get("/api/public/traffic/nearby?latitude=11.6757&longitude=78.1402&radius_km=5")
        assert cameras.status_code == 200
        assert all(camera["distance_km"] <= 5 for camera in cameras.json()["cameras"])
        assert all(camera["coordinate_source"] for camera in cameras.json()["cameras"])
        async def age_gps():
            async with AsyncSessionLocal() as db:
                sample = await latest_location(db, "BUS005")
                sample.timestamp = utc_now() - timedelta(minutes=3)
                await db.commit()
        asyncio.run(age_gps())
        assert client.get("/api/public/buses/BUS005").json()["tracking_status"] == "stale"
        assert all(item["id"] != "BUS005" for item in client.get(
            "/api/navigation/nearby-buses?latitude=11.6757&longitude=78.1402&radius_km=1").json()["buses"])


def test_role_camera_bus_safety_and_review():
    with TestClient(app) as client:
        created = client.post("/api/accounts", headers=auth(), json={"username": "driver_test",
            "password": "safe-test-password", "role": "driver", "bus_id": "BUS005"})
        assert created.status_code in {200, 409}, created.text
        driver = auth("driver_test", "safe-test-password")
        assert client.get("/api/mobility/session", headers=driver).json()["role"] == "driver"
        cameras = client.get('/api/mobility/cameras',headers=driver)
        assert cameras.status_code==200,cameras.text
        assert all(c['bus_id']=='BUS005' for c in cameras.json()['cameras'])
        speed = client.get('/api/traffic/speed',headers=driver)
        assert speed.status_code==200,speed.text
        assert any(c['id']=='BUS_ROAD_001' for c in speed.json()['cameras'])
        assert all(c['bus_id']=='BUS005' for c in speed.json()['cameras'])
        office_created = client.post("/api/accounts", headers=auth(), json={
            "username": "office_test", "password": "head-office-password", "role": "head_office"})
        assert office_created.status_code in {200, 409}, office_created.text
        office = auth("office_test", "head-office-password")
        assert client.get("/api/session", headers=office).status_code == 200
        assert client.get("/api/dashboard/summary", headers=office).status_code == 200
        assert client.post("/api/cameras/register", headers=office, json={
            "id": "NOT_ALLOWED", "name": "Denied camera", "role": "road_traffic"}).status_code == 403
        assert client.post("/api/buses/BUS002/location", headers=driver, json={
            "latitude": 11.67, "longitude": 78.14}).status_code == 403
        assert client.get("/api/alerts", headers=driver).status_code == 403
        camera = client.post("/api/cameras/register", headers=auth(), json={
            "id": "SAFE_TEST", "name": "Safety test interior", "role": "bus_interior",
            "bus_id": "BUS005", "stop_id": "S02", "corridor_id": "C02"})
        assert camera.status_code in {200, 409}, camera.text
        zone = client.patch("/api/mobility/cameras/SAFE_TEST", headers=auth(), json={
            "safety_zone": [0, 0, .5, 1], "door_open": False})
        assert zone.status_code == 200
        assert client.post("/api/buses/BUS005/location", headers=driver, json={
            "latitude": 11.6757, "longitude": 78.1402, "speed_kmh": 14,
            "source": "browser_geolocation"}).status_code == 200
        detection = {"class": "person", "confidence": .9, "bbox": [20, 20, 80, 150]}
        tracker = SafetyFrameTracker()
        async def observe():
            async with AsyncSessionLocal() as db:
                return await persist_observation(db, {"detections": [detection],
                    "safety_consecutive_frames": tracker.update([detection],320,240,[0,0,.5,1]),
                    "image_width": 320, "image_height": 240}, "SAFE_TEST", "test-camera", "browser_camera")
        for _ in range(3):
            assert asyncio.run(observe())["bus_observation"]["safety_event_id"] is None
        assert client.get("/api/alerts", headers=auth()).json()["alerts"] == []
        assert client.post("/api/buses/BUS005/door", headers=driver, json={"open": True}).status_code == 200
        first = asyncio.run(observe())
        assert first["bus_observation"]["safety_event_id"]
        public = client.get("/api/public/buses/BUS005").json()
        assert public["crowding"]["visible_people"] == 1
        assert public["crowding"]["coverage"] == "partial"
        assert public["public_safety_status"] == "Safety report under operator review"
        assert "detections" not in public["crowding"]
        alert_id = first["bus_observation"]["safety_event_id"]
        assert client.post(f"/api/alerts/{alert_id}/acknowledge", headers=auth(), json={"note": "Reviewing source"}).status_code == 200
        resolved = client.post(f"/api/alerts/{alert_id}/false-positive", headers=auth(), json={"note": "Demo signal"})
        assert resolved.status_code == 200
        detail = client.get(f"/api/alerts/{alert_id}", headers=auth()).json()
        assert [action["action"] for action in detail["actions"]] == ["acknowledge", "false-positive"]
        assert client.get("/api/exports/alerts", headers=auth()).status_code == 200
        assert client.get('/api/accounts',headers=driver).status_code == 403
        accounts = client.get('/api/accounts',headers=auth()).json()['accounts']
        assert any(item['username']=='driver_test' for item in accounts)
        assert all('password_hash' not in item for item in accounts)
        assert client.patch('/api/accounts/driver_test',headers=auth(),json={'active':False}).status_code == 200
        assert client.get('/api/mobility/session',headers=driver).status_code == 401
        assert client.patch('/api/accounts/driver_test',headers=auth(),json={'active':True}).status_code == 200


def test_live_safety_tracking_resets_for_absence_identity_and_gap():
    frame = SafetyFrameTracker()
    zone = [0, 0, .5, 1]
    person = {"class": "person", "bbox": [20,20,80,150], "track_id": 10}
    now = utc_now()
    assert frame.update([person],320,240,zone,now) == 1
    assert frame.update([person],320,240,zone,now + timedelta(seconds=1)) == 2
    assert frame.update([],320,240,zone,now + timedelta(seconds=2)) == 0
    assert frame.update([person],320,240,zone,now + timedelta(seconds=3)) == 1
    assert frame.update([{**person,"track_id":11}],320,240,zone,now + timedelta(seconds=4)) == 1
    assert frame.update([{**person,"track_id":11}],320,240,zone,now + timedelta(seconds=10)) == 1


def test_interior_uses_existing_human_model_and_partial_crowding():
    with TestClient(app) as client:
        response = client.post('/api/vision/samples/bus-image/analyze?camera_id=BUS_CAM_001',headers=auth())
        assert response.status_code == 200,response.text
        payload = response.json()
        assert payload['model_info']['type'] == 'human'
        assert set(payload['counts']) == {'person'}
        assert payload['counts']['person'] > 0
        assert payload['supported_classes'] == ['person']
        observation = client.get('/api/public/buses/BUS005').json()['crowding']
        assert observation['visible_people'] == payload['counts']['person']
        assert observation['load_factor'] is None
        assert observation['live'] is False and observation['source_type']=='image'
        assert payload['observation']['bus_observation']['safety_event_id'] is None
        assert client.patch('/api/settings',headers=auth(),json={
            'crowd_visible_thresholds':{'moderate':5,'high':4,'critical':9}}).status_code == 422


def test_websocket_frames_generate_alert_and_stale_door_does_not(monkeypatch):
    from api import live
    class FrameDetector:
        def __init__(self,mode,files,track,pose):
            self.pose = pose
            self.warnings = []
        def process(self,*args):
            return {'type':'detection','mode':'human','models':['test-frame-adapter'],
                'detections':[{'class':'person','confidence':.9,'bbox':[20,20,80,150],'track_id':1}],
                'counts':{'person':1},'total_objects':1,'frame_width':320,'frame_height':240,
                'tracking':True,'pose_enabled':False}
    monkeypatch.setattr(live,'LiveDetector',FrameDetector)
    with TestClient(app) as client:
        for camera_id in ('WS_SAFE','WS_STALE'):
            response = client.post('/api/cameras/register',headers=auth(),json={
                'id':camera_id,'name':camera_id+' interior','role':'bus_interior','bus_id':'BUS005'})
            assert response.status_code in {200,409},response.text
            assert client.patch('/api/mobility/cameras/'+camera_id,headers=auth(),json={
                'safety_zone':[0,0,.5,1]}).status_code == 200
        assert client.post('/api/buses/BUS005/location',headers=auth(),json={
            'latitude':11.67,'longitude':78.14,'speed_kmh':18,'source':'demo_simulation'}).status_code == 200
        assert client.post('/api/buses/BUS005/door',headers=auth(),json={'open':True}).status_code == 200
        ticket = client.post('/api/analyze/live/ticket',headers=auth()).json()['ticket']
        with client.websocket_connect('/api/analyze/live?mode=human&pose=false&camera_id=WS_SAFE&ticket='+ticket) as ws:
            assert ws.receive_json()['type'] == 'ready'
            for _ in range(3):
                ws.send_bytes(b'test frame')
                assert ws.receive_json()['type'] == 'detection'
            time.sleep(1.05)
            ws.send_bytes(b'test frame')
            output = ws.receive_json()
            assert output['transit_observation']['bus_observation']['safety_event_id']
        async def expire_door():
            async with AsyncSessionLocal() as db:
                actions = (await db.execute(select(TransitOperatorAction).where(
                    TransitOperatorAction.action=='door_state'))).scalars().all()
                for item in actions:
                    item.timestamp = utc_now() - timedelta(minutes=6)
                await db.commit()
        asyncio.run(expire_door())
        ticket = client.post('/api/analyze/live/ticket',headers=auth()).json()['ticket']
        with client.websocket_connect('/api/analyze/live?mode=human&pose=false&camera_id=WS_STALE&ticket='+ticket) as ws:
            assert ws.receive_json()['type'] == 'ready'
            for _ in range(3):
                ws.send_bytes(b'test frame')
                assert ws.receive_json()['type'] == 'detection'
            time.sleep(1.05)
            ws.send_bytes(b'test frame')
            output = ws.receive_json()
            assert output['transit_observation']['bus_observation']['safety_event_id'] is None


def test_bus_arrival_uses_declared_direction_and_provider_legs(monkeypatch):
    from transit import routing
    async def provider(stops):
        points = [[s['longitude'],s['latitude']] for s in stops]
        return {'code':'Ok','waypoints':[{'location':point} for point in points],
                'routes':[{'geometry':{'coordinates':points},'legs':[{'duration':60} for _ in stops[1:]]}]}
    monkeypatch.setattr(routing,'service_road_route',provider)
    with TestClient(app) as client:
        assert client.post('/api/buses/BUS005/session',headers=auth(),json={
            'direction':'outbound','active':True,'source':'demo_simulation'}).status_code == 200
        assert client.post('/api/buses/BUS005/location',headers=auth(),json={
            'latitude':11.6757,'longitude':78.1402,'accuracy_m':5,'source':'demo_simulation'}).status_code == 200
        estimate = client.get('/api/public/buses/BUS005/arrival?stop_id=S04')
        assert estimate.status_code == 200,estimate.text
        body = estimate.json()
        assert body['available'] is True
        assert body['estimated_minutes'] == 2
        assert body['next_stop']['id'] == 'S01'
        assert body['demo'] is True
        assert body['source'] == 'OSRM_ROAD_PROFILE_ESTIMATE'
        assert client.get('/api/public/buses/BUS005/arrival?stop_id=S12').status_code == 422
        assert client.post('/api/buses/BUS005/session',headers=auth(),json={
            'direction':'outbound','active':False}).status_code == 200
        assert client.get('/api/public/buses/BUS005/arrival').json()['available'] is False


def test_critical_crowding_requires_repeated_live_observations():
    with TestClient(app) as client:
        response=client.post('/api/cameras/register',headers=auth(),json={
            'id':'CROWD_TEST','name':'Crowding rule test','role':'bus_interior','bus_id':'BUS005'})
        assert response.status_code in {200,409}
        response=client.patch('/api/settings',headers=auth(),json={
            'crowd_visible_thresholds':{'moderate':1,'high':2,'critical':3}})
        assert response.status_code == 200,response.text
        frame={'image_width':320,'image_height':240,'detections':[
            {'class':'person','confidence':.9,'bbox':[x,20,30,100]} for x in [20,80,160]]}
        async def observe():
            async with AsyncSessionLocal() as db:
                return await persist_observation(db,frame,'CROWD_TEST','crowd-test','browser_camera')
        try:
            for _ in range(2):
                assert asyncio.run(observe())['bus_observation']['safety_event_id'] is None
            result=asyncio.run(observe())
            alert_id=result['bus_observation']['safety_event_id']
            assert alert_id
            event=client.get('/api/alerts/'+alert_id,headers=auth()).json()
            assert event['category']=='critical_visible_crowding_estimate'
            assert event['evidence']['coverage']=='partial'
            assert event['evidence']['sampled_observations']==3
        finally:
            client.patch('/api/settings',headers=auth(),json={
                'crowd_visible_thresholds':{'moderate':6,'high':15,'critical':30}})


def test_recorded_traffic_requires_explicit_demo_comparison(monkeypatch):
    from api import mobility
    async def cameras(*args):
        return [{'id':'CAM01','latitude':11.67,'longitude':78.14,'coordinate_source':'operator_configured',
            'observation':{'fresh':True,'live':False,'source':'REAL_MODEL_DETECTION',
                'observation_type':'recorded_detection','score':80}}]
    monkeypatch.setattr(mobility,'nearby_cameras',cameras)
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'code':'Ok','routes':[{'distance':2000,'duration':600,
            'geometry':{'coordinates':[[78.14,11.67],[78.15,11.68]]}}]}
    class Provider:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,*args,**kwargs):return Response()
    monkeypatch.setattr(mobility.httpx,'AsyncClient',Provider)
    with TestClient(app) as client:
        body={'origin':{'latitude':11.67,'longitude':78.14},'destination':{'latitude':11.68,'longitude':78.15}}
        live=client.post('/api/public/navigation/routes',json=body).json()['routes'][0]
        assert live['observed_camera_count']==0
        assert live['comparison_minutes']==live['base_duration_minutes']
        demo=client.post('/api/public/navigation/routes',json={**body,'use_recorded_demo':True}).json()['routes'][0]
        assert demo['observed_camera_count']==0
        assert demo['recorded_demo_camera_count']==1
        assert demo['comparison_minutes']>demo['base_duration_minutes']


def test_moving_bus_speed_is_fused_geolocated_and_reroutes_following_journeys(monkeypatch):
    from api import live, mobility as api_mobility
    from transit import mobility
    from transit.models import TransitTrafficObservation, TransitDetectionEvent, TransitBusLocation
    clock=[utc_now()]
    monkeypatch.setattr(mobility,'utc_now',lambda:clock[0])
    monkeypatch.setattr(api_mobility,'utc_now',lambda:clock[0])
    with TestClient(app) as client:
        invalid={'id':'SPEED_TEST','name':'Speed test','role':'bus_road'}
        assert client.post('/api/cameras/register',headers=auth(),json=invalid).status_code==422
        body={**invalid,'bus_id':'BUS005'}
        assert client.post('/api/cameras/register',headers=auth(),json={**body,'latitude':11.67,'longitude':78.14}).status_code==422
        assert client.post('/api/cameras/register',headers=auth(),json=body).status_code==200
        assert client.get('/api/traffic/speed').status_code==401
        live._active_camera_sessions.add('SPEED_TEST')
        try:
            async def frames():
                base=clock[0]
                async with AsyncSessionLocal() as db:
                    for i in range(10):
                        clock[0]=base+timedelta(seconds=i)
                        if i%5==0:
                            db.add(TransitBusLocation(id='speed-fix-'+str(i),bus_id='BUS005',timestamp=clock[0],
                                latitude=11.67,longitude=78.145,accuracy_m=5,speed_kmh=4,source='browser_geolocation'))
                            await db.commit()
                        result={'frame_width':320,'frame_height':240,'detections':[
                            {'class':kind,'confidence':.9,'bbox':[j*50,40,40,80],'track_id':j} for j,kind in enumerate(['bus','car','car'])]}
                        observed=await persist_observation(db,result,'SPEED_TEST','speed-session','browser_camera')
                        event=await db.get(TransitDetectionEvent,observed['id']);event.timestamp=clock[0]
                        traffic=(await db.execute(select(TransitTrafficObservation).where(TransitTrafficObservation.detection_event_id==event.id))).scalar_one()
                        traffic.timestamp=clock[0];await db.commit()
                    assert observed['speed_observation']['suspected_queue']
                    assert observed['bus_speed_kmh']==4
            asyncio.run(frames())
            dashboard=client.get('/api/traffic/speed',headers=auth()).json()
            row=next(c for c in dashboard['cameras'] if c['id']=='SPEED_TEST')
            assert row['suspected_queue'] and row['vehicle_count']==3
            feed=client.get('/api/public/traffic/feed').json()
            report=next(a for a in feed['alerts'] if a['camera_id']=='SPEED_TEST')
            assert report['reporting_bus_id']=='BUS005' and report['latitude']==11.67
            route_body={'routes':[{'id':'busy','geometry':[[78.14,11.67],[78.15,11.67]],'distance_km':1,'base_duration_minutes':4},
                {'id':'other','geometry':[[78.14,11.7],[78.15,11.7]],'distance_km':3,'base_duration_minutes':6}],
                'selected_route_id':'busy','goal':'lowest_observed_traffic'}
            monitored=client.post('/api/public/navigation/monitor',json=route_body).json()
            assert monitored['recommended_route_id']=='other'
            assert any('possible queue' in a['message'] for a in monitored['route_alerts'])
            clock[0]+=timedelta(seconds=21)
            assert not any(c['id']=='SPEED_TEST' for c in client.get('/api/public/traffic/feed').json()['cameras'])
            row=next(c for c in client.get('/api/traffic/speed',headers=auth()).json()['cameras'] if c['id']=='SPEED_TEST')
            assert not row['gps_speed']['available'] and not row['suspected_queue']
        finally:
            live._active_camera_sessions.discard('SPEED_TEST')


def test_moving_road_websocket_uses_general_detector_and_exposes_speed_evidence(monkeypatch):
    from api import live
    class Detector:
        def __init__(self,mode,*args):
            assert mode=='general'
            self.pose=False;self.warnings=[]
        def process(self,*args):
            return {'type':'detection','mode':'general','detections':[
                {'class':'bus','confidence':.9,'bbox':[10,10,80,80],'track_id':1}],
                'counts':{'bus':1},'total_objects':1,'frame_width':320,'frame_height':240,'tracking':True}
    monkeypatch.setattr(live,'LiveDetector',Detector)
    with TestClient(app) as client:
        registered=client.post('/api/cameras/register',headers=auth(),json={
            'id':'SPEED_WS','name':'Road websocket test','role':'bus_road','bus_id':'BUS005'})
        assert registered.status_code==200
        ticket=client.post('/api/analyze/live/ticket',headers=auth()).json()['ticket']
        with client.websocket_connect('/api/analyze/live?mode=human&camera_id=SPEED_WS&ticket='+ticket) as ws:
            assert 'requires general' in ws.receive_json()['error']
        ticket=client.post('/api/analyze/live/ticket',headers=auth()).json()['ticket']
        with client.websocket_connect('/api/analyze/live?mode=general&pose=false&camera_id=SPEED_WS&ticket='+ticket) as ws:
            assert ws.receive_json()['type']=='ready'
            ws.send_bytes(b'fixture frame')
            result=ws.receive_json()
            assert result['transit_observation']['vehicle_count']==1
            assert 'speed_observation' in result['transit_observation']
            assert result['transit_observation']['bus_observation'] is None


def test_rag_explains_verified_route_context_refreshes_evidence_and_enforces_bus_roles(monkeypatch):
    from api import mobility
    from transit import route_rag
    def generation(question,documents):
        # Test adapter: model generation is checked separately with installed weights.
        return {'answer':documents[0]['text'],'answer_source_id':documents[0]['id'],
                'generation_mode':'test_adapter','model':None}
    monkeypatch.setattr(route_rag,'generate',generation)
    live=[True]
    async def cameras(*args):
        return [dict(id='RAG_SIGNAL',name='Signal',latitude=11.67,longitude=78.145,coordinate_source='operator_configured',
            observation=dict(fresh=live[0],live=live[0],source='REAL_MODEL_DETECTION',score=90,category='SEVERE',timestamp='2026-10-09T12:00:00Z'))]
    monkeypatch.setattr(mobility,'nearby_cameras',cameras)
    monkeypatch.setattr(route_rag,'nearby_cameras',cameras)
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'code':'Ok','routes':[
            {'distance':2000,'duration':240,'geometry':{'coordinates':[[78.14,11.67],[78.15,11.67]]}},
            {'distance':3000,'duration':360,'geometry':{'coordinates':[[78.14,11.69],[78.15,11.69]]}}]}
    class Provider:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,*args,**kwargs):
            assert kwargs['params']['alternatives']=='3'
            return Response()
    monkeypatch.setattr(mobility.httpx,'AsyncClient',Provider)
    with TestClient(app) as client:
        planned=client.post('/api/public/navigation/routes',json={'origin':{'latitude':11.67,'longitude':78.14},
            'destination':{'latitude':11.69,'longitude':78.15},'goal':'lowest_observed_traffic'})
        assert planned.status_code==200,planned.text
        paths=planned.json();token=paths['route_context_id'];chosen=paths['recommended_route_id']
        answer=client.post('/api/public/rag/ask',json={'question':'Explain traffic speed and alternative route','route_context_id':token})
        assert answer.status_code==200,answer.text
        data=answer.json()
        assert data['route_advice']['recommended_route_id']==chosen
        assert any(d['id']=='live-RAG_SIGNAL' for d in data['sources'])
        assert any(d['id']=='current-recommendation' for d in data['sources'])
        assert data['answer']==next(d['text'] for d in data['sources'] if d['id']==data['answer_source_id'])
        assert data['actions_taken']==[]
        # Client distance tampering cannot alter the server's provider path context.
        fake=[{**r,'distance_km':999,'base_duration_minutes':999} for r in paths['routes']]
        monitored=client.post('/api/public/navigation/monitor',json={'routes':fake,'route_context_id':token,'goal':'shortest'})
        assert monitored.status_code==200
        assert monitored.json()['routes'][0]['distance_km']==2
        assert monitored.json()['goal']=='lowest_observed_traffic'
        live[0]=False
        refreshed=client.post('/api/public/rag/ask',json={'question':'Explain this traffic route','route_context_id':token}).json()
        assert not any(d['id']=='live-RAG_SIGNAL' for d in refreshed['sources'])
        assert refreshed['route_advice']['recommended_route_id']==paths['routes'][0]['id']
        assert client.post('/api/public/rag/ask',json={'question':'Explain','route_context_id':'expired'}).status_code==409
        assert client.post('/api/public/rag/ask',json={'question':'Explain','bus_id':'BUS005'}).status_code==422
        assert client.post('/api/rag/bus-advice',json={'question':'Can the bus change route?','bus_id':'BUS005'}).status_code==401
        private=client.post('/api/rag/bus-advice',headers=auth(),json={'question':'Can the bus change route?','bus_id':'BUS005','route_context_id':token})
        assert private.status_code==200,private.text
        assert private.json()['operator_review_required']
        assert {'policy-bus','bus-service'}<={s['id'] for s in private.json()['sources']}
        client.post('/api/accounts',headers=auth(),json={'username':'rag_driver','password':'rag-driver-password','role':'driver','bus_id':'BUS005'})
        assert client.post('/api/rag/bus-advice',headers=auth('rag_driver','rag-driver-password'),json={'question':'Bus change route?','bus_id':'BUS002'}).status_code==403
