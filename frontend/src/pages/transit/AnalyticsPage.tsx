import { useState } from 'react';
import { BarChart, Bar, CartesianGrid, LineChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts';
import { Download, Database, Activity, ShieldCheck, GitBranch } from 'lucide-react';
import { exportTransit, numberText, rows, timeText } from '../../services/transit';
import { ActionNotice, chartTooltip, Empty, ErrorNotice, Loading, Metric, PageHeading, Panel, RefreshButton, SourceBadge, useAction, useResource } from '../../components/transit/Shared';

export default function AnalyticsPage() {
  const analytics = useResource('/api/dashboard/analytics');
  const forecasts = useResource('/api/demand/forecasts');
  const scenarios = useResource('/api/simulator/scenarios');
  const action = useAction();
  const [exportKind, setExportKind] = useState('scenarios');
  const [corridor, setCorridor] = useState('');
  const runs = rows(analytics.data?.runs);
  const traffic = rows(analytics.data?.traffic);
  const actions = rows(analytics.data?.operator_actions);
  const corridors = [...new Set(traffic.map(item => String(item.corridor_id)))].sort();
  const selectedCorridor = corridor || corridors[0];
  const trafficChart = traffic.filter(item => item.corridor_id === selectedCorridor).reverse().map(item => ({
    timestamp: timeText(item.timestamp), score: item.congestion_score, source: item.source,
  }));
  const waitChart = [...runs].reverse().filter(item => item.totals?.average_wait_minutes != null).map((item, index) => ({
    run: `Run ${index + 1}`, baseline: item.baseline?.totals?.average_wait_minutes,
    optimized: item.totals.average_wait_minutes,
  }));
  const refresh = () => { analytics.refresh(); forecasts.refresh(); scenarios.refresh(); };
  return <div className="to-page">
    <PageHeading title="Analytics & reports" description="Stored observations, solver comparisons and operator decisions from connected application state." actions={<RefreshButton onClick={refresh} />} />
    <ErrorNotice message={analytics.error || forecasts.error || scenarios.error} retry={refresh} />
    <ActionNotice action={action} />
    {analytics.loading ? <Loading label="Loading persistent analytics…" /> : <>
      <div className="to-kpis">
        <Metric label="Recent solver runs" value={numberText(runs.length)} detail="Latest 30 persisted runs" icon={<GitBranch size={17} />} />
        <Metric label="Stored boarding observations" value={numberText(analytics.data?.stored_demand_rows)} detail="Synthetic stop-level history" icon={<Database size={17} />} />
        <Metric label="Recent traffic observations" value={numberText(traffic.length)} detail="Latest 200 stored observations" icon={<Activity size={17} />} accent="orange" />
        <Metric label="Recent operator actions" value={numberText(actions.length)} detail="Latest 100 audit records" icon={<ShieldCheck size={17} />} accent="green" />
      </div>
      <div className="to-grid">
        <Panel title="Waiting time by optimization run" subtitle="Identical scenario assumptions · minutes per served passenger">
          {waitChart.length ? <div className="to-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={waitChart}>
            <CartesianGrid stroke="#1b3850" vertical={false} /><XAxis dataKey="run" stroke="#6d8aa5" fontSize={9} /><YAxis stroke="#6d8aa5" fontSize={9} />
            <Tooltip contentStyle={chartTooltip} /><Legend wrapperStyle={{ fontSize: 10 }} />
            <Bar dataKey="baseline" name="Baseline wait" fill="#426886" radius={[3, 3, 0, 0]} /><Bar dataKey="optimized" name="Optimized wait" fill="#00d9ff" radius={[3, 3, 0, 0]} />
          </BarChart></ResponsiveContainer></div> : <Empty title="No solver comparisons yet" description="Run route optimization or a what-if scenario to create actual comparison data." />}
        </Panel>
        <Panel title="Congestion observation history" subtitle="Stored scores on one corridor · score 0–100" actions={<label className="to-field"><span className="sr-only">Traffic corridor</span><select aria-label="Traffic corridor" value={selectedCorridor ?? ''} onChange={event => setCorridor(event.target.value)}>{corridors.map(id => <option key={id}>{id}</option>)}</select></label>}>
          {trafficChart.length ? <div className="to-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={trafficChart}>
            <CartesianGrid stroke="#1b3850" vertical={false} /><XAxis dataKey="timestamp" stroke="#6d8aa5" fontSize={8} tick={false} /><YAxis domain={[0, 100]} stroke="#6d8aa5" fontSize={9} />
            <Tooltip content={({ active, payload, label }: any) => active && payload?.length ? <div style={{ ...chartTooltip, padding: 12, border: '1px solid #24445f' }}><div>{label}</div><div>Score {numberText(payload[0].payload.score, 1)}</div><SourceBadge source={payload[0].payload.source} /></div> : null} /><Line type="linear" dataKey="score" name="Congestion score" stroke="#ffb020" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart></ResponsiveContainer></div> : <Empty title="No traffic observations" description="Analyze an authorized sample or recording to store an observation." />}
          <p className="to-note">Scores may include synthetic seed values and vision-derived estimates. This history is not a calibrated speed measurement.</p>
        </Panel>
      </div>
      <Panel title="Export application records" subtitle="Downloads contain actual persisted records and scenario calculations">
        <div className="to-form-row">
          <label className="to-field">Record collection<select value={exportKind} onChange={event => setExportKind(event.target.value)}>
            <option value="forecasts">Demand forecasts</option><option value="traffic">Traffic observations</option><option value="recommendations">Route recommendations</option><option value="scenarios">Scenario results</option><option value="operator-actions">Operator audit records</option>
          </select></label>
          <div className="to-action-row"><button className="to-button primary" disabled={action.busy} onClick={() => action.run(() => exportTransit(exportKind, 'csv'))}><Download size={14} />Export CSV</button><button className="to-button" disabled={action.busy} onClick={() => action.run(() => exportTransit(exportKind, 'json'))}><Download size={14} />Export JSON</button></div>
        </div>
        <p className="to-small">{numberText(rows(forecasts.data?.forecasts).length)} recent saved forecasts · {numberText(rows(scenarios.data?.scenarios).length)} saved scenarios</p>
      </Panel>
      <Panel title="Stored optimization results" subtitle="Computed metrics, including remaining unmet demand">
        {runs.length ? <div className="to-data-table-wrap"><table className="to-data-table"><thead><tr><th>Recorded</th><th>Solver status</th><th>Buses</th><th>Demand coverage</th><th>Unserved boardings</th><th>Estimated cost</th></tr></thead><tbody>{runs.map(item => <tr key={item.id}><td>{timeText(item.timestamp)}</td><td><span className="to-status">{item.solver_status}</span></td><td>{numberText(item.totals?.allocated_buses)}</td><td>{numberText(item.totals?.demand_coverage_pct, 1)}%</td><td>{numberText(item.totals?.capacity_shortfall)}</td><td>₹{numberText(item.totals?.operating_cost_inr)}</td></tr>)}</tbody></table></div> : <Empty title="No stored optimization runs" description="Create a plan on the Route Optimization page." />}
      </Panel>
      <Panel title="Operator audit trail" subtitle="Approval, rejection and complete-plan simulation activation">
        {actions.length ? <div className="to-data-table-wrap"><table className="to-data-table"><thead><tr><th>Recorded</th><th>Operator</th><th>Action</th><th>Route</th><th>Note</th></tr></thead><tbody>{actions.map(item => <tr key={item.id}><td>{timeText(item.timestamp)}</td><td>{item.operator}</td><td>{String(item.action).replace(/_/g, ' ')}</td><td>{item.route_id ?? 'Complete plan'}</td><td>{item.note || '—'}</td></tr>)}</tbody></table></div> : <Empty title="No operator decisions yet" description="Review and approve or reject a generated recommendation." />}
      </Panel>
      <p className="to-note"><SourceBadge source="SYNTHETIC_DEMO_DATA" /> Forecast model: {analytics.data?.forecast_model?.algorithm ?? 'Unavailable'} · {analytics.data?.forecast_model?.model_version ?? 'Unavailable'}. Observed history and forecast evaluation use generated boardings; operational comparisons are estimated scenario outcomes.</p>
    </>}
  </div>;
}
