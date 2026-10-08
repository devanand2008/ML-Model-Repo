import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeading, Panel, ErrorNotice } from '../../components/transit/Shared';
import RouteRagAssistant from '../../components/transit/RouteRagAssistant';
import { transitRequest,type Data } from '../../services/transit';

export default function RouteRagPage(){
  const [status,setStatus]=useState<Data|null>(null),[buses,setBuses]=useState<Data[]>([]),[busId,setBusId]=useState(''),[error,setError]=useState('');
  useEffect(()=>{let active=true;Promise.all([transitRequest('/api/public/rag/status'),transitRequest('/api/public/buses')]).then(([model,data])=>{if(active){setStatus(model);setBuses(data.buses??[]);}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
  return <div className="to-page"><PageHeading eyebrow="RETRIEVAL AUGMENTED ROUTE ASSISTANT" title="Route RAG assistant" description="Retrieve traffic evidence and service rules, then use the local language model to provide a cited explanation." actions={<Link className="to-button" to="/passenger">Choose two map points</Link>}/><ErrorNotice message={error}/>
    <Panel title="Local RAG models"><div className="rag-model-info"><strong>{status?.retriever??'Loading retriever...'}</strong><span>{status?.generator??'Loading generator...'}</span><span>{status?.weights_available?'Local weights installed':'Run Setup-Route-RAG.bat to install weights'}</span><span>{status?.knowledge_documents??0} knowledge sources + current journey evidence</span></div><p className="to-note">The language model explains retrieved evidence. Road ranking uses current camera observations and verified provider paths. It does not approve bus-service changes.</p></Panel>
    <Panel title="Passenger or bus advice"><label className="to-field">Advice for<select aria-label="RAG advice for" value={busId} onChange={e=>setBusId(e.target.value)}><option value="">Passenger / general route questions</option>{buses.map(bus=><option key={bus.id} value={bus.id}>{bus.id} {bus.registration_number??''}</option>)}</select></label><RouteRagAssistant busId={busId||null}/>{busId&&<Link className="to-button primary" to={`/passenger?bus_id=${encodeURIComponent(busId)}&advice=bus`}>Compare road alternatives from this bus GPS</Link>}<p className="to-note">For an explanation of a specific journey, set the endpoints on the passenger map and ask its embedded assistant. Bus advice requires admin, head-office or assigned-driver access.</p></Panel>
  </div>;
}
