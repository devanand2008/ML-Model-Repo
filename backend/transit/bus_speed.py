"""Moving-bus GPS speed + YOLO road density, never monocular absolute speed.

Queue status is a reviewable heuristic. Real GPS and repeated live camera
evidence are required; recorded frames and simulated GPS cannot publish it.
"""
from datetime import datetime
from math import isfinite
from sqlalchemy import select
from transit.models import TransitBusLocation, TransitTrafficObservation

GPS_MAX_AGE = 20
MAX_ACCURACY_M = 30
SLOW_KMH = 10
HOLD_SECONDS = 8
MIN_VEHICLES = 3


def speed_from_fixes(current, previous, now):
    from transit.mobility import haversine_km, iso
    base = {'available': False, 'speed_kmh': None, 'upper_speed_kmh': None,
            'source': 'unavailable', 'timestamp': iso(current.timestamp) if current else None,
            'note': 'Bus speed comes from GPS; surrounding vehicle speed cannot be measured from this moving camera.'}
    if not current or not 0 <= (now-current.timestamp).total_seconds() <= GPS_MAX_AGE:
        return {**base, 'reason': 'A GPS reading from the last 20 seconds is required.'}
    if current.source not in {'browser_geolocation', 'gps_device'}:
        return {**base, 'reason': 'Simulated GPS is excluded from live speed and congestion alerts.'}
    if current.accuracy_m is None or not isfinite(current.accuracy_m) or not 0 <= current.accuracy_m <= MAX_ACCURACY_M:
        return {**base, 'reason': 'GPS horizontal accuracy must be reported and at most 30 metres.'}
    if current.speed_kmh is not None and isfinite(current.speed_kmh) and 0 <= current.speed_kmh <= 200:
        return {**base, 'available': True, 'speed_kmh': round(current.speed_kmh, 1),
                'upper_speed_kmh': round(current.speed_kmh, 1), 'source': 'gps_reported',
                'accuracy_m': current.accuracy_m}
    if previous and previous.source == current.source and previous.accuracy_m is not None:
        dt = (current.timestamp-previous.timestamp).total_seconds()
        if 5 <= dt <= 30 and 0 <= previous.accuracy_m <= MAX_ACCURACY_M:
            metres = haversine_km(previous.latitude, previous.longitude, current.latitude, current.longitude)*1000
            uncertainty = previous.accuracy_m+current.accuracy_m
            speed = metres/dt*3.6
            if speed <= 200:
                return {**base, 'available': True, 'source': 'gps_displacement_estimate',
                        'speed_kmh': round(speed, 1), 'lower_speed_kmh': round(max(0, metres-uncertainty)/dt*3.6, 1),
                        'upper_speed_kmh': round((metres+uncertainty)/dt*3.6, 1), 'interval_seconds': dt,
                        'accuracy_m': current.accuracy_m,
                        'note': 'Average GPS displacement speed; accuracy bounds must also indicate low speed before a congestion alert.'}
    return {**base, 'reason': 'GPS has no speed yet. Wait for another accurate fix at least five seconds apart.'}


def fuse_speed(metrics, speed, previous, now, session_id, source_type):
    result = dict(metrics)
    ts = now.timestamp()
    previous = previous or {}
    continuous = (previous.get('session_id') == session_id and 0 < ts-previous.get('observed_at', 0) <= 3)
    qualifies = (source_type == 'browser_camera' and speed.get('available')
                 and speed.get('upper_speed_kmh', 999) <= SLOW_KMH and metrics['vehicle_count'] >= MIN_VEHICLES)
    since = previous.get('slow_since') if continuous and qualifies else None
    first_fix = previous.get('first_gps_timestamp') if since is not None else speed.get('timestamp')
    since = (since if since is not None else ts) if qualifies else None
    duration = max(0, ts-since) if since is not None else 0
    multiple_fixes = bool(first_fix and first_fix != speed.get('timestamp'))
    suspected = qualifies and duration >= HOLD_SECONDS and multiple_fixes
    state = 'suspected_queue' if suspected else 'observing_slow_traffic' if qualifies else 'moving' if speed.get('available') and speed['speed_kmh'] > SLOW_KMH else 'insufficient_evidence'
    result['speed_observation'] = {**speed, 'state': state, 'slow_seconds': round(duration, 1),
        'suspected_queue': bool(suspected), 'visible_vehicles': metrics['vehicle_count'],
        'session_id': session_id, 'observed_at': ts, 'slow_since': since, 'first_gps_timestamp': first_fix,
        'method': 'GPS speed <=10 km/h, at least 3 visible vehicles, >=8 continuous seconds and two GPS fixes',
        'reason': speed.get('reason') or ('Sustained low bus speed with surrounding vehicles. A signal or bus stop can also explain this; congestion is suspected.' if suspected else 'Waiting for sustained low-speed, multi-vehicle evidence.')}
    result['bus_speed_kmh'] = speed.get('speed_kmh')
    result['speed_status'] = speed.get('source') if speed.get('available') else speed.get('reason')
    if suspected:
        result['congestion_score'] = max(metrics['congestion_score'], 70.0)
        result['data_quality'] = 'gps_speed_and_yolo_density_estimate'
        result['method'] += ' Sustained GPS slowdown with >=3 vehicles sets a 70/100 queue-risk floor; this is a heuristic, not calibrated delay.'
    return result


async def enrich_bus_speed(db, metrics, setup, source_id, source_type, now):
    fixes = (await db.execute(select(TransitBusLocation).where(TransitBusLocation.bus_id == setup.bus_id)
        .order_by(TransitBusLocation.timestamp.desc()).limit(2))).scalars().all()
    speed = speed_from_fixes(fixes[0] if fixes else None, fixes[1] if len(fixes)>1 else None, now)
    previous = (await db.execute(select(TransitTrafficObservation).where(
        TransitTrafficObservation.camera_id == setup.camera_id).order_by(
        TransitTrafficObservation.timestamp.desc()).limit(1))).scalar_one_or_none()
    if previous and fixes:
        from transit.mobility import haversine_km
        point = previous.payload.get('capture_location')
        if not point or haversine_km(point['latitude'],point['longitude'],fixes[0].latitude,fixes[0].longitude) > .05:
            previous = None
    result = fuse_speed(metrics, speed, (previous.payload or {}).get('speed_observation') if previous else None,
                        now, source_id, source_type)
    # Bind the observation to where it was captured, never the bus's later GPS position.
    if fixes and speed['available'] and source_type == 'browser_camera':
        result['capture_location'] = {'latitude': fixes[0].latitude, 'longitude': fixes[0].longitude,
                                      'timestamp': speed['timestamp'], 'source': 'bus_gps_at_capture'}
    return result
