import { useEffect,useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeading,Panel } from '../../components/transit/Shared';
import { transitRequest,type Data } from '../../services/transit';

export default function AppStatusPage(){
  const [data,setData]=useState<Data>({}),[checking,setChecking]=useState(false);
  async function refresh(){setChecking(true);const paths=['/api/system/status','/api/models/status','/api/public/rag/status'];const values=await Promise.allSettled(paths.map(p=>transitRequest(p)));setData(Object.fromEntries(values.map((v,i)=>[i,v.status==='fulfilled'?v.value:{error:v.reason.message}])));setChecking(false);}
  useEffect(()=>{void refresh();},[]);
  const system=data[0],models=data[1]?.detection_models??[],rag=data[2];
  const detector=models.find((m:Data)=>m.type==='general'&&m.is_default);
  const human=models.find((m:Data)=>m.type==='human'&&m.is_default);
  const cards=[
    {name:'Camera vehicle detection',ready:detector?.weights_available,detail:detector?.filename??data[1]?.error??'Waiting for detector status',link:'/ml'},
    {name:'Bus people detection',ready:human?.weights_available,detail:human?.filename??data[1]?.error??'Waiting for detector status',link:'/ml'},
    {name:'Demand forecasting',ready:system?.forecast?.ready,detail:system?.forecast?.algorithm??system?.error??'Waiting for forecast status',link:'/demand'},
    {name:'Fleet optimization',ready:system?.optimizer?.available,detail:system?.optimizer?.engine??system?.error??'Waiting for solver status',link:'/optimization'},
    {name:'Route RAG assistant',ready:rag?.weights_available,detail:rag?.generator??rag?.error??'Waiting for RAG status',link:'/rag'},
    {name:'Shared database',ready:system?.database==='connected',detail:system?.database??system?.error??'Waiting for database status',link:'/admin'}];
  return <div className="to-page"><PageHeading eyebrow="APP READINESS" title="Check the app" description="Check installed models and services, then open the module you need." actions={<button className="to-button primary" disabled={checking} onClick={()=>{void refresh();}}>{checking?'Checking...':'Check again'}</button>}/><div className="to-grid" style={{gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,280px),1fr))'}}>{cards.map(c=><Panel key={c.name} title={c.name}><p>{checking?'Checking...':c.ready?'Ready':'Needs attention'}</p><p className="to-note">{c.detail}</p><Link className="to-button" to={c.link}>Open module</Link></Panel>)}</div><Panel title="Device and data setup"><p className="to-note">Live camera and GPS require permission on your device. Phone access needs the trusted HTTPS connection. Passenger road routing requires the internet provider. Traffic prediction needs sufficient continuous live history and must pass validation. These requirements are checked when you use those modules.</p><div className="ml-actions"><Link className="to-button" to="/connect">Phone setup</Link><Link className="to-button" to="/speed">Bus speed and GPS</Link><Link className="to-button" to="/passenger">Plan a journey</Link></div></Panel></div>;
}
