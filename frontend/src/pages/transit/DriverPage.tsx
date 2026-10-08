import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { BusFront, Camera, CircleAlert, DoorOpen, MapPin, Radio, ShieldCheck } from 'lucide-react';
import { setCredentials } from '../../services/api';
import { postTransit, transitRequest, type Data } from '../../services/transit';
import ThemeToggle from '../../components/ThemeToggle';
import BusTrafficAdvice from '../../components/transit/BusTrafficAdvice';
import './passenger.css';

export default function DriverPage() {
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const [identity, setIdentity] = useState<Data | null>(null);
  const [busId, setBusId] = useState('BUS005'); const [bus, setBus] = useState<Data | null>(null);
  const [cameras, setCameras] = useState<Data[]>([]); const [events, setEvents] = useState<Data[]>([]);
  const [sharing, setSharing] = useState(false); const [status, setStatus] = useState('GPS sharing is off.');
  const [direction,setDirection] = useState<'outbound'|'inbound'>('outbound');
  const [doorOpen, setDoorOpen] = useState<boolean | null>(null);
  const [doorReportedAt, setDoorReportedAt] = useState<string | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const lastSent = useRef(0);

  async function login(event: FormEvent) {
    event.preventDefault(); setCredentials(username, password); setError(''); setBusy(true);
    try { const user = await transitRequest<Data>('/api/mobility/session'); setIdentity(user); if (user.bus_id) setBusId(user.bus_id); setPassword(''); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => {
    if (!identity) return;
    let active = true;
    const refresh = () => {
      transitRequest<Data>(`/api/buses/${busId}`).then(data => { if (active) setBus(data); }).catch(e => { if (active) setError(e.message); });
      transitRequest<Data>('/api/mobility/cameras').then(data => { if (active) setCameras((data.cameras ?? []).filter((camera: Data) => camera.bus_id === busId)); }).catch(() => {});
      transitRequest<Data>(`/api/buses/${busId}/safety-status`).then(data => { if (active) setEvents(data.events ?? []); }).catch(() => {});
    };
    refresh(); const timer = window.setInterval(refresh, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [identity, busId]);
  useEffect(() => {
    if (!sharing) return;
    if (!navigator.geolocation) { setError('This browser cannot provide GPS.'); setSharing(false); return; }
    let active = true;
    let registered = false;
    lastSent.current = 0;
    const watch = navigator.geolocation.watchPosition(async position => {
      const now = Date.now(); if (now - lastSent.current < 10000) return;
      lastSent.current = now;
      try {
        if (!registered) {
          await postTransit(`/api/buses/${busId}/session`,{direction,active:true,source:'driver_device'});
          registered = true;
          if (!active) { await postTransit(`/api/buses/${busId}/session`,{direction,active:false,source:'driver_device'}); return; }
        }
        const coords = position.coords;
        await postTransit(`/api/buses/${busId}/location`, { latitude: coords.latitude,
          longitude: coords.longitude, accuracy_m: coords.accuracy,
          heading_deg: coords.heading, speed_kmh: coords.speed == null ? null : coords.speed * 3.6,
          source: 'browser_geolocation' });
        if (active) setStatus(`GPS sent at ${new Date().toLocaleTimeString()} · ±${Math.round(coords.accuracy)} m`);
      } catch (e) { if (active) setError((e as Error).message); }
    }, e => { setStatus(`GPS unavailable: ${e.message}`); setSharing(false); },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 });
    return () => { active = false; navigator.geolocation.clearWatch(watch); if (registered) void postTransit(`/api/buses/${busId}/session`,{direction,active:false,source:'driver_device'}).catch(() => {}); };
  }, [sharing, busId,direction]);

  async function setDoor(open: boolean) {
    setBusy(true); setError('');
    try { await postTransit(`/api/buses/${busId}/door`, { open }); setDoorOpen(open); setDoorReportedAt(new Date().toLocaleTimeString()); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  if (!identity) return <div className="pa-shell dr-shell"><header className="pa-header"><Link to="/passenger" className="pa-brand"><BusFront /> TRANSITOPT <span>DRIVER</span></Link><ThemeToggle variant="compact" /></header><main className="dr-login"><form onSubmit={login}><div className="pa-eyebrow">REGISTERED DRIVER OR ADMIN</div><h1>Bus operations sign in</h1><p>Share a real GPS reading from a permitted device and report door status for your assigned bus.</p><label>Username<input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label><label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>{error && <p role="alert" className="dr-error">{error}</p>}<button className="pa-primary" disabled={busy}>Sign in</button></form></main></div>;

  return <div className="pa-shell dr-shell"><header className="pa-header"><Link to="/driver" className="pa-brand"><BusFront /> TRANSITOPT <span>DRIVER</span></Link><span className="pa-header-label">BUS OPERATIONS · {identity.role.toUpperCase()}</span><div style={{ display: 'flex', alignItems: 'center', gap: 14 }}><ThemeToggle variant="compact" /><Link to="/passenger" className="pa-operator-link">Passenger map →</Link></div></header>
    <main className="dr-content"><div className="pa-eyebrow">ASSIGNED VEHICLE</div><h1>{bus?.registration_number ?? busId}</h1><p className="dr-lead">{busId} · Route {bus?.route_id ?? 'Not assigned'} · {bus?.registration_source === 'illustrative_demo_registration' ? 'Illustrative registration' : 'Operator registered'}</p>
      {bus?.location?.source==='demo_simulation'&&<p className="dr-lead">SIMULATION GPS · These coordinates come from the explicit demo publisher.</p>}
      {identity.role === 'admin' && <label className="dr-field">Select registered bus<input value={busId} disabled={sharing} onChange={e => setBusId(e.target.value.toUpperCase())} /></label>}
      <label className="dr-field">Service direction<select value={direction} disabled={sharing} onChange={e=>setDirection(e.target.value as typeof direction)}><option value="outbound">Outbound · configured stop order</option><option value="inbound">Inbound · reversed stop order</option></select></label>
      {error && <div role="alert" className="dr-error">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
      <div className="dr-grid"><section className="dr-card"><div className="dr-card-icon"><MapPin /></div><h2>Bus GPS</h2><p>{status}</p><strong>{bus?.tracking_status === 'live' ? 'Live GPS' : bus?.tracking_status === 'stale' ? 'Last known position · stale' : 'No bus GPS reported'}</strong><p>{bus?.location ? `${bus.location.latitude.toFixed(5)}, ${bus.location.longitude.toFixed(5)} · ${new Date(bus.location.timestamp).toLocaleTimeString()}` : 'The laptop webcam does not provide location.'}</p><button className="pa-primary" onClick={() => setSharing(value => !value)}>{sharing ? 'Stop GPS sharing' : 'Share device GPS'}</button></section>
        <section className="dr-card"><div className="dr-card-icon"><Camera /></div><h2>Interior camera</h2><p>{cameras.length ? cameras.map(c => `${c.name} · ${c.status.replaceAll('_', ' ')}`).join(', ') : 'No interior camera mapped to this bus.'}</p><strong>Visible people: {bus?.crowding?.fresh ? bus.crowding.visible_people : 'Unavailable'}</strong><p>{bus?.crowding?.fresh ? `${bus.crowding.level} · ${bus.crowding.coverage} coverage` : 'Fresh camera observation unavailable.'}</p><small>Visible people are not verified total occupancy.</small></section>
        <section className="dr-card"><div className="dr-card-icon"><DoorOpen /></div><h2>Door state</h2><p>Report the physical door state. The safety rule also needs a configured zone, repeated detections, and fresh moving GPS.</p><strong>{doorOpen === null ? 'Not reported this session' : doorOpen ? 'Reported open' : 'Reported closed'}</strong><div className="dr-actions"><button disabled={busy} onClick={() => setDoor(true)}>Door open</button><button disabled={busy} onClick={() => setDoor(false)}>Door closed</button></div><p>{doorReportedAt ? `Reported at ${doorReportedAt}. ` : ''}Safety rules use door reports from the past five minutes. Report changes immediately.</p></section>
        <section className="dr-card"><div className="dr-card-icon"><CircleAlert /></div><h2>Safety updates</h2><strong>{events.filter(e => e.status === 'awaiting_review').length} awaiting review</strong>{events.length ? events.slice(0, 3).map(event => <p key={event.id}>{event.category.replaceAll('_', ' ')} · {event.status.replaceAll('_', ' ')} · {new Date(event.timestamp).toLocaleTimeString()}</p>) : <p>No safety reports for this bus.</p>}<small>Head office reviews suspected incidents before resolution.</small></section></div>
      <BusTrafficAdvice bus={bus}/>
      <div className="dr-strip"><Radio size={17} /> Browser GPS updates while this page remains active. Background phone tracking needs a supported native device or dedicated GPS tracker. <ShieldCheck size={17} /> Operator approved service plans appear in the control center.</div>
    </main></div>;
}
