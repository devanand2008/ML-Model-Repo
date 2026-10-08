# TransitOpt forecasting and synthetic demand

The forecasting service is separate from the existing YOLO detection model. It does not retrain or replace detection weights. Data labels distinguish `SYNTHETIC_DEMO_DATA`, `ML_FORECAST`, and actual camera detections.

## Reproducible dataset

Run from the project root using the project's Python environment:

```powershell
.\.venv\Scripts\python.exe scripts\train_transit_forecast.py
# Explicitly regenerate and retrain:
.\.venv\Scripts\python.exe scripts\train_transit_forecast.py --force
```

The seeded generator creates 90 complete days of half-hour observations ending **8 October 2026, 17:30 IST**. Every route R01–R08 has observations for each of its illustrative stop IDs. Integer stop boardings sum exactly to route boardings. Morning/evening peaks, weekends, synthetic event spikes, illustrative holidays, rainfall, temperature, congestion, current service frequency and partially missing crowd proxies are generated with seed 42. The calendar is a demonstration assumption, not an official Salem event/holiday source. These routes are not official transport routes.

The compressed CSV is `data/synthetic/transit_demand.csv.gz`. Its columns include timestamp, route/stop IDs, boarding demand, historical and previous counts, congestion, service frequency, rainfall, temperature, event/holiday/peak flags, estimated crowd observation and provenance. The backend can persist this same stop-level history in the existing relational database; route-total series are derived sums, not additional observed passengers. `TRANSIT_FORECAST_DIR` and `TRANSIT_DEMAND_DATASET` override the default artifact/data locations; explicit CLI path arguments take precedence. Docker's `/app/data` volume preserves both directories.

## Actual training and evaluation

Three genuine XGBoost regressors forecast **cumulative boardings during the next 30, 60 or 120 minutes**. One global model per horizon learns both route totals and route/stop series. Route/stop identifiers, calendar features, current demand, 1/2/48/336-bin lags, 4/48-bin trailing means and origin-time exogenous features are used. Missing observations use XGBoost's native missing-value handling.

Training covers the first 60 days, validation the next 15, and final testing the last 15. The initial seven days warm up seasonal lags. Training/validation rows whose target window crosses the next split boundary are purged. All lag/rolling and measured exogenous inputs are available at the forecast origin. Only calendar information is projected forward; future observed demand, traffic, weather or crowd values are not copied into features. Training never uses validation or test targets, and served artifacts retain that training boundary.

The statistical baseline sums the same half-hour boarding observations one week earlier. MAE, RMSE and weighted absolute percentage error are computed from held-out targets for ML and baseline, including route-total metrics. The actual results and split timestamps are saved in `data/forecasting/evaluation.json` and exposed by model status/forecast responses. They describe synthetic data only. No real-world accuracy claim or calibrated uncertainty interval is made.

The delivered eight-route artifacts were trained on 103,680 stop-level observations. Their final synthetic test route-total results are:

| Horizon | XGBoost MAE | Seasonal baseline MAE | XGBoost RMSE | XGBoost WAPE |
| --- | ---: | ---: | ---: | ---: |
| 30 minutes | 4.6691 | 6.5635 | 6.7014 | 12.371% |
| 60 minutes | 6.9734 | 9.9725 | 10.0938 | 9.261% |
| 120 minutes | 10.8830 | 15.6810 | 15.8554 | 7.256% |

MAE/RMSE are boarding counts per forecast window. This table describes the delivered artifact and is not a guarantee for other datasets or retrained models; the evaluation JSON is authoritative.

## Forecast and capacity contracts

`TransitForecastService(route_specs, artifacts_dir)` exposes `ensure_ready()`, `status()`, `history()`, `forecast()` and `forecast_all()`. `history_frame` provides the generated stop-level DataFrame for database import. Model JSON files are native XGBoost artifacts. Startup may explicitly train missing artifacts once in a worker thread; prediction requests never train or reload models.

Forecast origins are bounded by the recorded history. A request in the first seven days or after the last observation is rejected with a useful error. Forecasting the next 120 minutes from the last observation is supported directly, without recursive pseudo-observations. Arbitrary future origins require a separately validated recursive/exogenous forecasting design and are deliberately unsupported.

Default service capacity equals **allocated buses × seats per bus × forecast minutes / route cycle minutes**. It is a continuous planning estimate of trip capacity. A stop's default share uses its past-week share of route boardings. The API may pass an explicit capacity to reflect activated allocations or traffic-adjusted travel time. Capacity shortfall/surplus are calculated from the same horizon, not by comparing an hourly boarding count with a static fleet seat count.

For charts, observed history is in boardings per half-hour. Forecast chart points distribute direct cumulative forecasts into nonnegative half-hour increments; the 90/120-minute increments split the remaining 120-minute total evenly. The forecast card displays the cumulative horizon demand. Cumulative horizon predictions are constrained to be nondecreasing.

A camera crowd observation may be supplied as an estimated feature. Its effect follows an association learned on synthetic crowd proxies; it is **not calibrated actual boarding demand**, and the response explicitly says so. Detected people are never treated as ticketed passengers. Uncertainty intervals, physical speed and real service guarantees are unavailable.
