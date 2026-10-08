# Recorded validation — 8 October 2026

## Camera ML / shared app 2.1 validation

- Complete backend run: **64 passed** in 246.08 seconds, including the four new forecast/routing tests. After adding phone and public ML API checks, the targeted mobility/gateway suite passed **13 tests** in 41.16 seconds. Across these runs, **69 unique backend tests passed**. Existing deprecation warnings remain.
- Complete frontend run: **25 passed across eight files**. The new passenger check introduces traffic after initial route selection, exercises the five-second monitor and verifies that the passenger can select the newly recommended alternative. Following the final GPS-reset/layout changes, the six affected mobility/navigation checks passed again. TypeScript and the production build passed.
- Strict HTTPS verification with the generated local CA passed against `https://172.16.29.65:8443`. No certificate verification was disabled. Public feed and all six entry pages returned 200. ML overview returned 401 without credentials and 200 with the configured operator identity. A same-origin JSON request through the gateway returned 200 and retained its selected route.
- Actual OSRM integration through the HTTPS gateway returned one provider road route with 63 geometry points, 2.71 km distance and a 3.7-minute profile duration for the illustrative Salem coordinate request. No alternate was invented when the provider returned one route.
- Actual encrypted WebSocket inference processed the bundled Ultralytics still: general mode detected one bus and three people at Fast 320 px; human mode detected three people. Both reported `yolo26n.pt`. Live configuration acknowledgment passed. These were **unassociated sample frames**, not physical live camera observations, and did not publish a false live traffic feed. The cold general call took 1394.3 ms and the warm human call 80.5 ms; these samples do not establish camera FPS.
- Forecast checks verify minimum consecutive history, gaps, chronological holdout purge, baseline rejection, rising-pressure prediction and route re-ranking while preserving selection. Phone checks verify certificate identity/CA reuse, weak-password replacement, HTTP auth/origin preservation, binary WebSocket forwarding and foreign-origin rejection. Changing live inference settings starts a new history session so differently configured counts are not mixed.
- The local app and phone gateway are running. Strict TLS setup initially caught missing certificate identifiers; regenerated certificates include subject/authority identifiers and pass verification. Phone trust installation is manual and no OS trust/firewall settings were changed.
- Smoke metadata is saved in `data/demo_exports/camera-ml-smoke.json`. The supported UI tool reported no available apps or browsers, so the new screens could not receive a visual browser review in this session. Physical laptop/phone capture, phone certificate installation, Wi-Fi reachability and sustained hardware FPS still require device validation.

## TransitOpt AI 2.0 validation

- Complete backend suite: **60 passed** in 121.19 seconds. The eight mobility tests cover public/private access, GPS freshness and 5 km discovery, assigned driver roles, account disabling, actual human-model integration, consecutive-frame tracking, a WebSocket safety event, stale door rejection, incident review/audit, provider-leg arrival estimates, repeated critical crowd observations and explicit recorded-traffic demo selection.
- Complete frontend suite: **24 passed across eight files** in 8.00 seconds. Mobility tests cover consent-based GPS, route API use, personal route selection, driver door reporting, bus tracking/boarding-stop estimates and account creation/access changes. TypeScript and the production Vite build passed. The live overlay checks also passed after setting associated transit cameras to boxes-only inference by default.
- On the restarted live application, existing `yolo26n.pt` human inference processed the bundled `bus.jpg` with `BUS_CAM_001`: HTTP 200, four visible people persisted on `BUS005` (route R02). The road association `CAM02` used the general model and returned one bus and four people. Public summaries labeled the uploads as recorded evidence, with partial coverage and no verified load factor. No safety incident was generated from the still image.
- Interior video: an actual 15-frame inference job completed with person-only model classes, three people in the final frame, H.264 output and an authenticated 86,453-byte download. The source is a repeated bundled still image, clearly labeled as recorded demo footage.
- A live call to the OSRM demo server from two Salem coordinates returned HTTP 200 and one drivable route with 37 real geometry points, 1.66 km distance and a 2.4-minute road-profile duration. This verifies the provider integration for that request; route availability and traffic conditions vary.
- The explicit GPS simulator published `BUS005`'s outbound demo session. The live arrival endpoint used OSRM road geometry through its configured stops and returned a **2.4-minute DEMO road-profile estimate to New Bus Stand**. This excludes dwell, waiting and live traffic.
- `/`, `/passenger`, `/driver`, `/fleet`, `/safety` and `/accounts` returned HTTP 200 on the restarted server. Unauthenticated requests to alerts, accounts and raw outputs returned **401**. Real local smoke records are saved in `data/demo_exports/mobility-smoke.json` and `interior-video-smoke.json`.
- Retention shutdown now finishes an in-flight database transaction and disposes the connection pool before its event loop exits. The complete suite completed normally after this fix.
- Frontend map code is split into its own chunks; the main bundle is 903.67 KB (260.26 KB gzip). The still-large original main bundle is a performance limitation, while map code loads only when needed.
- Earlier headless Chrome checks rendered the actual OSM passenger map at desktop and a narrow width. Automatic approval review blocked the last Chrome screenshot launch with a generic policy reason; the supported browser provider was unavailable, so the final screenshot was not refreshed.
- Browser hardware permissions, a physical USB second camera and sustained dual-camera FPS could not be measured by automated tests in this environment. An authorized real-browser/device trial is still needed for those acceptance items.

The sections below record the earlier TransitOpt 1.0 baseline and its saved scenario results. Their test counts and bundle sizes are historical values.

Validation used the existing Python 3.13.5 environment, installed OR-Tools
9.15.6755, existing YOLO detector weights and the connected local API at port 8000.

## Automated and configuration checks

- Backend: the final complete `pytest backend/tests -q` run passed **52 tests**
  in 150.98 seconds, covering existing VisionX behavior, forecasting, optimization,
  connected transit APIs, configured fresh-install models and safe public assets.
- Optimizer: **13 tests passed**, including actual CP-SAT fleet/reserve/headway,
  graph continuity, explicit reverse-road permission, essential stops, shortfalls,
  scenario multipliers and whole-plan validation.
- Operations UI: **8 tests passed** in `operations.test.tsx`, including API KPI
  navigation, +20% inputs, infeasibility without invented allocations, approval,
  rejection, unchanged-plan explicit approval, saved scenario values and delayed
  alternative-map rendering.
- Analytics/settings/project: **4 tests passed**, including actual persistence
  payloads, validation errors, collection-specific exports and API-driven KPIs.
- Final complete frontend suite: **20 tests across six files passed** at
  19:11 IST, including the unchanged-plan UI regression. TypeScript and Vite's
  production build passed (914.9 KB main bundle, 264.3 KB gzip).
- Launcher `-CheckOnly`, demo-script compilation/help, and
  `docker compose config --quiet` passed. A complete Docker image build and hosted
  deployment were not performed as part of this local verification.
- The final local server restart passed health/readiness checks; the TransitOpt
  SVG is served as `image/svg+xml`, dashboard assets return HTTP 200, and the
  stored demo plan still has six pending recommendations with approval and
  activation false. Existing Model Center selections remain intact.

## Actual connected demonstration

Command, run against the restarted application:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py
```

The script analyzed both bundled samples, stored traffic/crowd observations,
forecast R02 boardings, ran the genuine optimizer, ran a second +20% demand
scenario and exported CSV/JSON. It completed successfully. Its default left all
changed-route recommendations for operator review; it did not approve or activate
the operating plan.

| Recorded result | Value |
|---|---|
| Genuine sample-image detections | 1 bus, 4 people |
| Stationary sample-video job | 15 processed frames; final frame 1 bus, 3 people |
| R02 60-minute forecast | 291.65 boardings |
| R02 current modeled capacity | 195 boardings |
| R02 forecast capacity shortfall | 96.65 boardings |
| Actual optimizer status | OPTIMAL |
| Allocated / reserved fleet | 24 / 4 buses, from 28 total |
| Scenario forecast demand | 1,697 boardings |
| Baseline → optimized unserved demand | 433 → 393 boardings |
| Baseline → optimized average waiting | 8.7554 → 8.4851 minutes |
| Baseline → optimized average modeled delay | 4.6863 → 2.8671 minutes |
| Operating cost | INR 16,800 for the 60-minute horizon |
| +20% scenario demand | 2,034 boardings |
| +20% scenario remaining shortfall | 704 boardings |

The image/video outputs are actual model detections. The short sample clip repeats
a bundled still photograph and demonstrates a genuine video job; it is not a live
traffic recording. Forecasts use synthetic ridership. Waiting, delay, capacity and
cost are computed planning estimates. Counts of detected people do not represent
ticketed passenger boardings. Demand is conservatively rounded up per route after
scenario multiplication, so rounded route totals need not increase by precisely
20.000%.

Local stored optimization run: `ebfc9c741baf4185b0620ae1295dc99f`.
It generated six pending-review recommendations, including R02 2 → 3 buses,
R04 4 → 3 buses and several graph-validated variant changes.
The second scenario ID is `eefc3d06615444059398c5345307f700`.

Generated artifacts:

- `data/demo_exports/demo-summary.json` — 461,076 bytes.
- `data/demo_exports/scenario-eefc3d06615444059398c5345307f700.csv` — 7,814 bytes.
- `data/demo_exports/scenario-eefc3d06615444059398c5345307f700.json` — 225,404 bytes.

These identifiers and values record this run. Subsequent camera observations,
operator decisions or changed scenarios can legitimately produce different results.

## Captioned video and launchers — 2026-10-09

- `npm.cmd test`: 28 tests passed across nine files, including screen-capture consent/cancellation, recording across routes, subtitle timing and stream cleanup. The ten-screen navigation integration test has a 30-second budget; the first lazy home-page load allows five seconds. Expectations remain unchanged.
- `cmd.exe /c Start-TransitOpt-All.bat -NoBrowser`: successful TypeScript/Vite production build and reuse of the healthy shared server. The browser-opening branch requires an available desktop browser.
- `/api/health`, `/record-demo`, `/record-result/road` and the current production JS/CSS assets returned HTTP 200.
- `Convert-Recording-To-MP4.bat` converted the actual annotated sample to a separate H.264 MP4 successfully.
- The delivered evidence video decoded all 3,360 frames: 1280×720, 24 FPS, 140 seconds, 2,703,570 bytes. Its embedded English subtitle stream decoded successfully. Actual generated frames were visually inspected for annotations and caption readability.
- The video contains real image/video inference and API results, with synthetic planning and recorded samples labeled. It is not an application screen recording. Native capture and browser attachment were unavailable in this environment; the guided browser recorder still needs real screen-sharing and webcam permission validation on the user's device.

See [video and launcher instructions](VIDEO_AND_LAUNCHERS.md).

## Practical limits

Road geometry and transit operations are illustrative rather than official Salem
routes or verified GPS. Physical speed, calibrated queue length, arbitrary future
forecast origins, calibrated uncertainty and authorized RTSP ingest remain
unavailable. CPU/camera hardware governs actual inference FPS. Complete approval
and activation are covered by API/UI tests; the default live CLI run intentionally
left its recommendations pending for operator review. CSV/JSON exports are
implemented; optional PDF reports are not implemented.

## Moving bus speed module - 2026-10-09

- Frontend: 34 tests passed across ten suites, including opt-in GPS, conversion to km/h, capture cleanup, authorization failure and planning from a following bus GPS location.
- Backend: 15 speed/route/forecast unit tests passed. Ten mobility integration tests passed, followed by two targeted moving-bus tests including the new WebSocket contract (11 distinct mobility tests). These exercise GPS quality and uncertainty, repeated-frame/fix persistence, gap reset, spatial history reset, queue publication, location binding, expiry, and recommendation of a road alternative.
- TypeScript/Vite production build passed. The new lazy-loaded page is `/speed`; the starter forward-camera assignment is `BUS_ROAD_001` for illustrative `BUS005`.
- Tests use controlled fixtures for traffic/GPS. They verify software behavior, not field speed accuracy or an improvement in ML accuracy. Moving-bus km/h comes from GPS, not monocular camera motion. Real phone permission, camera mounting and reference-speed validation remain device/field checks.

See [BUS_SPEED_GUIDE.md](BUS_SPEED_GUIDE.md) for exact rules and setup.

Final server check: `/api/health`, `/api/traffic/speed`, `/speed`, and the built speed-page asset returned HTTP 200. Starter `BUS_ROAD_001` is assigned to `BUS005`. The actual general YOLO sample produced one bus and four people; the recorded sample was excluded from the live traffic feed. The trusted phone gateway at `https://172.16.29.65:8443` returned healthy status. Assigned-driver camera/speed access checks passed after the final role fix. No physical GPS/camera test or measured accuracy claim was made.

## Local route RAG and two-click map - 2026-10-09

- Frontend: all 39 tests passed across 11 suites. New checks cover selecting two map points, two blue provider paths, thicker selection, reset/cancellation, explicit RAG route selection, expiry, private bus review, and ignoring old-context answers.
- Backend: 15 mobility/RAG tests passed in one run; 18 retrieval/context/speed/route tests passed in another (three retrieval tests overlap). Checks cover live-evidence refresh, server-owned provider paths, tamper resistance, context bounds/expiry, bus role access and exclusion of stale/recorded traffic.
- Pinned FLAN-T5-small safetensors weights downloaded successfully. A real local neural inference selected the GPS-speed rule, exactly matching its retrieved source, in about 2.3 seconds after loading. No cloud API key was used. This is evidence-constrained generation, not a new fine-tune or an accuracy claim.
- Production TypeScript/Vite build passed. The map requests up to three provider alternatives, de-duplicates geometry IDs and labels a one-path response. UI automation remains unavailable; map interaction/presentation was checked through component tests, not a new physical browser screenshot.

See [ROUTE_RAG_GUIDE.md](ROUTE_RAG_GUIDE.md) for model, citation, permission and startup details.

Final RAG validation: all 40 frontend tests passed. Four retrieval/context/question-focus tests and the RAG API integration check passed after the final question-focus correction. The running OSRM API returned two distinct Salem road paths for `11.6649,78.1460` to `11.6940,78.1630`. Actual local neural passenger and BUS005 answers matched their exact retrieved sources, with generation taking about 1.2 and 1.46 seconds respectively after loading. The served map/RAG assets and phone model-status endpoint passed. Results are recorded in `data/demo_exports/route-rag-validation.json`; no bus operating plan was changed.

## Full-app audit and usability improvements - 2026-10-09

- Final complete backend suite: **89 passed** (`.venv\Scripts\python.exe -m pytest backend/tests -q`). Deprecation warnings remain in upstream FastAPI/httpx compatibility and existing naive-UTC defaults; they did not fail tests.
- Final complete frontend suite: **44 passed** across 12 suites (`npm.cmd test`). It now covers module recovery, readiness with partial endpoint failures, module search, three camera roles, existing navigation, camera overlays, recorder, road alternatives, speed/GPS, role actions and RAG.
- Production TypeScript/Vite build passed through the full-app BAT launcher. The existing large-bundle advisory remains.
- `scripts/verify_full_app.py` passed 24 API/workflow checks and served 31 page entry points. Actual YOLO vehicle/person and video inference, 30/60/120-minute XGBoost predictions, OPTIMAL fleet allocation, scenario CSV/JSON exports, two provider road paths, local neural RAG and trusted phone HTTPS were exercised. Draft analysis, forecast, optimization and scenario records were created; no plan was approved or activated. Details: `data/demo_exports/full-app-verification.json`. Served HTML entry points are not a substitute for physical browser interaction.
- The traffic learner uses median ten-second bins, numeric speed/count validation, and regularization selection on an inner chronological split with a six-bin purge. The independent outer holdout still requires a 5% improvement over persistence before enabling a forecast.
- Routing suppresses insignificant changes: less than 0.1 pressure advantage (unless equal-pressure profile time saves one minute), less than 0.1 km for shortest distance, and less than max(1 minute, 5%) for fastest comparisons. Meaningful relief from a high-pressure camera can still trigger an alternative. Explicit recorded-demo comparisons remain labeled.
- `scripts/evaluate_scene_forecast.py` compares the previous mean-bin/Ridge-10 learner with the update on three labeled synthetic fixtures. Absolute one-minute forecast errors: clean rising 0.759 to 0.05; rising with isolated spikes 12.077 to 0.05; steady with spikes 23.333 to 0.0, with persistence preferred for the steady case. These illustrate controlled robustness, not general superiority or field accuracy. Artifact: `data/demo_exports/scene-forecast-robustness.json`.
- Usability: home-page next-step links, searchable modules, a readiness screen at `/status`, separate fixed-road/moving-bus/interior controls, and recoverable module rendering errors.
- Browser inventory returned no connected browser. Physical phone camera/GPS permissions, actual road accuracy and visual layout still require device verification. Specialized container/condition checkpoints and authorized RTSP ingestion remain unavailable; the app labels unsupported features. No new YOLO fine-tune or field accuracy claim was made.
