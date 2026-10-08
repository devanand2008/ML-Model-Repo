# TransitOpt AI: existing-project audit and implementation plan

The existing project is extended in place. A verified recovery archive was made before source changes: `D:/ml/backups/visionx-before-transitopt-20261008-183214-complete.zip`. It includes source, configuration, consistent SQLite snapshots, model weights and existing reports. Python/npm dependencies and disposable uploads/builds are recreated from manifests.

## Existing capabilities

- React 19, TypeScript, Vite 8, Tailwind 4, React Router, Lucide and Recharts.
- FastAPI, Pydantic 2, async SQLAlchemy, SQLite locally, PostgreSQL support, HTTP Basic authentication, CORS and bounded uploads/inference.
- Existing YOLO nano checkpoints in `weights/`, chosen through Model Center records; no replacement detector and no automatic detector training.
- Genuine image inference, tracked video jobs, continuous browser webcam inference, pose skeletons, text reports, model administration and analysis history.
- Detection output: class, class ID, confidence, pixel `[x, y, width, height]` bounding boxes; frame/session tracking IDs when enabled. COCO supports people, cars, buses, trucks, motorcycles and bicycles. Track IDs identify temporary detections, not people.
- Browser webcam and uploaded files are supported. No existing authorized RTSP worker, calibrated physical-speed measurement, passenger ticketing data, or queue measurement exists. Those metrics are unavailable rather than invented.
- Existing tables: users, AI models, versions, analyses, detections and datasets. Existing routes/API paths remain accessible.

## Implementation sequence

1. Add transit entities and an idempotent additive migration/seed using the same database and authentication.
2. Adapt real detection results into camera-associated aggregate crowd and vehicle observations with normalized regions of interest and transparent congestion assumptions.
3. Seed eight illustrative Salem-inspired routes, graph-validated alternatives, essential stops, 28 vehicles and reproducible 90-day half-hour ridership data.
4. Fit separate XGBoost demand models with chronological holdouts, origin-only lag/rolling features, seasonal baseline and calculated evaluation metrics. Save and reuse model artifacts.
5. Run OR-Tools CP-SAT with hard fleet/reserve/coverage/headway constraints, explicit unmet demand, configurable objective assumptions and meaningful infeasibility results.
6. Connect dashboard, stylized network, forecasts, scenarios, comparisons and exports to stored API results.
7. Require operator approval before transactional simulated activation. Record all decisions; simulated plans never operate real buses.
8. Test detector preservation, chronology/leakage, constraints, approval, persistence, UI actions and the complete connected workflow. Build and launch locally.

## Labels and units

The map uses illustrative coordinates, not unverified geographic coordinates or official routes. Synthetic traffic/ridership, real model detections, ML forecasts and solver results are labeled separately. Detected people are crowd observations, not ticketed passengers. Video counts summed over frames are not unique traffic throughput. Pixel movement is not physical speed. Capacity and forecast demand are compared over the same horizon. Simulated wait, delay and cost use documented assumptions and are not guaranteed field outcomes.
