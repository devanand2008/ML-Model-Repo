"""Per-video YOLO tracker; track IDs are isolated between sessions."""
import time
from collections import Counter, defaultdict, deque
import cv2
import numpy as np
from models.registry import resolve_model_path
from services.image_processor import draw_detections

def process_video(input_path, output_path, model_filename, conf=.5, iou=.45,
                  class_filter=None, track=True, frame_skip=1, progress_callback=None, frame_callback=None, person_only=False):
    from ultralytics import YOLO
    model = YOLO(resolve_model_path(model_filename))
    names = model.names if isinstance(model.names,dict) else dict(enumerate(model.names))
    if person_only:
        class_filter = [key for key,name in names.items() if str(name).lower().strip() in {'person','human','people'}]
        if not class_filter:
            raise ValueError('The configured human model does not expose a supported person class')
    cap = cv2.VideoCapture(input_path)
    writer = None
    start = time.perf_counter()
    counts, tracks, distances = Counter(), defaultdict(lambda: deque(maxlen=60)), Counter()
    unique, timeline = set(), []
    processed = 0
    try:
        width, height = int(cap.get(3)), int(cap.get(4))
        fps, total = cap.get(5) or 25, int(cap.get(7))
        if not cap.isOpened() or width <= 0 or height <= 0 or not np.isfinite(fps):
            raise ValueError('Corrupt or unsupported video')
        if width * height > 8500000 or total > 18000:
            raise ValueError('Video exceeds 4K or 18,000 frames; shorten or resize it')
        writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
        if not writer.isOpened():
            raise ValueError('Video encoder unavailable')
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if time.perf_counter() - start > 1800:
                raise TimeoutError('Video exceeded 30-minute processing limit')
            kwargs = dict(conf=conf, iou=iou, verbose=False, classes=class_filter)
            result = (model.track(frame, persist=True, **kwargs) if track else model(frame, **kwargs))[0]
            dets = []
            for i, box in enumerate(result.boxes if result.boxes is not None else []):
                x1, y1, x2, y2 = map(float, box.xyxy[0])
                tid = int(box.id[0]) if box.id is not None else None
                name = result.names[int(box.cls[0])]
                dets.append(dict(id=i, **{'class': name}, class_id=int(box.cls[0]), confidence=float(box.conf[0]),
                                 bbox=[x1,y1,x2-x1,y2-y1], track_id=tid, frame=processed))
                counts[name] += 1
                if tid is not None:
                    unique.add(tid)
                    point = (int((x1+x2)/2), int((y1+y2)/2))
                    if tracks[tid]:
                        distances[tid] += float(np.linalg.norm(np.subtract(point, tracks[tid][-1])))
                    tracks[tid].append(point)
            annotated = draw_detections(frame, dets)
            for points in tracks.values():
                if len(points) > 1:
                    cv2.polylines(annotated, [np.array(points, np.int32)], False, (255,200,0), 2)
            writer.write(annotated)
            processed += 1
            timeline.append({'frame': processed, 'seconds': round(processed/fps,3), 'counts': dict(Counter(d['class'] for d in dets)), 'visible': len(dets)})
            if frame_callback:
                roi_people = frame_callback(processed, max(total,processed), dets, width, height)
                if roi_people is not None:
                    timeline[-1]['roi_people'] = roi_people
            if progress_callback:
                progress_callback(processed, max(total, processed))
        if not processed:
            raise ValueError('Video contains no decodable frames')
        elapsed = time.perf_counter() - start
        return dict(width=width,height=height,total_frames=total,processed_frames=processed,fps=fps,
                    inference_fps=round(processed/elapsed,2),processing_time=round(elapsed,3),
                    class_counts=dict(counts),total_detections=sum(counts.values()),
                    unique_track_ids=sorted(unique),unique_count=len(unique),timeline=timeline,
                    movement_pixels={str(k): round(v,2) for k,v in distances.items()},
                    detections=dets,counts=timeline[-1]['counts'],
                    supported_classes=[names[key] for key in class_filter] if class_filter else list(names.values()))
    finally:
        cap.release()
        if writer:
            writer.release()
