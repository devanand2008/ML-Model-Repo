"""
VisionX AI Analyzer — Models & History API endpoints
"""
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from loguru import logger

from config import settings
from database import get_db, AIModel, Analysis, Detection, ModelVersion, Dataset
import hashlib
import io
import zipfile
from models.registry import clear_model_cache

from security import require_user, require_admin
router = APIRouter(dependencies=[Depends(require_user)])


# ── Models ───────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).order_by(AIModel.model_type, AIModel.id))
    models = result.scalars().all()
    return {
        "success": True,
        "models": [
            {
                "id":                 m.id,
                "name":               m.name,
                "model_type":         m.model_type,
                "filename":           m.filename,
                "description":        m.description,
                "version":            m.version,
                "is_active":          m.is_active,
                "is_default":         m.is_default,
                "confidence_threshold": m.confidence_threshold,
                "class_names":        m.class_names_list,
                "metrics":            m.metrics_dict,
                "created_at":         m.created_at.isoformat() if m.created_at else None,
            }
            for m in models
        ],
    }


@router.get("/models/{model_id}")
async def get_model_detail(model_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalars().first()
    if not m:
        raise HTTPException(404, "Model not found")
    return {
        "id": m.id, "name": m.name, "model_type": m.model_type,
        "filename": m.filename, "description": m.description,
        "version": m.version, "is_active": m.is_active, "is_default": m.is_default,
        "confidence_threshold": m.confidence_threshold,
        "class_names": m.class_names_list, "metrics": m.metrics_dict,
        "dataset_info": json.loads(m.dataset_info or "{}"),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/models/upload", dependencies=[Depends(require_admin)])
async def upload_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    model_type: str = Form(...),
    description: str = Form(""),
    version: str = Form("1.0.0"),
    confidence_threshold: float = Form(0.50, ge=0.1, le=0.95),
    dataset_info: str = Form("{}"),
    metrics: str = Form("{}"),
    class_names: str = Form("[]"),   # JSON string
    db: AsyncSession = Depends(get_db),
):
    if model_type not in {"general", "human", "ship", "container", "condition"}:
        raise HTTPException(422, "Invalid model type")
    try:
        cls_list = json.loads(class_names)
        dataset = json.loads(dataset_info)
        evaluation = json.loads(metrics)
        if not isinstance(cls_list, list) or not all(isinstance(c, str) for c in cls_list) or not isinstance(dataset, dict) or not isinstance(evaluation, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid model metadata JSON")
    if not (file.filename or "").lower().endswith(".pt"):
        raise HTTPException(400, "Only .pt model files are supported.")

    data = await file.read(500 * 1024 * 1024 + 1)
    if len(data) > 500 * 1024 * 1024:   # 500 MB limit
        raise HTTPException(413, "Model file too large (max 500 MB).")

    if not data or not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(400, "Expected a modern PyTorch .pt checkpoint ZIP archive")
    # Only trusted administrator checkpoints may be loaded: PyTorch files can contain executable code.
    # Sanitise filename
    safe_fn = f"{model_type}_{uuid.uuid4().hex[:8]}.pt"
    dest = settings.weights_dir / safe_fn
    dest.write_bytes(data)
    logger.info(f"Uploaded model saved to {dest}")

    # Parse class names
    try:
        cls_list = json.loads(class_names)
    except Exception:
        cls_list = []

    # Mark previous defaults of same type as non-default
    prev = await db.execute(
        select(AIModel).where(AIModel.model_type == model_type, AIModel.is_default == True)
    )
    for m in prev.scalars().all():
        m.is_default = False

    new_model = AIModel(
        name=name,
        model_type=model_type,
        filename=safe_fn,
        description=description,
        version=version,
        is_active=True,
        is_default=True,
        confidence_threshold=confidence_threshold,
        class_names=json.dumps(cls_list),
        dataset_info=json.dumps(dataset),
        metrics=json.dumps(evaluation),
    )
    db.add(new_model)
    await db.flush()
    db.add(ModelVersion(model_id=new_model.id,version=version,filename=safe_fn,sha256=hashlib.sha256(data).hexdigest()))
    if dataset:
        db.add(Dataset(name=str(dataset.get("name", name)),dataset_type=model_type,description=json.dumps(dataset),class_names=json.dumps(cls_list)))
    await db.commit()
    await db.refresh(new_model)

    # Clear cache for this type
    clear_model_cache()

    return {"success": True, "model_id": new_model.id, "filename": safe_fn}


@router.patch("/models/{model_id}")
async def update_model(
    model_id: int,
    name: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    is_default: Optional[bool] = Form(None),
    confidence_threshold: Optional[float] = Form(None, ge=0.1, le=0.95),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalars().first()
    if not m:
        raise HTTPException(404, "Model not found")

    if is_default:
        prev = await db.execute(select(AIModel).where(AIModel.model_type == m.model_type, AIModel.id != m.id))
        for other in prev.scalars():
            other.is_default = False
    if name is not None:              m.name = name
    if is_active is not None:         m.is_active = is_active
    if is_default is not None:        m.is_default = is_default
    if confidence_threshold is not None: m.confidence_threshold = confidence_threshold
    if description is not None:       m.description = description

    await db.commit()
    clear_model_cache()
    return {"success": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalars().first()
    if not m:
        raise HTTPException(404, "Model not found")
    if m.is_default:
        raise HTTPException(400, "Cannot delete the default model. Set another model as default first.")

    # Keep shared weights and preserve historical analysis records.
    filename = m.filename
    shared = (await db.execute(select(AIModel).where(
        AIModel.filename == filename, AIModel.id != m.id
    ))).scalars().first()
    clear_model_cache(m.filename)
    versions = await db.execute(select(ModelVersion).where(ModelVersion.model_id == m.id))
    for version_record in versions.scalars():
        await db.delete(version_record)
    await db.delete(m)
    await db.commit()
    fpath = settings.resolve_model_path(filename)
    if not shared and filename not in {settings.general_model, settings.human_model, settings.ship_model, settings.container_model, settings.pose_model}:
        fpath.unlink(missing_ok=True)
    clear_model_cache()
    return {"success": True}


# ── History ──────────────────────────────────────────────────────────

@router.get("/history")
async def get_history(
    limit: int = 50,
    offset: int = 0,
    analyzer_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    query = select(Analysis).order_by(desc(Analysis.created_at))
    if analyzer_type == "video":
        query = query.where(Analysis.input_type == "video")
    elif analyzer_type:
        query = query.where(Analysis.analyzer_type == analyzer_type)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    analyses = result.scalars().all()

    return {
        "success": True,
        "items": [
            {
                "id":               a.id,
                "analyzer_type":    a.analyzer_type,
                "input_filename":   a.input_filename,
                "input_type":       a.input_type,
                "total_objects":    a.total_objects,
                "processing_time":  a.processing_time,
                "created_at":       a.created_at.isoformat() if a.created_at else None,
                "image_width":      a.image_width,
                "image_height":     a.image_height,
            }
            for a in analyses
        ],
    }


@router.get("/history/{analysis_id}")
async def get_analysis_detail(analysis_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    a = result.scalars().first()
    if not a:
        raise HTTPException(404, "Analysis not found")

    return {
        "id":               a.id,
        "analyzer_type":    a.analyzer_type,
        "input_filename":   a.input_filename,
        "input_type":       a.input_type,
        "total_objects":    a.total_objects,
        "processing_time":  a.processing_time,
        "confidence_threshold": a.confidence_threshold,
        "image_width":      a.image_width,
        "image_height":     a.image_height,
        "created_at":       a.created_at.isoformat() if a.created_at else None,
        "results":          json.loads(a.results or "{}"),
    }


@router.delete("/history/{analysis_id}")
async def delete_analysis(analysis_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    a = result.scalars().first()
    if not a:
        raise HTTPException(404, "Analysis not found")
    await db.delete(a)
    await db.commit()
    clear_model_cache()
    return {"success": True}
