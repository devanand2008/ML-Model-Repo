import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Activity, ArrowUpRight, BarChart3, Bell, BrainCircuit, BusFront, Camera, ChevronDown, ChevronRight, CircleHelp, Database, FlaskConical, Gauge, GitBranch, LayoutDashboard, MapPin, Menu, Network, Settings2, ShieldCheck, Sparkles, Video, X } from 'lucide-react';
import { session } from '../../services/api';
import { TransitProvider } from './Shared';
import ThemeToggle from '../ThemeToggle';
import '../../transit.css';

const NAV = [
  { path: '/status', label: 'Check app readiness', icon: Activity },
  { path: '/ml', label: 'Camera ML workspace', icon: BrainCircuit },
  { path: '/speed', label: 'Bus speed & congestion', icon: Gauge },
  { path: '/rag', label: 'Route RAG assistant', icon: BrainCircuit },
  { path: '/admin', label: 'Overview', icon: LayoutDashboard }, { path: '/fleet', label: 'Live fleet & GPS', icon: BusFront },
  { path: '/safety', label: 'Safety alerts', icon: ShieldCheck }, { path: '/passenger', label: 'Passenger navigation', icon: MapPin },
  { path: '/driver', label: 'Driver dashboard', icon: Gauge }, { path: '/cctv', label: 'CCTV intelligence', icon: Camera },
  { path: '/demand', label: 'Passenger demand', icon: BarChart3 }, { path: '/optimization', label: 'Route optimization', icon: GitBranch },
  { path: '/network', label: 'Transit network', icon: Network }, { path: '/simulator', label: 'What-if simulator', icon: FlaskConical },
  { path: '/recommendations', label: 'Recommendations', icon: ShieldCheck }, { path: '/analytics', label: 'Analytics & reports', icon: Activity },
  { path: '/settings', label: 'Data & settings', icon: Settings2 },
  { path: '/accounts', label: 'Users & access', icon: ShieldCheck },
  { path: '/record-demo', label: 'Record app demonstration', icon: Video },
];
const LEGACY = [{ path: '/vision-overview', label: 'VisionX overview' }, { path: '/webcam', label: 'Live camera & skeleton' }, { path: '/image', label: 'Image detection' }, { path: '/human', label: 'Human detection' }, { path: '/video', label: 'Video analyzer' }, { path: '/ship', label: 'Ship analyzer' }, { path: '/container', label: 'Container analyzer' }, { path: '/combined', label: 'Combined analyzer' }, { path: '/models', label: 'Model Center' }, { path: '/history', label: 'Detection history' }];
export default function TransitLayout() {
  const [open, setOpen] = useState(false); const [visionOpen, setVisionOpen] = useState(false); const [online, setOnline] = useState<boolean | null>(null);
  const [navQuery,setNavQuery]=useState('');
  const location = useLocation();
  const cameraWorkspace=['/ml','/webcam','/cctv','/models','/fleet','/safety','/speed','/rag','/status'].includes(location.pathname);
  useEffect(() => { setOpen(false);setNavQuery(''); }, [location.pathname]);
  useEffect(() => {
    let active = true; const check = () => session().then(response => { if (active) setOnline(response.ok); }).catch(() => { if (active) setOnline(false); });
    check(); const timer = window.setInterval(check, 30000); return () => { active = false; window.clearInterval(timer); };
  }, []);
  const current = NAV.find(item => item.path === location.pathname)?.label ?? LEGACY.find(item => item.path === location.pathname)?.label ?? 'Project overview';
  return <TransitProvider><div className="to-shell">
    {open && <button aria-label="Close navigation backdrop" className="to-sidebar-backdrop" onClick={() => setOpen(false)} />}
    <aside className={`to-sidebar ${open ? 'open' : ''}`}>
      <Link to="/" className="to-brand"><div className="to-brand-symbol"><BusFront size={23} /><i /></div><div><strong>TRANSITOPT<span> AI</span></strong><small>INTELLIGENT MOBILITY</small></div></Link>
      <div className="to-workspace"><span className="to-workspace-icon"><Network size={17} /></span><div><strong>Salem, Tamil Nadu</strong><small>{cameraWorkspace?'Camera ML workspace':'Simulation workspace'}</small></div><ChevronDown size={14} /></div>
      <div className="to-nav-label">CONTROL CENTER</div>
      <input className="to-module-search" aria-label="Find a module" placeholder="Find camera, speed, routes..." value={navQuery} onChange={e=>setNavQuery(e.target.value)}/>
      <nav aria-label="Main navigation">{NAV.filter(item=>item.label.toLowerCase().includes(navQuery.trim().toLowerCase())).map(({ path, label, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} className={({ isActive }) => `to-nav-item ${isActive ? 'active' : ''}`}><Icon size={18} /><span>{label}</span><ChevronRight size={12} /></NavLink>)}</nav>
      <div className="to-nav-label">EXISTING ML PLATFORM</div><button className="to-nav-item to-legacy-toggle" aria-expanded={visionOpen} onClick={() => setVisionOpen(value => !value)}><BrainCircuit size={18} /><span>VisionX tools</span><ChevronDown size={13} /></button>
      {(visionOpen||navQuery.trim()) && <nav className="to-legacy-nav" aria-label="Existing vision tools">{LEGACY.filter(item=>item.label.toLowerCase().includes(navQuery.trim().toLowerCase())).map(item => <NavLink key={item.path} to={item.path}>{item.label}</NavLink>)}</nav>}
      <div className="to-sidebar-bottom"><div className="to-demo-card"><Sparkles size={19} /><strong>Human decisions.<br />AI-powered insight.</strong><p>Forecast, compare and approve service changes in simulation.</p><Link to="/project">Explore the project <ArrowUpRight size={14} /></Link></div><div className="to-system"><span className={online ? 'online' : 'offline'} /><span>{online === null ? 'Connecting to backend' : online ? 'API connected' : 'Backend disconnected'}</span><small>v2.1</small></div></div>
    </aside>
    <div className="to-main"><header className="to-topbar"><button className="to-mobile-menu" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={21} /></button><div className="to-breadcrumb">Control center <ChevronRight size={13} /><strong>{current}</strong></div><div className="to-topbar-right"><span className="to-demo-indicator"><i />{cameraWorkspace?'CAMERA ML':'SYNTHETIC DEMO'}</span><ThemeToggle variant="compact" /><Link to="/recommendations" aria-label="Open recommendation reviews" className="to-topbar-icon"><Bell size={18} /></Link><Link to="/project" aria-label="Project guide" className="to-topbar-icon"><CircleHelp size={18} /></Link><span className="to-operator-avatar">OP</span><span className="to-operator"><strong>Camera & fleet operator</strong><small>ML observations + simulation</small></span></div></header>
      <div className="to-content"><Outlet /></div><footer className="to-footer"><span>TRANSITOPT AI · Predict Demand · Analyze Traffic · Optimize Routes · Improve Service</span><span>Illustrative network · Simulation only</span></footer>
    </div>
  </div></TransitProvider>;
}
