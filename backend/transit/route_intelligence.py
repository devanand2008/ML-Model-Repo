"""Attach live ML evidence to provider road paths, with explicit comparison weights."""
from hashlib import sha256
from math import cos, radians


def route_id(geometry):
    return 'road-' + sha256(repr(geometry).encode()).hexdigest()[:12]


def near_path(camera, geometry, radius_km=.25):
    # Segment distance also finds cameras between sparse provider vertices.
    latitude, longitude = camera['latitude'], camera['longitude']
    scale_x = 111.32 * cos(radians(latitude))
    for a, b in zip(geometry, geometry[1:]):
        ax, ay = (a[0]-longitude)*scale_x, (a[1]-latitude)*111.32
        bx, by = (b[0]-longitude)*scale_x, (b[1]-latitude)*111.32
        dx, dy = bx-ax, by-ay
        t = max(0, min(1, -(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
        if (ax+t*dx)**2+(ay+t*dy)**2 <= radius_km**2:
            return True
    return False


def annotate_routes(routes, cameras, selected=None, goal='fastest', recorded_demo=False):
    options, alerts = [], []
    for route in routes:
        nearby, pressure, live_count, recorded_count, high_count = [], 0., 0, 0, 0
        for camera in cameras:
            if not near_path(camera, route['geometry']):
                continue
            observation, prediction = camera.get('observation'), camera.get('prediction', {})
            nearby.append({'camera_id': camera['id'], 'name': camera.get('name', camera['id']),
                           'observation': observation, 'prediction': prediction,
                           'coordinate_source': camera['coordinate_source']})
            usable = bool(observation and observation['fresh'] and observation['source']=='REAL_MODEL_DETECTION')
            live = usable and observation.get('live', False)
            recorded = usable and recorded_demo and observation.get('observation_type')=='recorded_detection'
            live_count += bool(live)
            recorded_count += bool(recorded)
            if live or recorded:
                score = observation['score']
                if live and prediction.get('available'):
                    score = max(score, prediction['predicted_score'])
                pressure += score / 100
                high_count += bool(live and score >= 50)
        # Two comparison minutes per maximum-pressure camera, bounded to half the
        # profile duration. It is a ranking preference, not a measured traffic ETA.
        penalty = min(route['base_duration_minutes']*.5, pressure*2)
        options.append({**route, 'nearby_cameras': nearby, 'observed_camera_count': live_count,
            'recorded_demo_camera_count': recorded_count,
            'high_pressure_camera_count': high_count,
            'observed_pressure_total': round(pressure, 3),
            'comparison_minutes': round(route['base_duration_minutes']+penalty, 1),
            'camera_comparison_penalty_minutes': round(penalty, 1),
            'traffic_coverage': 'approximate_demo_camera_local' if any(
                c['coordinate_source']=='illustrative_demo_coordinate' for c in nearby)
                else 'camera_local_only' if nearby else 'unknown'})
    if goal == 'lowest_observed_traffic':
        # Minimize observed pressure; an uncovered road is explicitly unknown,
        # never evidence of free-flowing traffic. Profile time breaks ties.
        ranking = sorted(options, key=lambda r: (r['observed_pressure_total'], r['base_duration_minutes'], r['id']))
    else:
        ranking = sorted(options, key=lambda r: (r['distance_km'] if goal=='shortest' else r['comparison_minutes'], r['id']))
    selected = selected if any(r['id']==selected for r in options) else ranking[0]['id']
    chosen = next(r for r in options if r['id']==selected)
    best=ranking[0]
    if goal=='lowest_observed_traffic':
        advantage=chosen['observed_pressure_total']-best['observed_pressure_total']
        meaningful=advantage>=.1 or abs(advantage)<1e-9 and chosen['base_duration_minutes']-best['base_duration_minutes']>=1
    elif goal=='shortest':
        meaningful=chosen['distance_km']-best['distance_km']>=.1
    else:
        meaningful=chosen['comparison_minutes']-best['comparison_minutes']>=max(1,chosen['comparison_minutes']*.05)
        meaningful=meaningful or (chosen['high_pressure_camera_count']>best['high_pressure_camera_count']
            and chosen['observed_pressure_total']-best['observed_pressure_total']>=.1)
        meaningful=meaningful or (recorded_demo and chosen['recorded_demo_camera_count']>best['recorded_demo_camera_count']
            and chosen['observed_pressure_total']-best['observed_pressure_total']>=.1)
    recommended=best if meaningful or best['id']==selected else chosen
    for camera in chosen['nearby_cameras']:
        observation, prediction = camera['observation'], camera['prediction']
        if not observation or not observation.get('live') or not observation.get('fresh') or observation.get('source') != 'REAL_MODEL_DETECTION':
            continue
        predicted_high = prediction.get('available') and prediction['predicted_score'] >= 50
        if observation['category'] not in {'HIGH', 'SEVERE'} and not predicted_high:
            continue
        alerts.append({'id': camera['camera_id']+'-route-pressure', 'camera_id': camera['camera_id'],
            'title': 'New traffic pressure on your route', 'severity': observation['category'],
            'score': observation['score'], 'prediction': prediction,
            'timestamp': observation['timestamp'], 'coordinate_source': camera['coordinate_source'],
            'message': (f"{camera['name']}: bus moving at {observation.get('bus_speed_kmh')} km/h with {observation.get('vehicle_count')} visible vehicles; possible queue. Check road alternatives."
                if observation.get('suspected_queue') else f"{camera['name']} reports {observation['category'].lower()} visible vehicle pressure. Check the road alternatives."),
            'delivery': 'in_app_only'})
    alternate = recommended if recommended['id']!=selected else None
    reason=('A road alternative has a meaningful advantage using the current comparison.' if alternate
        else 'The selected route ranks first.' if best['id']==selected
        else 'The difference is too small to justify switching; keep the selected route and monitor traffic.')
    return {'routes': options, 'selected_route_id': selected, 'recommended_route_id': recommended['id'],
        'ranked_first_route_id':best['id'],'recommendation_reason':reason,
        'route_alerts': alerts, 'alternative_available': bool(alternate),
        'goal': goal, 'recorded_demo_enabled': recorded_demo,
        'traffic_note': 'YOLO detections and validated one-minute scene forecasts inform camera-local ranking. Comparison weights are not measured delay or live ETAs; roads without cameras have unknown traffic.',
        'route_note': 'A passenger selection does not change any bus service.',
        'comparison_method': 'lowest observed pressure, then profile minutes' if goal == 'lowest_observed_traffic'
            else 'distance' if goal == 'shortest'
            else 'profile minutes + min(half profile minutes, 2 minutes × sum(camera pressure / 100))'}
