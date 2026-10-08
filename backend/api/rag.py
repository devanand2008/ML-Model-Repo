"""Public route explanations and role-scoped bus advice, never service actions."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from transit.accounts import actor, allowed
from transit.route_rag import ask, status

router=APIRouter(tags=['Route RAG assistant'])

class AskRequest(BaseModel):
    question:str=Field(min_length=3,max_length=800)
    route_context_id:str|None=Field(None,min_length=1,max_length=64)
    model_config={'extra':'forbid'}

class BusAskRequest(AskRequest):
    bus_id:str=Field(pattern=r'^BUS[0-9]{3}$')

@router.get('/public/rag/status')
async def rag_status():
    return status()

@router.post('/public/rag/ask')
async def public_ask(body:AskRequest,db:AsyncSession=Depends(get_db)):
    return await ask(db,body.question,body.route_context_id)

@router.post('/rag/bus-advice')
async def bus_advice(body:BusAskRequest,db:AsyncSession=Depends(get_db),user=Depends(actor)):
    allowed(user,{'admin','head_office','driver'},body.bus_id)
    return await ask(db,body.question,body.route_context_id,body.bus_id)
