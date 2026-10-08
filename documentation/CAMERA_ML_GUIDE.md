# One app: camera ML, passengers and admins

Start the laptop app with `Run-TransitOpt.bat start`. Open `http://127.0.0.1:8000` for the shared home. Passengers use `/passenger` without signing in. Admins and head office use `/ml` for camera ML and `/admin` for fleet planning. Drivers use `/driver`. Existing VisionX models and tools remain available.

## The two main ML uses

**Road traffic:** Choose a registered road camera in `/ml`. Set the actual traffic signal latitude and longitude in the Signal camera location form. Open this device camera, allow camera permission, and press Start Detection. The existing general YOLO model detects vehicles, and the adapter calculates visible vehicle scene pressure. High or severe live pressure appears in the shared home and passenger traffic feed within the five-second polling interval. Only authorized browser input is live; recorded uploads stay marked recorded.

**Bus crowding:** Choose Bus crowding in `/ml`, select the assigned interior camera and start detection. The existing human model filters actual person classes. People visible in the frame update the assigned bus crowd indicator. Road vehicle signals and interior people signals are stored separately. Partial camera coverage cannot measure total bus occupancy. Bus registration, capacity and coverage settings remain in `/fleet`.

The default demo mapping is `BUS005` / `TN30-N-1234` / `BUS_CAM_001`. Its registration and existing camera locations are explicitly illustrative until an administrator configures real data. Public passenger output is aggregate data, without raw detections, footage or incident evidence.

## Live traffic learning and route changes

The scene-pressure model is a Ridge autoregression. It aggregates the latest continuous camera session into ten-second bins. After ten minutes of complete consecutive history it fits lag, recent mean, slope and variability features to a one-minute-ahead scene pressure target. A chronological 20% holdout has a six-bin purge before its boundary. A model forecast becomes available only when it improves mean absolute error over last-observation persistence by at least 5%, and the baseline error is at least one score point. Stable or insufficient history uses current observations and reports why no prediction is active. Recorded footage, historical synthetic demand, other cameras and previous live sessions do not train this model. Models are refit in memory from actual live observations and cached per ten-second bin; no unverified new YOLO weights or invented accuracy are supplied.

Passengers choose origin and destination with GPS, map points or destination search. OSRM supplies real drivable road geometry and available alternatives. Routes load automatically once both points are set. Avoid observed traffic is the default: lowest summed camera pressure first, with profile time breaking ties. The fastest goal instead uses the comparison formula below. The map fits the selected road geometry and displays distance, profile travel time and camera coverage. After a route is selected, `/api/public/navigation/monitor` checks existing provider paths every five seconds, without repeatedly requesting the routing provider. Cameras within 250 m of a path contribute an explicit scene-pressure preference. A validated prediction can increase this preference when pressure is expected to rise. The ranking weight is `profile minutes + min(half profile minutes, 2 × sum(camera pressure/100))`. This is a comparison preference, **not measured traffic delay or a calibrated live ETA**. Unobserved roads remain unknown.

New high or predicted high pressure on the selected route creates an in-app route alert. If another provider route ranks better, **Automatically select and update my route** switches to it and shows a route-update notice. Selecting a route card or map line turns automatic switching off; passengers can re-enable it or select **Use recommended alternative** themselves. Route IDs are based on geometry, so provider ordering does not change path identity. If no better alternate is available, the app states that and keeps monitoring. Selecting an alternative updates only the personal journey. Recorded footage participates only through the explicit recorded-demo checkbox and never publishes a live alert. These updates work while the app is open; background push/SMS delivery is not configured.

## Phone camera setup

1. Connect the phone and laptop to the same Wi-Fi.
2. Run `Run-TransitOpt-Phone.bat start` on the laptop. An optional `-Address 192.168.1.25` selects a private Wi-Fi address. The launcher ensures authentication, replaces a weak demo password with a random strong password in `.env`, restarts this project's backend, and starts a TLS gateway at the printed `https://LAPTOP-IP:8443` address. It uses the same loopback backend and model caches, rather than launching another ML server.
3. Transfer **only** `data/phone_tls/transitopt-phone-ca.crt` to your own phone and manually install/trust that project certificate. On iPhone, enable full trust for it in Certificate Trust Settings. The launcher does not install system trust, alter firewall rules or distribute private keys. Never transfer `ca.key` or `server.key`.
4. Open the printed address in the phone browser over a trusted HTTPS connection. Open `/connect` for instructions, then `/ml` and sign in using the username and password in `.env`.
5. Select a registered road or interior camera, open this device camera, choose Rear phone camera or Front camera, allow permission and press Start Detection. Stop the camera to change devices. Laptop webcam selection remains available.

Browser camera access requires a secure context; plain `http://LAPTOP-IP` will not enable it. See [MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia). A certificate warning is not a completed phone setup. Wi-Fi peer isolation or an OS firewall blocking port 8443 can prevent access. Configure your own network as needed. `Run-TransitOpt-Phone.bat status` prints the address; `stop` stops only the gateway and leaves the laptop app running. Restart after changing Wi-Fi to refresh the server certificate address. Local CA files remain excluded from Git and Docker builds. Remove the project's trusted CA from your phone when you no longer use it.

Camera preview requests up to 60 FPS, while ML detection FPS is measured separately and depends on hardware and connection speed. Fast 320 px detection, binary JPEG frames, one frame in flight and no pose model by default for registered transit cameras preserve the existing performance improvements. The laptop currently uses CPU PyTorch, so no fixed inference FPS is promised.

## Operational limits

Authorized physical traffic-signal feeds are not supplied by this repository. A laptop/phone camera can demonstrate the actual ML pipeline, and recorded files can demonstrate observations, but those inputs do not establish a citywide live deployment. The RTSP worker remains unavailable. Demo geographic pins must be replaced with the signal's real location. Crowding is visible people, not ticketed ridership. GPS comes from device consent or a separately labeled demo publisher, not the webcam. Road routing requires internet and the configured OSRM service. No real bus services are changed.

The **Open in Google Maps** option sends the selected origin and destination to Google on click. Google calculates its own route and travel time; it does not receive the camera ranking or exact selected polyline. It uses the [official Maps directions URL](https://developers.google.com/maps/documentation/urls/get-started). GPS tracking in TransitOpt shows your position; spoken turn-by-turn navigation is provided by the external Maps app when available.

## Camera mounted on a moving bus

Use the `bus_road` role and `/speed`. Bus GPS supplies speed while the forward-facing camera counts vehicles; the interior camera remains separate. See the [moving bus speed guide](BUS_SPEED_GUIDE.md) for setup, sustained-low-speed rules, forecast improvements and limitations.

## Forecast robustness update

The scene learner now aggregates each ten-second bin with a median to reduce isolated detection spikes. Ridge regularization is selected from 1, 10 and 100 on an inner chronological split with a six-bin purge; the separate outer holdout still requires a 5% improvement over persistence. Controlled synthetic fixtures are evaluated by `scripts/evaluate_scene_forecast.py`; these are not field-accuracy measurements. Small route-comparison differences retain the selected path to reduce repeated switching. Meaningful high-pressure improvements can still recommend an alternative.
