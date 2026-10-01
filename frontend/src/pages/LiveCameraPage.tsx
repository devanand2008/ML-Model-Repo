import { useState, useRef, useCallback, useEffect } from "react";
import {
  Camera, CameraOff, Settings, Activity, Users, Ship, Package, Layers,
  Maximize2, Minimize2, Download, AlertCircle, Wifi, WifiOff, Zap,
  Eye, Play, Square, RotateCcw
} from "lucide-react";
import { BASE_URL, getLiveTicket, getActivityReports, downloadActivityReport, type ActivityReport } from "../services/api";

// ── Types ────────────────────────────────────────────────────────────

interface LiveDetection {
  id: number;
  class: string;
  confidence: number;
  bbox: [number, number, number, number];
  activity?: string;
  keypoints?: [number,number,number][];
  pose_observations?: string[];
  action_estimates?: string[];
  track_id?: number;
}

interface LiveFrame {
  type: string;
  annotated_frame: string;
  detections: LiveDetection[];
  counts: Record<string, number>;
  total_objects: number;
  inference_time: number;
  fps: number;
  mode: string;
  frame_width: number;
  frame_height: number;
  port_summary?: {
    people: number;
    ships: number;
    trucks: number;
    containers: number | null;
    vehicles: number;
    total: number;
  };
  warnings?: string[];
  unique_count?: number;
  recoverable?: boolean;
  tracking?: boolean;
  models?: string[];
  error?: string;
  report?: ActivityReport;
  monitoring?: Monitoring;
}

interface Monitoring {
  session_started:string; camera_on_seconds:number; next_report_in_seconds:number;
  recent_actions:{time:string;track_id:number;object:string;action:string;direction?:string}[];
}
const localTime=(value:string)=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Calcutta'});
const duration=(seconds:number)=>`${Math.floor(Math.max(0,seconds)/60)}:${String(Math.max(0,seconds)%60).padStart(2,'0')}`;
type DetectionMode = "general" | "human" | "ship" | "container" | "port_monitor";

const MODES: { value: DetectionMode; label: string; icon: typeof Eye; color: string; desc: string }[] = [
  { value: "general",      label: "All Objects",    icon: Eye,     color: "from-cyan-500 to-blue-500",   desc: "COCO 80-class detection" },
  { value: "human",        label: "Human Actions & Skeleton",icon: Users,   color: "from-purple-500 to-pink-500", desc: "Stick figure, tracking & pose activity" },
  { value: "ship",         label: "Ship Detection", icon: Ship,    color: "from-teal-500 to-cyan-500",   desc: "Maritime vessel monitoring" },
  { value: "container",    label: "Containers",     icon: Package, color: "from-orange-500 to-amber-500",desc: "Shipping container detection" },
  { value: "port_monitor", label: "Port Monitor",   icon: Layers,  color: "from-pink-500 to-rose-500",   desc: "Full port AI surveillance" },
];

// ── Component ────────────────────────────────────────────────────────

export default function LiveCameraPage() {
  // Camera state
  const [cameraActive, setCameraActive] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [mode, setMode] = useState<DetectionMode>("human");
  const [confidence, setConfidence] = useState(0.5);
  const [track,setTrack] = useState(true);
  const [pose,setPose] = useState(true);
  const [connecting,setConnecting] = useState(false);
  const [warnings,setWarnings] = useState<string[]>([]);
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stats
  const [lastFrame, setLastFrame] = useState<LiveFrame | null>(null);
  const [connected, setConnected] = useState(false);
  const [totalFrames, setTotalFrames] = useState(0);
  const [sessionDetections, setSessionDetections] = useState(0);

  const [reports,setReports]=useState<ActivityReport[]>([]);
  const [monitoring,setMonitoring]=useState<Monitoring|null>(null);
  const [now,setNow]=useState(Date.now());
  const [autoDownload,setAutoDownload]=useState(true);
  const [cameraStartedAt,setCameraStartedAt]=useState<string|null>(null);
  const autoDownloadRef=useRef(true);
  const cameraTimeRef=useRef('');
  const statusReceivedRef=useRef(Date.now());
  const stopRequestedRef=useRef(false);
  useEffect(()=>{autoDownloadRef.current=autoDownload;},[autoDownload]);
  useEffect(()=>{
    getActivityReports().then(setReports).catch(e=>setError(e.message));
    const timer=window.setInterval(()=>setNow(Date.now()),1000);
    return ()=>window.clearInterval(timer);
  },[]);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const annotatedRef = useRef<HTMLImageElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const sendingRef = useRef(false);
  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const timeoutRef = useRef<number>(0);

  // ── Start webcam ──────────────────────────────────────────────────

  const startCamera = useCallback(async () => {
    setError(null);
    try {
      streamRef.current?.getTracks().forEach(t=>t.stop());
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "environment" },
        audio: false,
      });
      if (!mountedRef.current) {stream.getTracks().forEach(t=>t.stop());return;}
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      cameraTimeRef.current=new Date().toISOString();setCameraStartedAt(cameraTimeRef.current);
      setCameraActive(true);
    } catch (e: any) {
      setError("Camera access denied. Please allow camera permissions.");
    }
  }, []);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraActive(false);
    stopStreaming();
  }, []);

  // ── WebSocket streaming ───────────────────────────────────────────

  const startStreaming = useCallback(async () => {
    if (!cameraActive || connecting || streaming) return;
    stopRequestedRef.current=false;
    setError(null);setConnecting(true);setLastFrame(null);setWarnings([]);setMonitoring(null);
    const generation=++generationRef.current;
    try {
      const ticket=await getLiveTicket();
      if(!mountedRef.current || generation!==generationRef.current)return;
      const endpoint=new URL(BASE_URL || window.location.origin,window.location.origin);
      endpoint.protocol=endpoint.protocol==='https:'?'wss:':'ws:';
      endpoint.pathname='/api/analyze/live';
      endpoint.search=new URLSearchParams({mode,confidence:String(confidence),track:String(track),pose:String(pose),ticket,camera_started_at:cameraTimeRef.current}).toString();
      const ws=new WebSocket(endpoint);
      wsRef.current=ws;
      timeoutRef.current=window.setTimeout(()=>{if(wsRef.current===ws){setError('Live model did not respond. Restart detection.');ws.close();}},125000);
      ws.onmessage=(ev)=>{
        if(wsRef.current!==ws)return;
        try {
          const data:LiveFrame=JSON.parse(ev.data);
          if(data.monitoring){statusReceivedRef.current=Date.now();setMonitoring(data.monitoring);}
          if(data.type==='report' && data.report){
            const report=data.report;
            setReports(items=>[report,...items.filter(item=>item.id!==report.id)].slice(0,50));
            if(autoDownloadRef.current)downloadActivityReport(report).catch(e=>setError(e.message));
            return;
          }
          if(data.type==='stopped'){ws.close();return;}
          if(data.warnings)setWarnings(data.warnings);
          if(data.error){
            setError(data.error);
            if(!data.recoverable){ws.close();return;}
            sendingRef.current=false;
            rafRef.current=requestAnimationFrame(sendFrame);
            return;
          }
          if(data.type==='ready'){
            clearTimeout(timeoutRef.current);setConnected(true);setStreaming(true);setConnecting(false);
            setTotalFrames(0);setSessionDetections(0);sendFrame();return;
          }
          if(data.type==='detection'){
            clearTimeout(timeoutRef.current);
            setLastFrame(data);setTotalFrames(n=>n+1);setSessionDetections(n=>n+data.total_objects);
            sendingRef.current=false;
            rafRef.current=requestAnimationFrame(sendFrame);
          }
        }catch{setError('Invalid response from live detector');ws.close();}
      };
      ws.onerror=()=>{if(wsRef.current===ws)setError('Cannot connect to live detection. Check that the backend is running.');};
      ws.onclose=(event)=>{
        if(wsRef.current!==ws)return;
        clearTimeout(timeoutRef.current);cancelAnimationFrame(rafRef.current);
        wsRef.current=null;sendingRef.current=false;
        setConnecting(false);setConnected(false);setStreaming(false);
        getActivityReports().then(items=>{if(mountedRef.current)setReports(items);}).catch(()=>{});
        if(event.code===1006)setError('Live connection lost. Run Run-VisionX.bat start, then click Start Detection to reconnect.');
        if(event.code===1013)setError('Live detection is busy. Try again shortly.');
        if(event.code===1008 && !event.wasClean)setError('Live session was rejected. Sign in again or check the selected model.');
      };
    }catch(e:any){if(mountedRef.current && generation===generationRef.current){setError(e.message || 'Could not start live detection');setConnecting(false);}}
  },[cameraActive,connecting,streaming,mode,confidence,track,pose]);

  const stopStreaming = useCallback(() => {
    ++generationRef.current;
    clearTimeout(timeoutRef.current);
    setConnecting(false);
    cancelAnimationFrame(rafRef.current);
    stopRequestedRef.current=true;
    const ws=wsRef.current;
    if(ws?.readyState===WebSocket.OPEN && mountedRef.current){
      ws.send(JSON.stringify({type:'stop'}));
      setConnecting(true);
      timeoutRef.current=window.setTimeout(()=>{if(wsRef.current===ws)ws.close();},130000);
    }else{ws?.close();wsRef.current=null;}
    setStreaming(false);
    setConnected(false);
    sendingRef.current = false;
  }, []);

  const sendFrame = useCallback(() => {
    if (sendingRef.current || stopRequestedRef.current) return;
    if (!videoRef.current || !canvasRef.current || !wsRef.current) return;
    if (wsRef.current.readyState !== WebSocket.OPEN) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (video.videoWidth === 0) {
      rafRef.current = requestAnimationFrame(sendFrame);
      return;
    }

    // Scale down for faster transfer
    const scale = Math.min(1, 640 / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    sendingRef.current = true;
    const frameData = canvas.toDataURL("image/jpeg", 0.7);
    try {
      wsRef.current.send(JSON.stringify({ type: "frame", frame: frameData }));
      clearTimeout(timeoutRef.current);
      timeoutRef.current=window.setTimeout(()=>{setError('Live inference timed out. Restart detection.');wsRef.current?.close();},125000);
    } catch {sendingRef.current=false;setError('Camera frame could not be sent');}

  }, []);

  // ── Mode change while streaming ───────────────────────────────────

  useEffect(() => {
    if (!stopRequestedRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "config", mode, confidence, track, pose }));
    }
  }, [mode, confidence, track, pose, connected]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current=true;
    return () => {
      mountedRef.current=false;
      stopCamera();
      stopStreaming();
    };
  }, []);

  // ── Download snapshot ─────────────────────────────────────────────

  const downloadSnapshot = () => {
    if (!annotatedRef.current?.src) return;
    const a = document.createElement("a");
    a.href = annotatedRef.current.src;
    a.download = `visionx-live-${Date.now()}.jpg`;
    a.click();
  };

  // ── Render ────────────────────────────────────────────────────────

  const modeInfo = MODES.find(m => m.value === mode)!;
  const ModeIcon = modeInfo.icon;

  return (
    <div className="p-6 max-w-screen-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold gradient-text flex items-center gap-3">
            <Camera size={32} />
            Live Camera Detection
          </h1>
          <p className="text-slate-400 mt-1">
            Live human skeleton tracking, posture estimates and object detection
          </p>
        </div>
        <div className="flex items-center gap-2">
          {connected ? (
            <span className="badge badge-green flex items-center gap-1">
              <Wifi size={12} /> Connected
            </span>
          ) : (
            <span className="badge badge-red flex items-center gap-1">
              <WifiOff size={12} /> Disconnected
            </span>
          )}
        </div>
      </div>

      <section className="glass p-5 space-y-3">
        <h2 className="font-semibold text-cyan-300">Camera timing and activity reports</h2>
        <div className="flex flex-wrap gap-6 text-sm text-slate-300">
          <p>Camera started: {cameraStartedAt?`${localTime(cameraStartedAt)} IST`:'Not started'}</p>
          <p>Camera on: {cameraActive && cameraStartedAt?duration(Math.floor((now-Date.parse(cameraStartedAt))/1000)):'Off'}</p>
          <p>Next text report: {streaming && monitoring?duration(Math.max(0,monitoring.next_report_in_seconds-Math.floor((now-statusReceivedRef.current)/1000))):'Start detection'}</p>
        </div>
        <p className="text-xs text-slate-400">A text report is saved every 10 minutes during detection. It records detected people and objects, movement, stationary periods, visibility changes and timestamps. Stop Detection saves the remaining interval.</p>
        <label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={autoDownload} onChange={e=>setAutoDownload(e.target.checked)}/>Automatically download new text reports</label>
        <p className="text-xs text-slate-500">Reports remain available below if your browser blocks automatic downloads. Movement is estimated in the image; actions such as eating or fighting require a trained action model. Keep tracking enabled to record movement.</p>
      </section>
      {/* Error Banner */}
      {error && (
        <div className="glass p-4 border border-red-500/30 bg-red-500/5 flex items-center gap-3">
          <AlertCircle className="text-red-400 shrink-0" size={20} />
          <p className="text-red-300 text-sm">{error}</p>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-300 text-sm">
            Dismiss
          </button>
        </div>
      )}

      {warnings.map(w=><p key={w} role="status" className="glass p-4 text-amber-300 text-sm">{w}</p>)}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        {/* ── Left Panel: Controls ──────────────────────────────────── */}
        <div className="xl:col-span-1 space-y-4">
          {/* Camera Controls */}
          <div className="glass p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
              <Settings size={14} className="text-cyan-400" /> Camera Controls
            </h3>

            {!cameraActive ? (
              <button onClick={startCamera} className="btn-primary w-full flex items-center justify-center gap-2">
                <Camera size={16} /> Start Camera
              </button>
            ) : (
              <div className="space-y-2">
                {!streaming ? (
                  <button onClick={startStreaming} disabled={connecting} className="btn-primary w-full flex items-center justify-center gap-2">
                    <Play size={16} /> {connecting ? (stopRequestedRef.current ? "Saving final report..." : "Loading live model...") : "Start Detection"}
                  </button>
                ) : (
                  <button onClick={stopStreaming} className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 hover:bg-red-500/30 transition-all">
                    <Square size={16} /> Stop Detection
                  </button>
                )}
                <button onClick={stopCamera} className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-slate-500/20 border border-slate-500/30 text-slate-300 hover:bg-slate-500/30 transition-all text-sm">
                  <CameraOff size={14} /> Turn Off Camera
                </button>
              </div>
            )}
          </div>

          {/* Detection Mode */}
          <div className="glass p-5 space-y-3">
            <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
              <Zap size={14} className="text-yellow-400" /> Detection Mode
            </h3>
            <div className="space-y-1.5">
              {MODES.map(m => (
                <button
                  key={m.value}
                  onClick={() => setMode(m.value)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all text-sm ${
                    mode === m.value
                      ? `bg-gradient-to-r ${m.color} text-white shadow-lg`
                      : "bg-slate-800/50 text-slate-400 hover:bg-slate-700/50 hover:text-slate-200"
                  }`}
                >
                  <m.icon size={16} />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{m.label}</p>
                    {mode === m.value && (
                      <p className="text-xs opacity-80 truncate">{m.desc}</p>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Confidence Threshold */}
          <div className="glass p-5 space-y-3">
            <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
              <Activity size={14} className="text-green-400" /> Confidence
            </h3>
            <input
              aria-label="Live confidence threshold" type="range" min={0.1} max={0.95} step={0.05}
              value={confidence}
              onChange={e => setConfidence(parseFloat(e.target.value))}
              className="w-full accent-cyan-400"
            />
            <p className="text-center text-lg font-mono text-cyan-400">{Math.round(confidence * 100)}%</p>
            <label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={track} onChange={e=>setTrack(e.target.checked)}/>Track objects and draw movement paths</label>
            {mode==='human' && <div className="space-y-2"><label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={pose} onChange={e=>setPose(e.target.checked)}/>Stick-figure skeleton and pose observations</label><p className="text-xs text-slate-500">The skeleton follows each person's joints. Estimates include standing, sitting, waving and raised hands. Keep tracking on for stable gesture detection; missing joints are omitted.</p></div>}
            <p className="text-xs text-slate-500">Changing the mode, skeleton or tracking option resets session tracking IDs.</p>
          </div>

          {/* Actions */}
          {streaming && (
            <div className="glass p-5 space-y-2">
              <button onClick={downloadSnapshot} className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-blue-500/20 border border-blue-500/30 text-blue-300 hover:bg-blue-500/30 transition-all text-sm">
                <Download size={14} /> Save Snapshot
              </button>
            </div>
          )}
        </div>

        {/* ── Center: Video Feed ────────────────────────────────────── */}
        <div className={`xl:col-span-2 space-y-4 ${fullscreen ? "fixed inset-0 z-50 bg-navy-950 p-4" : ""}`}>
          <div className="relative glass overflow-hidden" style={{ minHeight: 400 }}>
            {/* Hidden elements */}
            <video ref={videoRef} className="hidden" playsInline muted />
            <canvas ref={canvasRef} className="hidden" />

            {/* Annotated feed or raw camera */}
            {streaming && lastFrame ? (
              <img
                ref={annotatedRef}
                src={lastFrame.annotated_frame}
                alt="Live AI detection feed"
                className="w-full h-auto rounded-xl"
                style={{ maxHeight: fullscreen ? "calc(100vh - 120px)" : 600 }}
              />
            ) : cameraActive ? (
              <video
                ref={el => { if (el && streamRef.current) { el.srcObject = streamRef.current; el.play(); } }}
                className="w-full h-auto rounded-xl"
                style={{ maxHeight: fullscreen ? "calc(100vh - 120px)" : 600 }}
                playsInline muted autoPlay
              />
            ) : (
              <div className="flex flex-col items-center justify-center py-24 text-center">
                <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-cyan-500/10 to-blue-500/10 border border-cyan-500/20 flex items-center justify-center mb-6">
                  <Camera size={40} className="text-cyan-400/60" />
                </div>
                <h3 className="text-xl font-semibold text-slate-300 mb-2">Camera Not Active</h3>
                <p className="text-slate-500 text-sm max-w-md">
                  Click "Start Camera" to enable your webcam, then "Start Detection" to begin real-time AI analysis.
                </p>
              </div>
            )}

            {/* Live overlay HUD */}
            {streaming && lastFrame && (
              <>
                {/* Top-left: Mode badge */}
                <div className="absolute top-3 left-3">
                  <span className={`px-3 py-1.5 rounded-lg text-xs font-bold text-white bg-gradient-to-r ${modeInfo.color} shadow-lg flex items-center gap-1.5`}>
                    <ModeIcon size={12} />
                    {modeInfo.label.toUpperCase()}
                  </span>
                </div>

                {/* Top-right: FPS + inference */}
                <div className="absolute top-3 right-3 flex gap-2">
                  <span className="px-2.5 py-1 rounded-lg text-xs font-mono bg-black/60 text-green-400 backdrop-blur">
                    {lastFrame.fps} inference FPS
                  </span>
                  <span className="px-2.5 py-1 rounded-lg text-xs font-mono bg-black/60 text-cyan-400 backdrop-blur">
                    {lastFrame.inference_time}ms
                  </span>
                </div>

                {/* Bottom-left: Object count */}
                <div className="absolute bottom-3 left-3">
                  <span className="px-3 py-1.5 rounded-lg text-sm font-bold bg-black/60 text-yellow-400 backdrop-blur">
                    {lastFrame.total_objects} Objects Detected
                  </span>
                </div>
              </>
            )}

            {/* Fullscreen toggle */}
            <button
              onClick={() => setFullscreen(!fullscreen)}
              className="absolute bottom-3 right-3 p-2 rounded-lg bg-black/50 text-white hover:bg-black/70 transition-colors backdrop-blur"
            >
              {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          </div>

          {/* Port Monitor Summary Bar */}
          {streaming && mode === "port_monitor" && lastFrame?.port_summary && (
            <div className="glass p-4">
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-center">
                {[
                  { label: "People", value: lastFrame.port_summary.people, icon: Users, color: "text-purple-400" },
                  { label: "Ships", value: lastFrame.port_summary.ships, icon: Ship, color: "text-teal-400" },
                  { label: "Trucks", value: lastFrame.port_summary.trucks, icon: Package, color: "text-orange-400" },
                  { label: "Containers", value: lastFrame.port_summary.containers ?? "N/A", icon: Package, color: "text-amber-400" },
                  { label: "Vehicles", value: lastFrame.port_summary.vehicles, icon: Layers, color: "text-blue-400" },
                  { label: "Total", value: lastFrame.port_summary.total, icon: Eye, color: "text-cyan-400" },
                ].map(item => (
                  <div key={item.label} className="flex flex-col items-center">
                    <item.icon size={18} className={item.color} />
                    <p className={`text-2xl font-bold ${item.color} mt-1`}>{item.value}</p>
                    <p className="text-xs text-slate-500">{item.label}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Right Panel: Live Stats ──────────────────────────────── */}
        <div className="xl:col-span-1 space-y-4">
          {/* Session Stats */}
          <div className="glass p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
              <Activity size={14} className="text-cyan-400" /> Live Statistics
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Inference FPS", value: lastFrame?.fps ?? 0, color: "text-green-400" },
                { label: "Latency", value: `${lastFrame?.inference_time ?? 0}ms`, color: "text-cyan-400" },
                { label: "Objects", value: lastFrame?.total_objects ?? 0, color: "text-yellow-400" },
                { label: "Frames", value: totalFrames, color: "text-blue-400" },
                { label: "Unique IDs", value: lastFrame?.unique_count ?? 0, color: "text-purple-400" },
                { label: "Frame detections", value: sessionDetections, color: "text-orange-400" },
              ].map(s => (
                <div key={s.label} className="bg-slate-800/50 rounded-xl p-3 text-center">
                  <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Object Counts */}
          {lastFrame && Object.keys(lastFrame.counts).length > 0 && (
            <div className="glass p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-300">Detected Objects</h3>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {Object.entries(lastFrame.counts)
                  .sort(([, a], [, b]) => b - a)
                  .map(([cls, count]) => (
                    <div key={cls} className="flex items-center justify-between bg-slate-800/50 rounded-lg px-3 py-2">
                      <span className="text-sm text-slate-300 capitalize">{cls}</span>
                      <span className="text-sm font-bold text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded-md">
                        {count}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Detection Log */}
          {lastFrame && lastFrame.detections.length > 0 && (
            <div className="glass p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-300">Latest Detections</h3>
              <div className="space-y-1.5 max-h-80 overflow-y-auto text-xs">
                {lastFrame.detections.slice(0, 15).map(det => (
                  <div key={det.id} className="flex items-center gap-2 bg-slate-800/50 rounded-lg px-3 py-2">
                    <div
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{
                        backgroundColor: det.confidence >= 0.8 ? "#10b981" : det.confidence >= 0.5 ? "#3b82f6" : "#f59e0b"
                      }}
                    />
                    <span className="text-slate-300 capitalize flex-1 truncate">{det.class} {det.activity?`? ${det.activity}`:""} {det.pose_observations?.length?`? ${det.pose_observations.join(", ")}`:""}</span>
                    <span className="font-mono text-slate-500">{(det.confidence * 100).toFixed(0)}%</span>
                    {det.track_id != null && (
                      <span className="text-purple-400 font-mono">#{det.track_id}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Resolution Info */}
          {lastFrame && (
            <div className="glass p-4 text-center">
              <p className="text-xs text-cyan-400 mb-2">Models: {lastFrame.models?.map(path=>path.split(/[\\/]/).pop()).join(', ')}</p>
              <p className="text-xs text-slate-500">
                {lastFrame.frame_width}×{lastFrame.frame_height} •
                Session: {totalFrames} frames
              </p>
            </div>
          )}
        </div>
      </div>
      {mode==='human' && pose && <section className="glass p-5 space-y-4">
        <h2 className="font-semibold text-purple-300">Human actions and posture</h2>
        <p className="text-xs text-slate-400">Pose-based estimates: standing, sitting, waving, raised hands and bent knees. Waving requires repeated hand movement; uncertain or hidden joints are left unlabeled.</p>
        <div className="grid gap-3 md:grid-cols-2">{lastFrame?.detections.filter(det=>det.class==='person').map(det=><div key={det.id} className="rounded-lg bg-slate-800/50 p-4 space-y-2">
          <p className="font-medium text-slate-200">Person {det.track_id!=null?`#${det.track_id}`:'(untracked)'}</p>
          <p className="text-sm text-purple-300">{det.action_estimates?.length?det.action_estimates.join(' | '):'No confident posture or gesture estimate'}</p>
          <p className="text-sm text-slate-400">{det.pose_observations?.join(' | ') || 'No raised-hand or bent-knee observation'}{det.activity?` | ${det.activity}`:''}</p>
        </div>)}</div>
        {!lastFrame?.detections.some(det=>det.class==='person') && <p className="text-sm text-slate-500">Start detection and move into the camera view. Show your full body for standing and sitting estimates.</p>}
      </section>}
      <section className="glass p-5 space-y-4">
        <h2 className="font-semibold text-cyan-300">Recent observed activity</h2>
        {monitoring?.recent_actions.length ? <ul className="space-y-2 text-sm text-slate-300">{[...monitoring.recent_actions].reverse().map((event,index)=><li key={`${event.time}-${index}`}>{localTime(event.time)} IST ? {event.object} #{event.track_id}: {event.action}{event.direction?` (${event.direction})`:''}</li>)}</ul>:<p className="text-sm text-slate-500">Start detection to record activity.</p>}
      </section>
      <section className="glass p-5 space-y-4">
        <h2 className="font-semibold text-cyan-300">Saved text reports</h2>
        {!reports.length && <p className="text-sm text-slate-500">Your first report appears after 10 minutes, or when you stop detection.</p>}
        <div className="space-y-3 max-h-96 overflow-auto">{reports.map(report=><div key={report.id} className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-800/50 p-3">
          <div className="flex-1 text-sm text-slate-300"><p>{localTime(report.started_at)} ? {localTime(report.ended_at)} IST {report.partial?'(partial interval)':''}</p><p className="text-xs text-slate-500">{report.frames_analyzed} frames ? {report.unique_track_ids} tracked IDs</p></div>
          <button className="btn-secondary flex gap-2 items-center" onClick={()=>downloadActivityReport(report).catch(e=>setError(e.message))}><Download size={14}/>Download .txt</button>
        </div>)}</div>
      </section>
    </div>
  );
}
