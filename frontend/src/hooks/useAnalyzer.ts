import { useState, useEffect, useMemo } from "react";
import { AnalysisResult } from "../services/api";

export function useAnalyzer<T extends (...args: any[]) => Promise<AnalysisResult>>(fn: T, threshold = .5) {
  const [loading, setLoading] = useState(false);
  const [raw, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [annotation, setAnnotation] = useState<string>();
  const filtered = useMemo(() => {
    if (!raw || raw.processed_frames) return raw;
    const detections = raw.detections.filter(d => d.confidence >= threshold);
    const counts: Record<string, number> = {};
    detections.forEach(d => counts[d.class] = (counts[d.class] || 0) + 1);
    let condition=raw.condition;
    if(condition && condition.total_containers !== null) {
      const containers=detections.filter(d=>['container','intermodal container'].includes(d.class));
      const good=containers.filter(d=>['good','good container'].includes(d.condition||'') && (d.condition_confidence||0)>=threshold).length;
      const damaged=containers.filter(d=>['damaged','damage container','damaged container'].includes(d.condition||'') && (d.condition_confidence||0)>=threshold).length;
      condition={...condition,total_containers:containers.length,good:condition.condition_model_active?good:null,damaged:condition.condition_model_active?damaged:null,
        good_pct:condition.condition_model_active&&containers.length?100*good/containers.length:null,damaged_pct:condition.condition_model_active&&containers.length?100*damaged/containers.length:null};
    }
    return { ...raw, condition, keypoints:raw.keypoints?.filter((_,i)=>detections.some(d=>d.id===i)), detections, counts, people: counts.person || 0,
      ships: detections.filter(d=>d.source === "ship_model" || ["ship","boat"].includes(d.class)).length,
      other: detections.filter(d=>!["person","ship","boat","container","intermodal container","truck"].includes(d.class) && d.source !== "ship_model").length,
      containers: (counts.container || 0) + (counts['intermodal container'] || 0), trucks: counts.truck || 0 };
  }, [raw, threshold]);
  useEffect(() => {
    if (!filtered?.processed_image) return;
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (cancelled) return;
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d')!; ctx.drawImage(img, 0, 0);
      const size = Math.max(12, Math.round(img.width / 70));
      ctx.lineWidth = Math.max(2, img.width / 500); ctx.font = `${size}px sans-serif`;
      filtered.detections.forEach(d => {
        const [x,y,w,h] = d.bbox; ctx.strokeStyle = '#22d3ee'; ctx.fillStyle = '#22d3ee';
        ctx.strokeRect(x,y,w,h);
        const label = `#${d.id} ${d.class} ${(d.confidence*100).toFixed(0)}%`;
        ctx.fillRect(x, Math.max(0,y-size-6), ctx.measureText(label).width+8, size+6);
        ctx.fillStyle = '#071323'; ctx.fillText(label,x+4,Math.max(size,y-4));
      });
      filtered.keypoints?.forEach(points => points.forEach(([x,y,v]) => {
        if(v > .5) {ctx.fillStyle='#a78bfa';ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();}
      }));
      setAnnotation(c.toDataURL('image/jpeg', .94));
    };
    img.src = filtered.processed_image;
    return () => {cancelled = true;};
  }, [filtered]);
  const run = async (...args: Parameters<T>) => {
    setLoading(true); setError(null); setResult(null); setAnnotation(undefined);
    try {
      // Request the full supported confidence range; filtering is local and instant.
      const inputs = [...args];
      if (typeof inputs[1] === 'number') inputs[1] = .1;
      setResult(await fn(...inputs));
    } catch (e: any) { setError(e?.message ?? 'Analysis failed. Check backend connection.'); }
    finally { setLoading(false); }
  };
  const result = filtered ? {...filtered, annotated_image: annotation || filtered.annotated_image} : null;
  return {loading, result, error, run, setError, setResult};
}
export function downloadBase64(dataUrl: string, name = 'visionx-result.jpg') {
  const a = document.createElement('a'); a.href=dataUrl; a.download=name; a.click();
}
