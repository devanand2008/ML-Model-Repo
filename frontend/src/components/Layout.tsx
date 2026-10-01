import { Outlet, NavLink, useLocation } from "react-router-dom";
import {
  Eye, Users, Ship, Package, Layers, Video, Database,
  History, Brain, Activity, Menu, X, Zap, Camera
} from "lucide-react";
import { useState, useEffect } from "react";
import { session } from "../services/api";

const NAV = [
  { to: "/",          icon: Eye,      label: "Home",              color: "text-cyan-400" },
  { to: "/image",     icon: Eye,      label: "Image Analyzer",    color: "text-blue-400" },
  { to: "/human",     icon: Users,    label: "Human Analyzer",    color: "text-purple-400" },
  { to: "/ship",      icon: Ship,     label: "Ship Analyzer",     color: "text-teal-400" },
  { to: "/container", icon: Package,  label: "Container Analyzer",color: "text-orange-400" },
  { to: "/combined",  icon: Layers,   label: "Combined Analyzer", color: "text-pink-400" },
  { to: "/webcam", icon: Camera, label: "Live Camera AI", color: "text-red-400" },
  { to: "/video",     icon: Video,    label: "Video Analyzer",    color: "text-yellow-400" },
  { to: "/models",    icon: Brain,    label: "Model Center",      color: "text-indigo-400" },
  { to: "/history",   icon: History,  label: "History",           color: "text-green-400" },
];

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth >= 768);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const location = useLocation();

  useEffect(() => {
    let active=true;
    const check=()=>session().then(r=>{if(active)setBackendOk(r.ok);}).catch(()=>{if(active)setBackendOk(false);});
    check();
    const timer=window.setInterval(check,10000);
    return ()=>{active=false;window.clearInterval(timer);};
  }, []);

  return (
    <div className="flex min-h-screen animated-bg">
      {/* Sidebar */}
      <aside
        className={`flex flex-col glass border-r border-blue-500/10 transition-all duration-300 ${
          sidebarOpen ? "w-64" : "w-16"
        } shrink-0`}
        style={{ borderRadius: 0 }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-blue-500/10">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 shrink-0">
            <Zap size={18} className="text-white" />
          </div>
          {sidebarOpen && (
            <div className="overflow-hidden">
              <p className="font-bold gradient-text text-sm leading-tight">VisionX AI</p>
              <p className="text-xs text-slate-500 leading-tight">Analyzer Platform</p>
            </div>
          )}
          <button
            aria-label="Toggle navigation" onClick={() => setSidebarOpen(!sidebarOpen)}
            className="ml-auto text-slate-500 hover:text-slate-300 transition-colors"
          >
            {sidebarOpen ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
          {NAV.map(({ to, icon: Icon, label, color }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `nav-link ${isActive ? "active" : ""} justify-${sidebarOpen ? "start" : "center"}`
              }
            >
              <Icon size={18} className={color} />
              {sidebarOpen && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Backend status */}
        <div className={`px-4 py-3 border-t border-blue-500/10 flex items-center gap-2 ${!sidebarOpen && "justify-center"}`}>
          <span
            className={`w-2 h-2 rounded-full pulse-dot ${
              backendOk === null ? "bg-yellow-400" :
              backendOk ? "bg-green-400" : "bg-red-400"
            }`}
          />
          {sidebarOpen && (
            <span className="text-xs text-slate-500">
              {backendOk === null ? "Connecting…" : backendOk ? "Backend online" : "Backend offline"}
            </span>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
