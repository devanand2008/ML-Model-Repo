import { useDefaultConfidence } from "../hooks/useDefaultConfidence";
import { useState } from "react";
import { Package, AlertTriangle, CheckCircle } from "lucide-react";
import { api } from "../services/api";
import { useAnalyzer, downloadBase64 } from "../hooks/useAnalyzer";
import { ImageDropzone } from "../components/Dropzone";
import {
  PageHeader, ConfidenceSlider, Spinner, ErrorBanner,
  SummaryStats, DetectionTable, AnnotatedImage,
} from "../components/ResultsPanel";

export default function ContainerAnalyzerPage() {
  const [file,    setFile]   = useState<File | null>(null);
  const [conf,    setConf]   = useDefaultConfidence("container");
  const [condMode, setCond]  = useState(false);
  const { loading, result, error, run, setError, setResult } = useAnalyzer(api.analyzeContainer, conf);

  const cond = result?.condition;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader icon={Package} title="Container Analyzer" subtitle="Detect shipping containers, count them, and classify damage condition" iconColor="text-orange-400" badge="Condition AI" />

      {result?.warnings?.map(w => <div key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</div>)}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="glass p-5 space-y-4">
            <ImageDropzone onFile={f=>{setFile(f);setResult(null);}} label="Drop a container yard / port image" />
            <ConfidenceSlider value={conf} onChange={setConf} />

            <label className="flex items-start gap-3 p-3 rounded-xl border border-orange-500/20 bg-orange-500/5 cursor-pointer hover:border-orange-500/40 transition-colors">
              <input type="checkbox" checked={condMode} onChange={e => setCond(e.target.checked)} className="mt-0.5 accent-orange-500" />
              <div>
                <p className="text-sm text-slate-300 font-medium">Condition Detection Mode</p>
                <p className="text-xs text-slate-500 mt-0.5">Classify containers as <em>Good</em> or <em>Damaged</em>. Requires condition model to be uploaded.</p>
              </div>
            </label>

            <button onClick={() => file && run(file, conf, condMode)} disabled={!file || loading} className="btn-primary w-full">
              {loading ? "Analyzing…" : "Analyze Containers"}
            </button>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {loading && <div className="glass p-5"><Spinner label="Counting containers…" /></div>}

          {!loading && result && (
            <>
              {/* Count hero */}
              <div className="glass p-6 bg-gradient-to-br from-orange-500/10 to-amber-500/5">
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div>
                    <p className="text-4xl font-extrabold text-orange-400">{result.detections.length}</p>
                    <p className="text-slate-500 text-xs mt-1">Total Containers</p>
                  </div>
                  {cond?.condition_model_active ? (
                    <>
                      <div>
                        <p className="text-4xl font-extrabold text-green-400">{cond.good ?? 0}</p>
                        <p className="text-slate-500 text-xs mt-1">Good Containers</p>
                      </div>
                      <div>
                        <p className="text-4xl font-extrabold text-red-400">{cond.damaged ?? 0}</p>
                        <p className="text-slate-500 text-xs mt-1">Damaged Containers</p>
                      </div>
                    </>
                  ) : (
                    <div className="col-span-2 flex items-center justify-center text-xs text-slate-500">
                      {condMode ? "⚠ Custom condition model not installed. Upload a condition model in Model Center." : "Enable Condition Mode to classify damage."}
                    </div>
                  )}
                </div>

                {cond?.condition_model_active && cond.damaged_pct != null && (
                  <div className="mt-4 space-y-2">
                    <div className="flex justify-between text-xs text-slate-500">
                      <span>Damage Rate</span>
                      <span className="text-red-400 font-bold">{cond.damaged_pct}%</span>
                    </div>
                    <div className="progress-bar">
                      <div className="progress-bar-fill" style={{ width: `${cond.damaged_pct}%`, background: "linear-gradient(90deg,#10b981,#ef4444)" }} />
                    </div>
                    <div className="flex justify-between text-xs text-slate-600">
                      <span>Good {cond.good_pct}%</span>
                      <span>Damaged {cond.damaged_pct}%</span>
                    </div>
                  </div>
                )}
              </div>

              <SummaryStats result={result} />

              {result.annotated_image && (
                <div className="glass p-5">
                  <AnnotatedImage src={result.annotated_image} onDownload={() => downloadBase64(result.annotated_image!, "visionx-container-result.jpg")} />
                </div>
              )}

              <div className="glass p-5">
                <h2 className="font-semibold text-slate-300 text-sm mb-3">Container Detection Table</h2>
                <DetectionTable detections={result.detections} />
              </div>
            </>
          )}

          {!loading && !result && (
            <div className="glass flex flex-col items-center justify-center py-20 text-center">
              <Package size={48} className="text-orange-500/30 mb-4" />
              <p className="text-slate-500">Upload a container yard or port image</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
