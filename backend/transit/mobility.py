"""Bus GPS, camera associations, public summaries and reviewable safety rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from transit.models import (
    TransitBusLocation, TransitBusOccupancy, TransitBusProfile, TransitCamera,
    TransitCameraSetup, TransitDetectionEvent, TransitGeoStop, TransitSafetyAction,
    TransitSafetyEvent, TransitTrafficObservation, TransitVehicle, TransitOperatorAction,
    TransitBusSession,
    TransitRoute,
)

GPS_FRESH_SECONDS = 90
CAMERA_FRESH_SECONDS = 300
SAFETY_PERSISTENCE_FRAMES = 3
DOOR_FRESH_SECONDS = 300


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    latitude = radians(b_lat - a_lat)
    longitude = radians(b_lon - a_lon)
    arc = sin(latitude / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(longitude / 2) ** 2
    return 6371.0088 * 2 * asin(min(1, sqrt(arc)))


async def seed_mobility(db) -> None:
    old_demo = await db.get(TransitBusProfile, "BUS001")
    if old_demo and old_demo.demo and old_demo.registration_number == "TN30-N-1234":
        await db.delete(old_demo)
        await db.flush()
    if not await db.get(TransitBusProfile, "BUS005"):
        db.add(TransitBusProfile(bus_id="BUS005", registration_number="TN30-N-1234",
                                 source_city="Salem", coverage="partial", demo=True))
    if not await db.get(TransitCamera, "BUS_CAM_001"):
        db.add(TransitCamera(id="BUS_CAM_001", name="Demo bus interior webcam", stop_id="S02",
                             corridor_id="C02", status="awaiting_authorized_input",
                             source_type="browser_camera_or_upload"))
    if not await db.get(TransitCamera, "BUS_ROAD_001"):
        db.add(TransitCamera(id="BUS_ROAD_001", name="Demo bus forward road camera", stop_id="S02",
                             corridor_id="C02", status="awaiting_authorized_input",
                             source_type="browser_camera_or_upload"))
    await db.flush()
    setups = {
        "BUS_CAM_001": ("bus_interior", "BUS005", None, None, "unconfigured"),
        "BUS_ROAD_001": ("bus_road", "BUS005", None, None, "unconfigured"),
        "CAM01": ("road_traffic", None, 11.6649, 78.1460, "illustrative_demo_coordinate"),
        "CAM02": ("road_traffic", None, 11.6757, 78.1402, "illustrative_demo_coordinate"),
        "CAM03": ("road_traffic", None, 11.6725, 78.1207, "illustrative_demo_coordinate"),
        "CAM04": ("road_traffic", None, 11.6830, 78.1600, "illustrative_demo_coordinate"),
        "CAM05": ("road_traffic", None, 11.6500, 78.1700, "illustrative_demo_coordinate"),
    }
    for camera_id, (role, bus_id, lat, lon, source) in setups.items():
        existing = await db.get(TransitCameraSetup, camera_id)
        if camera_id == "BUS_CAM_001" and existing and existing.bus_id == "BUS001" and existing.coordinate_source == "unconfigured":
            existing.bus_id = "BUS005"
        if not existing:
            db.add(TransitCameraSetup(camera_id=camera_id, role=role, bus_id=bus_id,
                                      latitude=lat, longitude=lon, coordinate_source=source))
    # Approximate demo pins only; they are never described as verified stop locations.
    demo_stops = {
        "S01": (11.6649, 78.1460), "S02": (11.6757, 78.1402),
        "S03": (11.6725, 78.1207), "S04": (11.6830, 78.1600),
        "S05": (11.6500, 78.1700), "S06": (11.6940, 78.1630),
        "S07": (11.6920, 78.1290), "S08": (11.7040, 78.1120),
        "S09": (11.6580, 78.1600), "S10": (11.6670, 78.1090),
        "S11": (11.6750, 78.1510), "S12": (11.6440, 78.1510),
    }
    for stop_id, (lat, lon) in demo_stops.items():
        if not await db.get(TransitGeoStop, stop_id):
            db.add(TransitGeoStop(stop_id=stop_id, latitude=lat, longitude=lon,
                                  coordinate_source="illustrative_demo_coordinate"))
    await db.commit()


async def latest_location(db, bus_id: str) -> TransitBusLocation | None:
    return (await db.execute(select(TransitBusLocation).where(TransitBusLocation.bus_id == bus_id)
                             .order_by(TransitBusLocation.timestamp.desc()).limit(1))).scalar_one_or_none()


async def latest_occupancy(db, bus_id: str) -> TransitBusOccupancy | None:
    return (await db.execute(select(TransitBusOccupancy).where(TransitBusOccupancy.bus_id == bus_id)
                             .order_by(TransitBusOccupancy.timestamp.desc()).limit(1))).scalar_one_or_none()


async def camera_runtime(db,camera:TransitCamera):
    event=(await db.execute(select(TransitDetectionEvent).where(TransitDetectionEvent.camera_id==camera.id)
                           .order_by(TransitDetectionEvent.timestamp.desc()).limit(1))).scalar_one_or_none()
    status=camera.status
    if status=='observed_authorized_input':
        if event and event.source_type=='browser_camera':
            from api.live import _active_camera_sessions
            status='online' if camera.id in _active_camera_sessions and (utc_now()-event.timestamp).total_seconds()<=10 else 'offline'
        else:
            status='recorded_observation'
    return {'status':status,'last_processed_at':iso(event.timestamp) if event else None,
            'last_source_type':event.source_type if event else None}


async def bus_summary(db, vehicle: TransitVehicle) -> dict:
    profile = await db.get(TransitBusProfile, vehicle.id)
    location = await latest_location(db, vehicle.id)
    occupancy = await latest_occupancy(db, vehicle.id)
    crowd_event = await db.get(TransitDetectionEvent,occupancy.detection_event_id) if occupancy else None
    session = await db.get(TransitBusSession,vehicle.id)
    route = await db.get(TransitRoute,vehicle.route_id) if vehicle.route_id else None
    now = utc_now()
    gps_fresh = bool(location and (now - location.timestamp).total_seconds() <= GPS_FRESH_SECONDS)
    crowd_fresh = bool(occupancy and (now - occupancy.timestamp).total_seconds() <= CAMERA_FRESH_SECONDS)
    event = (await db.execute(select(TransitSafetyEvent).where(TransitSafetyEvent.bus_id == vehicle.id,
        TransitSafetyEvent.status.in_(["awaiting_review", "acknowledged"]))
        .order_by(TransitSafetyEvent.timestamp.desc()).limit(1))).scalar_one_or_none()
    return {
        "id": vehicle.id, "registration_number": profile.registration_number if profile else None,
        "registration_source": "illustrative_demo_registration" if profile and profile.demo else "operator_registered" if profile else "unregistered",
        "route_id": vehicle.route_id, "capacity": vehicle.capacity,
        "route_name":route.name if route else None,"stop_ids":route.spec.get('stop_ids',[]) if route else [],
        "available": vehicle.available, "reserved": vehicle.reserved,
        "location": {"latitude": location.latitude, "longitude": location.longitude,
                     "accuracy_m": location.accuracy_m, "heading_deg": location.heading_deg,
                     "speed_kmh": location.speed_kmh, "timestamp": iso(location.timestamp),
                     "source": location.source, "fresh": gps_fresh} if location else None,
        "tracking_status": "live" if gps_fresh else "stale" if location else "unavailable",
        "service_session": {"direction":session.direction,"active":session.active,
            "source":session.source,"updated_at":iso(session.updated_at)} if session else None,
        "crowding": {"visible_people": occupancy.visible_people, "level": occupancy.crowd_level,
                      "coverage": occupancy.coverage, "data_quality": occupancy.data_quality,
                      "timestamp": iso(occupancy.timestamp), "fresh": crowd_fresh,
                      "live":crowd_fresh and bool(crowd_event and crowd_event.source_type=='browser_camera'),
                      "source_type":crowd_event.source_type if crowd_event else 'unknown',
                      "load_factor": round(occupancy.visible_people / vehicle.capacity,3) if occupancy.coverage == "full_verified" else None,
                      "note": "Camera observation of visible people; total bus occupancy is unverified."} if occupancy else None,
        "public_safety_status": "Safety report under operator review" if event else "No active reported incident",
    }


def person_in_zone(detections: list[dict], zone: list[float], width: float, height: float) -> bool:
    if not width or not height:
        return False
    x, y, w, h = zone
    for detection in detections:
        if detection.get("class") != "person":
            continue
        bx, by, bw, bh = detection["bbox"]
        foot_x, foot_y = (bx + bw / 2) / width, (by + bh) / height
        if x <= foot_x <= x + w and y <= foot_y <= y + h:
            return True
    return False


class SafetyFrameTracker:
    """Consecutive in-zone observations within one live inference session."""
    def __init__(self):
        self.zone = None
        self.last_at = None
        self.counts = {}
        self.untracked_count = 0

    def reset(self):
        self.last_at = None
        self.counts = {}
        self.untracked_count = 0

    def update(self, detections, width, height, zone, timestamp=None):
        now = timestamp or utc_now()
        if zone != self.zone or (self.last_at and (now - self.last_at).total_seconds() > 5):
            self.reset()
        self.zone = list(zone) if zone else None
        self.last_at = now
        inside = [d for d in detections if zone and person_in_zone([d], zone, width, height)]
        ids = {d["track_id"] for d in inside if d.get("track_id") is not None}
        self.counts = {tid: self.counts.get(tid, 0) + 1 for tid in ids}
        self.untracked_count = self.untracked_count + 1 if inside and not ids else 0
        return max([self.untracked_count, *self.counts.values()])


async def record_bus_observation(db, camera: TransitCamera, setup: TransitCameraSetup,
                                 event: TransitDetectionEvent, detections: list[dict],
                                 width: int, height: int, config: dict | None = None) -> dict:
    bus = await db.get(TransitVehicle, setup.bus_id)
    if bus is None:
        raise HTTPException(422, "Camera is mapped to a missing bus")
    profile = await db.get(TransitBusProfile, bus.id)
    people = [d for d in detections if d.get("class") == "person"]
    visible = len(people)
    # With partial coverage, capacity percentages and true load factors are unsupported.
    coverage = profile.coverage if profile else "partial"
    thresholds = (config or {}).get("crowd_visible_thresholds",{"moderate":6,"high":15,"critical":30})
    if coverage == "full_verified":
        ratio = visible / bus.capacity
        level = "CRITICAL" if ratio >= 1 else "HIGH" if ratio >= .8 else "MODERATE" if ratio >= .5 else "LOW"
    else:
        level = "CRITICAL" if visible >= thresholds["critical"] else "HIGH" if visible >= thresholds["high"] else "MODERATE" if visible >= thresholds["moderate"] else "LOW"
    observation = TransitBusOccupancy(id=uuid4().hex, bus_id=bus.id, camera_id=camera.id,
        detection_event_id=event.id, timestamp=event.timestamp, visible_people=visible,
        crowd_level=level, coverage=coverage,
        data_quality="full_coverage_operator_verified" if coverage == "full_verified" else "visible_people_partial_camera")
    db.add(observation)
    safety = None
    zone = setup.safety_zone
    if event.source_type == "browser_camera" and zone and person_in_zone(detections, zone, width, height):
        count = event.payload.get("safety_consecutive_frames", 0)
        location = await latest_location(db, bus.id)
        moving = bool(location and (event.timestamp - location.timestamp).total_seconds() < GPS_FRESH_SECONDS
                      and location.speed_kmh is not None and location.speed_kmh >= 5)
        door = None
        if count >= SAFETY_PERSISTENCE_FRAMES and moving:
            actions = (await db.execute(select(TransitOperatorAction).where(
                TransitOperatorAction.action == "door_state",
                TransitOperatorAction.timestamp >= event.timestamp - timedelta(seconds=DOOR_FRESH_SECONDS))
                .order_by(TransitOperatorAction.timestamp.desc()).limit(100))).scalars()
            door = next((a for a in actions if a.payload.get("bus_id") == bus.id), None)
        if count >= SAFETY_PERSISTENCE_FRAMES and moving and door and door.payload.get("open") is True:
            prior = (await db.execute(select(TransitSafetyEvent).where(
                TransitSafetyEvent.camera_id == camera.id,
                TransitSafetyEvent.category == 'suspected_unsafe_doorway_position',
                TransitSafetyEvent.timestamp >= event.timestamp - timedelta(minutes=2))
                .limit(1))).scalar_one_or_none()
            if prior is None:
                safety = TransitSafetyEvent(id=uuid4().hex, bus_id=bus.id, camera_id=camera.id,
                    detection_event_id=event.id, timestamp=event.timestamp,
                    category="suspected_unsafe_doorway_position", severity="HIGH",
                    status="awaiting_review", evidence={"visible_person_in_zone_frames": count,
                        "gps_speed_kmh": location.speed_kmh, "door_open": True,
                        "gps_source": location.source, "door_source": "manual_driver_report",
                        "door_reported_at": iso(door.timestamp),
                        "simulation_context": location.source == "demo_simulation",
                        "safety_zone": zone, "model_confidence": max(d["confidence"] for d in people),
                        "source": "REAL_MODEL_DETECTION", "review_required": True,
                        "frame_available": False})
                db.add(safety)
    if safety is None and event.source_type == 'browser_camera' and level == 'CRITICAL':
        recent=(await db.execute(select(TransitBusOccupancy).where(
            TransitBusOccupancy.camera_id==camera.id,TransitBusOccupancy.bus_id==bus.id)
            .order_by(TransitBusOccupancy.timestamp.desc()).limit(3))).scalars().all()
        persistent=len(recent)==3 and all(row.crowd_level=='CRITICAL' for row in recent) and (
            event.timestamp-recent[-1].timestamp).total_seconds()<=10
        prior=(await db.execute(select(TransitSafetyEvent).where(TransitSafetyEvent.camera_id==camera.id,
            TransitSafetyEvent.category=='critical_visible_crowding_estimate',
            TransitSafetyEvent.timestamp>=event.timestamp-timedelta(minutes=2)).limit(1))).scalar_one_or_none()
        if persistent and prior is None:
            safety=TransitSafetyEvent(id=uuid4().hex,bus_id=bus.id,camera_id=camera.id,
                detection_event_id=event.id,timestamp=event.timestamp,category='critical_visible_crowding_estimate',
                severity='HIGH',status='awaiting_review',evidence={'visible_people':visible,'coverage':coverage,
                    'configured_visible_thresholds':thresholds,'sampled_observations':3,
                    'source':'REAL_MODEL_DETECTION','review_required':True,'frame_available':False,
                    'note':'Camera crowd threshold exceeded; total bus occupancy remains unverified unless coverage is full_verified.'})
            db.add(safety)
    return {"bus_id": bus.id, "visible_people": visible, "crowd_level": level,
            "coverage": observation.coverage, "data_quality": observation.data_quality,
            "safety_event_id": safety.id if safety else None,
            "safety_rule": "Requires three consecutive zone frames, fresh GPS speed >=5 km/h and confirmed open door"}


async def nearby_cameras(db, latitude: float, longitude: float, radius_km: float | None) -> list[dict]:
    setups = (await db.execute(select(TransitCameraSetup).where(
        TransitCameraSetup.role.in_(["road_traffic", "bus_road"])))).scalars().all()
    now = utc_now()
    result = []
    for setup in setups:
        camera = await db.get(TransitCamera, setup.camera_id)
        observation = (await db.execute(select(TransitTrafficObservation).where(
            TransitTrafficObservation.camera_id == camera.id)
            .order_by(TransitTrafficObservation.timestamp.desc()).limit(1))).scalar_one_or_none()
        fresh = bool(observation and (now - observation.timestamp).total_seconds() <= CAMERA_FRESH_SECONDS)
        runtime = await camera_runtime(db, camera)
        live = bool(fresh and observation.payload.get("input_source_type") == "browser_camera"
                    and runtime['status'] == 'online')
        moving = setup.role == 'bus_road'
        location = observation.payload.get('capture_location') if observation and moving else None
        if moving:
            # A moving camera's road evidence expires quickly and stays at capture position.
            live = bool(live and location and (now-observation.timestamp).total_seconds() <= 20)
            if not live:
                continue
            lat, lon = location['latitude'], location['longitude']
        else:
            lat, lon = setup.latitude, setup.longitude
            if lat is None or lon is None:
                continue
        distance = haversine_km(latitude, longitude, lat, lon)
        if radius_km is not None and distance > radius_km:
            continue
        from transit.traffic_forecasting import camera_forecast
        prediction = await camera_forecast(db, camera.id, now) if live else {
            'available': False, 'status': 'offline', 'reason': 'Start live road detection to collect training data.'}
        speed = (observation.payload.get('speed_observation') or {}) if observation else {}
        result.append({"id": camera.id, "name": camera.name, "latitude": lat,
            "longitude": lon, "coordinate_source": 'bus_gps_at_capture' if moving else setup.coordinate_source,
            "camera_role":setup.role, "bus_id":setup.bus_id,
            "corridor_id": camera.corridor_id, "distance_km": round(distance, 3),
            "camera_status": runtime['status'], "prediction": prediction, "observation": {
                "score": observation.score, "category": observation.category,
                "source": observation.source, "timestamp": iso(observation.timestamp), "fresh": fresh,
                "data_quality": observation.payload.get("data_quality")
                ,"observation_type":observation.payload.get("observation_type","unknown"),
                "live":live, "bus_speed_kmh":speed.get('speed_kmh') if live else None,
                "speed_source":speed.get('source'), "suspected_queue":bool(live and speed.get('suspected_queue')),
                "vehicle_count":observation.payload.get('vehicle_count'),
                "slow_seconds":speed.get('slow_seconds') if live else None
            } if observation else None})
    return sorted(result, key=lambda camera: camera["distance_km"])
