// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TransitProvider } from '../components/transit/Shared';
import AnalyticsPage from '../pages/transit/AnalyticsPage';
import SettingsPage from '../pages/transit/SettingsPage';
import ProjectPage from '../pages/transit/ProjectPage';
import { exportTransit, patchTransit } from '../services/transit';

const settings = { fleet_size: 28, reserve_fleet: 4, bus_capacity: 50, max_headway_minutes: 30,
  solver_time_limit_seconds: 5, vision_density_reference_vehicles: 20, default_confidence: 0.5,
  horizon_minutes: 60, traffic_thresholds: { moderate: 25, high: 50, severe: 75 },
  crowd_visible_thresholds: { moderate:6,high:15,critical:30 } };

vi.mock('../services/transit', async importOriginal => {
  const actual = await importOriginal<typeof import('../services/transit')>();
  return { ...actual, transitRequest: vi.fn(async (path: string) => {
    if (path === '/api/settings') return { settings, capabilities: { image: true, rtsp: false } };
    if (path === '/api/system/status') return { database: 'connected', forecast: { ready: true, horizons_minutes: [30, 60, 120] }, optimizer: { available: true, engine: 'Google OR-Tools CP-SAT' }, capabilities: { image: true, video: true, browser_camera: true, rtsp: false, physical_speed: false } };
    if (path === '/api/models/status') return { detection_models: [{ id: 1, name: 'Existing detector', filename: 'yolo26n.pt', type: 'general', weights_available: true, is_default: true, classes: ['person', 'bus'] }] };
    if (path === '/api/dashboard/analytics') return { runs: [{ id: 'run-real', timestamp: '2026-10-08T12:00:00Z', solver_status: 'OPTIMAL', baseline: { totals: { average_wait_minutes: 11 } }, totals: { allocated_buses: 24, average_wait_minutes: 8, demand_coverage_pct: 93, capacity_shortfall: 77, operating_cost_inr: 16800 } }], traffic: [{ id: 'obs', corridor_id: 'C02', congestion_score: 74, source: 'SYNTHETIC_DEMO_DATA', timestamp: '2026-10-08T12:00:00Z' }], operator_actions: [{ id: 'action', action: 'approve', operator: 'operator', route_id: 'R02', timestamp: '2026-10-08T12:00:00Z' }], stored_demand_rows: 95040 };
    if (path === '/api/demand/forecasts') return { forecasts: [{ id: 'f1' }] };
    if (path === '/api/simulator/scenarios') return { scenarios: [{ id: 's1' }, { id: 's2' }] };
    if (path === '/api/dashboard/summary') return { kpis: { available_buses: 28, reserve_buses: 4, allocated_buses: 24, forecast_passenger_demand: 1240, capacity_shortfall: 77 } };
    return {};
  }), patchTransit: vi.fn(), exportTransit: vi.fn() };
});

vi.mock('recharts', () => {
  const Container = ({ children }: any) => <div>{children}</div>;
  const Blank = () => null;
  return { ResponsiveContainer: Container, BarChart: Container, LineChart: Container,
    Bar: Blank, Line: Blank, CartesianGrid: Blank, Legend: Blank, Tooltip: Blank, XAxis: Blank, YAxis: Blank };
});

beforeEach(() => { vi.mocked(patchTransit).mockReset(); vi.mocked(exportTransit).mockReset(); });
afterEach(cleanup);
const wrap = (page: React.ReactNode) => <MemoryRouter><TransitProvider>{page}</TransitProvider></MemoryRouter>;

describe('Analytics and settings', () => {
  it('renders stored result metrics and exports the selected real record collection', async () => {
    vi.mocked(exportTransit).mockResolvedValue(undefined);
    render(wrap(<AnalyticsPage />));
    expect(await screen.findByText('OPTIMAL')).toBeTruthy();
    expect(screen.getByText('95,040')).toBeTruthy();
    expect(screen.getByText('77')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Record collection'), { target: { value: 'operator-actions' } });
    fireEvent.click(screen.getByRole('button', { name: 'Export JSON' }));
    await waitFor(() => expect(exportTransit).toHaveBeenCalledWith('operator-actions', 'json'));
  });

  it('sends validated selected settings to the persistence API and shows unavailable capabilities', async () => {
    vi.mocked(patchTransit).mockResolvedValue({ settings: { ...settings, fleet_size: 30, reserve_fleet: 5 } });
    render(wrap(<SettingsPage />));
    await screen.findByDisplayValue('28');
    fireEvent.change(screen.getByLabelText('Available fleet'), { target: { value: '30' } });
    fireEvent.change(screen.getByLabelText('Reserve buses'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(patchTransit).toHaveBeenCalledWith('/api/settings', { ...settings, fleet_size: 30, reserve_fleet: 5 }));
    expect(await screen.findByText('Settings saved to the database.')).toBeTruthy();
    expect(screen.getByText('Network / RTSP cameras')).toBeTruthy();
    expect(screen.getByText('Existing detector')).toBeTruthy();
  });

  it('blocks inconsistent thresholds and exposes backend fleet validation failures', async () => {
    vi.mocked(patchTransit).mockRejectedValue(new Error('Settings cannot reduce the active fleet below its allocation plus reserve.'));
    render(wrap(<SettingsPage />));
    await screen.findByDisplayValue('28');
    fireEvent.change(screen.getByLabelText('moderate congestion threshold'), { target: { value: '80' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(patchTransit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('moderate congestion threshold'), { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText('Available fleet'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(await screen.findByText('Settings cannot reduce the active fleet below its allocation plus reserve.')).toBeTruthy();
  });

  it('shows API-driven project KPIs and links to functional modules', async () => {
    render(wrap(<ProjectPage />));
    expect(await screen.findByText('1,240')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open operator dashboard' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('link', { name: 'Start CCTV analysis' }).getAttribute('href')).toBe('/cctv');
    expect(screen.getByText(/your existing VisionX computer vision model/)).toBeTruthy();
  });
});
