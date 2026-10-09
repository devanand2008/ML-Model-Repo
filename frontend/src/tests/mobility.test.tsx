// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PassengerPage from '../pages/transit/PassengerPage';
import DriverPage from '../pages/transit/DriverPage';
import { ThemeProvider } from '../context/ThemeContext';

const request = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const credentials = vi.hoisted(() => vi.fn());
const mapEvents = vi.hoisted(() => ({ click:null as null|((event:any)=>void), dragstart:null as null|(()=>void), flyTo:vi.fn(), setView:vi.fn() }));
vi.mock('../services/transit', () => ({ transitRequest: request, postTransit: post }));
vi.mock('../services/api', () => ({ setCredentials: credentials }));
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: any) => <div data-testid="real-map">{children}</div>,
  TileLayer: () => null, ZoomControl:()=>null, Circle: () => null, CircleMarker: ({ children }: any) => <>{children}</>,
  Marker: ({ children }: any) => <>{children}</>, Polyline: ({children,pathOptions,eventHandlers}:any) => <button data-testid="road-polyline" data-color={pathOptions?.color} data-weight={pathOptions?.weight} onClick={()=>eventHandlers?.click?.()}>{children}</button>,
  Popup: ({ children }: any) => <>{children}</>, Tooltip: ({ children }: any) => <>{children}</>,
  useMap: () => ({ flyTo: mapEvents.flyTo, setView: mapEvents.setView, fitBounds: vi.fn(), getZoom: () => 13 }), useMapEvents: (handlers:any) => {mapEvents.click=handlers.click;mapEvents.dragstart=handlers.dragstart;},
}));
afterEach(() => {cleanup();vi.useRealTimers();vi.restoreAllMocks();});

beforeEach(() => {
  vi.clearAllMocks();
  request.mockImplementation(async (path: string) => {
    if (path === '/api/public/stops') return { stops: [] };
    if (path.startsWith('/api/public/navigation/places')) return { places: [{ name: 'Five Roads, Salem', latitude: 11.6757, longitude: 78.1402 }] };
    if (path.startsWith('/api/public/traffic/nearby')) return { cameras: [] };
    if (path.startsWith('/api/navigation/nearby-buses')) return { buses: [] };
    if (path === '/api/public/navigation/routes') return { routes: [{ id: 'road-0', geometry: [[78.14, 11.67], [78.15, 11.68]], distance_km: 2, base_duration_minutes: 4, observed_camera_count: 0 }], selected_route_id: 'road-0', traffic_note: 'Traffic unknown.' };
    if (path === '/api/public/navigation/monitor') return {routes: [{id:'road-0',geometry:[[78.14,11.67],[78.15,11.68]],distance_km:2,base_duration_minutes:4,observed_camera_count:0}],selected_route_id:'road-0',route_alerts:[]};
    if (path === '/api/mobility/session') return { username: 'driver_test', role: 'driver', bus_id: 'BUS005' };
    if (path === '/api/buses/BUS005') return { id: 'BUS005', registration_number: 'TN30-N-1234', route_id: 'R02', tracking_status: 'unavailable', public_safety_status: 'No active reported incident' };
    if (path === '/api/mobility/cameras') return { cameras: [] };
    if (path === '/api/buses/BUS005/safety-status') return { events: [] };
    return {};
  });
  post.mockResolvedValue({});
});

describe('Passenger and driver mobility flows', () => {
  it('finds minimum and maximum live traffic places while keeping approximate and recorded pins unknown',async()=>{
    const base=request.getMockImplementation();
    const cameras=[['quiet',10,'LOW'],['busy',90,'SEVERE']].map(([id,score,category],index)=>({id,name:`${id} signal`,latitude:11.67+index*.01,longitude:78.14,
      coordinate_source:'operator_configured',camera_role:'road_traffic',observation:{live:true,fresh:true,score,category,source:'REAL_MODEL_DETECTION',timestamp:new Date().toISOString()}}));
    cameras.push({...cameras[0],id:'demo',name:'demo pin',coordinate_source:'illustrative_demo_coordinate'});
    request.mockImplementation(async(path:string,init?:any)=>path==='/api/public/traffic/feed'?{cameras,alerts:[]}:base?.(path,init));
    render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    await waitFor(()=>expect((screen.getByRole('button',{name:'Find minimum observed traffic'}) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button',{name:'Find minimum observed traffic'}));
    expect(mapEvents.flyTo).toHaveBeenCalledWith([11.67,78.14],13);
    fireEvent.click(screen.getByRole('button',{name:'Find maximum observed traffic'}));
    expect(mapEvents.flyTo).toHaveBeenCalledWith([11.68,78.14],13);
    expect(screen.getByText('1 cameras with unknown current traffic')).toBeTruthy();
    expect(screen.getAllByText(/Approximate camera location/).length).toBeGreaterThan(0);
  });
  it('starts location watching only on request, follows the dot, lets a map drag pause following and clears the watch',async()=>{
    let update:((position:any)=>void)|undefined;
    const watch=vi.fn((success:any)=>{update=success;return 71;});
    const clear=vi.fn();
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{watchPosition:watch,clearWatch:clear,getCurrentPosition:vi.fn()}});
    const view=render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    expect(watch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Start live location tracking'}));
    await waitFor(()=>expect(watch).toHaveBeenCalledOnce());
    act(()=>update?.({coords:{latitude:11.67,longitude:78.14,accuracy:8}}));
    expect(mapEvents.setView).toHaveBeenCalledWith([11.67,78.14],15,{animate:true});
    act(()=>mapEvents.dragstart?.());
    expect(screen.getByText('Location tracking on · Recenter to follow')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'Recenter on my location'}));
    expect(screen.getByText('Following your location')).toBeTruthy();
    view.unmount();expect(clear).toHaveBeenCalledWith(71);
  });
  it('updates the route after useful GPS movement while ignoring noisy or inaccurate fixes',async()=>{
    let update:((position:any)=>void)|undefined;
    let now=Date.now();vi.spyOn(Date,'now').mockImplementation(()=>now);
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{watchPosition:(success:any)=>{update=success;return 81;},clearWatch:vi.fn()}});
    render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    act(()=>mapEvents.click?.({latlng:{lat:11.67,lng:78.14}}));
    act(()=>mapEvents.click?.({latlng:{lat:11.68,lng:78.15}}));
    await waitFor(()=>expect(request.mock.calls.filter(([path])=>path==='/api/public/navigation/routes')).toHaveLength(1));
    fireEvent.click(screen.getByRole('button',{name:'Start live location tracking'}));
    await waitFor(()=>expect(request.mock.calls.filter(([path])=>path==='/api/public/navigation/routes')).toHaveLength(2));
    now+=31000;
    act(()=>update?.({coords:{latitude:11.675,longitude:78.145,accuracy:800}}));
    await act(async()=>{});
    expect(request.mock.calls.filter(([path])=>path==='/api/public/navigation/routes')).toHaveLength(2);
    act(()=>update?.({coords:{latitude:11.672,longitude:78.142,accuracy:8}}));
    await waitFor(()=>expect(request.mock.calls.filter(([path])=>path==='/api/public/navigation/routes')).toHaveLength(3));
    const calls=request.mock.calls.filter(([path])=>path==='/api/public/navigation/routes');
    expect(JSON.parse(calls[calls.length-1][1].body).origin).toEqual({latitude:11.672,longitude:78.142});
    now+=1000;
    act(()=>update?.({coords:{latitude:11.6721,longitude:78.1421,accuracy:8}}));
    await act(async()=>{});
    expect(request.mock.calls.filter(([path])=>path==='/api/public/navigation/routes')).toHaveLength(3);
  });
  it('loads multiple blue road paths after two map clicks and supports manual line selection',async()=>{
    const base=request.getMockImplementation();
    const paths=[{id:'first',geometry:[[78.14,11.67],[78.15,11.68]],distance_km:2,base_duration_minutes:4},
      {id:'other',geometry:[[78.14,11.67],[78.16,11.68]],distance_km:3,base_duration_minutes:5}];
    request.mockImplementation(async(path:string,init?:any)=>{
      if(path==='/api/public/navigation/routes')return {routes:paths,selected_route_id:'first',recommended_route_id:'first',route_context_id:'provider-context'};
      if(path==='/api/public/navigation/monitor')return {routes:paths,selected_route_id:JSON.parse(init.body).selected_route_id,recommended_route_id:'first',route_alerts:[]};
      return base?.(path,init);
    });
    render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    act(()=>mapEvents.click?.({latlng:{lat:11.67,lng:78.14}}));
    expect(screen.getByText('2. Click the map to choose your destination.')).toBeTruthy();
    act(()=>mapEvents.click?.({latlng:{lat:11.68,lng:78.15}}));
    await screen.findByText(/2 ways to reach your destination/);
    const planned=request.mock.calls.find(([path])=>path==='/api/public/navigation/routes');
    expect(JSON.parse(planned![1].body)).toMatchObject({origin:{latitude:11.67,longitude:78.14},destination:{latitude:11.68,longitude:78.15}});
    const lines=screen.getAllByTestId('road-polyline');
    expect(lines).toHaveLength(2);
    expect(lines[0].getAttribute('data-color')).toBe('#1267e9');
    expect(lines[1].getAttribute('data-color')).toBe('#60a5fa');
    expect(lines[0].getAttribute('data-weight')).toBe('8');
    fireEvent.click(lines[1]);
    expect((screen.getByLabelText('Automatically select and update my route') as HTMLInputElement).checked).toBe(false);
    expect(screen.getAllByTestId('road-polyline')[1].getAttribute('data-weight')).toBe('8');
    fireEvent.click(screen.getByText('New map journey'));
    expect(screen.queryAllByTestId('road-polyline')).toHaveLength(0);
    expect(screen.getByText('1. Click the map to choose your start.')).toBeTruthy();
  });
  it('shows new route traffic and lets the passenger choose a recommended alternative', async () => {
    const ticks: (()=>Promise<void>)[]=[];
    const originalInterval=window.setInterval.bind(window);
    vi.spyOn(window,'setInterval').mockImplementation(((callback:any,ms:number)=>{
      if(ms===5000)ticks.push(callback);
      return originalInterval(callback,ms);
    }) as typeof window.setInterval);
    const base=request.getMockImplementation();
    const paths=[{id:'first',geometry:[[78.14,11.67],[78.15,11.68]],distance_km:2,base_duration_minutes:4},
      {id:'other',geometry:[[78.14,11.67],[78.16,11.68]],distance_km:3,base_duration_minutes:5}];
    let congested=false;
    request.mockImplementation(async(path:string,init?:any)=> {
      if(path==='/api/public/navigation/routes')return {routes:paths,selected_route_id:'first',recommended_route_id:'first'};
      if(path==='/api/public/navigation/monitor')return {routes:paths,selected_route_id:JSON.parse(init.body).selected_route_id,
        recommended_route_id:congested?'other':'first',route_alerts:congested?[{id:'signal',message:'Signal camera reports severe pressure.'}]:[]};
      return base?.(path,init);
    });
    const gps=vi.fn((success:any)=>success({coords:{latitude:11.67,longitude:78.14,accuracy:5}}));
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition:gps}});
    render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    fireEvent.click(screen.getByLabelText('Automatically select and update my route'));
    fireEvent.click(screen.getByText('Use my GPS'));
    fireEvent.change(screen.getByLabelText('Search destination'),{target:{value:'Five Roads'}});
    fireEvent.click(screen.getByText('Search'));fireEvent.click(await screen.findByText('Five Roads, Salem'));
    fireEvent.click(screen.getByText('Find road routes'));
    await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/public/navigation/monitor',expect.anything()));
    congested=true;
    await act(async()=>{for(const tick of ticks)await tick();});
    expect(screen.getByRole('alert').textContent).toContain('Traffic detected on your route');
    const monitorCalls=request.mock.calls.filter(([path])=>path==='/api/public/navigation/monitor');
    expect(JSON.parse(monitorCalls[monitorCalls.length-1][1].body).selected_route_id).toBe('first');
    fireEvent.click(screen.getByRole('button',{name:/Use recommended alternative/}));
    await act(async()=>{});
    const changed=request.mock.calls.filter(([path])=>path==='/api/public/navigation/monitor');
    const latest=changed[changed.length-1];
    expect(JSON.parse(latest![1].body).selected_route_id).toBe('other');
    expect(screen.getAllByText(/3.0 km · 5 min/).length).toBeGreaterThan(0);
  });
  it('automatically switches to the better route when new traffic arrives and allows a manual override', async () => {
    const ticks: (()=>Promise<void>)[]=[];
    const originalInterval=window.setInterval.bind(window);
    vi.spyOn(window,'setInterval').mockImplementation(((callback:any,ms:number)=>{
      if(ms===5000)ticks.push(callback);
      return originalInterval(callback,ms);
    }) as typeof window.setInterval);
    const base=request.getMockImplementation();
    const paths=[{id:'first',geometry:[[78.14,11.67],[78.15,11.68]],distance_km:2,base_duration_minutes:4},
      {id:'other',geometry:[[78.14,11.67],[78.16,11.68]],distance_km:3,base_duration_minutes:5}];
    let congested=false;
    request.mockImplementation(async(path:string,init?:any)=> {
      if(path==='/api/public/navigation/routes')return {routes:paths,selected_route_id:'first',recommended_route_id:'first'};
      if(path==='/api/public/navigation/monitor')return {routes:paths,selected_route_id:JSON.parse(init.body).selected_route_id,
        recommended_route_id:congested?'other':'first',route_alerts:congested?[{id:'signal',message:'Signal camera reports severe pressure.'}]:[]};
      return base?.(path,init);
    });
    const gps=vi.fn((success:any)=>success({coords:{latitude:11.67,longitude:78.14,accuracy:5}}));
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition:gps}});
    render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    fireEvent.click(screen.getByText('Use my GPS'));
    fireEvent.change(screen.getByLabelText('Search destination'),{target:{value:'Five Roads'}});
    fireEvent.click(screen.getByText('Search'));fireEvent.click(await screen.findByText('Five Roads, Salem'));
    fireEvent.click(screen.getByText('Find road routes'));
    await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/public/navigation/monitor',expect.anything()));
    congested=true;
    await act(async()=>{for(const tick of ticks)await tick();});
    expect(screen.getByRole('alert').textContent).toContain('Traffic detected on your route');
    await waitFor(()=>expect(screen.getByRole('status').textContent).toContain('Route updated automatically'));
    const changed=request.mock.calls.filter(([path])=>path==='/api/public/navigation/monitor');
    expect(JSON.parse(changed[changed.length-1][1].body).selected_route_id).toBe('other');
    fireEvent.click(screen.getByRole('button',{name:/Primary road route/}));
    expect((screen.getByLabelText('Automatically select and update my route') as HTMLInputElement).checked).toBe(false);
    await act(async()=>{for(const tick of ticks)await tick();});
    expect(screen.getByRole('button',{name:/Primary road route/}).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByText(/3.0 km · 5 min/).length).toBeGreaterThan(0);
  });
  it('requests GPS only after a click and keeps route choice in the passenger map', async () => {
    const gps = vi.fn((success: any) => success({ coords: { latitude: 11.6649, longitude: 78.146, accuracy: 9 } }));
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition: gps, watchPosition: vi.fn(), clearWatch: vi.fn() } });
    render(<ThemeProvider><MemoryRouter><PassengerPage /></MemoryRouter></ThemeProvider>);
    expect(gps).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Use my GPS'));
    expect(gps).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText('Search destination'), { target: { value: 'Five Roads' } });
    fireEvent.click(screen.getByText('Search'));
    fireEvent.click(await screen.findByText('Five Roads, Salem'));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/public/navigation/routes', expect.objectContaining({ method: 'POST' })));
    const call = request.mock.calls.find(([path]) => path === '/api/public/navigation/routes');
    expect(JSON.parse(call![1].body)).toMatchObject({ origin: { latitude: 11.6649 }, destination: { latitude: 11.6757 } });
    expect(screen.getByText('Primary road route')).toBeTruthy();
    const google = new URL(screen.getByRole('link', { name: /Open in Google Maps/ }).getAttribute('href')!);
    expect(google.origin).toBe('https://www.google.com');
    expect(google.searchParams.get('origin')).toBe('11.6649,78.146');
    expect(google.searchParams.get('destination')).toBe('11.6757,78.1402');
    expect(screen.getByText('Unobserved roads are not confirmed clear')).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it('ignores an old route response after the origin changes', async () => {
    const base = request.getMockImplementation();
    const pending: { resolve: (data:any)=>void; signal:AbortSignal }[] = [];
    request.mockImplementation((path:string, init?:any) => {
      if(path === '/api/public/navigation/routes') return new Promise(resolve => pending.push({resolve,signal:init.signal}));
      if(path === '/api/public/navigation/monitor') {
        const routes=JSON.parse(init.body).routes;
        return Promise.resolve({routes,selected_route_id:routes[0].id,recommended_route_id:routes[0].id,route_alerts:[]});
      }
      return base?.(path,init);
    });
    let latitude = 11.67;
    Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition:(success:any)=>success({coords:{latitude,longitude:78.14,accuracy:5}})}});
    render(<ThemeProvider><MemoryRouter><PassengerPage/></MemoryRouter></ThemeProvider>);
    fireEvent.click(screen.getByText('Use my GPS'));
    fireEvent.change(screen.getByLabelText('Search destination'),{target:{value:'Five Roads'}});
    fireEvent.click(screen.getByText('Search'));
    fireEvent.click(await screen.findByText('Five Roads, Salem'));
    await waitFor(()=>expect(pending).toHaveLength(1));
    latitude = 11.68;
    fireEvent.click(screen.getByText('Use my GPS'));
    await waitFor(()=>expect(pending).toHaveLength(2));
    expect(pending[0].signal.aborted).toBe(true);
    const response = (id:string, distance:number) => ({routes:[{id,geometry:[[78.14,11.67],[78.15,11.68]],distance_km:distance,base_duration_minutes:5}],selected_route_id:id,recommended_route_id:id});
    await act(async()=>{pending[1].resolve(response('new',8));});
    await act(async()=>{pending[0].resolve(response('old',2));});
    expect(screen.getAllByText(/8.0 km/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/2.0 km/)).toBeNull();
  });

  it('signs in the driver and publishes GPS only for their assigned bus', async () => {
    render(<ThemeProvider><MemoryRouter><DriverPage /></MemoryRouter></ThemeProvider>);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'driver_test' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'safe-test-password' } });
    fireEvent.click(screen.getByText('Sign in'));
    await screen.findByText('Share device GPS');
    expect(credentials).toHaveBeenCalledWith('driver_test', 'safe-test-password');
    fireEvent.click(screen.getByText('Door open'));
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/buses/BUS005/door', { open: true }));
  });

  it('plans for a following bus from its shared GPS without requesting the viewer location',async()=>{
    const base=request.getMockImplementation();
    request.mockImplementation(async(path:string,init?:any)=>path==='/api/public/buses/BUS005'
      ?{id:'BUS005',location:{latitude:11.66,longitude:78.13,accuracy_m:5,fresh:true,timestamp:'2026-10-09T03:00:00Z',source:'gps_device'}}:base?.(path,init));
    const gps=vi.fn();Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition:gps}});
    render(<ThemeProvider><MemoryRouter initialEntries={['/passenger?bus_id=BUS005']}><PassengerPage/></MemoryRouter></ThemeProvider>);
    await screen.findByText(/Planning from BUS005/);
    fireEvent.change(screen.getByLabelText('Search destination'),{target:{value:'Five Roads'}});
    fireEvent.click(screen.getByText('Search'));fireEvent.click(await screen.findByText('Five Roads, Salem'));
    await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/public/navigation/routes',expect.anything()));
    const planned=request.mock.calls.find(([path])=>path==='/api/public/navigation/routes');
    expect(JSON.parse(planned![1].body).origin).toEqual({latitude:11.66,longitude:78.13});
    expect(gps).not.toHaveBeenCalled();
  });

  it('tracks a selected bus and shows the provider estimate for a chosen boarding stop', async () => {
    const base = request.getMockImplementation();
    const bus = {id:'BUS005',registration_number:'TN30-N-1234',route_id:'R02',stop_ids:['S01','S04'],
      location:{latitude:11.6757,longitude:78.1402,fresh:true,timestamp:'2026-10-08T12:00:00Z'},
      crowding:{fresh:true,level:'LOW',coverage:'partial',visible_people:3}};
    request.mockImplementation(async(path:string,init?:any)=>{
      if(path==='/api/public/stops')return {stops:[{id:'S01',name:'New Bus Stand'},{id:'S04',name:'Hasthampatti'}]};
      if(path.startsWith('/api/public/buses?q='))return {buses:[bus]};
      if(path==='/api/public/buses/BUS005')return bus;
      if(path.startsWith('/api/public/buses/BUS005/arrival'))return {available:true,estimated_minutes:5,demo:true,
        stop:{id:'S01',name:'New Bus Stand'},next_stop:{id:'S01',name:'New Bus Stand'},note:'Road profile estimate excludes waiting.'};
      return base?.(path,init);
    });
    render(<ThemeProvider><MemoryRouter><PassengerPage /></MemoryRouter></ThemeProvider>);
    fireEvent.change(screen.getByLabelText('Find bus or route'),{target:{value:'TN30'}});
    fireEvent.click(screen.getByText('Find'));
    fireEvent.click(await screen.findByRole('button',{name:/TN30-N-1234/}));
    expect(await screen.findByText('≈ 5 min to New Bus Stand')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Boarding stop'),{target:{value:'S04'}});
    await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/public/buses/BUS005/arrival?stop_id=S04'));
    expect(post).not.toHaveBeenCalled();
  });
});
