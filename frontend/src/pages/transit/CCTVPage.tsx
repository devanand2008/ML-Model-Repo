import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, Camera, Check, Download, Eye, FileVideo, Gauge, Pause, Play, RotateCcw, Square, Upload, Users } from 'lucide-react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { BASE_URL, request } from '../../services/api';
import { ErrorNotice, Loading, Metric, PageHeading, Panel, SourceBadge, chartTooltip, useAction, useResource, useTransitRefresh } from '../../components/transit/Shared';
import { numberText, patchTransit, postTransit, rows, transitRequest, uploadVision, type Data } from '../../services/transit';

const ACTIVE_JOB_STATES = new Set(['queued', 'processing', 'paused', 'encoding']);
const VEHICLE_CLASSES = ['car', 'bus', 'truck', 'motorcycle', 'bicycle'];
const ROI_FIELDS = ['X', 'Y', 'Width', 'Height'];
const mediaUrl = (path: string) => /^(data:|blob:|https?:)/.test(path) ? path : `${BASE_URL}${path}`;

function validRoi(roi: number[]) {
  return roi.length === 4 && roi.every(value => Number.isFinite(value) && value >= 0 && value <= 1)
    && roi[2] > 0 && roi[3] > 0 && roi[0] + roi[2] <= 1 && roi[1] + roi[3] <= 1;
}

function DetectionImage({ src, result, boxes, labels, roi }: { src: string; result: Data | null; boxes: boolean; labels: boolean; roi: number[] | null }) {
  const [naturalSize, setNaturalSize] = useState([0, 0]);
  const width = Number(result?.image_width ?? result?.width ?? naturalSize[0]);
  const height = Number(result?.image_height ?? result?.height ?? naturalSize[1]);
  const detections = rows(result?.detections);
  return <div style={{ position: 'relative', width: '100%' }}>
    <img src={src} alt="Authorized image source with optional model detection overlays" style={{ width: '100%', maxHeight: 550, objectFit: 'contain', display: 'block' }} onLoad={event => setNaturalSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])} />
    {width > 0 && height > 0 && <svg aria-label="Detection overlays" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
      {roi && validRoi(roi) && <rect x={roi[0] * width} y={roi[1] * height} width={roi[2] * width} height={roi[3] * height} fill="#a78bfa18" stroke="#a78bfa" strokeWidth={Math.max(2, width / 300)} strokeDasharray="10 6" />}
      {detections.map((detection, index) => {
        // The service contract is [x,y,width,height] in source pixels.
        const [x, y, boxWidth, boxHeight] = detection.bbox ?? [];
        if (![x, y, boxWidth, boxHeight].every(Number.isFinite)) return null;
        const color = detection.class === 'person' ? '#00e5a0' : '#00d9ff';
        const fontSize = Math.max(12, width / 55);
        return <g key={`${detection.track_id ?? index}-${index}`}>
          {boxes && <rect x={x} y={y} width={boxWidth} height={boxHeight} fill="none" stroke={color} strokeWidth={Math.max(2, width / 300)} />}
          {labels && <text x={Math.max(0, x + 3)} y={Math.max(fontSize, y - 5)} fontSize={fontSize} fill={color} stroke="#061426" strokeWidth={3} paintOrder="stroke" fontWeight={700}>{detection.class} {Math.round(Number(detection.confidence) * 100)}%{detection.track_id != null ? ` · #${detection.track_id}` : ''}</text>}
        </g>;
      })}
    </svg>}
  </div>;
}

export default function CCTVPage() {
  const cameras = useResource<Data>('/api/cameras');
  const samples = useResource<Data>('/api/vision/samples');
  const models = useResource<Data>('/api/models/status');
  const traffic = useResource<Data>('/api/traffic/summary');
  const [cameraId, setCameraId] = useState('CAM01');
  const [sourceMode, setSourceMode] = useState<'upload' | 'sample'>('sample');
  const [sampleId, setSampleId] = useState('bus-image');
  const [file, setFile] = useState<File | null>(null);
  const [fileUrl, setFileUrl] = useState('');
  const [confidence, setConfidence] = useState(0.5);
  const [result, setResult] = useState<Data | null>(null);
  const [job, setJob] = useState<Data | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showProcessed, setShowProcessed] = useState(true);
  const [roiEnabled, setRoiEnabled] = useState(false);
  const [roi, setRoi] = useState([0, 0, 1, 1]);
  const [roiDirty, setRoiDirty] = useState(false);
  const [pollError, setPollError] = useState('');
  const [pollRetry, setPollRetry] = useState(0);
  const [processedVideoUrl, setProcessedVideoUrl] = useState('');
  const [videoLoading, setVideoLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const jobControlRevision = useRef(0);
  const action = useAction();
  const invalidate = useTransitRefresh();
  const selectedCamera = rows(cameras.data?.cameras ?? cameras.data?.items).find(item => item.id === cameraId);
  const isInterior = selectedCamera?.role === 'bus_interior';
  const selectedSample = rows(samples.data?.samples).find(item => item.id === sampleId);
  const activeJob = !!job && ACTIVE_JOB_STATES.has(job.status);
  const videoSource = sourceMode === 'sample' ? selectedSample?.type === 'video' : !!file && (file.type.startsWith('video/') || /\.(mp4|avi|mov|mkv|webm)$/i.test(file.name));
  const isVideo = !!result?.download_url || videoSource;
  const observed = result?.observation;
  const counts = observed?.class_counts ?? result?.counts ?? {};
  const modelClasses:string[]=result?.supported_classes ?? rows(models.data?.detection_models).find(model=>model.type===(isInterior?'human':'general'))?.classes ?? [];
  const supportedClasses:string[]=modelClasses.map(name=>['human','people'].includes(name.toLowerCase())?'person':name.toLowerCase()).filter(name=>!isInterior||name==='person');
  const hasClass = (name: string) => !supportedClasses.length || supportedClasses.includes(name);
  const countText = (name: string) => !result ? '—' : !supportedClasses.length && !(name in counts) ? 'Unavailable' : hasClass(name) ? numberText(counts[name] ?? 0) : 'Unsupported';
  const rawImage = !isVideo ? result?.processed_image ?? (sourceMode === 'upload' ? fileUrl : '') : '';
  const imageSrc = rawImage || result?.annotated_image || '';
  const editableOverlay = !!rawImage && !!result;
  const outputUrl = result?.download_url ? mediaUrl(result.download_url) : '';
  const originalVideo = isVideo && sourceMode === 'upload' ? fileUrl : '';
  const visibleVideo = showProcessed && result?.download_url ? processedVideoUrl : originalVideo;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!file) { setFileUrl(''); return; }
    const url = URL.createObjectURL(file); setFileUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const savedRoi = JSON.stringify(selectedCamera?.roi ?? null);
  useEffect(() => {
    const configured = selectedCamera?.roi;
    setRoiEnabled(Array.isArray(configured)); setRoi(Array.isArray(configured) ? [...configured] : [0, 0, 1, 1]); setRoiDirty(false);
  }, [cameraId, savedRoi]);

  useEffect(() => {
    if (!job?.job_id || !activeJob) return;
    const jobId = job.job_id;
    let current = true;
    let timer = 0;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const revision = jobControlRevision.current;
        const update = await transitRequest<Data>(`/api/vision/jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal });
        if (!current) return;
        if (revision !== jobControlRevision.current) { timer = window.setTimeout(poll, 1000); return; }
        setJob(update); setPollError('');
        if (update.status === 'complete' && update.result) { setResult(update.result); setShowProcessed(true); invalidate(); }
        else if (update.status === 'failed' || update.status === 'interrupted') setPollError(update.error ?? 'Video processing was interrupted. Submit the source again.');
        if (ACTIVE_JOB_STATES.has(update.status)) timer = window.setTimeout(poll, 1000);
      } catch (error: any) { if (current && error.name !== 'AbortError') setPollError(error.message ?? 'Could not refresh this video job.'); }
    };
    timer = window.setTimeout(poll, 1000);
    return () => { current = false; controller.abort(); window.clearTimeout(timer); };
  }, [job?.job_id, activeJob, pollRetry, invalidate]);

  useEffect(() => {
    setProcessedVideoUrl(''); setPreviewError(''); setVideoLoading(false);
    if (!outputUrl) return;
    let current = true;
    let url = '';
    const controller = new AbortController();
    setVideoLoading(true);
    request(outputUrl, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Processed preview is unavailable. The stored output may have expired.');
      const blob = await response.blob();
      if (current) { url = URL.createObjectURL(blob); setProcessedVideoUrl(url); }
    }).catch(error => { if (current && error.name !== 'AbortError') setPreviewError(error.message); })
      .finally(() => { if (current) setVideoLoading(false); });
    return () => { current = false; controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [outputUrl]);

  async function startDetection() {
    ++jobControlRevision.current;
    const payload = await action.run(() => sourceMode === 'upload' && file
      ? uploadVision(file, cameraId, confidence)
      : postTransit<Data>(`/api/vision/samples/${encodeURIComponent(sampleId)}/analyze?camera_id=${encodeURIComponent(cameraId)}&confidence=${confidence}`));
    if (!payload || !mounted.current) return;
    setPollError(''); setPreviewError('');
    if (payload.job_id) { setJob(payload); setResult(null); }
    else { setResult(payload); setJob(null); invalidate(); }
  }

  async function controlJob(command: 'pause' | 'resume' | 'cancel') {
    if (!job?.job_id) return;
    ++jobControlRevision.current;
    const updated = await action.run(() => postTransit<Data>(`/api/vision/jobs/${encodeURIComponent(job.job_id)}/${command}`));
    if (updated && mounted.current) setJob(updated);
  }

  async function reset() {
    ++jobControlRevision.current;
    if (activeJob && job?.job_id) {
      const cancelled = await action.run(() => postTransit<Data>(`/api/vision/jobs/${encodeURIComponent(job.job_id)}/cancel`));
      if (!cancelled) return;
    }
    if (!mounted.current) return;
    setJob(null); setResult(null); setFile(null); setPollError(''); setPreviewError(''); action.setError('');
    if (inputRef.current) inputRef.current.value = '';
  }

  async function saveRoi() {
    if (roiEnabled && !validRoi(roi)) { action.setError('ROI must fit inside the image: X/Y between 0 and 1, positive width/height, and X + width / Y + height at most 1.'); return; }
    const saved = await action.run(() => patchTransit<Data>(`/api/cameras/${encodeURIComponent(cameraId)}`, { roi: roiEnabled ? roi : null }));
    if (saved && mounted.current) { setRoiDirty(false); invalidate(); }
  }

  async function downloadProcessed() {
    if (!outputUrl) return;
    await action.run(async () => {
      const response = await request(outputUrl);
      if (!response.ok) throw new Error('Processed output could not be downloaded.');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = `transitopt-detection-${result?.analysis_id ?? 'video'}.mp4`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  const timeline = rows(result?.timeline);
  const trend = timeline.filter((_, index) => index % Math.max(1, Math.ceil(timeline.length / 120)) === 0).map(point => ({
    seconds: point.seconds, crowd: point.roi_people ?? point.counts?.person ?? 0,
    vehicles: VEHICLE_CLASSES.reduce((total, name) => total + Number(point.counts?.[name] ?? 0), 0),
  }));

  return <div className="to-page">
    <PageHeading eyebrow="EXISTING MODEL · CONNECTED OBSERVATIONS" title="CCTV intelligence" description="Analyze an authorized image, recorded video or browser camera. Actual detections become stored traffic and crowd observations." actions={<SourceBadge source="REAL_MODEL_DETECTION" />} />
    <ErrorNotice message={cameras.error} retry={cameras.refresh} /><ErrorNotice message={samples.error} retry={samples.refresh} /><ErrorNotice message={models.error} retry={models.refresh} />
    <div className="to-grid to-grid-2">
      <Panel title="Video and image input" subtitle={isInterior ? 'The configured human detector updates the assigned bus visible crowding.' : 'The configured general detector analyzes supported road vehicle classes.'} actions={<Camera size={20} color="#00d9ff" />}>
        {cameras.loading ? <Loading label="Loading authorized camera associations…" /> : <>
          <label className="to-label">Camera association<select aria-label="Camera association" className="to-field" value={cameraId} disabled={action.busy || activeJob} onChange={event => { setCameraId(event.target.value); setResult(null); setJob(null); }}>
            {rows(cameras.data?.cameras ?? cameras.data?.items).map(camera => <option key={camera.id} value={camera.id}>{camera.name}</option>)}
          </select></label>
          <p className="to-help">{selectedCamera?.id} · {selectedCamera?.role === 'bus_interior' ? `Bus ${selectedCamera.bus_id} interior` : `Road corridor ${selectedCamera?.corridor_id}`} · {selectedCamera?.status?.replace(/_/g, ' ') ?? 'Awaiting input'}</p>
          <div className="to-inline-actions" style={{ margin: '16px 0' }}>
            <button className={`to-button ${sourceMode === 'upload' ? '' : 'subtle'}`} disabled={action.busy || activeJob} onClick={() => { setSourceMode('upload'); setResult(null); setJob(null); }}><Upload size={15} />Upload</button>
            <button className={`to-button ${sourceMode === 'sample' ? '' : 'subtle'}`} disabled={action.busy || activeJob} onClick={() => { setSourceMode('sample'); setResult(null); setJob(null); }}><FileVideo size={15} />Authorized sample</button>
            <Link className="to-button subtle" to={`/webcam?camera_id=${encodeURIComponent(cameraId)}&mode=${selectedCamera?.role === 'bus_interior' ? 'human' : 'general'}`}><Camera size={15} />Open browser camera</Link>
          </div>
          {sourceMode === 'upload' ? <label className="to-label">Choose image or recorded video<input ref={inputRef} aria-label="Choose image or recorded video" className="to-field" type="file" accept=".jpg,.jpeg,.png,.bmp,.webp,.mp4,.avi,.mov,.mkv,.webm" disabled={action.busy || activeJob} onChange={event => { setFile(event.target.files?.[0] ?? null); setResult(null); setJob(null); setPreviewError(''); }} /><span className="to-help">Authorized recordings only. Server validates media formats and upload limits.</span></label>
            : <label className="to-label">Sample<select aria-label="Sample" className="to-field" value={sampleId} disabled={action.busy || activeJob} onChange={event => { setSampleId(event.target.value); setResult(null); setJob(null); }}>
              {rows(samples.data?.samples).map(sample => <option key={sample.id} value={sample.id}>{sample.name}</option>)}
            </select><span className="to-help">{selectedSample?.provenance}</span></label>}
          <label className="to-label" style={{ marginTop: 18 }}>Detection confidence · {Math.round(confidence * 100)}%<input aria-label="Detection confidence" type="range" min="0.1" max="0.95" step="0.05" value={confidence} disabled={action.busy || activeJob} onChange={event => setConfidence(Number(event.target.value))} /></label>
          <div className="to-inline-actions" style={{ marginTop: 18 }}>
            <button className="to-button" disabled={action.busy || activeJob || roiDirty || !selectedCamera || (sourceMode === 'upload' ? !file : !selectedSample)} onClick={startDetection}><Play size={15} />{action.busy ? 'Processing…' : 'Start detection'}</button>
            <button className="to-button subtle" disabled={action.busy || !activeJob || job?.status === 'paused' || job?.status === 'encoding'} title={job?.status === 'encoding' ? 'Browser encoding cannot be paused; stop is available.' : 'Pause a running recorded-video job'} onClick={() => controlJob('pause')}><Pause size={15} />Pause</button>
            <button className="to-button subtle" disabled={action.busy || job?.status !== 'paused'} onClick={() => controlJob('resume')}><Play size={15} />Resume</button>
            <button className="to-button subtle" disabled={action.busy || !activeJob} onClick={() => controlJob('cancel')}><Square size={15} />Stop</button>
            <button className="to-button subtle" disabled={action.busy} onClick={reset}><RotateCcw size={15} />Reset</button>
          </div>
          {roiDirty && <p className="to-help">Save the ROI changes before starting detection.</p>}
          <p className="to-help">Pause, resume and stop apply to background video jobs. Browser camera controls are available on the live camera page.</p>
        </>}
        <ErrorNotice message={action.error} />
      </Panel>

      <Panel title="Bus-stop crowd region" subtitle="Save a normalized region of interest to count people within a chosen stop area." actions={<Users size={20} color="#00e5a0" />}>
        <label className="to-check"><input aria-label="Enable crowd ROI" type="checkbox" checked={roiEnabled} disabled={activeJob || action.busy} onChange={event => { setRoiEnabled(event.target.checked); setRoiDirty(true); }} />Enable region of interest</label>
        <div className="to-form-grid" style={{ margin: '18px 0' }}>{ROI_FIELDS.map((label, index) => <label key={label} className="to-label">{label}<input aria-label={`ROI ${label}`} className="to-field" type="number" min="0" max="1" step="0.05" disabled={!roiEnabled || activeJob || action.busy} value={roi[index]} onChange={event => { setRoi(values => values.map((value, current) => current === index ? Number(event.target.value) : value)); setRoiDirty(true); }} /></label>)}</div>
        <button className="to-button subtle" disabled={!selectedCamera || activeJob || action.busy || !roiDirty} onClick={saveRoi}><Check size={15} />Save camera ROI</button>
        <p className="to-help" style={{ marginTop: 16 }}>Values range from 0 to 1 relative to source dimensions. The person's bounding-box footpoint must fall inside the saved ROI. ROI estimates describe visible crowd, not measured boardings.</p>
        <div className="to-callout" style={{ marginTop: 18 }}><Eye size={18} /><div><strong>Network stream unavailable</strong><p>{cameras.data?.capabilities?.rtsp_reason ?? 'Authorized RTSP ingestion is not configured. Use an authorized recording or browser camera.'}</p></div></div>
      </Panel>
    </div>

    {job && <Panel title="Recorded-video job" subtitle={`Job ${job.job_id} · ${job.status === 'encoding' ? 'Encoding browser-compatible preview' : String(job.status).replace(/_/g, ' ')}`}>
      <div className="to-inline-actions"><span className="to-chip">{String(job.status).toUpperCase()}</span><span className="to-help">{numberText(job.frame ?? 0)} / {numberText(job.total ?? 0)} frames · {numberText(job.progress ?? 0, 1)}%</span></div>
      <progress aria-label="Video processing progress" value={Number(job.progress ?? 0)} max={100} style={{ width: '100%', marginTop: 16, accentColor: '#00d9ff' }} />
      {job.status === 'paused' && <p className="to-help">Inference is paused. Resume to continue this job or stop to remove its raw upload.</p>}
      {job.status === 'cancelled' && <p className="to-help">Processing was cancelled. The worker removes the raw upload and incomplete output.</p>}
      <ErrorNotice message={job.error ?? pollError} retry={activeJob && pollError ? () => setPollRetry(value => value + 1) : undefined} />
    </Panel>}

    <Panel title="Detection preview" subtitle={isVideo ? 'Processed video annotations are rendered by the existing model pipeline.' : 'Source image with client overlays from the real normalized detection output.'} actions={<div className="to-inline-actions">
      <label className="to-check"><input aria-label="Show bounding boxes" type="checkbox" checked={showBoxes} disabled={!editableOverlay} onChange={event => setShowBoxes(event.target.checked)} />Boxes</label>
      <label className="to-check"><input aria-label="Show labels" type="checkbox" checked={showLabels} disabled={!editableOverlay} onChange={event => setShowLabels(event.target.checked)} />Labels</label>
      {isVideo && result?.download_url && <label className="to-check"><input aria-label="Show processed video" type="checkbox" checked={showProcessed} disabled={!originalVideo} onChange={event => setShowProcessed(event.target.checked)} />Processed video</label>}
    </div>}>
      {isVideo ? <>
        {videoLoading && showProcessed ? <Loading label="Loading processed video preview…" /> : visibleVideo ? <video key={visibleVideo} src={visibleVideo} controls playsInline preload="metadata" style={{ width: '100%', maxHeight: 550, borderRadius: 12, background: '#020a15' }} onError={() => setPreviewError('This browser could not decode the preview. Download the processed recording to view it in a compatible player.')} aria-label={showProcessed && result?.download_url ? 'Processed detection video' : 'Original uploaded video'} />
          : <div className="to-empty"><FileVideo size={36} /><p>{activeJob ? 'The processed recording will appear when inference and browser encoding complete.' : 'Select an authorized video and start detection.'}</p></div>}
        {result?.download_url && <button className="to-button subtle" onClick={downloadProcessed} disabled={action.busy} style={{ marginTop: 14 }}><Download size={15} />Download processed video</button>}
        <p className="to-help">Box and label toggles apply to still-image overlays. Recorded-video annotations are baked into the processed output.{originalVideo ? ' Switch Processed video off to inspect the original upload.' : ' The bundled video sample contains repeated still frames, not live traffic.'}</p>
      </> : imageSrc ? <DetectionImage src={imageSrc} result={result} boxes={showBoxes} labels={showLabels} roi={roiEnabled && validRoi(roi) ? roi : null} />
        : <div className="to-empty"><Camera size={36} /><h3>Awaiting authorized input</h3><p>Run a bundled sample, upload a source, or open your browser camera to generate genuine model detections.</p></div>}
      <ErrorNotice message={previewError} />
    </Panel>

    <div className="to-grid to-grid-4">
      <Metric label="People detected · frame" value={countText('person')} detail={observed?.roi ? `Crowd inside saved ROI: ${numberText(observed.people_count)}` : 'Visible people are distinct from ridership'} icon={<Users size={17} />} accent="green" />
      <Metric label={isInterior ? 'Associated bus' : 'Vehicles detected · frame'} value={isInterior ? selectedCamera?.bus_id : result ? numberText(observed?.vehicle_count ?? VEHICLE_CLASSES.reduce((sum, name) => sum + Number(counts[name] ?? 0), 0)) : '—'} detail={isInterior ? 'Interior observations are stored against this bus' : 'Cars, buses, trucks, motorcycles and bicycles'} icon={<Activity size={17} />} />
      <Metric label={isInterior ? 'Visible crowding estimate' : 'Estimated congestion score'} value={isInterior ? observed?.bus_observation?.crowd_level ?? 'Awaiting input' : result ? numberText(observed?.congestion_score, 1) : '—'} unit={!isInterior && result ? '/100' : undefined} detail={isInterior ? 'Partial coverage; total occupancy unverified' : observed?.congestion_category ?? 'Awaiting a processed observation'} accent={isInterior ? 'green' : observed?.congestion_score >= 50 ? 'orange' : 'cyan'} />
      <Metric label="Processing FPS" value={result ? numberText(result.inference_fps ?? observed?.processing_fps, 1) : '—'} detail={result?.download_url ? 'Measured recorded-video processing rate' : 'Still images do not provide sustained FPS'} icon={<Gauge size={17} />} accent="blue" />
    </div>

    <div className="to-grid to-grid-2">
      <Panel title="Supported detection outputs" subtitle="Video counts below describe the final processed frame; detections across frames are not unique people." actions={result && <SourceBadge source="REAL_MODEL_DETECTION" />}>
        <div className="to-table-wrap"><table className="to-table"><thead><tr><th>Object class</th><th>Detected / frame</th><th>Model support</th></tr></thead><tbody>{['person', 'car', 'bus', 'truck', 'motorcycle', 'bicycle'].map(name => <tr key={name}><td style={{ textTransform: 'capitalize' }}>{name}</td><td>{countText(name)}</td><td>{models.loading && !result ? 'Loading model classes' : supportedClasses.length ? hasClass(name) ? 'Supported' : 'Unsupported' : 'Class information unavailable'}</td></tr>)}</tbody></table></div>
        <p className="to-help">Average detection confidence: {observed?.confidence_mean == null ? 'Unavailable' : `${numberText(Number(observed.confidence_mean) * 100, 1)}%`}. Bounding boxes use source pixel coordinates (x, y, width, height). Tracking IDs appear only when the existing pipeline supplies them.</p>
        {rows(result?.warnings).length > 0 && <p className="to-help">{result?.warnings.join(' ')}</p>}
      </Panel>
      <Panel title="Traffic and crowd interpretation" subtitle="Measured object detections support estimated scene conditions.">
        <div className="to-table-wrap"><table className="to-table"><tbody>
          <tr><td>Relative vehicle density</td><td>{result ? numberText(observed?.vehicle_density, 3) : 'Unavailable'}</td></tr>
          <tr><td>Average visible vehicles / frame</td><td>{result ? numberText(observed?.mean_vehicles_per_frame, 2) : 'Unavailable'}</td></tr>
          <tr><td>Average crowd / frame</td><td>{result ? numberText(observed?.mean_people_per_frame, 2) : 'Unavailable'}</td></tr>
          <tr><td>Physical vehicle speed</td><td>Unavailable</td></tr><tr><td>Calibrated queue length</td><td>Unavailable</td></tr><tr><td>Actual ticketed passengers</td><td>Unavailable</td></tr>
        </tbody></table></div>
        <p className="to-help">{isInterior ? 'Interior observations update bus crowding; they do not become road congestion estimates. Live doorway safety also requires fresh GPS and door-state context.' : observed?.method ?? 'Congestion uses a configurable visible-vehicle count/reference proxy. It is not a physical traffic-flow measurement.'}</p>
        <p className="to-help">{observed?.crowd_note ?? 'Detected people are crowd observations, not actual ticketed boarding demand.'} Observations associated with a camera are persisted for dashboard, forecasts and route optimization.</p>
      </Panel>
    </div>

    {trend.length > 1 && <Panel title="Crowd and vehicle observations over this recording" subtitle="Real per-frame detections, sampled for display. ROI crowd counts apply when a saved region was configured.">
      <div style={{ width: '100%', height: 240 }}><ResponsiveContainer width="100%" height="100%"><LineChart data={trend}><CartesianGrid stroke="#193753" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="seconds" stroke="#8ba6c4" unit="s" /><YAxis stroke="#8ba6c4" /><Tooltip contentStyle={chartTooltip} /><Legend /><Line dataKey="crowd" name="Detected crowd" stroke="#00e5a0" dot={false} /><Line dataKey="vehicles" name="Visible vehicles" stroke="#00d9ff" dot={false} /></LineChart></ResponsiveContainer></div>
    </Panel>}

    <Panel title="Connected corridor alerts" subtitle="Synthetic scenario alerts and real model observations retain their own source labels.">
      <ErrorNotice message={traffic.error} retry={traffic.refresh} />
      {traffic.loading ? <Loading label="Loading stored traffic alerts…" /> : rows(traffic.data?.events).length ? <div className="to-alert-list">{rows(traffic.data?.events).slice(0, 8).map(event => <div className="to-callout" key={event.id}><Activity size={18} /><div><strong>{event.title} · {event.corridor_id ?? event.camera_id}</strong><p>{event.suggested_action}{event.route_ids?.length ? ` · affected routes: ${event.route_ids.join(', ')}` : ''}</p></div><SourceBadge source={event.source} /></div>)}</div> : <p className="to-help">No high-congestion or crowd alerts have been recorded.</p>}
    </Panel>
  </div>;
}
