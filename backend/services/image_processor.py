"""
VisionX AI Analyzer — Image Processing Service
OpenCV-based preprocessing and annotation utilities.
"""
import io
import time
import base64
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import cv2
import numpy as np
from PIL import Image, ImageEnhance
from loguru import logger


# ── Colour palette for bounding boxes (BGR) ─────────────────────────
_COLORS = [
    (0, 255, 128), (0, 200, 255), (255, 100, 0),  (255, 0, 200),
    (0, 128, 255), (200, 255, 0), (128, 0, 255),  (0, 255, 200),
    (255, 200, 0), (0, 100, 255), (255, 50, 50),  (50, 255, 50),
]

def _class_color(class_id: int) -> Tuple[int, int, int]:
    return _COLORS[class_id % len(_COLORS)]


# ── Core loading helpers ─────────────────────────────────────────────

def load_image_bytes(data: bytes) -> np.ndarray:
    """Load image from raw bytes → OpenCV BGR array."""
    if not data:
        raise ValueError("Empty image")
    with Image.open(io.BytesIO(data)) as probe:
        if probe.width * probe.height > 25_000_000:
            raise ValueError("Image exceeds 25 megapixels; resize before uploading")
        probe.verify()
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image. Unsupported or corrupt file.")
    return img


def load_image_path(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not load image from path: {path}")
    return img


def ndarray_to_bytes(img: np.ndarray, fmt: str = ".jpg") -> bytes:
    ok, buf = cv2.imencode(fmt, img)
    if not ok:
        raise ValueError("Failed to encode image.")
    return bytes(buf)


def ndarray_to_base64(img: np.ndarray, fmt: str = ".jpg") -> str:
    raw = ndarray_to_bytes(img, fmt)
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def image_to_base64(img: np.ndarray) -> str:
    return ndarray_to_base64(img)


# ── Preprocessing ────────────────────────────────────────────────────

def preprocess_image(
    img: np.ndarray,
    brightness: float = 1.0,
    contrast: float = 1.0,
    sharpness: float = 1.0,
    resize: Optional[Tuple[int, int]] = None,
    grayscale: bool = False,
    denoise: bool = False,
) -> np.ndarray:
    """Apply preprocessing pipeline to an OpenCV BGR image."""
    if resize:
        img = cv2.resize(img, resize, interpolation=cv2.INTER_AREA)

    if grayscale:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    if denoise:
        img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

    # Use Pillow for brightness/contrast/sharpness
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if brightness != 1.0:
        pil = ImageEnhance.Brightness(pil).enhance(brightness)
    if contrast != 1.0:
        pil = ImageEnhance.Contrast(pil).enhance(contrast)
    if sharpness != 1.0:
        pil = ImageEnhance.Sharpness(pil).enhance(sharpness)
    img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    return img


# ── Annotation ───────────────────────────────────────────────────────

def draw_detections(
    img: np.ndarray,
    detections: List[Dict[str, Any]],
    line_thickness: int = 2,
    font_scale: float = 0.6,
) -> np.ndarray:
    """Draw bounding boxes and labels on an image (in-place on a copy)."""
    out = img.copy()
    h, w = out.shape[:2]

    for det in detections:
        x, y, bw, bh = det.get("bbox", [0, 0, 0, 0])
        cls_id    = det.get("class_id", 0)
        cls_name  = det.get("class", "object")
        conf      = det.get("confidence", 0.0)
        track_id  = det.get("track_id")

        color = _class_color(cls_id)

        # Clamp coordinates
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(w, int(x + bw))
        y2 = min(h, int(y + bh))

        cv2.rectangle(out, (x1, y1), (x2, y2), color, line_thickness)

        label = f"{cls_name} {conf:.2f}"
        if track_id is not None:
            label = f"#{track_id} {label}"

        (lw, lh), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
        )
        cv2.rectangle(
            out,
            (x1, max(0, y1 - lh - baseline - 4)),
            (x1 + lw + 4, y1),
            color,
            cv2.FILLED,
        )
        cv2.putText(
            out,
            label,
            (x1 + 2, y1 - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    return out


def draw_pose(img: np.ndarray, keypoints_list: List[List[Tuple[int, int, float]]]) -> np.ndarray:
    """Draw pose keypoints and skeleton on image."""
    out = img.copy()

    # COCO skeleton connections
    SKELETON = [
        (0, 1), (0, 2), (1, 3), (2, 4),           # head
        (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),   # arms
        (5, 11), (6, 12), (11, 12),                 # torso
        (11, 13), (13, 15), (12, 14), (14, 16),     # legs
    ]

    KP_COLORS = [
        (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
        (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
        (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
        (255, 0, 255), (255, 0, 170),
    ]

    for kps in keypoints_list:
        # Draw joints
        for i, (x, y, conf) in enumerate(kps):
            if conf > 0.3 and x > 0 and y > 0:
                color = KP_COLORS[i % len(KP_COLORS)]
                cv2.circle(out, (int(x), int(y)), 4, color, -1, cv2.LINE_AA)

        # Draw skeleton
        for (a, b) in SKELETON:
            if a < len(kps) and b < len(kps):
                xa, ya, ca = kps[a]
                xb, yb, cb = kps[b]
                if ca > 0.3 and cb > 0.3 and xa > 0 and xb > 0:
                    cv2.line(
                        out,
                        (int(xa), int(ya)),
                        (int(xb), int(yb)),
                        (0, 255, 128),
                        2,
                        cv2.LINE_AA,
                    )
    return out


# ── Frame / video utilities ──────────────────────────────────────────

def get_video_info(path: str) -> Dict[str, Any]:
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"fps": fps, "total_frames": total, "width": w, "height": h,
            "duration_s": total / fps if fps else 0}


def extract_frames(path: str, max_frames: int = 300, step: int = 1):
    """Generator that yields (frame_index, bgr_frame)."""
    cap = cv2.VideoCapture(path)
    idx = 0
    yielded = 0
    while cap.isOpened() and yielded < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            yield idx, frame
            yielded += 1
        idx += 1
    cap.release()
