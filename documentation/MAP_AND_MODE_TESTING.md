# Location tracking and camera traffic map

Open the [passenger map](https://transitopt-free.onrender.com/passenger). It uses OpenStreetMap and OSRM with Google Maps-style location controls. It does not import Google's proprietary traffic layer.

1. Click **Live location**, allow location permission, and follow the blue dot. Its circle shows GPS accuracy. **Recenter** resumes following after you drag the map. **Stop tracking** releases the location watcher.
2. Search a destination or choose **Starting place** to search the origin. You can also pick two points, use a single GPS fix, or swap endpoints.
3. Blue lines show road alternatives; the thicker line is selected. **Fit routes** shows the available paths. Keep **Avoid observed traffic** and automatic routing enabled to monitor cameras every five seconds. Useful GPS movement updates the route origin at most once every 30 seconds. Low-accuracy fixes do not trigger rerouting.
4. In **Find traffic places**, choose nearby coverage or **All cameras**. Click **Minimum observed** or **Maximum observed** to jump to a camera. Sort the list, inspect the map card, or select **Directions to this place**.
5. Green/yellow/orange/red markers represent low/moderate/high/severe visible vehicle pressure. Gray means unknown current traffic. Hide the traffic layer while keeping blue routes visible.

Minimum/maximum comparisons require fresh live road-camera detections and an actual configured position or synchronized bus GPS. Recorded footage, stale reports and approximate demo pins are excluded. Fixed-camera evidence expires after five minutes; moving-bus captures after twenty seconds. Pressure describes a camera view, not an entire road, measured delay or a guarantee that another road is clear. Provider alternatives are not fabricated when only one path exists.

GPS requires HTTPS and explicit permission ([MDN location watching](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/watchPosition)). Route-origin updates and destinations go to the existing routing API; the visible location dot stays in the browser. [Google Maps directions links](https://developers.google.com/maps/documentation/urls/get-started) calculate their own route and time.

## Verification and limits

Automated suites cover the installed API, ML and UI modes, map alternatives, manual overrides, automatic switching, GPS consent/cleanup/following, movement throttling and stale/unlocated traffic exclusion. Regression checks caught a missing `time` import in local live-camera work. Camera controls now remain visible during background refresh.

On October 9, 2026, 107 backend tests and 53 frontend tests passed. The free gateway Docker image built successfully, including TypeScript checking and the production frontend build. The public workflow run passed 24 API/ML checks and 31 page entry points, returning two real road alternatives and an optimal draft bus plan.

`scripts/verify_full_app.py --base-url https://transitopt-free.onrender.com --public` checks module APIs, 31 SPA entry points, recorded general/person image and video detections, 30/60/120-minute forecasts, draft optimization, scenario exports, OSRM alternatives and local route RAG. It never approves or activates a plan. Its local report is ignored by Git at `data/demo_exports/public-app-verification.json`.

Samples are a stock image and repeated-image video, not live signal or bus-interior footage. Demand training remains synthetic. Specialist container/condition weights and authorized network feeds must be supplied. Physical webcam, phone-camera and GPS permissions require device testing. Browser automation was unavailable during this run; real-device GPS accuracy and screenshots are not claimed.

Full ML remains on the laptop behind the free Render gateway. Keep `Start-Free-Hosting.bat` running and the laptop awake. Admin access remains public; model checkpoint uploads stay on the signed-in laptop app.
