import { ArrowDownUp, Camera, MapPin } from 'lucide-react';
import type { Data } from '../../services/transit';
import { trafficEvidence, TRAFFIC_COLORS } from '../../services/mapIntelligence';

type Props={cameras:Data[]; ranked:Data[]; ordered:Data[]; now:number; radius:number; scope:'nearby'|'all'; order:'lowest'|'highest';
  updated:string|null; error:string; hasOrigin:boolean; onRadius:(radius:number)=>void; onScope:(scope:'nearby'|'all')=>void;
  onOrder:(order:'lowest'|'highest')=>void; onFocus:(camera:Data)=>void};

export default function MapTrafficPanel({cameras,ranked,ordered,now,radius,scope,order,updated,error,hasOrigin,onRadius,onScope,onOrder,onFocus}:Props){
  const lowest=ranked[0],highest=ranked.length>1?ranked[ranked.length-1]:null;
  return <section className="pa-section pa-traffic-panel" aria-label="Traffic places">
    <h2><Camera size={17}/>Find traffic places</h2>
    <div className="pa-scope" role="group" aria-label="Traffic discovery area"><button aria-pressed={scope==='nearby'} onClick={()=>onScope('nearby')}>Near my start</button><button aria-pressed={scope==='all'} onClick={()=>onScope('all')}>All cameras</button></div>
    {scope==='nearby'&&<div className="pa-radii">{[1,3,5,10].map(value=><button key={value} aria-pressed={radius===value} className={radius===value?'selected':''} onClick={()=>onRadius(value)}>{value} km</button>)}</div>}
    {!hasOrigin&&scope==='nearby'&&<p className="pa-muted">Choose a start or use GPS to find nearby traffic. Showing registered cameras until then.</p>}
    <div className="pa-traffic-extremes">
      <button disabled={!lowest} aria-label="Find minimum observed traffic" onClick={()=>lowest&&onFocus(lowest)}><span>Minimum observed</span><strong>{lowest?`${trafficEvidence(lowest,now).score}/100`:'No live data'}</strong><small>{lowest?.name??'Start a located road camera'}</small></button>
      <button disabled={!highest} aria-label="Find maximum observed traffic" onClick={()=>highest&&onFocus(highest)}><span>Maximum observed</span><strong>{highest?`${trafficEvidence(highest,now).score}/100`:ranked.length===1?'One report only':'No live data'}</strong><small>{highest?.name??'At least two reports to compare'}</small></button>
    </div>
    <div className="pa-traffic-legend" aria-label="Traffic colors">{Object.entries(TRAFFIC_COLORS).map(([level,color])=><span key={level}><i style={{background:color}}/>{level.charAt(0)+level.slice(1).toLowerCase()}</span>)}</div>
    <label className="pa-select"><span><ArrowDownUp size={13}/>Sort traffic places</span><select aria-label="Sort traffic places" value={order} onChange={event=>onOrder(event.target.value as Props['order'])}><option value="highest">Highest traffic first</option><option value="lowest">Lowest traffic first</option></select></label>
    {ordered.slice(0,12).map(camera=>{const evidence=trafficEvidence(camera,now);return <button key={camera.id} className="pa-traffic-place" onClick={()=>onFocus(camera)}><i style={{background:evidence.color}}/><div><strong>{camera.name}</strong><small>{evidence.label}{camera.distance_km!=null?` · ${camera.distance_km.toFixed(1)} km away`:''}</small><small>{new Date(camera.observation.timestamp).toLocaleTimeString('en-IN')} · Located live camera</small></div><MapPin size={15}/></button>;})}
    {!ranked.length&&<p className="pa-muted">No fresh, accurately located live camera reports in this area. Traffic is unknown; recorded footage and approximate demo pins are not ranked as live places.</p>}
    <details><summary>{cameras.length-ranked.length} cameras with unknown current traffic</summary>{cameras.filter(camera=>!trafficEvidence(camera,now).available).map(camera=><button key={camera.id} className="pa-traffic-place" onClick={()=>onFocus(camera)}><i style={{background:TRAFFIC_COLORS.UNKNOWN}}/><div><strong>{camera.name}</strong><small>{trafficEvidence(camera,now).label}</small></div></button>)}</details>
    {error&&<p className="pa-muted" role="alert">{error}</p>}
    <p className="pa-muted">{updated?`Last feed check ${updated}. `:''}Scores describe visible vehicle pressure at camera locations, not whole-road traffic or measured delay.</p>
  </section>;
}
