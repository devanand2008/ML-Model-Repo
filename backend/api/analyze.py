"""
VisionX AI Analyzer — Analysis API endpoints
POST /api/analyze/*
"""
import io
import json
import uuid
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from config import settings
from database import get_db, Analysis, Detection, AIModel, AsyncSessionLocal, User
from services.image_processor import (
    load_image_bytes, preprocess_image,
    draw_detections, draw_pose, ndarray_to_base64, image_to_base64
)
from services.detector import (
    analyze_general, analyze_human, analyze_ship,
    analyze_container, analyze_combined
)
from services.video_processor import process_video
from models.registry import get_model, resolve_model_path

from sqlalchemy import select
import asyncio
from concurrent.futures import ThreadPoolExecutor

from security import inference_limit, require_user
router = APIRouter(dependencies=[Depends(require_user)])
_executor = ThreadPoolExecutor(max_workers=1)
_video_executor = ThreadPoolExecutor(max_workers=1)
_video_jobs = {}
_video_tasks = set()

_pending = set()

async def run_cpu(fn, *args):
    if len(_pending) >= 4:
        raise HTTPException(429, "Inference queue is full; retry shortly")
    future = asyncio.get_running_loop().run_in_executor(_executor, fn, *args)
    _pending.add(future)
    future.add_done_callback(_pending.discard)
    return await asyncio.wait_for(asyncio.shield(future), timeout=settings.inference_timeout)

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv"}


# ── Helpers ─────────────────────────────────────────────────────────

async def _validate_and_save_upload(file: UploadFile, allowed: set, subdir: str = "") -> Path:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {allowed}")

    data = await file.read(settings.max_file_size_bytes + 1)
    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(413, f"File too large. Max {settings.max_file_size_mb} MB.")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    save_dir  = settings.upload_dir / subdir
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / safe_name
    if allowed == ALLOWED_VIDEO_EXT:
        path.write_bytes(data)
    return path, data


async def _get_active_model(db: AsyncSession, model_type: str) -> Optional[AIModel]:
    result = await db.execute(
        select(AIModel).where(
            AIModel.model_type == model_type,
            AIModel.is_active == True,
            AIModel.is_default == True,
        )
    )
    return result.scalars().first()


async def _save_analysis(
    db: AsyncSession,
    analyzer_type: str,
    model: Optional[AIModel],
    result: dict,
    input_filename: str,
    output_filename: Optional[str],
    image_shape: tuple,
    conf: float,
) -> int:
    operator = (await db.execute(select(User).where(User.username == settings.admin_username))).scalars().first()
    analysis = Analysis(
        user_id=operator.id if operator else None,
        analyzer_type=analyzer_type,
        input_filename=input_filename,
        input_type="video" if output_filename else "image",
        output_filename=output_filename,
        model_id=model.id if model else None,
        confidence_threshold=conf,
        total_objects=result.get("total_detections", len(result.get("detections", []))),
        image_width=image_shape[1] if len(image_shape) > 1 else None,
        image_height=image_shape[0],
        processing_time=result.get("processing_time"),
        results=json.dumps({k: v for k, v in result.items() if not k.endswith("_image")}),
    )
    db.add(analysis)
    await db.flush()

    for det in result.get("detections", []):
        bbox = det.get("bbox", [0, 0, 0, 0])
        db.add(Detection(
            analysis_id=analysis.id,
            class_name=det.get("class", ""),
            confidence=det.get("confidence", 0.0),
            bbox_x=bbox[0] if len(bbox) > 0 else None,
            bbox_y=bbox[1] if len(bbox) > 1 else None,
            bbox_w=bbox[2] if len(bbox) > 2 else None,
            bbox_h=bbox[3] if len(bbox) > 3 else None,
            track_id=det.get("track_id"),
        ))

    await db.commit()
    return analysis.id


def _build_response(result: dict, annotated_img, analysis_id: int, model: Optional[AIModel]):
    annotated_b64 = ndarray_to_base64(annotated_img) if annotated_img is not None else None
    return {
        **result,
        "success": True,
        "analysis_id": analysis_id,
        "processing_time": result.get("processing_time", 0),
        "detections": result.get("detections", []),
        "counts": result.get("counts", {}),
        "keypoints": result.get("keypoints", []),
        "condition": result.get("condition"),
        "annotated_image": annotated_b64,
        "model_info": {
            "name": model.name if model else "Unknown",
            "type": model.model_type if model else "general",
            "filename": result.get("model_filename", model.filename if model else ""),
        } if model else None,
    }


# ── Image endpoints ──────────────────────────────────────────────────

@router.post("/image", dependencies=[Depends(inference_limit)])
async def analyze_image(
    file: UploadFile = File(...),
    confidence: float = Form(0.50, ge=0.10, le=0.95),
    brightness: float = Form(1.0, ge=0.1, le=3.0),
    contrast: float = Form(1.0, ge=0.1, le=3.0),
    sharpness: float = Form(1.0, ge=0.1, le=3.0),
    grayscale: bool = Form(False),
    denoise: bool = Form(False),
    resize_width: int = Form(0, ge=0, le=4096),
    db: AsyncSession = Depends(get_db),
):
    path, data = await _validate_and_save_upload(file, ALLOWED_IMAGE_EXT)
    model_rec = await _get_active_model(db, "general")
    model_file = model_rec.filename if model_rec else settings.general_model

    loop = asyncio.get_event_loop()
    img = await run_cpu(load_image_bytes, data)
    img = await run_cpu(
        preprocess_image, img,
        brightness, contrast, sharpness, (resize_width, max(1, round(img.shape[0] * resize_width / img.shape[1]))) if resize_width else None, grayscale, denoise
    )

    result = await run_cpu(
        analyze_general, img, model_file, confidence
    )

    annotated = await run_cpu(
        draw_detections, img, result["detections"]
    )

    result["processed_image"] = ndarray_to_base64(img)
    result["image_width"]  = img.shape[1]
    result["image_height"] = img.shape[0]

    aid = await _save_analysis(
        db, "image", model_rec, result, file.filename, None, img.shape, confidence
    )
    return _build_response(result, annotated, aid, model_rec)


@router.post("/webcam", dependencies=[Depends(inference_limit)])
@router.post("/human", dependencies=[Depends(inference_limit)])
async def analyze_human_endpoint(
    file: UploadFile = File(...),
    confidence: float = Form(0.50, ge=0.10, le=0.95),
    pose_mode: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    path, data = await _validate_and_save_upload(file, ALLOWED_IMAGE_EXT)
    model_rec = await _get_active_model(db, "human")
    model_file = model_rec.filename if model_rec else settings.human_model
    is_custom  = bool(model_rec and "yolo26n" not in model_rec.filename)

    loop = asyncio.get_event_loop()
    img = await run_cpu(load_image_bytes, data)

    result = await run_cpu(
        analyze_human, img, model_file, confidence, pose_mode, is_custom
    )

    annotated = await run_cpu(
        draw_detections, img, result["detections"]
    )
    if pose_mode and result.get("keypoints"):
        annotated = await loop.run_in_executor(
            _executor, draw_pose, annotated, result["keypoints"]
        )

    result["processed_image"] = ndarray_to_base64(img)
    result["image_width"]  = img.shape[1]
    result["image_height"] = img.shape[0]
    result["people_count"] = result["counts"].get("person", 0)

    aid = await _save_analysis(
        db, "human", model_rec, result, file.filename, None, img.shape, confidence
    )
    return _build_response(result, annotated, aid, model_rec)


@router.post("/ship", dependencies=[Depends(inference_limit)])
async def analyze_ship_endpoint(
    file: UploadFile = File(...),
    confidence: float = Form(0.50, ge=0.10, le=0.95),
    db: AsyncSession = Depends(get_db),
):
    path, data = await _validate_and_save_upload(file, ALLOWED_IMAGE_EXT)
    model_rec = await _get_active_model(db, "ship")
    model_file = model_rec.filename if model_rec else settings.ship_model
    is_custom  = bool(model_rec and "yolo26n" not in model_rec.filename)

    loop = asyncio.get_event_loop()
    img = await run_cpu(load_image_bytes, data)
    result = await run_cpu(
        analyze_ship, img, model_file, confidence, is_custom
    )

    annotated = await run_cpu(
        draw_detections, img, result["detections"]
    )

    result["processed_image"] = ndarray_to_base64(img)
    result["image_width"]  = img.shape[1]
    result["image_height"] = img.shape[0]

    aid = await _save_analysis(
        db, "ship", model_rec, result, file.filename, None, img.shape, confidence
    )
    return _build_response(result, annotated, aid, model_rec)


@router.post("/container", dependencies=[Depends(inference_limit)])
async def analyze_container_endpoint(
    file: UploadFile = File(...),
    confidence: float = Form(0.50, ge=0.10, le=0.95),
    condition_mode: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    path, data = await _validate_and_save_upload(file, ALLOWED_IMAGE_EXT)
    model_rec = await _get_active_model(db, "container")
    model_file = model_rec.filename if model_rec else settings.container_model
    is_custom  = bool(model_rec and "yolo26n" not in model_rec.filename)

    cond_model: Optional[str] = None
    if condition_mode:
        cond_rec = await _get_active_model(db, "condition")
        cond_model = cond_rec.filename if cond_rec else settings.container_condition_model

    loop = asyncio.get_event_loop()
    img = await run_cpu(load_image_bytes, data)
    result = await run_cpu(
        analyze_container, img, model_file, cond_model, confidence, is_custom
    )

    annotated = await run_cpu(
        draw_detections, img, result["detections"]
    )

    result["processed_image"] = ndarray_to_base64(img)
    result["image_width"]  = img.shape[1]
    result["image_height"] = img.shape[0]

    aid = await _save_analysis(
        db, "container", model_rec, result, file.filename, None, img.shape, confidence
    )
    return _build_response(result, annotated, aid, model_rec)


@router.post("/combined", dependencies=[Depends(inference_limit)])
async def analyze_combined_endpoint(
    file: UploadFile = File(...),
    confidence: float = Form(0.50, ge=0.10, le=0.95),
    condition_mode: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    path, data = await _validate_and_save_upload(file, ALLOWED_IMAGE_EXT)

    general_rec  = await _get_active_model(db, "general")
    human_rec    = await _get_active_model(db, "human")
    ship_rec     = await _get_active_model(db, "ship")
    container_rec = await _get_active_model(db, "container")

    g_file  = general_rec.filename  if general_rec   else settings.general_model
    h_file  = human_rec.filename    if human_rec      else settings.human_model
    s_file  = ship_rec.filename     if ship_rec       else settings.ship_model
    c_file  = container_rec.filename if container_rec else settings.container_model

    condition_rec = await _get_active_model(db, "condition") if condition_mode else None
    condition_file = (condition_rec.filename if condition_rec else settings.container_condition_model) if condition_mode else None
    loop = asyncio.get_event_loop()
    img = await run_cpu(load_image_bytes, data)
    result = await run_cpu(
        analyze_combined, img, g_file, h_file, s_file, c_file, confidence, condition_file
    )

    annotated = await run_cpu(
        draw_detections, img, result["detections"]
    )

    result["processed_image"] = ndarray_to_base64(img)
    result["image_width"]  = img.shape[1]
    result["image_height"] = img.shape[0]

    aid = await _save_analysis(
        db, "combined", general_rec, result, file.filename, None, img.shape, confidence
    )
    return _build_response(result, annotated, aid, general_rec)


# ── Video endpoint ───────────────────────────────────────────────────

@router.post("/video", dependencies=[Depends(inference_limit)])
async def analyze_video_endpoint(
    file: UploadFile = File(...),
    analyzer_type: str = Form("general"),
    confidence: float = Form(0.50, ge=0.10, le=0.95),
    track: bool = Form(True),
    background: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    if analyzer_type not in {"general", "human", "ship", "container"}:
        raise HTTPException(422, "Unsupported video analyzer")
    path, _ = await _validate_and_save_upload(file, ALLOWED_VIDEO_EXT, "videos")

    model_rec = await _get_active_model(db, analyzer_type)
    model_file = model_rec.filename if model_rec else settings.general_model

    out_name = f"out_{path.stem}.mp4"
    out_path = settings.output_dir / out_name

    loop = asyncio.get_event_loop()

    for key in list(_video_jobs):
        if time.time() - _video_jobs[key]["created"] > settings.output_ttl_seconds:
            del _video_jobs[key]
    if background and sum(j["status"] in {"queued", "processing"} for j in _video_jobs.values()) >= 2:
        path.unlink(missing_ok=True)
        raise HTTPException(429, "Video queue is full. Retry after current jobs finish.")
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "status": "queued", "frame": 0, "total": 0, "progress": 0, "created": time.time()}
    def progress(frame, total):
        job.update(status="processing", frame=frame, total=total, progress=round(frame/total*100,1))
    def _process():
        try:
            if analyzer_type == "container" and model_file == settings.general_model:
                raise ValueError("Container video detection requires custom container weights.")
            return process_video(str(path), str(out_path), model_file, conf=confidence, track=track,
                class_filter=([0] if analyzer_type == "human" else [8] if analyzer_type == "ship" else None) if model_file == settings.general_model else None,
                progress_callback=progress)
        except Exception:
            out_path.unlink(missing_ok=True)
            raise
        finally:
            path.unlink(missing_ok=True)
    async def finish(session):
        result = await loop.run_in_executor(_video_executor, _process)
        aid = await _save_analysis(session, analyzer_type, model_rec, result, file.filename,
            out_name, (result["height"], result["width"]), confidence)
        return {"success": True, "analysis_id": aid, "download_url": f"/api/outputs/{out_name}", "image_width": result["width"], "image_height": result["height"], **result}
    if not background:
        return await finish(db)
    _video_jobs[job_id] = job
    async def worker():
        try:
            async with AsyncSessionLocal() as session:
                job["result"] = await finish(session)
            job.update(status="complete", progress=100)
        except Exception as exc:
            logger.exception("Video job failed")
            job.update(status="failed", error=str(exc) if isinstance(exc,(ValueError,TimeoutError)) else "Video processing failed. Check installed model and server logs.")
    task = asyncio.create_task(worker())
    _video_tasks.add(task)
    task.add_done_callback(_video_tasks.discard)
    return {"success": True, "job_id": job_id}

@router.get("/video/jobs/{job_id}", dependencies=[Depends(require_user)])
async def video_job(job_id: str):
    job = _video_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Video job expired or does not exist")
    return job
