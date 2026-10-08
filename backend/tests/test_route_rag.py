"""Actual retrieval quality and bounded provider-context integrity."""
import sys
from pathlib import Path
import pytest
from fastapi import HTTPException
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transit.route_rag import retrieve,knowledge,answer_candidates
from transit import route_context

def test_speed_question_retrieves_speed_rule_with_citation():
    retrieved=retrieve('bus GPS speed km/h slow queue three vehicles',knowledge(),3)
    assert retrieved[0]['id']=='policy-speed'
    assert retrieved[0]['retrieval_score']>0
    assert '10 km/h' in retrieved[0]['text']
    assert retrieved[0]['url']=='/speed'

def test_bus_service_question_retrieves_review_rule_without_private_safety_data():
    docs=retrieve('bus diversion operator approval required stops accessibility',knowledge(),2)
    assert docs[0]['id']=='policy-bus'
    assert 'cannot approve' in docs[0]['text']
    assert all('password' not in d['text'].lower() for d in docs)

def test_passenger_journey_answer_focuses_on_current_recommendation_not_bus_service_rules():
    documents=knowledge()+[{'id':'current-recommendation','title':'Current route','text':'Road option 2 ranks first.'}]
    assert [d['id'] for d in answer_candidates('Which road option should I choose?',documents)]==['current-recommendation']
    assert [d['id'] for d in answer_candidates('Can the bus change its route?',documents)]==['policy-bus']
    assert [d['id'] for d in answer_candidates('Can BUS005 change its route?',documents)]==['policy-bus']
    assert [d['id'] for d in answer_candidates('Explain GPS speed',documents)]==['policy-speed']

def test_context_is_copy_isolated_expires_and_is_bounded(monkeypatch):
    monkeypatch.setattr(route_context,'_contexts',route_context.OrderedDict())
    now=[100.];monkeypatch.setattr(route_context.time,'monotonic',lambda:now[0])
    paths=[dict(id='provider',geometry=[[78,11],[78.1,11.1]],distance_km=4,base_duration_minutes=8)]
    token=route_context.remember(paths,{}, {},'fastest',False)
    paths[0]['distance_km']=999
    copy=route_context.resolve(token);copy['routes'][0]['distance_km']=0
    assert route_context.resolve(token)['routes'][0]['distance_km']==4
    for _ in range(route_context.MAX_CONTEXTS):
        route_context.remember(paths,{}, {},'fastest',False)
    assert len(route_context._contexts)==route_context.MAX_CONTEXTS
    with pytest.raises(HTTPException) as evicted:route_context.resolve(token)
    assert evicted.value.status_code==409
    current=next(iter(route_context._contexts));now[0]+=route_context.TTL+1
    with pytest.raises(HTTPException):route_context.resolve(current)
