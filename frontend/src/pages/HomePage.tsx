import { useNavigate } from "react-router-dom";
import { Eye, Users, Ship, Package, Layers, Video, Brain, ArrowRight, Zap, BarChart2, Shield } from "lucide-react";

const MODULES = [
  {
    to: "/image",
    icon: Eye,
    title: "Image Analyzer",
    desc: "General object detection with 80-class COCO model. Bounding boxes, confidence scores, and object counting.",
    badge: "80 Classes",
    badgeClass: "badge-blue",
    iconBg: "from-blue-500 to-cyan-500",
    gradient: "from-blue-500/10 to-cyan-500/5",
  },
  {
    to: "/human",
    icon: Users,
    title: "Human Analyzer",
    desc: "Detect people, count individuals, estimate positions, and optionally run pose estimation with 17 keypoints.",
    badge: "Pose Mode",
    badgeClass: "badge-purple",
    iconBg: "from-purple-500 to-pink-500",
    gradient: "from-purple-500/10 to-pink-500/5",
  },
  {
    to: "/ship",
    icon: Ship,
    title: "Ship Analyzer",
    desc: "Maritime vessel detection for harbor, port, satellite, and drone imagery. Ship type classification.",
    badge: "Custom types optional",
    badgeClass: "badge-cyan",
    iconBg: "from-teal-500 to-cyan-500",
    gradient: "from-teal-500/10 to-cyan-500/5",
  },
  {
    to: "/container",
    icon: Package,
    title: "Container Analyzer",
    desc: "Detect shipping containers in port/yard images. Optional damage condition classification.",
    badge: "Condition AI",
    badgeClass: "badge-orange",
    iconBg: "from-orange-500 to-amber-500",
    gradient: "from-orange-500/10 to-amber-500/5",
  },
  {
    to: "/combined",
    icon: Layers,
    title: "Combined Port Analyzer",
    desc: "Run all detectors simultaneously on a single image — people, ships, containers, trucks, and more.",
    badge: "All Models",
    badgeClass: "badge-green",
    iconBg: "from-green-500 to-emerald-500",
    gradient: "from-green-500/10 to-emerald-500/5",
  },
  {
    to: "/video",
    icon: Video,
    title: "Video Analyzer",
    desc: "Frame-by-frame object detection and tracking. Upload MP4/AVI/MOV files and download annotated output.",
    badge: "Tracking",
    badgeClass: "badge-cyan",
    iconBg: "from-yellow-500 to-orange-500",
    gradient: "from-yellow-500/10 to-orange-500/5",
  },
];

const FEATURES = [
  { icon: Zap,      title: "YOLO26 Powered",      desc: "State-of-the-art real-time detection" },
  { icon: BarChart2, title: "Analytics Dashboard", desc: "Charts, counts, and confidence scores" },
  { icon: Shield,   title: "Secure & Private",     desc: "Images stay in memory; video files expire" },
];

export default function HomePage() {
  const navigate = useNavigate();
  return (
    <div className="p-6 space-y-8 max-w-6xl mx-auto">
      {/* Hero */}
      <div className="text-center py-10 space-y-4">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass border border-cyan-500/20 text-cyan-400 text-sm font-medium mb-4">
          <span className="w-2 h-2 rounded-full bg-cyan-400 pulse-dot" />
          AI Computer Vision Platform
        </div>
        <h1 className="text-5xl font-extrabold gradient-text leading-tight">
          VisionX AI Analyzer
        </h1>
        <p className="text-slate-400 text-lg max-w-2xl mx-auto leading-relaxed">
          Local-first computer vision platform for port monitoring, maritime surveillance, human detection,
          and container inspection — powered by YOLO26.
        </p>
        <div className="flex justify-center gap-3 pt-2">
          <button onClick={() => navigate("/combined")} className="btn-primary flex items-center gap-2 text-base px-6 py-3">
            <Layers size={18} /> Launch Combined Analyzer
          </button>
          <button onClick={() => navigate("/webcam")} className="btn-secondary flex items-center gap-2 text-base px-6 py-3">
            <Eye size={18} /> Open Webcam
          </button>
        </div>
      </div>

      {/* Feature pills */}
      <div className="grid grid-cols-3 gap-4">
        {FEATURES.map(({ icon: Icon, title, desc }) => (
          <div key={title} className="glass glass-hover p-5 flex gap-4">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center shrink-0">
              <Icon size={20} className="text-blue-400" />
            </div>
            <div>
              <p className="font-semibold text-slate-200 text-sm">{title}</p>
              <p className="text-slate-500 text-xs mt-0.5">{desc}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Module cards */}
      <div>
        <h2 className="text-lg font-bold text-slate-300 mb-4">Choose an Analyzer</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {MODULES.map(({ to, icon: Icon, title, desc, badge, badgeClass, iconBg, gradient }) => (
            <button
              key={to}
              onClick={() => navigate(to)}
              className={`glass glass-hover p-5 text-left group bg-gradient-to-br ${gradient}`}
            >
              <div className="flex items-start justify-between mb-4">
                <div className={`w-11 h-11 rounded-2xl bg-gradient-to-br ${iconBg} flex items-center justify-center shadow-lg`}>
                  <Icon size={20} className="text-white" />
                </div>
                <span className={`badge ${badgeClass}`}>{badge}</span>
              </div>
              <h3 className="font-bold text-slate-200 mb-1.5">{title}</h3>
              <p className="text-slate-500 text-xs leading-relaxed mb-4">{desc}</p>
              <div className="flex items-center text-blue-400 text-xs font-medium gap-1 group-hover:gap-2 transition-all">
                Open Analyzer <ArrowRight size={13} />
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Bottom links */}
      <div className="flex gap-4 justify-center pb-4">
        <button onClick={() => navigate("/models")} className="btn-secondary flex items-center gap-2 text-sm">
          <Brain size={15} /> Model Center
        </button>
        <button onClick={() => navigate("/history")} className="btn-secondary flex items-center gap-2 text-sm">
          View History
        </button>
      </div>
    </div>
  );
}
