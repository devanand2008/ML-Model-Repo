import { useState, useEffect } from "react";
import { History, Trash2, Eye, Filter } from "lucide-react";
import { api, HistoryItem, AnalysisResult } from "../services/api";
import { PageHeader, ErrorBanner, Spinner, DetectionTable, CountChart } from "../components/ResultsPanel";

const ANALYZER_LABELS: Record<string, string> = {
  image: "Image", human: "Human", ship: "Ship",
  container: "Container", combined: "Combined", video: "Video",
};
const BADGE_COLORS: Record<string, string> = {
  image: "badge-blue", human: "badge-purple", ship: "badge-cyan",
  container: "badge-orange", combined: "badge-green", video: "badge-orange",
};

export default function HistoryPage() {
  const [detail,setDetail] = useState<AnalysisResult|null>(null);
  const [items,    setItems]    = useState<HistoryItem[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [filter,   setFilter]   = useState("all");

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.getHistory(100, 0, filter === "all" ? undefined : filter);
      setItems(res.items);
    } catch (e: any) { setError(e?.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const del = async (id: number) => {
    if (!confirm("Delete this analysis record?")) return;
    try {await api.deleteAnalysis(id);await load();} catch(e:any) {setError(e.message);}
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <PageHeader icon={History} title="Analysis History" subtitle="Previous analyses with results, file names, and processing details" iconColor="text-green-400" />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {detail&&<div className="glass p-4"><button className="btn-secondary mb-3" onClick={()=>setDetail(null)}>Close details</button><DetectionTable detections={detail.detections||[]}/></div>}
      {items.length>0&&<details className="glass p-4"><summary>Recent processing times (milliseconds)</summary><CountChart counts={Object.fromEntries(items.slice(0,10).map(i=>[`#${i.id}`,Math.round(i.processing_time*1000)]))}/></details>}
      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter size={14} className="text-slate-500" />
        {["all","image","human","ship","container","combined","video"].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              filter === f
                ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                : "text-slate-500 hover:text-slate-300 border border-transparent"
            }`}
          >
            {f === "all" ? "All" : ANALYZER_LABELS[f] ?? f}
          </button>
        ))}
        <button onClick={load} className="ml-auto btn-secondary text-xs py-1.5 px-3">Refresh</button>
      </div>

      {loading ? (
        <div className="glass p-5"><Spinner label="Loading history…" /></div>
      ) : items.length === 0 ? (
        <div className="glass flex flex-col items-center justify-center py-20 text-center">
          <History size={48} className="text-green-500/20 mb-4" />
          <p className="text-slate-500">No analysis history yet.</p>
          <p className="text-slate-600 text-sm">Run an analysis to see results here.</p>
        </div>
      ) : (
        <div className="glass overflow-x-auto">
          <table className="detection-table w-full">
            <thead>
              <tr>
                <th>ID</th>
                <th>Analyzer</th>
                <th>File</th>
                <th>Objects</th>
                <th>Processing</th>
                <th>Resolution</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr key={item.id}>
                  <td className="font-mono text-xs text-slate-500">#{item.id}</td>
                  <td>
                    <span className={`badge ${BADGE_COLORS[item.analyzer_type] ?? "badge-blue"}`}>
                      {ANALYZER_LABELS[item.analyzer_type] ?? item.analyzer_type}
                    </span>
                  </td>
                  <td className="max-w-32 truncate text-slate-400 text-xs" title={item.input_filename}>
                    {item.input_filename ?? "—"}
                  </td>
                  <td className="font-bold text-cyan-400">{item.total_objects}</td>
                  <td className="font-mono text-xs text-slate-400">
                    {item.processing_time ? `${(item.processing_time * 1000).toFixed(0)} ms` : "—"}
                  </td>
                  <td className="font-mono text-xs text-slate-500">
                    {item.image_width ? `${item.image_width}×${item.image_height}` : "—"}
                  </td>
                  <td className="text-xs text-slate-500">
                    {item.created_at ? new Date(item.created_at).toLocaleString() : "—"}
                  </td>
                  <td>
                    <button aria-label={`View analysis ${item.id}`} className="mr-3 text-cyan-400" onClick={async()=>{try{setDetail((await api.getAnalysis(item.id)).results);}catch(e:any){setError(e.message);}}}><Eye size={14}/></button>
                    <button aria-label={`Delete analysis ${item.id}`} onClick={() => del(item.id)} className="text-slate-600 hover:text-red-400 transition-colors">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
