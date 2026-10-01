import { useDefaultConfidence } from "../hooks/useDefaultConfidence";
import { useState } from "react";
import { Layers, Users, Ship, Package, Truck } from "lucide-react";
import { api } from "../services/api";
import { useAnalyzer, downloadBase64 } from "../hooks/useAnalyzer";
import { ImageDropzone } from "../components/Dropzone";
import {
  PageHeader, ConfidenceSlider, Spinner, ErrorBanner,
  DetectionTable, CountChart, DistributionPie, AnnotatedImage, SummaryStats,
} from "../components/ResultsPanel";

const CATEGORY_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  people: Users,
  ships: Ship,
  containers: Package,
  trucks: Truck,
  other: Layers,
};

export default function CombinedAnalyzerPage() {
  const [conditionMode,setConditionMode] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [conf, setConf] = useDefaultConfidence("general");
  const { loading, result, error, run, setError, setResult } = useAnalyzer(api.analyzeCombined, conf);

  const categories = result ? [
    { key: "people",     value: result.people ?? 0,     color: "text-purple-400" },
    { key: "ships",      value: result.ships ?? 0,      color: "text-teal-400"   },
    { key: "containers", value: result.condition?.total_containers === null ? "N/A" : result.containers ?? 0, color: "text-orange-400" },
    { key: "trucks",     value: result.trucks ?? 0,     color: "text-yellow-400" },
    { key: "other",      value: result.other ?? 0,      color: "text-slate-400"  },
  ] : [];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={Layers}
        title="Combined Port Analyzer"
        subtitle="Run all detection models simultaneously — people, ships, containers, trucks, and more"
        iconColor="text-pink-400"
        badge="All Models"
      />

      {result?.warnings?.map(w => <div key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</div>)}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="glass p-5 space-y-4">
            <h2 className="font-semibold text-slate-300 text-sm">Upload Port / Ship / Yard Image</h2>
            <ImageDropzone onFile={f=>{setFile(f);setResult(null);}} label="Drop a port or maritime scene" />
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={conditionMode} onChange={e=>setConditionMode(e.target.checked)}/>Classify container condition (requires custom weights)</label>
            <ConfidenceSlider value={conf} onChange={setConf} />

            <div className="p-3 rounded-xl bg-blue-500/5 border border-blue-500/10 text-xs text-slate-500 space-y-1">
              <p className="font-medium text-slate-400">Model pipeline:</p>
              {["General Object Detector","Human Detector","Ship Detector","Container Detector"].map(m => (
                <div key={m} className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  {m}
                </div>
              ))}
            </div>

            <button onClick={() => file && run(file, conf, conditionMode)} disabled={!file || loading} className="btn-primary w-full flex items-center justify-center gap-2">
              <Layers size={16} /> Run Full Port Analysis
            </button>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {loading && <div className="glass p-5"><Spinner label="Running all detectors…" /></div>}

          {!loading && result && (
            <>
              {/* Category overview */}
              <div className="glass p-5 bg-gradient-to-br from-pink-500/10 to-purple-500/5">
                <h2 className="font-semibold text-slate-300 text-sm mb-4">Total Objects Detected</h2>
                <div className="grid grid-cols-5 gap-3">
                  {categories.map(({ key, value, color }) => {
                    const Icon = CATEGORY_ICONS[key] || Layers;
                    return (
                      <div key={key} className="text-center">
                        <div className="w-10 h-10 rounded-xl bg-slate-800/60 flex items-center justify-center mx-auto mb-2">
                          <Icon size={18} className={color} />
                        </div>
                        <p className={`text-2xl font-extrabold ${color}`}>{value}</p>
                        <p className="text-xs text-slate-500 capitalize">{key}</p>
                      </div>
                    );
                  })}
                </div>
              </div>

              <SummaryStats result={result} />
              {conditionMode && <div className="glass p-4 text-sm">{result.condition?.condition_model_active ? `Good: ${result.condition.good} ? Damaged: ${result.condition.damaged} ? Damaged rate: ${result.condition.damaged_pct ?? 0}%` : "Container condition model unavailable."}</div>}

              {result.annotated_image && (
                <div className="glass p-5">
                  <h2 className="font-semibold text-slate-300 text-sm mb-3">Annotated Scene</h2>
                  <AnnotatedImage src={result.annotated_image} onDownload={() => downloadBase64(result.annotated_image!, "visionx-combined-result.jpg")} />
                </div>
              )}

              <div className="glass p-5 grid grid-cols-2 gap-6">
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wider">Object Counts</h3>
                  <CountChart counts={result.counts} />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wider">Distribution</h3>
                  <DistributionPie counts={result.counts} />
                </div>
              </div>

              <div className="glass p-5">
                <h2 className="font-semibold text-slate-300 text-sm mb-3">All Detections</h2>
                <DetectionTable detections={result.detections} />
              </div>
            </>
          )}

          {!loading && !result && (
            <div className="glass flex flex-col items-center justify-center py-20 text-center">
              <Layers size={48} className="text-pink-500/30 mb-4" />
              <p className="text-slate-500">Upload a port scene to run all detectors simultaneously</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
