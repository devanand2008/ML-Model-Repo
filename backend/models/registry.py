"""
VisionX AI Analyzer — Model Registry
Centralised model loading, caching, and management.
All model paths come from the database or config — never hard-coded elsewhere.
"""
import json
from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from config import settings

# Lazy-imported so we only depend on ultralytics when actually loading
_model_cache: Dict[str, object] = {}


def _load_yolo(model_path: str):
    """Load a YOLO model with cache."""
    from ultralytics import YOLO
    if model_path not in _model_cache:
        logger.info(f"Loading YOLO model: {model_path}")
        _model_cache[model_path] = YOLO(model_path)
        logger.info(f"Model loaded: {model_path}")
    return _model_cache[model_path]


def resolve_model_path(filename: str) -> str:
    """
    Resolve a model filename to a full absolute path.
    If the file exists in weights_dir, use it.
    Otherwise fall back to ultralytics hub download (by passing filename as-is).
    """
    candidate = settings.resolve_model_path(filename)
    if candidate.exists():
        return str(candidate)
    if filename not in {"yolo26n.pt", "yolo26n-pose.pt", "yolo26n-cls.pt"}:
        raise FileNotFoundError(f"Custom weights missing: {filename}")
    return str(candidate)


def get_model(filename: str):
    """Get (or cache-load) a YOLO model by filename."""
    path = resolve_model_path(filename)
    return _load_yolo(path)


def clear_model_cache(filename: Optional[str] = None):
    """Clear one or all cached models."""
    if filename:
        # Cache eviction must also work after the checkpoint has been removed.
        key = str(settings.resolve_model_path(filename))
        _model_cache.pop(key, None)
    else:
        _model_cache.clear()
    logger.info("Model cache cleared.")


# ── Built-in class filter helpers ──────────────────────────────────────

COCO_CLASSES = [
    "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
    "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
    "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
    "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
    "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
    "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
    "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
    "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse","remote",
    "keyboard","cell phone","microwave","oven","toaster","sink","refrigerator","book",
    "clock","vase","scissors","teddy bear","hair drier","toothbrush"
]

# COCO class indices for commonly needed classes
COCO_PERSON_ID = 0
COCO_BOAT_ID = 8
COCO_TRUCK_ID = 7
COCO_CAR_ID = 2

# Inferred class filter sets (used when no custom model is loaded)
MODEL_TYPE_FILTERS: Dict[str, Optional[list]] = {
    "general":   None,                    # all classes
    "human":     [COCO_PERSON_ID],
    "ship":      [COCO_BOAT_ID],
    "container": None,                    # custom model; fallback = all
    "condition": None,
}

SHIP_SUBTYPES = ["container ship", "cargo ship", "tanker", "passenger ship", "bulk carrier", "ro-ro"]
CONTAINER_CLASSES = ["container", "intermodal container"]
CONDITION_CLASSES = ["good container", "damaged container"]
