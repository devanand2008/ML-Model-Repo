# TransitOpt / VisionX API

## Camera ML and passenger intelligence (2.1)

`GET /api/ml/overview` requires an admin or head-office identity. It returns the active general/human detection model metadata, registered cameras, source/runtime state and live road forecast readiness. `PUT /api/traffic/cameras/{camera_id}/location` requires an admin and accepts `{ "latitude": 11.67, "longitude": 78.14 }`; it updates a road camera's operator-configured location and creates an audit entry.

`GET /api/public/traffic/feed` is an aggregate public feed. It returns active road camera observations, one-minute scene-pressure forecasts when validated, and high-pressure in-app alerts. Offline cameras and recorded uploads do not publish live alerts. No footage, raw bounding boxes or private bus incident evidence are included.

`POST /api/public/navigation/routes` accepts geographic `origin`, `destination`, `goal` (`fastest`, `lowest_observed_traffic`, `shortest`), optional `selected_route_id`, `save` and `use_recorded_demo`. OSRM provides road paths and actual available alternatives. Geometry-derived route IDs retain path identity independently of provider order. The `fastest` goal ranks profile duration plus camera scene-pressure preference weights. `lowest_observed_traffic` ranks summed usable camera pressure first, then profile time; `shortest` ranks distance. Unknown coverage does not mean a clear road. Routes expose `observed_pressure_total` and `high_pressure_camera_count`; comparison minutes are **not calibrated live ETAs**.

`POST /api/public/navigation/monitor` re-evaluates provider paths without another OSRM request. Send up to four `routes` containing `id`, `geometry` as longitude/latitude pairs, `distance_km`, and `base_duration_minutes`, together with `selected_route_id`, `goal`, and optional `use_recorded_demo`. The response contains annotated routes, `route_alerts`, `recommended_route_id`, unchanged valid `selected_route_id`, `alternative_available`, forecast provenance and the comparison method. The client polls every five seconds while a route is selected and, with automatic routing enabled by default, adopts the recommended route. Choosing a route manually disables automatic switching. The endpoint itself retains the supplied valid selection for clients that prefer manual control. Coordinates are validated; these client-supplied comparisons do not authorize official service changes.

The Ridge scene-pressure forecast uses ten-second bins from one continuous live road camera session, with ten minutes of minimum history, a one-minute horizon, chronological holdout and a six-bin target purge. It is enabled only when holdout MAE improves the persistence baseline by at least 5%. Insufficient/flat/offline history returns explicit unavailable status. Recorded data and bus interior counts never train this road forecast. Model output estimates visible vehicle pressure, not physical road speed.

Laptop or phone `POST /api/analyze/live/ticket` remains authenticated. Binary JPEG frames use `/api/analyze/live` WebSocket with a one-time ticket and registered `camera_id`. Interior cameras require `mode=human`; road cameras require `mode=general`. `Run-TransitOpt-Phone.bat` starts an HTTPS gateway on private Wi-Fi port 8443 that relays HTTP and WebSockets to the same loopback backend. Authentication and origin validation remain in place; public CA trust on the phone is manual. See [camera setup](documentation/CAMERA_ML_GUIDE.md).

## Existing analysis API

Interactive OpenAPI is served at `/api/docs`, with the schema at `/openapi.json`.
Authentication is HTTP Basic when `AUTH_ENABLED=true`; all model, history, output and analysis routes are protected. `/api/health` is public. Errors return HTTP status plus `detail` (validation) or `error` (processing).

## Image and webcam requests

`POST /api/analyze/{image,human,ship,container,combined,webcam}` accepts multipart `file` and `confidence` (0.10–0.95, default 0.50).

- `image`: optional `brightness`, `contrast`, `sharpness` (0.1–3), `resize_width` (0–4096; zero preserves size), `grayscale`, `denoise`.
- `human` and `webcam`: optional `pose_mode`. Webcam accepts a JPEG/PNG frame captured by the browser and runs human analysis. For general/combined frames use the corresponding image endpoint.
- `container`: optional `condition_mode`; requires separate installed classifier.

```bash
curl -F 'file=@photo.jpg' -F 'confidence=0.5' http://localhost:8000/api/analyze/image
```

Results contain `success`, `analysis_id`, `processing_time` in seconds, `image_width`, `image_height`, `detections`, `counts`, `model_info`, `processed_image`, `annotated_image` and optional `warnings`, `keypoints`, `condition`. Images are base64 JPEG data URLs. Bounding boxes are **[x, y, width, height] in processed-image pixels**, not corner pairs. Detection IDs in image results are per-image indexes. Confidence is [0,1]. Condition fields are null when unsupported, not zero-quality estimates.

## Video

`POST /api/analyze/video` accepts MP4/AVI/MOV/MKV with `file`, `analyzer_type` (`general`, `human`, `ship`, `container`), `confidence`, `track`, and `background` (default false).

With `background=true`, returns `{success:true,job_id:...}` immediately after upload. Poll `GET /api/analyze/video/jobs/{job_id}` for status (`queued`, `processing`, `complete`, `failed`), `frame`, `total`, `progress`. On completion `result` contains the summary and `download_url`; failure includes `error`. Polling does not consume inference quota. Job IDs are random and expire from the in-memory registry. Synchronous callers receive the completed result directly.

Video summary: frame count, source FPS, inference FPS, dimensions, processing time, per-frame `timeline`, frame-aggregated `class_counts`, last-frame `detections`/`counts`, `unique_track_ids`, `unique_count`, movement distances in pixels and annotated MP4 download URL. Output has no audio. Download through `GET /api/outputs/{filename}` before expiry. Use an authenticated request when auth is enabled.

## Models

- `GET /api/models`: available records and active/default state.
- `GET /api/models/{id}`: detail including class names, metrics and dataset metadata.
- `POST /api/models/upload`: trusted checkpoint `file`, `name`, `model_type`, optional `description`, `version`, `confidence_threshold`, `class_names` (JSON array), `dataset_info`/`metrics` (JSON objects). Installs and selects the model for its type.
- `PATCH /api/models/{id}`: multipart `name`, `is_active`, `is_default`, `confidence_threshold`, `description`. Selecting a default clears other defaults of that type.
- `DELETE /api/models/{id}`: rejects deleting the currently selected default.

Supported model types: `general`, `human`, `ship`, `container`, `condition`. Model upload does not run evaluation or invent metrics. Upload only checkpoints from trusted sources.

## History and sessions

- `GET /api/history?limit=50&offset=0&analyzer_type=human`: metadata, latest first; limit 1–200.
- `GET /api/history/{id}`: stored numerical results.
- `DELETE /api/history/{id}`: deletes metadata/detections.
- `GET /api/session`: current configured operator; 401 requires sign-in.
- `GET /api/health`: liveness, version, environment; does not assert that weights are loaded.

Relevant errors: 400 invalid/corrupt media or metadata, 401 unauthenticated, 404 missing resource, 413 upload limit, 422 invalid parameters, 429 inference quota/queue full, 503 unavailable weights, 504 response timeout, 500 model/runtime failure. No server tracebacks or local file contents are sent in generic errors.

## Continuous live video

`POST /api/analyze/live/ticket` uses the same HTTP authentication as other inference routes and returns `{ticket:...}`. Tickets are single-use and expire after 30 seconds. Do not put user passwords in the WebSocket URL.

Connect to `ws://localhost:8000/api/analyze/live?mode=human&confidence=0.5&track=true&ticket=...` (`wss://` with HTTPS). Modes: `general`, `human`, `ship`, `container`, `port_monitor`. Container mode requires compatible container weights. Models come from active Model Center defaults and are resolved when the session opens.

Wait for `{type:"ready"}` before sending frames. Send `{type:"frame",frame:"data:image/jpeg;base64,..."}`. Wait for its detection response before sending the next frame. Capture width 640 is recommended; encoded images must be under 2 MB. Response includes `annotated_frame`, `detections`, `counts`, `total_objects`, `unique_count`, `fps` (inference throughput), `inference_time` (milliseconds), dimensions, model paths, `tracking`, `warnings` and optional `port_summary`. Boxes use `[x,y,width,height]`. In port summaries an unavailable container count is `null`.

Send `{type:"config",mode:"ship",confidence:0.6,track:true}` to change configuration. A `config_ack` confirms success. Mode/tracking changes reset tracking IDs. `{type:"ping"}` receives `pong`. Errors contain `error` and `recoverable`; fatal errors close the session. Admission is limited to two connections and inference is capped at 15 frames/second per connection. The browser uses the same-origin WebSocket path; Vite's API proxy includes WebSocket forwarding.

## Moving-bus speed and congestion

Route RAG endpoints: `GET /api/public/rag/status`, `POST /api/public/rag/ask` with `question` and optional `route_context_id`, and authenticated `POST /api/rag/bus-advice` with those fields plus `bus_id`. The navigation response supplies a bounded, expiring provider context; the assistant re-ranks its original paths with current public camera evidence. Generation is constrained to retrieved paragraphs and returns sources, snapshot/expiry timestamps and separate structured route advice. No bus plan actions are available. See [ROUTE_RAG_GUIDE.md](documentation/ROUTE_RAG_GUIDE.md).

`GET /api/traffic/speed` returns authenticated per-camera GPS-speed validity, live vehicle counts, queue status and forecast readiness. `POST /api/cameras/register` accepts `bus_road` with `bus_id`; fixed coordinates are rejected. General live detection combines synchronized real GPS with forward-road counts. Speed/queue/capture-location evidence flows into public traffic alerts and route monitoring; uploads and simulated GPS are excluded. The v2 Ridge model adds counts and GPS-speed inputs while retaining its holdout quality gate and a 100-m continuous history window for moving cameras. See [BUS_SPEED_GUIDE.md](documentation/BUS_SPEED_GUIDE.md) for exact freshness and persistence thresholds.
