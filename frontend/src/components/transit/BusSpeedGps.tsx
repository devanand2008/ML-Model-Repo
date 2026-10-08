import { useEffect, useRef, useState } from 'react';
import { postTransit } from '../../services/transit';

/** Opt-in GPS paired with the forward camera on the same moving bus. */
export default function BusSpeedGps({busId}:{busId:string}) {
  const [sharing,setSharing]=useState(false),[message,setMessage]=useState('GPS speed sharing is off.');
  const lastSent=useRef(0);
  useEffect(()=>{
    if(!sharing)return;
    if(!navigator.geolocation){setMessage('GPS is unavailable on this device. Use a phone with location access.');setSharing(false);return;}
    let active=true,pending=false;lastSent.current=0;
    const id=navigator.geolocation.watchPosition(async position=>{
      if(!active || pending || Date.now()-lastSent.current<5000)return;
      pending=true;lastSent.current=Date.now();
      const p=position.coords;
      try{
        await postTransit(`/api/buses/${busId}/location`,{latitude:p.latitude,longitude:p.longitude,
          accuracy_m:p.accuracy,heading_deg:p.heading,speed_kmh:p.speed==null?null:p.speed*3.6,source:'browser_geolocation'});
        if(active)setMessage(`${p.speed==null?'Speed pending; comparing GPS fixes':`${(p.speed*3.6).toFixed(1)} km/h GPS speed`} | accuracy ${Math.round(p.accuracy)} m | ${new Date().toLocaleTimeString()}`);
      }catch(e){if(active){setMessage((e as Error).message);setSharing(false);}}
      finally{pending=false;}
    },e=>{if(active){setMessage(`GPS unavailable: ${e.message}`);setSharing(false);}},{enableHighAccuracy:true,maximumAge:2000,timeout:15000});
    return()=>{active=false;navigator.geolocation.clearWatch(id);};
  },[sharing,busId]);
  return <div className="speed-gps"><button className="to-button primary" onClick={()=>{setSharing(v=>!v);setMessage(sharing?'GPS speed sharing stopped.':'Waiting for location permission...');}}>{sharing?'Stop bus GPS speed':'Share bus GPS speed'}</button><p role="status">{message}</p><small>Use this only while the device is aboard {busId}. Sign in as admin for camera and GPS together. Assigned drivers can share GPS from their Driver dashboard. Keep the camera page active.</small></div>;
}
