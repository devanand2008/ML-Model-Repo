/**
 * VisionX AI Analyzer — API service layer
 * All backend calls go through this module.
 */

const configuredApiUrl = (import.meta.env.VITE_API_URL ?? "").trim().replace(/\/$/, '');
function resolveApiBase(): string {
  if (!configuredApiUrl) return '';
  // localhost and 127.0.0.1 point to the same local server, but are different
  // browser origins. Use relative requests when both refer to this app's port.
  try {
    const api = new URL(configuredApiUrl, window.location.origin);
    const localHosts = new Set(['localhost', '127.0.0.1', '[::1]']);
    if (localHosts.has(api.hostname) && localHosts.has(window.location.hostname)
      && api.port === window.location.port && api.protocol === window.location.protocol
      && api.pathname === '/' && !api.search && !api.hash) return '';
  } catch { /* Other deployments retain their explicitly configured API URL. */ }
  return configuredApiUrl;
}
export const BASE_URL = resolveApiBase();

let authorization = '';
export function setCredentials(username: string, password: string) {
  authorization='Basic '+btoa(String.fromCharCode(...new TextEncoder().encode(`${username}:${password}`)));
}
export async function request(url: string, init: RequestInit = {}) {
  const headers=new Headers(init.headers);
  if(authorization)headers.set('Authorization',authorization);
  return fetch(url,{...init,headers});
}
async function mutation(url: string, init: RequestInit) {
  const res=await request(url,init);
  const data=await res.json();
  if(!res.ok)throw new Error(data.detail || data.error || 'Request failed');
  return data;
}
export async function session() {
  const controller = new AbortController();
  const timer = window.setTimeout(()=>controller.abort(),5000);
  try {
    const response = await request(`${BASE_URL}/api/session`, {signal:controller.signal,cache:'no-store'});
    if(response.ok){
      const data = await response.clone().json();
      if(typeof data.username !== 'string')throw new Error('The website address is not connected to the VisionX backend.');
    }
    return response;
  } finally {window.clearTimeout(timer);}
}

export interface ActivityReport {
  id:string; started_at:string; ended_at:string; camera_started_at:string;
  partial:boolean; frames_analyzed:number; unique_track_ids:number; file_name:string; download_url:string;
}
export async function getActivityReports():Promise<ActivityReport[]> {
  return (await get<{reports:ActivityReport[]}>('/api/reports')).reports;
}
export async function downloadActivityReport(report:ActivityReport) {
  const response = await request(`${BASE_URL}${report.download_url}`);
  if(!response.ok)throw new Error('Report download failed. Check the backend connection.');
  const url=URL.createObjectURL(await response.blob());
  const link=document.createElement('a');link.href=url;link.download=report.file_name;link.click();
  window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export interface Detection {
  id: number;
  class: string;
  class_id: number;
  confidence: number;
  bbox: [number, number, number, number]; // x, y, w, h
  condition?: string;
  condition_confidence?: number;
  track_id?: number;
  position?: string;
  source?: string;
}

export interface AnalysisResult {
  warnings?: string[];
  processed_image?: string;
  unique_count?: number;
  inference_fps?: number;
  timeline?: { frame: number; seconds: number; visible: number }[];
  success: boolean;
  analysis_id: number;
  processing_time: number;
  detections: Detection[];
  counts: Record<string, number>;
  keypoints?: Array<Array<[number, number, number]>>;
  condition?: {
    total_containers: number | null;
    good: number | null;
    damaged: number | null;
    damaged_pct: number | null;
    good_pct: number | null;
    condition_model_active: boolean;
  };
  annotated_image?: string; // base64 data URL
  image_width?: number;
  image_height?: number;
  model_info?: {
    name: string;
    type: string;
    filename: string;
  };
  // combined
  people?: number;
  ships?: number;
  containers?: number;
  trucks?: number;
  other?: number;
  // video
  download_url?: string;
  total_frames?: number;
  processed_frames?: number;
  fps?: number;
  total_detections?: number;
  class_counts?: Record<string, number>;
}

export interface AIModel {
  id: number;
  name: string;
  model_type: string;
  filename: string;
  description: string;
  version: string;
  is_active: boolean;
  is_default: boolean;
  confidence_threshold: number;
  class_names: string[];
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface HistoryItem {
  id: number;
  analyzer_type: string;
  input_filename: string;
  input_type: string;
  total_objects: number;
  processing_time: number;
  created_at: string;
  image_width: number;
  image_height: number;
}

// ── helpers ───────────────────────────────────────────────────────────

function buildForm(fields: Record<string, unknown>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (v instanceof File || v instanceof Blob) {
      fd.append(k, v as File);
    } else if (v !== undefined && v !== null) {
      fd.append(k, String(v));
    }
  }
  return fd;
}

async function post<T>(endpoint: string, body: FormData): Promise<T> {
  const res = await request(`${BASE_URL}${endpoint}`, { method: "POST", body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error ?? (typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail)) ?? `HTTP ${res.status}`);
  }
  return res.json();
}

async function get<T>(endpoint: string): Promise<T> {
  const res = await request(`${BASE_URL}${endpoint}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Analysis API ─────────────────────────────────────────────────────

export const api = {
  analyzeImage(file: File, confidence = 0.5, opts: Record<string, unknown> = {}) {
    return post<AnalysisResult>("/api/analyze/image", buildForm({ file, confidence, ...opts }));
  },
  analyzeHuman(file: File, confidence = 0.45, poseMode = false) {
    return post<AnalysisResult>("/api/analyze/human", buildForm({ file, confidence, pose_mode: poseMode }));
  },
  analyzeShip(file: File, confidence = 0.45) {
    return post<AnalysisResult>("/api/analyze/ship", buildForm({ file, confidence }));
  },
  analyzeContainer(file: File, confidence = 0.45, conditionMode = false) {
    return post<AnalysisResult>("/api/analyze/container", buildForm({ file, confidence, condition_mode: conditionMode }));
  },
  analyzeCombined(file: File, confidence = 0.5, conditionMode = false) {
    return post<AnalysisResult>("/api/analyze/combined", buildForm({ file, confidence, condition_mode: conditionMode }));
  },
  async analyzeVideo(file: File, analyzerType = "general", confidence = 0.5, track = true, progress?: (job: {progress:number;frame:number;total:number})=>void): Promise<AnalysisResult> {
    const {job_id} = await post<{job_id:string}>("/api/analyze/video", buildForm({file,analyzer_type:analyzerType,confidence,track,background:true}));
    for (;;) {
      await new Promise(resolve=>setTimeout(resolve,1000));
      const job=await get<{status:string;progress:number;frame:number;total:number;result:AnalysisResult;error?:string}>(`/api/analyze/video/jobs/${job_id}`);
      progress?.(job);
      if(job.status==='complete')return job.result;
      if(job.status==='failed')throw new Error(job.error || 'Video processing failed');
    }
  },

  // ── Models ──────────────────────────────────────────────────────────
  getModels() { return get<{ models: AIModel[] }>("/api/models"); },
  getModel(id: number) { return get<AIModel>(`/api/models/${id}`); },
  uploadModel(file: File, meta: Record<string, unknown>) {
    return post<{ success: boolean; model_id: number }>("/api/models/upload", buildForm({ file, ...meta }));
  },
  updateModel(id: number, fields: Record<string, unknown>) {
    const fd = buildForm(fields);
    return mutation(`${BASE_URL}/api/models/${id}`, { method: "PATCH", body: fd });
  },
  deleteModel(id: number) {
    return mutation(`${BASE_URL}/api/models/${id}`, { method: "DELETE" });
  },

  // ── History ──────────────────────────────────────────────────────────
  getHistory(limit = 50, offset = 0, analyzerType?: string) {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (analyzerType) q.set("analyzer_type", analyzerType);
    return get<{ items: HistoryItem[] }>(`/api/history?${q}`);
  },
  getAnalysis(id: number) { return get<HistoryItem & { results: AnalysisResult }>(`/api/history/${id}`); },

  // ── History management ───────────────────────────────────────────────
  deleteAnalysis(id: number) {
    return mutation(`${BASE_URL}/api/history/${id}`, { method: "DELETE" });
  },

  // ── Health ───────────────────────────────────────────────────────────
  health() { return get<{ status: string }>("/api/health"); },
};

export async function downloadOutput(path:string) {
  const res=await request(`${BASE_URL}${path}`);
  if(!res.ok)throw new Error('Download unavailable or expired');
  const url=URL.createObjectURL(await res.blob());const a=document.createElement('a');
  a.href=url;a.download='visionx-annotated.mp4';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export async function getLiveTicket():Promise<string> {
  return (await post<{ticket:string}>('/api/analyze/live/ticket',new FormData())).ticket;
}
