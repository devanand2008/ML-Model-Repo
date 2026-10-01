# VisionX AI Analyzer

A React/TypeScript dashboard and Python/FastAPI computer vision service using OpenCV and Ultralytics YOLO26. No generated or simulated detections are used. Pretrained weights download on first inference and are cached in `weights/`.

## Run locally

**Windows launcher:** double-click `Run-VisionX.bat`. It creates a Python virtual environment if needed, installs missing dependencies, builds the dashboard, starts the API and web UI together at http://127.0.0.1:8000, and opens your browser. Install Python 3.12/3.13 and Node 22.12+ first. The server stays running when the launcher window closes. Use `Run-VisionX.bat start` to start it, `Run-VisionX.bat status` to check it, and `Run-VisionX.bat stop` to stop only this project's server. An already-running VisionX server is reused. Logs are in `logs/`. Existing `.env` settings are preserved. Run `Run-VisionX.bat -CheckOnly` to check prerequisites without starting services.

Use Python 3.12 or 3.13 and Node 22.12+ from the `visionx-ai` directory. The CPU path works without a GPU.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# On a fresh installation only; preserve an existing .env:
Copy-Item .env.example .env
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API documentation: http://localhost:8000/api/docs. Vite proxies `/api` to the backend. On Linux/macOS activate with `source .venv/bin/activate` instead.

For a single-server build, run `npm run build` in `frontend`, then start the backend and open http://localhost:8000. The API serves the built dashboard with SPA routing. `VITE_API_URL` is optional for deployments with a separate API origin.

## Capabilities

| Module | Pretrained behavior | Custom model support |
|---|---|---|
| Image | COCO 80-class detection | General detection weights |
| Human | Person-only detection; optional 17-keypoint pose weights | Person detection weights |
| Ship | COCO boat class, explicitly identified as a fallback | Maritime detection and trained ship subtype classes |
| Container | General-object fallback, container count shown as unavailable | `container`, `intermodal container` detection weights |
| Condition | Unavailable without trained weights | Separate YOLO classification model on individual container crops; `good` and `damaged` classes |
| Combined | People, boats/ships, trucks, other COCO objects | Adds custom human, ship and container detectors |
| Webcam | Continuous WebSocket detection, tracking IDs, trajectories, live counts and snapshots | Uses active Model Center defaults; adds custom port detectors |
| Video | Frame-by-frame YOLO detection and tracking, progress, trajectories, unique IDs, annotated MP4 | Human, ship or container detector selection |

Container detection is not a COCO capability. The fallback never calls unrelated objects containers or labels unclassified containers good. Ship subtypes depend on the class names actually present in trained weights. Satellite/drone/port performance requires evaluation on representative held-out data. No personal attributes are inferred.

Image confidence filtering is immediate in the browser: inference requests the supported 0.10 floor, and the current threshold filters boxes, tables, counts, annotations and exports. History records the raw inference threshold/results; exported reports reflect the current visible detections. Counts in video summaries are **detections across frames**, not unique objects; `unique_count` counts tracker IDs and can overcount when identities are lost. Movement is measured in image pixels, not physical speed.

Open **Live Webcam**, allow camera access, click **Start Camera**, then **Start Detection**. Choose All Objects, Human Detection, Ship Detection, Containers or Port Monitor. The pretrained live model is YOLO26 nano. Tracking is enabled by default with ByteTrack; IDs and movement paths persist within each session. Toggle tracking or change the mode to reset tracking state. Use Save Snapshot to download an annotated frame.

Live webcam frames are sent through an authenticated WebSocket at up to 15 frames/second per session, with one frame in flight at a time. Actual speed depends on CPU/GPU performance; the dashboard reports measured inference FPS and latency. Up to two live sessions are admitted; each has its own YOLO instance/tracker. Start Detection obtains a single-use 30-second ticket through the authenticated HTTP API. Raw and annotated live frames stay in memory and are not added to history. Connections expire after one hour and close after 60 seconds without input.

Port Monitor combines general detections with installed custom human/ship/container models. Container-only mode requires trained container weights. Port Monitor reports container count as unavailable when those weights are absent. No COCO object is treated as a container proxy. Camera capture requires localhost or HTTPS and browser permission.

## Models and administration

Model Center supports uploading `.pt` files, names, versions, class names, dataset metadata JSON, evaluation metrics JSON, activation, default selection, renaming and default confidence. SHA-256 and version records are stored for uploaded checkpoints. No accuracy metrics are populated without evaluation. Configuration is centralized in `backend/config.py` and database model records.

Only upload weights you trust: PyTorch checkpoints can execute code during loading. Uploads are administrator operations, use generated filenames, enforce type/size/metadata validation and require a checkpoint ZIP container. ZIP validation is not a malicious-model sandbox. Do not expose model administration to untrusted users. Separate inference workers/containers are necessary for mutually untrusted model authors.

Use Model Center to replace active defaults after the initial database seed. Environment model settings seed a fresh database; changing them does not overwrite existing model records. Example custom files:

```text
weights/human_model.pt
weights/ship_model.pt
weights/container_model.pt
weights/container_condition_model.pt
```

Condition weights must be YOLO **classification** weights trained on container crops. A detector with damage boxes is a different task and is rejected as a condition classifier. A condition model is used only when requested, with a compatible container detector.

## Training and evaluation

Datasets and trained custom weights are not bundled. Obtain images and licenses yourself; annotate the exact target domain. Candidate dataset resources supplied in the project brief include CrowdHuman, COCO, SeaDronesSee, xView and Roboflow. Convert their source annotations into YOLO format before preparation. Automatic provider downloads and source-format conversion are not included.

Detection input layout:

```text
raw/images/example.jpg
raw/labels/example.txt   # each row: class_id center_x center_y width height
```

Coordinates are normalized to [0,1]. Empty labels explicitly denote background images. Prepare a new destination (must be empty):

```powershell
python training/prepare_dataset.py --source raw --output prepared/containers --classes container "intermodal container"
python training/train_container.py --data prepared/containers/dataset.yaml --epochs 100 --device cpu
python training/train_human.py --data prepared/human/dataset.yaml
python training/train_ship.py --data prepared/ships/dataset.yaml
python training/evaluate.py --model models/containers/training/weights/best.pt --data prepared/containers/dataset.yaml
```

The preparer verifies images, normalized boxes, class IDs, duplicates and matching labels, then makes reproducible disjoint 80/10/10 splits (at least one validation/test image). For video/satellite datasets, split by sequence/site **before** preparation to avoid correlated train/test leakage; the tool rejects byte-identical duplicates but cannot detect near-duplicates.

Training validates all three splits and applies spatial/color augmentation. Detector evaluation uses the test split with a low confidence floor for precision-recall curves, exports precision, recall, mAP50, mAP50–95 and F1, and saves Ultralytics confusion-matrix plots. Do not tune training against the test split.

Condition classification layout uses cropped containers:

```text
datasets/container_condition/{train,val,test}/{good,damaged}/*.jpg
```

```powershell
python training/prepare_condition.py --source raw_condition --output prepared/condition
python training/train_condition.py --data prepared/condition --weights yolo26n-cls.pt
python training/evaluate.py --model models/container_condition/training/weights/best.pt --data prepared/condition
```

Classification evaluation returns top-1/top-5 accuracy and confusion plots; detection mAP does not apply to classification. The initial human/ship/container training dataset YAMLs are empty templates, not usable trained models. Training requires labeled data and adequate compute.

## Security, storage and operating limits

- Local mode is a single trusted operator and defaults to no login. Bind to `127.0.0.1`.
- Set `AUTH_ENABLED=true`, `ADMIN_USERNAME`, and a strong `ADMIN_PASSWORD` to require login. The dashboard sends Basic authentication over HTTPS in production. Credentials remain in frontend memory. Production refuses disabled auth or the sample password.
- This is a single-workspace admin application, not a multi-tenant SaaS. Analyses and models are shared by the configured administrator. The schema includes users for extension, but user registration and role management are not implemented.
- Original images stay in memory; previews are returned directly, never persisted. History stores metadata and detections, without image pixels.
- Video originals are temporary and deleted after processing (including errors). Annotated output expires after `OUTPUT_TTL_SECONDS`, default one hour. A startup/background sweep removes expired files. Download to retain a result. There is no permanent server-side image-save option.
- Upload limits: 100 MB input, 500 MB model, 25 MP images, video at most 4K/18,000 frames. A reverse proxy should enforce matching request-body limits before multipart parsing.
- Inference is limited to 30 requests per client/minute, four queued image operations and two asynchronous video jobs. Image operation responses time out after 120 seconds; an already-running native inference may finish in its bounded worker afterward. Video processing stops between frames after 30 minutes. Native-library hangs require restarting the worker.
- Use **one Uvicorn worker**: job state, inference admission and rate limits are process-local. Video jobs do not survive restarts. For horizontal scaling, replace these with a durable task queue/shared limiter.
- SQLite is the zero-setup development database. PostgreSQL via `asyncpg` is supported and is used by Docker Compose. Schema is defined in `backend/database.py` and exported in `backend/schema.sql`. Add migrations before changing a deployed schema.
- Local directories or mounted volumes provide storage. Cloud object-store integration is not implemented; production can mount persistent storage or extend the storage layer.

## Docker deployment

Set non-default `ADMIN_PASSWORD` and `POSTGRES_PASSWORD` in `.env`, then:

```powershell
docker compose up --build
```

Open http://localhost:8000. Compose builds the UI and API, starts PostgreSQL with a health check, and preserves database, weights and output volumes. The host port is loopback-only. Put an HTTPS reverse proxy in front before remote access; configure upload/time limits and backups. First inference requires internet to fetch official weights unless they are preinstalled. CPU image is provided; GPU deployment needs a CUDA-compatible PyTorch base and NVIDIA container runtime.

Ultralytics API reference: https://docs.ultralytics.com/models/yolo26/ and https://docs.ultralytics.com/usage/python/. Review Ultralytics and dataset licensing for your deployment.

## Live activity reports

The live page opens in **Human Actions & Skeleton** mode. Its action panel and camera labels include standing/sitting posture and waving estimates. Standing/sitting require confident joints on both legs and an upright torso. Waving requires repeated wrist reversals relative to the shoulder over a time window and persistent tracking; a still raised hand is not classified as a wave. Labels need a stable observation before display. These rule-based pose/gesture estimates are included in ten-minute reports and can be affected by camera angle and occlusion. They are not a trained semantic action classifier.

Choose **Human Actions & Skeleton** in the live camera controls for a tracked stick-figure overlay, enabled by default in that mode. It uses the configured `pose_model` (default `yolo26n-pose.pt`) to estimate 17 body joints for each person. Joints with low confidence are omitted from the overlay. The skeleton checkbox switches back to the selected human detection weights when disabled. All Objects continues to use the general object detector.

Human skeleton mode also displays conservative geometric observations: left/right hand above shoulder and left/right knee bent. Report events require an observation to remain stable for at least 0.8 seconds. These estimates and per-frame observation counts are included in the existing ten-minute text reports. They do not recognize intent, validate exercise form, or establish actions such as eating, fighting, or running. Occlusion, camera angle and uncertain keypoints can prevent an observation.

Run `Run-VisionX.bat start` and open http://127.0.0.1:8000/webcam. Click **Start Camera**, then **Start Detection**, and keep tracking enabled. The camera start time, elapsed camera time, and next report countdown appear above the feed. Backend status refreshes automatically; the connection screen shows the address and actual connection error if the server is unreachable.

During detection, the backend saves a text report every 600 seconds in `reports/` (override with `REPORT_DIR`). Reports contain IST timestamps, camera and monitoring start times, object classes, tracked IDs, moving/stationary estimates, image movement direction, observation gaps and visibility changes. They contain no camera images. **Stop Detection** saves the remaining partial interval; a disconnected session also saves its remaining observations. Reports survive app restarts and are available from **Saved text reports**. Automatic downloads are enabled by default; if the browser blocks repeated downloads, use **Download .txt**. Docker preserves them in a reports volume.

These are observations of image movement, not recognition of every human action. Semantic actions such as eating or fighting need a separately trained action model; camera movement, missed detections and occlusion can affect motion estimates. Reports cover only received frames and supported detector classes. Without tracking, reports contain class counts but cannot attribute movement to individual tracks. Monitoring requires the page, camera and backend to remain active; browser suspension can interrupt frame delivery. Live sessions end after one hour and must be restarted.

## Verification

```powershell
python -m pytest backend/tests -q
cd frontend
npm run build
```

Tests exercise real pretrained image detection, container fallback integrity, combined counts, video tracking, corrupt uploads, authentication and cleanup. The first test run downloads weights if necessary. Tests also cover live WebSocket tracking, authentication, invalid frames and mode changes. A real camera, representative custom-model accuracy and production infrastructure require deployment-specific validation.
