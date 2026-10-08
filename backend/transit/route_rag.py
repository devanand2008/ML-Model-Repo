"""Local TF-IDF retrieval + FLAN-T5 generation constrained to cited evidence.

The language model selects an answer from retrieved facts. Routing decisions
come from the actual provider paths and current traffic rank, never model text.
"""
import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import time

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from config import settings
from transit.mobility import nearby_cameras, utc_now, iso
from transit.models import TransitVehicle, TransitRoute
from transit.route_context import resolve
from transit.route_intelligence import annotate_routes

KNOWLEDGE=Path(__file__).with_name('rag_knowledge.json')
MODEL_DIR=settings.weights_dir/'route-rag'/'flan-t5-small'
_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='route-rag')
_engine=None
_inflight=0

def knowledge():
    return json.loads(KNOWLEDGE.read_text(encoding='utf-8'))

def status():
    return {'retriever':'TF-IDF cosine similarity','generator':'google/flan-t5-small',
            'weights_available':(MODEL_DIR/'model.safetensors').is_file(), 'loaded':_engine is not None,
            'knowledge_documents':len(knowledge()),'generation':'constrained to retrieved evidence',
            'cloud_api_required':False,'operating_plan_actions':False}

def retrieve(question,documents,limit=6):
    vectorizer=TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True,strip_accents='unicode')
    matrix=vectorizer.fit_transform([f"{d['title']} {d['text']}" for d in documents])
    scores=cosine_similarity(vectorizer.transform([question]),matrix)[0]
    order=np.argsort(-scores,kind='stable')
    return [{**documents[i],'retrieval_score':round(float(scores[i]),4)} for i in order[:limit]]

def intent_policy(question):
    query=question.lower()
    if re.search(r'\b(speed|gps|km/h|slow|queue)\b',query):return 'policy-speed'
    if re.search(r'\b(forecast|prediction|predict|ridge|accuracy)\b',query):return 'policy-forecast'
    if re.search(r'\b(bus(?:[0-9]{3})?|buses|diversion|operator|approve|stops)\b',query):return 'policy-bus'
    return None

def answer_candidates(question,documents):
    """Keep the small generator focused on the question's retrieved evidence."""
    by_id={d['id']:d for d in documents}
    policy=intent_policy(question)
    targets=[]
    if policy=='policy-speed':
        targets=['policy-speed']+[d['id'] for d in documents if d.get('kind')=='live_camera' and 'GPS speed' in d['text']]
    elif policy=='policy-forecast':
        targets=['policy-forecast']
    elif policy=='policy-bus':
        targets=['policy-bus','bus-service']
    elif 'current-recommendation' in by_id:
        targets=['current-recommendation']
    focused=[by_id[i] for i in targets if i in by_id]
    if focused:
        return focused[:3]
    # For general questions, unrelated low-relevance paragraphs should not
    # displace the retrieval model's strongest supported answers.
    maximum=max((d.get('retrieval_score') or 0 for d in documents),default=0)
    return [d for d in documents if (d.get('retrieval_score') or 0)>=maximum*.75][:3] or documents[:1]

class EvidenceGenerator:
    def __init__(self):
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        self.tokenizer=AutoTokenizer.from_pretrained(MODEL_DIR,local_files_only=True,trust_remote_code=False)
        self.model=AutoModelForSeq2SeqLM.from_pretrained(MODEL_DIR,local_files_only=True,
                                                       trust_remote_code=False,use_safetensors=True).eval()

    def answer(self,question,documents):
        import torch
        # Prefix-constrained decoding guarantees every output is a full retrieved
        # evidence paragraph, including its exact numbers and uncertainty labels.
        trie={};candidates={};maximum=0
        for doc in documents:
            tokens=self.tokenizer.encode(doc['text'],add_special_tokens=True)
            if len(tokens)>190:
                continue
            candidates[tuple(tokens)]=doc
            maximum=max(maximum,len(tokens));node=trie
            for token in tokens:
                node=node.setdefault(token,{})
        if not candidates:
            raise ValueError('No bounded evidence candidates')
        prompt='Answer the question using the provided evidence. Copy the most relevant complete answer.\nQuestion: '+question+'\nEvidence:\n'+'\n'.join(d['text'] for d in documents)
        inputs=self.tokenizer(prompt,return_tensors='pt',truncation=True,max_length=512)
        def allowed(_batch,tokens):
            node=trie
            for token in tokens.tolist()[1:]:
                node=node.get(token,{})
            return list(node) or [self.tokenizer.eos_token_id]
        started=time.perf_counter()
        with torch.inference_mode():
            output=self.model.generate(**inputs,max_new_tokens=maximum,do_sample=False,num_beams=1,
                prefix_allowed_tokens_fn=allowed)
        chosen=candidates.get(tuple(output[0].tolist()[1:]))
        if chosen is None:
            raise ValueError('Generated response failed exact-evidence validation')
        return {'answer':chosen['text'],'answer_source_id':chosen['id'],'generation_mode':'local_neural_constrained',
                'model':'google/flan-t5-small','generation_seconds':round(time.perf_counter()-started,2)}

def generate(question,documents):
    global _engine
    if not status()['weights_available']:
        return {'answer':documents[0]['text'],'answer_source_id':documents[0]['id'],
                'generation_mode':'retrieval_fallback','model':None,'reason':'Local generator weights are not installed. Run Setup-Route-RAG.bat.'}
    try:
        if _engine is None:
            _engine=EvidenceGenerator()
        return _engine.answer(question,answer_candidates(question,documents))
    except Exception:
        from loguru import logger
        logger.exception('Local route RAG generation failed; returning retrieved evidence')
        return {'answer':documents[0]['text'],'answer_source_id':documents[0]['id'],
                'generation_mode':'retrieval_fallback','model':None,'reason':'Local generation unavailable; showing the retrieved source directly.'}

async def ask(db,question,context_id=None,bus_id=None):
    global _inflight
    from fastapi import HTTPException
    if _inflight>=2:
        raise HTTPException(429,'Route assistant is busy. Try again shortly.')
    documents=knowledge()
    ranking=None
    if context_id:
        context=resolve(context_id)
        cameras=await nearby_cameras(db,0,0,None)
        ranking=annotate_routes(context['routes'],cameras,context.get('selected'),context['goal'],context['recorded_demo'])
        for index,route in enumerate(ranking['routes']):
            live=route['observed_camera_count'];recorded=route['recorded_demo_camera_count']
            text=(f"Road option {index+1} covers {route['distance_km']} km with {route['base_duration_minutes']} profile minutes. "
                f"It has {live} usable live camera observations and {route['high_pressure_camera_count']} high-pressure reports. "
                f"Recorded demo observations: {recorded}. Traffic beyond camera coverage is unknown.")
            documents.append({'id':'path-'+route['id'],'title':f'Road alternative {index+1}',
                              'url':'/passenger','text':text,'kind':'provider_path'})
        best=next(r for r in ranking['routes'] if r['id']==ranking['recommended_route_id'])
        chosen=next(r for r in ranking['routes'] if r['id']==ranking['selected_route_id'])
        number=next(i+1 for i,r in enumerate(ranking['routes']) if r['id']==best['id'])
        summary=(f"Road option {number} is currently recommended for {ranking['goal'].replace('_',' ')}. "
                 f"Distance: {best['distance_km']} km. Road-profile time: {best['base_duration_minutes']} minutes. "
                 'This comparison does not establish that the whole route is free of traffic.')
        if best['id']==chosen['id']:
            summary+=' '+ranking['recommendation_reason']
        else:
            summary+=f" Its observed pressure total is {best['observed_pressure_total']} compared with {chosen['observed_pressure_total']} on the selected path; roads without observations remain unknown."
        documents.append({'id':'current-recommendation','title':'Current route recommendation','url':'/passenger',
                          'text':summary,'kind':'current_recommendation'})
        used=set()
        for route in ranking['routes']:
            for camera in route['nearby_cameras']:
                o=camera.get('observation')
                if camera['camera_id'] in used or not o or not o.get('fresh') or not o.get('live') or o.get('source')!='REAL_MODEL_DETECTION':
                    continue
                used.add(camera['camera_id'])
                text=f"Live camera {camera['camera_id']} reports {o['category'].lower()} scene pressure of {o['score']}/100 at {o['timestamp']}. "
                if o.get('bus_speed_kmh') is not None:
                    text+=f"Bus GPS speed at capture: {o['bus_speed_kmh']} km/h. Visible vehicles: {o.get('vehicle_count')}. "
                if o.get('suspected_queue'):
                    text+='Sustained low speed with several vehicles suggests a possible queue; signals or bus stops may also explain it. '
                p=camera.get('prediction',{})
                if p.get('available'):
                    text+=f"Validated one-minute scene-pressure prediction: {p['predicted_score']}/100. "
                documents.append({'id':'live-'+camera['camera_id'],'title':'Live traffic and speed evidence','url':'/speed',
                                  'text':text,'timestamp':o['timestamp'],'kind':'live_camera'})
    if bus_id:
        vehicle=await db.get(TransitVehicle,bus_id)
        if not vehicle:
            raise HTTPException(404,'Bus not found')
        route=await db.get(TransitRoute,vehicle.route_id) if vehicle.route_id else None
        text=f"Bus {bus_id} is assigned to service {vehicle.route_id or 'unassigned'}. "
        if route:
            text+=f"Configured service stops: {', '.join(route.spec.get('stop_ids',[]))}. Current variant: {route.current_variant_id}. This project service network is illustrative demo data. "
        text+='Road alternatives need operator checks of required stops, road restrictions and service direction before any bus diversion.'
        documents.append({'id':'bus-service','title':'Assigned bus service constraints','url':'/fleet','text':text,'kind':'bus_service'})
    retrieved=await asyncio.to_thread(retrieve,question,documents)
    # Decision and service constraints always remain visible even for a very short question.
    required={'current-recommendation'} if ranking else set()
    # Intent-specific policy sources must be available to the constrained decoder.
    policy=intent_policy(question)
    if policy:required.add(policy)
    required|={d['id'] for d in documents if d.get('kind')=='live_camera'}
    if bus_id: required|={'policy-bus','bus-service'}
    for doc in documents:
        if doc['id'] in required and not any(d['id']==doc['id'] for d in retrieved):
            retrieved.append({**doc,'retrieval_score':None})
    snapshot=utc_now()
    if _inflight>=2:
        raise HTTPException(429,'Route assistant is busy. Try again shortly.')
    _inflight+=1
    future=asyncio.get_running_loop().run_in_executor(_executor,generate,question,retrieved)
    def finished(_future):
        global _inflight
        _inflight-=1
    future.add_done_callback(finished)
    try:
        answer=await asyncio.wait_for(asyncio.shield(future),90)
    except asyncio.TimeoutError:
        raise HTTPException(503,'Local assistant timed out. Traffic monitoring and route selection remain available.')
    return {**answer,'question':question,'retriever':'TF-IDF cosine similarity','sources':retrieved,
            'retrieved_at':iso(snapshot),'expires_at':iso(snapshot+timedelta(seconds=20 if ranking else 120)),
            'route_advice':{'recommended_route_id':ranking['recommended_route_id'],'selected_route_id':ranking['selected_route_id'],
                'summary':summary,'options':len(ranking['routes']),'change_advised':ranking['alternative_available'],
                'requires_operator_review':bool(bus_id)} if ranking else None,
            'bus_id':bus_id,'operator_review_required':bool(bus_id),'actions_taken':[],
            'note':'Answers select retrieved evidence. Current route ranking is separate from the language model. Recheck before changing a journey; official bus diversions require operator review.'}
