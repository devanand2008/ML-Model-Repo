"""
VisionX AI Analyzer — Detection Service
Unified YOLO inference for all analyzer modules.
"""
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
import numpy as np

from models.registry import (
    get_model, MODEL_TYPE_FILTERS, COCO_CLASSES,
    SHIP_SUBTYPES, CONTAINER_CLASSES, CONDITION_CLASSES,
)
from config import settings


# ── Raw YOLO result parser ───────────────────────────────────────────

def _parse_boxes(result, model_classes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Convert a single ultralytics Result object to a list of detection dicts."""
    detections = []
    if result.boxes is None:
        return detections

    names = model_classes or list(result.names.values()) if result.names else COCO_CLASSES

    for box in result.boxes:
        cls_id  = int(box.cls[0])
        conf    = float(box.conf[0])
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        bw = x2 - x1
        bh = y2 - y1

        cls_name = result.names[cls_id] if result.names else (
            names[cls_id] if cls_id < len(names) else str(cls_id)
        )

        detections.append({
            "class_id": cls_id,
            "class": cls_name,
            "confidence": round(conf, 4),
            "bbox": [round(x1, 1), round(y1, 1), round(bw, 1), round(bh, 1)],
        })

    return detections


def _parse_poses(result) -> List[List[Tuple[float, float, float]]]:
    """Extract keypoints from a pose result."""
    kp_list = []
    if result.keypoints is None:
        return kp_list
    for kp in result.keypoints.data:
        pts = [(float(x), float(y), float(v)) for x, y, v in kp]
        kp_list.append(pts)
    return kp_list


def _build_counts(detections: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for d in detections:
        counts[d["class"]] = counts.get(d["class"], 0) + 1
    return counts


# ── Core inference function ──────────────────────────────────────────

def run_inference(
    img_or_path,                          # np.ndarray or str path
    model_filename: str,
    conf: float = 0.50,
    iou: float = 0.45,
    class_filter: Optional[List[int]] = None,
    pose_mode: bool = False,
    model_classes: Optional[List[str]] = None,
    max_det: int = 300,
) -> Dict[str, Any]:
    """Run YOLO inference and return a structured result dict."""
    t0 = time.perf_counter()

    model = get_model(model_filename)

    kwargs: Dict[str, Any] = {
        "conf": conf,
        "iou": iou,
        "max_det": max_det,
        "verbose": False,
    }
    if class_filter:
        kwargs["classes"] = class_filter

    try:
        results = model(img_or_path, **kwargs)
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        raise RuntimeError(f"Model inference error: {e}") from e

    result = results[0]
    elapsed = time.perf_counter() - t0

    detections = _parse_boxes(result, model_classes)
    keypoints  = _parse_poses(result) if pose_mode else []

    # Annotate with index (useful for tracking UI)
    for i, d in enumerate(detections):
        d["id"] = i

    return {
        "detections": detections,
        "keypoints":  keypoints,
        "counts":     _build_counts(detections),
        "processing_time": round(elapsed, 4),
        "model_filename": model_filename,
    }


# ── Specialised inference wrappers ───────────────────────────────────

def analyze_general(
    img, model_filename: str, conf: float = 0.50, **kwargs
) -> Dict[str, Any]:
    return run_inference(img, model_filename, conf=conf, **kwargs)


def analyze_human(
    img, model_filename: str, conf: float = 0.45,
    pose_mode: bool = False, is_custom: bool = False, **kwargs
) -> Dict[str, Any]:
    """Detect people; optionally run pose estimation."""
    if pose_mode:
        model_filename = settings.pose_model
    # If custom weights, don't filter (model already person-only)
    class_filter = None if is_custom else MODEL_TYPE_FILTERS["human"]
    result = run_inference(
        img, model_filename, conf=conf,
        class_filter=class_filter,
        pose_mode=pose_mode,
        **kwargs,
    )
    # Enrich with position labels
    for d in result["detections"]:
        x, y, w, h = d["bbox"]
        # determine position quadrant
        img_h, img_w = (img.shape[:2] if hasattr(img, "shape") else (1080, 1920))
        cx = x + w / 2
        cy = y + h / 2
        hpos = "left" if cx < img_w * 0.33 else ("right" if cx > img_w * 0.66 else "center")
        vpos = "top"  if cy < img_h * 0.33 else ("bottom" if cy > img_h * 0.66 else "middle")
        d["position"] = f"{vpos}-{hpos}"
    return result


def analyze_ship(
    img, model_filename: str, conf: float = 0.45,
    is_custom: bool = False, **kwargs
) -> Dict[str, Any]:
    class_filter = None if is_custom else MODEL_TYPE_FILTERS["ship"]
    result = run_inference(img, model_filename, conf=conf, class_filter=class_filter, **kwargs)
    if not is_custom:
        result["warnings"] = ["Custom model not installed. Using available pretrained model. Ship results use the COCO boat class; ship types and overhead imagery accuracy require custom training."]
    if is_custom:
        # Custom model already has fine-grained ship classes
        pass
    else:
        # Re-label COCO 'boat' as 'ship'
        for d in result["detections"]:
            if d["class"] == "boat":
                d["class"] = "ship"
        result["counts"] = _build_counts(result["detections"])
    return result


def analyze_container(
    img,
    model_filename: str,
    condition_model_filename: Optional[str] = None,
    conf: float = 0.45,
    is_custom: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    result = run_inference(img, model_filename, conf=conf, **kwargs)
    container_dets = [d for d in result["detections"] if d["class"].lower().replace("-", " ") in CONTAINER_CLASSES]
    supported = any(str(n).lower().replace("-", " ") in CONTAINER_CLASSES for n in get_model(model_filename).names.values())
    result["warnings"] = [] if supported else ["Custom model not installed. Using available pretrained model. Container detection and condition are unavailable; results show supported general objects."]
    good = damaged = 0
    if condition_model_filename and supported:
        model = get_model(condition_model_filename)
        if model.task != "classify":
            raise ValueError("Condition weights must be a YOLO classification model trained on container crops.")
        for det in container_dets:
            x, y, w, h = map(int, det["bbox"])
            crop = img[max(0,y):max(0,y+h), max(0,x):max(0,x+w)]
            if not crop.size:
                continue
            pred = model(crop, verbose=False)[0]
            label = pred.names[pred.probs.top1].lower().replace("-", " ").replace("_", " ")
            score = float(pred.probs.top1conf)
            det["condition"] = label if score >= conf else "unclassified"
            det["condition_confidence"] = score
            good += int(score >= conf and label in {"good", "good container"})
            damaged += int(score >= conf and label in {"damaged", "damage container", "damaged container"})
    total = len(container_dets)
    active = bool(condition_model_filename and supported)
    result["condition"] = {"total_containers": total if supported else None,
        "good": good if active else None, "damaged": damaged if active else None,
        "good_pct": round(good / total * 100, 1) if active and total else None,
        "damaged_pct": round(damaged / total * 100, 1) if active and total else None,
        "condition_model_active": active}
    return result


def analyze_combined(
    img,
    general_model: str,
    human_model: str,
    ship_model: str,
    container_model: str,
    conf: float = 0.50,
    condition_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Run all detectors and merge into a unified result."""
    t0 = time.perf_counter()

    human_res     = analyze_human(img, human_model, conf=conf, is_custom=human_model != settings.general_model)
    ship_res      = analyze_ship(img, ship_model, conf=conf, is_custom=ship_model != settings.general_model)
    container_res = analyze_container(img, container_model, condition_model_filename=condition_model, conf=conf)
    general_res   = analyze_general(img, general_model, conf=conf)

    # Merge all detections, tagging source
    all_detections = []
    for det in human_res["detections"]:
        det["source"] = "human_model"
        all_detections.append(det)
    for det in ship_res["detections"]:
        det["source"] = "ship_model"
        all_detections.append(det)
    for det in container_res["detections"]:
        if det["class"].lower() not in CONTAINER_CLASSES:
            continue
        det["source"] = "container_model"
        all_detections.append(det)
    # Add general detections not already covered
    covered = {"person", "boat", "ship", "container", "intermodal container"}
    for det in general_res["detections"]:
        if det["class"] not in covered:
            det["source"] = "general_model"
            all_detections.append(det)

    # Re-assign IDs
    for i, d in enumerate(all_detections):
        d["id"] = i

    counts = _build_counts(all_detections)
    return {
        "detections": all_detections,
        "counts": counts,
        "warnings": container_res.get("warnings", []),
        "condition": container_res.get("condition"),
        "people":     counts.get("person", 0),
        "ships":      len(ship_res["detections"]),
        "containers": counts.get("container", 0) + counts.get("intermodal container", 0),
        "trucks":     counts.get("truck", 0),
        "other":      sum(v for k, v in counts.items()
                          if k not in {"person","ship","boat","container","intermodal container","truck"}),
        "processing_time": round(time.perf_counter() - t0, 4),
    }
