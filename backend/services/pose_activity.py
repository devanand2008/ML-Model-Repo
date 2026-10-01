"""Conservative geometric pose observations, not semantic action recognition."""
import math
import time
from collections import deque

def joint_angle(points, hip, knee, ankle):
    a = [points[hip][j]-points[knee][j] for j in (0,1)]
    b = [points[ankle][j]-points[knee][j] for j in (0,1)]
    lengths = math.hypot(*a)*math.hypot(*b)
    if lengths <= 100:
        return None
    return math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(a,b))/lengths))))

def posture_observations(points):
    """Require both visible legs and an upright torso; otherwise abstain."""
    if len(points) != 17 or not all(points[i][2]>=.5 and points[i][0]>0 and points[i][1]>0 for i in (5,6,11,12,13,14,15,16)):
        return []
    shoulder = [(points[5][j]+points[6][j])/2 for j in (0,1)]
    hip = [(points[11][j]+points[12][j])/2 for j in (0,1)]
    torso = math.dist(shoulder,hip)
    if torso < 15 or hip[1]-shoulder[1] < torso*.7:
        return []
    angles = [joint_angle(points,*indices) for indices in ((11,13,15),(12,14,16))]
    if None in angles:
        return []
    if all(angle>155 for angle in angles) and all(points[k][1]-points[h][1]>10 and points[a][1]-points[k][1]>10 for h,k,a in ((11,13,15),(12,14,16))):
        return ['Standing posture (estimate)']
    if all(60<angle<125 for angle in angles) and all(abs(points[k][1]-points[h][1])<math.dist(points[k][:2],points[h][:2])*.45 for h,k in ((11,13),(12,14))):
        return ['Sitting posture (estimate)']
    return []

class PoseActionEstimator:
    """Track-local temporal gesture estimates; state never crosses sessions."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.tracks = {}

    def observe(self, track_id, points):
        tick = self.clock()
        for tid in list(self.tracks):
            if tick-self.tracks[tid]['last']>5:
                del self.tracks[tid]
        labels = posture_observations(points)
        if track_id is None or len(points)!=17:
            return labels
        state = self.tracks.get(track_id)
        if state is None or tick-state['last']>1.5:
            state = dict(last=tick,wrists={'left':deque(maxlen=120),'right':deque(maxlen=120)},candidate=(),since=tick,confirmed=())
            self.tracks[track_id] = state
        state['last'] = tick
        for side,s,h,w in [('left',5,11,9),('right',6,12,10)]:
            history = state['wrists'][side]
            while history and tick-history[0][0]>3:
                history.popleft()
            if not all(points[i][2]>=.5 and points[i][0]>0 and points[i][1]>0 for i in (s,h,w)):
                history.clear();continue
            torso = math.dist(points[s][:2],points[h][:2])
            if torso < 15 or points[w][1]>points[s][1]+torso*.1:
                history.clear();continue
            history.append((tick,(points[w][0]-points[s][0])/torso))
            if len(history)>=5 and history[-1][0]-history[0][0]>=.6:
                pivot=history[0][1];direction=0;reversals=0
                for _,value in history:
                    delta=value-pivot
                    if direction==0 and abs(delta)>=.15:
                        direction=1 if delta>0 else -1;pivot=value
                    elif direction and delta*direction>0:
                        pivot=value
                    elif direction and delta*direction<=-.15:
                        reversals+=1;direction=-direction;pivot=value
                if reversals>=2 and max(v for _,v in history)-min(v for _,v in history)>=.3:
                    labels.append(f'{side.capitalize()} hand waving (estimate)')
        candidate=tuple(sorted(labels))
        if candidate != state['candidate']:
            state['candidate'],state['since'] = candidate,tick
            state['confirmed'] = ()
        elif tick-state['since']>=.6:
            state['confirmed'] = candidate
        return list(state['confirmed'])

def pose_observations(points):
    if len(points) != 17:
        return []
    def visible(*indices):
        return all(points[i][2] >= .5 and points[i][0] > 0 and points[i][1] > 0 for i in indices)
    labels = []
    for side, shoulder, hip, wrist in [('left',5,11,9),('right',6,12,10)]:
        if visible(shoulder,hip,wrist):
            torso = math.dist(points[shoulder][:2],points[hip][:2])
            if torso > 10 and points[wrist][1] < points[shoulder][1] - torso*.15:
                labels.append(f'{side} hand above shoulder')
    for side, hip, knee, ankle in [('left',11,13,15),('right',12,14,16)]:
        if visible(hip,knee,ankle):
            a = [points[hip][j]-points[knee][j] for j in (0,1)]
            b = [points[ankle][j]-points[knee][j] for j in (0,1)]
            lengths = math.hypot(*a)*math.hypot(*b)
            if lengths > 100:
                angle = math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(a,b))/lengths))))
                if angle < 125:
                    labels.append(f'{side} knee bent')
    return labels
