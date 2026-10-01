import { useDefaultConfidence } from "../hooks/useDefaultConfidence";
import { useState } from "react";
import { Eye } from "lucide-react";
import { api } from "../services/api";
import { useAnalyzer, downloadBase64 } from "../hooks/useAnalyzer";
import { ImageDropzone } from "../components/Dropzone";
import {
  PageHeader, ConfidenceSlider, Spinner, ErrorBanner,
  SummaryStats, DetectionTable, CountChart, DistributionPie, AnnotatedImage,
} from "../components/ResultsPanel";

export default function ImageAnalyzerPage() {
  const [file, setFile]       = useState<File | null>(null);
  const [conf, setConf]       = useDefaultConfidence("general");
  const [brightness, setBr]   = useState(1.0);
  const [contrast,   setCo]   = useState(1.0);
  const [sharpness,  setSh]   = useState(1.0);
  const [grayscale,  setGs]   = useState(false);
  const [denoise,    setDn]   = useState(false);
  const [resizeWidth, setResizeWidth] = useState(0);
  const [showPre,    setSP]   = useState(false);
  const { loading, result, error, run, setError, setResult } = useAnalyzer(api.analyzeImage, conf);

  const analyze = () => {
    if (!file) return;
    run(file, conf, { brightness, contrast, sharpness, grayscale, denoise, resize_width: resizeWidth });
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader icon={Eye} title="Image Analyzer" subtitle="General object detection — COCO 80-class model" badge="YOLO" />

      {result?.warnings?.map(w => <div key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</div>)}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Left panel */}
        <div className="lg:col-span-2 space-y-4">
          <div className="glass p-5 space-y-4">
            <h2 className="font-semibold text-slate-300 text-sm">Upload Image</h2>
            <ImageDropzone onFile={f=>{setFile(f);setResult(null);}} />
            <label className="block text-xs text-slate-400">Resize width (0 = original)<input aria-label="Resize width" type="number" min={0} max={4096} value={resizeWidth} onChange={e=>setResizeWidth(Number(e.target.value))} className="input-field mt-2" /></label>
            <ConfidenceSlider value={conf} onChange={setConf} />

            {/* Preprocessing toggles */}
            <details className="group">
              <summary className="text-xs text-slate-500 cursor-pointer select-none hover:text-slate-400 transition-colors">
                ▸ Preprocessing Options
              </summary>
              <div className="mt-3 space-y-3 pl-2">
                {[
                  { label: "Brightness", val: brightness, set: setBr },
                  { label: "Contrast",   val: contrast,   set: setCo },
                  { label: "Sharpness",  val: sharpness,  set: setSh },
                ].map(({ label, val, set }) => (
                  <div key={label} className="space-y-1">
                    <div className="flex justify-between text-xs text-slate-500">
                      <span>{label}</span><span className="font-mono text-cyan-400">{val.toFixed(1)}</span>
                    </div>
                    <input type="range" min={0.5} max={2.0} step={0.1} value={val} onChange={e => set(parseFloat(e.target.value))} />
                  </div>
                ))}
                <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                  <input type="checkbox" checked={grayscale} onChange={e => setGs(e.target.checked)} className="accent-blue-500" />
                  Grayscale
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                  <input type="checkbox" checked={denoise} onChange={e => setDn(e.target.checked)} className="accent-blue-500" />
                  Noise Reduction
                </label>
              </div>
            </details>

            <button onClick={analyze} disabled={!file || loading} className="btn-primary w-full flex items-center justify-center gap-2">
              {loading ? "Analyzing…" : "Run AI Analysis"}
            </button>
          </div>
        </div>

        {/* Right panel */}
        <div className="lg:col-span-3 space-y-4">
          {loading && <div className="glass p-5"><Spinner /></div>}

          {!loading && result && (
            <>
              <SummaryStats result={result} />
              {result.processed_image && <details className="glass p-4"><summary>Compare processed image</summary><img src={result.processed_image} alt="Processed image before detection" className="w-full mt-3 rounded-xl" /></details>}

              {result.annotated_image && (
                <div className="glass p-5">
                  <h2 className="font-semibold text-slate-300 text-sm mb-3">Detection Result</h2>
                  <AnnotatedImage
                    src={result.annotated_image}
                    onDownload={() => downloadBase64(result.annotated_image!, "visionx-image-result.jpg")}
                  />
                </div>
              )}

              {Object.keys(result.counts).length > 0 && (
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
              )}

              <div className="glass p-5">
                <h2 className="font-semibold text-slate-300 text-sm mb-3">Detection Table</h2>
                <DetectionTable detections={result.detections} />
              </div>

              {result.model_info && (
                <div className="glass p-4">
                  <h3 className="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wider">Model Information</h3>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="text-slate-500">Name</div><div className="text-slate-300">{result.model_info.name}</div>
                    <div className="text-slate-500">Type</div><div className="text-slate-300 capitalize">{result.model_info.type}</div>
                    <div className="text-slate-500">File</div><div className="text-slate-300 font-mono">{result.model_info.filename}</div>
                    <div className="text-slate-500">Threshold</div><div className="text-cyan-400">{(conf * 100).toFixed(0)}%</div>
                  </div>
                </div>
              )}
            </>
          )}

          {!loading && !result && (
            <div className="glass flex flex-col items-center justify-center py-20 text-center">
              <Eye size={48} className="text-blue-500/30 mb-4" />
              <p className="text-slate-500">Upload an image and click <strong className="text-slate-400">Run AI Analysis</strong></p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
