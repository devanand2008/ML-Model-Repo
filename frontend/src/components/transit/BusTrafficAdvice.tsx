import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { transitRequest, type Data } from '../../services/transit';

export default function BusTrafficAdvice({bus}:{bus:Data|null}){
  const [alerts,setAlerts]=useState<Data[]>([]),[error,setError]=useState('');
  useEffect(()=>{
    let active=true,pending=false;
    const refresh=async()=>{if(pending)return;pending=true;try{const data=await transitRequest('/api/public/traffic/feed');if(active){setAlerts(data.alerts??[]);setError('');}}catch{if(active){setAlerts([]);setError('Traffic feed unavailable.');}}finally{pending=false;}};
    void refresh();const timer=window.setInterval(refresh,5000);return()=>{active=false;window.clearInterval(timer);};
  },[]);
  const nearby=bus?.location?.fresh?alerts.filter(a=>a.reporting_bus_id!==bus.id && Number.isFinite(a.latitude) && Math.hypot((a.latitude-bus.location.latitude)*111.32,(a.longitude-bus.location.longitude)*111.32*Math.cos(bus.location.latitude*Math.PI/180))<=5):[];
  return <section className="dr-card"><h2>Nearby traffic warnings</h2>{nearby.map(a=><p key={a.id} role="status">{a.message}</p>)}{!nearby.length&&<p>{error || (bus?.location?.fresh?'No active high-pressure camera reports within 5 km. Unobserved roads remain unknown.':'Share fresh bus GPS to match nearby traffic reports.')}</p>}<small>These reports are nearby, not necessarily ahead. Open the planner to compare your destination routes. Check any bus diversion with the operator.</small>{bus&&<p><Link className="pa-google-link" to={`/passenger?bus_id=${encodeURIComponent(bus.id)}`}>Compare alternatives from this bus</Link></p>}</section>;
}
