// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TransitProvider } from '../components/transit/Shared';
import DemandPage from '../pages/transit/DemandPage';
import { postTransit } from '../services/transit';

vi.mock('../services/transit', async importOriginal => {
  const actual = await importOriginal<typeof import('../services/transit')>();
  return { ...actual, transitRequest: vi.fn(async (path: string) => {
    if (path === '/api/network') return {
      routes: [{ id: 'R02', name: 'Suramangalam to Hasthampatti', stop_ids: ['S01', 'S03'] }],
      stops: [{ id: 'S01', name: 'New Bus Stand' }, { id: 'S03', name: 'Suramangalam' }, { id: 'S05', name: 'Ammapet' }],
    };
    return { history: [{ timestamp: '2026-10-08T17:30:00+05:30', boardings: 145 }] };
  }), postTransit: vi.fn() };
});

vi.mock('recharts', () => {
  const Container = ({ children }: any) => <div>{children}</div>;
  const Blank = () => null;
  return { ResponsiveContainer: Container, ComposedChart: Container, Area: Blank, Line: Blank,
    CartesianGrid: Blank, Legend: Blank, Tooltip: Blank, XAxis: Blank, YAxis: Blank };
});

afterEach(() => { cleanup(); vi.mocked(postTransit).mockReset(); });

describe('Passenger demand page', () => {
  it('submits the chosen stop and horizon, then displays backend calculations', async () => {
    vi.mocked(postTransit).mockResolvedValue({
      id: 'forecast-actual', route_id: 'R02', stop_id: 'S01', horizon_minutes: 120,
      forecast_at: '2026-10-08T17:30:00+05:30', forecast_end: '2026-10-08T19:30:00+05:30',
      predicted_passengers: 320, baseline_passengers: 300, available_capacity: 200,
      capacity_shortfall: 120, capacity_surplus: 0, capacity_method: 'planning service capacity',
      history: [{ timestamp: '2026-10-08T17:30:00+05:30', boardings: 145 }],
      future_points: [{ timestamp: '2026-10-08T18:00:00+05:30', predicted_passengers: 80, baseline_passengers: 75 }],
      evaluation_metrics: { test: { ml: { mae: 6.97, rmse: 10.09, wape_percent: 9.26 }, seasonal_baseline: { mae: 9.97, rmse: 15.69, wape_percent: 13.24 } } },
      model_version: 'transitopt-xgb-v1',
    });
    render(<TransitProvider><DemandPage /></TransitProvider>);
    await screen.findByRole('option', { name: 'New Bus Stand' });
    expect(screen.queryByRole('option', { name: 'Ammapet' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Stop'), { target: { value: 'S01' } });
    fireEvent.change(screen.getByLabelText('Forecast horizon'), { target: { value: '120' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run demand forecast' }));
    await waitFor(() => expect(postTransit).toHaveBeenCalledWith('/api/demand/forecast', {
      route_id: 'R02', stop_id: 'S01', horizon_minutes: 120, forecast_at: null,
    }));
    expect(await screen.findByText('320')).toBeTruthy();
    expect(screen.getByText('120')).toBeTruthy();
    expect(screen.getByText('Capacity shortfall')).toBeTruthy();
    expect(screen.getByText('6.97')).toBeTruthy();
    expect(screen.getByText(/Uncertainty interval: unavailable/)).toBeTruthy();
  });

  it('shows server validation errors without presenting a forecast result', async () => {
    vi.mocked(postTransit).mockRejectedValue(new Error('Forecast origins beyond recorded history are unsupported'));
    render(<TransitProvider><DemandPage /></TransitProvider>);
    await screen.findByRole('button', { name: 'Run demand forecast' });
    fireEvent.click(screen.getByRole('button', { name: 'Run demand forecast' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Forecast origins beyond recorded history are unsupported')).toBeTruthy();
    expect(screen.queryByText('ML boarding forecast')).toBeNull();
  });
});
