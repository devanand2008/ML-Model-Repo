import { Detection, AnalysisResult } from "../services/api";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend
} from "recharts";
import { Download, CheckCircle, Clock, Cpu, ImageIcon } from "lucide-react";

// ── Colours per class ──────────────────────────────────────────────
const CHART_COLORS = ["#00d4ff","#3b82f6","#8b5cf6","#10b981","#f59e0b","#ef4444","#06b6d4","#a78bfa","#34d399","#fbbf24"];

function classColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff;
  return CHART_COLORS[h % CHART_COLORS.length];
}

// ── Confidence bar ─────────────────────────────────────────────────
function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "#10b981" : pct >= 50 ? "#3b82f6" : "#f59e0b";
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="progress-bar flex-1"><div className="progress-bar-fill" style={{ width: `${pct}%`, background: color }} /></div>
      <span className="text-xs font-mono text-slate-400 w-8 text-right">{pct}%</span>
    </div>
  );
}

// ── Detection Table ─────────────────────────────────────────────────
export function DetectionTable({ detections }: { detections: Detection[] }) {
  if (!detections.length) return <p className="text-slate-500 text-sm text-center py-6">No detections</p>;
  return (
    <div className="overflow-x-auto">
      <table className="detection-table">
        <thead>
          <tr>
            <th>ID</th><th>Object</th><th>Confidence</th>
            <th>X</th><th>Y</th><th>Width</th><th>Height</th>
            {detections.some(d => d.position) && <th>Position</th>}
            {detections.some(d => d.track_id != null) && <th>Track ID</th>}
          </tr>
        </thead>
        <tbody>
          {detections.map((d) => (
            <tr key={d.id}>
              <td className="text-slate-500 font-mono text-xs">#{d.id}</td>
              <td>
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: classColor(d.class) }} />
                  <span className="font-medium capitalize">{d.class}</span>
                </span>
              </td>
              <td className="min-w-28"><ConfBar value={d.confidence} /></td>
              <td className="font-mono text-xs text-slate-400">{d.bbox[0].toFixed(0)}</td>
              <td className="font-mono text-xs text-slate-400">{d.bbox[1].toFixed(0)}</td>
              <td className="font-mono text-xs text-slate-400">{d.bbox[2].toFixed(0)}</td>
              <td className="font-mono text-xs text-slate-400">{d.bbox[3].toFixed(0)}</td>
              {d.position && <td className="text-xs text-slate-400 capitalize">{d.position}</td>}
              {d.track_id != null && <td className="font-mono text-xs text-cyan-400">#{d.track_id}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Object Count Chart ─────────────────────────────────────────────
export function CountChart({ counts }: { counts: Record<string, number> }) {
  const data = Object.entries(counts).map(([name, count]) => ({ name: name.charAt(0).toUpperCase() + name.slice(1), count, fill: classColor(name) }));
  if (!data.length) return null;
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
        <XAxis dataKey="name" tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip
          contentStyle={{ background: "rgba(10,22,40,0.95)", border: "1px solid rgba(59,130,246,0.3)", borderRadius: "8px", color: "#e2e8f0" }}
          cursor={{ fill: "rgba(59,130,246,0.05)" }}
        />
        <Bar dataKey="count" radius={[4, 4, 0, 0]}>
          {data.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Pie distribution ────────────────────────────────────────────────
export function DistributionPie({ counts }: { counts: Record<string, number> }) {
  const data = Object.entries(counts).map(([name, value]) => ({ name: name.charAt(0).toUpperCase() + name.slice(1), value }));
  if (!data.length) return null;
  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie data={data} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
          {data.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
        </Pie>
        <Legend wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }} />
        <Tooltip contentStyle={{ background: "rgba(10,22,40,0.95)", border: "1px solid rgba(59,130,246,0.3)", borderRadius: "8px", color: "#e2e8f0" }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ── Annotated image panel ──────────────────────────────────────────
export function AnnotatedImage({ src, onDownload }: { src: string; onDownload: () => void }) {
  return (
    <div className="relative">
      <img src={src} alt="Annotated result" className="w-full rounded-xl border border-blue-500/20 object-contain max-h-[500px]" />
      <button onClick={onDownload} className="absolute top-3 right-3 btn-secondary flex items-center gap-2 py-1.5 px-3 text-xs">
        <Download size={13} /> Download
      </button>
    </div>
  );
}

// ── Summary stat strip ─────────────────────────────────────────────
export function SummaryStats({ result }: { result: AnalysisResult }) {
  const stats = [
    { label: "Total Objects", value: result.detections.length, icon: CheckCircle, color: "text-cyan-400" },
    { label: "Processing",    value: `${(result.processing_time * 1000).toFixed(0)} ms`, icon: Clock, color: "text-blue-400" },
    { label: "Resolution",    value: result.image_width ? `${result.image_width}×${result.image_height}` : "—", icon: ImageIcon, color: "text-purple-400" },
    { label: "Model",         value: result.model_info?.name?.split(" ")[0] ?? "YOLO", icon: Cpu, color: "text-green-400" },
  ];
  const exportReport = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href=url;a.download='visionx-report.json';a.click();URL.revokeObjectURL(url);
  };
  return (<div className="space-y-3"><button onClick={exportReport} className="btn-secondary text-xs">Export report (JSON)</button>
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map(({ label, value, icon: Icon, color }) => (
        <div key={label} className="stat-card">
          <div className="flex items-center gap-2 mb-1">
            <Icon size={14} className={color} />
            <span className="text-xs text-slate-500 font-medium">{label}</span>
          </div>
          <p className="text-lg font-bold text-slate-200">{value}</p>
        </div>
      ))}
    </div>
    <details className="glass p-4"><summary className="text-sm cursor-pointer">Confidence distribution ? {Object.keys(result.counts).length} categories</summary><CountChart counts={Object.fromEntries([10,30,50,70,90].map(low=>[`${low}-${Math.min(low+20,100)}%`,result.detections.filter(d=>d.confidence*100>=low && (d.confidence*100<low+20 || low===90)).length]))}/></details>
    </div>
  );
}

// ── Confidence slider ──────────────────────────────────────────────
export function ConfidenceSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-slate-500">
        <span>Confidence Threshold</span>
        <span className="font-mono text-cyan-400">{(value * 100).toFixed(0)}%</span>
      </div>
      <input
        aria-label="Confidence threshold" type="range" min={0.1} max={0.95} step={0.05}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      <div className="flex justify-between text-xs text-slate-600">
        <span>10%</span><span>95%</span>
      </div>
    </div>
  );
}

// ── Loading spinner ────────────────────────────────────────────────
export function Spinner({ label = "Analyzing…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4">
      <div className="w-12 h-12 rounded-full border-2 border-blue-500/20 border-t-cyan-400 animate-spin" />
      <p className="text-slate-400 text-sm animate-pulse">{label}</p>
    </div>
  );
}

// ── Error banner ───────────────────────────────────────────────────
export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
      <span className="text-red-400 text-sm flex-1">{message}</span>
      <button onClick={onDismiss} className="text-red-400 hover:text-red-300"><span>✕</span></button>
    </div>
  );
}

// ── Page header ────────────────────────────────────────────────────
export function PageHeader({ icon: Icon, title, subtitle, iconColor = "text-cyan-400", badge }: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  subtitle: string;
  iconColor?: string;
  badge?: string;
}) {
  return (
    <div className="flex items-start gap-4 p-6 pb-0">
      <div className="w-12 h-12 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
        <Icon size={24} className={iconColor} />
      </div>
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold gradient-text">{title}</h1>
          {badge && <span className="badge badge-cyan">{badge}</span>}
        </div>
        <p className="text-slate-500 text-sm mt-0.5">{subtitle}</p>
      </div>
    </div>
  );
}
