import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import { ArrowRight, BusFront, Camera, Crosshair, MapPin, Navigation, Search, ShieldCheck } from 'lucide-react';
import { transitRequest, type Data } from '../../services/transit';
import ThemeToggle from '../../components/ThemeToggle';
import RouteRagAssistant from '../../components/transit/RouteRagAssistant';
import 'leaflet/dist/leaflet.css';
import './passenger.css';

type Point = { latitude: number; longitude: number };
type MapPick = 'origin' | 'destination' | null;
const SALEM: [number, number] = [11.6649, 78.1460];
const colors = ['#1267e9', '#3b82f6', '#60a5fa', '#2563eb'];
const marker = (label: string, color: string) => L.divIcon({ className: 'pa-pin', html: `<span style="background:${color}">${label}</span>`, iconSize: [34, 34], iconAnchor: [17, 17] });

function RouteViewport({ route, routes }: { route?: Data; routes:Data[] }) {
  const map = useMap();
  const paths=routes.map(r=>r.id).join('|');
  const previousPaths=useRef('');
  useEffect(() => {
    const geometry = paths!==previousPaths.current ? routes.flatMap(r=>r.geometry??[]) : route?.geometry;
    previousPaths.current=paths;
    if (Array.isArray(geometry) && geometry.length > 1) map.fitBounds(geometry.map(([lon, lat]: [number, number]) => [lat, lon]), { padding: [45, 90], maxZoom: 15 });
  }, [map, route?.id, paths]);
  return null;
}

export function googleDirections(origin: Point, destination: Point) {
  return `https://www.google.com/maps/dir/?${new URLSearchParams({ api: '1', origin: `${origin.latitude},${origin.longitude}`, destination: `${destination.latitude},${destination.longitude}`, travelmode: 'driving', dir_action: 'navigate' })}`;
}

function MapInteraction({ pick, setPoint, focus }: { pick: MapPick; setPoint: (point: Point) => void; focus: Point | null }) {
  const map = useMap();
  useMapEvents({ click(event) { if (pick) setPoint({ latitude: event.latlng.lat, longitude: event.latlng.lng }); } });
  useEffect(() => { if (focus) map.flyTo([focus.latitude, focus.longitude], Math.max(map.getZoom(), 13)); }, [focus, map]);
  return null;
}

function formatTime(value?: string) { return value ? new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : 'Unavailable'; }
function km(value?: number) { return value == null ? 'Unavailable' : `${value.toFixed(1)} km`; }
function crowdText(crowd:Data|undefined) { return crowd?.fresh ? `${crowd.live ? 'Live' : 'Recorded'} ${crowd.level} visible crowd · ${crowd.coverage} coverage` : 'Current crowding unavailable'; }

export default function PassengerPage() {
  const [searchParams]=useSearchParams();
  const [linkedBus,setLinkedBus]=useState(searchParams.get('bus_id') ?? '');
  const busOriginRef=useRef<{point:Point;at:number}|null>(null);
  const [origin, setOrigin] = useState<Point | null>(null);
  const [destination, setDestination] = useState<Point | null>(null);
  const [focus, setFocus] = useState<Point | null>(null);
  const [pick, setPick] = useState<MapPick>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [gpsState, setGpsState] = useState('Location permission has not been requested.');
  const [radius, setRadius] = useState(5);
  const [query, setQuery] = useState('');
  const [places, setPlaces] = useState<Data[]>([]);
  const [cameras, setCameras] = useState<Data[]>([]);
  const [buses, setBuses] = useState<Data[]>([]);
  const [busQuery, setBusQuery] = useState('');
  const [busResults, setBusResults] = useState<Data[]>([]);
  const [stops, setStops] = useState<Data[]>([]);
  const [routes, setRoutes] = useState<Data[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [trackedBus, setTrackedBus] = useState<string | null>(null);
  const [boardingStop,setBoardingStop] = useState('');
  const [arrival,setArrival] = useState<Data|null>(null);
  const [arrivalError,setArrivalError] = useState('');
  const [navigating, setNavigating] = useState(false);
  const [goal, setGoal] = useState<'fastest' | 'lowest_observed_traffic' | 'shortest'>('lowest_observed_traffic');
  const [useRecordedDemo,setUseRecordedDemo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [routeAlerts, setRouteAlerts] = useState<Data[]>([]);
  const [sharedAlerts, setSharedAlerts] = useState<Data[]>([]);
  const [recommendedId, setRecommendedId] = useState<string | null>(null);
  const [autoRoute, setAutoRoute] = useState(true);
  const [switchNotice, setSwitchNotice] = useState('');
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const planVersion = useRef(0);
  const planController = useRef<AbortController | null>(null);
  const planTimer = useRef<number | undefined>(undefined);
  const [monitorError, setMonitorError] = useState('');
  const [routeContextId,setRouteContextId]=useState<string|null>(null);
  const [busAdvice,setBusAdvice]=useState(searchParams.get('advice')==='bus');
  const routesRef = useRef<Data[]>([]);
  useEffect(() => { routesRef.current = routes; }, [routes]);
  useEffect(() => {
    let active = true, pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try { const feed = await transitRequest<Data>('/api/public/traffic/feed'); if (active) setSharedAlerts(feed.alerts ?? []); }
      catch { /* Route monitor reports its own connection status below. */ }
      finally { pending = false; }
    };
    refresh(); const timer = window.setInterval(refresh, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const [lastFix, setLastFix] = useState<number | null>(null);

  useEffect(()=>{
    if(!linkedBus)return;
    let active=true,pending=false;
    const refresh=async()=>{
      if(pending)return;pending=true;
      try{
        const bus=await transitRequest<Data>(`/api/public/buses/${encodeURIComponent(linkedBus)}`);
        if(!active)return;
        if(!bus.location?.fresh){setGpsState(`${linkedBus}: fresh bus GPS is required.`);setOrigin(null);setRoutes([]);routesRef.current=[];setSelected(null);busOriginRef.current=null;return;}
        const point={latitude:bus.location.latitude,longitude:bus.location.longitude};
        setGpsState(`${linkedBus} GPS${bus.location.source==='demo_simulation'?' (SIMULATION)':''}: ${formatTime(bus.location.timestamp)}`);
        const previous=busOriginRef.current;
        const moved=previous?Math.hypot((point.latitude-previous.point.latitude)*111320,(point.longitude-previous.point.longitude)*111320*Math.cos(point.latitude*Math.PI/180)):Infinity;
        if(!previous || moved>=100 && Date.now()-previous.at>=30000){
          busOriginRef.current={point,at:Date.now()};setOrigin(point);setFocus(point);setAccuracy(bus.location.accuracy_m??null);
          setRoutes([]);routesRef.current=[];setSelected(null);setRouteAlerts([]);
        }
      }catch(e){if(active){setGpsState(`Bus GPS unavailable: ${(e as Error).message}`);setOrigin(null);setRoutes([]);routesRef.current=[];setSelected(null);busOriginRef.current=null;}}
      finally{pending=false;}
    };
    void refresh();const timer=window.setInterval(refresh,10000);return()=>{active=false;window.clearInterval(timer);};
  },[linkedBus]);

  useEffect(() => {
    transitRequest<Data>('/api/public/stops').then(data => setStops(data.stops ?? [])).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!origin) return;
    let active = true;
    const refresh = () => {
      const q = `latitude=${origin.latitude}&longitude=${origin.longitude}`;
      transitRequest<Data>(`/api/public/traffic/nearby?${q}&radius_km=${radius}`).then(data => { if (active) setCameras(data.cameras ?? []); }).catch(e => { if (active) setError(e.message); });
      transitRequest<Data>(`/api/navigation/nearby-buses?${q}&radius_km=20`).then(data => { if (active) setBuses(data.buses ?? []); }).catch(e => { if (active) setError(e.message); });
    };
    refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [origin?.latitude, origin?.longitude, radius]);
  useEffect(() => {
    if (!navigating || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(position => {
      setOrigin({ latitude: position.coords.latitude, longitude: position.coords.longitude });
      setAccuracy(position.coords.accuracy);
      setLastFix(Date.now());
      setGpsState(`GPS updated ${new Date().toLocaleTimeString()}`);
    }, e => setGpsState(`GPS signal unavailable: ${e.message}. Manual origin remains available.`),
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 12000 });
    return () => navigator.geolocation.clearWatch(id);
  }, [navigating]);
  useEffect(() => {
    if (!trackedBus) return;
    let active = true;
    setArrival(null);setArrivalError('');
    const refresh = () => {
      transitRequest<Data>(`/api/public/buses/${trackedBus}`).then(bus => {
        if (active) setBusResults(current=>[...current.filter(item=>item.id!==bus.id),bus]);
      }).catch(e=>{if(active)setArrivalError(e.message);});
      transitRequest<Data>(`/api/public/buses/${trackedBus}/arrival${boardingStop ? '?stop_id='+encodeURIComponent(boardingStop) : ''}`)
        .then(data=>{if(active){setArrival(data);setArrivalError('');}}).catch(e=>{if(active)setArrivalError(e.message);});
    };
    refresh();const timer=window.setInterval(refresh,15000);
    return ()=>{active=false;window.clearInterval(timer);};
  }, [trackedBus,boardingStop]);
  useEffect(() => {
    if (!navigating || lastFix === null) return;
    const timer = window.setInterval(() => {
      if (Date.now() - lastFix > 90000) setGpsState('GPS signal lost. The last position may be stale.');
    }, 10000);
    return () => window.clearInterval(timer);
  }, [navigating, lastFix]);
  useEffect(() => {
    if (!destination || !selected) return;
    let active = true, pending = false;
    const refresh = async () => {
      const version = planVersion.current;
      const currentRoutes = routesRef.current;
      if (!currentRoutes.length || pending) return;
      pending = true;
      try {
        const data = await transitRequest<Data>('/api/public/navigation/monitor', { method: 'POST',
          body: JSON.stringify({ routes: currentRoutes.map(route => ({ id:route.id, geometry:route.geometry,
            distance_km:route.distance_km, base_duration_minutes:route.base_duration_minutes })),
            selected_route_id: selected, goal, use_recorded_demo: useRecordedDemo,route_context_id:routeContextId??undefined }) });
        if (!active || version !== planVersion.current) return;
        setRoutes(data.routes ?? []); routesRef.current = data.routes ?? []; setRouteAlerts(data.route_alerts ?? []);
        setRecommendedId(data.recommended_route_id); setMonitorError('');
        setCheckedAt(new Date().toLocaleTimeString());
        if (autoRoute && data.recommended_route_id && data.recommended_route_id !== selected && data.routes?.some((route: Data) => route.id === data.recommended_route_id)) {
          setSelected(data.recommended_route_id);
          setSwitchNotice('Route updated automatically using the latest camera comparison. Traffic on unobserved roads remains unknown.');
        }
      } catch (e) { if (active) setMonitorError(`Live traffic monitoring unavailable: ${(e as Error).message}`); }
      finally { pending = false; }
    };
    refresh(); const timer = window.setInterval(refresh, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [destination?.latitude, destination?.longitude, selected, goal, useRecordedDemo, autoRoute, routeContextId]);

  useEffect(() => {
    // Replan after endpoint/goal changes; GPS tracking must not trigger a request per fix.
    if (navigating) { setBusy(false); return; }
    setRouteContextId(null);
    if (!origin || !destination) return;
    const timer = window.setTimeout(() => { void plan(); }, 400);
    planTimer.current = timer;
    return () => { window.clearTimeout(timer); planController.current?.abort(); planVersion.current += 1; };
  }, [origin?.latitude, origin?.longitude, destination?.latitude, destination?.longitude, goal, useRecordedDemo, navigating]);
  useEffect(() => () => { planController.current?.abort(); planVersion.current += 1; }, []);

  const selectedRoute = useMemo(() => routes.find(route => route.id === selected), [routes, selected]);
  const displayBuses = useMemo(() => Array.from(new Map([...buses, ...busResults].map(bus => [bus.id, bus])).values()), [buses, busResults]);

  function locate() {
    setLinkedBus('');
    if (!navigator.geolocation) { setGpsState('This browser does not support geolocation. Choose an origin on the map.'); return; }
    setGpsState('Waiting for GPS permission…');
    navigator.geolocation.getCurrentPosition(position => {
      const point = { latitude: position.coords.latitude, longitude: position.coords.longitude };
      setNavigating(false); setOrigin(point); setFocus(point); setAccuracy(position.coords.accuracy);
      setRoutes([]);routesRef.current=[];setSelected(null);setRouteAlerts([]);setRecommendedId(null);
      setLastFix(Date.now());
      setGpsState(`GPS fix received ${new Date().toLocaleTimeString()}`);
    }, e => setGpsState(`Location unavailable: ${e.message}. Choose an origin on the map.`),
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 12000 });
  }
  async function searchPlaces(event: FormEvent) {
    event.preventDefault(); if (query.trim().length < 3) return;
    setBusy(true); setError('');
    try { const data = await transitRequest<Data>(`/api/public/navigation/places?q=${encodeURIComponent(query.trim())}`); setPlaces(data.places ?? []); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function searchBus(event: FormEvent) {
    event.preventDefault(); setError('');
    try { const data = await transitRequest<Data>(`/api/public/buses?q=${encodeURIComponent(busQuery.trim())}`); setBusResults(data.buses ?? []); }
    catch (e) { setError((e as Error).message); }
  }
  async function plan(nextGoal = goal) {
    if (!origin || !destination) { setError('Set a starting point and destination first.'); return; }
    window.clearTimeout(planTimer.current);
    const version = ++planVersion.current;
    planController.current?.abort();
    const controller = new AbortController(); planController.current = controller;
    setBusy(true); setError(''); setNotice(''); setSwitchNotice('');
    try {
      const data = await transitRequest<Data>('/api/public/navigation/routes', { method: 'POST',
        signal: controller.signal, body: JSON.stringify({ origin, destination, goal: nextGoal,use_recorded_demo:useRecordedDemo }) });
      if (version !== planVersion.current || controller.signal.aborted) return;
      setRoutes(data.routes ?? []); routesRef.current=data.routes ?? []; setSelected(data.selected_route_id);
      setRouteAlerts(data.route_alerts ?? []); setRecommendedId(data.recommended_route_id);
      setRouteContextId(data.route_context_id??null);
      setCheckedAt(new Date().toLocaleTimeString());
      setNotice(data.traffic_note ?? 'Road routes returned by OSRM.');
    } catch (e) { if (version === planVersion.current && !controller.signal.aborted) setError((e as Error).message); }
    finally { if (version === planVersion.current) setBusy(false); }
  }
  function selectRoute(id: string) { setAutoRoute(false); setSelected(id); setSwitchNotice('Manual route selected. Enable automatic routing to switch again as traffic changes.'); }
  const effectivePick=pick??(!origin?'origin':!destination?'destination':null);
  const choosePoint = (point: Point) => {
    if(!effectivePick)return;
    setNavigating(false);setRouteContextId(null);
    if(effectivePick==='origin'){setLinkedBus('');setOrigin(point);setAccuracy(null);setLastFix(null);setGpsState('Manual origin selected.');setPick(destination?null:'destination');}
    else{setDestination(point);setPick(null);}
    setFocus(point);setRoutes([]);routesRef.current=[];setSelected(null);setRouteAlerts([]);setRecommendedId(null);
  };
  function newJourney(){planController.current?.abort();window.clearTimeout(planTimer.current);planVersion.current+=1;setBusy(false);setNavigating(false);setLinkedBus('');setBusAdvice(false);setOrigin(null);setDestination(null);setPick('origin');setAccuracy(null);setLastFix(null);setQuery('');setRoutes([]);routesRef.current=[];setSelected(null);setRecommendedId(null);setRouteAlerts([]);setRouteContextId(null);setAutoRoute(true);setSwitchNotice('');setError('');setGpsState('Click the start, then the destination on the map.');}
  const choosePlace = (place: Data) => { setNavigating(false); const point = { latitude: place.latitude, longitude: place.longitude }; setDestination(point); setFocus(point); setPlaces([]); setQuery(place.name); setRoutes([]); routesRef.current=[]; setSelected(null); setRouteAlerts([]); setRecommendedId(null); };

  return <div className="pa-shell">
    <header className="pa-header"><Link to="/" className="pa-brand"><BusFront size={24} /> TRANSITOPT <span>AI 2.0</span></Link><div className="pa-header-label">SALEM PASSENGER NAVIGATION <span>· DEMO MAP</span></div><div style={{ display: 'flex', alignItems: 'center', gap: 14 }}><ThemeToggle variant="compact" /><Link className="pa-operator-link" to="/admin">Head office <ArrowRight size={15} /></Link></div></header>
    <main className="pa-workspace">
      <aside className="pa-sidebar">
        <div className="pa-intro"><div className="pa-eyebrow">DETECT · TRACK · NAVIGATE</div><h1>Move with clarity.</h1><p>Find a road route, inspect nearby camera coverage, and track registered buses when GPS updates are available.</p></div>
        <div className="pa-section"><h2><Navigation size={17} /> Plan your journey</h2>
          <form className="pa-search" onSubmit={searchPlaces}><Search size={16} /><input aria-label="Search destination" placeholder="Search a destination in India" value={query} onChange={e => setQuery(e.target.value)} /><button disabled={busy || query.trim().length < 3}>Search</button></form>
          {places.length > 0 && <div className="pa-place-results">{places.map((place, i) => <button key={i} onClick={() => choosePlace(place)}><MapPin size={14} />{place.name}</button>)}</div>}
          <div className="pa-point-actions"><button onClick={locate}><Crosshair size={15} /> Use my GPS</button><button className={effectivePick === 'origin' ? 'selected' : ''} onClick={() => setPick('origin')}>Pick origin</button><button className={effectivePick === 'destination' ? 'selected' : ''} onClick={() => setPick('destination')}>Pick destination</button><button onClick={newJourney}>New map journey</button></div>
          <p className="pa-map-instructions">{!origin?'1. Click the map to choose your start.':!destination?'2. Click the map to choose your destination.':'Click a blue line or a route card to choose a way to reach your destination.'}</p>
          <div className="pa-coordinates"><span>START <b>{origin ? `${origin.latitude.toFixed(5)}, ${origin.longitude.toFixed(5)}` : 'Choose on map or use GPS'}</b></span><span>DESTINATION <b>{destination ? `${destination.latitude.toFixed(5)}, ${destination.longitude.toFixed(5)}` : 'Search or choose on map'}</b></span></div>
          <div className="pa-gps-note">{gpsState}{accuracy != null ? ` · accuracy ±${Math.round(accuracy)} m` : ''}</div>
          {linkedBus && <p className="pa-muted">Planning from {linkedBus}. GPS refreshes every 10 seconds; the route origin updates after moving 100 m, at most every 30 seconds. This is a road advisory; bus stops and service changes require operator approval.</p>}
          <label className="pa-select">Route goal<select value={goal} onChange={e => setGoal(e.target.value as typeof goal)}><option value="fastest">Fastest camera-aware comparison</option><option value="lowest_observed_traffic">Avoid observed traffic</option><option value="shortest">Shortest distance</option></select></label>
          <label className="pa-auto-route"><input type="checkbox" checked={autoRoute} onChange={e=>{setAutoRoute(e.target.checked);setSwitchNotice('');}}/>Automatically select and update my route</label><p className="pa-muted">Routes load when both points are set. Choose a route manually to turn automatic switching off.</p>
          <label className="pa-muted" style={{display:'flex',gap:8,marginBottom:14}}><input type="checkbox" checked={useRecordedDemo} onChange={e=>setUseRecordedDemo(e.target.checked)}/>Use recorded demo traffic in route comparison</label>
          <button className="pa-primary" disabled={busy || !origin || !destination} onClick={() => plan()}>{busy ? 'Checking road routes…' : 'Find road routes'} <ArrowRight size={16} /></button>
        </div>
        <div className="pa-section"><h2><Camera size={17} /> Camera coverage</h2><div className="pa-radii">{[1, 3, 5, 10].map(value => <button key={value} className={radius === value ? 'selected' : ''} onClick={() => setRadius(value)}>{value} km</button>)}</div><p className="pa-muted">The circle shows camera discovery around the selected origin. Each camera observes only its own view.</p>{cameras.map(camera => <div className="pa-camera" key={camera.id}><span className="pa-status-dot" style={{ background: camera.observation?.live ? '#00e5a0' : '#fbbf24' }} /><div><strong>{camera.name}</strong><small>{km(camera.distance_km)} · {camera.observation?.live ? `${camera.observation.category} · live camera` : camera.observation?.fresh && camera.observation?.observation_type==='recorded_detection' ? `${camera.observation.category} · recorded evidence` : 'Current traffic unknown'}</small></div></div>)}{origin && !cameras.length && <p className="pa-muted">No registered road cameras in this radius.</p>}</div>
      </aside>
      <div className="pa-map-pane"><MapContainer className="pa-map" center={SALEM} zoom={13} zoomControl={false} scrollWheelZoom><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" /><ZoomControl position="bottomleft" /><MapInteraction pick={effectivePick} setPoint={choosePoint} focus={focus} /><RouteViewport route={selectedRoute} routes={routes} />
        {origin && <><Circle center={[origin.latitude, origin.longitude]} radius={radius * 1000} pathOptions={{ color: '#43baff', fillColor: '#43baff', fillOpacity: .07, weight: 1 }} /><Marker position={[origin.latitude, origin.longitude]} icon={marker('●', '#2e90ff')}><Popup>Your selected origin{accuracy != null ? ` · GPS accuracy ±${Math.round(accuracy)} m` : ''}</Popup></Marker></>}
        {destination && <Marker position={[destination.latitude, destination.longitude]} icon={marker('◆', '#fbbf24')}><Popup>Destination</Popup></Marker>}
        {routes.map((route, index) => <Polyline key={route.id} bubblingMouseEvents={false} positions={(route.geometry ?? []).map(([lon, lat]: [number, number]) => [lat, lon])} pathOptions={{ color: route.id === selected ? colors[0] : colors[(index % 3) + 1], weight: route.id === selected ? 8 : 5, opacity: route.id === selected ? 1 : .8 }} eventHandlers={{ click: () => selectRoute(route.id) }}><Tooltip sticky>Road option {index+1} | {route.base_duration_minutes} min | {km(route.distance_km)}</Tooltip></Polyline>)}
        {arrival?.geometry && <Polyline positions={arrival.geometry.map(([lon,lat]:[number,number])=>[lat,lon])} pathOptions={{color:'#965cfa',weight:5,dashArray:'8 6'}}><Tooltip>Configured bus stop sequence · road profile estimate</Tooltip></Polyline>}
        {stops.filter(stop => stop.latitude != null).map(stop => <CircleMarker key={stop.id} center={[stop.latitude, stop.longitude]} radius={5} pathOptions={{ color: '#ffffff', fillColor: '#37d7bc', fillOpacity: 1, weight: 2 }}><Tooltip>{stop.name} · {stop.coordinate_source==='illustrative_demo_coordinate'?'illustrative demo location':'operator configured location'}</Tooltip></CircleMarker>)}
        {cameras.map(camera=><CircleMarker key={camera.id} center={[camera.latitude,camera.longitude]} radius={8} pathOptions={{color:'#061828',fillColor:camera.observation?.live?'#00e5a0':'#fbbf24',fillOpacity:1,weight:2}}><Popup><strong>{camera.name}</strong><br/>{camera.coordinate_source.replaceAll('_',' ')}<br/>{camera.observation?.live?`Live camera: ${camera.observation.category}`:camera.observation?.observation_type==='recorded_detection'?`Recorded evidence: ${camera.observation.category}`:'Current traffic unknown'}</Popup></CircleMarker>)}
        {displayBuses.filter(bus => bus.location).map(bus => <Marker key={bus.id} position={[bus.location.latitude, bus.location.longitude]} icon={marker('B', bus.location.fresh ? '#00e5a0' : '#8a9ba7')}><Popup><strong>{bus.registration_number ?? bus.id}</strong><br />Route {bus.route_id}<br />{bus.location.source==='demo_simulation'?'SIMULATION GPS':'GPS'} {formatTime(bus.location.timestamp)} · {bus.location.fresh ? 'fresh' : 'last known, stale'}<br />{crowdText(bus.crowding)}</Popup></Marker>)}
      </MapContainer><div className="pa-map-caption">{pick ? `Click the map to set your ${pick}` : 'OSRM roads · OpenStreetMap · Demo pins approximate'}</div>
        {error && <div className="pa-error" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
        {selectedRoute && <div className="pa-route-card"><div><small>SELECTED ROAD ROUTE</small><strong>{km(selectedRoute.distance_km)} · {selectedRoute.base_duration_minutes} min</strong><p>{selectedRoute.observed_camera_count ? `${selectedRoute.observed_camera_count} local camera observation(s) · comparison ${selectedRoute.comparison_minutes} min` : 'Traffic conditions unknown along most of this route'}</p></div><button disabled={Boolean(linkedBus)} onClick={() => setNavigating(value => !value)}>{linkedBus ? 'Following bus GPS' : navigating ? 'Stop GPS tracking' : 'Track my position'}</button></div>}
      </div>
      <aside className="pa-right"><div className="pa-right-heading"><span>TRAVEL INTELLIGENCE</span><ShieldCheck size={17} /></div>
        <h2>Route options</h2>{routes.length===1&&<p className="pa-muted">The provider returned one valid road path. No other alternative is currently available.</p>}{routes.length>1&&<p className="pa-muted">{routes.length} ways to reach your destination. Blue lines show provider road alternatives; the thicker line is selected.</p>}{selected && <p className="pa-muted">{autoRoute ? 'Automatic routing on - checks every 5 seconds' : 'Manual route - traffic checks every 5 seconds'}{checkedAt && ` - checked ${checkedAt}`}</p>}{switchNotice && <div className="pa-route-update" role="status">{switchNotice}</div>}{origin && destination && <><a className="pa-google-link" href={googleDirections(origin, destination)} target="_blank" rel="noopener noreferrer">Open in Google Maps <Navigation size={16}/></a><p className="pa-muted">Google Maps calculates its own route and travel time for these points.</p></>}{monitorError && <p className="pa-muted" role="status">{monitorError}</p>}
        {routeAlerts.length > 0 && <div className="pa-traffic-alert" role="alert"><strong>Traffic detected on your route</strong>{routeAlerts.map(alert => <p key={alert.id}>{alert.message}{alert.prediction?.available ? ` Next-minute pressure: ${alert.prediction.predicted_score}/100.` : ''}</p>)}{recommendedId && recommendedId!==selected ? <button onClick={() => selectRoute(recommendedId)}>Use recommended alternative <ArrowRight size={14} /></button> : <small>No better provider alternative is available yet. Monitoring continues.</small>}</div>}
        {recommendedId && recommendedId!==selected && !routeAlerts.length && <button className="pa-primary" onClick={() => selectRoute(recommendedId)}>Select recommended alternative <ArrowRight size={14} /></button>}{routes.length ? routes.map((route, index) => <button key={route.id} className={`pa-option ${selected === route.id ? 'active' : ''}`} onClick={() => selectRoute(route.id)} aria-pressed={selected === route.id}><span className="pa-option-line" style={{ background: colors[index] }} /><div><strong>{route.id===recommendedId ? 'Recommended road route' : index === 0 ? 'Primary road route' : `Alternative ${index}`}</strong><small>{km(route.distance_km)} · {route.base_duration_minutes} min profile ETA</small><small>{route.observed_camera_count ? `${route.observed_camera_count} live camera(s) - comparison ${route.comparison_minutes} min` : route.recorded_demo_camera_count ? `${route.recorded_demo_camera_count} RECORDED DEMO camera(s)` : 'Current traffic coverage unknown'}</small><small className="pa-route-evidence">{route.observed_camera_count ? (route.high_pressure_camera_count ? 'High pressure observed on this route' : 'No high pressure reported by covered cameras') : 'Unobserved roads are not confirmed clear'}</small></div></button>) : <p className="pa-muted">Set two points to compare road network alternatives.</p>}
        {routes.length > 0 && <p className="pa-muted">{notice} Selecting an alternative changes only your journey.</p>}
        {routes.length>0&&<>{linkedBus&&<label className="pa-auto-route"><input type="checkbox" checked={busAdvice} onChange={e=>setBusAdvice(e.target.checked)}/>Include bus service constraints (operator sign-in)</label>}<RouteRagAssistant contextId={routeContextId} busId={busAdvice?linkedBus:null} recommendedId={recommendedId} onSelect={selectRoute}/></>}<div className="pa-divider" /><h2>Shared traffic updates</h2>{sharedAlerts.length ? sharedAlerts.map(alert => <div className="pa-camera" key={alert.id}><Camera size={15} /><div><strong>{alert.camera_name}</strong><small>{alert.message}</small></div></div>) : <p className="pa-muted">No active camera reports high traffic pressure. Traffic on unobserved roads remains unknown.</p>}<div className="pa-divider" /><h2>Find a bus</h2><form className="pa-search" onSubmit={searchBus}><Search size={16} /><input aria-label="Find bus or route" placeholder="Bus, route, stop or destination" value={busQuery} onChange={e => setBusQuery(e.target.value)} /><button>Find</button></form><p className="pa-muted">Nearby buses refresh every 10 seconds. Search also shows buses without live GPS.</p>{displayBuses.length ? displayBuses.map(bus => <button key={bus.id} className={`pa-bus ${trackedBus === bus.id ? 'active' : ''}`} onClick={() => { setTrackedBus(bus.id); setBoardingStop(''); if (bus.location) setFocus({ latitude: bus.location.latitude, longitude: bus.location.longitude }); }}><BusFront size={18} /><div><strong>{bus.registration_number ?? bus.id} <span>· {bus.route_id}</span></strong><small>{bus.location?.fresh ? `${bus.location.source==='demo_simulation'?'SIMULATION · ':''}${bus.distance_km == null ? 'Fresh location' : km(bus.distance_km)+' away'} · GPS ${formatTime(bus.location.timestamp)}` : bus.location ? 'Live tracking unavailable · last known location' : 'Live tracking unavailable · no GPS report'}</small><small>{crowdText(bus.crowding)}</small></div></button>) : <p className="pa-muted">No bus with a fresh GPS report is nearby. Start the demo GPS publisher or search a registered bus.</p>}
        {trackedBus && <div className="pa-privacy" style={{display:'block'}}><strong>Tracking {trackedBus}</strong><label className="pa-select">Boarding stop<select aria-label="Boarding stop" value={boardingStop} onChange={e=>setBoardingStop(e.target.value)}><option value="">Next stop in declared direction</option>{stops.filter(stop=>displayBuses.find(bus=>bus.id===trackedBus)?.stop_ids?.includes(stop.id)).map(stop=><option key={stop.id} value={stop.id}>{stop.name}</option>)}</select></label>{arrival?.available ? <><strong>≈ {arrival.estimated_minutes} min to {arrival.stop?.name}</strong><p>Next stop: {arrival.next_stop?.name} · {arrival.demo ? 'DEMO ESTIMATE' : 'ROAD PROFILE ESTIMATE'}</p></> : <p>{arrivalError || arrival?.reason || 'Checking current bus progress…'}</p>}<small>{arrival?.note ?? 'Arrival estimates require fresh GPS and a declared service direction.'}</small></div>}
        <p className="pa-privacy"><ShieldCheck size={16} /> Passenger view contains only aggregate crowding. Interior CCTV and incident evidence require operator access. Selected route coordinates go to OSRM; place searches go to Nominatim.</p>
      </aside>
    </main>
  </div>;
}
