import { useMemo, useState } from 'react';
import { Activity, ArrowRight, BrainCircuit, Clock3, Layers3, Play, Users } from 'lucide-react';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ErrorNotice, Loading, Metric, PageHeading, Panel, SourceBadge, chartTooltip, useAction, useResource, useTransitRefresh } from '../../components/transit/Shared';
import { numberText, postTransit, rows, timeText, type Data, type Network } from '../../services/transit';

function halfHourLabel(value: string) {
  return new Date(value).toLocaleTimeString('en-IN', { timeZone: 'Asia/Calcutta', hour: '2-digit', minute: '2-digit', hour12: false });
}

export default function DemandPage() {
  const network = useResource<Network>('/api/network');
  const [routeId, setRouteId] = useState('R02');
  const [stopId, setStopId] = useState('');
  const [horizon, setHorizon] = useState(60);
  const [origin, setOrigin] = useState('');
  const [forecast, setForecast] = useState<Data | null>(null);
  const action = useAction();
  const invalidate = useTransitRefresh();
  const route = network.data?.routes.find(item => item.id === routeId);
  const stops = network.data?.stops.filter(item => route?.stop_ids.includes(item.id)) ?? [];
  const historyPath = `/api/demand/history?route_id=${encodeURIComponent(routeId)}${stopId ? `&stop_id=${encodeURIComponent(stopId)}` : ''}&limit=48`;
  const history = useResource<Data>(historyPath);
  const historyPoints = rows(forecast?.history ?? history.data?.history ?? history.data?.points);
  const chartPoints = useMemo(() => [
    ...historyPoints.map(point => ({ timestamp: point.timestamp, observed: point.boardings ?? point.passengers, forecast: null, baseline: null })),
    ...rows(forecast?.future_points).map(point => ({ timestamp: point.timestamp, observed: null, forecast: point.predicted_passengers, baseline: point.baseline_passengers })),
  ], [forecast, history.data]);
  const testMetrics = forecast?.evaluation_metrics?.test;
  const selectedMetrics = stopId ? testMetrics : testMetrics?.route_totals ?? testMetrics;
  const mlMetrics = selectedMetrics?.ml;
  const baselineMetrics = selectedMetrics?.seasonal_baseline;
  const split = forecast?.evaluation_metrics?.splits;

  function changeSelection(update: () => void) {
    update(); setForecast(null); action.setError('');
  }

  async function runForecast() {
    const forecastAt = origin ? `${origin.length === 16 ? `${origin}:00` : origin}+05:30` : null;
    const result = await action.run(() => postTransit<Data>('/api/demand/forecast', {
      route_id: routeId, stop_id: stopId || null, horizon_minutes: horizon, forecast_at: forecastAt,
    }));
    if (result) { setForecast(result.forecast ?? result); invalidate(); }
  }

  return <div className="to-page">
    <PageHeading eyebrow="PASSENGER DEMAND INTELLIGENCE" title="Predict the next movement" description="Forecast boarding demand with trained XGBoost models, compare the seasonal baseline, and check service capacity." actions={<><SourceBadge source="SYNTHETIC_DEMO_DATA" /><SourceBadge source="ML_FORECAST" /></>} />
    <ErrorNotice message={network.error} retry={network.refresh} />
    <Panel title="Forecast workspace" subtitle="Select an illustrative route and the planning window. Predictions are saved through the backend." actions={<BrainCircuit size={22} color="#00d9ff" />}>
      {network.loading ? <Loading label="Loading routes and stops…" /> : <div className="to-form-grid">
        <label className="to-label">Route<select aria-label="Route" className="to-field" value={routeId} onChange={event => changeSelection(() => { setRouteId(event.target.value); setStopId(''); })}>
          {(network.data?.routes ?? []).map(item => <option key={item.id} value={item.id}>{item.id} · {item.name}</option>)}
        </select></label>
        <label className="to-label">Stop<select aria-label="Stop" className="to-field" value={stopId} onChange={event => changeSelection(() => setStopId(event.target.value))}>
          <option value="">All route stops · aggregate demand</option>
          {stops.map(stop => <option key={stop.id} value={stop.id}>{stop.name}</option>)}
        </select></label>
        <label className="to-label">Forecast horizon<select aria-label="Forecast horizon" className="to-field" value={horizon} onChange={event => changeSelection(() => setHorizon(Number(event.target.value)))}>
          <option value={30}>Next 30 minutes</option><option value={60}>Next 60 minutes</option><option value={120}>Next 120 minutes</option>
        </select></label>
        <label className="to-label">Historical forecast origin · IST<input aria-label="Historical forecast origin" className="to-field" type="datetime-local" step={1800} value={origin} onChange={event => changeSelection(() => setOrigin(event.target.value))} /><span className="to-help">Leave empty to use the latest available observation.</span></label>
      </div>}
      <div className="to-inline-actions" style={{ marginTop: 20 }}>
        <button className="to-button" onClick={runForecast} disabled={action.busy || network.loading || !route}><Play size={16} />{action.busy ? 'Computing forecast…' : 'Run demand forecast'}</button>
        <span className="to-help"><Clock3 size={14} /> {forecast ? `Observation origin: ${timeText(forecast.forecast_at)} IST` : '90 days of reproducible half-hour history · seed 42'}</span>
      </div>
      <ErrorNotice message={action.error} />
    </Panel>

    {forecast ? <>
      <div className="to-grid to-grid-4">
        <Metric label="ML boarding forecast" value={numberText(forecast.predicted_passengers, 1)} unit="passengers" detail={`Cumulative next ${forecast.horizon_minutes} minutes`} icon={<Users size={18} />} />
        <Metric label="Seasonal baseline" value={numberText(forecast.baseline_passengers, 1)} unit="passengers" detail="Matching half-hours one week earlier" icon={<Layers3 size={18} />} accent="blue" />
        <Metric label="Available service capacity" value={numberText(forecast.available_capacity, 1)} unit="boardings" detail={`Same ${forecast.horizon_minutes}-minute planning window`} icon={<Activity size={18} />} accent="green" />
        <Metric label={Number(forecast.capacity_shortfall) > 0 ? 'Capacity shortfall' : 'Capacity surplus'} value={numberText(Number(forecast.capacity_shortfall) > 0 ? forecast.capacity_shortfall : forecast.capacity_surplus, 1)} unit="passengers" detail={Number(forecast.capacity_shortfall) > 0 ? 'Demand above estimated service capacity' : 'Estimated service capacity above demand'} accent={Number(forecast.capacity_shortfall) > 0 ? 'orange' : 'green'} />
      </div>
      <div className="to-callout"><ArrowRight size={18} /><div><strong>{forecast.route_id}{forecast.stop_id ? ` · ${stops.find(item => item.id === forecast.stop_id)?.name ?? forecast.stop_id}` : ' · route total'}</strong><p>{timeText(forecast.forecast_at)} → {timeText(forecast.forecast_end)} IST. Capacity uses {forecast.capacity_method}.</p></div></div>
    </> : <div className="to-callout"><BrainCircuit size={20} /><div><strong>Ready to forecast {routeId}</strong><p>Run the model to calculate demand, baseline comparison and capacity shortfall for your selected {horizon}-minute window.</p></div></div>}

    <ErrorNotice message={history.error} retry={history.refresh} />
    <Panel title="Historical boardings → future demand" subtitle="Every chart point is boardings per 30 minutes. Forecast cards show cumulative demand across the selected horizon." actions={<SourceBadge source={forecast ? 'ML_FORECAST' : 'SYNTHETIC_DEMO_DATA'} />}>
      {history.loading && !forecast ? <Loading label="Loading boarding history…" /> : chartPoints.length ? <div style={{ width: '100%', height: 340 }} role="img" aria-label="Observed half-hour demand and future ML and seasonal baseline forecasts">
        <ResponsiveContainer width="100%" height="100%"><ComposedChart data={chartPoints} margin={{ top: 20, right: 20, left: 0, bottom: 12 }}>
          <defs><linearGradient id="demandObservedGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2f80ed" stopOpacity={0.36} /><stop offset="100%" stopColor="#2f80ed" stopOpacity={0.01} /></linearGradient></defs>
          <CartesianGrid stroke="#193753" strokeDasharray="3 5" vertical={false} />
          <XAxis dataKey="timestamp" tickFormatter={halfHourLabel} minTickGap={40} stroke="#8ba6c4" tick={{ fontSize: 11 }} />
          <YAxis stroke="#8ba6c4" tick={{ fontSize: 11 }} label={{ value: 'Boardings / 30 min', angle: -90, position: 'insideLeft', fill: '#8ba6c4', fontSize: 11 }} />
          <Tooltip contentStyle={chartTooltip} labelFormatter={label => `${timeText(String(label))} IST`} formatter={(value, name) => [numberText(value, 1), name]} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 14 }} />
          <Area type="monotone" dataKey="observed" name="Observed synthetic boardings" stroke="#2f80ed" fill="url(#demandObservedGradient)" strokeWidth={2} connectNulls={false} />
          <Line type="monotone" dataKey="forecast" name="XGBoost forecast" stroke="#00d9ff" strokeWidth={3} dot={{ r: 4 }} connectNulls={false} />
          <Line type="monotone" dataKey="baseline" name="Seasonal baseline" stroke="#ffb020" strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3 }} connectNulls={false} />
        </ComposedChart></ResponsiveContainer>
      </div> : <p className="to-help">No historical observations are available for this selection.</p>}
      {forecast && <p className="to-help">Forecast points distribute the direct cumulative horizon estimates into half-hour intervals. The remaining 90/120-minute demand is split evenly; these are planning estimates.</p>}
    </Panel>

    <div className="to-grid to-grid-2">
      <Panel title="Measured model evaluation" subtitle={stopId ? 'Held-out route and stop series · synthetic data' : 'Held-out route-total series · synthetic data'}>
        {mlMetrics ? <>
          <div className="to-table-wrap"><table className="to-table"><thead><tr><th>Test metric</th><th>XGBoost</th><th>Seasonal baseline</th></tr></thead><tbody>
            <tr><td>MAE · passengers</td><td>{numberText(mlMetrics.mae, 2)}</td><td>{numberText(baselineMetrics?.mae, 2)}</td></tr>
            <tr><td>RMSE · passengers</td><td>{numberText(mlMetrics.rmse, 2)}</td><td>{numberText(baselineMetrics?.rmse, 2)}</td></tr>
            <tr><td>WAPE</td><td>{numberText(mlMetrics.wape_percent, 2)}%</td><td>{numberText(baselineMetrics?.wape_percent, 2)}%</td></tr>
          </tbody></table></div>
          <p className="to-help">{split?.strategy ?? 'Chronological train / validation / test split with target-window purging.'}</p>
          <p className="to-help">Train targets end {timeText(split?.train?.target_end)}. Test origins start {timeText(split?.test?.origin_start)} IST. Model: {forecast?.model_version}.</p>
        </> : <p className="to-help">Run a forecast to view the trained model's measured MAE, RMSE and WAPE alongside the historical baseline.</p>}
      </Panel>
      <Panel title="What the forecast knows" subtitle="Current observations and historical patterns support the next planning window.">
        <div className="to-help" style={{ display: 'grid', gap: 14 }}>
          <p><strong style={{ color: 'var(--text-heading)' }}>Time and history.</strong> Route and stop patterns, weekday, peak periods, previous demand, one-day and one-week lags, and trailing averages.</p>
          <p><strong style={{ color: 'var(--text-heading)' }}>Origin-time signals.</strong> Traffic, service frequency, weather and available crowd estimates. Future measured observations are excluded from model features.</p>
          <p><strong style={{ color: 'var(--text-heading)' }}>Capacity and provenance.</strong> Seat capacity is scaled to the selected horizon and route cycle. Synthetic boarding counts differ from detected people. Camera crowd signals are estimates.</p>
          <p><strong style={{ color: 'var(--text-heading)' }}>Uncertainty interval: unavailable.</strong> Forecasts are synthetic planning estimates. Historical origins require seven preceding days; origins after the recorded dataset are unsupported.</p>
        </div>
      </Panel>
    </div>
  </div>;
}
