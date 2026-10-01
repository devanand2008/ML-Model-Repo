# VisionX API

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
