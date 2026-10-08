import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import {
  Camera, CameraOff, Settings, Activity, Users, Ship, Package, Layers,
  Maximize2, Minimize2, Download, AlertCircle, Wifi, WifiOff, Zap,
  Eye, Play, Square, RotateCcw, CheckCircle2, Clock, Sliders, Shield,
  Search, FileText, Check, ChevronLeft, ChevronRight, RefreshCw,
  Sparkles, Smartphone, Crosshair, Info, CheckSquare, Square as BoxIcon
} from "lucide-react";
import { BASE_URL, getLiveTicket, getActivityReports, downloadActivityReport, type ActivityReport } from "../services/api";
import { transitRequest, type Data } from "../services/transit";
import BusSpeedGps from '../components/transit/BusSpeedGps';
import './transit/bus-speed.css';

// ── Types ────────────────────────────────────────────────────────────

interface LiveDetection {
  id: number;
  class: string;
  confidence: number;
  bbox: [number, number, number, number];
  activity?: string;
  keypoints?: [number, number, number][];
  pose_observations?: string[];
  action_estimates?: string[];
  track_id?: number;
}

interface LiveFrame {
  type: string;
  annotated_frame?: string;
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
  trajectories?: { track_id: number; points: [number, number][] }[];
  config_id?: number;
  transit_observation?: Data;
}

interface Monitoring {
  session_started: string;
  camera_on_seconds: number;
  next_report_in_seconds: number;
  recent_actions: { time: string; track_id: number; object: string; action: string; direction?: string }[];
}

const localTime = (value: string) => {
  try {
    return new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Calcutta', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return value;
  }
};

const localDate = (value: string) => {
  try {
    return new Date(value).toLocaleDateString('en-IN', { timeZone: 'Asia/Calcutta', day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return value;
  }
};

const duration = (seconds: number) => `${Math.floor(Math.max(0, seconds) / 60)}:${String(Math.max(0, seconds) % 60).padStart(2, '0')}`;

type DetectionMode = "general" | "human" | "ship" | "container" | "port_monitor";
type LiveQuality = "fast" | "balanced" | "detail";

const LIVE_QUALITY: Record<LiveQuality, { size: number; jpegQuality: number; label: string; tag: string }> = {
  fast: { size: 320, jpegQuality: 0.65, label: "Fast · 320px", tag: "Low Latency" },
  balanced: { size: 416, jpegQuality: 0.72, label: "Balanced · 416px", tag: "Default" },
  detail: { size: 640, jpegQuality: 0.8, label: "Detail · 640px", tag: "High Res" },
};

const SKELETON: [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8],
  [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
];

export function drawDetectionOverlay(canvas: HTMLCanvasElement, frame: LiveFrame, options = { boxes: true, labels: true }) {
  if (canvas.width !== frame.frame_width) canvas.width = frame.frame_width;
  if (canvas.height !== frame.frame_height) canvas.height = frame.frame_height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.lineWidth = Math.max(1.8, canvas.width / 300);
  ctx.lineJoin = "round";
  ctx.strokeStyle = "#00d9ff";

  // Trajectory paths
  for (const path of frame.trajectories ?? []) {
    if (path.points.length < 2) continue;
    ctx.beginPath();
    path.points.forEach(([x, y], index) => index ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.stroke();
  }

  const fontSize = Math.max(11, Math.round(canvas.width / 44));
  ctx.font = `700 ${fontSize}px sans-serif`;
  ctx.textBaseline = "top";

  for (const det of frame.detections) {
    const [x, y, width, height] = det.bbox;
    const color = det.class === "person" ? "#c084fc" : "#00d9ff";
    ctx.strokeStyle = color;
    if (options.boxes) {
      ctx.strokeRect(x, y, width, height);
      // Small corner accents
      const cornerLen = Math.min(10, width / 4);
      ctx.lineWidth = Math.max(2.5, canvas.width / 240);
      ctx.beginPath();
      ctx.moveTo(x, y + cornerLen); ctx.lineTo(x, y); ctx.lineTo(x + cornerLen, y);
      ctx.moveTo(x + width - cornerLen, y); ctx.lineTo(x + width, y); ctx.lineTo(x + width, y + cornerLen);
      ctx.moveTo(x, y + height - cornerLen); ctx.lineTo(x, y + height); ctx.lineTo(x + cornerLen, y + height);
      ctx.moveTo(x + width - cornerLen, y + height); ctx.lineTo(x + width, y + height); ctx.lineTo(x + width, y + height - cornerLen);
      ctx.stroke();
      ctx.lineWidth = Math.max(1.8, canvas.width / 300);
    }
    if (options.labels) {
      const label = `${det.track_id != null ? `#${det.track_id} ` : ""}${det.class} ${Math.round(det.confidence * 100)}%`;
      const labelWidth = Math.min(canvas.width, ctx.measureText(label).width + 8);
      const labelX = Math.min(Math.max(0, x), canvas.width - labelWidth);
      const labelY = Math.max(0, y - fontSize - 6);
      ctx.fillStyle = "rgba(6, 19, 37, 0.88)";
      ctx.fillRect(labelX, labelY, labelWidth, fontSize + 6);
      ctx.fillStyle = color;
      ctx.fillText(label, labelX + 4, labelY + 3);
    }

    const keypoints = det.keypoints ?? [];
    const visible = (point?: [number, number, number]) => point && point[2] > 0.3 && point[0] > 0 && point[1] > 0;
    ctx.strokeStyle = "#00e5a0";
    for (const [a, b] of SKELETON) {
      if (!visible(keypoints[a]) || !visible(keypoints[b])) continue;
      ctx.beginPath();
      ctx.moveTo(keypoints[a][0], keypoints[a][1]);
      ctx.lineTo(keypoints[b][0], keypoints[b][1]);
      ctx.stroke();
    }
    ctx.fillStyle = "#ffb020";
    for (const point of keypoints) {
      if (!visible(point)) continue;
      ctx.beginPath();
      ctx.arc(point[0], point[1], Math.max(2.5, canvas.width / 160), 0, 2 * Math.PI);
      ctx.fill();
    }

    const observations = [...new Set([...(det.action_estimates ?? []), ...(det.pose_observations ?? [])])];
    if (det.activity) observations.push(det.activity);
    ctx.fillStyle = "#00e5a0";
    observations.forEach((label, index) => {
      const textY = Math.min(canvas.height - fontSize - 2, y + height + 4 + index * (fontSize + 4));
      ctx.fillStyle = "rgba(6, 19, 37, 0.88)";
      ctx.fillRect(Math.max(0, x), textY, ctx.measureText(label).width + 8, fontSize + 4);
      ctx.fillStyle = "#00e5a0";
      ctx.fillText(label, Math.max(0, x) + 4, textY + 2);
    });
  }
}

const MODES: { value: DetectionMode; label: string; icon: typeof Eye; color: string; desc: string; badge: string }[] = [
  { value: "general", label: "COCO 80-Class", icon: Eye, color: "from-cyan-500 to-blue-500", desc: "Vehicles, pedestrians & objects", badge: "General" },
  { value: "human", label: "Human Pose & Actions", icon: Users, color: "from-purple-500 to-pink-500", desc: "17-pt skeleton, tracking & postures", badge: "Pose AI" },
  { value: "ship", label: "Maritime Vessels", icon: Ship, color: "from-teal-500 to-cyan-500", desc: "Vessel detection & sea traffic", badge: "Marine" },
  { value: "container", label: "Freight Containers", icon: Package, color: "from-orange-500 to-amber-500", desc: "ISO cargo boxes & inspection", badge: "Cargo" },
  { value: "port_monitor", label: "Port Surveillance", icon: Layers, color: "from-pink-500 to-rose-500", desc: "Unified maritime & port detection", badge: "Full Port" },
];

// ── Main Component ───────────────────────────────────────────────────

export default function LiveCameraPage() {
  const transitCameraId = new URLSearchParams(window.location.search).get('camera_id') ?? '';

  // Stream & Session State
  const [cameraActive, setCameraActive] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState<DetectionMode>(() => new URLSearchParams(window.location.search).get('mode') === 'general' ? 'general' : 'human');
  const [confidence, setConfidence] = useState(0.5);
  const [track, setTrack] = useState(true);
  const [pose, setPose] = useState(!transitCameraId);
  const [quality, setQuality] = useState<LiveQuality>("fast");
  const [permissionState, setPermissionState] = useState<'prompt' | 'granted' | 'denied' | 'unknown'>('unknown');
  const [trackerResetNotice, setTrackerResetNotice] = useState<string | null>(null);

  // Active Rail Tab
  const [activeTab, setActiveTab] = useState<'device' | 'model' | 'automation'>('device');

  // Overlays & HUD options
  const [showBoxes, setShowBoxes] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Hardware devices
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');

  // Associated Transit/Fleet Camera
  const [association, setAssociation] = useState<Data | null>(null);
  const [busObservation, setBusObservation] = useState<Data | null>(null);
  const [roadObservation, setRoadObservation] = useState<Data | null>(null);

  // Performance Telemetry Stats
  const [lastFrame, setLastFrame] = useState<LiveFrame | null>(null);
  const [totalFrames, setTotalFrames] = useState(0);
  const [sessionDetections, setSessionDetections] = useState(0);
  const [cameraFps, setCameraFps] = useState(0);
  const [cameraFpsEstimated, setCameraFpsEstimated] = useState(false);
  const [detectionFps, setDetectionFps] = useState(0);
  const [roundTripMs, setRoundTripMs] = useState(0);
  const [cameraAspect, setCameraAspect] = useState(16 / 9);

  // Reports & Automation
  const [reports, setReports] = useState<ActivityReport[]>([]);
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null);
  const [now, setNow] = useState(Date.now());
  const [autoDownload, setAutoDownload] = useState(true);
  const [cameraStartedAt, setCameraStartedAt] = useState<string | null>(null);

  // Report Table UI State
  const [reportSearch, setReportSearch] = useState('');
  const [reportFilter, setReportFilter] = useState<'all' | 'full' | 'partial'>('all');
  const [selectedReports, setSelectedReports] = useState<Set<string>>(new Set());
  const [reportPage, setReportPage] = useState(1);
  const reportsPerPage = 6;

  // Shortcuts modal
  const [showShortcuts, setShowShortcuts] = useState(false);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const overlayOptionsRef = useRef({ boxes: true, labels: true });
  const latestOverlayFrameRef = useRef<LiveFrame | null>(null);
  const snapshotFrameRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const sendingRef = useRef(false);
  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const timeoutRef = useRef<number>(0);
  const captureSerialRef = useRef(0);
  const configRevisionRef = useRef(0);
  const configPendingRef = useRef(false);
  const lastConfigSentRef = useRef("");
  const captureStartedRef = useRef(0);
  const responseTimesRef = useRef<number[]>([]);
  const autoDownloadRef = useRef(true);
  const cameraTimeRef = useRef('');
  const statusReceivedRef = useRef(Date.now());
  const stopRequestedRef = useRef(false);

  const configRef = useRef({ mode, confidence, track, pose, quality });
  configRef.current = { mode, confidence, track, pose, quality };

  useEffect(() => { autoDownloadRef.current = autoDownload; }, [autoDownload]);

  // Check camera permissions
  useEffect(() => {
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: 'camera' as PermissionName }).then((status) => {
        setPermissionState(status.state as 'prompt' | 'granted' | 'denied');
        status.onchange = () => {
          setPermissionState(status.state as 'prompt' | 'granted' | 'denied');
        };
      }).catch(() => setPermissionState('unknown'));
    }
  }, []);

  // Periodic clock and initial reports fetch
  useEffect(() => {
    getActivityReports().then(setReports).catch(e => setError(e.message));
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Fleet association
  useEffect(() => {
    if (!transitCameraId) return;
    let active = true;
    transitRequest<Data>('/api/cameras').then(async (data) => {
      const camera = (data.cameras ?? []).find((item: Data) => item.id === transitCameraId);
      if (camera && active) setAssociation(camera);
      if (camera?.bus_id) {
        const bus = await transitRequest<Data>(`/api/buses/${camera.bus_id}`);
        if (active) setAssociation({ ...camera, registration_number: bus.registration_number, capacity: bus.capacity });
      }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [transitCameraId]);

  // Hardware enumerate devices
  useEffect(() => {
    const devices = navigator.mediaDevices;
    if (!devices?.enumerateDevices) return;
    let active = true;
    const refresh = () => devices.enumerateDevices().then(items => {
      if (active) setVideoDevices(items.filter(item => item.kind === 'videoinput'));
    }).catch(() => {});
    refresh(); devices.addEventListener?.('devicechange', refresh);
    return () => { active = false; devices.removeEventListener?.('devicechange', refresh); };
  }, []);

  const clearOverlay = useCallback(() => {
    const canvas = overlayRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    snapshotFrameRef.current = null;
    latestOverlayFrameRef.current = null;
  }, []);

  useEffect(() => {
    overlayOptionsRef.current = { boxes: showBoxes, labels: showLabels };
    if (overlayRef.current && latestOverlayFrameRef.current) {
      drawDetectionOverlay(overlayRef.current, latestOverlayFrameRef.current, overlayOptionsRef.current);
    }
  }, [showBoxes, showLabels]);

  // Decoded Camera FPS independent monitoring
  useEffect(() => {
    if (!cameraActive || !videoRef.current) { setCameraFps(0); setCameraFpsEstimated(false); return; }
    const video = videoRef.current;
    const hasFrameCallback = typeof video.requestVideoFrameCallback === 'function';
    let callbackId = 0;
    let callbackFrames = 0;
    let lastPresented = 0;
    const onVideoFrame = (_time: number, metadata: VideoFrameCallbackMetadata) => {
      callbackFrames += lastPresented ? Math.max(0, metadata.presentedFrames - lastPresented) : 1;
      lastPresented = metadata.presentedFrames;
      callbackId = video.requestVideoFrameCallback(onVideoFrame);
    };
    if (hasFrameCallback) callbackId = video.requestVideoFrameCallback(onVideoFrame);
    let previousFrames = video.getVideoPlaybackQuality?.().totalVideoFrames ?? 0;
    let previousCallbackFrames = 0;
    let previousTime = performance.now();
    const timer = window.setInterval(() => {
      const currentTime = performance.now();
      const frames = video.getVideoPlaybackQuality?.().totalVideoFrames;
      const estimated = !hasFrameCallback && !frames;
      const frameDelta = hasFrameCallback ? callbackFrames - previousCallbackFrames : Math.max(0, (frames ?? 0) - previousFrames);
      const fps = estimated ? streamRef.current?.getVideoTracks()[0]?.getSettings().frameRate ?? 0
        : frameDelta * 1000 / (currentTime - previousTime);
      setCameraFps(Math.round(fps * 10) / 10);
      setCameraFpsEstimated(estimated);
      previousFrames = frames ?? 0;
      previousCallbackFrames = callbackFrames;
      previousTime = currentTime;
    }, 1000);
    return () => { window.clearInterval(timer); if (hasFrameCallback) video.cancelVideoFrameCallback(callbackId); };
  }, [cameraActive]);

  // Camera start
  const startCamera = useCallback(async () => {
    setError(null);
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError('Camera access requires trusted HTTPS on a phone, or localhost on the laptop. Open Connect phone in the app for setup.');
      setPermissionState('denied');
      return;
    }
    try {
      streamRef.current?.getTracks().forEach(t => t.stop());
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 60 },
          ...(selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : { facingMode: { ideal: facingMode } })
        },
        audio: false,
      });
      if (!mountedRef.current) { stream.getTracks().forEach(t => t.stop()); return; }
      streamRef.current = stream;
      setPermissionState('granted');
      navigator.mediaDevices.enumerateDevices?.().then(items => setVideoDevices(items.filter(item => item.kind === 'videoinput'))).catch(() => {});
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        if (videoRef.current.videoHeight) setCameraAspect(videoRef.current.videoWidth / videoRef.current.videoHeight);
      }
      cameraTimeRef.current = new Date().toISOString();
      setCameraStartedAt(cameraTimeRef.current);
      setCameraActive(true);
    } catch (e: any) {
      setPermissionState('denied');
      const messages: Record<string, string> = {
        NotAllowedError: 'Camera permission denied. Allow this site to access your camera in browser settings.',
        NotFoundError: 'No camera hardware found on this system.',
        NotReadableError: 'The camera is currently occupied by another program. Close it and retry.',
        OverconstrainedError: 'The selected camera resolution or lens is unavailable. Reset to default camera.'
      };
      setError(messages[e?.name] ?? 'Could not initialize camera stream. Verify device permissions.');
    }
  }, [selectedDeviceId, facingMode]);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraActive(false);
    stopStreaming();
  }, []);

  // Frame sender
  const sendFrame = useCallback(() => {
    if (sendingRef.current || stopRequestedRef.current || configPendingRef.current || !mountedRef.current) return;
    if (!videoRef.current || !canvasRef.current || !wsRef.current) return;
    if (wsRef.current.readyState !== WebSocket.OPEN) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ws = wsRef.current;
    if (video.videoWidth === 0 || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || ws.bufferedAmount > 0) {
      rafRef.current = requestAnimationFrame(sendFrame);
      return;
    }

    const captureConfig = configRef.current;
    const settings = LIVE_QUALITY[captureConfig.quality];
    const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
    const width = Math.round(video.videoWidth * scale);
    const height = Math.round(video.videoHeight * scale);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) { setError('Camera frame could not be captured'); return; }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    sendingRef.current = true;
    captureStartedRef.current = performance.now();
    const serial = ++captureSerialRef.current;
    const generation = generationRef.current;
    const revision = configRevisionRef.current;
    try {
      canvas.toBlob(blob => {
        if (serial !== captureSerialRef.current || generation !== generationRef.current || wsRef.current !== ws) return;
        if (!mountedRef.current || stopRequestedRef.current || ws.readyState !== WebSocket.OPEN) { sendingRef.current = false; return; }
        const currentConfig = configRef.current;
        if (captureConfig.mode !== currentConfig.mode || captureConfig.confidence !== currentConfig.confidence || captureConfig.track !== currentConfig.track || captureConfig.pose !== currentConfig.pose || captureConfig.quality !== currentConfig.quality) {
          sendingRef.current = false;
          if (revision !== configRevisionRef.current && !configPendingRef.current) sendFrame();
          return;
        }
        if (revision !== configRevisionRef.current || configPendingRef.current) { sendingRef.current = false; sendFrame(); return; }
        if (!blob) { sendingRef.current = false; setError('Camera frame could not be encoded'); ws.close(); return; }
        try {
          ws.send(blob);
          clearTimeout(timeoutRef.current);
          timeoutRef.current = window.setTimeout(() => { if (wsRef.current === ws) { setError('Live inference timed out. Restart detection.'); ws.close(); } }, 125000);
        } catch { sendingRef.current = false; setError('Camera frame could not be sent'); ws.close(); }
      }, "image/jpeg", settings.jpegQuality);
    } catch { sendingRef.current = false; setError('Camera frame could not be sent'); }
  }, []);

  // WebSocket streaming
  const startStreaming = useCallback(async () => {
    if (!cameraActive || connecting || streaming) return;
    stopRequestedRef.current = false;
    setError(null); setConnecting(true); setLastFrame(null); setWarnings([]); setMonitoring(null);
    setBusObservation(null); setRoadObservation(null); clearOverlay(); setDetectionFps(0); setRoundTripMs(0);
    responseTimesRef.current = []; configPendingRef.current = false; sendingRef.current = false;
    ++captureSerialRef.current;
    const generation = ++generationRef.current;
    try {
      const ticket = await getLiveTicket();
      if (!mountedRef.current || generation !== generationRef.current) return;
      const endpoint = new URL(BASE_URL || window.location.origin, window.location.origin);
      endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:';
      endpoint.pathname = '/api/analyze/live';
      const settings = configRef.current;
      const inferenceSize = LIVE_QUALITY[settings.quality].size;
      lastConfigSentRef.current = JSON.stringify({ mode: settings.mode, confidence: settings.confidence, track: settings.track, pose: settings.pose, inference_size: inferenceSize, annotated: false });
      endpoint.search = new URLSearchParams({
        mode: settings.mode,
        confidence: String(settings.confidence),
        track: String(settings.track),
        pose: String(settings.pose),
        inference_size: String(inferenceSize),
        annotated: 'false',
        ticket,
        camera_started_at: cameraTimeRef.current,
        ...(transitCameraId ? { camera_id: transitCameraId } : {})
      }).toString();
      const ws = new WebSocket(endpoint);
      wsRef.current = ws;
      timeoutRef.current = window.setTimeout(() => { if (wsRef.current === ws) { setError('Live model did not respond. Restart detection.'); ws.close(); } }, 125000);

      ws.onmessage = (ev) => {
        if (wsRef.current !== ws || !mountedRef.current) return;
        try {
          const data: LiveFrame = JSON.parse(ev.data);
          if (data.monitoring) { statusReceivedRef.current = Date.now(); setMonitoring(data.monitoring); }
          if (data.type === 'report' && data.report) {
            const report = data.report;
            setReports(items => [report, ...items.filter(item => item.id !== report.id)].slice(0, 50));
            if (autoDownloadRef.current) downloadActivityReport(report).catch(e => setError(e.message));
            return;
          }
          if (data.type === 'stopped') { ws.close(); return; }
          if (data.warnings) setWarnings(data.warnings);
          if (data.error) {
            setError(data.error);
            if (!data.recoverable) { ws.close(); return; }
            sendingRef.current = false;
            rafRef.current = requestAnimationFrame(sendFrame);
            return;
          }
          if (data.type === 'ready') {
            if (stopRequestedRef.current) return;
            const current = configRef.current;
            configPendingRef.current = lastConfigSentRef.current !== JSON.stringify({ mode: current.mode, confidence: current.confidence, track: current.track, pose: current.pose, inference_size: LIVE_QUALITY[current.quality].size, annotated: false });
            clearTimeout(timeoutRef.current); setConnected(true); setStreaming(true); setConnecting(false);
            setTotalFrames(0); setSessionDetections(0); sendFrame(); return;
          }
          if (data.type === 'config_ack') {
            if (stopRequestedRef.current) return;
            if (data.config_id === configRevisionRef.current) {
              configPendingRef.current = false;
              clearTimeout(timeoutRef.current); clearOverlay(); sendFrame();
            }
            return;
          }
          if (data.type === 'detection') {
            if (stopRequestedRef.current) return;
            clearTimeout(timeoutRef.current);
            const receivedAt = performance.now();
            const samples = responseTimesRef.current;
            samples.push(receivedAt);
            while (samples.length > 1 && samples[0] < receivedAt - 2000) samples.shift();
            setDetectionFps(samples.length > 1 ? Math.round((samples.length - 1) * 10000 / (receivedAt - samples[0])) / 10 : 0);
            setRoundTripMs(Math.round(receivedAt - captureStartedRef.current));
            setTotalFrames(n => n + 1); setSessionDetections(n => n + data.total_objects);
            if (!configPendingRef.current) {
              setLastFrame(data);
              if (data.transit_observation?.bus_observation) setBusObservation(data.transit_observation.bus_observation);
              if (data.transit_observation && !data.transit_observation.bus_observation) setRoadObservation(data.transit_observation);
              latestOverlayFrameRef.current = data;
              if (overlayRef.current) drawDetectionOverlay(overlayRef.current, data, overlayOptionsRef.current);
              const captured = canvasRef.current;
              if (captured) {
                const saved = snapshotFrameRef.current ?? document.createElement('canvas');
                if (saved.width !== captured.width) saved.width = captured.width;
                if (saved.height !== captured.height) saved.height = captured.height;
                saved.getContext('2d')?.drawImage(captured, 0, 0);
                snapshotFrameRef.current = saved;
              }
            }
            sendingRef.current = false;
            if (configPendingRef.current) {
              timeoutRef.current = window.setTimeout(() => { if (wsRef.current === ws) { setError('Live model did not respond. Restart detection.'); ws.close(); } }, 125000);
            } else sendFrame();
          }
        } catch { setError('Invalid response from live detector'); ws.close(); }
      };

      ws.onerror = () => { if (wsRef.current === ws) setError('Cannot connect to live detection. Check that backend is running on port 8000.'); };
      ws.onclose = (event) => {
        if (wsRef.current !== ws) return;
        clearTimeout(timeoutRef.current); cancelAnimationFrame(rafRef.current); ++captureSerialRef.current;
        wsRef.current = null; sendingRef.current = false; configPendingRef.current = false; clearOverlay();
        if (!mountedRef.current) return;
        setConnecting(false); setConnected(false); setStreaming(false); setDetectionFps(0);
        getActivityReports().then(items => { if (mountedRef.current) setReports(items); }).catch(() => {});
        if (event.code === 1006) setError('Connection dropped. Verify network connection and retry.');
        if (event.code === 1013) setError('Live inference pipeline busy. Retrying in a few seconds...');
        if (event.code === 1008 && !event.wasClean) setError('Session unauthorized or model weights not initialized.');
      };
    } catch (e: any) {
      if (mountedRef.current && generation === generationRef.current) {
        setError(e.message || 'Could not start live detection'); setConnecting(false);
      }
    }
  }, [cameraActive, connecting, streaming, clearOverlay, transitCameraId, sendFrame]);

  const stopStreaming = useCallback(() => {
    ++generationRef.current;
    clearTimeout(timeoutRef.current);
    setConnecting(false);
    cancelAnimationFrame(rafRef.current);
    stopRequestedRef.current = true;
    ++captureSerialRef.current;
    configPendingRef.current = false;
    clearOverlay();
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN && mountedRef.current) {
      ws.send(JSON.stringify({ type: 'stop' }));
      setConnecting(true);
      timeoutRef.current = window.setTimeout(() => { if (wsRef.current === ws) ws.close(); }, 130000);
    } else {
      ws?.close();
      wsRef.current = null;
    }
    setStreaming(false);
    setConnected(false);
    setDetectionFps(0);
    sendingRef.current = false;
  }, [clearOverlay]);

  // Combined one-click launch or stop
  const toggleMasterStream = useCallback(async () => {
    if (!cameraActive) {
      await startCamera();
      // startStreaming will be ready once camera active
    } else if (!streaming) {
      startStreaming();
    } else {
      stopStreaming();
    }
  }, [cameraActive, streaming, startCamera, startStreaming, stopStreaming]);

  // Push configuration updates while live
  useEffect(() => {
    const ws = wsRef.current;
    if (!stopRequestedRef.current && connected && ws?.readyState === WebSocket.OPEN) {
      const config = { mode, confidence, track, pose, inference_size: LIVE_QUALITY[quality].size, annotated: false };
      const serialized = JSON.stringify(config);
      if (serialized === lastConfigSentRef.current) return;
      lastConfigSentRef.current = serialized;
      configPendingRef.current = true;
      const config_id = ++configRevisionRef.current;
      clearOverlay(); setLastFrame(null); setDetectionFps(0); responseTimesRef.current = [];
      ws.send(JSON.stringify({ type: "config", ...config, config_id }));
      clearTimeout(timeoutRef.current);
      timeoutRef.current = window.setTimeout(() => { if (wsRef.current === ws) { setError('Live model did not respond. Restart detection.'); ws.close(); } }, 125000);
    }
  }, [mode, confidence, track, pose, quality, connected, clearOverlay]);

  // Tracking reset notification
  const triggerTrackerResetNotice = (reason: string) => {
    setTrackerResetNotice(reason);
    window.setTimeout(() => setTrackerResetNotice(null), 3500);
  };

  const handleModeChange = (newMode: DetectionMode) => {
    setMode(newMode);
    triggerTrackerResetNotice(`Switched to ${MODES.find(m => m.value === newMode)?.label} — Tracking IDs reset`);
  };

  const handleTrackToggle = (val: boolean) => {
    setTrack(val);
    triggerTrackerResetNotice(`Object tracking ${val ? 'enabled' : 'disabled'} — Tracking IDs reset`);
  };

  // Keyboard shortcut listener
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName) || target.isContentEditable) return;

      if (e.code === 'Space') {
        e.preventDefault();
        toggleMasterStream();
      } else if (e.key === 'c' || e.key === 'C') {
        setActiveTab('device');
      } else if (e.key === 'm' || e.key === 'M') {
        setActiveTab('model');
      } else if (e.key === 'a' || e.key === 'A') {
        setActiveTab('automation');
      } else if (e.key === 's' || e.key === 'S') {
        downloadSnapshot();
      } else if (e.key === 'f' || e.key === 'F') {
        setFullscreen(v => !v);
      } else if (e.key === '?') {
        setShowShortcuts(v => !v);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [toggleMasterStream]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stopCamera();
      stopStreaming();
    };
  }, []);

  // Snapshot exporter
  const downloadSnapshot = () => {
    const captured = snapshotFrameRef.current;
    const overlay = overlayRef.current;
    if (!captured || !overlay) return;
    const snapshot = document.createElement("canvas");
    snapshot.width = captured.width; snapshot.height = captured.height;
    const ctx = snapshot.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(captured, 0, 0);
    ctx.drawImage(overlay, 0, 0, snapshot.width, snapshot.height);
    const a = document.createElement("a");
    a.href = snapshot.toDataURL("image/jpeg", 0.92);
    a.download = `transitopt-telemetry-snapshot-${Date.now()}.jpg`;
    a.click();
  };

  // Scene Density Index
  const sceneDensity = useMemo(() => {
    if (!lastFrame) return { score: 0, label: "Zero Load", color: "text-slate-400", badge: "bg-slate-500/10 text-slate-400" };
    const count = lastFrame.total_objects;
    if (count === 0) return { score: 0, label: "Clear / Low", color: "text-emerald-400", badge: "badge-green" };
    if (count <= 4) return { score: Math.round(count * 15), label: "Light Presence", color: "text-emerald-400", badge: "badge-green" };
    if (count <= 10) return { score: Math.round(count * 8), label: "Moderate Traffic", color: "text-amber-400", badge: "badge-orange" };
    return { score: Math.min(100, count * 7), label: "High Density / Congestion", color: "text-rose-400", badge: "badge-red" };
  }, [lastFrame]);

  // Reports Table filtering & pagination
  const filteredReports = useMemo(() => {
    return reports.filter(r => {
      if (reportFilter === 'full' && r.partial) return false;
      if (reportFilter === 'partial' && !r.partial) return false;
      if (reportSearch.trim()) {
        const query = reportSearch.toLowerCase();
        const str = `${r.file_name} ${r.started_at} ${r.frames_analyzed} ${r.unique_track_ids}`.toLowerCase();
        if (!str.includes(query)) return false;
      }
      return true;
    });
  }, [reports, reportFilter, reportSearch]);

  const totalReportPages = Math.ceil(filteredReports.length / reportsPerPage) || 1;
  const pagedReports = useMemo(() => {
    const start = (reportPage - 1) * reportsPerPage;
    return filteredReports.slice(start, start + reportsPerPage);
  }, [filteredReports, reportPage, reportsPerPage]);

  const toggleSelectAllReports = () => {
    if (selectedReports.size === pagedReports.length) {
      setSelectedReports(new Set());
    } else {
      setSelectedReports(new Set(pagedReports.map(r => r.id)));
    }
  };

  const toggleSelectReport = (id: string) => {
    setSelectedReports(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBulkExport = async () => {
    const targets = reports.filter(r => selectedReports.has(r.id));
    if (!targets.length) return;
    for (const report of targets) {
      await downloadActivityReport(report).catch(e => setError(e.message));
      await new Promise(res => setTimeout(res, 200));
    }
  };

  const modeInfo = MODES.find(m => m.value === mode) || MODES[0];
  const ModeIcon = modeInfo.icon;

  return (
    <div className="p-4 md:p-6 max-w-[1800px] mx-auto space-y-6">
      {/* ── Top Bar & Guided State Machine ──────────────────────────── */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-[var(--border-subtle)]">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[var(--accent-primary)] mb-1">
            <Shield size={14} /> Control Center · Live Computer Vision
            {association && (
              <span className="px-2 py-0.5 rounded-md bg-[var(--accent-primary-bg)] border border-[var(--border-focus)] text-[var(--accent-primary)]">
                Assigned: {association.name} ({association.registration_number ?? association.bus_id ?? association.corridor_id})
              </span>
            )}
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-[var(--text-heading)] flex items-center gap-3">
            <Camera className="text-[var(--accent-primary)]" size={30} />
            Camera ML Workspace
          </h1>
          <p className="text-xs md:text-sm text-[var(--text-secondary)] mt-0.5">
            Real-time YOLO multi-class object detection, ByteTrack trajectory forecasting, and pose gesture recognition.
          </p>
        </div>

        {/* Guided State Pipeline Indicator */}
        <div className="flex items-center gap-2 overflow-x-auto py-1">
          {/* Step 1 */}
          <button
            onClick={() => setActiveTab('device')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${
              cameraActive
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-[var(--bg-surface-elevated)] border-[var(--border-card)] text-[var(--text-secondary)] hover:border-[var(--border-focus)]"
            }`}
          >
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${
              cameraActive ? "bg-emerald-500 text-slate-950 font-bold" : "bg-slate-700 text-white"
            }`}>
              {cameraActive ? <Check size={12} /> : "1"}
            </span>
            <span>Camera Source</span>
          </button>
          <div className="w-3 h-0.5 bg-[var(--border-subtle)] hidden sm:block" />

          {/* Step 2 */}
          <button
            onClick={() => setActiveTab('model')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${
              activeTab === 'model'
                ? "bg-[var(--accent-primary-bg)] border-[var(--border-focus)] text-[var(--accent-primary)]"
                : "bg-[var(--bg-surface-elevated)] border-[var(--border-card)] text-[var(--text-secondary)] hover:border-[var(--border-focus)]"
            }`}
          >
            <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] bg-slate-700 text-white">
              2
            </span>
            <span>Model & Mode ({modeInfo.badge})</span>
          </button>
          <div className="w-3 h-0.5 bg-[var(--border-subtle)] hidden sm:block" />

          {/* Step 3 */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold ${
            streaming
              ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-sm"
              : "bg-[var(--bg-surface-elevated)] border-[var(--border-card)] text-[var(--text-muted)]"
          }`}>
            <span className={`w-2 h-2 rounded-full ${streaming ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} />
            <span>{streaming ? "Live Session Active" : "Stream Idle"}</span>
          </div>

          {/* Shortcuts Button */}
          <button
            onClick={() => setShowShortcuts(true)}
            className="p-1.5 ml-2 rounded-lg border border-[var(--border-card)] bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--accent-primary)] hover:border-[var(--border-focus)] transition-all"
            title="Keyboard Shortcuts (?)"
          >
            <Sliders size={15} />
          </button>
        </div>
      </div>

      {/* ── Dynamic Toast Warning for Tracker Reset ─────────────────── */}
      {trackerResetNotice && (
        <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl border border-amber-500/40 bg-amber-500/10 text-amber-300 text-xs font-medium animate-fadeIn">
          <RotateCcw size={15} className="animate-spin text-amber-400 shrink-0" />
          <span>{trackerResetNotice}</span>
        </div>
      )}

      {/* ── Error & Warning Banners ─────────────────────────────────── */}
      {error && (
        <div className="p-4 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 flex items-center gap-3">
          <AlertCircle className="text-rose-400 shrink-0" size={20} />
          <div className="flex-1 text-xs md:text-sm">
            <p className="font-semibold text-rose-200">Operational Notice</p>
            <p>{error}</p>
          </div>
          <button onClick={() => setError(null)} className="px-3 py-1 rounded-lg text-xs bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 font-semibold transition-all">
            Dismiss
          </button>
        </div>
      )}

      {warnings.map(w => (
        <div key={w} role="status" className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-300 text-xs flex items-center gap-2">
          <Info size={16} className="text-amber-400 shrink-0" />
          <span>{w}</span>
        </div>
      ))}

      {/* ── TWO-COLUMN OPERATIONAL LAYOUT: 65% Main Stage / 35% Control Rail ── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* ════ LEFT: MAIN STAGE (65% width / col-span-8) ════ */}
        <div className="lg:col-span-8 space-y-4">
          <div className={`relative glass overflow-hidden border border-[var(--border-card)] rounded-2xl shadow-xl bg-slate-950/80 transition-all ${
            fullscreen ? "fixed inset-0 z-50 p-4 bg-slate-950" : ""
          }`}>
            {/* Hidden canvas for image capture without blocking render */}
            <canvas ref={canvasRef} className="hidden" />

            {/* Video & Overlay Viewport */}
            <div
              className={cameraActive ? "relative w-full flex items-center justify-center bg-black/90 overflow-hidden" : "hidden"}
              style={{ aspectRatio: cameraAspect, maxHeight: fullscreen ? "calc(100vh - 140px)" : "680px" }}
            >
              <video
                ref={videoRef}
                aria-label="Live camera preview stream"
                className="block w-full h-full object-contain rounded-xl"
                onLoadedMetadata={e => {
                  if (e.currentTarget.videoHeight) setCameraAspect(e.currentTarget.videoWidth / e.currentTarget.videoHeight);
                }}
                playsInline muted autoPlay
              />
              <canvas
                ref={overlayRef}
                aria-label="AI detection overlay canvas"
                className="absolute inset-0 w-full h-full object-contain pointer-events-none"
              />
            </div>

            {/* Inactive Camera Stage Empty View */}
            {!cameraActive && (
              <div className="flex flex-col items-center justify-center py-20 px-6 text-center" style={{ minHeight: "440px" }}>
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--accent-primary-bg)] to-cyan-500/10 border border-[var(--border-focus)] flex items-center justify-center mb-5 shadow-lg shadow-cyan-500/5">
                  <Camera size={38} className="text-[var(--accent-primary)] animate-pulse" />
                </div>
                <h2 className="text-xl font-bold text-[var(--text-heading)] mb-1.5">Live Vision Stream Disconnected</h2>
                <p className="text-xs md:text-sm text-[var(--text-secondary)] max-w-md mb-6 leading-relaxed">
                  Connect your video device to initialize edge frame sampling and feed real-time inferences into the telemetry dashboard.
                </p>
                <div className="flex flex-wrap items-center justify-center gap-3">
                  <button
                    onClick={startCamera}
                    className="btn-primary px-6 py-3 rounded-xl font-bold text-sm flex items-center gap-2.5 shadow-lg shadow-cyan-500/20"
                  >
                    <Camera size={18} /> Enable Camera Stream
                  </button>
                  <button
                    onClick={() => setActiveTab('device')}
                    className="btn-secondary px-5 py-3 rounded-xl font-semibold text-sm flex items-center gap-2"
                  >
                    <Settings size={16} /> Device Preferences
                  </button>
                </div>
                <div className="mt-6 flex items-center gap-2 text-xs text-[var(--text-muted)]">
                  <span className={`w-2 h-2 rounded-full ${permissionState === 'granted' ? 'bg-emerald-400' : permissionState === 'denied' ? 'bg-rose-400' : 'bg-amber-400'}`} />
                  Browser Permission: <strong className="capitalize text-[var(--text-heading)]">{permissionState}</strong>
                </div>
              </div>
            )}

            {/* ── TOP HUD TELEMETRY OVERLAY ──────────────────────────── */}
            {cameraActive && (
              <>
                {/* Top-Left: Status Chip + Mode Badge */}
                <div className="absolute top-3.5 left-3.5 flex items-center gap-2.5 z-10 flex-wrap">
                  <div className={`px-3 py-1.5 rounded-lg text-xs font-bold tracking-wide flex items-center gap-2 shadow-lg backdrop-blur-md ${
                    streaming
                      ? "bg-slate-900/85 text-emerald-400 border border-emerald-500/40"
                      : connecting
                      ? "bg-slate-900/85 text-amber-300 border border-amber-500/40"
                      : "bg-slate-900/85 text-slate-300 border border-slate-700"
                  }`}>
                    <span className={`w-2 h-2 rounded-full ${
                      streaming ? "bg-emerald-400 animate-pulse" : connecting ? "bg-amber-400 animate-ping" : "bg-slate-500"
                    }`} />
                    <span>{streaming ? "ACTIVE" : connecting ? "CONNECTING..." : "CAMERA READY"}</span>
                  </div>

                  <span className={`px-2.5 py-1.5 rounded-lg text-xs font-bold text-white bg-gradient-to-r ${modeInfo.color} shadow-md flex items-center gap-1.5 backdrop-blur-md`}>
                    <ModeIcon size={12} />
                    {modeInfo.label.toUpperCase()}
                  </span>
                </div>

                {/* Top-Right: Comprehensive Telemetry HUD */}
                <div className="absolute top-3.5 right-3.5 flex flex-wrap justify-end gap-1.5 max-w-[65%] z-10">
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-black/75 text-emerald-300 border border-emerald-500/20 backdrop-blur-md shadow-sm">
                    <strong>{cameraFps}</strong> cam FPS
                  </span>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-black/75 text-cyan-300 border border-cyan-500/20 backdrop-blur-md shadow-sm">
                    <strong>{detectionFps}</strong> ai FPS
                  </span>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-black/75 text-slate-200 border border-slate-700/60 backdrop-blur-md shadow-sm">
                    <strong>{roundTripMs}</strong>ms lag
                  </span>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-black/75 text-purple-300 border border-purple-500/20 backdrop-blur-md shadow-sm">
                    <strong>{lastFrame?.unique_count ?? 0}</strong> IDs
                  </span>
                </div>

                {/* Bottom-Left: Live Density & Object Counter */}
                {streaming && (
                  <div className="absolute bottom-3.5 left-3.5 flex items-center gap-2 z-10">
                    <span className="px-3 py-1.5 rounded-lg text-xs font-bold bg-black/80 text-yellow-300 border border-yellow-500/30 backdrop-blur-md shadow-lg flex items-center gap-1.5">
                      <Zap size={13} className="text-yellow-400" />
                      {lastFrame?.total_objects ?? 0} Detected
                    </span>
                    <span className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-black/80 border border-slate-700/60 backdrop-blur-md shadow-lg ${sceneDensity.color}`}>
                      Density: {sceneDensity.label} ({sceneDensity.score}/100)
                    </span>
                  </div>
                )}
              </>
            )}

            {/* Fullscreen Button */}
            <button
              onClick={() => setFullscreen(!fullscreen)}
              className="absolute bottom-3.5 right-3.5 p-2 rounded-lg bg-black/60 text-slate-200 hover:text-white hover:bg-black/80 transition-all backdrop-blur-md border border-slate-700/40 z-10"
              title="Toggle Fullscreen (F)"
            >
              {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          </div>

          {/* ── UNIFIED PRIMARY OPERATIONAL DOCK ──────────────────────── */}
          <div className="glass p-3 md:p-4 rounded-xl border border-[var(--border-card)] flex flex-wrap items-center justify-between gap-3 shadow-md bg-[var(--bg-surface-elevated)]">
            {/* Master Action & Quick Camera Switch */}
            <div className="flex items-center gap-2.5">
              {!cameraActive ? (
                <button
                  onClick={startCamera}
                  className="btn-primary px-5 py-2.5 rounded-xl font-bold text-xs md:text-sm flex items-center gap-2 shadow-md shadow-cyan-500/20"
                >
                  <Camera size={16} /> Start Camera
                </button>
              ) : !streaming ? (
                <button
                  onClick={startStreaming}
                  disabled={connecting}
                  className="btn-primary px-5 py-2.5 rounded-xl font-bold text-xs md:text-sm flex items-center gap-2 shadow-md shadow-cyan-500/20 disabled:opacity-50"
                >
                  <Play size={16} /> {connecting ? "Loading Model..." : "Launch Stream (Space)"}
                </button>
              ) : (
                <button
                  onClick={stopStreaming}
                  className="px-5 py-2.5 rounded-xl font-bold text-xs md:text-sm flex items-center gap-2 bg-rose-500/20 border border-rose-500/40 text-rose-300 hover:bg-rose-500/30 transition-all shadow-md shadow-rose-500/10"
                >
                  <Square size={16} /> Stop Stream (Space)
                </button>
              )}

              {cameraActive && (
                <button
                  onClick={stopCamera}
                  className="px-3.5 py-2.5 rounded-xl text-xs font-semibold border border-[var(--border-card)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:text-rose-400 hover:border-rose-500/30 transition-all"
                  title="Shut off video capture"
                >
                  <CameraOff size={15} />
                </button>
              )}

              <button
                onClick={downloadSnapshot}
                disabled={!lastFrame}
                className="px-3.5 py-2.5 rounded-xl text-xs font-semibold border border-[var(--border-card)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:text-[var(--accent-primary)] hover:border-[var(--border-focus)] transition-all disabled:opacity-40 flex items-center gap-1.5"
                title="Instant Snapshot (S)"
              >
                <Download size={14} />
                <span className="hidden sm:inline">Snapshot</span>
              </button>
            </div>

            {/* Overlay Display Toggles */}
            <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)]">
              <label className="flex items-center gap-1.5 cursor-pointer hover:text-[var(--text-main)] select-none">
                <input
                  type="checkbox"
                  checked={showBoxes}
                  onChange={e => setShowBoxes(e.target.checked)}
                  className="accent-[var(--accent-primary)] rounded w-3.5 h-3.5"
                />
                <span>Boxes</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer hover:text-[var(--text-main)] select-none">
                <input
                  type="checkbox"
                  checked={showLabels}
                  onChange={e => setShowLabels(e.target.checked)}
                  className="accent-[var(--accent-primary)] rounded w-3.5 h-3.5"
                />
                <span>Labels</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer hover:text-[var(--text-main)] select-none">
                <input
                  type="checkbox"
                  checked={track}
                  onChange={e => handleTrackToggle(e.target.checked)}
                  className="accent-[var(--accent-primary)] rounded w-3.5 h-3.5"
                />
                <span>Trails</span>
              </label>

              {mode === 'human' && (
                <label className="flex items-center gap-1.5 cursor-pointer hover:text-[var(--text-main)] select-none text-purple-400">
                  <input
                    type="checkbox"
                    checked={pose}
                    onChange={e => {
                      setPose(e.target.checked);
                      triggerTrackerResetNotice(`Skeleton tracking ${e.target.checked ? 'enabled' : 'disabled'}`);
                    }}
                    className="accent-purple-400 rounded w-3.5 h-3.5"
                  />
                  <span>Skeleton</span>
                </label>
              )}
            </div>
          </div>

          {/* ── Human Posture & Action Analysis Tray (When Human Mode Active) ── */}
          {mode === 'human' && pose && (
            <div className="glass p-4 rounded-xl border border-[var(--border-card)] space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-purple-300 flex items-center gap-2">
                  <Users size={14} /> Real-Time Posture & Gesture Telemetry
                </h3>
                <span className="text-[11px] text-[var(--text-muted)]">
                  Standing, sitting, waving & gesture estimates
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
                {lastFrame?.detections.filter(d => d.class === 'person').map(det => (
                  <div key={det.id} className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-200">Person {det.track_id != null ? `#${det.track_id}` : '(untracked)'}</span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20">
                        {Math.round(det.confidence * 100)}%
                      </span>
                    </div>
                    <p className="text-purple-300 font-medium">
                      {det.action_estimates?.length ? det.action_estimates.join(' · ') : 'Awaiting motion pattern'}
                    </p>
                    <p className="text-[10px] text-[var(--text-muted)] truncate">
                      {det.pose_observations?.join(' · ') || 'Standard posture'}{det.activity ? ` · ${det.activity}` : ''}
                    </p>
                  </div>
                ))}
              </div>
              {!lastFrame?.detections.some(d => d.class === 'person') && (
                <p className="text-xs text-[var(--text-muted)] italic text-center py-2">
                  No person currently detected in camera frame. Stand or move into the camera field of view.
                </p>
              )}
            </div>
          )}

          {/* Fleet Speed Sensor (When Associated) */}
          {association?.role === 'bus_road' && (
            <div className="glass p-4 rounded-xl border border-[var(--border-card)] space-y-2">
              <BusSpeedGps busId={association.bus_id} />
              <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                <span>Forward Road Camera · GPS Speed: <strong>{roadObservation?.bus_speed_kmh != null ? `${roadObservation.bus_speed_kmh} km/h` : 'Awaiting GPS'}</strong></span>
                <span className="text-[var(--accent-primary)]">{roadObservation?.speed_observation?.state?.replaceAll('_', ' ') ?? 'Recording'}</span>
              </div>
            </div>
          )}
        </div>

        {/* ════ RIGHT: CONTROL RAIL (35% width / col-span-4) ════ */}
        <div className="lg:col-span-4 space-y-4">
          <div className="glass rounded-2xl border border-[var(--border-card)] shadow-xl overflow-hidden bg-[var(--bg-surface-elevated)]">
            {/* Control Rail Tab Header */}
            <div className="flex border-b border-[var(--border-subtle)] bg-[var(--bg-surface-alt)]">
              <button
                onClick={() => setActiveTab('device')}
                className={`flex-1 py-3 px-2 text-center text-xs font-bold transition-all border-b-2 flex items-center justify-center gap-1.5 ${
                  activeTab === 'device'
                    ? "border-[var(--accent-primary)] text-[var(--accent-primary)] bg-[var(--bg-surface)]"
                    : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-main)]"
                }`}
              >
                <Camera size={14} />
                <span>Device</span>
              </button>

              <button
                onClick={() => setActiveTab('model')}
                className={`flex-1 py-3 px-2 text-center text-xs font-bold transition-all border-b-2 flex items-center justify-center gap-1.5 ${
                  activeTab === 'model'
                    ? "border-[var(--accent-primary)] text-[var(--accent-primary)] bg-[var(--bg-surface)]"
                    : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-main)]"
                }`}
              >
                <BrainIcon size={14} />
                <span>Model & AI</span>
              </button>

              <button
                onClick={() => setActiveTab('automation')}
                className={`flex-1 py-3 px-2 text-center text-xs font-bold transition-all border-b-2 flex items-center justify-center gap-1.5 ${
                  activeTab === 'automation'
                    ? "border-[var(--accent-primary)] text-[var(--accent-primary)] bg-[var(--bg-surface)]"
                    : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-main)]"
                }`}
              >
                <Clock size={14} />
                <span>Audit & Log</span>
              </button>
            </div>

            {/* Tab 1: Device & Stream Settings */}
            {activeTab === 'device' && (
              <div className="p-5 space-y-4">
                <div>
                  <label className="block text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                    Hardware Camera Source
                  </label>
                  <select
                    aria-label="Video input source selector"
                    value={selectedDeviceId}
                    disabled={cameraActive}
                    onChange={e => setSelectedDeviceId(e.target.value)}
                    className="w-full rounded-xl bg-[var(--bg-input)] px-3.5 py-2.5 text-xs text-[var(--text-primary)] border border-[var(--border-input)] focus:border-[var(--border-focus)] transition-all"
                  >
                    <option value="">Default System Webcam</option>
                    {videoDevices.map((device, index) => (
                      <option key={device.deviceId || index} value={device.deviceId}>
                        {device.label || `Video Input Device #${index + 1}`}
                      </option>
                    ))}
                  </select>
                  {cameraActive && (
                    <p className="text-[10px] text-[var(--text-muted)] mt-1">
                      Turn off camera stream to change active hardware device.
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                    Lens Orientation (Mobile / Phone)
                  </label>
                  <select
                    aria-label="Lens orientation facing mode"
                    value={facingMode}
                    disabled={cameraActive || !!selectedDeviceId}
                    onChange={e => setFacingMode(e.target.value as 'environment' | 'user')}
                    className="w-full rounded-xl bg-[var(--bg-input)] px-3.5 py-2.5 text-xs text-[var(--text-primary)] border border-[var(--border-input)] focus:border-[var(--border-focus)] transition-all"
                  >
                    <option value="environment">Rear / Environment Lens (Recommended)</option>
                    <option value="user">Front / User Selfie Lens</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                    Resolution & Pipeline Latency
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {(Object.keys(LIVE_QUALITY) as LiveQuality[]).map(qKey => {
                      const qConf = LIVE_QUALITY[qKey];
                      return (
                        <button
                          key={qKey}
                          onClick={() => setQuality(qKey)}
                          className={`p-2.5 rounded-xl border text-center transition-all ${
                            quality === qKey
                              ? "bg-[var(--accent-primary-bg)] border-[var(--border-focus)] text-[var(--accent-primary)] font-bold shadow-sm"
                              : "bg-[var(--bg-surface)] border-[var(--border-card)] text-[var(--text-secondary)] hover:border-[var(--border-card-hover)]"
                          }`}
                        >
                          <p className="text-xs capitalize">{qKey}</p>
                          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{qConf.size}px</p>
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[10px] text-[var(--text-muted)] mt-1.5">
                    Fast processes smaller frames at high FPS; Detail uses 640px for distant objects.
                  </p>
                </div>

                {/* Device Telemetry Card */}
                <div className="p-3.5 rounded-xl bg-[var(--bg-surface-alt)] border border-[var(--border-card)] text-xs space-y-2">
                  <div className="flex justify-between items-center text-[var(--text-secondary)]">
                    <span>Aspect Ratio:</span>
                    <strong className="text-[var(--text-heading)] font-mono">{cameraAspect.toFixed(2)}:1</strong>
                  </div>
                  <div className="flex justify-between items-center text-[var(--text-secondary)]">
                    <span>Browser Permission:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      permissionState === 'granted' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' :
                      permissionState === 'denied' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30' :
                      'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                    }`}>
                      {permissionState}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[var(--text-secondary)]">
                    <span>Active Session:</span>
                    <span className="text-[var(--text-heading)]">{cameraActive ? "Capturing" : "Idle"}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 2: Detection Model & Sensitivity */}
            {activeTab === 'model' && (
              <div className="p-5 space-y-4">
                <div>
                  <label className="block text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    Detection Model Mode
                  </label>
                  <div className="space-y-2">
                    {MODES.map(m => (
                      <button
                        key={m.value}
                        disabled={Boolean(association && ((association.role === 'bus_interior' && m.value !== 'human') || (['road_traffic', 'bus_road'].includes(association.role) && m.value !== 'general')))}
                        onClick={() => handleModeChange(m.value)}
                        className={`w-full flex items-center gap-3 p-3 rounded-xl border text-left transition-all ${
                          mode === m.value
                            ? "bg-[var(--accent-primary-bg)] border-[var(--border-focus)] text-[var(--text-heading)] shadow-sm"
                            : "bg-[var(--bg-surface)] border-[var(--border-card)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
                        }`}
                      >
                        <m.icon size={18} className={mode === m.value ? "text-[var(--accent-primary)]" : "text-slate-400"} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-xs">{m.label}</span>
                            <span className="text-[9.5px] font-semibold px-1.5 py-0.5 rounded bg-slate-800 text-[var(--text-muted)]">
                              {m.badge}
                            </span>
                          </div>
                          <p className="text-[10.5px] text-[var(--text-muted)] truncate mt-0.5">{m.desc}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Dual Confidence Threshold Controls */}
                <div className="p-3.5 rounded-xl bg-[var(--bg-surface-alt)] border border-[var(--border-card)] space-y-2.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                      Confidence Cutoff
                    </label>
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number"
                        min="10"
                        max="95"
                        step="1"
                        value={Math.round(confidence * 100)}
                        onChange={e => {
                          const val = Math.max(10, Math.min(95, Number(e.target.value)));
                          setConfidence(val / 100);
                        }}
                        className="w-14 text-center rounded-lg bg-[var(--bg-input)] border border-[var(--border-input)] text-xs font-mono font-bold text-[var(--accent-primary)] py-1"
                      />
                      <span className="text-xs text-[var(--text-muted)] font-mono">%</span>
                    </div>
                  </div>

                  <input
                    aria-label="Confidence Threshold Slider"
                    type="range"
                    min={0.10}
                    max={0.95}
                    step={0.05}
                    value={confidence}
                    onChange={e => setConfidence(parseFloat(e.target.value))}
                    className="w-full accent-[var(--accent-primary)] cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-[var(--text-muted)] font-mono">
                    <span>10% (High Recall)</span>
                    <span>50% (Balanced)</span>
                    <span>95% (High Precision)</span>
                  </div>
                </div>

                {/* Tracking & Trails */}
                <div className="space-y-2">
                  <label className="flex items-center justify-between p-3 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-card)] text-xs cursor-pointer hover:border-[var(--border-focus)] transition-all">
                    <div className="space-y-0.5">
                      <span className="font-semibold text-[var(--text-heading)]">ByteTrack Entity Tracking</span>
                      <p className="text-[10px] text-[var(--text-muted)]">Assigns persistent tracking IDs and draws trajectory vectors</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={track}
                      onChange={e => handleTrackToggle(e.target.checked)}
                      className="accent-[var(--accent-primary)] w-4 h-4 rounded"
                    />
                  </label>
                </div>
              </div>
            )}

            {/* Tab 3: Automation & Logging */}
            {activeTab === 'automation' && (
              <div className="p-5 space-y-4">
                <div className="p-4 rounded-xl bg-gradient-to-br from-[var(--bg-surface-alt)] to-[var(--bg-surface)] border border-[var(--border-card)] space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-[var(--text-heading)] flex items-center gap-2">
                      <Clock size={15} className="text-[var(--accent-primary)]" />
                      10-Minute Audit Interval
                    </span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] font-bold">
                      {streaming && monitoring ? `${duration(Math.max(0, monitoring.next_report_in_seconds - Math.floor((now - statusReceivedRef.current) / 1000)))} remaining` : "Idle"}
                    </span>
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                    Automated snapshots of object counts, dwell times, and motion trajectories compile every 10 minutes into an audit log.
                  </p>
                  <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={autoDownload}
                      onChange={e => setAutoDownload(e.target.checked)}
                      className="accent-[var(--accent-primary)] rounded w-3.5 h-3.5"
                    />
                    <span>Automatically trigger browser file download on interval</span>
                  </label>
                </div>

                {/* Recent Activity Event Stream */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                      Recent Activity Stream
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)]">Live Event Log</span>
                  </div>
                  <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                    {monitoring?.recent_actions.length ? (
                      [...monitoring.recent_actions].reverse().slice(0, 8).map((event, idx) => (
                        <div key={`${event.time}-${idx}`} className="p-2 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[11px] flex items-center justify-between">
                          <span className="text-[var(--text-heading)] font-medium">
                            {event.object} #{event.track_id}: <strong className="text-[var(--accent-primary)]">{event.action}</strong> {event.direction ? `(${event.direction})` : ''}
                          </span>
                          <span className="font-mono text-[10px] text-[var(--text-muted)]">{localTime(event.time)}</span>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-[var(--text-muted)] text-center py-6">
                        No events recorded yet. Launch detection stream to monitor activity.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ════ BOTTOM SECTION: SAVED AUDIT REPORTS DATA TABLE ════ */}
      <section className="glass p-5 md:p-6 rounded-2xl border border-[var(--border-card)] shadow-xl space-y-4 bg-[var(--bg-surface-elevated)]">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
          <div>
            <h2 className="text-lg font-bold text-[var(--text-heading)] flex items-center gap-2.5">
              <FileText className="text-[var(--accent-primary)]" size={20} />
              Saved Inspection Audit Reports
            </h2>
            <p className="text-xs text-[var(--text-secondary)]">
              Historical interval records capturing analyzed frames, active tracking IDs, and dwell classifications.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {selectedReports.size > 0 && (
              <button
                onClick={handleBulkExport}
                className="px-3.5 py-2 rounded-xl text-xs font-bold bg-[var(--accent-primary)] text-slate-950 flex items-center gap-2 shadow-sm hover:opacity-90 transition-all"
              >
                <Download size={14} /> Export Selected ({selectedReports.size})
              </button>
            )}

            <button
              onClick={() => getActivityReports().then(setReports).catch(() => {})}
              className="p-2 rounded-xl border border-[var(--border-card)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:text-[var(--accent-primary)] transition-all"
              title="Refresh Reports"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {/* Table Filters and Search Toolbar */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={15} />
            <input
              type="text"
              placeholder="Search reports by filename or frame count..."
              value={reportSearch}
              onChange={e => { setReportSearch(e.target.value); setReportPage(1); }}
              className="w-full pl-9 pr-4 py-2 rounded-xl bg-[var(--bg-input)] border border-[var(--border-input)] text-xs text-[var(--text-primary)] focus:border-[var(--border-focus)] transition-all"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Filter:</span>
            <select
              value={reportFilter}
              onChange={e => { setReportFilter(e.target.value as any); setReportPage(1); }}
              className="rounded-xl bg-[var(--bg-input)] border border-[var(--border-input)] px-3 py-1.5 text-xs text-[var(--text-primary)]"
            >
              <option value="all">All Intervals ({reports.length})</option>
              <option value="full">Full Intervals (10-min)</option>
              <option value="partial">Partial Intervals</option>
            </select>
          </div>
        </div>

        {/* Compact, High-Density Table */}
        <div className="overflow-x-auto border border-[var(--border-subtle)] rounded-xl">
          <table className="to-data-table">
            <thead>
              <tr>
                <th className="w-10 text-center">
                  <button
                    onClick={toggleSelectAllReports}
                    className="p-1 hover:text-[var(--accent-primary)]"
                  >
                    {selectedReports.size === pagedReports.length && pagedReports.length > 0 ? (
                      <CheckSquare size={15} className="text-[var(--accent-primary)]" />
                    ) : (
                      <BoxIcon size={15} />
                    )}
                  </button>
                </th>
                <th>Time Window (IST)</th>
                <th>Interval Type</th>
                <th>Frames Analyzed</th>
                <th>Tracked Unique IDs</th>
                <th>Log File Name</th>
                <th className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {pagedReports.length > 0 ? (
                pagedReports.map(report => (
                  <tr key={report.id} className={selectedReports.has(report.id) ? "bg-[var(--accent-primary-bg)]" : ""}>
                    <td className="text-center">
                      <input
                        type="checkbox"
                        checked={selectedReports.has(report.id)}
                        onChange={() => toggleSelectReport(report.id)}
                        className="accent-[var(--accent-primary)] rounded w-3.5 h-3.5"
                      />
                    </td>
                    <td>
                      <div>
                        <strong>{localDate(report.started_at)}</strong>
                        <span className="text-[10px] text-[var(--text-muted)] block">
                          {localTime(report.started_at)} → {localTime(report.ended_at)}
                        </span>
                      </div>
                    </td>
                    <td>
                      <span className={`to-status ${report.partial ? 'moderate' : 'activated'}`}>
                        {report.partial ? 'Partial' : 'Full (10m)'}
                      </span>
                    </td>
                    <td className="font-mono text-xs">{report.frames_analyzed.toLocaleString()} frames</td>
                    <td className="font-mono text-xs text-purple-400 font-bold">{report.unique_track_ids} IDs</td>
                    <td className="font-mono text-[11px] text-[var(--text-muted)] truncate max-w-[200px]" title={report.file_name}>
                      {report.file_name}
                    </td>
                    <td className="text-right">
                      <button
                        onClick={() => downloadActivityReport(report).catch(e => setError(e.message))}
                        className="to-button subtle py-1 px-2.5 text-xs inline-flex items-center gap-1.5"
                      >
                        <Download size={13} /> Download .txt
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="text-center py-10 text-[var(--text-muted)] text-xs">
                    No inspection activity reports match your filter criteria.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        <div className="flex items-center justify-between text-xs text-[var(--text-secondary)] pt-2">
          <span>
            Showing {filteredReports.length ? (reportPage - 1) * reportsPerPage + 1 : 0}–{Math.min(reportPage * reportsPerPage, filteredReports.length)} of {filteredReports.length} reports
          </span>

          <div className="flex items-center gap-2">
            <button
              disabled={reportPage <= 1}
              onClick={() => setReportPage(p => p - 1)}
              className="p-1.5 rounded-lg border border-[var(--border-card)] disabled:opacity-40 hover:bg-[var(--bg-surface-hover)]"
            >
              <ChevronLeft size={15} />
            </button>
            <span className="font-mono px-2">{reportPage} / {totalReportPages}</span>
            <button
              disabled={reportPage >= totalReportPages}
              onClick={() => setReportPage(p => p + 1)}
              className="p-1.5 rounded-lg border border-[var(--border-card)] disabled:opacity-40 hover:bg-[var(--bg-surface-hover)]"
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </div>
      </section>

      {/* ── Keyboard Shortcuts Modal ─────────────────────────────────── */}
      {showShortcuts && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="glass p-6 rounded-2xl border border-[var(--border-focus)] max-w-md w-full space-y-4 shadow-2xl bg-[var(--bg-surface-elevated)]">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-[var(--text-heading)] flex items-center gap-2">
                <Sliders className="text-[var(--accent-primary)]" size={18} />
                Operational Keyboard Shortcuts
              </h3>
              <button onClick={() => setShowShortcuts(false)} className="text-[var(--text-muted)] hover:text-white text-lg">✕</button>
            </div>
            <div className="space-y-2 text-xs">
              {[
                { key: "Space", desc: "Start / Stop live detection stream" },
                { key: "S", desc: "Instant annotated telemetry snapshot" },
                { key: "C", desc: "Switch to Camera & Device settings tab" },
                { key: "M", desc: "Switch to Detection Model & Confidence tab" },
                { key: "A", desc: "Switch to Automation & Audit Log tab" },
                { key: "F", desc: "Toggle Fullscreen mode" },
                { key: "?", desc: "Open this keyboard reference" },
              ].map(item => (
                <div key={item.key} className="flex justify-between items-center p-2 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-card)]">
                  <span className="text-[var(--text-secondary)]">{item.desc}</span>
                  <kbd className="px-2 py-0.5 rounded bg-slate-800 text-[var(--accent-primary)] font-mono font-bold border border-slate-700">{item.key}</kbd>
                </div>
              ))}
            </div>
            <button
              onClick={() => setShowShortcuts(false)}
              className="btn-primary w-full py-2.5 rounded-xl text-xs font-bold mt-2"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function BrainIcon({ size = 16 }: { size?: number }) {
  return <Zap size={size} />;
}
