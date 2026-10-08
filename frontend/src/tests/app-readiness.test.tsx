// @vitest-environment jsdom
import { cleanup,fireEvent,render,screen } from '@testing-library/react';
import { MemoryRouter,Route,Routes } from 'react-router-dom';
import { afterEach,describe,expect,it,vi } from 'vitest';
import ModuleErrorBoundary from '../components/ModuleErrorBoundary';
import AppStatusPage from '../pages/transit/AppStatusPage';
import MLWorkspacePage from '../pages/transit/MLWorkspacePage';
const request=vi.hoisted(()=>vi.fn());
vi.mock('../services/transit',()=>({transitRequest:request}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks();});
describe('Usability and recovery',()=>{
  it('a failed module offers recovery and another route still opens',async()=>{
    vi.spyOn(console,'error').mockImplementation(()=>{});
    function Broken(){throw new Error('Fixture rendering error');return null;}
    render(<MemoryRouter initialEntries={['/broken']}><ModuleErrorBoundary><Routes><Route path="/broken" element={<Broken/>}/><Route path="/" element={<h1>App home works</h1>}/></Routes></ModuleErrorBoundary></MemoryRouter>);
    expect(screen.getByRole('alert').textContent).toContain('This module could not open');
    fireEvent.click(screen.getByRole('link',{name:'App home'}));
    await screen.findByText('App home works');
  });
  it('readiness reports a failed model endpoint while showing working services',async()=>{
    request.mockImplementation(async(path:string)=>{
      if(path==='/api/models/status')throw new Error('Model status unavailable');
      if(path==='/api/system/status')return {database:'connected',forecast:{ready:true,algorithm:'XGBoost'},optimizer:{available:true,engine:'OR-Tools'}};
      return {weights_available:true,generator:'FLAN-T5'};
    });
    render(<MemoryRouter><AppStatusPage/></MemoryRouter>);
    await screen.findByText('XGBoost');
    expect(screen.getAllByText('Ready')).toHaveLength(4);
    expect(screen.getAllByText('Needs attention')).toHaveLength(2);
    expect(screen.getAllByText('Model status unavailable')).toHaveLength(2);
  });
  it('moving bus mode keeps the vehicle model and explains GPS setup',async()=>{
    request.mockResolvedValue({cameras:[{id:'CAM01',role:'road_traffic',name:'Fixed signal'},
      {id:'BUS_ROAD_001',role:'bus_road',bus_id:'BUS005',name:'Bus road'},
      {id:'BUS_CAM_001',role:'bus_interior',name:'Bus interior'}],
      models:{detection_models:[{type:'general',filename:'vehicle.pt',is_default:true,weights_available:true},
      {type:'human',filename:'people.pt',is_default:true,weights_available:true}]},road_cameras:[]});
    render(<MemoryRouter><MLWorkspacePage/></MemoryRouter>);
    await screen.findByText('vehicle.pt');
    fireEvent.click(screen.getByRole('button',{name:/Moving bus road camera/}));
    expect(screen.getByRole('link',{name:/Open this device camera/}).getAttribute('href')).toBe('/webcam?mode=general&camera_id=BUS_ROAD_001');
    expect(screen.getByText(/click Share bus GPS speed/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:/Inside the bus/}));
    expect(screen.getByRole('link',{name:/Open this device camera/}).getAttribute('href')).toBe('/webcam?mode=human&camera_id=BUS_CAM_001');
    expect(screen.getByText('people.pt')).toBeTruthy();
  });
});
