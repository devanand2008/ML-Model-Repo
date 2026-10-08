import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BrainCircuit, BusFront, Camera, MapPin, ShieldCheck, Smartphone, Users } from 'lucide-react';
import { transitRequest, type Data } from '../../services/transit';
import ThemeToggle from '../../components/ThemeToggle';
import './ml.css';

export default function AppHomePage() {
  const [feed, setFeed] = useState<Data | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true, pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try { const data = await transitRequest('/api/public/traffic/feed'); if (active) { setFeed(data); setError(''); } }
      catch (e) { if (active) setError((e as Error).message); }
      finally { pending = false; }
    }
    refresh(); const timer = window.setInterval(refresh, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const live = (feed?.cameras ?? []).filter((c: Data) => c.observation?.live).length;
  return <div className="ml-home">
    <header className="ml-app-header"><Link to="/" className="ml-logo"><BrainCircuit />TRANSITOPT <span>AI</span></Link><nav aria-label="App navigation"><Link to="/passenger">Travel</Link><Link to="/ml">Camera ML</Link><Link to="/admin">Admin</Link><Link to="/connect"><Smartphone size={16} />Connect phone</Link><ThemeToggle variant="compact" /></nav></header>
    <main className="ml-home-content"><div className="ml-hero"><div><span className="ml-eyebrow">ONE APP · TWO CAMERA ML USES</span><h1>See the traffic.<br /><em>Choose your next move.</em></h1><p>Road cameras detect vehicles. Bus cameras detect people. Live model observations help you compare routes and see visible bus crowding.</p><div className="ml-actions"><Link className="ml-primary" to="/passenger"><MapPin size={18} />Plan my journey<ArrowRight size={17} /></Link><Link className="ml-secondary" to="/ml"><Camera size={18} />Open camera ML</Link></div><small>{live} road camera{live===1?'':'s'} analyzing live · {feed?.alerts?.length ?? 0} current traffic alerts</small></div><div className="ml-flow" aria-label="Camera data flow"><div><Camera /><strong>Laptop or phone camera</strong><span>Authorized road or bus view</span></div><i /><div><BrainCircuit /><strong>YOLO detection + scene forecast</strong><span>Vehicles outside · people inside</span></div><i /><div><MapPin /><strong>Passenger route intelligence</strong><span>Traffic alerts · road alternatives · crowding</span></div></div></div>
      <div className="ml-role-grid"><Link to="/passenger"><MapPin /><h2>Passenger</h2><p>Choose your starting point and destination. Receive traffic alerts on your route and compare an alternative.</p><span>Start a journey <ArrowRight size={16} /></span></Link><Link to="/ml"><ShieldCheck /><h2>Admin & camera operator</h2><p>Choose road traffic or bus crowd detection, connect a camera, and inspect the active ML models.</p><span>Open ML workspace <ArrowRight size={16} /></span></Link><Link to="/driver"><BusFront /><h2>Bus driver</h2><p>Share your bus GPS, declare the service direction, and check crowding and safety signals.</p><span>Open assigned bus <ArrowRight size={16} /></span></Link></div>
      <section className="ml-feed"><div className="ml-section-heading"><div><span className="ml-eyebrow">GET STARTED</span><h2>Choose what you want to do</h2></div></div><div className="ml-actions"><Link className="ml-secondary" to="/passenger">1. Click start and destination</Link><Link className="ml-secondary" to="/speed">2. Check bus speed</Link><Link className="ml-secondary" to="/rag">3. Explain route choices</Link><Link className="ml-secondary" to="/status">Check app readiness</Link></div><p>On the map, click two places to load blue road alternatives. For live ML, choose your camera type, allow access, then start detection.</p></section><section className="ml-feed"><div className="ml-section-heading"><div><span className="ml-eyebrow">SHARED LIVE INTELLIGENCE</span><h2>Traffic updates for everyone</h2></div><span>Refreshes every 5 seconds</span></div>{error ? <p role="alert">Cannot load camera updates: {error}</p> : !feed ? <p role="status">Connecting to the ML service…</p> : feed.alerts?.length ? <div className="ml-alert-grid">{feed.alerts.map((a: Data) => <article key={a.id}><Camera /><div><strong>{a.camera_name}</strong><p>{a.message}</p><small>{a.coordinate_source==='illustrative_demo_coordinate'?'Approximate demo location':'Configured camera location'} · {new Date(a.timestamp).toLocaleTimeString()}{a.prediction?.available ? ` · next-minute score ${a.prediction.predicted_score}/100` : ''}</small><Link to="/passenger">Check your route <ArrowRight size={14} /></Link></div></article>)}</div> : <div className="ml-empty"><Users /><p>{live ? 'No active camera reports high vehicle pressure.' : 'Start a road camera in the ML workspace to share live traffic updates.'}<small>Unobserved roads have unknown traffic. Camera footage remains in the operator workspace.</small></p></div>}</section>
      <footer>YOLO camera detection · Live scene-pressure learning · Road graph routing · Separate bus crowd observations</footer>
    </main>
  </div>;
}
