# Render deployment for the full ML app

This repository includes `render.yaml` and `Dockerfile.render` for one public HTTPS service serving the React app, FastAPI, browser-camera WebSockets, stock YOLO26 detection/pose, XGBoost demand forecasts, OR-Tools and the local FLAN-T5 route assistant. The app starts a new cloud database; the laptop's private database, uploads, recordings and `.env` are not copied to GitHub or the image.

## Deploy

Open [Deploy to Render](https://dashboard.render.com/select-repo?type=blueprint&repo=https%3A%2F%2Fgithub.com%2Fdevanand2008%2FML-Model-Repo). Sign into Render, authorize the GitHub repository if prompted, and review the Blueprint.

The prepared configuration uses **2 CPU / 4 GB RAM** (`2c-4g`) in Singapore and a **5 GB persistent disk**. This is a proposed starting size, not a measured concurrency guarantee. Check Render's displayed compute/storage price before creating it. The full in-process PyTorch/RAG application is not sized for the free 512 MB plan. Hosting charges require your budget approval.

Set `ADMIN_PASSWORD` to a unique password of at least 12 characters when Render asks. Username is `admin`. Render generates `SECRET_KEY`; no secret belongs in `render.yaml` or GitHub. Keep this cloud password in your password manager. The password from the laptop does not automatically become the cloud password.

When the deploy completes, use the actual HTTPS URL shown in Render. Verify `/api/health`, open `/status`, sign in, then check an image detection, demand forecast, route assistant, and browser camera. A successful Docker build validates and installs the stock YOLO detection/pose checkpoints, pinned FLAN-T5 weights and forecast artifacts. Custom ship/container-condition weights remain an operator-supplied option and are explicitly unavailable until installed.

## How storage and model setup work

The Docker build installs CPU PyTorch wheels, builds the React frontend and prepares model assets under `/app/cloud-seed`. It evaluates the reproducible **synthetic** demand model during the build. First startup copies missing assets into `/app/storage`; subsequent starts preserve existing data, uploaded weights and forecasts. `scripts/start_cloud.py` sets database, weights, uploads, outputs, reports and forecast paths under this disk. It respects explicit path overrides, fixes new disk ownership, drops root privileges and starts one Uvicorn worker on Render's `PORT`.

The disk is available only at runtime. The app requires one service instance because SQLite, camera histories, route contexts and ML caches are local to this process. Disk-based redeployments briefly interrupt service. Outputs/uploads retain the app's existing one-hour cleanup; history has its existing retention. Save recordings/downloads that you need to keep separately and monitor disk usage.

## Cameras, GPS and performance

Laptop and phone cameras run through the user's browser over the public HTTPS site after explicit camera permission. The Render server does not directly open a laptop's USB webcam. Keep the camera tab open to send frames. Moving-bus speed uses qualified browser GPS; the stock camera model cannot measure bus speed in km/h by itself. A private LAN RTSP address is not reachable from Render unless the operator supplies a network-accessible feed or secure gateway.

The Blueprint caps accepted live frames at 15 FPS. Actual inference throughput depends on CPU, frame size, network latency and simultaneous users; it is not a promised 15 FPS. Start with one camera and check `/status`. Scene-pressure training still requires sufficient fresh camera history and its validation threshold. It becomes unavailable when evidence expires. Route ranking depends on camera coverage; unobserved roads are unknown. OSRM profile minutes are not measured traffic travel times.

The route assistant runs the local pinned FLAN-T5 model. It explains retrieved route evidence and operator review constraints; it does not activate bus diversions. Field deployment still requires validated camera locations, real bus assignments and operator-reviewed service data.

## Local checks

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_cloud_startup.py -q
docker build -f Dockerfile.render -t transitopt-render .
```

To test the image, provide `ADMIN_PASSWORD` and `SECRET_KEY` through environment variables and mount a named Docker volume at `/app/storage`. Keep the container private while testing. The same source's original `Dockerfile` and BAT launchers remain available for the existing local app.

Official references: [Blueprint specification](https://render.com/docs/blueprint-spec), [Docker deployment](https://render.com/docs/docker), [persistent disks](https://render.com/docs/disks), [pricing](https://render.com/pricing), [Render CLI sign-in](https://render.com/docs/cli).
