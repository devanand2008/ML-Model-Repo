# Moving bus speed and congestion

Open `/speed` from **Bus speed & congestion**. This module is designed for the user's camera mounted on a moving bus. It combines **YOLO vehicle counts from a forward road camera** with **the same bus's GPS speed**. It does not claim the bus's speed or other vehicles' absolute speeds can be recovered from an uncalibrated moving camera alone.

## Use the module

1. The starter assignment `BUS_ROAD_001` is a forward road camera for the illustrative bus `BUS005`. Register a real bus and a camera with role **Moving bus road** in Fleet for your own deployment. The separate `BUS_CAM_001` interior camera remains dedicated to people counting.
2. On the phone aboard that bus, open its **Camera + GPS** link, allow camera access and select the rear camera facing the road. Start detection.
3. Click **Share bus GPS speed** and allow location access. Sign in as admin for camera and GPS together on this page. Assigned drivers can instead publish GPS from their Driver dashboard while an operator supplies camera frames. A head-office viewer can inspect results and operate cameras but cannot publish device GPS. Use the trusted phone HTTPS address and keep this page active.
4. The speed dashboard refreshes every five seconds. Actual live results show GPS speed, source, vehicle count, sustained low-speed duration, possible queue and forecast quality. A laptop without suitable GPS shows unavailable speed rather than a fabricated estimate.
5. Following buses can open **Plan from this bus**, enter their destination and keep automatic route selection enabled. The planner starts from fresh shared bus GPS and monitors camera observations every five seconds. Its origin updates after at least 100 m of movement, at most every 30 seconds. Provider alternatives may be unavailable. This does not change official bus routes or stop sequences.

GPS publishing is opt-in and stops on leaving the camera page or clicking Stop. The device must remain aboard the assigned bus. Route-planning viewers use that bus's already-shared GPS; their own GPS permission is not requested. Nearby driver warnings do not claim a camera is ahead or on the same carriageway.

## Speed and congestion calculation

- Browser-reported speed is converted from metres per second to km/h by multiplying by 3.6. Some devices return no speed; see [MDN speed](https://developer.mozilla.org/en-US/docs/Web/API/GeolocationCoordinates/speed).
- When speed is missing, two accurate GPS fixes 5–30 seconds apart provide an average displacement estimate: `haversine distance / elapsed time × 3.6`. The UI displays an accuracy range using the sum of both horizontal accuracy radii. It is not instantaneous camera speed or a statistical confidence interval.
- GPS must be at most 20 seconds old with reported horizontal accuracy at most 30 m. Simulated GPS is excluded. Reported or estimated bus speed is separate from average surrounding-vehicle speed, which remains unavailable.
- A possible queue requires bus speed at most 10 km/h, at least three detected vehicles, eight seconds of consecutive live observations, and multiple GPS fixes. For displacement estimates, the upper accuracy bound must also be at most 10 km/h. Camera gaps over three seconds, session changes, missing GPS and location jumps over 50 m reset persistence.
- A qualifying queue sets a heuristic scene-pressure floor of 70/100. It is a warning: signals, bus stops, detection errors and parked vehicles can also explain slow movement. These thresholds have not been calibrated on field traffic.
- The alert uses GPS recorded with that camera observation, never a bus's later position. Moving-camera evidence expires after 20 seconds or when the stream stops. Recorded uploads cannot publish live speed or traffic alerts.

## Forecast changes

`scene-pressure-speed-v2` adds visible vehicle count, valid GPS speed, speed availability, queue state and recent changes to the existing Ridge features. It predicts the next minute of scene pressure; it does not forecast physical vehicle speeds or claim improved accuracy without validation.

The ten-minute minimum, chronological holdout, six-bin purge and requirement to beat persistence MAE by 5% remain. A moving camera's training window contains only its latest continuous observations within 100 m of the latest capture point; moving to another road or losing GPS starts collection again. While collecting, current qualified queue evidence still informs route ranking.

## API and validation

- `GET /api/traffic/speed`: authenticated operator dashboard; assigned drivers see their own cameras.
- `POST /api/cameras/register`: supports `role: "bus_road"` with a registered `bus_id`. Fixed latitude/longitude is rejected for this role.
- Existing bus GPS and camera WebSocket endpoints are reused. `bus_road` requires the general detector; `bus_interior` requires the human detector.
- Traffic observations expose `bus_speed_kmh`, `speed_observation`, and synchronized `capture_location` when available. Public feeds expose aggregate speed/count/queue evidence only.
- Software checks exercise quality rejection, displacement bounds, persistence, restart/gap reset, spatial forecast reset, role validation, public alerts, expiry and alternative-route ranking. Physical phone/GPS and road accuracy still need field validation with measured reference data.

Location access requires user permission and a secure context; see [MDN watchPosition](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/watchPosition). Existing local HTTPS instructions are in [CAMERA_ML_GUIDE.md](CAMERA_ML_GUIDE.md).

## Forecast robustness update

The scene learner now aggregates each ten-second bin with a median to reduce isolated detection spikes. Ridge regularization is selected from 1, 10 and 100 on an inner chronological split with a six-bin purge; the separate outer holdout still requires a 5% improvement over persistence. Controlled synthetic fixtures are evaluated by `scripts/evaluate_scene_forecast.py`; these are not field-accuracy measurements. Small route-comparison differences retain the selected path to reduce repeated switching. Meaningful high-pressure improvements can still recommend an alternative.
