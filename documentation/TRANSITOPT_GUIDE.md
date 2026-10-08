# TransitOpt AI: local setup and demonstration

**Predict Demand · Analyze Traffic · Optimize Routes · Improve Service**

The application extends the existing VisionX FastAPI, async SQLAlchemy database,
React/TypeScript/Vite frontend, and cached Ultralytics YOLO inference. Existing
image, video, human, ship/container, model center, history and live-camera APIs
remain available. The detector is reused without automatic retraining or replacement.

## Install and launch on this Windows workspace

Use Python 3.13 and Node.js 22.12 or newer. The existing `.venv` uses Python 3.13.5.
Run these commands from PowerShell:

```powershell
Set-Location -LiteralPath 'D:\ml\visionx-ai'
# Only if .venv does not exist:
if (-not (Test-Path -LiteralPath .venv)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Only if .env does not exist; preserve an existing configuration:
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The Python server serves the built frontend and API
from one origin. API documentation is **http://127.0.0.1:8000/api/docs**. There is no
external account dependency for the local demo. First launch seeds the relational
transit network/history and prepares missing forecast artifacts; readiness is
reported by `/api/system/status`.

The compatible launchers perform dependency checks and build the frontend:

```powershell
.\Run-TransitOpt.bat start
.\Run-TransitOpt.bat status
.\Run-TransitOpt.bat stop
# Check Python and Node prerequisites without changing files/services:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\Start-VisionX.ps1 -CheckOnly
```

`Run-VisionX.bat` remains supported. An already-running backend should be restarted
after installing backend changes. The stop command targets this project's server.

For frontend development, start the backend as above and run in another terminal:

```powershell
Set-Location -LiteralPath 'D:\ml\visionx-ai\frontend'
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173**. Vite proxies API requests to port 8000. A browser
webcam requires user permission and a supported local/secure browser context.

## Existing detection model

The original model registry and inference services remain the source of truth.
The configured detector is `weights/yolo26n.pt` in this workspace; settings
`GENERAL_MODEL`, `HUMAN_MODEL`, `SHIP_MODEL` and `CONTAINER_MODEL` select existing
model filenames. Model Center lets an operator inspect/install/register trusted
weights and choose defaults. Do not upload an untrusted PyTorch checkpoint.
Fresh databases seed the model filenames from `GENERAL_MODEL`, `HUMAN_MODEL`,
`SHIP_MODEL` and `CONTAINER_MODEL`; existing Model Center records are preserved.
The default public YOLO26 weights may download on first inference if absent.
For custom models, provide the authorized existing checkpoint in `WEIGHTS_DIR`
(or mount it into `/app/weights` in Docker). Unknown checkpoint classes remain
uninspected until the real model is loaded; no detector is automatically retrained.
Human inference filters the model's actual person class; general inference detects
its supported COCO vehicles. Tracking IDs are local object tracks, without face
recognition or identity inference. Ship/container functionality retains its existing
capability warnings when specialized weights are absent.

The TransitOpt adapter normalizes actual detections, preserves class/confidence
and bounding-box output, and attaches source and frame timestamps. It does not
invent unsupported classes or detections. Recorded video inference uses a worker
job with status/progress and pause/resume/cancel actions. The loaded model is reused
throughout a video, rather than reloaded every frame.

## Connected hackathon walkthrough

1. Open the operator dashboard. Show the **synthetic Salem-inspired network**,
   routes R01–R08 and dynamically calculated fleet/capacity KPIs. Canvas coordinates
   are illustrative, not verified GPS or official government routes.
2. Open CCTV Intelligence. Select a camera/corridor and the bundled authorized
   sample image or video, or upload your authorized footage. Start analysis and show
   real people/vehicle detections, bounding boxes, confidence and processing FPS.
   The bundled video is a labeled 15-frame stationary clip made from the bundled
   sample photo to demonstrate background video processing; it is not live CCTV.
3. Inspect the stored traffic observation and corridor event. Counts/density are
   frame aggregates; the congestion score is a documented estimate. Ordinary
   detections do not provide physical vehicle speed, calibrated queue length, or
   ticketed ridership. Unsupported metrics display unavailable.
4. Open Passenger Demand, choose **R02** and **60 minutes**, and run forecast.
   Show the actual XGBoost output, seasonal baseline, held-out errors and matched
   horizon capacity/shortfall. Forecasts use generated ridership, and crowd features
   remain labeled estimates.
5. Run Route Optimization with **28 fleet**, **4 reserve**, a **30-minute maximum
   headway**, current traffic, normal demand, no additional event, and a **5-second
   solver limit**. Show actual CP-SAT status, constraints, allocation, frequency,
   alternate corridor and remaining shortfall.
6. On Transit Network compare the existing and recommended paths. Alternatives
   follow graph-validated road segments and retain required stops.
7. In Recommendations review every changed route in the run. Approve the complete
   changed plan, then choose **Activate in Simulation**. Pending/rejected/stale or
   infeasible plans cannot activate. Activation updates the entire allocation
   transaction and audit trail; it does not dispatch real buses.
8. In What-If Simulator choose **+20% demand**, select traffic/fleet/event controls,
   and run again. Show updated computed demand, allocation and constraints. A strict
   low-fleet scenario may return meaningful infeasibility instead of a fake plan.
9. Compare baseline and optimized waits, coverage, cost and delay from the same
   scenario assumptions. A weighted optimum can improve some metrics and worsen
   others; the displayed differences are calculations, not claimed guarantees.
10. Export stored forecast, traffic, recommendation, scenario or operator records
    as CSV/JSON. Per-scenario export includes its actual baseline and solver result.

The script `scripts/run_demo.py` performs the same API flow and saves exports. Its
default leaves recommendations for operator review; the explicit `--activate`
switch approves and activates its complete run in simulation.

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py
.\.venv\Scripts\python.exe scripts\run_demo.py --activate
```

## Reproduce the synthetic dataset and forecast artifacts

```powershell
.\.venv\Scripts\python.exe scripts\train_transit_forecast.py
# Explicitly regenerate deterministic history and retrain forecast models only:
.\.venv\Scripts\python.exe scripts\train_transit_forecast.py --force
```

The generator uses seed 42 and creates at least 90 days of half-hour stop boardings,
morning/evening peaks, illustrative calendar events, weather/congestion and crowd
proxies. Native XGBoost JSON artifacts and measured evaluation metrics persist in
`data/forecasting`; the compressed source history is
`data/synthetic/transit_demand.csv.gz`. Existing detection weights are untouched.
The forecast is trained chronologically with split-boundary target purging and
evaluated against the same-weekday/half-hour historical baseline.

Read [forecasting.md](forecasting.md) for feature, split and horizon details and
[OPTIMIZATION.md](OPTIMIZATION.md) for capacity, unit scaling, weights and graph
constraints. Data/API contracts are in
[TRANSIT_API_CONTRACT.md](TRANSIT_API_CONTRACT.md).

## Docker

Docker retains the existing `app` and PostgreSQL services. Set strong values for
`POSTGRES_PASSWORD` and `ADMIN_PASSWORD` in `.env`, and optionally
`ADMIN_USERNAME`. Do not use the development password in production.

```powershell
docker compose up --build
```

Open **http://127.0.0.1:8000** and authenticate with the configured operator
credentials. Named volumes retain the database, weights, reports, inference
outputs and `/app/data` synthetic/forecast artifacts. The container also includes
training/demo scripts. Missing weights may need a one-time authorized model
installation/download through Model Center. Initial build downloads public Python
and npm packages. The container uses the compatible existing Python 3.12 base.

## Final project structure

The original VisionX modules remain alongside the additive TransitOpt modules:

```text
visionx-ai/
├── backend/
│   ├── main.py, config.py, database.py, security.py
│   ├── api/
│   │   ├── analyze.py, live.py, models.py, reports.py  # Existing VisionX APIs
│   │   └── transit.py                              # Connected TransitOpt APIs
│   ├── models/registry.py                          # Existing cached model registry
│   ├── services/
│   │   ├── detector.py, image_processor.py, video_processor.py, live_detector.py
│   │   ├── transit_forecasting.py                  # Synthetic history + XGBoost
│   │   └── transit_optimizer.py                    # OR-Tools + plan evaluation
│   ├── transit/
│   │   ├── models.py, schemas.py, seed.py            # Tables, inputs, network seed
│   │   └── service.py, vision.py                    # Persistence + vision adapters
│   └── tests/                                     # Existing + transit tests
├── frontend/src/
│   ├── App.tsx, main.tsx, transit.css
│   ├── components/transit/                        # Layout, map, resource helpers
│   ├── pages/transit/                             # Dashboard and all transit screens
│   ├── pages/                                     # Preserved VisionX screens
│   ├── services/api.ts, services/transit.ts         # Authenticated API clients
│   └── tests/                                     # Connected workflow UI tests
├── weights/                                       # Existing trusted detector weights
├── training/                                      # Preserved detector training tools
├── data/
│   ├── synthetic/transit_demand.csv.gz             # Generated 90-day history
│   ├── forecasting/                               # XGBoost JSON + evaluation artifacts
│   └── demo_exports/                              # Calculated CSV/JSON demonstrations
├── scripts/
│   ├── Start-VisionX.ps1
│   ├── train_transit_forecast.py                   # Generate/cache forecasting artifacts
│   └── run_demo.py                                 # Connected end-to-end API demo
├── documentation/                                 # Audit, contracts, models, assumptions, QA
├── Run-TransitOpt.bat, Run-VisionX.bat
└── Dockerfile, docker-compose.yml, requirements.txt, .env.example
```

Generated data, model weights, databases and exports are runtime artifacts. Local
SQLite uses `visionx.db`; Docker Compose persists PostgreSQL and `/app/data` volumes.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m pytest backend\tests\test_transit_optimizer.py -q
Set-Location frontend
npm.cmd test
npm.cmd run build
```

The optimizer suite exercises genuine solver allocations, reserve/headway/essential
stop constraints, graph continuity, excluded invalid alternatives, infeasibility,
scenario multipliers, changing congestion and whole-plan activation validation.
The original VisionX suite includes genuine bundled-image/video model inference,
live camera tracking, authentication, upload validation and model lifecycle.
Forecasting and transit API suites add chronological splits, actual evaluation,
persistence, forecasts, recommendations and approval workflow. Final delivery
reports the checks actually run; commands above also let you repeat them locally.
See [VALIDATION.md](VALIDATION.md) for the recorded connected API demonstration
and its computed observations, forecasts, solver results and exported files.

## Security and practical limits

HTTP Basic authentication is configurable locally and required by the production
compose service. Existing upload limits, safe storage paths, allowed file types,
origin checks and retention cleanup remain in place. Camera/network credentials
must not be exposed to the browser. Network-camera/RTSP ingest is unavailable until
an authorized source adapter is configured and supported; uploaded footage and
browser webcam are the current supported paths.

The demonstration uses synthetic boardings and illustrative road geometry.
Forecast evaluation describes synthetic held-out observations, not real Salem
accuracy. Cost, delay, headway and capacity are planning estimates. No calibrated
speed/queue measurement, uncertainty interval, real GPS bus feed or real dispatch
integration is claimed. Browser-camera and inference FPS depend on hardware and
camera permissions. SQLite supports the local demo; PostgreSQL is provided for
deployment. PDF reports are optional; CSV/JSON exports are implemented.

**PREDICT SMARTER. OPTIMIZE BETTER. MOVE PEOPLE EFFICIENTLY.**
