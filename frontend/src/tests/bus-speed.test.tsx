// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import BusSpeedGps from '../components/transit/BusSpeedGps';
import BusSpeedPage from '../pages/transit/BusSpeedPage';
const post=vi.hoisted(()=>vi.fn());
const request=vi.hoisted(()=>vi.fn());
vi.mock('../services/transit',()=>({postTransit:post,transitRequest:request}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks();});
describe('Moving bus speed module',()=>{
  it('shares bus GPS only after permission click and releases it on stop',async()=>{
    let callback:(p:any)=>void=()=>{};
    const watch=vi.fn(fn=>{callback=fn;return 44;}), clear=vi.fn();
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{watchPosition:watch,clearWatch:clear}});
    post.mockResolvedValue({});
    render(<BusSpeedGps busId="BUS005"/>);
    expect(watch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Share bus GPS speed'));
    await act(async()=>callback({coords:{latitude:11.67,longitude:78.14,accuracy:5,speed:10,heading:90}}));
    expect(post).toHaveBeenCalledWith('/api/buses/BUS005/location',expect.objectContaining({speed_kmh:36,source:'browser_geolocation',accuracy_m:5}));
    fireEvent.click(screen.getByText('Stop bus GPS speed'));
    expect(clear).toHaveBeenCalledWith(44);
  });
  it('shows missing speed honestly and links the assigned camera and bus route',async()=>{
    request.mockResolvedValue({cameras:[{id:'BUS_ROAD_001',bus_id:'BUS005',name:'Forward road',state:'awaiting_live_camera',gps_speed:{available:false,reason:'Fresh GPS required.'},live_evidence:false}]});
    render(<MemoryRouter><BusSpeedPage/></MemoryRouter>);
    await screen.findByText('Speed unavailable');
    expect(screen.getByText('Fresh GPS required.')).toBeTruthy();
    expect(screen.getByRole('link',{name:'Camera + GPS'}).getAttribute('href')).toBe('/webcam?mode=general&camera_id=BUS_ROAD_001');
    expect(screen.getByRole('link',{name:'Plan from this bus'}).getAttribute('href')).toBe('/passenger?bus_id=BUS005');
  });
  it('stops publishing after an authorization error',async()=>{
    let callback:(p:any)=>void=()=>{};const clear=vi.fn();
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{watchPosition:(fn:any)=>{callback=fn;return 4;},clearWatch:clear}});
    post.mockRejectedValue(new Error('This bus is not assigned to you.'));
    render(<BusSpeedGps busId="BUS005"/>);fireEvent.click(screen.getByText('Share bus GPS speed'));
    await act(async()=>callback({coords:{latitude:11,longitude:78,accuracy:5,speed:null,heading:null}}));
    await waitFor(()=>expect(clear).toHaveBeenCalledWith(4));
    expect(screen.getByRole('status').textContent).toContain('not assigned');
  });
});
