# TransitOpt AI 2.0: bus safety, GPS and road navigation

TransitOpt AI 2.0 extends the working TransitOpt 1.0 / VisionX app. The original YOLO26 detector, its model files, live WebSocket, video pipeline, XGBoost demand forecast and OR-Tools fleet solver are reused. The 2.0 layer adds a registered bus, an interior camera, GPS positions, public bus summaries, a real road map and a reviewable safety rule.

## Start locally

From `D:\ml\visionx-ai` in PowerShell:

```powershell
.\Run-TransitOpt.bat start
```

Open `http://127.0.0.1:8000` for the shared app home, `/ml` for camera ML, `/admin` for head office, `/passenger` for the public map, and `/driver` for device GPS. The local operator account is read from `.env` (`ADMIN_USERNAME` and `ADMIN_PASSWORD`); `AUTH_ENABLED=true` is required for private CCTV and incident endpoints. Use `Run-TransitOpt.bat status` or `stop` to manage the owned local server. The server binds loopback by default. See [camera ML and phone access](CAMERA_ML_GUIDE.md) for the current 2.1 setup.

Direct development commands:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Vite serves `http://localhost:5173` and proxies `/api` to port 8000. SQLite is used locally through the existing `DATABASE_URL`; the new tables are created additively at startup. Docker Compose still supports PostgreSQL, but a full Docker image build has not been validated for this 2.0 change. FastAPI schemas are at `/api/docs`.

## What is connected

The demo registration `TN30-N-1234` belongs to `BUS005` on the seeded R02 route. `BUS_CAM_001` is its interior camera. Existing `CAM01`–`CAM05` are road cameras. The registration, service network, camera pins and stop pins are illustrative demo data. Bus coordinates appear only after the driver app or explicit GPS simulation sends them. The 12 geolocated demo stops and five road camera pins are approximate; the UI labels them accordingly. An administrator can configure verified stop coordinates through `PUT /api/stops/{stop_id}/location` and register a new camera with operator-supplied coordinates.

An interior camera observation runs through the actual existing human detector and stores visible-person counts for its mapped bus. Public passengers see only an aggregate crowding level, timestamp and coverage warning. They cannot request raw interior detections, CCTV output or private incident evidence. Road cameras run the existing general detector for supported COCO vehicle classes and store count-based scene traffic estimates. A road camera does not cover surrounding roads beyond its field of view.

The safety rule uses a normalized doorway zone `[x,y,width,height]`, three consecutive **analyzed live browser-camera** frames containing a detected person in that zone, a fresh GPS speed of at least 5 km/h and a driver-reported open door from the past five minutes. Tracking IDs maintain a person's streak when available; absence, changed identity, changed zone or a frame gap resets it. A critical visible-crowd threshold sustained for three sampled live observations also creates a reviewable estimate alert. Thresholds can be configured in **Data & settings**. Partial coverage uses visible count thresholds; an actual load factor is available only when an administrator has verified full coverage. A single still image or untimecoded uploaded video does not generate a safety violation. The system stores detection and rule metadata, not an evidence frame. There is no automatic disciplinary decision, face recognition, email or SMS delivery. Operators can acknowledge, resolve, mark false positive and add notes; actions are recorded. Incident export is available at `/api/exports/alerts` to head office.

The passenger screen requests browser location only after **Use my GPS** or **Start navigation**. Manual origin selection works without GPS. It uses Leaflet and OpenStreetMap tiles, OSRM's road graph for route geometry and alternatives, and an explicit Nominatim place search. OSRM sees selected origin and destination coordinates; Nominatim sees submitted search text. No passenger identity or GPS history is stored by default. The map updates bus markers from actual published positions, marks stale positions, shows the selected 1/3/5/10 km camera-discovery radius, and refreshes route conditions during navigation. A passenger's route selection never changes an operational bus route.

OSRM's base duration uses its road profile and **is not a live traffic ETA**. A camera-local count score can influence an explicitly labeled route comparison only near the camera's configured coordinate; most road traffic remains unknown without more cameras or an authorized traffic provider. The earlier synthetic eight-route transit network and OR-Tools plan approval stay separate from real road navigation. The public OSRM demo server and OSM tile server are best-effort services; configure `OSRM_BASE_URL` with a suitable routing service for sustained deployment. No unsupported road names, restrictions, calibrated vehicle speeds or turn instructions are fabricated.

Uploaded images and recordings are **recorded evidence**, even when processing just finished. They do not automatically become live road traffic. The passenger route screen has an explicit **Use recorded demo traffic** option for demonstrations. Simulated bus GPS is labeled **SIMULATION**. Camera status distinguishes an active live stream, recorded observation, processing, stopped and offline states. The fleet **Stop** control cancels matching recording jobs and requests the active browser stream to stop; opening a webcam still needs browser permission.

Bus tracking offers a boarding-stop estimate at `/api/public/buses/{id}/arrival`. It requires fresh bus GPS, an active service session and an outbound/inbound direction declared by the driver. OSRM provides road geometry through the configured stop sequence and duration for each leg; GPS is projected onto that path to estimate remaining travel time. An inaccurate fix, a point away from the path, an inactive session, an already-passed stop or missing provider data returns an unavailable estimate with a reason. Estimates exclude stop dwell, waiting and live traffic; approximate demo stop coordinates are explicitly marked. The purple dashed service line is a road-profile estimate for the configured demo stop order, not an official bus diversion. A real service needs verified stop and route data, bus restrictions and calibrated progress/ETA validation.

Provider references: [OSRM route API](https://project-osrm.org/docs/v5.5.1/api/), [OSRM demo usage](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server), [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/), and [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/). Place search is explicit submit to avoid an autocomplete request stream to Nominatim.

## Demo flow

1. Start the server. Sign into the head-office dashboard with the configured local operator credentials. Open **Live fleet & GPS** and confirm `BUS005` and `BUS_CAM_001`.
2. Open `/passenger`. Choose an origin and destination on the map, or grant GPS permission and search a destination. **Find road routes** calls OSRM; click another route to select it. The 5 km ring and nearby registered camera pins show known coverage. This step requires internet for OSM tiles and OSRM routing.
3. In another terminal, publish explicitly synthetic GPS positions:

   ```powershell
   .\.venv\Scripts\python.exe scripts\simulate_bus_gps.py --steps 6 --interval 10
   ```

   `BUS005` appears on the public map with source `demo_simulation`. Search it by registration, route or stop and click its card to track it; choose a boarding stop for an arrival estimate. For real device GPS, sign into `/driver` using an assigned driver account, choose service direction, press **Share device GPS**, and allow browser geolocation. The page must remain active; a browser tab is not a supported background tracker. Stopping GPS sharing closes the active service session.
4. Open **CCTV intelligence**, choose `BUS_CAM_001`, and open the browser camera in human mode. Allow camera permission and point it at visible people. Live detections update `BUS005`'s visible-person count. A still/video upload can also update the bus crowding observation, but it cannot establish a live safety incident.
5. In **Safety alerts**, configure `BUS_CAM_001`'s doorway zone. In the driver page, report **Door open**. For a live safety demonstration, keep fresh simulated or actual moving GPS and let a visible person occupy the configured zone for at least three consecutive processed webcam frames. Inspect the resulting suspected event in head office and acknowledge or mark it false positive. The GPS simulation and manually reported door state are visibly labeled.
6. Run the existing **Passenger demand**, **Route optimization** and **Recommendations** workflow. Service changes still require head-office approval before *simulation* activation. Export incident records or scenario results.

An administrator can create accounts from **Users & access**, assign drivers to a bus, disable access and reset passwords. The equivalent API is `POST /api/accounts`, providing a username, password of at least 12 characters, role `driver`, and `bus_id: "BUS005"`. Passwords are stored as PBKDF2 hashes; account changes are audited. The local admin credential remains in `.env`; configure a strong value before network deployment. Head-office accounts use role `head_office`; only admin can register buses/cameras/accounts. Public endpoints live under `/api/public`; private APIs and raw outputs enforce authentication. GPS history is retained for seven days, saved optional navigation requests for one day and crowd observations for 30 days. The server's general upload/output TTL also applies.

Interior image/video input uses the active configured **human** model and filters actual person class IDs from its labels. Road input uses the active **general** model. Live camera associations enforce the corresponding mode. Select the laptop or USB input in the live screen's **Video input device** control. Two distinct registered live cameras can run in separate tabs within the existing two-session admission limit; one webcam plus a recorded road video is an alternative. Physical throughput depends on the CPU/GPU and camera. API aliases `/api/detection/image`, `/api/detection/video`, `/api/detection/jobs/{id}` and `/api/detection/results/{id}` reuse the same normalized pipeline.

Associated transit live cameras start with the Fast 320-pixel profile and pose analysis off to avoid an extra model pass. The original unassociated live camera keeps its skeleton default. Pose can still be enabled when needed; measured camera and inference FPS remain separate.

For a phone on the same Wi-Fi, run `Run-TransitOpt-Phone.bat start` and follow the [phone certificate instructions](CAMERA_ML_GUIDE.md). The local TLS gateway keeps one ML backend, requires strong authentication and preserves same-origin checks. A public deployment still needs an appropriately configured HTTPS host. Browser GPS and camera access require a secure context on non-localhost origins.

## Tests and exact limits

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm.cmd test
npm.cmd run build
```

The public route depends on OSRM availability. OSM tiles and Nominatim search also need internet. The laptop webcam cannot supply GPS or door state. RTSP/IP ingestion, physical traffic speed, calibrated queues, full-bus occupancy, background phone tracking, official Salem service changes and external alerts require additional devices, calibration, permissions or provider integrations. The frontend's map/browser GPS and webcam permissions need a real browser and hardware for final field validation.
