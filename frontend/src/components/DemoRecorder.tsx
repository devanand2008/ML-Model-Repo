import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import './demo-recorder.css';

export const DEMO_STEPS = [
  ['/', 'One TransitOpt app connects passengers, drivers and administrators.', 10],
  ['/ml', 'The ML workspace connects laptop and phone cameras to the existing YOLO models.', 14],
  ['/record-result/road', 'Real YOLO vehicle detection on a bundled recorded image. This is sample evidence, not a live traffic feed.', 18],
  ['/record-result/interior', 'Person-only detection demonstrates the bus crowd pipeline on the same sample. Real bus interior footage is still needed.', 18],
  ['/cctv', 'CCTV intelligence accepts authorized images and recorded video, with model overlays, camera associations and source labels.', 12],
  ['/webcam?mode=general&camera_id=CAM02', 'Live mode needs your camera permission. Preview FPS and ML detection FPS are measured separately. Pause the tour to demonstrate your webcam.', 14],
  ['/passenger', 'Choose an origin and destination. Camera-aware routes monitor traffic every five seconds. Pause here to plan a journey.', 16],
  ['/fleet', 'Registered buses connect GPS, camera assignments and visible crowding. Missing or stale data is labeled.', 14],
  ['/network', 'The configured transit network is an illustrative planning schematic; passenger road paths use the real routing provider.', 12],
  ['/demand', 'XGBoost predicts demand at 30, 60 and 120 minutes using the labeled synthetic transit dataset.', 14],
  ['/optimization', 'OR-Tools compares fleet plans under capacity, reserve and service constraints.', 12],
  ['/simulator', 'What-if scenarios compare demand and traffic assumptions. These are simulation results.', 12],
  ['/recommendations', 'Operators review recommendations before any simulation activation. The tour does not approve plans.', 12],
  ['/safety', 'Bus safety signals require repeated detections and configured GPS and doorway context; people review incidents.', 12],
  ['/analytics', 'Analytics and exports preserve the model and solver results for review.', 12],
  ['/models', 'Model Center manages installed YOLO weights and model metadata.', 12],
  ['/history', 'Detection history retains actual image and video analysis results for inspection.', 12],
  ['/accounts', 'Administrators manage operator and assigned driver access. Passenger navigation remains publicly accessible.', 12],
  ['/settings', 'Settings expose traffic density and crowd thresholds. Recorded and synthetic data remain labeled.', 12],
  ['/connect', 'Phone cameras use the same ML server over trusted HTTPS. Follow the device setup guide.', 12],
] as const;

export function srtTime(ms:number) { const t=Math.max(0,Math.floor(ms));return `${String(Math.floor(t/3600000)).padStart(2,'0')}:${String(Math.floor(t/60000)%60).padStart(2,'0')}:${String(Math.floor(t/1000)%60).padStart(2,'0')},${String(t%1000).padStart(3,'0')}`; }
type Cue={start:number;end:number;text:string};
export function cuesToSrt(cues:Cue[]) {return cues.filter(c=>c.end>c.start).map((c,i)=>`${i+1}\n${srtTime(c.start)} --> ${srtTime(c.end)}\n${c.text}\n`).join('\n');}
type RecorderState={active:boolean;recording:boolean;error:string;videoUrl:string;extension:string;srt:string;start:(capture:boolean)=>Promise<void>;stop:()=>void};
const Context=createContext<RecorderState|null>(null);
export function useDemoRecorder(){const value=useContext(Context);if(!value)throw new Error('Recorder provider unavailable');return value;}

export function DemoRecorderProvider({children}:{children:ReactNode}) {
  const navigate=useNavigate();
  const [active,setActive]=useState(false),[recording,setRecording]=useState(false),[paused,setPaused]=useState(false),[step,setStep]=useState(0);
  const [error,setError]=useState(''),[videoUrl,setVideoUrl]=useState(''),[extension,setExtension]=useState('webm'),[srt,setSrt]=useState('');
  const recorder=useRef<MediaRecorder|null>(null),stream=useRef<MediaStream|null>(null),parts=useRef<Blob[]>([]),urlRef=useRef('');
  const started=useRef(0),cues=useRef<Cue[]>([]),finishing=useRef(false),stepRef=useRef(0);
  function addCue(index:number) {const now=performance.now()-started.current;const last=cues.current[cues.current.length-1];if(last)last.end=now;cues.current.push({start:now,end:now,text:DEMO_STEPS[index][1]});}
  function move(index:number) {if(index>=DEMO_STEPS.length){stop();return;}const next=Math.max(0,index);stepRef.current=next;setStep(next);addCue(next);navigate(DEMO_STEPS[next][0]);}
  function stop() {
    if(finishing.current)return;finishing.current=true;
    const last=cues.current[cues.current.length-1];if(last)last.end=performance.now()-started.current;
    setSrt(cuesToSrt(cues.current));setActive(false);setRecording(false);
    if(recorder.current?.state==='recording')recorder.current.stop();
    stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;
    navigate('/record-demo');
  }
  async function start(capture:boolean) {
    if(active)return;
    setError('');
    try {
      if(capture) {
        if(!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder==='undefined')throw new Error('Screen recording is unavailable here. Use desktop Chrome or Edge on localhost or trusted HTTPS.');
        // Browser requires this call directly in the user's click gesture.
        stream.current=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:30},audio:false});
        const mime=['video/webm;codecs=vp8','video/webm','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
        if(!mime)throw new Error('This browser has no supported recording format.');
        const next=new MediaRecorder(stream.current,{mimeType:mime,videoBitsPerSecond:5000000});
        parts.current=[];setExtension(mime.includes('mp4')?'mp4':'webm');
        next.ondataavailable=e=>{if(e.data.size)parts.current.push(e.data);};
        next.onstop=()=>{const blob=new Blob(parts.current,{type:mime});if(urlRef.current)URL.revokeObjectURL(urlRef.current);urlRef.current=URL.createObjectURL(blob);setVideoUrl(urlRef.current);recorder.current=null;};
        next.onerror=()=>{setError('Recording stopped because the browser reported a capture error.');stop();};
        stream.current.getVideoTracks()[0].onended=stop;
        recorder.current=next;next.start(1000);setRecording(true);
      }
      if(urlRef.current){URL.revokeObjectURL(urlRef.current);urlRef.current='';}setVideoUrl('');
      finishing.current=false;started.current=performance.now();cues.current=[];setSrt('');setPaused(false);setActive(true);move(0);
    } catch(e) {stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;setError((e as Error).message);}
  }
  useEffect(()=>{if(!active||paused)return;const timer=window.setTimeout(()=>move(stepRef.current+1),DEMO_STEPS[step][2]*1000);return()=>window.clearTimeout(timer);},[active,paused,step]);
  useEffect(()=>()=>{finishing.current=true;stream.current?.getTracks().forEach(t=>{t.onended=null;t.stop();});if(recorder.current?.state==='recording'){recorder.current.onstop=null;recorder.current.stop();}if(urlRef.current)URL.revokeObjectURL(urlRef.current);},[]);
  return <Context.Provider value={{active,recording,error,videoUrl,extension,srt,start,stop}}>{children}{active&&<div className="demo-record-bar"><div><span className={recording?'demo-record-dot':''}/><strong>{recording?'RECORDING':'TOUR PREVIEW'} · {step+1}/{DEMO_STEPS.length}</strong><button onClick={()=>setPaused(v=>!v)}>{paused?'Resume tour':'Pause tour'}</button><button disabled={!step} onClick={()=>move(step-1)}>Previous</button><button onClick={()=>move(step+1)}>Next</button><button onClick={stop}>{recording?'Stop & save':'End tour'}</button></div><p aria-live="polite">{DEMO_STEPS[step][1]}</p>{paused&&<small>Tour paused. Recording continues while you demonstrate the module.</small>}</div>}</Context.Provider>;
}
