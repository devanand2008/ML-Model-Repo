// @vitest-environment jsdom
import { Suspense, useEffect, type ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { postTransit, transitRequest } from '../services/transit';

const fixture = vi.hoisted(() => {
  const stops = [{ id: 'S01', name: 'New Bus Stand', x: 200, y: 200, essential: true, terminal: true },
    { id: 'S02', name: 'Five Roads', x: 450, y: 300, essential: true }];
  const geometry = stops.map(({ x, y }) => ({ x, y }));
  const buses = [4, 2, 3, 4, 3, 2, 3, 3];
  const routes = buses.map((current_buses, index) => ({ id: `R0${index + 1}`, name: `Illustrative route ${index + 1}`,
    color: '#00d9ff', current_buses, current_variant_id: 'existing', bus_capacity: 50, capacity: 50,
    min_buses: 1, max_headway_minutes: 30, cycle_minutes: 40, corridor_id: `C0${index + 1}`,
    stop_ids: ['S01', 'S02'], geometry, source: 'SYNTHETIC_DEMO_DATA',
    variants: [{ id: 'existing', name: 'Existing', geometry, stop_ids: ['S01', 'S02'], segment_ids: [], cycle_minutes: 40, distance_km: 10, validated: true },
      { id: 'alternative', name: 'Alternative', geometry: [geometry[0], { x: 300, y: 350 }, geometry[1]], stop_ids: ['S01', 'S02'], segment_ids: [], cycle_minutes: 42, distance_km: 11, validated: true }] }));
  const cameras = [{ id: 'CAM01', name: 'New Bus Stand demo camera', stop_id: 'S01', corridor_id: 'C01', roi: null, status: 'awaiting_authorized_input' }];
  const settings = { fleet_size: 28, reserve_fleet: 4, bus_capacity: 50, horizon_minutes: 60,
    max_headway_minutes: 30, solver_time_limit_seconds: 5, vision_density_reference_vehicles: 20,
    default_confidence: 0.5, traffic_thresholds: { moderate: 25, high: 50, severe: 75 } };
  const capabilities = { image: true, video: true, browser_camera: true, tracking: true, regions_of_interest: true, rtsp: false };
  return { network: { width: 800, height: 600, source: 'SYNTHETIC_DEMO_DATA', disclaimer: 'Illustrative network',
    routes, stops, segments: [], corridors: [], cameras, stop_metrics: [] }, cameras, settings, capabilities };
});

vi.mock('../components/AuthGate', () => ({ default: ({ children }: { children: ReactNode }) => <>{children}</> }));
// Native media and camera permissions are outside this routing test; the preserved route must still mount.
vi.mock('../pages/LiveCameraPage', () => ({ default: () => <h1>Preserved live camera tools</h1> }));
vi.mock('../services/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../services/api')>();
  return { ...actual, session: vi.fn(async () => ({ ok: true, status: 200 })) };
});
vi.mock('../services/transit', async importOriginal => {
  const actual = await importOriginal<typeof import('../services/transit')>();
  return { ...actual, transitRequest: vi.fn(async (path: string) => {
    if (path === '/api/public/traffic/feed') return {cameras:[],alerts:[]};
    if (path === '/api/public/rag/status') return {weights_available:true,generator:'FLAN-T5'};
    if (path === '/api/network') return fixture.network;
    if (path === '/api/settings') return { settings: fixture.settings, capabilities: fixture.capabilities };
    if (path === '/api/dashboard/summary') return { kpis: { available_buses: 28, reserve_buses: 4, allocated_buses: 24,
      forecast_passenger_demand: 1680, capacity_shortfall: 255, average_waiting_time_minutes: 11,
      fleet_utilization_pct: 85.7, high_congestion_corridors: 0, active_ai_recommendations: 0 },
      settings: fixture.settings, traffic: [], recommendations: [], plan: { routes: [] } };
    if (path.startsWith('/api/demand/history')) return { history: [{ timestamp: '2026-10-08T17:30:00+05:30', boardings: 140, passengers: 140 }] };
    if (path === '/api/cameras') return { cameras: fixture.cameras, capabilities: fixture.capabilities };
    if (path === '/api/vision/samples') return { samples: [{ id: 'bus-image', name: 'Bundled bus sample', type: 'image' }] };
    if (path === '/api/models/status') return { detection_models: [{ id: 1, name: 'Existing model', filename: 'yolo26n.pt',
      type: 'general', classes: ['person', 'car', 'bus'], weights_available: true, is_default: true }] };
    if (path === '/api/system/status') return { database: 'connected', capabilities: fixture.capabilities,
      forecast: { ready: true, horizons_minutes: [30, 60, 120] }, optimizer: { available: true, engine: 'Google OR-Tools CP-SAT' } };
    if (path === '/api/dashboard/analytics') return { runs: [], traffic: [], operator_actions: [], stored_demand_rows: 103680 };
    if (path === '/api/recommendations') return { recommendations: [] };
    if (path === '/api/simulator/scenarios') return { scenarios: [] };
    if (path === '/api/demand/forecasts') return { forecasts: [] };
    if (path === '/api/traffic/summary') return { events: [], corridors: [] };
    if (path === '/api/traffic/corridors') return { corridors: [] };
    throw new Error(`Unmocked API route in navigation test: ${path}`);
  }), postTransit: vi.fn(), exportTransit: vi.fn() };
});
vi.mock('../components/transit/Shared', async importOriginal => {
  const actual = await importOriginal<typeof import('../components/transit/Shared')>();
  function FreshResources() { const refresh = actual.useTransitRefresh(); useEffect(() => { refresh(); }, [refresh]); return null; }
  return { ...actual, TransitProvider: ({ children }: { children: ReactNode }) => <actual.TransitProvider><FreshResources />{children}</actual.TransitProvider> };
});
vi.mock('recharts', () => {
  const Container = ({ children }: { children: ReactNode }) => <div>{children}</div>;
  const Blank = () => null;
  return { ResponsiveContainer: Container, ComposedChart: Container, LineChart: Container,
    BarChart: Container, AreaChart: Container, Area: Blank, Bar: Blank, Line: Blank,
    CartesianGrid: Blank, Legend: Blank, Tooltip: Blank, XAxis: Blank, YAxis: Blank };
});

function Location() { const location = useLocation(); return <output data-testid="current-route">{location.pathname}</output>; }
function mount(path = '/admin') {
  return render(<MemoryRouter initialEntries={[path]}><Suspense fallback={<p>Loading page module…</p>}><App /></Suspense><Location /></MemoryRouter>);
}
beforeEach(() => { localStorage.clear(); vi.mocked(postTransit).mockClear(); vi.mocked(transitRequest).mockClear(); });
afterEach(cleanup);

describe('Actual application navigation', () => {
  it('opens all ten TransitOpt screens through the layout and preserves the live camera route', async () => {
    mount();
    await screen.findByRole('heading', { level: 1, name: 'Plan better journeys.' });
    expect(await screen.findByText('1,680')).toBeTruthy();
    const destinations = [
      ['CCTV intelligence', '/cctv', 'CCTV intelligence'],
      ['Passenger demand', '/demand', 'Predict the next movement'],
      ['Route optimization', '/optimization', 'Route & fleet optimization'],
      ['Transit network', '/network', 'Salem transit network'],
      ['What-if simulator', '/simulator', 'What if the city changes?'],
      ['Recommendations', '/recommendations', 'Recommendations & approval'],
      ['Analytics & reports', '/analytics', 'Analytics & reports'],
      ['Data & settings', '/settings', 'Data & settings'],
      ['Check app readiness', '/status', 'Check the app'],
    ];
    for (const [label, path, title] of destinations) {
      fireEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: label }));
      await screen.findByRole('heading', { level: 1, name: title });
      await waitFor(() => expect(screen.getByTestId('current-route').textContent).toBe(path));
    }
    fireEvent.click(screen.getByRole('link', { name: 'Explore the project' }));
    await screen.findByRole('heading', { level: 1, name: 'The TransitOpt AI project' });
    expect(screen.getByTestId('current-route').textContent).toBe('/project');
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: 'Overview' }));
    await screen.findByRole('heading', { level: 1, name: 'Plan better journeys.' });
    fireEvent.click(screen.getByRole('button', { name: 'VisionX tools' }));
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Existing vision tools' })).getByRole('link', { name: 'Live camera & skeleton' }));
    await screen.findByRole('heading', { level: 1, name: 'Preserved live camera tools' });
    expect(screen.getByTestId('current-route').textContent).toBe('/webcam');
    expect(transitRequest).toHaveBeenCalledWith('/api/vision/samples');
    expect(transitRequest).toHaveBeenCalledWith('/api/dashboard/analytics');
    expect(postTransit).not.toHaveBeenCalled();
  }, 30000); // This integration test renders ten complete screens on CPU.

  it('redirects an unknown deep link to the shared app home', async () => {
    mount('/unavailable-screen');
    await screen.findByRole('heading', { level: 1, name: /See the traffic/ }, { timeout: 5000 });
    await waitFor(() => expect(screen.getByTestId('current-route').textContent).toBe('/'));
    expect(screen.getByRole('link', {name:/Plan my journey/})).toBeTruthy();
  });
  it('finds a legacy module through search and clears the search after navigation',async()=>{
    mount();await screen.findByRole('heading',{level:1,name:'Plan better journeys.'});
    fireEvent.change(screen.getByLabelText('Find a module'),{target:{value:'Live camera'}});
    fireEvent.click(screen.getByRole('link',{name:'Live camera & skeleton'}));
    await screen.findByRole('heading',{level:1,name:'Preserved live camera tools'});
    expect((screen.getByLabelText('Find a module') as HTMLInputElement).value).toBe('');
    expect(screen.getByRole('link',{name:'Route RAG assistant'})).toBeTruthy();
  });
});
