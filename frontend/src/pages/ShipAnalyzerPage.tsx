import { useDefaultConfidence } from "../hooks/useDefaultConfidence";
import { useState } from "react";
import { Ship } from "lucide-react";
import { api } from "../services/api";
import { useAnalyzer, downloadBase64 } from "../hooks/useAnalyzer";
import { ImageDropzone } from "../components/Dropzone";
import {
  PageHeader, ConfidenceSlider, Spinner, ErrorBanner,
  SummaryStats, DetectionTable, CountChart, AnnotatedImage,
} from "../components/ResultsPanel";

const SHIP_TYPES = ["Container Ship","Cargo Ship","Tanker","Passenger Ship","Bulk Carrier","Ro-Ro","Boat/Ship"];

export default function ShipAnalyzerPage() {
  const [file, setFile] = useState<File | null>(null);
  const [conf, setConf] = useDefaultConfidence("ship");
  const { loading, result, error, run, setError, setResult } = useAnalyzer(api.analyzeShip, conf);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader icon={Ship} title="Ship Analyzer" subtitle="Maritime vessel detection — harbor, port, satellite, and drone imagery" iconColor="text-teal-400" badge="Maritime AI" />

      {result?.warnings?.map(w => <div key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</div>)}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="glass p-5 space-y-4">
            <h2 className="font-semibold text-slate-300 text-sm">Upload Maritime Image</h2>
            <ImageDropzone onFile={f=>{setFile(f);setResult(null);}} label="Drop a port / harbor / satellite image" />
            <ConfidenceSlider value={conf} onChange={setConf} />

            <div className="space-y-2">
              <p className="text-xs text-slate-500 font-medium">Supported Ship Classes</p>
              <div className="flex flex-wrap gap-1.5">
                {SHIP_TYPES.map(t => (
                  <span key={t} className="badge badge-cyan text-xs">{t}</span>
                ))}
              </div>
              <p className="text-xs text-slate-600">Full ship-type classification available when custom model is uploaded.</p>
            </div>

            <button onClick={() => file && run(file, conf)} disabled={!file || loading} className="btn-primary w-full">
              {loading ? "Detecting Ships…" : "Detect Ships"}
            </button>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {loading && <div className="glass p-5"><Spinner label="Scanning for ships…" /></div>}

          {!loading && result && (
            <>
              <div className="glass p-6 text-center bg-gradient-to-br from-teal-500/10 to-cyan-500/5">
                <p className="text-5xl font-extrabold" style={{ background: "linear-gradient(135deg,#14b8a6,#06b6d4)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                  {result.detections.length}
                </p>
                <p className="text-slate-400 text-sm">Ships / Vessels Detected</p>
              </div>

              <SummaryStats result={result} />

              {result.annotated_image && (
                <div className="glass p-5">
                  <h2 className="font-semibold text-slate-300 text-sm mb-3">Detection Result</h2>
                  <AnnotatedImage src={result.annotated_image} onDownload={() => downloadBase64(result.annotated_image!, "visionx-ship-result.jpg")} />
                </div>
              )}

              {Object.keys(result.counts).length > 0 && (
                <div className="glass p-5">
                  <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wider">Ship Type Distribution</h3>
                  <CountChart counts={result.counts} />
                </div>
              )}

              <div className="glass p-5">
                <h2 className="font-semibold text-slate-300 text-sm mb-3">Ship Detection Table</h2>
                <DetectionTable detections={result.detections} />
              </div>
            </>
          )}

          {!loading && !result && (
            <div className="glass flex flex-col items-center justify-center py-20 text-center">
              <Ship size={48} className="text-teal-500/30 mb-4" />
              <p className="text-slate-500">Upload a maritime image to detect ships</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
