"""Adapter for genuine existing VisionX results, with transparent count-based traffic estimates."""
from collections import Counter
from datetime import datetime, timezone
import uuid
from fastapi import HTTPException
from transit.models import TransitCamera, TransitCameraSetup, TransitDetectionEvent, TransitTrafficObservation
from transit.service import settings_dict

VEHICLES={"car","bus","truck","motorcycle","bicycle"}
PERSON={"person","human","people"}


def normalize_detections(detections,source_id,frame_seconds=0):
    timestamp=datetime.now(timezone.utc).isoformat()
    result=[]
    for d in detections:
        name=str(d.get("class","")).strip().lower()
        if name in PERSON:
            name="person"
        bbox=d.get("bbox",[])
        if len(bbox)!=4:
            continue
        result.append({**d,"class":name,"object_class":name,"confidence":float(d.get("confidence",0)),
                       "bbox":[float(v) for v in bbox],"bbox_format":"xywh_pixels",
                       "source_id":source_id,"frame_timestamp_seconds":frame_seconds,"timestamp":timestamp,
                       "track_id":d.get("track_id")})
    return result


def summarize(detections,width,height,roi=None,timeline=None,reference=20,thresholds=None):
    counts=dict(Counter(d["class"] for d in detections))
    visible_people=[d for d in detections if d["class"]=="person"]
    if roi and width and height:
        x,y,w,h=roi
        visible_people=[d for d in visible_people if x<= (d["bbox"][0]+d["bbox"][2]/2)/width <=x+w
                        and y<= (d["bbox"][1]+d["bbox"][3])/height <=y+h]
    vehicles=sum(counts.get(k,0) for k in VEHICLES)
    if timeline:
        mean_vehicles=sum(sum(frame.get("counts",{}).get(k,0) for k in VEHICLES) for frame in timeline)/len(timeline)
        mean_people=sum(frame.get("roi_people",sum(frame.get("counts",{}).get(k,0) for k in PERSON)) for frame in timeline)/len(timeline)
    else:
        mean_vehicles,mean_people=vehicles,len(visible_people)
    score=round(min(100,mean_vehicles/max(1,reference)*100),1)
    thresholds=thresholds or {"moderate":25,"high":50,"severe":75}
    category="SEVERE" if score>=thresholds["severe"] else "HIGH" if score>=thresholds["high"] else "MODERATE" if score>=thresholds["moderate"] else "LOW"
    return {"class_counts":counts,"vehicle_count":vehicles,"people_count":len(visible_people),
            "mean_vehicles_per_frame":round(mean_vehicles,2),"mean_people_per_frame":round(mean_people,2),
            "congestion_score":score,"congestion_category":category,"crowd_count":len(visible_people),
            "crowd_level":"HIGH" if mean_people>=15 else "MODERATE" if mean_people>=6 else "LOW",
            "vehicle_density":round(mean_vehicles/max(1,reference),3),"vehicle_density_unit":"relative scene count/reference",
            "average_speed_kmh":None,"queue_length":None,"speed_status":"Unavailable — scene calibration not configured",
            "queue_status":"Unavailable — queue calibration not configured","crowd_is_ridership":False,
            "crowd_note":"Detected people are crowd observations, not ticketed passenger boardings.",
            "confidence_mean":round(sum(d["confidence"] for d in detections)/len(detections),4) if detections else None,
            "source":"REAL_MODEL_DETECTION","data_quality":"estimated_count_based",
            "method":f"Estimated congestion = min(100, mean visible vehicles per frame / {reference} × 100). Scene-count proxy; not physical traffic flow.",
            "roi":roi}


async def camera_for(db,camera_id):
    if not camera_id:
        return None
    camera=await db.get(TransitCamera,camera_id)
    if not camera:
        raise HTTPException(404,"Camera association not found")
    return camera


async def persist_observation(db,result,camera_id=None,source_id="upload",source_type="image",analysis_id=None):
    camera=await camera_for(db,camera_id)
    config=await settings_dict(db)
    seconds=(result.get("timeline") or [{}])[-1].get("seconds",0)
    dets=normalize_detections(result.get("detections",[]),source_id,seconds)
    width=result.get("image_width",result.get("frame_width",result.get("width",0)))
    height=result.get("image_height",result.get("frame_height",result.get("height",0)))
    metrics=summarize(dets,width,height,camera.roi if camera else None,result.get("timeline"),
        config["vision_density_reference_vehicles"],config["traffic_thresholds"])
    setup=await db.get(TransitCameraSetup,camera_id) if camera_id else None
    if setup and setup.role=='bus_road':
        from transit.bus_speed import enrich_bus_speed
        from transit.mobility import utc_now
        if source_type=='browser_camera':
            metrics=await enrich_bus_speed(db,metrics,setup,source_id,source_type,utc_now())
            thresholds=config['traffic_thresholds'];score=metrics['congestion_score']
            metrics['congestion_category']='SEVERE' if score>=thresholds['severe'] else 'HIGH' if score>=thresholds['high'] else 'MODERATE' if score>=thresholds['moderate'] else 'LOW'
        else:
            metrics['speed_status']='Moving-bus speed requires synchronized live GPS; uploads are not geolocated.'
    metrics.update(input_source_type=source_type,
        observation_type="live_camera_detection" if source_type=="browser_camera" else "recorded_detection",
        timestamp_basis="received_live_frame" if source_type=="browser_camera" else "processing_time")
    event_id=uuid.uuid4().hex
    event=TransitDetectionEvent(id=event_id,analysis_id=analysis_id,camera_id=camera_id,source_id=source_id,
        source_type=source_type,frame_timestamp_seconds=seconds,counts=metrics["class_counts"],confidence_mean=metrics["confidence_mean"],
        payload={**metrics,"detections":dets,"width":width,"height":height,
                 "safety_consecutive_frames":result.get("safety_consecutive_frames",0),
                 "processing_fps":result.get("inference_fps",result.get("fps")),"frames":result.get("processed_frames",1)})
    db.add(event)
    await db.flush()
    bus_observation=None
    if camera:
        if setup and setup.role=="bus_interior" and setup.bus_id:
            from transit.mobility import record_bus_observation
            bus_observation=await record_bus_observation(db,camera,setup,event,dets,width,height,config)
        elif setup is None or setup.role in {"road_traffic", "bus_road"}:
            db.add(TransitTrafficObservation(id=uuid.uuid4().hex,camera_id=camera_id,detection_event_id=event_id,
                corridor_id=camera.corridor_id,score=metrics["congestion_score"],category=metrics["congestion_category"],
                source="REAL_MODEL_DETECTION",payload={**metrics,"processing_fps":result.get("inference_fps",result.get("fps"))}))
        camera.status="observed_authorized_input"
    await db.commit()
    return {**metrics,"id":event_id,"camera_id":camera_id,"corridor_id":camera.corridor_id if camera else None,
            "source_id":source_id,"source_type":source_type,"detections":dets,"frame_timestamp_seconds":seconds,
            "bus_observation":bus_observation}
