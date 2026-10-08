// @vitest-environment jsdom
import { useEffect } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TransitProvider, useTransitRefresh } from '../components/transit/Shared';
import { DashboardPage, RecommendationsPage, SimulatorPage } from '../pages/transit/OperationsPages';
import { postTransit, type Network } from '../services/transit';

const initialRecommendations = [
  { id: 'rec-add', run_id: 'run-saved', route_id: 'R02', current_buses: 2, proposed_buses: 3,
    proposed_variant_id: 'alternative', status: 'pending_review', reason: 'Forecast capacity shortfall requires extra service.', timestamp: '2026-10-08T12:00:00Z' },
  { id: 'rec-release', run_id: 'run-saved', route_id: 'R06', current_buses: 2, proposed_buses: 1,
    proposed_variant_id: 'existing', status: 'pending_review', reason: 'Release a bus while retaining essential service.', timestamp: '2026-10-08T12:00:00Z' },
];
let recommendations = initialRecommendations.map(row => ({ ...row }));
let unchangedApproved = false;
let unchangedActivated = false;
const totals = { fleet_size: 28, reserve_fleet: 4, allocated_buses: 24, unused_operational_buses: 0,
  forecast_demand: 1200, demand_coverage_pct: 95, capacity_shortfall: 60,
  average_wait_minutes: 8.5, average_delay_minutes: 3.2, operating_cost_inr: 16800, fleet_utilization_pct: 100 };
const successfulPlan = { id: 'run-saved', run_id: 'run-saved', scenario_id: 'scenario-saved', feasible: true,
  solver_status: 'OPTIMAL', wall_time_seconds: 0.12, config: { fleet_size: 28, reserve_fleet: 4, horizon_minutes: 60 },
  totals, baseline: { totals: { ...totals, average_wait_minutes: 11, capacity_shortfall: 140 } },
  routes: [{ route_id: 'R02', previous_buses: 2, buses: 3, variant_id: 'alternative', headway_minutes: 14,
    capacity: 214, demand: 200, unserved_demand: 0, changed: true, reason: 'Add a bus and use the validated alternative.' }],
  constraints: [{ name: 'Operational fleet and reserve', satisfied: true, detail: '24 <= 24' }], assumptions: [] };

vi.mock('../services/transit', async importOriginal => {
  const actual = await importOriginal<typeof import('../services/transit')>();
  return { ...actual, transitRequest: vi.fn(async (path: string) => {
    if (path === '/api/settings') return { settings: { fleet_size: 28, reserve_fleet: 4, bus_capacity: 50, horizon_minutes: 60, max_headway_minutes: 30, solver_time_limit_seconds: 5 } };
    if (path === '/api/network') return { width: 800, height: 600, stops: [], segments: [], corridors: [], cameras: [], routes: [{ id: 'R02', name: 'Suramangalam route', current_buses: 2, color: '#00d9ff' }, { id: 'R06', name: 'Gugai route', current_buses: 2, color: '#ffb020' }] };
    if (path === '/api/dashboard/summary') return { kpis: { available_buses: 28, reserve_buses: 4, allocated_buses: 24, forecast_passenger_demand: 1200, capacity_shortfall: 140, average_waiting_time_minutes: 11, fleet_utilization_pct: 85.7, high_congestion_corridors: 0, active_ai_recommendations: recommendations.length }, settings: { horizon_minutes: 60 }, traffic: [], recommendations: [], plan: { routes: [] } };
    if (path.startsWith('/api/demand/history')) return { history: [{ timestamp: '2026-10-08T17:30:00+05:30', passengers: 80, boardings: 80 }] };
    if (path === '/api/recommendations') return { recommendations: recommendations.map(row => ({ ...row })) };
    if (path === '/api/optimization/results/run-unchanged') return { ...successfulPlan, id: 'run-unchanged', run_id: 'run-unchanged',
      baseline: { totals }, plan_approved: unchangedApproved, activated: unchangedActivated,
      routes: successfulPlan.routes.map(row => ({ ...row, previous_buses: 2, buses: 2, variant_id: 'existing', changed: false })) };
    if (path.startsWith('/api/optimization/results/')) return successfulPlan;
    if (path === '/api/simulator/scenarios') return { scenarios: [] };
    return {};
  }), postTransit: vi.fn(), exportTransit: vi.fn() };
});

vi.mock('../components/transit/TransitMap', () => ({ default: () => <div>Illustrative transit network</div> }));
vi.mock('recharts', () => {
  const Container = ({ children }: any) => <div>{children}</div>;
  const Blank = () => null;
  return { ResponsiveContainer: Container, BarChart: Container, AreaChart: Container,
    Bar: Blank, Area: Blank, CartesianGrid: Blank, Legend: Blank, Tooltip: Blank, XAxis: Blank, YAxis: Blank };
});

function FreshResources() { const invalidate = useTransitRefresh(); useEffect(() => { invalidate(); }, []); return null; }
function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output>; }
function wrap(page: React.ReactNode, path = '/') {
  return <MemoryRouter initialEntries={[path]}><TransitProvider><FreshResources />{page}<Location /></TransitProvider></MemoryRouter>;
}
beforeEach(() => { localStorage.clear(); recommendations = initialRecommendations.map(row => ({ ...row })); unchangedApproved = false; unchangedActivated = false; vi.mocked(postTransit).mockReset(); });
afterEach(cleanup);

describe('Connected operating workflows', () => {
  it('renders dashboard calculations and opens the actual stored optimization run', async () => {
    vi.mocked(postTransit).mockResolvedValue(successfulPlan);
    render(wrap(<DashboardPage />));
    expect(await screen.findByText('1,200')).toBeTruthy();
    expect(screen.getByText('140')).toBeTruthy();
    expect(screen.getByText('85.7')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Run optimization' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/optimization/run', { name: 'Operator dashboard scenario' }));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/optimization?run=run-saved'));
  });

  it('submits selected +20 percent demand and fleet conditions, then renders returned allocations', async () => {
    vi.mocked(postTransit).mockResolvedValue({ ...successfulPlan, totals: { ...totals, forecast_demand: 1440, capacity_shortfall: 180 } });
    render(wrap(<SimulatorPage />, '/simulator'));
    await screen.findByDisplayValue('28');
    fireEvent.click(screen.getByRole('button', { name: '+20%' }));
    fireEvent.click(screen.getByRole('button', { name: '30 buses' }));
    fireEvent.change(screen.getByLabelText('Traffic conditions'), { target: { value: 'high' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run optimization' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/simulator/run', expect.objectContaining({ demand_multiplier: 1.2, fleet_size: 30, traffic_level: 'high', reserve_fleet: 4 })));
    expect(await screen.findByText('Recommended route allocations')).toBeTruthy();
    expect(screen.getByText('3 buses')).toBeTruthy();
    expect(screen.getAllByText('180').length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'Review recommendations' }).getAttribute('href')).toBe('/recommendations?run=run-saved');
  });

  it('shows infeasibility with no invented route allocation after a low fleet run', async () => {
    vi.mocked(postTransit).mockResolvedValue({ id: 'infeasible', scenario_id: 'infeasible-scenario', feasible: false,
      solver_status: 'INFEASIBLE', routes: [], config: { fleet_size: 20, reserve_fleet: 4 }, minimum_required_buses: 18,
      warnings: ['Maximum headway requires 18 buses; only 16 operational buses remain.'] });
    render(wrap(<SimulatorPage />, '/simulator'));
    await screen.findByDisplayValue('28');
    fireEvent.click(screen.getByRole('button', { name: '20 buses' }));
    fireEvent.click(screen.getByRole('button', { name: 'Run optimization' }));
    expect(await screen.findByText('No feasible operating plan')).toBeTruthy();
    expect(screen.getByText('Maximum headway requires 18 buses; only 16 operational buses remain.')).toBeTruthy();
    expect(screen.queryByText('Recommended route allocations')).toBeNull();
    expect(screen.queryByText('3 buses')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Review recommendations' })).toBeNull();
  });

  it('retains saved scenario fleet choices after loading backend defaults', async () => {
    localStorage.setItem('transitopt-simulator', JSON.stringify({ fleet_size: 40, reserve_fleet: 5, demand_multiplier: 1.2 }));
    vi.mocked(postTransit).mockResolvedValue(successfulPlan);
    render(wrap(<SimulatorPage />, '/simulator'));
    await screen.findByText('Illustrative transit network');
    expect((screen.getByLabelText('Available fleet') as HTMLInputElement).value).toBe('40');
    expect((screen.getByLabelText('Reserve fleet') as HTMLInputElement).value).toBe('5');
    fireEvent.click(screen.getByRole('button', { name: 'Run optimization' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/simulator/run', expect.objectContaining({ fleet_size: 40, reserve_fleet: 5, demand_multiplier: 1.2 })));
  });

  it('requires complete approval before sending simulated activation', async () => {
    vi.mocked(postTransit).mockImplementation(async path => {
      if (path.endsWith('/approve')) recommendations = recommendations.map(row => ({ ...row, status: 'approved' }));
      if (path.endsWith('/activate-simulation')) recommendations = recommendations.map(row => ({ ...row, status: 'activated' }));
      return {};
    });
    render(wrap(<RecommendationsPage />, '/recommendations?run=run-saved'));
    const activate = await screen.findByRole('button', { name: 'Activate in simulation' });
    expect((activate as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Approve complete plan' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Activate in simulation' }) as HTMLButtonElement).disabled).toBe(false));
    expect(postTransit).toHaveBeenCalledWith('/api/optimization/results/run-saved/approve', { note: '' });
    fireEvent.click(screen.getByRole('button', { name: 'Activate in simulation' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/optimization/results/run-saved/activate-simulation'));
    expect(await screen.findByText('This plan is active in simulation.')).toBeTruthy();
  });

  it('records an individual rejection and blocks approval or activation of that plan', async () => {
    vi.mocked(postTransit).mockImplementation(async path => {
      recommendations = recommendations.map(row => path.includes(row.id) ? { ...row, status: 'rejected' } : row);
      return {};
    });
    render(wrap(<RecommendationsPage />, '/recommendations?run=run-saved'));
    const buttons = await screen.findAllByRole('button', { name: /^Reject$/ });
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/recommendations/rec-add/reject', { note: '' }));
    expect(await screen.findByText('A rejected route blocks this plan. Run a revised optimization.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Approve complete plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Activate in simulation' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByRole('button', { name: /^Reject$/ })).toHaveLength(1);
  });

  it('requires explicit plan approval before activating an unchanged scenario with no route recommendations', async () => {
    recommendations = [];
    vi.mocked(postTransit).mockImplementation(async path => {
      if (path === '/api/optimization/results/run-unchanged/approve') unchangedApproved = true;
      if (path === '/api/optimization/results/run-unchanged/activate-simulation') unchangedActivated = true;
      return { plan_approved: unchangedApproved, activated: unchangedActivated };
    });
    render(wrap(<RecommendationsPage />, '/recommendations?run=run-unchanged'));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Approve complete plan' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByText('No recommendations to review')).toBeNull();
    expect((screen.getByRole('button', { name: 'Activate in simulation' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Approve complete plan' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/optimization/results/run-unchanged/approve', { note: '' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Activate in simulation' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Activate in simulation' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/optimization/results/run-unchanged/activate-simulation'));
    expect(await screen.findByText('This plan is active in simulation.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Activate in simulation' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows an alternative corridor when a plan arrives after the map has loaded', async () => {
    const { default: TransitMap } = await vi.importActual<typeof import('../components/transit/TransitMap')>('../components/transit/TransitMap');
    const existing = [{ x: 10, y: 20 }, { x: 80, y: 20 }];
    const alternative = [{ x: 10, y: 20 }, { x: 45, y: 40 }, { x: 80, y: 20 }];
    const network: Network = { width: 100, height: 100, source: 'SYNTHETIC_DEMO_DATA', disclaimer: 'Illustrative network',
      stops: [], cameras: [], corridors: [], segments: [], routes: [{ id: 'R02', name: 'Demo route', color: '#00d9ff', current_buses: 2,
        current_variant_id: 'existing', bus_capacity: 50, capacity: 50, min_buses: 1, max_headway_minutes: 30,
        corridor_id: 'C02', stop_ids: [], geometry: existing, source: 'SYNTHETIC_DEMO_DATA',
        variants: [{ id: 'existing', name: 'Existing', geometry: existing, stop_ids: [], segment_ids: [], cycle_minutes: 40, distance_km: 10, validated: true },
                   { id: 'alternative', name: 'Alternative', geometry: alternative, stop_ids: [], segment_ids: [], cycle_minutes: 42, distance_km: 11, validated: true }] }] };
    const view = render(<TransitMap network={network} />);
    expect((screen.getByLabelText('Solver plan') as HTMLInputElement).disabled).toBe(true);
    view.rerender(<TransitMap network={network} plan={{ routes: [{ route_id: 'R02', buses: 3, variant_id: 'alternative' }] }} />);
    await waitFor(() => expect((screen.getByLabelText('Solver plan') as HTMLInputElement).checked).toBe(true));
    expect(screen.getByText('Solver plan R02: 3 buses, Alternative')).toBeTruthy();
    expect(view.container.querySelector('polyline[stroke-dasharray="8 6"]')?.getAttribute('points')).toBe('10,20 45,40 80,20');
    view.rerender(<TransitMap network={network} />);
    await waitFor(() => expect(view.container.querySelector('polyline[stroke-dasharray="8 6"]')).toBeNull());
  });
});
