# Free Render website with full laptop ML

The default `render.yaml` uses Render's **free** plan and `Dockerfile.gateway`. Only the React website and a small streaming gateway run there. YOLO, local route RAG, XGBoost, traffic learning, optimization, camera analysis and the database run on the existing laptop server. There is no paid disk or paid compute in this setup.

## Run or reconnect

1. On the configured laptop, double-click **Start-Free-Hosting.bat**. Leave that window open and keep the laptop awake and connected to the internet.
2. Open the Render website printed by the launcher. Use your existing TransitOpt admin login. Passenger and driver pages use their existing permissions. Browser camera and GPS still require your permission.
3. If the laptop restarted, the launcher creates a new Cloudflare address and reconnects the free Render service. Wait for its deployment to finish, then refresh the website. Reconnection uses the official Render CLI login stored on the laptop; run `render login` again if it expires.
4. Run `Start-Free-Hosting.bat status` to check the laptop bridge. Run `Start-Free-Hosting.bat stop` to close the public tunnel. The local ML app stays available.

The website shows whether laptop ML is connected. Its UI remains available when the laptop is offline; analysis and live route intelligence require the laptop. Model weights and application records stay in their existing local folders, so back them up there.

## Connection and secrets

Render → HTTPS Cloudflare Quick Tunnel → token-protected loopback bridge (8788) → ML server (8000).

The Cloudflare address exposes the bridge, which requires a separate random secret on every ML request. The app's admin authentication still applies. The bridge exposes only the API, never arbitrary laptop files. Render stores `TUNNEL_URL` and `BRIDGE_TOKEN`; the Render account key stays on the laptop. The private `.tools/free-hosting.json` file contains the connection secret and must never be committed or shared. Logs are in `logs/free-bridge.log`, `logs/free-tunnel.log` and `logs/free-hosting.log`.

The launcher stops only its own bridge and tunnel processes. It does not change firewall rules, enable remote desktop, install an automatic startup service, or stop the local ML app. Quick Tunnels do not require a Cloudflare account or domain. If recreating this setup on another computer, install the full local app, authenticate the official Render CLI, and configure a free gateway service with the same private bridge token.

## Free plan limits

[Render free web services](https://render.com/docs/free) sleep after 15 minutes without incoming traffic and can take about a minute to wake. The 750 free instance hours are shared by **all free web services in the workspace**; this account already has other apps. Usage limits can suspend services, so this is a demonstration deployment, not guaranteed continuous hosting. No keep-awake service is installed.

[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) are temporary development/testing connections without an uptime guarantee. Their address changes when recreated, and they do not support SSE; this app uses HTTP and WebSockets. Laptop internet upload speed and the two network hops affect camera FPS. Moving-bus speed still requires GPS/calibration; a camera alone does not establish accurate vehicle speed. Missing optional specialist weights and synthetic forecast training data retain their existing labels.

`render.paid.yaml` and `Dockerfile.render` preserve the separately tested full cloud deployment example. They are **not used by free hosting**. Do not apply the paid example unless you choose paid hosting later.
