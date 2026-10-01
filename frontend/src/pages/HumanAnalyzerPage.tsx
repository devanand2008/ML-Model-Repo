import { useDefaultConfidence } from "../hooks/useDefaultConfidence";
import { useState } from "react";
import { Users } from "lucide-react";
import { api } from "../services/api";
import { useAnalyzer, downloadBase64 } from "../hooks/useAnalyzer";
import { ImageDropzone } from "../components/Dropzone";
import {
  PageHeader, ConfidenceSlider, Spinner, ErrorBanner,
  SummaryStats, DetectionTable, AnnotatedImage,
} from "../components/ResultsPanel";

export default function HumanAnalyzerPage() {
  const [file,     setFile]    = useState<File | null>(null);
  const [conf,     setConf]    = useDefaultConfidence("human");
  const [poseMode, setPose]    = useState(false);
  const { loading, result, error, run, setError, setResult } = useAnalyzer(api.analyzeHuman, conf);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader icon={Users} title="Human Analyzer" subtitle="Person detection, counting, position estimation, and pose keypoints" iconColor="text-purple-400" badge="Pose Mode" />

      {result?.warnings?.map(w => <div key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</div>)}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="glass p-5 space-y-4">
            <h2 className="font-semibold text-slate-300 text-sm">Upload Image</h2>
            <ImageDropzone onFile={f=>{setFile(f);setResult(null);}} />
            <ConfidenceSlider value={conf} onChange={setConf} />

            <label className="flex items-start gap-3 p-3 rounded-xl border border-purple-500/20 bg-purple-500/5 cursor-pointer hover:border-purple-500/40 transition-colors">
              <input type="checkbox" checked={poseMode} onChange={e => setPose(e.target.checked)} className="mt-0.5 accent-purple-500" />
              <div>
                <p className="text-sm text-slate-300 font-medium">Pose Estimation Mode</p>
                <p className="text-xs text-slate-500 mt-0.5">Detect 17 body keypoints (nose, shoulders, elbows, wrists, hips, knees, ankles)</p>
              </div>
            </label>

            <div className="text-xs text-slate-600 bg-slate-800/30 rounded-lg p-3">
              ℹ️ This analyzer detects people only. No personal attributes (ethnicity, gender, etc.) are inferred.
            </div>

            <button onClick={() => file && run(file, conf, poseMode)} disabled={!file || loading} className="btn-primary w-full">
              {loading ? "Analyzing…" : "Detect People"}
            </button>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {loading && <div className="glass p-5"><Spinner label="Detecting people…" /></div>}

          {!loading && result && (
            <>
              {/* People count hero */}
              <div className="glass p-6 text-center bg-gradient-to-br from-purple-500/10 to-pink-500/5">
                <p className="text-5xl font-extrabold gradient-text mb-1">{result.counts["person"] ?? 0}</p>
                <p className="text-slate-400 text-sm">People Detected</p>
                <p className="text-xs text-slate-500 mt-1">Processing: {(result.processing_time * 1000).toFixed(0)} ms</p>
              </div>

              <SummaryStats result={result} />

              {result.annotated_image && (
                <div className="glass p-5">
                  <h2 className="font-semibold text-slate-300 text-sm mb-3">
                    {poseMode ? "Pose Estimation Result" : "Detection Result"}
                  </h2>
                  <AnnotatedImage src={result.annotated_image} onDownload={() => downloadBase64(result.annotated_image!, "visionx-human-result.jpg")} />
                </div>
              )}

              <div className="glass p-5">
                <h2 className="font-semibold text-slate-300 text-sm mb-3">Person Details</h2>
                <DetectionTable detections={result.detections} />
              </div>
            </>
          )}

          {!loading && !result && (
            <div className="glass flex flex-col items-center justify-center py-20 text-center">
              <Users size={48} className="text-purple-500/30 mb-4" />
              <p className="text-slate-500">Upload an image to detect people</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
