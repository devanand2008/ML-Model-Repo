"""TransitOpt 2.0 passenger, driver and head-office workflows."""
from __future__ import annotations

import asyncio
import csv
import io
from datetime import timedelta
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from config import settings
from transit.accounts import actor, allowed, password_hash
from transit.mobility import (CAMERA_FRESH_SECONDS, bus_summary, haversine_km,
                              iso, latest_location, latest_occupancy,
                              nearby_cameras, utc_now, camera_runtime)
from transit.models import (TransitAccount, TransitBusLocation, TransitBusOccupancy,
    TransitBusProfile, TransitBusSession, TransitCamera, TransitCameraSetup, TransitGeoStop,
    TransitNavigationRequest, TransitOperatorAction, TransitSafetyAction, TransitSafetyEvent,
    TransitRoute, TransitStop, TransitTrafficObservation, TransitVehicle)

public = APIRouter(prefix="/public", tags=["Passenger and public map"])
private = APIRouter(tags=["Mobility operations"])
OSRM_BASE = settings.osrm_base_url.rstrip("/")
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_geocode_lock = asyncio.Lock()
_geocode_last = 0.0


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: GeoPoint
    destination: GeoPoint
    selected_route_id: str | None = None
    goal: str = Field("fastest", pattern="^(fastest|lowest_observed_traffic|shortest)$")
    save: bool = False
    use_recorded_demo: bool = False


class MonitoredRoute(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    geometry: list[list[float]] = Field(min_length=2, max_length=10000)
    distance_km: float = Field(ge=0, le=50000)
    base_duration_minutes: float = Field(ge=0, le=100000)

    @model_validator(mode='after')
    def coordinates(self):
        if any(len(p)!=2 or not -180<=p[0]<=180 or not -90<=p[1]<=90 for p in self.geometry):
            raise ValueError('Each route point must be [longitude,latitude] in geographic bounds')
        return self


class MonitorRequest(BaseModel):
    routes: list[MonitoredRoute] = Field(min_length=1, max_length=4)
    selected_route_id: str | None = Field(None, max_length=64)
    goal: str = Field('fastest', pattern='^(fastest|lowest_observed_traffic|shortest)$')
    use_recorded_demo: bool = False
    route_context_id: str | None = Field(None,max_length=64)

    @model_validator(mode='after')
    def distinct(self):
        if len({r.id for r in self.routes}) != len(self.routes):
            raise ValueError('Route IDs must be unique')
        return self


class LocationRequest(GeoPoint):
    accuracy_m: float | None = Field(None, ge=0, le=100000)
    heading_deg: float | None = Field(None, ge=0, lt=360)
    speed_kmh: float | None = Field(None, ge=0, le=200)
    source: str = Field("browser_geolocation", pattern="^(browser_geolocation|gps_device|demo_simulation)$")


class BusRegistration(BaseModel):
    bus_id: str = Field(pattern=r"^BUS[0-9]{3}$")
    registration_number: str = Field(min_length=5, max_length=32, pattern=r"^[A-Z0-9 -]+$")
    route_id: str | None = None
    capacity: int = Field(ge=1, le=150)
    operator_name: str | None = Field(None, max_length=120)
    gps_device_id: str | None = Field(None, max_length=100)
    coverage: str = Field("partial", pattern="^(partial|full_verified)$")


class CameraRegistration(BaseModel):
    id: str = Field(min_length=3, max_length=16, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=3, max_length=120)
    role: str = Field(pattern="^(bus_interior|road_traffic|bus_road)$")
    source_type: str = Field("browser_camera_or_upload", pattern="^(browser_camera_or_upload|authorized_ip_camera|recorded_demo)$")
    bus_id: str | None = None
    stop_id: str = "S02"
    corridor_id: str = "C02"
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    coordinate_source: str = Field("operator_configured", max_length=40)

    @model_validator(mode="after")
    def association(self):
        if self.role in {"bus_interior", "bus_road"} and not self.bus_id:
            raise ValueError("A bus camera requires a registered bus")
        if self.role == 'bus_road' and (self.latitude is not None or self.longitude is not None):
            raise ValueError('Moving bus cameras use synchronized bus GPS, not a fixed camera pin')
        if self.role == "road_traffic" and self.bus_id:
            raise ValueError("A road camera cannot be assigned to a bus")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Camera latitude and longitude must both be supplied")
        return self


class CameraSafetyConfig(BaseModel):
    safety_zone: list[float] | None = None
    door_open: bool | None = None

    @model_validator(mode="after")
    def zone_valid(self):
        z = self.safety_zone
        if z is not None and (len(z) != 4 or any(not 0 <= v <= 1 for v in z)
                              or z[2] <= 0 or z[3] <= 0 or z[0] + z[2] > 1 or z[1] + z[3] > 1):
            raise ValueError("Safety zone must be normalized [x,y,width,height] within the frame")
        return self


class ReviewRequest(BaseModel):
    note: str = Field("", max_length=1000)


class DoorStateRequest(BaseModel):
    open: bool


class BusSessionRequest(BaseModel):
    direction: str = Field("outbound",pattern="^(outbound|inbound)$")
    active: bool = True
    source: str = Field("driver_device",pattern="^(driver_device|demo_simulation)$")


class AccountRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)
    role: str = Field(pattern="^(driver|head_office|admin)$")
    bus_id: str | None = None


class AccountUpdate(BaseModel):
    active: bool | None = None
    password: str | None = Field(None,min_length=12,max_length=128)


def camera_payload(camera: TransitCamera, setup: TransitCameraSetup | None) -> dict:
    return {"id": camera.id, "name": camera.name, "role": setup.role if setup else "unconfigured",
        "bus_id": setup.bus_id if setup else None, "stop_id": camera.stop_id,
        "corridor_id": camera.corridor_id, "source_type": camera.source_type,
        "status": camera.status, "latitude": setup.latitude if setup else None,
        "longitude": setup.longitude if setup else None,
        "coordinate_source": setup.coordinate_source if setup else "unconfigured",
        "safety_zone": setup.safety_zone if setup else None,
        "door_open": setup.door_open if setup else None,
        "roi": camera.roi}


@private.get("/mobility/session")
async def mobility_session(user=Depends(actor)):
    return user


@private.post("/accounts")
async def create_account(body: AccountRequest, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin"})
    if body.bus_id and not await db.get(TransitVehicle, body.bus_id):
        raise HTTPException(404, "Bus not found")
    if body.role == "driver" and not body.bus_id:
        raise HTTPException(422, "Driver account requires a bus assignment")
    if body.username == user["username"] or await db.get(TransitAccount, body.username):
        raise HTTPException(409, "Account already exists")
    db.add(TransitAccount(username=body.username, password_hash=password_hash(body.password),
                          role=body.role, bus_id=body.bus_id, active=True))
    db.add(TransitOperatorAction(id=uuid4().hex,action='account_create',operator=user['username'],timestamp=utc_now(),
        payload={'username':body.username,'role':body.role,'bus_id':body.bus_id}))
    await db.commit()
    return {"username": body.username, "role": body.role, "bus_id": body.bus_id, "active": True}


@private.get('/accounts')
async def accounts(db:AsyncSession=Depends(get_db),user=Depends(actor)):
    allowed(user,{'admin'})
    items=(await db.execute(select(TransitAccount).order_by(TransitAccount.username))).scalars()
    return {'accounts':[{'username':row.username,'role':row.role,'bus_id':row.bus_id,'active':row.active} for row in items]}


@private.patch('/accounts/{username}')
async def update_account(username:str,body:AccountUpdate,db:AsyncSession=Depends(get_db),user=Depends(actor)):
    allowed(user,{'admin'})
    if username==user['username']:
        raise HTTPException(409,'Use environment configuration to change the active administrator account')
    row=await db.get(TransitAccount,username)
    if row is None:
        raise HTTPException(404,'Account not found')
    if body.active is not None:
        row.active=body.active
    if body.password is not None:
        row.password_hash=password_hash(body.password)
    db.add(TransitOperatorAction(id=uuid4().hex,action='account_update',operator=user['username'],timestamp=utc_now(),
        payload={'username':username,'active':row.active,'password_changed':body.password is not None}))
    await db.commit()
    return {'username':row.username,'role':row.role,'bus_id':row.bus_id,'active':row.active}


@private.post("/buses/register")
async def register_bus(body: BusRegistration, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin"})
    vehicle = await db.get(TransitVehicle, body.bus_id)
    if vehicle is None:
        raise HTTPException(404, "Bus ID is not part of the configured fleet")
    if body.route_id is not None and body.route_id != vehicle.route_id:
        raise HTTPException(409, "Route assignments are changed through approved fleet plans")
    profile = await db.get(TransitBusProfile, body.bus_id)
    if profile is None:
        profile = TransitBusProfile(bus_id=body.bus_id, registration_number=body.registration_number)
        db.add(profile)
    profile.registration_number = body.registration_number
    profile.operator_name = body.operator_name
    profile.gps_device_id = body.gps_device_id
    profile.coverage = body.coverage
    profile.demo = False
    vehicle.capacity = body.capacity
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, "Registration number must be unique")
    return await bus_summary(db, vehicle)


@public.get("/buses")
async def public_buses(route_id: str | None = None, q: str | None = Query(None, max_length=100),
                       db: AsyncSession = Depends(get_db)):
    vehicles = (await db.execute(select(TransitVehicle).order_by(TransitVehicle.id))).scalars().all()
    items = [await bus_summary(db, vehicle) for vehicle in vehicles if vehicle.available and not vehicle.reserved]
    if route_id:
        items = [item for item in items if item["route_id"] == route_id]
    if q:
        query = q.casefold()
        routes = {route.id: route for route in (await db.execute(select(TransitRoute))).scalars()}
        stops = {stop.id: stop.name for stop in (await db.execute(select(TransitStop))).scalars()}
        items = [item for item in items if query in item["id"].casefold()
                 or query in (item["registration_number"] or "").casefold()
                 or query in (item["route_id"] or "").casefold()
                 or (item["route_id"] in routes and (query in routes[item["route_id"]].name.casefold()
                     or any(query in stops.get(stop_id, "").casefold()
                            for stop_id in routes[item["route_id"]].spec.get("stop_ids", []))))]
    return {"buses": items, "tracking_fresh_seconds": 90,
            "crowding_fresh_seconds": CAMERA_FRESH_SECONDS}


@public.get("/buses/{bus_id}")
async def public_bus(bus_id: str, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(TransitVehicle, bus_id)
    if vehicle is None:
        raise HTTPException(404, "Bus not found")
    return await bus_summary(db, vehicle)


@private.get("/buses")
async def buses(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office", "driver"})
    vehicles = (await db.execute(select(TransitVehicle).order_by(TransitVehicle.id))).scalars().all()
    if user["role"] == "driver":
        vehicles = [v for v in vehicles if v.id == user["bus_id"]]
    return {"buses": [await bus_summary(db, vehicle) for vehicle in vehicles]}


@private.get("/buses/{bus_id}")
async def bus(bus_id: str, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office", "driver"}, bus_id)
    vehicle = await db.get(TransitVehicle, bus_id)
    if vehicle is None:
        raise HTTPException(404, "Bus not found")
    return await bus_summary(db, vehicle)


@private.post("/buses/{bus_id}/location")
async def update_bus_location(bus_id: str, body: LocationRequest,
                              db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "driver"}, bus_id)
    vehicle = await db.get(TransitVehicle, bus_id)
    if vehicle is None:
        raise HTTPException(404, "Bus not found")
    if body.source == "gps_device" and user["role"] == "driver":
        raise HTTPException(403, "GPS device ingestion requires a dedicated credential")
    if body.source == "demo_simulation" and user["role"] != "admin":
        raise HTTPException(403,"Only an administrator can publish simulated GPS")
    sample = TransitBusLocation(id=uuid4().hex, bus_id=bus_id, timestamp=utc_now(),
        latitude=body.latitude, longitude=body.longitude, accuracy_m=body.accuracy_m,
        heading_deg=body.heading_deg, speed_kmh=body.speed_kmh, source=body.source)
    db.add(sample)
    await db.commit()
    return {"bus_id": bus_id, "location": (await bus_summary(db, vehicle))["location"]}


@private.post("/buses/{bus_id}/session")
async def bus_session(bus_id:str,body:BusSessionRequest,db:AsyncSession=Depends(get_db),user=Depends(actor)):
    allowed(user,{"admin","driver"},bus_id)
    if not await db.get(TransitVehicle,bus_id):
        raise HTTPException(404,"Bus not found")
    if body.source == "demo_simulation" and user['role'] != 'admin':
        raise HTTPException(403,"Only an administrator can start a GPS simulation")
    row = await db.get(TransitBusSession,bus_id)
    if row is None:
        row = TransitBusSession(bus_id=bus_id)
        db.add(row)
    row.direction, row.active, row.source = body.direction, body.active, body.source
    row.operator,row.updated_at = user['username'],utc_now()
    await db.commit()
    return {'bus_id':bus_id,'direction':row.direction,'active':row.active,'source':row.source}


@public.get('/buses/{bus_id}/arrival')
async def bus_arrival(bus_id:str,stop_id:str|None=None,db:AsyncSession=Depends(get_db)):
    vehicle = await db.get(TransitVehicle,bus_id)
    if vehicle is None:
        raise HTTPException(404,'Bus not found')
    summary = await bus_summary(db,vehicle)
    session = summary['service_session']
    base = {'bus_id':bus_id,'estimated_minutes':None,'available':False,
            'note':'Road profile estimate excludes dwell, waiting and live traffic; service direction is driver-declared.'}
    if not session or not session['active']:
        return {**base,'reason':'An active driver service session and declared direction are required'}
    if summary['tracking_status'] != 'live':
        return {**base,'reason':'A fresh bus GPS report is required'}
    route = await db.get(TransitRoute,vehicle.route_id) if vehicle.route_id else None
    if route is None:
        return {**base,'reason':'No service route is assigned'}
    ids = list(route.spec.get('stop_ids',[]))
    if session['direction']=='inbound':
        ids.reverse()
    if stop_id and stop_id not in ids:
        raise HTTPException(422,'The selected stop is not on this bus service')
    stops = []
    for sid in ids:
        geo,stop = await db.get(TransitGeoStop,sid),await db.get(TransitStop,sid)
        if geo is None or stop is None:
            return {**base,'reason':'All service stops need configured geographic coordinates'}
        stops.append({'id':sid,'name':stop.name,'latitude':geo.latitude,'longitude':geo.longitude,
                      'coordinate_source':geo.coordinate_source})
    if len(stops)<2:
        return {**base,'reason':'A service needs at least two geolocated stops'}
    from transit.routing import service_road_route,progress_estimate
    payload = await service_road_route(stops)
    location = summary['location']
    accuracy = location.get('accuracy_m')
    if accuracy is not None and accuracy > 200:
        return {**base,'reason':'GPS accuracy is too low for a route progress estimate'}
    progress = progress_estimate(payload,location['latitude'],location['longitude'])
    if progress['off_route_km'] > .15+(accuracy or 0)/1000:
        return {**base,'reason':'The reported GPS point is away from the configured service road path',
                'off_route_km':round(progress['off_route_km'],3),'geometry':payload['routes'][0]['geometry']['coordinates'],'stops':stops}
    next_index = next((i for i,distance in enumerate(progress['stop_distances_km'])
                       if distance > progress['distance_along_km']+.02),len(stops)-1)
    target = ids.index(stop_id) if stop_id else next_index
    if target < next_index:
        return {**base,'reason':'This stop is behind the reported progress in the declared direction','stops':stops}
    estimate = max(0,progress['stop_elapsed_minutes'][target]-progress['elapsed_minutes'])
    return {**base,'available':True,'reason':None,'estimated_minutes':round(estimate,1),
        'stop':stops[target],'next_stop':stops[next_index],'stops':stops,
        'geometry':payload['routes'][0]['geometry']['coordinates'],
        'source':'OSRM_ROAD_PROFILE_ESTIMATE','gps_timestamp':location['timestamp'],
        'direction':session['direction'],'demo':session['source']=='demo_simulation' or any(
            stop['coordinate_source']=='illustrative_demo_coordinate' for stop in stops)}


@private.get("/buses/{bus_id}/location")
async def bus_location(bus_id: str, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office", "driver"}, bus_id)
    vehicle = await db.get(TransitVehicle, bus_id)
    if vehicle is None:
        raise HTTPException(404, "Bus not found")
    item = await bus_summary(db, vehicle)
    return {"bus_id": bus_id, "location": item["location"], "tracking_status": item["tracking_status"]}


@private.get("/buses/{bus_id}/occupancy")
async def bus_occupancy(bus_id: str, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office", "driver"}, bus_id)
    vehicle = await db.get(TransitVehicle, bus_id)
    if vehicle is None:
        raise HTTPException(404, "Bus not found")
    return {"bus_id": bus_id, "crowding": (await bus_summary(db, vehicle))["crowding"]}


@private.get("/buses/{bus_id}/safety-status")
async def bus_safety(bus_id: str, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office", "driver"}, bus_id)
    if not await db.get(TransitVehicle, bus_id):
        raise HTTPException(404, "Bus not found")
    events = (await db.execute(select(TransitSafetyEvent).where(TransitSafetyEvent.bus_id == bus_id)
                               .order_by(TransitSafetyEvent.timestamp.desc()).limit(20))).scalars().all()
    return {"bus_id": bus_id, "events": [alert_payload(e) for e in events]}


@private.post("/buses/{bus_id}/door")
async def update_door(bus_id: str, body: DoorStateRequest,
                      db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "driver"}, bus_id)
    setups = (await db.execute(select(TransitCameraSetup).where(
        TransitCameraSetup.bus_id == bus_id, TransitCameraSetup.role == "bus_interior"))).scalars().all()
    if not setups:
        raise HTTPException(404, "No interior camera is assigned to this bus")
    for setup in setups:
        setup.door_open = body.open
    db.add(TransitOperatorAction(id=uuid4().hex, action="door_state", operator=user["username"],
        timestamp=utc_now(), payload={"bus_id": bus_id, "open": body.open, "source": "manual_driver_report"}))
    await db.commit()
    return {"bus_id": bus_id, "door_open": body.open, "source": "manual_driver_report"}


@private.post("/cameras/register")
async def register_camera(body: CameraRegistration, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin"})
    if await db.get(TransitCamera, body.id):
        raise HTTPException(409, "Camera ID already exists")
    if not await db.get(TransitStop, body.stop_id):
        raise HTTPException(404, "Stop not found")
    if body.bus_id and not await db.get(TransitBusProfile, body.bus_id):
        raise HTTPException(422, "Register the bus before assigning its camera")
    camera = TransitCamera(id=body.id, name=body.name, stop_id=body.stop_id,
        corridor_id=body.corridor_id, source_type=body.source_type,
        status="awaiting_authorized_input")
    setup = TransitCameraSetup(camera_id=body.id, role=body.role, bus_id=body.bus_id,
        latitude=body.latitude, longitude=body.longitude,
        coordinate_source=body.coordinate_source if body.latitude is not None else "unconfigured",
        source_label=body.source_type)
    db.add_all([camera, setup])
    await db.commit()
    return camera_payload(camera, setup)


@private.get("/traffic/cameras")
@private.get("/mobility/cameras")
async def camera_list(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office", "driver"}, user.get('bus_id'))
    cameras = (await db.execute(select(TransitCamera).order_by(TransitCamera.id))).scalars().all()
    result = []
    for camera in cameras:
        setup = await db.get(TransitCameraSetup, camera.id)
        if user["role"] == "driver" and (setup is None or setup.bus_id != user["bus_id"]):
            continue
        result.append({**camera_payload(camera, setup),**(await camera_runtime(db,camera))})
    return {"cameras": result}


@private.patch("/mobility/cameras/{camera_id}")
async def configure_safety(camera_id: str, body: CameraSafetyConfig,
                           db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    camera = await db.get(TransitCamera, camera_id)
    setup = await db.get(TransitCameraSetup, camera_id)
    if camera is None or setup is None:
        raise HTTPException(404, "Camera not found")
    if setup.role != "bus_interior":
        raise HTTPException(422, "Safety zones apply only to bus interior cameras")
    setup.safety_zone = body.safety_zone
    setup.door_open = body.door_open
    await db.commit()
    return camera_payload(camera, setup)


@private.post("/cameras/{camera_id}/start")
@private.post("/cameras/{camera_id}/stop")
async def camera_control(camera_id: str, request: Request, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    camera = await db.get(TransitCamera, camera_id)
    if camera is None:
        raise HTTPException(404, "Camera not found")
    if request.url.path.endswith("/start") and camera.source_type == "authorized_ip_camera":
        raise HTTPException(501, "RTSP/IP camera worker is not configured; use an authorized browser camera or upload")
    if request.url.path.endswith("/start") and camera.source_type == "recorded_demo":
        raise HTTPException(422, "Recorded cameras are analyzed through the video upload endpoint")
    # A browser webcam needs its user's permission; this records the requested state only.
    camera.status = "awaiting_browser_permission" if request.url.path.endswith("/start") else "stopped"
    from api.live import _stop_camera_requests
    from api.transit import _jobs,_ACTIVE_JOB_STATES
    if request.url.path.endswith('/stop'):
        _stop_camera_requests.add(camera_id)
        for job in _jobs.values():
            if job.get('camera_id')==camera_id and job['status'] in _ACTIVE_JOB_STATES:
                job['status']='cancelled'
    else:
        _stop_camera_requests.discard(camera_id)
    await db.commit()
    return {"camera_id": camera_id, "status": camera.status, "stream_started": False}


@public.get("/traffic/nearby")
@private.get("/traffic/nearby")
async def traffic_nearby(latitude: float = Query(..., ge=-90, le=90),
                         longitude: float = Query(..., ge=-180, le=180),
                         radius_km: float = Query(5, ge=1, le=10),
                         db: AsyncSession = Depends(get_db)):
    return {"center": {"latitude": latitude, "longitude": longitude},
        "radius_km": radius_km, "cameras": await nearby_cameras(db, latitude, longitude, radius_km),
        "coverage_note": "Each camera covers only its own field of view. Unobserved roads remain unknown."}


@public.get('/traffic/feed')
async def traffic_feed(db: AsyncSession = Depends(get_db)):
    cameras = await nearby_cameras(db, 0, 0, None)
    alerts = []
    for camera in cameras:
        o, p = camera['observation'], camera['prediction']
        if o and o['live'] and (o['category'] in {'HIGH','SEVERE'} or p.get('available') and p['predicted_score']>=50):
            alerts.append({'id': camera['id']+'-traffic-pressure', 'camera_id': camera['id'],
                'title': 'Traffic pressure detected', 'camera_name': camera['name'],
                'reporting_bus_id':camera.get('bus_id'),
                'latitude':camera['latitude'], 'longitude':camera['longitude'],
                'coordinate_source':camera['coordinate_source'], 'score':o['score'],
                'severity':o['category'], 'timestamp':o['timestamp'], 'prediction':p,
                'message': (f"{camera['name']}: bus speed {o.get('bus_speed_kmh')} km/h, {o.get('vehicle_count')} visible vehicles; sustained slowdown, possible queue."
                    if o.get('suspected_queue') else f"{camera['name']}: {o['category'].lower()} visible vehicle pressure."),
                'delivery':'in_app_only'})
    return {'alerts':alerts,'cameras':cameras,'updated_at':iso(utc_now()), 'poll_seconds':5,
            'note':'Only active road cameras publish live traffic. Passenger video and incident evidence remain private.'}


@private.get('/ml/overview')
async def ml_overview(db:AsyncSession=Depends(get_db), user=Depends(actor)):
    allowed(user, {'admin','head_office'})
    from api.transit import models_status
    cameras = await camera_list(db=db, user=user)
    feed = await traffic_feed(db)
    return {'models': await models_status(db), 'cameras':cameras['cameras'],
            'road_cameras':feed['cameras'], 'traffic_alerts':feed['alerts'],
            'use_cases': ['road_traffic','bus_interior'], 'max_live_sessions':2,
            'traffic_forecast':{'model':'Ridge autoregression','horizon_seconds':60,
                'minimum_history_seconds':600,'training_source':'continuous live road camera frames only',
                'validation':'chronological holdout, purged targets, 5% improvement over persistence required'},
            'phone_setup':{'url':'/connect','secure_context_required':True}}


@private.put('/traffic/cameras/{camera_id}/location')
async def locate_road_camera(camera_id:str, body:GeoPoint, db:AsyncSession=Depends(get_db), user=Depends(actor)):
    allowed(user, {'admin'})
    setup = await db.get(TransitCameraSetup,camera_id)
    if setup is None or setup.role!='road_traffic':
        raise HTTPException(422,'Select a registered road traffic camera')
    setup.latitude, setup.longitude = body.latitude, body.longitude
    setup.coordinate_source = 'operator_configured'
    db.add(TransitOperatorAction(id=uuid4().hex,action='camera_location_update',operator=user['username'],
        timestamp=utc_now(),payload={'camera_id':camera_id,**body.model_dump()}))
    await db.commit()
    return {'camera_id':camera_id, **body.model_dump(), 'coordinate_source':setup.coordinate_source}


@private.get('/traffic/speed')
async def speed_dashboard(db:AsyncSession=Depends(get_db), user=Depends(actor)):
    from transit.bus_speed import speed_from_fixes
    allowed(user, {'admin','head_office','driver'}, user.get('bus_id'))
    cameras = (await camera_list(db,user))['cameras']
    result = []
    for camera in cameras:
        if camera['role'] != 'bus_road':
            continue
        fixes = (await db.execute(select(TransitBusLocation).where(TransitBusLocation.bus_id==camera['bus_id'])
                                 .order_by(TransitBusLocation.timestamp.desc()).limit(2))).scalars().all()
        observation = (await db.execute(select(TransitTrafficObservation).where(TransitTrafficObservation.camera_id==camera['id'])
                                       .order_by(TransitTrafficObservation.timestamp.desc()).limit(1))).scalar_one_or_none()
        speed = speed_from_fixes(fixes[0] if fixes else None, fixes[1] if len(fixes)>1 else None, utc_now())
        live = bool(camera['status']=='online' and observation and
                    observation.payload.get('input_source_type')=='browser_camera' and
                    (utc_now()-observation.timestamp).total_seconds()<=5)
        evidence = observation.payload.get('speed_observation',{}) if live else {}
        from transit.traffic_forecasting import camera_forecast
        prediction = await camera_forecast(db,camera['id'],utc_now()) if live and speed['available'] else {
            'available':False,'status':'awaiting_live_gps_and_camera','reason':'Live road frames and accurate bus GPS are required.'}
        result.append({**camera,'gps_speed':speed,'live_evidence':live,
            'prediction':prediction,
            'state':evidence.get('state','awaiting_live_camera'),
            'suspected_queue':bool(live and speed['available'] and evidence.get('suspected_queue')),
            'slow_seconds':evidence.get('slow_seconds',0),
            'vehicle_count':observation.payload.get('vehicle_count') if live else None,
            'bus_speed_at_observation_kmh':evidence.get('speed_kmh') if live else None,
            'congestion_score':observation.score if live else None,
            'location':observation.payload.get('capture_location') if live else None,
            'last_observed_at':iso(observation.timestamp) if observation else None})
    return {'cameras':result,'method':'YOLO road vehicle counts + synchronized bus GPS',
            'rule':{'slow_kmh':10,'minimum_vehicles':3,'sustained_seconds':8,'gps_max_age_seconds':20},
            'note':'A moving camera cannot determine absolute vehicle speed alone. Queue risk is a heuristic; a traffic signal or bus stop may also cause slow movement.'}


@public.post('/navigation/monitor')
async def monitor_routes(body:MonitorRequest, db:AsyncSession=Depends(get_db)):
    from transit.route_intelligence import annotate_routes
    cameras = await nearby_cameras(db, 0, 0, None)
    paths=[r.model_dump() for r in body.routes]
    goal,recorded=body.goal,body.use_recorded_demo
    if body.route_context_id:
        from transit.route_context import resolve
        context=resolve(body.route_context_id)
        paths=context['routes'];goal=context['goal'];recorded=context['recorded_demo']
    result=annotate_routes(paths,cameras,body.selected_route_id,goal,recorded)
    if body.route_context_id:
        from transit.route_context import selection
        selection(body.route_context_id,result['selected_route_id'])
    return result


@private.get("/traffic/observations")
async def traffic_observations(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    records = (await db.execute(select(TransitTrafficObservation).order_by(
        TransitTrafficObservation.timestamp.desc()).limit(100))).scalars().all()
    return {"observations": [{"id": o.id, "camera_id": o.camera_id, "corridor_id": o.corridor_id,
        "score": o.score, "category": o.category, "source": o.source,
        "timestamp": iso(o.timestamp), "fresh": (utc_now() - o.timestamp).total_seconds() <= CAMERA_FRESH_SECONDS}
        for o in records]}


@public.get("/stops")
async def public_stops(db: AsyncSession = Depends(get_db)):
    stops = (await db.execute(select(TransitStop).order_by(TransitStop.id))).scalars().all()
    result = []
    for stop in stops:
        geo = await db.get(TransitGeoStop, stop.id)
        result.append({"id": stop.id, "name": stop.name, "latitude": geo.latitude if geo else None,
            "longitude": geo.longitude if geo else None,
            "coordinate_source": geo.coordinate_source if geo else "unconfigured",
            "source": "SYNTHETIC_DEMO_DATA"})
    return {"stops": result}


@private.put("/stops/{stop_id}/location")
async def set_stop_location(stop_id: str, point: GeoPoint,
                            db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin"})
    if not await db.get(TransitStop, stop_id):
        raise HTTPException(404, "Stop not found")
    geo = await db.get(TransitGeoStop, stop_id)
    if geo is None:
        geo = TransitGeoStop(stop_id=stop_id, latitude=point.latitude,
                             longitude=point.longitude, coordinate_source="operator_configured")
        db.add(geo)
    else:
        geo.latitude, geo.longitude = point.latitude, point.longitude
        geo.coordinate_source = "operator_configured"
    await db.commit()
    return {"stop_id": stop_id, "latitude": geo.latitude, "longitude": geo.longitude,
            "coordinate_source": geo.coordinate_source}


@public.get("/navigation/nearby-stops")
@private.get("/navigation/nearby-stops")
async def nearby_stops(latitude: float = Query(..., ge=-90, le=90),
                       longitude: float = Query(..., ge=-180, le=180),
                       radius_km: float = Query(5, ge=.1, le=10),
                       db: AsyncSession = Depends(get_db)):
    stops = (await public_stops(db))["stops"]
    for stop in stops:
        if stop["latitude"] is not None:
            stop["distance_km"] = round(haversine_km(latitude, longitude, stop["latitude"], stop["longitude"]), 3)
    return {"stops": sorted([s for s in stops if s.get("distance_km", 1e6) <= radius_km],
                            key=lambda s: s["distance_km"]), "radius_km": radius_km}


@public.get("/navigation/nearby-buses")
@private.get("/navigation/nearby-buses")
async def nearby_buses(latitude: float = Query(..., ge=-90, le=90),
                       longitude: float = Query(..., ge=-180, le=180),
                       radius_km: float = Query(5, ge=.1, le=20),
                       db: AsyncSession = Depends(get_db)):
    buses = (await public_buses(route_id=None, q=None, db=db))["buses"]
    fresh = []
    for item in buses:
        location = item["location"]
        if location and location["fresh"]:
            distance = haversine_km(latitude, longitude, location["latitude"], location["longitude"])
            if distance <= radius_km:
                fresh.append({**item, "distance_km": round(distance, 3)})
    return {"buses": sorted(fresh, key=lambda item: item["distance_km"]), "radius_km": radius_km}


async def road_routes(body: RouteRequest, db: AsyncSession) -> dict:
    coords = f"{body.origin.longitude},{body.origin.latitude};{body.destination.longitude},{body.destination.latitude}"
    try:
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "TransitOptAI-CollegePrototype/2.0"}) as client:
            response = await client.get(f"{OSRM_BASE}/route/v1/driving/{coords}", params={
                "alternatives": "3", "steps": "false", "geometries": "geojson", "overview": "full"})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"Road routing provider unavailable: {type(exc).__name__}")
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise HTTPException(422, "No valid drivable road route found between these points")
    from transit.route_intelligence import annotate_routes, route_id
    cameras = await nearby_cameras(db, 0, 0, None)
    options = []
    for route in payload['routes'][:4]:
        geometry = route.get('geometry', {}).get('coordinates', [])
        if len(geometry) < 2:
            continue
        identity=route_id(geometry)
        if any(option['id']==identity for option in options):
            continue
        options.append({'id': identity, 'geometry': geometry,
            'distance_km': round(float(route['distance'])/1000, 2),
            'base_duration_minutes': round(float(route['duration'])/60, 1),
            'source': 'OSRM_OPENSTREETMAP_ROAD_GRAPH'})
    if not options:
        raise HTTPException(503, 'Routing provider returned no usable geometry')
    result = annotate_routes(options, cameras, body.selected_route_id, body.goal, body.use_recorded_demo)
    result['provider'] = 'OSRM'
    selected = result['selected_route_id']
    from transit.route_context import remember
    result['route_context_id']=remember(options,body.origin.model_dump(),body.destination.model_dump(),
                                        body.goal,body.use_recorded_demo,selected)
    if body.save:
        db.add(TransitNavigationRequest(id=uuid4().hex, timestamp=utc_now(), route_provider="OSRM",
            origin=body.origin.model_dump(), destination=body.destination.model_dump(),
            selected_route_id=selected, options=result))
        await db.commit()
    return result


@private.post("/navigation/routes")
@private.post("/navigation/reroute")
@public.post("/navigation/routes")
@public.post("/navigation/reroute")
async def public_routes(body: RouteRequest, db: AsyncSession = Depends(get_db)):
    return await road_routes(body, db)


@public.get("/navigation/places")
async def places(q: str = Query(..., min_length=3, max_length=120)):
    global _geocode_last
    async with _geocode_lock:
        now = asyncio.get_running_loop().time()
        if now - _geocode_last < 1:
            await asyncio.sleep(1 - (now - _geocode_last))
        _geocode_last = asyncio.get_running_loop().time()
        try:
            async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "TransitOptAI-CollegePrototype/2.0"}) as client:
                response = await client.get(f"{NOMINATIM_BASE}/search", params={
                    "q": q, "format": "jsonv2", "limit": 5, "countrycodes": "in"})
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, f"Place search unavailable: {type(exc).__name__}")
    return {"places": [{"name": item["display_name"], "latitude": float(item["lat"]),
                        "longitude": float(item["lon"])} for item in data],
            "provider": "OpenStreetMap Nominatim", "search_mode": "explicit_submit"}


def alert_payload(event: TransitSafetyEvent) -> dict:
    return {"id": event.id, "bus_id": event.bus_id, "camera_id": event.camera_id,
        "timestamp": iso(event.timestamp), "category": event.category, "severity": event.severity,
        "status": event.status, "note": event.note, "evidence": event.evidence,
        "delivery": "in_app_only"}


async def alert_detail_payload(db: AsyncSession, event: TransitSafetyEvent) -> dict:
    profile = await db.get(TransitBusProfile, event.bus_id)
    camera = await db.get(TransitCamera, event.camera_id)
    location = await latest_location(db, event.bus_id)
    return {**alert_payload(event),
        "registration_number": profile.registration_number if profile else None,
        "camera_name": camera.name if camera else event.camera_id,
        "last_known_location": {"latitude": location.latitude, "longitude": location.longitude,
            "timestamp": iso(location.timestamp), "source": location.source,
            "fresh": (utc_now() - location.timestamp).total_seconds() <= 90} if location else None}


@private.get("/alerts")
async def alerts(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    records = (await db.execute(select(TransitSafetyEvent).order_by(
        TransitSafetyEvent.timestamp.desc()).limit(200))).scalars().all()
    return {"alerts": [await alert_detail_payload(db, event) for event in records],
            "notification_delivery": "in_app_only"}


@private.get("/alerts/{alert_id}")
async def alert(alert_id: str, db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    record = await db.get(TransitSafetyEvent, alert_id)
    if record is None:
        raise HTTPException(404, "Alert not found")
    actions = (await db.execute(select(TransitSafetyAction).where(
        TransitSafetyAction.event_id == alert_id).order_by(TransitSafetyAction.timestamp))).scalars().all()
    return {**(await alert_detail_payload(db, record)), "actions": [{"operator": a.operator, "action": a.action,
        "timestamp": iso(a.timestamp), "note": a.note} for a in actions]}


@private.post("/alerts/{alert_id}/{action}")
async def review_alert(alert_id: str, action: str, body: ReviewRequest = ReviewRequest(),
                       db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    if action not in {"acknowledge", "resolve", "false-positive"}:
        raise HTTPException(404, "Unknown alert action")
    record = await db.get(TransitSafetyEvent, alert_id)
    if record is None:
        raise HTTPException(404, "Alert not found")
    if record.status in {"resolved", "false_positive"}:
        raise HTTPException(409, "Alert is already closed")
    record.status = {"acknowledge": "acknowledged", "resolve": "resolved",
                     "false-positive": "false_positive"}[action]
    record.note = body.note
    db.add(TransitSafetyAction(id=uuid4().hex, event_id=alert_id,
        operator=user["username"], action=action, timestamp=utc_now(), note=body.note))
    await db.commit()
    return await alert_detail_payload(db, record)


@private.get("/exports/alerts")
async def export_alerts(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    records = (await db.execute(select(TransitSafetyEvent).order_by(TransitSafetyEvent.timestamp.desc()))).scalars().all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "bus_id", "camera_id", "timestamp", "category", "severity", "status", "note"])
    for record in records:
        writer.writerow([record.id, record.bus_id, record.camera_id, iso(record.timestamp),
                         record.category, record.severity, record.status, record.note])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=transitopt-alerts.csv"})


@private.get("/dashboard/fleet")
async def fleet_dashboard(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    return await buses(db, user)


@private.get("/dashboard/safety")
async def safety_dashboard(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    return await alerts(db, user)


@private.get("/dashboard/traffic")
async def traffic_dashboard(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    return await traffic_observations(db, user)


@private.get("/dashboard/overview")
async def mobility_overview(db: AsyncSession = Depends(get_db), user=Depends(actor)):
    allowed(user, {"admin", "head_office"})
    fleet = (await buses(db, user))["buses"]
    incidents = (await alerts(db, user))["alerts"]
    return {"fleet_count": len(fleet), "gps_live": sum(b["tracking_status"] == "live" for b in fleet),
        "camera_crowding_fresh": sum(bool(b["crowding"] and b["crowding"]["fresh"]) for b in fleet),
        "alerts_awaiting_review": sum(a["status"] == "awaiting_review" for a in incidents),
        "source": "REGISTERED_BUSES_AND_STORED_OBSERVATIONS"}
