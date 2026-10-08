"""Persisted transit application orchestration around real forecast and solver services."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import uuid
from sqlalchemy import select, func, insert
from fastapi import HTTPException
from config import BASE_DIR
from database import AsyncSessionLocal
from transit.models import *
from transit.seed import NETWORK, ROUTE_SPECS, DEFAULT_SETTINGS, seed_transit

forecast_service = None
_activation_lock = asyncio.Lock()


def iso(value):
    return value.isoformat()+"Z" if value else None


async def initialize():
    global forecast_service
    from services.transit_forecasting import TransitForecastService
    async with AsyncSessionLocal() as db:
        await seed_transit(db)
        from transit.mobility import seed_mobility
        await seed_mobility(db)
        # Running process interruptions cannot leave jobs falsely marked as processing.
        jobs=(await db.execute(select(TransitVisionJob).where(TransitVisionJob.status.in_(["queued","processing","paused","encoding"])))).scalars()
        for job in jobs:
            job.status="interrupted"
            job.payload={**job.payload,"error":"Server restarted; submit the source again."}
            if job.payload.get('camera_id'):
                camera=await db.get(TransitCamera,job.payload['camera_id'])
                if camera:
                    camera.status='offline'
        await db.commit()
    forecast_service=TransitForecastService(ROUTE_SPECS)
    await asyncio.to_thread(forecast_service.ensure_ready)
    async with AsyncSessionLocal() as db:
        if not (await db.execute(select(TransitDemandObservation.id).limit(1))).first():
            frame=forecast_service.history_frame
            # Persist the generated data in batches, keeping source features and ridership separate from crowds.
            records=[]
            for row in frame.to_dict("records"):
                timestamp=datetime.fromisoformat(str(row["timestamp"])).replace(tzinfo=None)
                features={k:(None if v!=v else v) for k,v in row.items() if k not in {"timestamp","route_id","stop_id","boardings","source"}}
                records.append({"route_id":row["route_id"],"stop_id":row["stop_id"],"timestamp":timestamp,
                                "boardings":float(row["boardings"]),"source":"SYNTHETIC_DEMO_DATA","features":features})
                if len(records)>=2000:
                    await db.execute(insert(TransitDemandObservation),records); records=[]
            if records:
                await db.execute(insert(TransitDemandObservation),records)
            await db.commit()


async def settings_dict(db):
    rows=(await db.execute(select(TransitSetting))).scalars().all()
    return {**DEFAULT_SETTINGS,**{r.key:r.value for r in rows}}


async def routes_list(db):
    records=(await db.execute(select(TransitRoute).order_by(TransitRoute.id))).scalars().all()
    config=await settings_dict(db)
    return [{**r.spec,"current_buses":r.current_buses,"current_variant_id":r.current_variant_id,
             "capacity":config["bus_capacity"],"bus_capacity":config["bus_capacity"],
             "effective_max_headway_minutes":min(r.spec["max_headway_minutes"],config["max_headway_minutes"]),
             "cycle_minutes":next((v["cycle_minutes"] for v in r.spec["variants"] if v["id"]==r.current_variant_id),r.spec["cycle_minutes"]),
             "geometry":next((v["geometry"] for v in r.spec["variants"] if v["id"]==r.current_variant_id),r.spec["geometry"])} for r in records]


def camera_dict(camera):
    return {"id":camera.id,"name":camera.name,"stop_id":camera.stop_id,"corridor_id":camera.corridor_id,
            "roi":camera.roi,"status":camera.status,"source_type":camera.source_type}


async def traffic_corridors(db):
    observations=(await db.execute(select(TransitTrafficObservation).order_by(TransitTrafficObservation.timestamp.desc()))).scalars().all()
    latest={}
    for observation in observations:
        if observation.corridor_id not in latest:
            latest[observation.corridor_id]=observation
    result=[]
    for c in NETWORK["corridors"]:
        o=latest.get(c["id"])
        result.append({**c,"congestion_score":o.score if o else c["congestion_score"],"category":o.category if o else "Unavailable",
                       "source":o.source if o else "SYNTHETIC_DEMO_DATA","timestamp":iso(o.timestamp) if o else None,
                       **(o.payload if o else {}),"camera_id":o.camera_id if o else None})
    return result


async def network_dict(db):
    result=deepcopy(NETWORK)
    result["routes"]=await routes_list(db)
    from transit.models import TransitCameraSetup
    road_ids={s.camera_id for s in (await db.execute(select(TransitCameraSetup).where(
        TransitCameraSetup.role=="road_traffic"))).scalars()}
    result["cameras"]=[camera_dict(c) for c in (await db.execute(select(TransitCamera).order_by(TransitCamera.id))).scalars()
                       if c.id in road_ids]
    result["corridors"]=await traffic_corridors(db)
    scores={c["id"]:c["congestion_score"] for c in result["corridors"]}
    for segment in result["segments"]:
        # Alternative scores retain the documented hypothetical corridor discount.
        segment["congestion_score"]=max(0,scores.get(segment["corridor_id"],0)-(24 if "-alt-" in segment["id"] else 0))
    latest_timestamp=(await db.execute(select(func.max(TransitDemandObservation.timestamp)))).scalar()
    boardings={row[0]:float(row[1]) for row in (await db.execute(select(TransitDemandObservation.stop_id,
        func.sum(TransitDemandObservation.boardings)).where(TransitDemandObservation.timestamp==latest_timestamp)
        .group_by(TransitDemandObservation.stop_id))).all()} if latest_timestamp else {}
    latest_crowds={}
    camera_stops={c["id"]:c["stop_id"] for c in result["cameras"]}
    events=(await db.execute(select(TransitDetectionEvent).where(TransitDetectionEvent.camera_id!=None)
        .order_by(TransitDetectionEvent.timestamp.desc()).limit(1000))).scalars()
    for event in events:
        stop_id=camera_stops.get(event.camera_id)
        if stop_id and stop_id not in latest_crowds:
            latest_crowds[stop_id]=event
    scenario_time=latest_timestamp.isoformat()+"+05:30" if latest_timestamp else None
    result["stop_metrics"]=[{"stop_id":stop["id"],"boarding_demand":boardings.get(stop["id"],0),
        "source":"SYNTHETIC_DEMO_DATA","interval_minutes":30,"timestamp":scenario_time,
        "crowd_count":latest_crowds[stop["id"]].payload.get("people_count") if stop["id"] in latest_crowds else None,
        "crowd_source":"REAL_MODEL_DETECTION" if stop["id"] in latest_crowds else None,
        "crowd_timestamp":iso(latest_crowds[stop["id"]].timestamp) if stop["id"] in latest_crowds else None}
        for stop in result["stops"]]
    result["as_of"]=scenario_time
    result["updated_at"]=datetime.now(timezone.utc).isoformat()
    return result


def require_forecaster():
    if forecast_service is None:
        raise HTTPException(503,"Forecast model is initializing; retry shortly.")
    return forecast_service


async def forecast_all(horizon,db=None,net=None,config=None):
    if db is None:
        return await asyncio.to_thread(require_forecaster().forecast_all,horizon)
    from services.transit_optimizer import evaluate_plan
    net=net or await network_dict(db)
    config=config or await settings_dict(db)
    evaluation=evaluate_plan(net["routes"],net,{r["id"]:0 for r in net["routes"]},{**config,"horizon_minutes":horizon})
    capacity={r["route_id"]:r["capacity"] for r in evaluation["routes"]}
    recent=(await db.execute(select(TransitDetectionEvent).where(TransitDetectionEvent.camera_id!=None).order_by(TransitDetectionEvent.timestamp.desc()).limit(100))).scalars().all()
    from transit.models import TransitCameraSetup
    road_ids={s.camera_id for s in (await db.execute(select(TransitCameraSetup).where(
        TransitCameraSetup.role=="road_traffic"))).scalars()}
    camera_stops={c.id:c.stop_id for c in (await db.execute(select(TransitCamera))).scalars() if c.id in road_ids}
    counts={}
    for event in recent:
        sid=camera_stops.get(event.camera_id)
        if sid and sid not in counts and (datetime.utcnow()-event.timestamp).total_seconds()<900:
            counts[sid]=event.payload.get("mean_people_per_frame",event.payload.get("people_count",0))
    forecasts=[]
    for route in net["routes"]:
        observed=[counts[sid] for sid in route["stop_ids"] if sid in counts]
        crowd=sum(observed) if observed else None
        result=await asyncio.to_thread(require_forecaster().forecast,route["id"],None,horizon,None,capacity.get(route["id"],0),crowd)
        if crowd is not None:
            result["crowd_signal_source"]="REAL_MODEL_DETECTION"
            result["crowd_signal_note"]="Recent observed crowd injected into synthetic scenario model; not measured boardings."
        forecasts.append(result)
    return {"horizon_minutes":horizon,"forecast_at":forecasts[0]["forecast_at"] if forecasts else None,
            "model_version":forecasts[0].get("model_version") if forecasts else None,"source":"ML_FORECAST",
            "data_source":"SYNTHETIC_DEMO_DATA","forecasts":forecasts}


async def store_forecast(db,payload):
    fid=uuid.uuid4().hex
    payload={**payload,"id":fid}
    db.add(TransitForecast(id=fid,route_id=payload["route_id"],stop_id=payload.get("stop_id"),
        horizon_minutes=payload["horizon_minutes"],predicted_demand=payload["predicted_passengers"],
        model_version=payload.get("model_version","unknown"),payload=payload))
    return payload


def recommendation_dict(row):
    return {**row.payload,"id":row.id,"run_id":row.run_id,"route_id":row.route_id,"status":row.status,
            "proposed_buses":row.proposed_buses,"proposed_variant_id":row.proposed_variant_id,"timestamp":iso(row.timestamp)}


async def recommendations(db,run_id=None):
    query=select(TransitRecommendation).order_by(TransitRecommendation.timestamp.desc())
    if run_id:
        query=query.where(TransitRecommendation.run_id==run_id)
    return [recommendation_dict(row) for row in (await db.execute(query)).scalars()]


async def run_optimization(db,inputs):
    from services.transit_optimizer import optimize_plan
    config=await settings_dict(db)
    config.update({k:v for k,v in inputs.items() if v is not None and k!="name"})
    net=await network_dict(db)
    forecasts=await forecast_all(config.get("horizon_minutes",60),db,net,config)
    demand={f["route_id"]:f["predicted_passengers"] for f in forecasts["forecasts"]}
    # Crowd counts are an observed, explicitly estimated model covariate where supported.
    # Crowd-to-boardings conversion is intentionally not fabricated here.
    result=await asyncio.to_thread(optimize_plan,net["routes"],net,demand,config)
    config=result.get("config",config)
    run_id,scenario_id=uuid.uuid4().hex,uuid.uuid4().hex
    result={**result,"id":run_id,"run_id":run_id,"scenario_id":scenario_id,"config":config,"plan_approved":False,"activated":False,
            "source":"OPTIMIZATION_RESULT","data_source":"SYNTHETIC_DEMO_DATA","forecast":forecasts,
            "timestamp":datetime.now(timezone.utc).isoformat()}
    db.add(TransitOptimizationRun(id=run_id,config=config,solver_status=result["solver_status"],feasible=result["feasible"],
        results={**result,"snapshot":{"routes":net["routes"],"network":net,"demand_by_route":demand,
            "active_scenario_id":config.get("active_scenario_id")}}))
    await db.flush()
    if result["feasible"]:
        current={r["id"]:r for r in net["routes"]}
        for proposal in result["routes"]:
            route=current[proposal["route_id"]]
            if proposal["buses"]!=route["current_buses"] or proposal["variant_id"]!=route["current_variant_id"]:
                rid=uuid.uuid4().hex
                db.add(TransitRecommendation(id=rid,run_id=run_id,route_id=route["id"],proposed_buses=proposal["buses"],
                    proposed_variant_id=proposal["variant_id"],payload={**proposal,"current_buses":route["current_buses"],
                        "current_variant_id":route["current_variant_id"],"source":"OPTIMIZATION_RESULT"}))
    db.add(TransitScenario(id=scenario_id,name=inputs.get("name") or "Salem what-if scenario",run_id=run_id,
        inputs=config,baseline=result.get("baseline",{}),optimized=result.get("totals",{}),payload=result))
    for f in forecasts["forecasts"]:
        await store_forecast(db,f)
    await db.commit()
    result["recommendations"]=await recommendations(db,run_id)
    return result


async def stored_result(db,run_id):
    run=await db.get(TransitOptimizationRun,run_id)
    if not run:
        raise HTTPException(404,"Optimization run not found")
    result={k:v for k,v in run.results.items() if k!="snapshot"}
    result["recommendations"]=await recommendations(db,run_id)
    result["activated"]=bool((await db.execute(select(TransitScenario).where(TransitScenario.run_id==run_id,TransitScenario.activated==True))).first())
    approvals=(await db.execute(select(TransitOperatorAction).where(TransitOperatorAction.action=="approve_plan"))).scalars()
    result["plan_approved"]=any(action.payload.get("run_id")==run_id for action in approvals)
    return result


async def operator_action(db,rec,action,operator,note=""):
    allowed={"approve":{"pending_review"},"reject":{"pending_review","approved"}}
    if rec.status not in allowed[action]:
        raise HTTPException(409,f"Cannot {action} recommendation in {rec.status} state")
    rec.status="approved" if action=="approve" else "rejected"
    db.add(TransitOperatorAction(id=uuid.uuid4().hex,recommendation_id=rec.id,action=action,operator=operator,
        payload={"run_id":rec.run_id,"route_id":rec.route_id,"note":note}))


async def activate_run(db,run_id,operator):
    from services.transit_optimizer import evaluate_plan, DEFAULT_CONFIG
    async with _activation_lock:
        run=await db.get(TransitOptimizationRun,run_id)
        if not run:
            raise HTTPException(404,"Optimization run not found")
        if not run.feasible:
            raise HTTPException(409,"An infeasible plan cannot be activated")
        recs=(await db.execute(select(TransitRecommendation).where(TransitRecommendation.run_id==run_id))).scalars().all()
        if any(r.status!="approved" for r in recs):
            raise HTTPException(409,"Approve every changed-route recommendation in this plan before activation")
        if not recs:
            approval_actions=(await db.execute(select(TransitOperatorAction).where(TransitOperatorAction.action=="approve_plan"))).scalars()
            if not any(action.payload.get("run_id")==run_id for action in approval_actions):
                raise HTTPException(409,"Explicitly approve the complete plan before activating this unchanged scenario")
        scenario=(await db.execute(select(TransitScenario).where(TransitScenario.run_id==run_id))).scalars().first()
        if scenario and scenario.activated:
            raise HTTPException(409,"This scenario is already activated")
        snapshot=run.results["snapshot"]
        current_config=await settings_dict(db)
        if current_config.get("active_scenario_id")!=snapshot.get("active_scenario_id"):
            raise HTTPException(409,"Active simulation changed since this run. Run optimization again before activation.")
        current=await routes_list(db)
        current_by_id={r["id"]:r for r in current}
        if any(current_by_id[r["id"]]["current_buses"]!=r["current_buses"] or current_by_id[r["id"]]["current_variant_id"]!=r["current_variant_id"] for r in snapshot["routes"]):
            raise HTTPException(409,"Operating plan changed since this run. Run optimization again before activation.")
        validated=await asyncio.to_thread(evaluate_plan,snapshot["routes"],snapshot["network"],snapshot["demand_by_route"],run.config,run.results["routes"])
        if not validated.get("feasible",True):
            raise HTTPException(409,"Stored plan failed constraint validation")
        records=(await db.execute(select(TransitRoute))).scalars().all()
        proposed={r["route_id"]:r for r in run.results["routes"]}
        for route in records:
            route.current_buses=proposed[route.id]["buses"]
            route.current_variant_id=proposed[route.id]["variant_id"]
        # Update the complete vehicle assignment and fleet in the same transaction as route allocations.
        existing=(await db.execute(select(TransitVehicle).order_by(TransitVehicle.id))).scalars().all()
        fleet=int(run.config["fleet_size"])
        while len(existing)<fleet:
            vehicle=TransitVehicle(id=f"BUS{len(existing)+1:03}",capacity=int(run.config["bus_capacity"]))
            db.add(vehicle);existing.append(vehicle)
        for vehicle in existing:
            vehicle.capacity=int(run.config["bus_capacity"])
        cursor=0
        for route in records:
            for _ in range(route.current_buses):
                vehicle=existing[cursor];vehicle.route_id=route.id;vehicle.reserved=False;vehicle.available=True;cursor+=1
        for index,vehicle in enumerate(existing[cursor:],cursor):
            vehicle.route_id=None;vehicle.available=index<fleet;vehicle.reserved=index<fleet and index>=fleet-int(run.config["reserve_fleet"])
        for key in DEFAULT_CONFIG:
            setting=await db.get(TransitSetting,key)
            if setting:
                setting.value=run.config[key]
            else:
                db.add(TransitSetting(key=key,value=run.config[key]))
        setting=await db.get(TransitSetting,"active_scenario_id")
        if setting:
            setting.value=scenario.id if scenario else None
        else:
            db.add(TransitSetting(key="active_scenario_id",value=scenario.id if scenario else None))
        for rec in recs:
            rec.status="activated"
            db.add(TransitOperatorAction(id=uuid.uuid4().hex,recommendation_id=rec.id,action="activate_simulation",operator=operator,
                payload={"run_id":run_id,"whole_plan":True,"simulation_only":True}))
        db.add(TransitOperatorAction(id=uuid.uuid4().hex,action="activate_plan_simulation",operator=operator,
            payload={"run_id":run_id,"scenario_id":scenario.id if scenario else None,"whole_plan":True,"simulation_only":True}))
        if scenario:
            scenario.activated=True
        await db.commit()
        return {"success":True,"run_id":run_id,"scenario_id":scenario.id if scenario else None,"simulation_only":True,
                "routes":await routes_list(db),"message":"Complete approved plan activated in the local simulation."}


async def dashboard(db):
    from services.transit_optimizer import evaluate_plan
    config=await settings_dict(db)
    net=await network_dict(db)
    forecast=await forecast_all(config["horizon_minutes"],db,net,config)
    demand={f["route_id"]:f["predicted_passengers"] for f in forecast["forecasts"]}
    plan=await asyncio.to_thread(evaluate_plan,net["routes"],net,demand,config)
    totals=plan.get("totals",plan.get("metrics",{}))
    recs=await recommendations(db)
    allocated=sum(r["current_buses"] for r in net["routes"])
    def metric(*names,default=0):
        return next((totals[n] for n in names if n in totals),default)
    kpis={"available_buses":config["fleet_size"],"allocated_buses":allocated,"reserve_buses":config["reserve_fleet"],
          "forecast_passenger_demand":metric("forecast_demand",default=round(sum(demand.values()))),
          "raw_ml_forecast_demand":round(sum(demand.values()),2),
          "capacity_shortfall":metric("capacity_shortfall","unserved_demand","total_unserved_demand"),
          "average_waiting_time_minutes":metric("average_waiting_time_minutes","average_wait_minutes","avg_wait_minutes"),
          "fleet_utilization_pct":round(allocated/config["fleet_size"]*100,1),
          "high_congestion_corridors":sum(c["congestion_score"]>=50 for c in net["corridors"]),
          "active_ai_recommendations":sum(r["status"] in {"pending_review","approved"} for r in recs)}
    factor=config.get("demand_multiplier",1)*{"none":1,"moderate":1.1,"high":1.25}[config.get("event_intensity","none")]
    return {"source":"SYNTHETIC_DEMO_DATA","data_labels":["REAL_MODEL_DETECTION","SYNTHETIC_DEMO_DATA","ML_FORECAST","OPTIMIZATION_RESULT"],
            "raw_ml_forecast_demand":round(sum(demand.values()),2),"scenario_factor":factor,
            "active_planning_inputs":{"scenario_id":config.get("active_scenario_id"),"demand_multiplier":config.get("demand_multiplier",1),
                "event_intensity":config.get("event_intensity","none"),"traffic_level":config.get("traffic_level","current"),
                "horizon_minutes":config["horizon_minutes"],"bus_capacity":config["bus_capacity"],"weights":config.get("weights"),
                "demand_source":"ML_FORECAST_WITH_ACTIVE_SCENARIO","rounding_method":"Round up adjusted demand once per route for conservative capacity checks."},
            "settings":config,"kpis":kpis,"traffic":net["corridors"],"forecast":forecast,"plan":plan,"recommendations":recs[:12],
            "system":{"forecast":require_forecaster().status(),"simulation_only":True},"as_of":forecast.get("forecast_at"),
            "updated_at":datetime.now(timezone.utc).isoformat()}
