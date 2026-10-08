import { Link } from 'react-router-dom';
import { ArrowUpRight, BrainCircuit, BusFront, Camera, GitBranch, ShieldCheck, FlaskConical, Database } from 'lucide-react';
import { numberText } from '../../services/transit';
import { ErrorNotice, Loading, Metric, PageHeading, Panel, SourceBadge, useResource } from '../../components/transit/Shared';

const modules = [
  { to: '/cctv', icon: Camera, title: 'Analyze traffic', text: 'Use your existing detector on authorized images, videos or a browser camera.' },
  { to: '/demand', icon: BrainCircuit, title: 'Predict demand', text: 'Forecast 30, 60 or 120 minutes of boardings with evaluated XGBoost models.' },
  { to: '/optimization', icon: GitBranch, title: 'Optimize service', text: 'Generate real CP-SAT plans constrained by fleet, reserve, headway and essential stops.' },
  { to: '/recommendations', icon: ShieldCheck, title: 'Review & approve', text: 'Inspect evidence, record an operator decision and activate the full plan in simulation.' },
  { to: '/simulator', icon: FlaskConical, title: 'Explore scenarios', text: 'Change demand, traffic and available fleet; compare calculated operating outcomes.' },
  { to: '/analytics', icon: Database, title: 'Export results', text: 'Download persisted forecasts, observations, comparisons and approval records.' },
];

export default function ProjectPage() {
  const dashboard = useResource('/api/dashboard/summary');
  const kpis = dashboard.data?.kpis ?? {};
  return <div className="to-page">
    <PageHeading eyebrow="SALEM · TRANSIT DECISION SUPPORT" title="The TransitOpt AI project" description="Predict demand · Analyze traffic · Optimize routes · Improve service" />
    <ErrorNotice message={dashboard.error} retry={dashboard.refresh} />
    <section className="to-hero">
      <SourceBadge source="SYNTHETIC_DEMO_DATA" />
      <h2>Predict smarter.<br /><span>Optimize better.</span><br />Move people efficiently.</h2>
      <p>A connected public transit planning platform built on your existing VisionX computer vision model. Forecast demand, validate fleet choices and keep operators in control.</p>
      <div className="to-action-row"><Link to="/" className="to-button primary large"><BusFront size={16} />Open operator dashboard<ArrowUpRight size={15} /></Link><Link to="/cctv" className="to-button large"><Camera size={16} />Start CCTV analysis</Link></div>
    </section>
    {dashboard.loading ? <Loading label="Loading the operating scenario…" /> : <div className="to-kpis">
      <Metric label="Available fleet" value={numberText(kpis.available_buses)} unit="buses" detail={`${numberText(kpis.reserve_buses)} held in reserve`} />
      <Metric label="Active allocation" value={numberText(kpis.allocated_buses)} unit="buses" detail="Persisted simulated operating plan" />
      <Metric label="Forecast boarding demand" value={numberText(kpis.forecast_passenger_demand)} detail="Configured planning horizon · synthetic history" accent="green" />
      <Metric label="Capacity shortfall" value={numberText(kpis.capacity_shortfall)} unit="boardings" detail="Explicit unmet forecast demand" accent="orange" />
    </div>}
    <Panel title="From observation to an approved plan" subtitle="Each step connects to the API, database and actual models">
      <div className="to-workflow">{['CCTV observations', 'Traffic intelligence', 'Demand forecasts', 'Constraint-aware optimization', 'Operator approval', 'Simulation comparison'].map((step, index) => <div key={step}><span>{String(index + 1).padStart(2, '0')}</span>{step}</div>)}</div>
      <p className="to-note">People detected at a stop are crowd estimates. Forecasts model boarding demand from synthetic history. Activation updates the local scenario after approval.</p>
    </Panel>
    <div className="to-grid three">{modules.map(({ to, icon: Icon, title, text }) => <Panel key={to} title={title}>
      <Icon size={24} color="#00d9ff" /><p className="to-description">{text}</p><Link className="to-button subtle" to={to}>Open module<ArrowUpRight size={13} /></Link>
    </Panel>)}</div>
    <Panel title="An honest demonstration network" subtitle="Eight illustrative routes R01–R08 around recognizable Salem area labels">
      <div className="to-pills"><SourceBadge source="REAL_MODEL_DETECTION" /><SourceBadge source="SYNTHETIC_DEMO_DATA" /><SourceBadge source="ML_FORECAST" /><SourceBadge source="OPTIMIZATION_RESULT" /></div>
      <p className="to-description">New Bus Stand, Five Roads, Suramangalam, Hasthampatti and Ammapet anchor a stylized network. Paths and operating assumptions are illustrative; the application does not claim official transport routes, verified GPS positions or real dispatch integration.</p>
      <Link to="/network" className="to-button">Explore the transit network<ArrowUpRight size={13} /></Link>
    </Panel>
  </div>;
}
