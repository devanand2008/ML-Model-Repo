import { useDefaultConfidence } from "../hooks/useDefaultConfidence";
import { useState } from "react";
import { Video, Download } from "lucide-react";
import { api, downloadOutput } from "../services/api";
import { useAnalyzer } from "../hooks/useAnalyzer";
import { VideoDropzone } from "../components/Dropzone";
import {
  PageHeader, ConfidenceSlider, Spinner, ErrorBanner, CountChart,
} from "../components/ResultsPanel";

const ANALYZER_TYPES = [
  { value: "general",   label: "General (All Objects)" },
  { value: "human",     label: "Human / Person" },
  { value: "ship",      label: "Ship / Maritime" },
  { value: "container", label: "Shipping Container" },
];

export default function VideoAnalyzerPage() {
  const [progress, setProgress] = useState({progress:0,frame:0,total:0});
  const [frameIndex,setFrameIndex] = useState(0);
  const [file,         setFile]     = useState<File | null>(null);
  const [conf,         setConf]     = useDefaultConfidence("general");
  const [analyzerType, setType]     = useState("general");
  const [track,        setTrack]    = useState(true);
  const { loading, result, error, run, setError, setResult } = useAnalyzer(api.analyzeVideo, conf);

  const downloadUrl = result?.download_url ? `${import.meta.env.VITE_API_URL ?? ""}${result.download_url}` : null;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader icon={Video} title="Video Analyzer" subtitle="Frame-by-frame detection with tracking across MP4/AVI/MOV files" iconColor="text-yellow-400" badge="Tracking" />

      {result?.warnings?.map(w => <div key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</div>)}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="glass p-5 space-y-4">
            <h2 className="font-semibold text-slate-300 text-sm">Upload Video</h2>
            <VideoDropzone onFile={f=>{setFile(f);setResult(null);}} />
            <ConfidenceSlider value={conf} onChange={setConf} />

            <div className="space-y-2">
              <label className="text-xs text-slate-500">Analyzer Mode</label>
              <select
                value={analyzerType}
                onChange={e => setType(e.target.value)}
                className="input-field"
              >
                {ANALYZER_TYPES.map(({ value, label }) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>

            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={track} onChange={e => setTrack(e.target.checked)} className="accent-yellow-500" />
              <span className="text-sm text-slate-300">Enable Object Tracking (persistent IDs)</span>
            </label>

            <div className="text-xs text-slate-600 bg-slate-800/30 rounded-lg p-3">
              ⚠ Large videos may take several minutes. Processing runs on CPU by default.
            </div>

            <button
              onClick={() => file && run(file, analyzerType, conf, track, setProgress)}
              disabled={!file || loading}
              className="btn-primary w-full"
            >
              {loading ? "Processing Video…" : "Analyze Video"}
            </button>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {loading && (
            <div className="glass p-5">
              <progress className="w-full" max={100} value={progress.progress}/><p role="status">{progress.progress}% ? Frame {progress.frame} / {progress.total || "pending"}</p><Spinner label="Processing video frame by frame…" />
              <p className="text-center text-xs text-slate-600 mt-2">This may take a while for long videos</p>
            </div>
          )}

          {!loading && result && (
            <>
              <div className="glass p-5 space-y-3"><p>Unique tracked IDs: {result.unique_count ?? 0} ? Inference FPS: {result.inference_fps ?? 0}</p>
              {result.timeline?.length ? <><label>Video timeline<input aria-label="Video timeline" type="range" min={0} max={result.timeline.length-1} value={frameIndex} onChange={e=>setFrameIndex(Number(e.target.value))}/></label><p>Frame {result.timeline[frameIndex]?.frame} ? {result.timeline[frameIndex]?.seconds}s ? Visible objects: {result.timeline[frameIndex]?.visible}</p></> : null}</div>
              {/* Video stats */}
              <div className="glass p-6 bg-gradient-to-br from-yellow-500/10 to-orange-500/5">
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div>
                    <p className="text-3xl font-bold text-yellow-400">{result.processed_frames ?? 0}</p>
                    <p className="text-xs text-slate-500 mt-1">Frames Processed</p>
                  </div>
                  <div>
                    <p className="text-3xl font-bold text-cyan-400">{result.total_detections ?? 0}</p>
                    <p className="text-xs text-slate-500 mt-1">Total Detections</p>
                  </div>
                  <div>
                    <p className="text-3xl font-bold text-green-400">{result.fps?.toFixed(1) ?? "—"}</p>
                    <p className="text-xs text-slate-500 mt-1">Video FPS</p>
                  </div>
                </div>

                {result.class_counts && Object.keys(result.class_counts).length > 0 && (
                  <div className="mt-4 pt-4 border-t border-yellow-500/10">
                    <p className="text-xs text-slate-500 mb-1">Object Counts Across All Frames</p>
                    <div className="flex flex-wrap gap-2 mt-2">
                      {Object.entries(result.class_counts).map(([cls, cnt]) => (
                        <span key={cls} className="badge badge-orange capitalize">
                          {cls}: {cnt}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Processing time */}
              <div className="glass p-4 grid grid-cols-2 gap-4 text-sm">
                <div><span className="text-slate-500">Total Frames: </span><span className="text-slate-300">{result.total_frames}</span></div>
                <div><span className="text-slate-500">Processing Time: </span><span className="text-slate-300">{result.processing_time?.toFixed(2)}s</span></div>
                <div><span className="text-slate-500">Resolution: </span><span className="text-slate-300">{result.image_width}×{result.image_height}</span></div>
                <div><span className="text-slate-500">FPS: </span><span className="text-slate-300">{result.fps?.toFixed(1)}</span></div>
              </div>

              {/* Download */}
              {downloadUrl && (
                <div className="glass p-5 text-center">
                  <p className="text-slate-400 text-sm mb-3">Annotated video is ready for download</p>
                  <button onClick={()=>downloadOutput(result.download_url!).catch(e=>setError(e.message))} className="btn-primary inline-flex items-center gap-2">
                    <Download size={15} /> Download Annotated Video
                  </button>
                </div>
              )}

              {result.class_counts && (
                <div className="glass p-5">
                  <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wider">Detection Distribution</h3>
                  <CountChart counts={result.class_counts} />
                </div>
              )}
            </>
          )}

          {!loading && !result && (
            <div className="glass flex flex-col items-center justify-center py-20 text-center">
              <Video size={48} className="text-yellow-500/30 mb-4" />
              <p className="text-slate-500">Upload a video to start frame-by-frame analysis</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
