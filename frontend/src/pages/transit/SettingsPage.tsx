import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Database, Save, ShieldCheck, Cpu, ExternalLink } from 'lucide-react';
import { numberText, patchTransit, rows, type Data } from '../../services/transit';
import { ActionNotice, ErrorNotice, Loading, PageHeading, Panel, SourceBadge, useAction, useResource, useTransitRefresh } from '../../components/transit/Shared';

const fields = [
  ['fleet_size', 'Available fleet', 1, 200, 1], ['reserve_fleet', 'Reserve buses', 0, 100, 1],
  ['bus_capacity', 'Seats per bus', 1, 150, 1], ['max_headway_minutes', 'Maximum headway (minutes)', 5, 120, 1],
  ['solver_time_limit_seconds', 'Solver time limit (seconds)', 0.1, 30, 0.1],
  ['vision_density_reference_vehicles', 'Vehicle density reference', 1, 500, 1],
  ['default_confidence', 'Detection confidence', 0.1, 0.95, 0.05],
] as const;

export default function SettingsPage() {
  const settings = useResource('/api/settings');
  const system = useResource('/api/system/status');
  const models = useResource('/api/models/status');
  const invalidate = useTransitRefresh();
  const action = useAction();
  const [form, setForm] = useState<Data>({});
  useEffect(() => { if (settings.data?.settings) setForm({ ...settings.data.settings,
    crowd_visible_thresholds: { moderate:6,high:15,critical:30,...settings.data.settings.crowd_visible_thresholds },
    traffic_thresholds: { ...settings.data.settings.traffic_thresholds } }); }, [settings.data]);
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    const payload: Data = {};
    for (const [key, label, low, high] of fields) {
      const value = Number(form[key]);
      if (form[key] === '' || !Number.isFinite(value) || value < low || value > high) { action.setError(`${label} must be between ${low} and ${high}.`); return; }
      if (['fleet_size', 'reserve_fleet', 'bus_capacity', 'vision_density_reference_vehicles'].includes(key) && !Number.isInteger(value)) { action.setError(`${label} must be a whole number.`); return; }
      payload[key] = value;
    }
    if (payload.reserve_fleet > payload.fleet_size) { action.setError('Reserve buses cannot exceed available fleet.'); return; }
    const thresholds = Object.fromEntries(['moderate', 'high', 'severe'].map(key => [key, Number(form.traffic_thresholds?.[key])]));
    if (!(thresholds.moderate > 0 && thresholds.moderate < thresholds.high && thresholds.high < thresholds.severe && thresholds.severe <= 100)) { action.setError('Traffic thresholds must satisfy 0 < moderate < high < severe ≤ 100.'); return; }
    payload.traffic_thresholds = thresholds;
    const crowds = Object.fromEntries(['moderate','high','critical'].map(key => [key,Number(form.crowd_visible_thresholds?.[key])]));
    if (!(Object.values(crowds).every(Number.isInteger) && crowds.moderate > 0 && crowds.moderate < crowds.high && crowds.high < crowds.critical && crowds.critical <= 300)) { action.setError('Visible crowd thresholds must be increasing whole counts between 1 and 300.'); return; }
    payload.crowd_visible_thresholds = crowds;
    payload.horizon_minutes = Number(form.horizon_minutes);
    action.run(async () => { const saved = await patchTransit('/api/settings', payload); setForm(saved.settings); invalidate(); return saved; }, 'Settings saved to the database.');
  };
  const caps = system.data?.capabilities ?? settings.data?.capabilities ?? {};
  return <div className="to-page">
    <PageHeading title="Data & settings" description="Persist planning assumptions, inspect model readiness and review supported camera capabilities." />
    <ErrorNotice message={settings.error || system.error || models.error} retry={() => { settings.refresh(); system.refresh(); models.refresh(); }} />
    <ActionNotice action={action} />
    {settings.loading ? <Loading label="Loading saved settings…" /> : <div className="to-grid">
      <Panel title="Planning & inference settings" subtitle="Changes are validated and persisted by the existing backend">
        <form onSubmit={save} className="to-fields">
          <div className="to-form-row">{fields.map(([key, label, low, high, step]) => <label className="to-field" key={key}>{label}<input aria-label={label} type="number" min={low} max={high} step={step} required value={form[key] ?? ''} onChange={event => setForm(old => ({ ...old, [key]: event.target.value }))} /></label>)}</div>
          <label className="to-field">Planning horizon<select aria-label="Planning horizon" value={form.horizon_minutes ?? 60} onChange={event => setForm(old => ({ ...old, horizon_minutes: Number(event.target.value) }))}><option value={30}>30 minutes</option><option value={60}>60 minutes</option><option value={120}>120 minutes</option></select></label>
          <div className="to-form-row">{['moderate', 'high', 'severe'].map(level => <label key={level} className="to-field">{level[0].toUpperCase() + level.slice(1)} congestion threshold<input aria-label={`${level} congestion threshold`} type="number" min={1} max={100} step={1} required value={form.traffic_thresholds?.[level] ?? ''} onChange={event => setForm(old => ({ ...old, traffic_thresholds: { ...old.traffic_thresholds, [level]: event.target.value } }))} /></label>)}</div>
          <div className="to-form-row">{['moderate','high','critical'].map(level => <label key={level} className="to-field">{level} visible people threshold<input aria-label={`${level} visible people threshold`} type="number" min={1} max={300} step={1} required value={form.crowd_visible_thresholds?.[level] ?? ''} onChange={event => setForm(old => ({ ...old,crowd_visible_thresholds:{...old.crowd_visible_thresholds,[level]:event.target.value} }))} /></label>)}</div>
          <p className="to-note">Visible people thresholds estimate crowding for partial camera coverage. A bus load factor is available only when an administrator has verified full camera coverage.</p>
          <button type="submit" className="to-button primary" disabled={action.busy || !settings.data}><Save size={14} />{action.busy ? 'Saving…' : 'Save settings'}</button>
          <p className="to-note">Fleet changes must retain enough buses for the active plan and reserve. Use the simulator to propose and approve a smaller operating plan first. Route-specific essential-service limits still apply.</p>
        </form>
      </Panel>
      <div className="to-stack">
        <Panel title="System readiness" subtitle="Reported by the connected application">
          <div className="to-bullet"><Database size={15} /><span>Database: <strong>{system.data?.database ?? 'Unavailable'}</strong></span></div>
          <div className="to-bullet"><Cpu size={15} /><span>Demand forecasting: <strong>{system.data?.forecast?.ready ? 'Ready · XGBoost' : 'Unavailable'}</strong></span></div>
          <div className="to-bullet"><ShieldCheck size={15} /><span>Optimization: <strong>{system.data?.optimizer?.available ? system.data.optimizer.engine : 'Unavailable'}</strong></span></div>
          <p className="to-small">Forecast horizons: {rows(system.data?.forecast?.horizons_minutes).length ? system.data?.forecast?.horizons_minutes.join(', ') : '30, 60, 120'} minutes · Version {system.data?.forecast?.model_version ?? 'Unavailable'}</p>
        </Panel>
        <Panel title="Camera capabilities" subtitle="Authorized uploaded footage and browser-camera input">
          <div className="to-data-table-wrap"><table className="to-data-table"><tbody>{[['Image analysis', caps.image], ['Recorded video jobs', caps.video], ['Browser camera', caps.browser_camera], ['Object tracking', caps.tracking], ['Regions of interest', caps.regions_of_interest], ['Network / RTSP cameras', caps.rtsp], ['Physical vehicle speed', caps.physical_speed], ['Calibrated queue length', caps.queue_length]].map(([label, available]) => <tr key={String(label)}><td>{label}</td><td>{available ? 'Supported' : 'Unavailable'}</td></tr>)}</tbody></table></div>
          <p className="to-note">{caps.rtsp_reason ?? 'Authorized stream ingestion is not configured.'} Detected people are crowd observations, not measured ticketed boardings.</p>
        </Panel>
      </div>
    </div>}
    <Panel title="Existing detection models" subtitle="Current VisionX registry · detector weights are reused" actions={<Link to="/models" className="to-button"><ExternalLink size={14} />Model Center</Link>}>
      {models.loading ? <Loading label="Inspecting the model registry…" /> : <div className="to-data-table-wrap"><table className="to-data-table"><thead><tr><th>Model</th><th>Type</th><th>File</th><th>Weights</th><th>Supported classes</th><th>Default</th></tr></thead><tbody>{rows(models.data?.detection_models).map(model => <tr key={model.id}><td>{model.name}</td><td>{model.type}</td><td>{model.filename}</td><td>{model.weights_available ? 'Available' : 'Unavailable'}</td><td>{numberText(rows(model.classes).length)}</td><td>{model.is_default ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div>}
      <p className="to-note"><SourceBadge source="SYNTHETIC_DEMO_DATA" /> Forecast training uses generated history. Detection model training is separate; this platform reuses the configured detector. Only trusted model files should be registered.</p>
    </Panel>
  </div>;
}
