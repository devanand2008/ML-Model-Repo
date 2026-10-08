// @vitest-environment jsdom
import { act,cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react';
import { afterEach,describe,expect,it,vi } from 'vitest';
import RouteRagAssistant from '../components/transit/RouteRagAssistant';
const request=vi.hoisted(()=>vi.fn());
vi.mock('../services/transit',()=>({transitRequest:request}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks();});
const answer=()=>({answer:'Camera reports possible slow traffic.',answer_source_id:'live-signal',generation_mode:'local_neural_constrained',
  sources:[{id:'live-signal',url:'/speed',title:'Live signal evidence',text:'Camera reports possible slow traffic.',retrieval_score:.8}],
  retrieved_at:new Date().toISOString(),expires_at:new Date(Date.now()+60000).toISOString(),note:'Check current evidence.',
  route_advice:{recommended_route_id:'other',summary:'Road option 2 ranks first.'},operator_review_required:false});
describe('Route RAG evidence UI',()=>{
  it('asks with provider context and displays sources before explicit road selection',async()=>{
    request.mockResolvedValue(answer());const select=vi.fn();
    render(<RouteRagAssistant contextId="provider-context" recommendedId="other" onSelect={select}/>);
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Ask RAG assistant'}));
    await screen.findByText('Local FLAN-T5 + retrieved evidence');
    expect(JSON.parse(request.mock.calls[0][1].body)).toMatchObject({route_context_id:'provider-context'});
    expect(request.mock.calls[0][0]).toBe('/api/public/rag/ask');
    expect(screen.getByText('Answer source: live-signal')).toBeTruthy();
    expect(select).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Select recommended road route'));expect(select).toHaveBeenCalledWith('other');
  });
  it('bus advice uses the authenticated API and cannot activate a road recommendation',async()=>{
    request.mockResolvedValue({...answer(),operator_review_required:true});const select=vi.fn();
    render(<RouteRagAssistant busId="BUS005" contextId="provider-context" recommendedId="other" onSelect={select}/>);
    fireEvent.click(screen.getByRole('button',{name:'Ask RAG assistant'}));
    await screen.findByText('Bus diversion requires operator review.');
    expect(request.mock.calls[0][0]).toBe('/api/rag/bus-advice');
    expect(JSON.parse(request.mock.calls[0][1].body).bus_id).toBe('BUS005');
    const button=screen.getByText('Select recommended road route') as HTMLButtonElement;
    expect(button.disabled).toBe(true);fireEvent.click(button);expect(select).not.toHaveBeenCalled();
  });
  it('a new journey discards a delayed answer for an old context',async()=>{
    let resolve:(data:any)=>void=()=>{};request.mockImplementation(()=>new Promise(done=>{resolve=done;}));
    const mounted=render(<RouteRagAssistant contextId="old"/>);
    fireEvent.click(screen.getByRole('button',{name:'Ask RAG assistant'}));
    mounted.rerender(<RouteRagAssistant contextId="new"/>);
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async()=>resolve(answer()));
    expect(screen.queryByText('Local FLAN-T5 + retrieved evidence')).toBeNull();
    await waitFor(()=>expect((screen.getByRole('button',{name:'Ask RAG assistant'}) as HTMLButtonElement).disabled).toBe(false));
  });
  it('an expired traffic answer disables changing the route',async()=>{
    request.mockResolvedValue({...answer(),expires_at:new Date(Date.now()-1000).toISOString()});
    render(<RouteRagAssistant contextId="provider-context" recommendedId="other" onSelect={vi.fn()}/>);
    fireEvent.click(screen.getByRole('button',{name:'Ask RAG assistant'}));
    await screen.findByText('Refresh route evidence');
    expect((screen.getByText('Select recommended road route') as HTMLButtonElement).disabled).toBe(true);
  });
  it('keeps automatic routing intact when the selected path already ranks first',async()=>{
    request.mockResolvedValue({...answer(),route_advice:{recommended_route_id:'same',summary:'The selected path already ranks first.',change_advised:false}});
    const select=vi.fn();render(<RouteRagAssistant contextId="provider-context" recommendedId="same" onSelect={select}/>);
    fireEvent.click(screen.getByRole('button',{name:'Ask RAG assistant'}));
    await screen.findByText('The selected path already ranks first.');
    const button=screen.getByText('Select recommended road route') as HTMLButtonElement;
    expect(button.disabled).toBe(true);fireEvent.click(button);expect(select).not.toHaveBeenCalled();
  });
});
