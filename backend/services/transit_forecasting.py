"""Reproducible synthetic boarding history and cached direct-horizon XGBoost forecasts.

This module is independent of the existing detection model. A boarding count is a
synthetic ridership observation; a camera person count is only a crowd estimate.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (30, 60, 120)
SEED = 42
DEMO_END = "2026-10-08T17:30:00+05:30"
MODEL_VERSION = "transitopt-xgb-v1"
ALL_STOPS = "ALL"
FEATURES = [
    "route_index", "stop_index", "hour_sin", "hour_cos", "day_of_week",
    "weekend", "month", "future_peak", "scheduled_event", "synthetic_holiday",
    "demand_current", "lag_1", "lag_2", "lag_48", "lag_336", "rolling_4",
    "rolling_48", "traffic_congestion", "bus_frequency", "weather_rain",
    "temperature_c", "crowd_observation",
]


def _route_id(route: dict[str, Any]) -> str:
    return str(route.get("id", route.get("route_id", "")))


def _calendar(index: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    hour = index.hour.to_numpy() + index.minute.to_numpy() / 60.0
    # This is an illustrative calendar, not an official event or holiday feed.
    event = ((index.day.to_numpy() % 14 == 7) & (hour >= 16) & (hour < 22)).astype(int)
    holiday = ((index.dayofweek.to_numpy() == 6) | ((index.month == 8) & (index.day == 15))).astype(int)
    peak = (((hour >= 7) & (hour < 10)) | ((hour >= 17) & (hour < 20))).astype(int)
    return {"hour": hour, "event": event, "holiday": holiday, "peak": peak}


def generate_synthetic_demand(
    route_specs: list[dict[str, Any]], days: int = 90, seed: int = SEED,
    end_at: str = DEMO_END,
) -> pd.DataFrame:
    """Generate half-hour boardings at each route/stop pair, with reproducible RNG."""
    if days < 1:
        raise ValueError("days must be positive")
    routes = sorted(route_specs, key=_route_id)
    if not routes or len({_route_id(r) for r in routes}) != len(routes):
        raise ValueError("Provide unique nonempty route specifications")
    index = pd.date_range(end=pd.Timestamp(end_at), periods=days * 48, freq="30min")
    if index.tz is None:
        index = index.tz_localize("Asia/Kolkata")
    calendar = _calendar(index)
    hour = calendar["hour"]
    rng = np.random.default_rng(seed)
    frames: list[pd.DataFrame] = []
    base_levels = [66, 86, 59, 70, 65, 18, 79, 57]
    for route_index, route in enumerate(routes):
        route_id = _route_id(route)
        stops = list(dict.fromkeys(route.get("stop_ids", [])))
        if not route_id or not stops:
            raise ValueError(f"Route {route_id!r} requires stop_ids")
        base = base_levels[route_index % len(base_levels)]
        morning = np.exp(-0.5 * ((hour - 8.25) / 1.35) ** 2)
        evening = np.exp(-0.5 * ((hour - 18.0) / 1.65) ** 2)
        operating = np.where((hour >= 5) & (hour < 23), 1.0, 0.09)
        weekday = np.where(index.dayofweek.to_numpy() >= 5, 0.81, 1.0)
        rain_days = rng.binomial(1, 0.24, size=days + 1)
        elapsed_days = np.arange(len(index)) // 48
        rain = rain_days[elapsed_days].astype(float)
        temperature = 29 + 4 * np.sin(2 * np.pi * (hour - 8) / 24) + rng.normal(0, 0.6, len(index))
        congestion = np.clip(18 + 31 * morning + 39 * evening + route_index * 2 + rng.normal(0, 5, len(index)), 0, 100)
        expected = base * (0.36 + 1.08 * morning + 1.37 * evening) * operating * weekday
        expected *= 1 + 0.28 * calendar["event"] - 0.08 * rain - 0.12 * calendar["holiday"]
        expected *= 1 + 0.035 * np.sin(np.arange(len(index)) / 48 / 8)
        route_boardings = rng.poisson(np.maximum(expected, 0.2))
        weights = np.linspace(1.35, 0.65, len(stops))
        weights /= weights.sum()
        # Integer stop observations sum exactly to the synthetic route total.
        stop_boardings = np.array([rng.multinomial(int(total), weights) for total in route_boardings])
        frequency = float(route.get("current_buses", 3)) * 60 / float(route.get("cycle_minutes", 45))
        for stop_index, stop_id in enumerate(stops):
            boardings = stop_boardings[:, stop_index]
            crowd = np.maximum(0, boardings * 0.32 + rng.normal(0, 2.0, len(index)))
            crowd[rng.random(len(index)) < 0.18] = np.nan
            frames.append(pd.DataFrame({
                "timestamp": index, "route_id": route_id, "stop_id": str(stop_id),
                "day_of_week": index.dayofweek, "boardings": boardings,
                "historical_passenger_count": boardings,
                "previous_demand": np.r_[np.nan, boardings[:-1]],
                "traffic_congestion": np.round(congestion, 3),
                "bus_frequency": round(frequency, 4), "weather_rain": rain,
                "temperature_c": np.round(temperature, 3),
                "event_indicator": calendar["event"], "holiday": calendar["holiday"],
                "peak": calendar["peak"], "crowd_observation": np.round(crowd, 3),
                "source": "SYNTHETIC_DEMO_DATA",
            }))
    return pd.concat(frames, ignore_index=True).sort_values(["route_id", "stop_id", "timestamp"]).reset_index(drop=True)


def aggregate_route_history(history: pd.DataFrame) -> pd.DataFrame:
    """Add one route-total series without double-counting stops in persisted data."""
    aggregation = {"boardings": "sum", "historical_passenger_count": "sum", "previous_demand": "sum",
                   "crowd_observation": lambda values: values.sum(min_count=1)}
    for column in ["day_of_week", "traffic_congestion", "bus_frequency", "weather_rain",
                   "temperature_c", "event_indicator", "holiday", "peak"]:
        aggregation[column] = "mean"
    routes = history.groupby(["route_id", "timestamp"], as_index=False).agg(aggregation)
    routes["stop_id"] = ALL_STOPS
    routes["source"] = "SYNTHETIC_DEMO_DATA"
    return pd.concat([history, routes], ignore_index=True).sort_values(["route_id", "stop_id", "timestamp"]).reset_index(drop=True)


def build_forecast_frame(history: pd.DataFrame, horizon_minutes: int) -> pd.DataFrame:
    """Features use observations through origin; target contains only future bins.

    Future calendar fields are known deterministically. Future measured traffic,
    weather and crowd values are never copied into the feature matrix.
    """
    if horizon_minutes not in HORIZONS:
        raise ValueError("Supported horizons are 30, 60 and 120 minutes")
    steps = horizon_minutes // 30
    data = history.copy().sort_values(["route_id", "stop_id", "timestamp"]).reset_index(drop=True)
    grouped = data.groupby(["route_id", "stop_id"], sort=False)
    data["route_index"] = data["route_id"].str.extract(r"(\d+)")[0].astype(int)
    data["stop_index"] = data["stop_id"].str.extract(r"(\d+)")[0].fillna(0).astype(int)
    future_index = pd.DatetimeIndex(data["timestamp"] + pd.Timedelta(minutes=horizon_minutes / 2))
    calendar = _calendar(future_index)
    data["hour_sin"] = np.sin(2 * np.pi * calendar["hour"] / 24)
    data["hour_cos"] = np.cos(2 * np.pi * calendar["hour"] / 24)
    data["day_of_week"] = future_index.dayofweek
    data["weekend"] = (future_index.dayofweek >= 5).astype(int)
    data["month"] = future_index.month
    data["future_peak"] = calendar["peak"]
    data["scheduled_event"] = calendar["event"]
    data["synthetic_holiday"] = calendar["holiday"]
    data["demand_current"] = data["boardings"]
    for lag in [1, 2, 48, 336]:
        data[f"lag_{lag}"] = grouped["boardings"].shift(lag)
    for window in [4, 48]:
        data[f"rolling_{window}"] = grouped["boardings"].transform(lambda values: values.rolling(window, min_periods=1).mean())
    targets = [grouped["boardings"].shift(-step) for step in range(1, steps + 1)]
    # The seasonal baseline observes the same future half-hours one week earlier.
    baseline = [grouped["boardings"].shift(336 - step) for step in range(1, steps + 1)]
    data["target"] = pd.concat(targets, axis=1).sum(axis=1, min_count=steps)
    data["baseline"] = pd.concat(baseline, axis=1).sum(axis=1, min_count=steps)
    data["target_end"] = data["timestamp"] + pd.Timedelta(minutes=horizon_minutes)
    return data


def chronological_masks(frame: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """60/15/15-day split with target-end purging and one-week lag warmup."""
    start = frame["timestamp"].min()
    train_end = start + pd.Timedelta(days=60)
    validation_end = start + pd.Timedelta(days=75)
    eligible = frame["target"].notna() & frame["lag_336"].notna()
    masks = {
        "train": eligible & (frame["target_end"] < train_end),
        "validation": eligible & (frame["timestamp"] >= train_end) & (frame["target_end"] < validation_end),
        "test": eligible & (frame["timestamp"] >= validation_end),
    }
    description: dict[str, Any] = {"strategy": "chronological 60/15/15 days; 7-day lag warmup; target-end boundary purge",
                                  "train_cutoff": train_end.isoformat(), "validation_cutoff": validation_end.isoformat()}
    for split, mask in masks.items():
        part = frame.loc[mask]
        if part.empty:
            raise ValueError("At least 90 days of history are required for the evaluation split")
        description[split] = {
            "rows": len(part), "origin_start": part["timestamp"].min().isoformat(),
            "origin_end": part["timestamp"].max().isoformat(), "target_end": part["target_end"].max().isoformat(),
        }
    return masks, description


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    return {"mae": round(float(mean_absolute_error(actual, predicted)), 4),
            "rmse": round(math.sqrt(float(mean_squared_error(actual, predicted))), 4),
            "wape_percent": round(float(np.abs(actual - predicted).sum() / max(actual.sum(), 1) * 100), 3)}


class TransitForecastService:
    """Loads history/models once. Explicit ensure_ready may train missing artifacts."""
    def __init__(self, route_specs: list[dict[str, Any]], artifacts_dir: str | Path | None = None,
                 *, dataset_path: str | Path | None = None, seed: int = SEED):
        self.route_specs = sorted([dict(route) for route in route_specs], key=_route_id)
        self.routes = {_route_id(route): route for route in self.route_specs}
        self.artifacts_dir = Path(artifacts_dir or os.getenv("TRANSIT_FORECAST_DIR") or PROJECT_ROOT / "data" / "forecasting")
        self.dataset_path = Path(dataset_path or os.getenv("TRANSIT_DEMAND_DATASET") or PROJECT_ROOT / "data" / "synthetic" / "transit_demand.csv.gz")
        self.seed = seed
        self.history_frame = pd.DataFrame()
        self._series_frame = pd.DataFrame()
        self._frames: dict[int, pd.DataFrame] = {}
        self._models: dict[int, Any] = {}
        self.metadata: dict[str, Any] = {}
        self._lock = threading.RLock()

    @property
    def signature(self) -> str:
        # Only data-relevant fields are included; activation does not retrain models.
        specs = [{key: route.get(key) for key in ("id", "route_id", "stop_ids", "cycle_minutes", "current_buses")} for route in self.route_specs]
        raw = json.dumps({"routes": specs, "seed": self.seed, "end": DEMO_END, "version": MODEL_VERSION}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _load_history(self, regenerate: bool = False) -> None:
        if self.dataset_path.exists() and not regenerate:
            self.history_frame = pd.read_csv(self.dataset_path)
            self.history_frame["timestamp"] = pd.to_datetime(self.history_frame["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
        else:
            self.history_frame = generate_synthetic_demand(self.route_specs, seed=self.seed)
            self.dataset_path.parent.mkdir(parents=True, exist_ok=True)
            # Fixed gzip mtime preserves reproducibility beyond the random seed.
            self.history_frame.to_csv(self.dataset_path, index=False, compression={"method": "gzip", "mtime": 0})
        self._series_frame = aggregate_route_history(self.history_frame)
        self._frames = {horizon: build_forecast_frame(self._series_frame, horizon) for horizon in HORIZONS}

    def ensure_ready(self, train_if_missing: bool = True) -> dict[str, Any]:
        with self._lock:
            if self._models:
                return self.status()
            metadata_path = self.artifacts_dir / "evaluation.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            valid = metadata.get("dataset_signature") == self.signature and all((self.artifacts_dir / f"demand_{horizon}.json").exists() for horizon in HORIZONS)
            if not valid and not train_if_missing:
                raise RuntimeError("Forecast model artifacts are missing or incompatible; run scripts/train_transit_forecast.py")
            self._load_history(regenerate=not valid)
            if not valid:
                return self.train()
            from xgboost import XGBRegressor
            self.metadata = metadata
            for horizon in HORIZONS:
                model = XGBRegressor()
                model.load_model(self.artifacts_dir / f"demand_{horizon}.json")
                self._models[horizon] = model
            return self.status()

    def train(self, *, regenerate: bool = False, n_estimators: int = 180) -> dict[str, Any]:
        """Explicit offline/startup training; never called by forecast()."""
        from xgboost import XGBRegressor
        import xgboost
        with self._lock:
            if self.history_frame.empty or regenerate:
                self._load_history(regenerate=regenerate)
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            evaluation: dict[str, Any] = {}
            for horizon in HORIZONS:
                frame = self._frames[horizon]
                masks, splits = chronological_masks(frame)
                model = XGBRegressor(n_estimators=n_estimators, max_depth=6, learning_rate=0.08,
                                     subsample=0.9, colsample_bytree=0.95, objective="reg:squarederror",
                                     tree_method="hist", n_jobs=4, random_state=self.seed)
                train = frame.loc[masks["train"]]
                model.fit(train[FEATURES].astype(np.float32), train["target"].to_numpy())
                results: dict[str, Any] = {"splits": splits}
                for split in ["validation", "test"]:
                    part = frame.loc[masks[split]]
                    predicted = np.maximum(model.predict(part[FEATURES].astype(np.float32)), 0)
                    result = {"ml": _metrics(part["target"].to_numpy(), predicted),
                              "seasonal_baseline": _metrics(part["target"].to_numpy(), part["baseline"].to_numpy())}
                    route_mask = part["stop_id"].to_numpy() == ALL_STOPS
                    result["route_totals"] = {"ml": _metrics(part.loc[route_mask, "target"].to_numpy(), predicted[route_mask]),
                                               "seasonal_baseline": _metrics(part.loc[route_mask, "target"].to_numpy(), part.loc[route_mask, "baseline"].to_numpy())}
                    results[split] = result
                model.save_model(self.artifacts_dir / f"demand_{horizon}.json")
                self._models[horizon] = model
                evaluation[str(horizon)] = results
            self.metadata = {
                "model_version": MODEL_VERSION, "algorithm": "XGBoost direct multi-horizon regression",
                "xgboost_version": xgboost.__version__, "dataset_signature": self.signature,
                "seed": self.seed, "days": 90, "interval_minutes": 30,
                "history_start": self.history_frame["timestamp"].min().isoformat(),
                "history_end": self.history_frame["timestamp"].max().isoformat(),
                "stop_observation_rows": len(self.history_frame), "route_count": len(self.routes),
                "features": FEATURES, "native_missing_value_handling": True,
                "baseline": "sum of matching half-hour boardings one week earlier",
                "evaluation": evaluation, "data_source": "SYNTHETIC_DEMO_DATA",
            }
            (self.artifacts_dir / "evaluation.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")
            return self.status()

    def status(self) -> dict[str, Any]:
        return {"ready": bool(self._models), "model_version": MODEL_VERSION,
                "algorithm": "XGBoost", "horizons_minutes": list(HORIZONS),
                "data_source": "SYNTHETIC_DEMO_DATA", "dataset_path": str(self.dataset_path),
                "metadata": self.metadata}

    def _require_ready(self) -> None:
        if not self._models:
            raise RuntimeError("Forecast service is not ready; initialize it before forecasting")

    def _validate_series(self, route_id: str, stop_id: str | None) -> str:
        if route_id not in self.routes:
            raise ValueError(f"Unknown route {route_id}")
        selected = stop_id or ALL_STOPS
        if selected != ALL_STOPS and selected not in self.routes[route_id]["stop_ids"]:
            raise ValueError(f"Stop {selected} is not served by route {route_id}")
        return selected

    def history(self, route_id: str, stop_id: str | None = None, limit: int = 48,
                forecast_at: str | None = None) -> dict[str, Any]:
        self._require_ready()
        selected = self._validate_series(route_id, stop_id)
        if not 1 <= limit <= 4320:
            raise ValueError("history limit must be between 1 and 4320 half-hours")
        frame = self._series_frame
        part = frame[(frame["route_id"] == route_id) & (frame["stop_id"] == selected)]
        if forecast_at:
            at = self._parse_origin(forecast_at)
            part = part[part["timestamp"] <= at]
        points = [{"timestamp": row.timestamp.isoformat(), "passengers": int(row.boardings),
                   "boardings": int(row.boardings), "traffic_congestion": round(float(row.traffic_congestion), 2),
                   "crowd_observation": None if pd.isna(row.crowd_observation) else round(float(row.crowd_observation), 2),
                   "source": "SYNTHETIC_DEMO_DATA"} for row in part.tail(limit).itertuples()]
        return {"route_id": route_id, "stop_id": None if selected == ALL_STOPS else selected,
                "interval_minutes": 30, "source": "SYNTHETIC_DEMO_DATA", "history": points,
                "points": points, "count": len(points)}

    @staticmethod
    def _parse_origin(value: str) -> pd.Timestamp:
        try:
            at = pd.Timestamp(value)
        except Exception as exc:
            raise ValueError("forecast_at must be an ISO date/time") from exc
        if pd.isna(at):
            raise ValueError("forecast_at must be an ISO date/time")
        return at.tz_localize("Asia/Kolkata") if at.tz is None else at.tz_convert("Asia/Kolkata")

    def forecast(self, route_id: str, stop_id: str | None = None, horizon_minutes: int = 60,
                 forecast_at: str | None = None, capacity: float | None = None,
                 crowd_observation: float | None = None) -> dict[str, Any]:
        self._require_ready()
        selected = self._validate_series(route_id, stop_id)
        if horizon_minutes not in HORIZONS:
            raise ValueError("Supported horizons are 30, 60 and 120 minutes")
        latest = self._series_frame["timestamp"].max()
        at = self._parse_origin(forecast_at) if forecast_at else latest
        if at > latest:
            raise ValueError("Forecast origins beyond recorded history are unsupported; forecast from the latest observation")
        cumulative: dict[int, float] = {}
        baselines: dict[int, float] = {}
        row = None
        for horizon in HORIZONS:
            frame = self._frames[horizon]
            part = frame[(frame["route_id"] == route_id) & (frame["stop_id"] == selected) & (frame["timestamp"] <= at)]
            if part.empty:
                raise ValueError("No history exists at the requested forecast time")
            row = part.iloc[-1]
            if pd.isna(row["lag_336"]):
                raise ValueError("Forecast requires at least seven days of preceding history")
            features = row[FEATURES].astype(float).to_frame().T.astype(np.float32)
            if crowd_observation is not None:
                if not np.isfinite(crowd_observation) or crowd_observation < 0:
                    raise ValueError("crowd_observation must be finite and nonnegative")
                features["crowd_observation"] = float(crowd_observation)
            prediction = max(float(self._models[horizon].predict(features)[0]), 0)
            # Cumulative horizons cannot contain fewer boardings than shorter windows.
            cumulative[horizon] = max(prediction, max(cumulative.values(), default=0))
            baselines[horizon] = max(float(row["baseline"]), 0)
        origin = row["timestamp"]
        demand = round(cumulative[horizon_minutes], 2)
        route = self.routes[route_id]
        supplied_capacity = capacity is not None
        if capacity is None:
            capacity = float(route.get("current_buses", 3)) * float(route.get("bus_capacity", 50)) * horizon_minutes / float(route.get("cycle_minutes", 45))
            if selected != ALL_STOPS:
                recent = self._series_frame[(self._series_frame["timestamp"] > origin - pd.Timedelta(days=7)) &
                                            (self._series_frame["timestamp"] <= origin)]
                route_total = recent[(recent["route_id"] == route_id) & (recent["stop_id"] == ALL_STOPS)]["boardings"].sum()
                stop_total = recent[(recent["route_id"] == route_id) & (recent["stop_id"] == selected)]["boardings"].sum()
                capacity *= stop_total / max(route_total, 1)
        if not np.isfinite(capacity) or capacity < 0:
            raise ValueError("capacity must be finite and nonnegative")
        increments = [cumulative[30], cumulative[60] - cumulative[30],
                      (cumulative[120] - cumulative[60]) / 2, (cumulative[120] - cumulative[60]) / 2]
        baseline_increments = [baselines[30], baselines[60] - baselines[30],
                               (baselines[120] - baselines[60]) / 2, (baselines[120] - baselines[60]) / 2]
        future = [{"timestamp": (origin + pd.Timedelta(minutes=30 * (i + 1))).isoformat(),
                   "predicted_passengers": round(value, 2), "baseline_passengers": round(max(baseline_increments[i], 0), 2)}
                  for i, value in enumerate(increments[:horizon_minutes // 30])]
        return {"route_id": route_id, "stop_id": None if selected == ALL_STOPS else selected,
                "horizon_minutes": horizon_minutes, "forecast_at": origin.isoformat(),
                "forecast_end": (origin + pd.Timedelta(minutes=horizon_minutes)).isoformat(),
                "predicted_passengers": demand, "baseline_passengers": round(baselines[horizon_minutes], 2),
                "available_capacity": round(float(capacity), 2),
                "capacity_shortfall": round(max(demand - capacity, 0), 2),
                "capacity_surplus": round(max(capacity - demand, 0), 2),
                "capacity_method": "caller-supplied service capacity" if supplied_capacity else "buses × seats × horizon / cycle time; stop capacity uses past-week boarding share",
                "history": self.history(route_id, stop_id, 48, origin.isoformat())["history"],
                "future_points": future, "all_horizons": [{"horizon_minutes": h, "predicted_passengers": round(cumulative[h], 2), "baseline_passengers": round(baselines[h], 2)} for h in HORIZONS],
                "source": "ML_FORECAST", "data_source": "SYNTHETIC_DEMO_DATA", "model_version": MODEL_VERSION,
                "evaluation_metrics": self.metadata.get("evaluation", {}).get(str(horizon_minutes), {}),
                "uncertainty_interval": None, "crowd_signal_used": crowd_observation is not None,
                "notes": ["Synthetic boardings are distinct from detected people.",
                          "Forecasts and fractional trip capacity are planning estimates, not measured ridership or timetable guarantees.",
                          "Future chart half-hours distribute the direct cumulative horizon estimates; no calibrated uncertainty interval is available."] +
                         (["Camera crowd input uses a synthetic learned association; it is not calibrated real-world boarding demand."] if crowd_observation is not None else [])}

    def forecast_all(self, horizon_minutes: int = 60, forecast_at: str | None = None) -> dict[str, Any]:
        forecasts = [self.forecast(route_id, horizon_minutes=horizon_minutes, forecast_at=forecast_at) for route_id in self.routes]
        return {"horizon_minutes": horizon_minutes, "forecast_at": forecasts[0]["forecast_at"],
                "model_version": MODEL_VERSION, "source": "ML_FORECAST", "data_source": "SYNTHETIC_DEMO_DATA", "forecasts": forecasts}
