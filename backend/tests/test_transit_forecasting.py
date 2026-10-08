"""Forecast contracts, genuine fitting/evaluation, temporal leakage and reproducibility."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.transit_forecasting import (
    FEATURES, TransitForecastService, aggregate_route_history, build_forecast_frame,
    chronological_masks, generate_synthetic_demand,
)

ROUTES = [
    {"id": "R01", "stop_ids": ["S01", "S02"], "bus_capacity": 50, "cycle_minutes": 48, "current_buses": 4},
    {"id": "R02", "stop_ids": ["S01", "S03"], "bus_capacity": 50, "cycle_minutes": 30, "current_buses": 2},
]


@pytest.fixture(scope="module")
def trained_service(tmp_path_factory):
    folder = tmp_path_factory.mktemp("forecast_artifacts")
    service = TransitForecastService(ROUTES, folder / "models", dataset_path=folder / "history.csv.gz")
    service.train(regenerate=True, n_estimators=24)
    return service


def test_reproducible_ninety_day_stop_history():
    first = generate_synthetic_demand(ROUTES)
    second = generate_synthetic_demand(ROUTES)
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 90 * 48 * 4
    assert first["timestamp"].nunique() == 90 * 48
    assert (first["boardings"] >= 0).all()
    assert first["crowd_observation"].isna().any()
    assert set(first["source"]) == {"SYNTHETIC_DEMO_DATA"}
    combined = aggregate_route_history(first)
    sums = first.groupby(["route_id", "timestamp"])["boardings"].sum().sort_index()
    totals = combined[combined["stop_id"] == "ALL"].set_index(["route_id", "timestamp"])["boardings"].sort_index()
    pd.testing.assert_series_equal(sums, totals)


def test_origin_features_do_not_read_future_observations():
    history = aggregate_route_history(generate_synthetic_demand(ROUTES))
    origin = history["timestamp"].min() + pd.Timedelta(days=35)
    original = build_forecast_frame(history, 120)
    changed = history.copy()
    after = changed["timestamp"] > origin
    changed.loc[after, "boardings"] = 999999
    changed.loc[after, ["traffic_congestion", "weather_rain", "crowd_observation"]] = 999999
    perturbed = build_forecast_frame(changed, 120)
    before = original["timestamp"] <= origin
    pd.testing.assert_frame_equal(original.loc[before, FEATURES], perturbed.loc[before, FEATURES])
    at_origin = original["timestamp"] == origin
    assert not np.array_equal(original.loc[at_origin, "target"], perturbed.loc[at_origin, "target"])


def test_chronological_splits_purge_target_windows(trained_service):
    for horizon in (30, 60, 120):
        frame = trained_service._frames[horizon]
        masks, split = chronological_masks(frame)
        train, validation, test = (frame.loc[masks[name]] for name in ("train", "validation", "test"))
        assert train["target_end"].max() < validation["timestamp"].min()
        assert validation["target_end"].max() < test["timestamp"].min()
        assert len(train) and len(validation) and len(test)
        assert split["train"]["rows"] == len(train)
        assert train["timestamp"].min() >= frame["timestamp"].min() + pd.Timedelta(days=7)


def test_models_are_native_serialized_and_metrics_measured(trained_service):
    metadata = json.loads((trained_service.artifacts_dir / "evaluation.json").read_text())
    assert metadata["algorithm"].startswith("XGBoost")
    for horizon in (30, 60, 120):
        assert (trained_service.artifacts_dir / f"demand_{horizon}.json").exists()
        report = metadata["evaluation"][str(horizon)]
        for split in ("validation", "test"):
            assert report[split]["ml"]["mae"] >= 0
            assert report[split]["seasonal_baseline"]["rmse"] >= 0
            assert report[split]["route_totals"]["ml"]["wape_percent"] >= 0
    loaded = TransitForecastService(ROUTES, trained_service.artifacts_dir, dataset_path=trained_service.dataset_path)
    loaded.ensure_ready(train_if_missing=False)
    assert loaded.forecast("R02")["predicted_passengers"] == trained_service.forecast("R02")["predicted_passengers"]


def test_forecast_capacity_horizons_and_no_request_retraining(trained_service, monkeypatch):
    def forbidden_train(*args, **kwargs):
        raise AssertionError("Prediction requests must never train models")
    monkeypatch.setattr(trained_service, "train", forbidden_train)
    thirty = trained_service.forecast("R02", horizon_minutes=30)
    sixty = trained_service.forecast("R02", horizon_minutes=60)
    one_twenty = trained_service.forecast("R02", horizon_minutes=120)
    assert thirty["available_capacity"] == 100
    assert sixty["available_capacity"] == 200
    assert one_twenty["available_capacity"] == 400
    assert thirty["predicted_passengers"] <= sixty["predicted_passengers"] <= one_twenty["predicted_passengers"]
    assert len(sixty["history"]) == 48 and len(sixty["future_points"]) == 2
    assert abs(sum(point["predicted_passengers"] for point in sixty["future_points"]) - sixty["predicted_passengers"]) <= 0.02
    constrained = trained_service.forecast("R02", capacity=10)
    assert constrained["capacity_shortfall"] == round(max(constrained["predicted_passengers"] - 10, 0), 2)
    assert constrained["source"] == "ML_FORECAST"
    assert constrained["uncertainty_interval"] is None
    stop = trained_service.forecast("R02", "S01")
    assert 0 < stop["available_capacity"] < sixty["available_capacity"]
    assert len(trained_service.forecast_all()["forecasts"]) == 2


def test_prediction_validation_and_explicit_crowd_signal(trained_service):
    for route, stop, horizon in [("BAD", None, 60), ("R02", "S02", 60), ("R02", None, 45)]:
        with pytest.raises(ValueError):
            trained_service.forecast(route, stop, horizon)
    with pytest.raises(ValueError, match="beyond recorded history"):
        trained_service.forecast("R02", forecast_at="2026-10-09T12:00:00+05:30")
    with pytest.raises(ValueError, match="seven days"):
        trained_service.forecast("R02", forecast_at=trained_service.history_frame["timestamp"].min().isoformat())
    with pytest.raises(ValueError):
        trained_service.forecast("R02", crowd_observation=-1)
    result = trained_service.forecast("R02", crowd_observation=25)
    assert result["crowd_signal_used"] is True
    assert any("not calibrated" in note for note in result["notes"])


def test_historical_stop_capacity_uses_only_preceding_observations(trained_service, monkeypatch):
    origin = trained_service.history_frame["timestamp"].min() + pd.Timedelta(days=40)
    before = trained_service.forecast("R02", "S01", forecast_at=origin.isoformat())
    perturbed = trained_service._series_frame.copy()
    future_stop = (perturbed["timestamp"] > origin) & (perturbed["route_id"] == "R02") & (perturbed["stop_id"] == "S01")
    perturbed.loc[future_stop, "boardings"] = 999999
    monkeypatch.setattr(trained_service, "_series_frame", perturbed)
    after = trained_service.forecast("R02", "S01", forecast_at=origin.isoformat())
    assert after["available_capacity"] == before["available_capacity"]


def test_uninitialized_service_does_not_train_implicitly(tmp_path):
    service = TransitForecastService(ROUTES, tmp_path / "models", dataset_path=tmp_path / "history.csv.gz")
    with pytest.raises(RuntimeError, match="not ready"):
        service.forecast("R02")
    with pytest.raises(RuntimeError, match="artifacts"):
        service.ensure_ready(train_if_missing=False)
