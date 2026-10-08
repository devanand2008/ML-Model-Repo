import { useEffect, useRef, useState, type FormEvent } from 'react';
import { BrainCircuit, ArrowRight } from 'lucide-react';
import { transitRequest, type Data } from '../../services/transit';
import './route-rag.css';

type Props={contextId?:string|null;busId?:string|null;recommendedId?:string|null;onSelect?:(id:string)=>void};
export default function RouteRagAssistant({contextId,busId,recommendedId,onSelect}:Props){
  const [question,setQuestion]=useState('Why should I change my route?');
  const [result,setResult]=useState<Data|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[now,setNow]=useState(Date.now());
  const controller=useRef<AbortController|null>(null),version=useRef(0);
  useEffect(()=>{controller.current?.abort();version.current+=1;setResult(null);setBusy(false);setError('');return()=>{controller.current?.abort();version.current+=1;};},[contextId,busId]);
  useEffect(()=>{if(!result)return;const timer=window.setInterval(()=>setNow(Date.now()),1000);return()=>window.clearInterval(timer);},[result]);
  const expired=Boolean(result && now>=new Date(result.expires_at).getTime());
  async function ask(event?:FormEvent,prompt=question){
    event?.preventDefault();if(prompt.trim().length<3)return;
    controller.current?.abort();const next=new AbortController();controller.current=next;
    const revision=++version.current;setBusy(true);setError('');setResult(null);
    try{
      const answer=await transitRequest<Data>(busId?'/api/rag/bus-advice':'/api/public/rag/ask',{
        method:'POST',signal:next.signal,body:JSON.stringify({question:prompt,route_context_id:contextId??undefined,...(busId?{bus_id:busId}:{})})});
      if(revision===version.current){setResult(answer);setNow(Date.now());}
    }catch(e){if(revision===version.current&&!next.signal.aborted)setError((e as Error).message);}
    finally{if(revision===version.current)setBusy(false);}
  }
  return <section className="rag-assistant" aria-label="Route RAG assistant"><h2><BrainCircuit size={19}/>Route evidence assistant</h2><p className="rag-note">{busId?`Bus ${busId}: route advice includes operator review and required-stop constraints.`:contextId?'Ask about these road alternatives and current traffic evidence.':'Ask how route selection, speed and traffic prediction work. Set two map points for journey-specific advice.'}</p>
    <form onSubmit={e=>{void ask(e);}}><label>Ask about your route<textarea aria-label="Route question" maxLength={800} rows={2} value={question} onChange={e=>setQuestion(e.target.value)}/></label><button type="submit" disabled={busy||question.trim().length<3}>{busy?'Retrieving and reading evidence...':'Ask RAG assistant'}<ArrowRight size={15}/></button></form>
    <div className="rag-prompts">{['Why should I change my route?','What does the bus speed warning mean?','Can a bus use this alternative?'].map(prompt=><button key={prompt} disabled={busy} onClick={()=>{setQuestion(prompt);void ask(undefined,prompt);}}>{prompt}</button>)}</div>
    {error&&<p className="rag-error" role="alert">{error}</p>}
    {result&&<div className={`rag-result ${expired?'expired':''}`}><p className="rag-engine">{result.generation_mode==='local_neural_constrained'?'Local FLAN-T5 + retrieved evidence':'Retrieved evidence fallback'}</p><p className="rag-answer">{result.answer}</p><small>Answer source: {result.answer_source_id}</small>{result.route_advice&&<div className="rag-advice"><strong>Current road recommendation</strong><p>{result.route_advice.summary}</p>{result.operator_review_required&&<strong>Bus diversion requires operator review.</strong>}</div>}
      <p className="rag-note">Evidence snapshot {new Date(result.retrieved_at).toLocaleTimeString()}{expired?' - refresh before acting':''}. {result.note}</p>
      {expired&&<button onClick={()=>{void ask();}} disabled={busy}>Refresh route evidence</button>}
      {onSelect&&result.route_advice&&<button disabled={expired||result.operator_review_required||result.route_advice.change_advised===false||result.route_advice.recommended_route_id!==recommendedId} onClick={()=>onSelect(result.route_advice.recommended_route_id)}>Select recommended road route</button>}
      <details><summary>Retrieved sources ({result.sources.length})</summary>{result.sources.map((source:Data)=><article key={source.id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a><small>{source.id}{source.retrieval_score!=null?` | relevance ${source.retrieval_score}`:''}{source.timestamp?` | ${new Date(source.timestamp).toLocaleTimeString()}`:''}</small><p>{source.text}</p></article>)}</details>
    </div>}
  </section>;
}
