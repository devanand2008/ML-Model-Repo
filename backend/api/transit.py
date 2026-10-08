"""Connected TransitOpt APIs using the existing database, authentication and model adapters."""
import asyncio
import csv
import io
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import subprocess
import os
import time
import uuid
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from config import settings, BASE_DIR
from database import get_db, AsyncSessionLocal, AIModel
from security import require_user, inference_limit
from transit import service
from transit.models import *
from transit.schemas import ForecastRequest, OptimizationRequest, OperatorRequest, CameraRequest, SettingsRequest
from transit.vision import persist_observation, camera_for, summarize, normalize_detections

router=APIRouter(dependencies=[Depends(require_user)])
_video_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="transit-video")
_jobs={}
_tasks=set()
_ACTIVE_JOB_STATES={"queued","processing","paused","encoding"}


def encode_browser_video(output,job):
    """Encode the existing genuine annotated frames for HTML5 playback, without shell execution."""
    import imageio_ffmpeg
    temporary=output.with_name(output.stem+".h264.mp4")
    job.update(status="encoding",stage="encoding_browser_preview",progress=95)
    args=[imageio_ffmpeg.get_ffmpeg_exe(),"-hide_banner","-loglevel","error","-y","-i",str(output),
          "-vf","pad=ceil(iw/2)*2:ceil(ih/2)*2","-an","-c:v","libx264","-preset","veryfast","-crf","23",
          "-pix_fmt","yuv420p","-movflags","+faststart",str(temporary)]
    process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    started=time.monotonic()
    try:
        while process.poll() is None:
            if job["status"]=="cancelled":
                raise InterruptedError("Video encoding cancelled by operator")
            if time.monotonic()-started>300:
                raise TimeoutError("Browser preview encoding exceeded five minutes")
            time.sleep(.1)
        _,stderr=process.communicate()
        if process.returncode or not temporary.exists() or not temporary.stat().st_size:
            raise ValueError("Browser video encoding failed: "+stderr.decode("utf-8",errors="replace")[-300:])
        temporary.replace(output)
    finally:
        if process.poll() is None:
            process.kill();process.communicate()
        temporary.unlink(missing_ok=True)


def capabilities():
    return {"image":True,"video":True,"browser_camera":True,"tracking":True,"regions_of_interest":True,
            "rtsp":False,"network_camera":False,"physical_speed":False,"queue_length":False,
            "bus_gps_speed":True,"moving_bus_congestion_fusion":True,
            "rtsp_reason":"Authorized network stream ingestion is not configured. Use an authorized uploaded recording or browser camera.",
            "simulation_only":True,"existing_visionx_preserved":True}


@router.get("/network")
async def network(db:AsyncSession=Depends(get_db)) -> dict:
    return await service.network_dict(db)


@router.get("/routes")
async def routes(db:AsyncSession=Depends(get_db)) -> dict:
    rows=await service.routes_list(db)
    return {"routes":rows,"items":rows,"source":"SYNTHETIC_DEMO_DATA"}


@router.get("/routes/{route_id}")
async def route(route_id:str,db:AsyncSession=Depends(get_db)) -> dict:
    rows=await service.routes_list(db)
    found=next((r for r in rows if r["id"]==route_id),None)
    if not found:
        raise HTTPException(404,"Route not found")
    return found


@router.get("/stops")
async def stops(db:AsyncSession=Depends(get_db)) -> dict:
    rows=(await service.network_dict(db))["stops"]
    return {"stops":rows,"items":rows,"source":"SYNTHETIC_DEMO_DATA"}


@router.get("/cameras")
async def cameras(db:AsyncSession=Depends(get_db)) -> dict:
    from transit.models import TransitCameraSetup
    rows=[]
    for camera in (await db.execute(select(TransitCamera).order_by(TransitCamera.id))).scalars():
        from transit.mobility import camera_runtime
        setup=await db.get(TransitCameraSetup,camera.id)
        rows.append({**service.camera_dict(camera),**(await camera_runtime(db,camera)),"role":setup.role if setup else "unconfigured",
            "bus_id":setup.bus_id if setup else None,
            "latitude":setup.latitude if setup else None,"longitude":setup.longitude if setup else None,
            "coordinate_source":setup.coordinate_source if setup else "unconfigured"})
    return {"cameras":rows,"items":rows,"capabilities":capabilities()}


@router.patch("/cameras/{camera_id}")
async def configure_camera(camera_id:str,request:CameraRequest,db:AsyncSession=Depends(get_db)) -> dict:
    camera=await camera_for(db,camera_id)
    camera.roi=request.roi
    await db.commit()
    return service.camera_dict(camera)


@router.get("/settings")
async def get_settings(db:AsyncSession=Depends(get_db)) -> dict:
    return {"settings":await service.settings_dict(db),"capabilities":capabilities()}


@router.patch("/settings")
async def update_settings(request:SettingsRequest,db:AsyncSession=Depends(get_db)) -> dict:
    current=await service.settings_dict(db)
    updates=request.model_dump(exclude_none=True)
    candidate={**current,**updates}
    allocated=sum(r["current_buses"] for r in await service.routes_list(db))
    if candidate["fleet_size"]-candidate["reserve_fleet"]<allocated:
        raise HTTPException(409,"Settings cannot reduce the active fleet below its allocation plus reserve. Use the what-if simulator and approve a valid plan.")
    for key,value in updates.items():
        record=await db.get(TransitSetting,key)
        if record:
            record.value=value
        else:
            db.add(TransitSetting(key=key,value=value))
    # Fleet settings represent synthetic inventory and must stay consistent with its vehicle rows.
    if "fleet_size" in updates or "reserve_fleet" in updates:
        inventory=(await db.execute(select(TransitVehicle).order_by(TransitVehicle.id))).scalars().all()
        while len(inventory)<candidate["fleet_size"]:
            vehicle=TransitVehicle(id=f"BUS{len(inventory)+1:03}",capacity=candidate["bus_capacity"])
            db.add(vehicle);inventory.append(vehicle)
        for i,vehicle in enumerate(inventory):
            vehicle.available=i<candidate["fleet_size"]
            vehicle.reserved=i>=candidate["fleet_size"]-candidate["reserve_fleet"] and i<candidate["fleet_size"]
    if "bus_capacity" in updates:
        for vehicle in (await db.execute(select(TransitVehicle))).scalars():
            vehicle.capacity=updates["bus_capacity"]
    await db.commit()
    return await get_settings(db)


@router.get("/traffic/corridors")
async def corridors(db:AsyncSession=Depends(get_db)) -> dict:
    rows=await service.traffic_corridors(db)
    return {"corridors":rows,"items":rows}


@router.get("/traffic/events")
async def traffic_events(db:AsyncSession=Depends(get_db)) -> dict:
    rows=await service.traffic_corridors(db)
    events=[{"id":c["id"]+"-congestion","title":"Heavy congestion detected" if c["source"]=="REAL_MODEL_DETECTION" else "Synthetic congestion scenario",
             "corridor_id":c["id"],"corridor":c["name"],"severity":c["category"],"category":c["category"],
             "congestion_score":c["congestion_score"],"route_ids":c["route_ids"],"source":c["source"],"timestamp":c["timestamp"],
             "suggested_action":"Run route optimization","delay_minutes":None} for c in rows if c["congestion_score"]>=50]
    crowd=(await db.execute(select(TransitDetectionEvent).order_by(TransitDetectionEvent.timestamp.desc()).limit(100))).scalars().all()
    seen=set()
    for o in crowd:
        if o.camera_id and o.camera_id not in seen:
            seen.add(o.camera_id)
            if o.payload.get("crowd_level")=="HIGH":
                events.append({"id":o.id,"title":"High crowd observation","camera_id":o.camera_id,"severity":"HIGH",
                               "people_count":o.payload.get("people_count"),"source":"REAL_MODEL_DETECTION",
                               "timestamp":service.iso(o.timestamp),"suggested_action":"Review estimated crowd signal; detected people are not measured ridership."})
    return {"events":events,"items":events}


@router.get("/traffic/summary")
async def traffic_summary(db:AsyncSession=Depends(get_db)) -> dict:
    rows=await service.traffic_corridors(db)
    return {"corridors":rows,"events":(await traffic_events(db))["events"],
            "high_congestion_corridors":sum(c["congestion_score"]>=50 for c in rows),
            "observed_vehicles":sum(c.get("vehicle_count") or 0 for c in rows),"average_speed_kmh":None}


@router.get("/demand/history")
async def demand_history(route_id:str="R02",stop_id:str|None=None,limit:int=Query(48,ge=1,le=500)) -> dict:
    try:
        return await asyncio.to_thread(service.require_forecaster().history,route_id,stop_id,limit)
    except (ValueError,KeyError) as exc:
        raise HTTPException(422,str(exc)) from exc


@router.post("/demand/forecast")
async def demand_forecast(request:ForecastRequest,db:AsyncSession=Depends(get_db)) -> dict:
    from services.transit_optimizer import evaluate_plan
    config=await service.settings_dict(db)
    net=await service.network_dict(db)
    routes_by_id={r["id"]:r for r in net["routes"]}
    if request.stop_id and request.stop_id not in routes_by_id[request.route_id]["stop_ids"]:
        raise HTTPException(422,"Selected stop is not served by this route")
    # Evaluate actual simulated capacity with the same headway/cycle assumptions as optimization.
    assessment=evaluate_plan(net["routes"],net,{r["id"]:0 for r in net["routes"]},{**config,"horizon_minutes":request.horizon_minutes})
    capacity=next(r["capacity"] for r in assessment["routes"] if r["route_id"]==request.route_id)
    if request.stop_id:
        frame=service.require_forecaster().history_frame
        observed=frame[frame["route_id"]==request.route_id]
        origin=service.require_forecaster()._parse_origin(request.forecast_at) if request.forecast_at else observed["timestamp"].max()
        import pandas as pd
        recent=observed[(observed["timestamp"]<=origin)&(observed["timestamp"]>origin-pd.Timedelta(days=7))]
        share=recent[recent["stop_id"]==request.stop_id]["boardings"].sum()/max(1,recent["boardings"].sum())
        capacity=round(capacity*float(share),2)
    latest=(await db.execute(select(TransitDetectionEvent).join(TransitCameraSetup,
        TransitDetectionEvent.camera_id==TransitCameraSetup.camera_id).where(
        TransitCameraSetup.role=='road_traffic').order_by(TransitDetectionEvent.timestamp.desc()).limit(100))).scalars().all()
    camera_rows={c.id:c for c in (await db.execute(select(TransitCamera))).scalars()}
    current_origin=service.require_forecaster().history_frame["timestamp"].max()
    historical_origin=request.forecast_at is not None and service.require_forecaster()._parse_origin(request.forecast_at)<current_origin
    crowd_event=next((o for o in latest if o.camera_id in camera_rows
        and camera_rows[o.camera_id].stop_id in routes_by_id[request.route_id]["stop_ids"]
        and (not request.stop_id or camera_rows[o.camera_id].stop_id==request.stop_id)
        and (datetime.utcnow()-o.timestamp).total_seconds()<900),None) if not historical_origin else None
    crowd=crowd_event.payload.get("mean_people_per_frame") if crowd_event else None
    try:
        result=await asyncio.to_thread(service.require_forecaster().forecast,request.route_id,request.stop_id,
            request.horizon_minutes,request.forecast_at,capacity,crowd)
    except (ValueError,KeyError) as exc:
        raise HTTPException(422,str(exc)) from exc
    result["capacity_method"]="Current simulated bus allocation and congestion-adjusted cycle; selected stop uses only preceding seven-day boarding share."
    if crowd_event:
        result["crowd_signal_source"]="REAL_MODEL_DETECTION"
        result["crowd_signal_timestamp"]=service.iso(crowd_event.timestamp)
        result["crowd_signal_note"]="Recent actual crowd used as a planning covariate in the synthetic scenario, not converted into boardings."
    result=await service.store_forecast(db,result)
    await db.commit()
    return result


@router.get("/demand/forecasts")
async def forecasts(db:AsyncSession=Depends(get_db)) -> dict:
    rows=[r.payload for r in (await db.execute(select(TransitForecast).order_by(TransitForecast.timestamp.desc()).limit(100))).scalars()]
    return {"forecasts":rows,"items":rows}


@router.post("/optimization/run")
@router.post("/simulator/run")
async def optimize(request:OptimizationRequest,db:AsyncSession=Depends(get_db)) -> dict:
    return await service.run_optimization(db,request.model_dump(exclude_none=True))


@router.get("/optimization/results/{run_id}")
async def optimization_result(run_id:str,db:AsyncSession=Depends(get_db)) -> dict:
    return await service.stored_result(db,run_id)


@router.get("/recommendations")
async def recs(run_id:str|None=None,db:AsyncSession=Depends(get_db)) -> dict:
    rows=await service.recommendations(db,run_id)
    return {"recommendations":rows,"items":rows}


@router.post("/recommendations/{recommendation_id}/approve")
async def approve(recommendation_id:str,request:OperatorRequest=OperatorRequest(),db:AsyncSession=Depends(get_db),operator=Depends(require_user)) -> dict:
    rec=await db.get(TransitRecommendation,recommendation_id)
    if not rec:
        raise HTTPException(404,"Recommendation not found")
    await service.operator_action(db,rec,"approve",operator,request.note)
    await db.commit()
    return service.recommendation_dict(rec)


@router.post("/recommendations/{recommendation_id}/reject")
async def reject(recommendation_id:str,request:OperatorRequest=OperatorRequest(),db:AsyncSession=Depends(get_db),operator=Depends(require_user)) -> dict:
    rec=await db.get(TransitRecommendation,recommendation_id)
    if not rec:
        raise HTTPException(404,"Recommendation not found")
    await service.operator_action(db,rec,"reject",operator,request.note)
    await db.commit()
    return service.recommendation_dict(rec)


@router.post("/optimization/results/{run_id}/approve")
async def approve_plan(run_id:str,request:OperatorRequest=OperatorRequest(),db:AsyncSession=Depends(get_db),operator=Depends(require_user)) -> dict:
    await service.stored_result(db,run_id)
    records=(await db.execute(select(TransitRecommendation).where(TransitRecommendation.run_id==run_id))).scalars().all()
    if any(r.status in {"rejected","activated"} for r in records):
        raise HTTPException(409,"Rejected or activated plans cannot be approved")
    for rec in records:
        if rec.status=="pending_review":
            await service.operator_action(db,rec,"approve",operator,request.note)
    db.add(TransitOperatorAction(id=uuid.uuid4().hex,action="approve_plan",operator=operator,
        payload={"run_id":run_id,"note":request.note,"whole_plan":True}))
    await db.commit()
    return await service.stored_result(db,run_id)


@router.post("/optimization/results/{run_id}/activate-simulation")
async def activate_plan(run_id:str,db:AsyncSession=Depends(get_db),operator=Depends(require_user)) -> dict:
    return await service.activate_run(db,run_id,operator)


@router.post("/recommendations/{recommendation_id}/activate-simulation")
async def activate_recommendation(recommendation_id:str,db:AsyncSession=Depends(get_db),operator=Depends(require_user)) -> dict:
    rec=await db.get(TransitRecommendation,recommendation_id)
    if not rec:
        raise HTTPException(404,"Recommendation not found")
    return await service.activate_run(db,rec.run_id,operator)


def scenario_dict(row):
    return {"id":row.id,"name":row.name,"run_id":row.run_id,"inputs":row.inputs,"baseline":row.baseline,
            "optimized":row.optimized,"result":row.payload,"activated":row.activated,"timestamp":service.iso(row.timestamp)}


@router.get("/simulator/scenarios")
async def scenarios(db:AsyncSession=Depends(get_db)) -> dict:
    rows=[scenario_dict(r) for r in (await db.execute(select(TransitScenario).order_by(TransitScenario.timestamp.desc()))).scalars()]
    return {"scenarios":rows,"items":rows}


@router.get("/simulator/results/{scenario_id}")
async def scenario_result(scenario_id:str,db:AsyncSession=Depends(get_db)) -> dict:
    row=await db.get(TransitScenario,scenario_id)
    if not row:
        raise HTTPException(404,"Scenario not found")
    return scenario_dict(row)


@router.get("/dashboard/summary")
async def dashboard(db:AsyncSession=Depends(get_db)) -> dict:
    return await service.dashboard(db)


@router.get("/dashboard/analytics")
async def analytics(db:AsyncSession=Depends(get_db)) -> dict:
    runs=(await db.execute(select(TransitOptimizationRun).order_by(TransitOptimizationRun.timestamp.desc()).limit(30))).scalars().all()
    traffic=(await db.execute(select(TransitTrafficObservation).order_by(TransitTrafficObservation.timestamp.desc()).limit(200))).scalars().all()
    actions=(await db.execute(select(TransitOperatorAction).order_by(TransitOperatorAction.timestamp.desc()).limit(100))).scalars().all()
    return {"runs":[{"id":r.id,"timestamp":service.iso(r.timestamp),"solver_status":r.solver_status,
                     "baseline":r.results.get("baseline"),"totals":r.results.get("totals"),"comparison":r.results.get("comparison"),"config":r.config} for r in runs],
            "traffic":[{"id":r.id,"timestamp":service.iso(r.timestamp),"corridor_id":r.corridor_id,"congestion_score":r.score,"source":r.source} for r in traffic],
            "operator_actions":[{"id":r.id,"action":r.action,"operator":r.operator,"timestamp":service.iso(r.timestamp),**r.payload} for r in actions],
            "forecast_model":service.require_forecaster().status(),
            "stored_demand_rows":(await db.execute(select(func.count()).select_from(TransitDemandObservation))).scalar_one(),
            "source":"PERSISTED_APPLICATION_STATE"}


@router.get("/system/status")
async def system_status(db:AsyncSession=Depends(get_db)) -> dict:
    return {"status":"ready","capabilities":capabilities(),"database":"connected","forecast":service.require_forecaster().status(),
            "optimizer":{"engine":"Google OR-Tools CP-SAT","available":True},"settings":await service.settings_dict(db)}


@router.get("/models/status")
async def models_status(db:AsyncSession=Depends(get_db)) -> dict:
    records=(await db.execute(select(AIModel).where(AIModel.is_active==True))).scalars().all()
    return {"detection_models":[{"id":r.id,"name":r.name,"filename":r.filename,"type":r.model_type,
                                  "weights_available":settings.resolve_model_path(r.filename).exists(),"classes":r.class_names_list,
                                  "source":"EXISTING_VISIONX_MODEL","is_default":r.is_default} for r in records],
            "forecast":service.require_forecaster().status(),"capabilities":capabilities()}


def export_response(rows,kind,format):
    if format=="json":
        return Response(json.dumps(rows,ensure_ascii=False,indent=2,default=str),media_type="application/json",
                        headers={"Content-Disposition":f'attachment; filename="transitopt-{kind}.json"'})
    keys=list(dict.fromkeys(key for row in rows for key in row))
    output=io.StringIO(newline="")
    writer=csv.DictWriter(output,fieldnames=keys)
    writer.writeheader()
    for row in rows:
        formatted={k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()}
        # Spreadsheet programs must not execute operator notes/labels as formulas.
        formatted={k:("'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v) for k,v in formatted.items()}
        writer.writerow(formatted)
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="transitopt-{kind}.csv"'})


@router.get("/exports/{kind}")
async def export(kind:str,format:str=Query("csv",pattern="^(csv|json)$"),db:AsyncSession=Depends(get_db)):
    if kind=="forecasts":
        rows=[r.payload for r in (await db.execute(select(TransitForecast))).scalars()]
    elif kind=="traffic":
        rows=[{"id":r.id,"corridor_id":r.corridor_id,"timestamp":service.iso(r.timestamp),"congestion_score":r.score,"source":r.source,**r.payload} for r in (await db.execute(select(TransitTrafficObservation))).scalars()]
    elif kind=="recommendations":
        rows=await service.recommendations(db)
    elif kind=="scenarios":
        rows=[scenario_dict(r) for r in (await db.execute(select(TransitScenario))).scalars()]
    elif kind=="operator-actions":
        rows=[{"id":r.id,"recommendation_id":r.recommendation_id,"action":r.action,"operator":r.operator,"timestamp":service.iso(r.timestamp),**r.payload} for r in (await db.execute(select(TransitOperatorAction))).scalars()]
    else:
        raise HTTPException(404,"Unknown export type")
    return export_response(rows,kind,format)


@router.get("/exports/scenarios/{scenario_id}")
async def export_scenario(scenario_id:str,format:str=Query("json",pattern="^(csv|json)$"),db:AsyncSession=Depends(get_db)):
    scenario=await scenario_result(scenario_id,db)
    if format=="json":
        return export_response([scenario],"scenario-"+scenario_id,format)
    result=scenario["result"]
    rows=[{"scenario_id":scenario_id,"plan":"optimized",**r} for r in result.get("routes",[])]
    baseline=result.get("baseline",{})
    rows += [{"scenario_id":scenario_id,"plan":"baseline",**r} for r in baseline.get("routes",[])]
    return export_response(rows,"scenario-"+scenario_id,format)


async def image_pipeline(file,confidence,camera_id,db):
    from api.analyze import _validate_and_save_upload,ALLOWED_IMAGE_EXT,_get_active_model,run_cpu,_save_analysis,_build_response
    from services.image_processor import load_image_bytes,draw_detections,ndarray_to_base64
    from services.detector import analyze_general
    from models.registry import get_model
    from functools import partial
    camera=await camera_for(db,camera_id)
    setup=await db.get(TransitCameraSetup,camera_id) if camera else None
    kind="human" if setup and setup.role=="bus_interior" else "general"
    _,data=await _validate_and_save_upload(file,ALLOWED_IMAGE_EXT)
    model=await _get_active_model(db,kind)
    filename=model.filename if model else getattr(settings,kind+"_model")
    image=await run_cpu(load_image_bytes,data)
    loaded=await run_cpu(get_model,filename)
    names=loaded.names if isinstance(loaded.names,dict) else dict(enumerate(loaded.names))
    class_filter=[key for key,name in names.items() if str(name).strip().lower() in {"person","human","people"}] if kind=="human" else None
    if kind=="human" and not class_filter:
        raise HTTPException(503,"The configured human model does not expose a supported person class")
    result=await run_cpu(partial(analyze_general,class_filter=class_filter),image,filename,confidence)
    annotated=await run_cpu(draw_detections,image,result["detections"])
    result.update(image_width=image.shape[1],image_height=image.shape[0],processed_image=ndarray_to_base64(image))
    aid=await _save_analysis(db,kind,model,result,file.filename,None,image.shape,confidence)
    observation=await persist_observation(db,result,camera_id,f"analysis-{aid}","image",aid)
    supported_classes=[names[key] for key in class_filter] if class_filter else list(names.values())
    return {**_build_response(result,annotated,aid,model),"observation":observation,"source":"REAL_MODEL_DETECTION",
            "detections":observation["detections"],"counts":observation["class_counts"],"supported_classes":supported_classes,
            "unsupported_metrics":["physical_speed","queue_length","ticketed_passengers"]}


@router.post("/vision/analyze-image",dependencies=[Depends(inference_limit)])
@router.post("/detection/image",dependencies=[Depends(inference_limit)])
async def analyze_image(file:UploadFile=File(...),confidence:float=Form(.5,ge=.1,le=.95),camera_id:str|None=Form(None),db:AsyncSession=Depends(get_db)) -> dict:
    return await image_pipeline(file,confidence,camera_id,db)


async def start_video(file,confidence,camera_id,track,db):
    from api.analyze import _validate_and_save_upload,ALLOWED_VIDEO_EXT,_get_active_model,_save_analysis
    from services.video_processor import process_video
    camera=await camera_for(db,camera_id)
    setup=await db.get(TransitCameraSetup,camera_id) if camera else None
    kind="human" if setup and setup.role=="bus_interior" else "general"
    for key in list(_jobs):
        if _jobs[key]["status"] not in _ACTIVE_JOB_STATES and time.time()-_jobs[key].get("created",time.time())>settings.output_ttl_seconds:
            del _jobs[key]
    if sum(j["status"] in _ACTIVE_JOB_STATES for j in _jobs.values())>=2:
        raise HTTPException(429,"Video queue full; finish or cancel an active job.")
    path,_=await _validate_and_save_upload(file,ALLOWED_VIDEO_EXT,"videos")
    model=await _get_active_model(db,kind)
    filename=model.filename if model else getattr(settings,kind+"_model")
    job_id=uuid.uuid4().hex
    output_name=f"transit_{job_id}.mp4"
    output=settings.output_dir/output_name
    job={"job_id":job_id,"status":"queued","progress":0,"frame":0,"total":0,"camera_id":camera_id,"source":"REAL_MODEL_DETECTION","created":time.time()}
    _jobs[job_id]=job
    if camera:
        camera.status='processing'
    db.add(TransitVisionJob(id=job_id,status="queued",payload=job.copy()))
    await db.commit()
    roi=camera.roi if camera else None
    def callback(frame,total,dets,width,height):
        while job["status"]=="paused":
            time.sleep(.1)
        if job["status"]=="cancelled":
            raise InterruptedError("Video analysis cancelled by operator")
        job.update(status="processing",stage="model_inference",frame=frame,total=total,progress=round(frame/max(1,total)*95,1))
        if roi:
            metrics=summarize(normalize_detections(dets,job_id),width,height,roi)
            return metrics["people_count"]
        return None
    def process():
        try:
            if job["status"]=="cancelled":
                raise InterruptedError("Video analysis cancelled by operator")
            result=process_video(str(path),str(output),filename,conf=confidence,track=track,frame_callback=callback,person_only=kind=="human")
            if job["status"]=="cancelled":
                raise InterruptedError("Video analysis cancelled by operator")
            encode_browser_video(output,job)
            return {**result,"video_encoding":"H.264","pixel_format":"yuv420p","browser_playback":True}
        finally:
            path.unlink(missing_ok=True)
    async def worker():
        try:
            result=await asyncio.get_running_loop().run_in_executor(_video_executor,process)
            if job["status"]=="cancelled":
                raise InterruptedError("Video analysis cancelled by operator")
            async with AsyncSessionLocal() as session:
                aid=await _save_analysis(session,kind,model,result,file.filename,output_name,(result["height"],result["width"]),confidence)
                observation=await persist_observation(session,result,camera_id,job_id,"video",aid)
                result={**result,"analysis_id":aid,"image_width":result["width"],"image_height":result["height"],
                        "download_url":f"/api/outputs/{output_name}","observation":observation,"detections":observation["detections"],"counts":observation["class_counts"],"source":"REAL_MODEL_DETECTION",
                        "model_info":{"type":kind,"filename":filename,"name":model.name if model else filename}}
                if job["status"]=="cancelled":
                    raise InterruptedError("Video analysis cancelled by operator")
                job.update(status="complete",progress=100,result=result)
        except InterruptedError:
            job.update(status="cancelled",error="Video analysis cancelled; raw upload removed.")
            output.unlink(missing_ok=True)
        except Exception as exc:
            job.update(status="failed",error=str(exc) if isinstance(exc,(ValueError,TimeoutError,FileNotFoundError)) else "Video processing failed; check model and server logs.")
            output.unlink(missing_ok=True)
        finally:
            async with AsyncSessionLocal() as session:
                saved=await session.get(TransitVisionJob,job_id)
                saved.status=job["status"];saved.progress=job["progress"];saved.payload=job.copy()
                if camera_id and job['status'] in {'failed','cancelled'}:
                    stored_camera=await session.get(TransitCamera,camera_id)
                    if stored_camera:
                        stored_camera.status='error' if job['status']=='failed' else 'stopped'
                await session.commit()
    task=asyncio.create_task(worker());_tasks.add(task);task.add_done_callback(_tasks.discard)
    return {"job_id":job_id,"status":"queued","source":"REAL_MODEL_DETECTION"}


@router.post("/vision/analyze-video",dependencies=[Depends(inference_limit)])
@router.post("/detection/video",dependencies=[Depends(inference_limit)])
async def analyze_video(file:UploadFile=File(...),confidence:float=Form(.5,ge=.1,le=.95),camera_id:str|None=Form(None),track:bool=Form(True),db:AsyncSession=Depends(get_db)) -> dict:
    return await start_video(file,confidence,camera_id,track,db)


@router.get("/vision/jobs/{job_id}")
@router.get("/detection/jobs/{job_id}")
async def vision_job(job_id:str,db:AsyncSession=Depends(get_db)) -> dict:
    if job_id in _jobs:
        return _jobs[job_id]
    stored=await db.get(TransitVisionJob,job_id)
    if not stored:
        raise HTTPException(404,"Vision job not found")
    return {**stored.payload,"status":stored.status,"progress":stored.progress}


@router.post("/vision/jobs/{job_id}/{action}")
async def control_vision(job_id:str,action:str,db:AsyncSession=Depends(get_db)) -> dict:
    job=_jobs.get(job_id)
    if not job or job["status"] not in _ACTIVE_JOB_STATES:
        raise HTTPException(409,"Only an active video job can be controlled")
    if action=="pause" and job["status"]=="encoding":
        raise HTTPException(409,"Encoding is the final preview preparation step; it can be cancelled but cannot be paused.")
    if action=="pause" and job["status"] in {"queued","processing"}:
        job["status"]="paused"
    elif action=="resume" and job["status"]=="paused":
        job["status"]="processing"
    elif action in {"cancel","stop"}:
        job["status"]="cancelled"
    else:
        raise HTTPException(422,"Use pause, resume or cancel for an applicable state")
    record=await db.get(TransitVisionJob,job_id);record.status=job["status"];record.payload=job.copy()
    await db.commit()
    return job


@router.get("/vision/results/{result_id}")
@router.get("/detection/results/{result_id}")
async def vision_result(result_id:str,db:AsyncSession=Depends(get_db)) -> dict:
    result=await db.get(TransitDetectionEvent,result_id)
    if not result:
        raise HTTPException(404,"Vision result not found")
    return {"id":result.id,"camera_id":result.camera_id,"source_id":result.source_id,"timestamp":service.iso(result.timestamp),**result.payload}


@router.get("/vision/samples")
async def vision_samples() -> dict:
    return {"samples":[{"id":"bus-image","name":"Bundled COCO bus sample","type":"image","provenance":"Ultralytics bundled bus.jpg; genuine existing-model detections."},
                       {"id":"bus-video","name":"Short stationary bus sample clip","type":"video","provenance":"Demonstration clip generated from bundled bus.jpg; repeated still frames, not live traffic footage."}]}


@router.post("/vision/samples/{sample_id}/analyze",dependencies=[Depends(inference_limit)])
async def analyze_sample(sample_id:str,camera_id:str|None=None,confidence:float=Query(.5,ge=.1,le=.95),db:AsyncSession=Depends(get_db)) -> dict:
    from ultralytics.utils import ASSETS
    if sample_id=="bus-image":
        file=UploadFile(filename="bundled-bus.jpg",file=io.BytesIO((ASSETS/"bus.jpg").read_bytes()))
        return await image_pipeline(file,confidence,camera_id,db)
    if sample_id=="bus-video":
        import cv2
        directory=BASE_DIR/"data"/"sample_videos";directory.mkdir(parents=True,exist_ok=True)
        path=directory/"bundled-bus-still-demo.avi"
        if not path.exists():
            frame=cv2.resize(cv2.imread(str(ASSETS/"bus.jpg")),(320,416))
            writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"MJPG"),5,(320,416))
            if not writer.isOpened():
                raise HTTPException(503,"Sample video encoder unavailable")
            for _ in range(15):
                writer.write(frame)
            writer.release()
        file=UploadFile(filename=path.name,file=io.BytesIO(path.read_bytes()))
        return await start_video(file,confidence,camera_id,True,db)
    raise HTTPException(404,"Sample not found")


@router.post("/vision/analyze-stream")
async def analyze_stream() -> dict:
    raise HTTPException(422,capabilities()["rtsp_reason"])
