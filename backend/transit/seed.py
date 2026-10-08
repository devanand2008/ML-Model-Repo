"""Deterministic illustrative Salem network. Coordinates are canvas units, not GPS."""
from copy import deepcopy
import uuid
from sqlalchemy import select
from transit.models import (TransitRoute, TransitStop, TransitVehicle, TransitCamera,
                            TransitTrafficObservation, TransitSetting)

STOPS = [
    {"id":"S01","name":"New Bus Stand","x":380,"y":260,"essential":True,"terminal":True},
    {"id":"S02","name":"Five Roads","x":270,"y":180,"essential":True},
    {"id":"S03","name":"Suramangalam","x":110,"y":260,"essential":True},
    {"id":"S04","name":"Hasthampatti","x":530,"y":230,"essential":True},
    {"id":"S05","name":"Ammapet","x":690,"y":420,"essential":True},
    {"id":"S06","name":"Yercaud Road","x":660,"y":90,"essential":True},
    {"id":"S07","name":"Omalur Road","x":260,"y":65,"essential":True},
    {"id":"S08","name":"Mettur Road","x":90,"y":100,"essential":True},
    {"id":"S09","name":"Old Bus Stand","x":440,"y":450,"essential":True,"terminal":True},
    {"id":"S10","name":"Salem Junction","x":100,"y":430,"essential":True},
    {"id":"S11","name":"Fairlands","x":400,"y":120,"essential":True},
    {"id":"S12","name":"Gugai","x":320,"y":520,"essential":True},
]
_route_rows = [
    ("R01","New Bus Stand – Omalur Road",["S01","S02","S07"],4,48,"#00d9ff",28),
    ("R02","Suramangalam – Hasthampatti",["S03","S02","S01","S04"],2,30,"#2f80ed",74),
    ("R03","Junction – New Bus Stand",["S10","S03","S01"],3,42,"#a78bfa",48),
    ("R04","Bus Stand – Ammapet",["S01","S04","S05"],4,48,"#00e5a0",42),
    ("R05","Five Roads – Old Bus Stand",["S02","S01","S09"],3,54,"#ffb020",64),
    ("R06","Old Bus Stand – Gugai",["S09","S12"],2,36,"#f472b6",22),
    ("R07","Yercaud Road – Ammapet",["S06","S04","S05"],3,60,"#ff4d67",83),
    ("R08","Mettur Road – Fairlands",["S08","S02","S11"],3,42,"#22d3ee",36),
]
ROUTE_SPECS, SEGMENTS, CORRIDORS = [], [], []
_stops = {s["id"]:s for s in STOPS}
for number,(rid,name,stop_ids,buses,cycle,color,score) in enumerate(_route_rows,1):
    corridor_id = f"C{number:02}"
    variants = []
    for alternative in (False,True):
        segment_ids, geometry = [], []
        for j,(a,b) in enumerate(zip(stop_ids,stop_ids[1:])):
            sid = f"{rid}-{'alt' if alternative else 'base'}-{j}"
            pa,pb = _stops[a],_stops[b]
            points = [{"x":pa["x"],"y":pa["y"]}]
            if alternative:
                points.append({"x":(pa["x"]+pb["x"])/2+24,"y":(pa["y"]+pb["y"])/2-32})
            points.append({"x":pb["x"],"y":pb["y"]})
            SEGMENTS.append({"id":sid,"from_stop":a,"to_stop":b,"corridor_id":corridor_id,
                             "congestion_score":max(0,score-24) if alternative else score,
                             "geometry":points,"illustrative":True})
            segment_ids.append(sid)
            geometry.extend(points if not geometry else points[1:])
        variants.append({"id":"alternative" if alternative else "existing","name":"Alternative corridor" if alternative else "Existing route",
                         "stop_ids":stop_ids,"segment_ids":segment_ids,"geometry":geometry,
                         "cycle_minutes":round(cycle*1.12,1) if alternative else cycle,
                         "distance_km":round(cycle*.19*(1.12 if alternative else 1),1),"validated":True})
    ROUTE_SPECS.append({"id":rid,"name":name,"color":color,"stop_ids":stop_ids,"required_stop_ids":stop_ids,
                        "capacity":50,"bus_capacity":50,"current_buses":buses,"min_buses":1,
                        "max_headway_minutes":30,"cycle_minutes":cycle,"essential":True,
                        "current_variant_id":"existing","corridor_id":corridor_id,
                        "geometry":variants[0]["geometry"],"variants":variants,"source":"SYNTHETIC_DEMO_DATA"})
    CORRIDORS.append({"id":corridor_id,"name":name,"route_ids":[rid],"congestion_score":score})

CAMERAS = [{"id":f"CAM{i:02}","name":_stops[sid]["name"]+" demo camera", "stop_id":sid,
            "corridor_id":cid,"source_type":"upload_or_browser_camera","status":"awaiting_authorized_input"}
           for i,(sid,cid) in enumerate([("S01","C01"),("S02","C02"),("S03","C03"),("S04","C07"),("S05","C04")],1)]
NETWORK = {"coordinate_system":"illustrative_canvas","width":800,"height":600,
           "source":"SYNTHETIC_DEMO_DATA","disclaimer":"Illustrative Salem-inspired network; not official routes or geographic coordinates.",
           "stops":STOPS,"segments":SEGMENTS,"corridors":CORRIDORS,"cameras":CAMERAS,"routes":ROUTE_SPECS}
DEFAULT_SETTINGS = {"fleet_size":28,"reserve_fleet":4,"bus_capacity":50,"horizon_minutes":60,
                    "max_headway_minutes":30,"solver_time_limit_seconds":5,
                    "traffic_thresholds":{"moderate":25,"high":50,"severe":75},
                    "crowd_visible_thresholds":{"moderate":6,"high":15,"critical":30},
                    "vision_density_reference_vehicles":20,"default_confidence":0.5,
                    "raw_upload_retention_seconds":3600,"demo_mode":True,"schema_version":1,
                    "demand_multiplier":1,"event_intensity":"none","traffic_level":"current",
                    "weights":{"unserved":1,"waiting":1,"operating_cost":1,"traffic_delay":1,"stability":1},
                    "active_scenario_id":None}


async def seed_transit(db):
    if (await db.execute(select(TransitRoute.id).limit(1))).first():
        for key,value in DEFAULT_SETTINGS.items():
            if await db.get(TransitSetting,key) is None:
                db.add(TransitSetting(key=key,value=value))
        await db.commit()
        return
    for s in STOPS:
        db.add(TransitStop(id=s["id"],name=s["name"],x=s["x"],y=s["y"],essential=s["essential"]))
    for spec in ROUTE_SPECS:
        db.add(TransitRoute(id=spec["id"],name=spec["name"],spec=deepcopy(spec),current_buses=spec["current_buses"]))
    await db.flush()
    n = 1
    for route in ROUTE_SPECS:
        for _ in range(route["current_buses"]):
            db.add(TransitVehicle(id=f"BUS{n:03}",route_id=route["id"],capacity=50)); n += 1
    for i in range(n,29):
        db.add(TransitVehicle(id=f"BUS{i:03}",capacity=50,reserved=True))
    for camera in CAMERAS:
        db.add(TransitCamera(**camera))
    for c in CORRIDORS:
        score=c["congestion_score"]
        db.add(TransitTrafficObservation(id=uuid.uuid4().hex,corridor_id=c["id"],score=score,
            category="SEVERE" if score>=75 else "HIGH" if score>=50 else "MODERATE" if score>=25 else "LOW",
            source="SYNTHETIC_DEMO_DATA",payload={"vehicle_count":None,"average_speed_kmh":None,
                "queue_length":None,"data_quality":"synthetic_scenario","method":"Reproducible seeded scenario; not measured traffic."}))
    for key,value in DEFAULT_SETTINGS.items():
        db.add(TransitSetting(key=key,value=value))
    await db.commit()
