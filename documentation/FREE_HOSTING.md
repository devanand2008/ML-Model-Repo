# Free Render website with full laptop ML

The default `render.yaml` uses Render's **free** plan and `Dockerfile.gateway`. Only the React website and a small streaming gateway run there. YOLO, local route RAG, XGBoost, traffic learning, optimization, camera analysis and the database run on the existing laptop server. There is no paid disk or paid compute in this setup.

Live website: **https://transitopt-free.onrender.com**. Render dashboard: https://dashboard.render.com/web/srv-db4499jbc2fs73aifsd0.

Verified October 9, 2026: the service is on the `free` plan; its Linux gateway passed a 0.1 CPU / 512 MB check using about 41 MB. Ten gateway/phone regression tests and the frontend build passed. The actual public URL passed admin authentication, YOLO image inference, general and person-only camera WebSocket inference, a 30-minute XGBoost forecast, an `OPTIMAL` draft optimizer result and local neural route RAG generation. OSRM returned a valid road route and its monitoring request passed; this selected test pair returned one alternative, so multiple alternatives depend on the provider and endpoints. Camera tests used a recorded stock validation image. Physical webcam, phone-camera and GPS permissions were not exercised automatically. No plan was approved or activated.

## Run or reconnect

1. On the configured laptop, double-click **Start-Free-Hosting.bat**. Leave that window open and keep the laptop awake and connected to the internet.
2. Open the Render website printed by the launcher. **The hosted admin dashboard is public and has no ID/password sign-in. Anyone with the link can use admin controls.** The laptop app retains its existing sign-in. Browser camera and GPS still require your permission.
3. If the laptop restarted, the launcher creates a new Cloudflare address and securely updates the running Render gateway. Tunnel address changes no longer rebuild or redeploy the website. The banner reconnects automatically after the new tunnel is ready. Normal handoffs use the private bridge token; the Render CLI login is only needed for initial configuration and saving a fallback address for future service restarts.
4. Run `Start-Free-Hosting.bat status` to check the laptop bridge, Cloudflare edge and deployed ML connection. Run `Start-Free-Hosting.bat stop` to close the public tunnel. The local ML app stays available.

The launcher now selects Cloudflare's transport automatically rather than forcing HTTP/2. It waits for an actual edge connection before updating Render, recreates a tunnel after two minutes without an edge connection, retries startup failures, and checks the local ML server every minute. Connection diagnostics listen only on `127.0.0.1:8789`. The hosted banner retries failed checks every ten seconds, checks again when you return to the tab, and offers **Retry connection**; a page refresh is no longer needed to update the banner.

The laptop sends an authenticated `PUT /gateway/connection` once a minute. The gateway accepts only HTTPS Cloudflare Quick Tunnel addresses, checks the replacement's ML health through the protected bridge, and switches HTTP and new camera WebSocket requests only after that check passes. Failed updates preserve the previous target. The endpoint never returns tunnel addresses or secrets and is unavailable on the laptop bridge. Existing camera connections must reconnect if their old tunnel has stopped; the live-camera page already supports reconnecting.

The website shows whether laptop ML is connected. Its UI remains available when the laptop is offline; analysis and live route intelligence require the laptop. Model weights and application records stay in their existing local folders, so back them up there.

## Connection and secrets

Render → HTTPS Cloudflare Quick Tunnel → token-protected loopback bridge (8788) → ML server (8000).

The Cloudflare address exposes the bridge, which requires a separate random secret on every ML request. Render's public-admin mode supplies the laptop administrator credential on the server side; visitors receive no password or authorization token. The laptop backend still enforces authentication. Render stores `TUNNEL_URL`, `BRIDGE_TOKEN`, `PUBLIC_ADMIN_ENABLED=true` and the secret `UPSTREAM_ADMIN_AUTHORIZATION` (HTTP Basic authorization derived from the laptop `.env`). The Render account key stays on the laptop. The private `.tools/free-hosting.json` file contains the connection secret and must never be committed or shared. Logs are in `logs/free-bridge.log`, `logs/free-tunnel.log` and `logs/free-hosting.log`.

Model checkpoint uploads remain **laptop-only** because PyTorch `.pt` files can execute code when loaded. Public upload attempts return an explanatory error. Image/video analysis and the installed model tools remain available on the website. Upload a trusted new checkpoint through the signed-in laptop app. Public users share the same admin role and can change settings and application records; use this public setup only for data and controls you intend to share.

The launcher stops only its own bridge and tunnel processes. It does not change firewall rules, enable remote desktop, install an automatic startup service, or stop the local ML app. Quick Tunnels do not require a Cloudflare account or domain. If recreating this setup on another computer, install the full local app, authenticate the official Render CLI, and configure a free gateway service with the same private bridge token and server-side admin credential. Changing the laptop administrator credential requires updating the corresponding Render secret and deploying that configuration.

## Free plan limits

[Render free web services](https://render.com/docs/free) sleep after 15 minutes without incoming traffic and can take about a minute to wake. The 750 free instance hours are shared by **all free web services in the workspace**; this account already has other apps. Usage limits can suspend services, so this is a demonstration deployment, not guaranteed continuous hosting. The launcher's minute connection updates keep the gateway active while the laptop connection runs and consume free instance hours; stopping the launcher allows idle sleep.

[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) are temporary development/testing connections without an uptime guarantee. Their address changes when recreated, and they do not support SSE; this app uses HTTP and WebSockets. Laptop internet upload speed and the two network hops affect camera FPS. Moving-bus speed still requires GPS/calibration; a camera alone does not establish accurate vehicle speed. Missing optional specialist weights and synthetic forecast training data retain their existing labels.

`render.paid.yaml` and `Dockerfile.render` preserve the separately tested full cloud deployment example. They are **not used by free hosting**. Do not apply the paid example unless you choose paid hosting later.
