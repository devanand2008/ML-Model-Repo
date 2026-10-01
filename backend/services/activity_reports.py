"""Observable movement reports. Detector IDs are observations, not identities."""
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import json
import math
import time
import uuid
from config import settings

IST = timezone(timedelta(hours=5, minutes=30), 'IST')
REPORT_SECONDS = 600

class ActivityReporter:
    def __init__(self, clock=time.monotonic, wall_clock=None, camera_started_at=None):
        self.clock = clock
        self.start = self.window_start = clock()
        self.wall_start = wall_clock or datetime.now(IST)
        self.camera_started_at = camera_started_at or self.wall_start.isoformat(timespec='seconds')
        self.session_id = uuid.uuid4().hex
        self.sequence = 0
        self.tracks = {}
        self.recent = deque(maxlen=20)
        self.frames = 0
        self.peak = 0
        self.untracked = 0
        self.classes = Counter()
        self.poses = Counter()
        self.stats = {}
        self.events = []
        self.dropped_events = 0
        self.modes = set()
        self.models = set()
        self.last_frame = None
        self.epoch = 0

    def timestamp(self, tick):
        return (self.wall_start+timedelta(seconds=tick-self.start)).isoformat(timespec='seconds')

    def event(self, tick, track, action, **extra):
        item = dict(time=self.timestamp(tick), track_id=track['id'], object=track['name'], action=action, **extra)
        self.recent.append(item)
        if len(self.events) < 20000:
            self.events.append(item)
        else:
            self.dropped_events += 1

    def reset_tracking(self, reason='Tracker reset after configuration change'):
        tick = self.clock()
        for track in self.tracks.values():
            self.event(tick,track,reason)
        self.tracks.clear()
        self.epoch += 1

    def ingest(self, result):
        tick = self.clock()
        gap = tick-self.last_frame if self.last_frame is not None else 0
        if gap > 5:
            for track in self.tracks.values():
                self.event(tick,track,'Observation gap; tracking continuity uncertain')
            self.tracks.clear()
        self.last_frame = tick
        self.frames += 1
        self.peak = max(self.peak,len(result['detections']))
        self.modes.add(result['mode'])
        self.models.update(result.get('models',[]))
        diagonal = math.hypot(result['frame_width'], result['frame_height'])
        for det in result['detections']:
            name = det['class']
            self.classes[name] += 1
            self.poses.update(det.get('pose_observations',[])+det.get('action_estimates',[]))
            tid = det.get('track_id')
            if tid is None:
                self.untracked += 1
                det['activity'] = 'visible; no persistent track ID'
                continue
            key = f'{self.epoch}:{tid}'
            x,y,w,h = det['bbox']
            center = (x+w/2,y+h/2)
            if key not in self.tracks:
                self.tracks[key] = dict(id=tid,name=name,first=tick,last=tick,center=center,
                    samples=deque([(tick,center)],maxlen=60),action='observed',candidate=None,candidate_since=tick)
                self.event(tick,self.tracks[key],'First observed in frame')
            track = self.tracks[key]
            if 'pose_observations' in det:
                observed = tuple(sorted(det['pose_observations']+det.get('action_estimates',[])))
                if observed != track.get('pose_candidate'):
                    track['pose_candidate'],track['pose_since'] = observed,tick
                elif tick-track['pose_since'] >= .8 and observed != track.get('confirmed_pose'):
                    previous = track.get('confirmed_pose')
                    track['confirmed_pose'] = observed
                    if observed:
                        self.event(tick,track,'Pose estimate: '+', '.join(observed))
                    elif previous:
                        self.event(tick,track,'Previous pose observation no longer confirmed')
            stat = self.stats.setdefault(key,dict(track_id=tid,object=name,first=self.timestamp(tick),
                last=self.timestamp(tick),moving_seconds=0.,stationary_seconds=0.,distance_pixels=0.,max_speed_pixels_s=0.))
            dt = tick-max(track['last'],self.window_start)
            if 0 < dt <= 3:
                distance = math.dist(center,track['center'])
                stat['distance_pixels'] += distance
                if track['action'] in ('moving','stationary'):
                    stat[f"{track['action']}_seconds"] += dt
            # Measure displacement over a one-second horizon, not noisy per-frame speed.
            while len(track['samples'])>1 and tick-track['samples'][1][0]>=1:
                track['samples'].popleft()
            prior_tick, prior_center = track['samples'][0]
            span = tick-prior_tick
            action = track['action']
            if span >= .7:
                speed = math.dist(center,prior_center)/max(span,.001)
                stat['max_speed_pixels_s'] = max(stat['max_speed_pixels_s'],speed)
                candidate = 'moving' if speed > max(3,diagonal*.008) else 'stationary'
                if candidate != track['candidate']:
                    track['candidate'],track['candidate_since'] = candidate,tick
                elif tick-track['candidate_since'] >= .8 and candidate != track['action']:
                    action = candidate
                    dx,dy = center[0]-prior_center[0],center[1]-prior_center[1]
                    direction = ('right' if dx>0 else 'left') if abs(dx)>=abs(dy) else ('down' if dy>0 else 'up')
                    self.event(tick,track,candidate,direction=direction if candidate=='moving' else None,speed_pixels_s=round(speed,1))
            track.update(last=tick,center=center,action=action)
            track['samples'].append((tick,center))
            stat['last'] = self.timestamp(tick)
            det['activity'] = action
        for key in list(self.tracks):
            track = self.tracks[key]
            if tick-track['last'] > 3:
                self.event(tick,track,'No longer detected (may be occluded or outside frame)')
                del self.tracks[key]
        return self.status()

    def status(self):
        tick = self.clock()
        return dict(session_id=self.session_id,session_started=self.timestamp(self.start),
            camera_on_seconds=round(tick-self.start),report_every_seconds=REPORT_SECONDS,
            next_report_in_seconds=max(0,math.ceil(self.window_start+REPORT_SECONDS-tick)),
            recent_actions=list(self.recent)[-12:],time_zone='Asia/Calcutta (IST, UTC+05:30)')

    def flush(self, partial=False, reason='10-minute interval', end=None):
        end = self.clock() if end is None else end
        if end <= self.window_start or (partial and not self.frames and not self.events):
            return None
        self.sequence += 1
        report_id = f'activity_{self.session_id}_{self.sequence:04d}'
        metadata = dict(id=report_id,session_id=self.session_id,sequence=self.sequence,
            started_at=self.timestamp(self.window_start),ended_at=self.timestamp(end),
            camera_started_at=self.camera_started_at,monitoring_started_at=self.timestamp(self.start),duration_seconds=round(end-self.window_start,1),
            partial=partial,reason=reason,frames_analyzed=self.frames,peak_visible_objects=self.peak,
            unique_track_ids=len(self.stats),file_name=report_id+'.txt',download_url=f'/api/reports/{report_id}/download')
        lines=['VisionX AI - Human and Object Activity Report',
            f'Report: {report_id}',f"Camera started (browser time): {metadata['camera_started_at']}",f"Monitoring started: {metadata['monitoring_started_at']}",
            f"Period: {metadata['started_at']} to {metadata['ended_at']}",
            'Timezone: Asia/Calcutta (IST, UTC+05:30)',f'Report type: {reason}',
            f"Duration: {metadata['duration_seconds']} seconds",f'Frames analyzed: {self.frames}',
            f'Peak visible objects: {self.peak}',f'Tracked IDs observed in this interval: {len(self.stats)}',
            'Modes: '+', '.join(sorted(self.modes)), 'Models: '+', '.join(sorted(self.models)),
            f'Untracked detection instances: {self.untracked}', '', 'OBJECT DETECTIONS ACROSS FRAMES (not unique objects)']
        lines += [f'{name}: {count}' for name,count in sorted(self.classes.items())] or ['None observed']
        lines += ['', 'POSE OBSERVATIONS ACROSS FRAMES (geometric estimates, not unique actions)']
        lines += [f'{name}: {count}' for name,count in sorted(self.poses.items())] or ['None observed']
        lines += ['', 'TRACK SUMMARY']
        for key,stat in self.stats.items():
            lines.append(f"Track {key} ({stat['object']}): first {stat['first']}; last {stat['last']}; moving {stat['moving_seconds']:.1f}s; stationary {stat['stationary_seconds']:.1f}s; movement {stat['distance_pixels']:.1f}px; max image speed {stat['max_speed_pixels_s']:.1f}px/s")
        lines += ['', 'TIMESTAMPED OBSERVATIONS']
        for event in self.events:
            detail = f"; direction: {event['direction']}" if event.get('direction') else ''
            lines.append(f"{event['time']} | ID {event['track_id']} | {event['object']} | {event['action']}{detail}")
        if not self.events:lines.append('No activity transitions observed.')
        if self.dropped_events:lines.append(f'{self.dropped_events} additional event transitions omitted due to report size limit.')
        lines += ['', 'INTERPRETATION',
            'Actions describe observed image movement and visibility, not intent or identity.',
            'Stationary/moving are estimates from tracked bounding-box centers; camera movement and occlusion affect them.',
            'Human skeletons and raised-hand/bent-knee labels are confidence-filtered geometric pose estimates; obscured joints cannot be interpreted.',
            'Semantic actions (e.g. eating, fighting, working) require a separately trained action-recognition model.',
            'All objects means classes supported by the installed detector. No sensitive personal attributes are inferred.',
            'Observation time includes only received detection frames; gaps and tracker resets are recorded.']
        settings.report_dir.mkdir(parents=True,exist_ok=True)
        (settings.report_dir/(report_id+'.txt')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        temporary = settings.report_dir/(report_id+'.json.tmp')
        temporary.write_text(json.dumps(metadata),encoding='utf-8')
        temporary.replace(settings.report_dir/(report_id+'.json'))
        self.window_start = end
        self.frames = self.peak = self.untracked = self.dropped_events = 0
        self.stats = {};self.classes.clear();self.poses.clear();self.events=[];self.modes.clear();self.models.clear()
        return metadata

    def due(self):
        if self.clock()-self.window_start >= REPORT_SECONDS:
            return self.flush(end=self.window_start+REPORT_SECONDS)
        return None
