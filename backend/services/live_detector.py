"""One detector/tracker per live session; no tracker state shared across cameras."""
from collections import Counter, defaultdict, deque
from pathlib import Path
import base64
import cv2
import numpy as np

from models.registry import resolve_model_path, CONTAINER_CLASSES, COCO_CLASSES
from services.detector import _parse_boxes, _parse_poses
from services.image_processor import load_image_bytes, draw_detections, draw_pose, ndarray_to_base64
from services.pose_activity import pose_observations, PoseActionEstimator
from config import settings

MAX_FRAME_BYTES = 2 * 1024 * 1024

def decode_frame(encoded):
    if not isinstance(encoded, str) or len(encoded) > MAX_FRAME_BYTES * 4 // 3 + 100:
        raise ValueError('Camera frame too large; use 640px capture width')
    try:
        raw = base64.b64decode(encoded.split(',', 1)[-1], validate=True)
        if len(raw) > MAX_FRAME_BYTES:
            raise ValueError()
        frame = load_image_bytes(raw)
    except Exception as exc:
        raise ValueError('Invalid camera frame') from exc
    if max(frame.shape[:2]) > 1280:
        scale = 1280 / max(frame.shape[:2])
        frame = cv2.resize(frame, (round(frame.shape[1]*scale), round(frame.shape[0]*scale)))
    return frame

def normalized(name):
    return str(name).lower().replace('-', ' ').replace('_', ' ').strip()

class LiveDetector:
    def __init__(self, mode, files, track=True, pose=True):
        from ultralytics import YOLO
        self.mode, self.track = mode, track
        self.pose = mode == 'human' and pose
        self.actions = PoseActionEstimator()
        self.models = []
        self.paths = defaultdict(lambda: deque(maxlen=45))
        self.last_seen = {}
        self.unique_ids = set()
        self.frame_index = 0
        self.warnings = []
        types = ['general'] if mode == 'port_monitor' else [mode]
        if mode == 'port_monitor':
            types += [kind for kind in ('human', 'ship', 'container') if files[kind] != files['general']]
        for kind in types:
            model = YOLO(resolve_model_path(settings.pose_model if self.pose else files[kind]))
            if model.task != ('pose' if self.pose else 'detect'):
                raise ValueError(f'{kind} live mode requires object-detection weights')
            names = {int(i): normalized(n) for i, n in model.names.items()}
            coco = list(names.values()) == COCO_CLASSES
            filters = None
            if kind == 'human':
                filters = [i for i, name in names.items() if name in {'person','human','people'}]
                if not filters:
                    raise ValueError('Selected human weights do not contain a person class')
            elif kind == 'ship' and coco:
                filters = [i for i, name in names.items() if name == 'boat']
                self.warnings.append('Using pretrained COCO boat detection. Ship subtypes require custom weights.')
            elif kind == 'container':
                filters = [i for i, name in names.items() if name in CONTAINER_CLASSES]
                if not filters:
                    if mode == 'container':
                        raise ValueError('Custom container model not installed. Choose All Objects or upload container weights in Model Center.')
                    continue
            self.models.append((kind, model, filters, coco))
        self.container_supported = any(any(normalized(n) in CONTAINER_CLASSES for n in m.names.values()) for _,m,_,_ in self.models)
        if mode == 'port_monitor' and not self.container_supported:
            self.warnings.append('Container detection unavailable: install custom container weights in Model Center.')

    def process(self, encoded, confidence):
        frame = decode_frame(encoded)
        all_dets = []
        covered = {kind for kind,_,_,_ in self.models if kind != 'general'}
        self.frame_index += 1
        for model_index, (kind, model, filters, coco) in enumerate(self.models):
            options = dict(conf=confidence, classes=filters, max_det=100, imgsz=640, verbose=False)
            result = (model.track(frame, persist=True, tracker='bytetrack.yaml', **options) if self.track else model.predict(frame, **options))[0]
            dets = _parse_boxes(result)
            poses = _parse_poses(result) if self.pose else []
            for index, (det, box) in enumerate(zip(dets, result.boxes if result.boxes is not None else [])):
                if index < len(poses):
                    det['keypoints'] = poses[index]
                    det['pose_observations'] = pose_observations(poses[index])
                name = normalized(det['class'])
                if kind == 'general' and ((name=='person' and 'human' in covered) or (name=='boat' and 'ship' in covered) or (name in CONTAINER_CLASSES and 'container' in covered)):
                    continue
                if kind == 'ship' and name == 'boat':
                    det['class'] = 'ship'
                elif kind == 'human':
                    det['class'] = 'person'
                det['source'] = kind
                if self.track and box.id is not None:
                    tid = model_index * 1_000_000 + int(box.id[0])
                    det['track_id'] = tid
                    if len(self.unique_ids) < 10000:
                        self.unique_ids.add(tid)
                    x,y,w,h = det['bbox']
                    self.paths[tid].append((round(x+w/2),round(y+h/2)))
                    self.last_seen[tid] = self.frame_index
                if 'keypoints' in det:
                    det['action_estimates'] = self.actions.observe(det.get('track_id'),det['keypoints'])
                all_dets.append(det)
        for i,det in enumerate(all_dets):
            det['id'] = i
        counts = dict(Counter(d['class'] for d in all_dets))
        annotated = draw_detections(frame, all_dets)
        if self.pose:
            annotated = draw_pose(annotated,[d['keypoints'] for d in all_dets if 'keypoints' in d])
            for det in all_dets:
                labels = det.get('action_estimates',[]) + det.get('pose_observations',[])
                if labels:
                    x,y,_,h = det['bbox']
                    for row,label in enumerate(labels):
                        label_y = min(frame.shape[0]-8,int(y+h)+18) - (len(labels)-1-row)*15
                        cv2.putText(annotated,label,(max(0,int(x)),max(12,label_y)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,128),1,cv2.LINE_AA)
        visible_ids = {d.get('track_id') for d in all_dets}
        for tid in list(self.paths):
            if self.frame_index-self.last_seen[tid] > 30:
                del self.paths[tid]; del self.last_seen[tid]
            elif tid in visible_ids and len(self.paths[tid]) > 1:
                cv2.polylines(annotated,[np.array(self.paths[tid],np.int32)],False,(255,200,0),2)
        return dict(type='detection', annotated_frame=ndarray_to_base64(annotated), detections=all_dets,
                    counts=counts, total_objects=len(all_dets), unique_count=len(self.unique_ids),
                    frame_width=frame.shape[1], frame_height=frame.shape[0], mode=self.mode,
                    warnings=self.warnings, tracking=self.track, pose_enabled=self.pose,
                    models=[Path(m.ckpt_path).name for _,m,_,_ in self.models],
                    port_summary=dict(people=counts.get('person',0),
                        ships=sum(1 for d in all_dets if d['source']=='ship' or normalized(d['class']) in {'boat','ship'}),
                        trucks=counts.get('truck',0),
                        containers=sum(v for k,v in counts.items() if normalized(k) in CONTAINER_CLASSES) if self.container_supported else None,
                        vehicles=sum(counts.get(k,0) for k in ('car','bus','truck','motorcycle')),
                        total=len(all_dets)) if self.mode=='port_monitor' else None)
