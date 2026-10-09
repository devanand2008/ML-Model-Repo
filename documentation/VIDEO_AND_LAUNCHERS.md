# Full-app launchers and captioned recordings

Keep these BAT files in the `visionx-ai` project folder; they use its relative `scripts`, `.venv` and `frontend` folders.

| File | Action |
|---|---|
| `Start-Free-Hosting.bat` | Starts full laptop ML and its secure connection to the free Render website. Keep the laptop and launcher running. See [free hosting](FREE_HOSTING.md). |
| `Start-TransitOpt-All.bat` | Checks Python and Node, installs missing project dependencies, builds the frontend, starts the existing shared server, and opens the full web app. |
| `Run-On-Web.bat` | Alias for the complete web-app launcher. |
| `Record-Full-Demo.bat` | Starts the app and opens `/record-demo`. |
| `Convert-Recording-To-MP4.bat` | Drag a browser WebM recording onto it to create a new H.264 MP4 next to the original. |
| `Run-TransitOpt-Phone.bat start` | Optional local HTTPS phone gateway. Follow the certificate guide. |
| `Run-TransitOpt.bat stop` | Stops the owned laptop app server. |
| `Setup-Route-RAG.bat` | Installs the pinned local FLAN-T5 language model used by the route explanation assistant. |

The app's one server provides passenger navigation, driver workflow, admin, road and person YOLO inference, camera observations, live traffic learning, bus crowding, XGBoost demand, OR-Tools optimization, scenarios, review, analytics, model management and the original VisionX tools. Model weights load when used; cameras and GPS start only through their device-permission controls. Real signal-camera URLs, calibration and missing optional model weights are not supplied by a launcher.

## Video delivered now

`deliverables/TransitOpt-Demo/TransitOpt-ML-Demo-AI-Voice.mp4` adds an AI-generated English (India) voiceover, aligned to all 12 chapters of the 140-second walkthrough. Visible captions and the selectable English subtitle track are retained. The narration uses the caption text and the Neerja neural voice, without background music. The standalone narration is `TransitOpt-ML-Demo-AI-Narration.wav`.

The original silent version, `TransitOpt-ML-Working-Demo-With-Subtitles.mp4`, remains available. Both are 1280×720 evidence walkthroughs generated from real model and API results. The matching SRT is `TransitOpt-ML-Demo-Captions.srt`.

To reproduce the narration, install the optional export dependency with `.venv\Scripts\python.exe -m pip install edge-tts==7.2.8`, then run `.venv\Scripts\python.exe scripts\add_demo_voiceover.py`. The script sends only the public caption text to the [online speech service through edge-tts](https://github.com/rany2/edge-tts), caches chapter audio, preserves existing final output, and records timing in `narration-manifest.json`. This export dependency is separate from the app's ML runtime.

This video is **not a screen recording of the application**. It shows actual YOLO annotated image/video output and actual API results, with explanation cards for live workflows that require device interaction. The sample street image tests both the general and person-only pipelines; it is not bus interior footage. The sample video repeats the bundled image. Fleet demand and optimizer data are synthetic and explicitly labeled. No new GPS simulation, plan approval, or activation was performed to create this video. Normal analysis, forecast, draft optimization and scenario records were created.

The environment exposed neither a connected browser nor a working native capture connection, so automatic recording of the actual app was unavailable. `actual-results.json` preserves the source results, and `chapters.json` lists the exact timeline. The export contains no administrator password or authorization headers.

## Record the actual full application

1. Double-click `Record-Full-Demo.bat` and sign in with the credentials in `.env`.
2. Click **Record guided tour** and select the **TransitOpt browser tab** in the browser's chooser. Selecting another window will record that chosen content instead. Screen sharing requires a user gesture and a browser selection; the app cannot silently choose it. See [MDN getDisplayMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia).
3. The guided tour navigates through actual app modules and runs the recorded sample detections. Captions stay visible. Use **Pause tour** on the live camera page, allow camera access, and click Start Detection to demonstrate your real device. Resume when ready.
4. Pause on the passenger map to select origin and destination and request real routes. GPS and camera permissions are separate user actions. A traffic-triggered alternative needs active, properly located traffic cameras and an available provider alternative; do not treat recorded examples as live traffic.
5. The tour visits fleet, network, demand, optimization, scenarios, recommendations, safety, analytics, models, history, account management, settings and phone setup. You can interact while paused; recording continues. Avoid displaying passwords or unrelated personal windows.
6. Click **Stop & save**, or let the tour finish. Download the screen recording and its SRT captions before closing or refreshing the tab. The default recording format is WebM, or MP4 if that is the browser's supported format. Recording is local to the browser, with no audio or upload.
7. For MP4, drag the downloaded WebM onto `Convert-Recording-To-MP4.bat`. The output ends in `-converted.mp4`; the original remains unchanged. On-screen captions are already part of the recorded pixels.

Use a desktop browser on `http://127.0.0.1:8000` or a trusted HTTPS origin. The software tests cover capture consent, cancellation, captions, navigation, stop and resource cleanup. A real browser recording still requires the screen chooser and device validation.
