"""One-minute scene-pressure learning from a single live camera session.

This forecasts scene pressure (including qualified GPS slowdowns), not travel time.
Recorded uploads and synthetic demand never train this model.
"""
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select

from transit.models import TransitTrafficObservation, TransitDetectionEvent, TransitCameraSetup

BIN_SECONDS = 10
HORIZON_BINS = 6
MIN_BINS = 60
_cache = {}


def local_history(rows, location):
    from transit.mobility import haversine_km
    local_rows = []
    for row in reversed(rows):
        point = row[2].get('capture_location')
        if not point or haversine_km(location['latitude'],location['longitude'],point['latitude'],point['longitude']) > .1:
            break
        local_rows.append(row)
    return local_rows[::-1]


def forecast_samples(samples, now: datetime) -> dict:
    enriched = any(len(row)>2 for row in samples)
    base = {"available": False, "model": "Ridge autoregression", "version": "scene-pressure-speed-v2" if enriched else "scene-pressure-v1",
            "horizon_seconds": 60, "target": "visible_vehicle_scene_pressure_0_100",
            "aggregation":"median per ten-second bin",
            "model_revision":"median-inner-tuning-v1",
            "source": "LIVE_CAMERA_HISTORY", "minimum_history_seconds": MIN_BINS * BIN_SECONDS,
            "note": "Scene-pressure forecast with vehicle-count and available GPS-speed inputs; not a calibrated travel-time prediction."}
    buckets = defaultdict(list)
    extra_buckets = defaultdict(list)
    for row in samples:
        timestamp, score = row[:2]
        if 0 <= (now - timestamp).total_seconds() <= 7200 and np.isfinite(score):
            bucket = int(timestamp.timestamp()) // BIN_SECONDS
            buckets[bucket].append(float(score))
            payload = row[2] if len(row)>2 else {}
            speed = payload.get('speed_observation') or {}
            raw_speed=speed.get('speed_kmh')
            valid = bool(speed.get('available') and isinstance(raw_speed,(int,float)) and np.isfinite(raw_speed) and 0<=raw_speed<=200)
            count=payload.get('vehicle_count',0)
            count=count if isinstance(count,(int,float)) and np.isfinite(count) and count>=0 else 0
            extra_buckets[bucket].append([count,raw_speed if valid else 0,
                                         int(bool(valid)),int(bool(speed.get('suspected_queue')))])
    # Use complete consecutive bins only; a camera gap starts a new learning window.
    completed = int(now.timestamp()) // BIN_SECONDS - 1
    values, extras = [], []
    while completed in buckets:
        values.append(float(np.median(buckets[completed])))
        extras.append(np.median(extra_buckets[completed], axis=0))
        completed -= 1
    values = np.asarray(values[::-1], dtype=float)
    extras = np.asarray(extras[::-1], dtype=float)
    base.update(history_bins=len(values), history_seconds=len(values) * BIN_SECONDS)
    if len(values) < MIN_BINS:
        return {**base, "status": "collecting", "reason": "Keep this road camera live for at least ten continuous minutes."}

    def features(window):
        return [window[-1], window[-2], window[-3], np.mean(window),
                window[-1] - window[-3], np.std(window)]

    def feature_at(i):
        result = features(values[i-5:i+1])
        if enriched:
            result += list(extras[i]) + list(extras[i]-extras[i-2])
        return result
    x = np.asarray([feature_at(i) for i in range(5, len(values)-HORIZON_BINS)])
    y = values[5+HORIZON_BINS:]
    split = int(len(x) * .8)
    # Purge overlapping forecast targets before the chronological holdout.
    train_end = split - HORIZON_BINS
    # Select regularization on an inner chronological split. The outer holdout
    # remains untouched and still decides whether the forecast may be used.
    inner_split=int(train_end*.75)
    inner_train_end=inner_split-HORIZON_BINS
    errors={}
    for alpha in (1.,10.,100.):
        candidate=make_pipeline(StandardScaler(),Ridge(alpha=alpha))
        candidate.fit(x[:inner_train_end],y[:inner_train_end])
        errors[alpha]=float(np.mean(np.abs(np.clip(candidate.predict(x[inner_split:train_end]),0,100)-y[inner_split:train_end])))
    alpha=min(errors,key=errors.get)
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
    model.fit(x[:train_end], y[:train_end])
    predictions = np.clip(model.predict(x[split:]), 0, 100)
    error = float(np.mean(np.abs(predictions-y[split:])))
    baseline_error = float(np.mean(np.abs(x[split:, 0]-y[split:])))
    metrics = {"validation_mae": round(error, 3), "persistence_mae": round(baseline_error, 3),
               "validation_samples": len(y)-split, "training_samples": train_end,
               "selected_alpha":alpha,"tuning":"inner chronological split with six-bin purge",
               "validation": "chronological holdout with six-bin target purge"}
    if baseline_error < 1 or error >= baseline_error * .95:
        return {**base, **metrics, "status": "baseline_preferred",
                "reason": "The model has not improved the holdout persistence baseline by 5%; use current observations."}
    model.fit(x, y)
    predicted = float(np.clip(model.predict([feature_at(len(values)-1)])[0], 0, 100))
    return {**base, **metrics, "available": True, "status": "validated",
            "predicted_score": round(predicted, 1), "current_score": round(values[-1], 1),
            "trend": "rising" if predicted > values[-1]+5 else "falling" if predicted < values[-1]-5 else "steady"}


async def camera_forecast(db, camera_id: str, now: datetime) -> dict:
    latest = (await db.execute(select(TransitDetectionEvent).where(
        TransitDetectionEvent.camera_id == camera_id).order_by(
        TransitDetectionEvent.timestamp.desc()).limit(1))).scalar_one_or_none()
    if not latest or latest.source_type != "browser_camera" or (now-latest.timestamp).total_seconds() > 15:
        return {"available": False, "status": "offline", "reason": "A fresh live road camera is required."}
    location = latest.payload.get('capture_location')
    setup = await db.get(TransitCameraSetup,camera_id)
    if setup and setup.role=='bus_road' and not location:
        return {'available':False,'status':'gps_required','reason':'The latest moving-bus frame needs synchronized accurate GPS.'}
    position_key = (round(location['latitude'],5),round(location['longitude'],5)) if location else None
    key = (camera_id, latest.source_id, int(now.timestamp())//BIN_SECONDS, position_key)
    if key in _cache:
        return _cache[key]
    rows = (await db.execute(select(TransitTrafficObservation.timestamp, TransitTrafficObservation.score, TransitTrafficObservation.payload)
        .join(TransitDetectionEvent, TransitTrafficObservation.detection_event_id == TransitDetectionEvent.id)
        .where(TransitTrafficObservation.camera_id == camera_id,
               TransitTrafficObservation.source == "REAL_MODEL_DETECTION",
               TransitDetectionEvent.source_type == "browser_camera",
               TransitDetectionEvent.source_id == latest.source_id,
               TransitTrafficObservation.timestamp >= now-timedelta(hours=2))
        .order_by(TransitTrafficObservation.timestamp))).all()
    location = latest.payload.get('capture_location')
    if location:
        rows = local_history(rows,location)  # Never learn different roads as one junction.
    # Ridge training is small, but keep inference and requests off the ASGI event loop.
    import asyncio
    result = await asyncio.to_thread(forecast_samples, rows, now)
    if len(_cache) >= 128:
        _cache.pop(next(iter(_cache)))
    _cache[key] = result
    return result
