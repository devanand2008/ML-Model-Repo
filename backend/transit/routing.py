"""Provider road geometry and conservative bus progress estimates for configured stop sequences."""
import asyncio
import math
import time
import httpx
from fastapi import HTTPException
from config import settings
from transit.mobility import haversine_km

_cache = {}
_lock = asyncio.Lock()


async def service_road_route(stops):
    key = tuple((s['id'],s['latitude'],s['longitude']) for s in stops)
    saved = _cache.get(key)
    if saved and time.monotonic()-saved[0] < 3600:
        return saved[1]
    async with _lock:
        coords = ';'.join(f"{s['longitude']},{s['latitude']}" for s in stops)
        try:
            async with httpx.AsyncClient(timeout=12,headers={'User-Agent':'TransitOptAI-CollegePrototype/2.0'}) as client:
                response = await client.get(settings.osrm_base_url.rstrip('/')+'/route/v1/driving/'+coords,
                    params={'geometries':'geojson','overview':'full','steps':'false'})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError,ValueError) as exc:
            raise HTTPException(503,'Bus road geometry provider unavailable: '+type(exc).__name__)
        if payload.get('code') != 'Ok' or not payload.get('routes'):
            raise HTTPException(422,'No road route through this configured stop sequence')
        route = payload['routes'][0]
        if len(route.get('geometry',{}).get('coordinates',[])) < 2 or len(route.get('legs',[])) != len(stops)-1:
            raise HTTPException(503,'Routing provider returned incomplete service geometry')
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = (time.monotonic(),payload)
        return payload


def progress_estimate(payload,latitude,longitude):
    """Project onto the declared direction; distribute each provider leg's time by its road length."""
    route = payload['routes'][0]
    points = route['geometry']['coordinates']
    cumulative = [0.0]
    for (a_lon,a_lat),(b_lon,b_lat) in zip(points,points[1:]):
        cumulative.append(cumulative[-1]+haversine_km(a_lat,a_lon,b_lat,b_lon))
    scale_x = 111.195*math.cos(math.radians(latitude))
    scale_y = 111.195
    nearest = None
    for index,((a_lon,a_lat),(b_lon,b_lat)) in enumerate(zip(points,points[1:])):
        ax,ay = (a_lon-longitude)*scale_x,(a_lat-latitude)*scale_y
        bx,by = (b_lon-longitude)*scale_x,(b_lat-latitude)*scale_y
        dx,dy = bx-ax,by-ay
        fraction = min(1,max(0,-(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
        distance = math.hypot(ax+fraction*dx,ay+fraction*dy)
        along = cumulative[index]+fraction*(cumulative[index+1]-cumulative[index])
        if nearest is None or distance < nearest[0]:
            nearest = (distance,along)
    offsets = []
    lower_index = 0
    for waypoint in payload.get('waypoints',[]):
        lon,lat = waypoint['location']
        index = min(range(lower_index,len(points)),key=lambda i:haversine_km(lat,lon,points[i][1],points[i][0]))
        offsets.append(cumulative[index])
        lower_index = index
    if len(offsets) != len(route['legs'])+1:
        raise ValueError('Provider stop waypoints are incomplete')
    elapsed = 0.0
    elapsed_at_stops = [0.0]
    for index,leg in enumerate(route['legs']):
        duration = float(leg['duration'])/60
        start,end = offsets[index],offsets[index+1]
        if nearest[1] >= end:
            elapsed += duration
        elif nearest[1] > start and end > start:
            elapsed += duration*(nearest[1]-start)/(end-start)
        elapsed_at_stops.append(elapsed_at_stops[-1]+duration)
    return {'off_route_km':nearest[0],'distance_along_km':nearest[1],
            'elapsed_minutes':elapsed,'stop_distances_km':offsets,'stop_elapsed_minutes':elapsed_at_stops}
