import { useEffect, useMemo, useState } from 'react';
import { BusFront, Camera, Layers, MapPin, Minus, Plus, RotateCcw } from 'lucide-react';
import { numberText, rows, type Data, type Network, type Point } from '../../services/transit';

const pointsText = (points: Point[]) => points.map(p => `${p.x},${p.y}`).join(' ');
function positionAlong(points: Point[], fraction: number): Point {
  if (!points.length) return { x: 0, y: 0 };
  const lengths = points.slice(1).map((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y));
  let target = lengths.reduce((a, b) => a + b, 0) * fraction;
  for (let i = 0; i < lengths.length; i++) {
    if (target <= lengths[i]) { const t = lengths[i] ? target / lengths[i] : 0; return { x: points[i].x + (points[i + 1].x - points[i].x) * t, y: points[i].y + (points[i + 1].y - points[i].y) * t }; }
    target -= lengths[i];
  }
  return points[points.length - 1];
}
export default function TransitMap({ network, traffic = [], plan, compact = false, selectedRoute: suppliedRoute, onSelectRoute }: { network: Network; traffic?: Data[]; plan?: Data; compact?: boolean; selectedRoute?: string; onSelectRoute?: (id: string) => void }) {
  const [localRoute, setLocalRoute] = useState('');
  const selectedRoute = suppliedRoute ?? localRoute;
  const [selectedStop, setSelectedStop] = useState('');
  const [zoom, setZoom] = useState(1);
  const [layers, setLayers] = useState({ routes: true, recommended: Boolean(plan), traffic: true, buses: false, demand: false, crowd: true });
  const [showLayers, setShowLayers] = useState(!compact);
  const selected = network.stops.find(stop => stop.id === selectedStop);
  const stopMetrics = new Map((network.stop_metrics ?? []).map(metric => [metric.stop_id, metric]));
  const maximumDemand = Math.max(1, ...(network.stop_metrics ?? []).map(metric => Number(metric.boarding_demand ?? 0)));
  const allocations = rows(plan?.routes);
  const planKey = allocations.map(row => `${row.route_id}:${row.variant_id}:${row.buses}`).join('|');
  useEffect(() => { setLayers(current => ({ ...current, recommended: Boolean(planKey) })); }, [planKey]);
  const scores = useMemo(() => new Map(traffic.map(c => [c.id, c])), [traffic]);
  const toggle = (name: keyof typeof layers) => setLayers(previous => ({ ...previous, [name]: !previous[name] }));
  const choose = (id: string) => { setLocalRoute(id); onSelectRoute?.(id); };
  const mapWidth = network.width || 800, mapHeight = network.height || 600;
  return <div className={`to-map ${compact ? 'compact' : ''}`}>
    <div className="to-map-caption"><span>SALEM TRANSIT NETWORK</span><span>ILLUSTRATIVE · NOT TO SCALE</span></div>
    <svg viewBox={`0 0 ${mapWidth} ${mapHeight}`} role="img" aria-label="Interactive illustrative Salem transit network with eight routes" className="to-map-canvas">
      <defs>
        <pattern id="transit-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#17334a" strokeWidth=".65" /></pattern>
        <radialGradient id="transit-demand"><stop offset="0" stopColor="#00d9ff" stopOpacity=".26" /><stop offset="1" stopColor="#00d9ff" stopOpacity="0" /></radialGradient>
      </defs>
      <rect width={mapWidth} height={mapHeight} fill="#081b30" /><rect width={mapWidth} height={mapHeight} fill="url(#transit-grid)" />
      <g transform={`translate(${mapWidth / 2} ${mapHeight / 2}) scale(${zoom}) translate(${-mapWidth / 2} ${-mapHeight / 2})`}>
        <path d="M 30,560 C 140,460 210,390 280,340 S 400,270 490,340 S 670,490 775,485" stroke="#12334a" fill="none" strokeWidth="15" />
        {network.segments.map(segment => <polyline key={segment.id} points={pointsText(segment.geometry ?? [])} fill="none" stroke="#28435b" strokeWidth="9" strokeLinejoin="round" opacity=".48" />)}
        {layers.traffic && network.routes.map(route => {
          const observation = scores.get(route.corridor_id);
          const score = Number(observation?.congestion_score ?? 0);
          if (score < 50) return null;
          const point = positionAlong(route.geometry, .54);
          return <g key={route.id}><circle cx={point.x} cy={point.y} r={score >= 75 ? 36 : 28} fill={score >= 75 ? '#ff4d67' : '#ffb020'} opacity=".09" /><circle cx={point.x} cy={point.y} r={score >= 75 ? 36 : 28} fill="none" stroke={score >= 75 ? '#ff4d67' : '#ffb020'} strokeDasharray="3 5" opacity=".4" /><title>{route.id}: {observation?.category} congestion — {observation?.source}</title></g>;
        })}
        {layers.demand && network.stops.map(stop => <circle key={stop.id} cx={stop.x} cy={stop.y} r={15 + 35 * Math.sqrt(Number(stopMetrics.get(stop.id)?.boarding_demand ?? 0) / maximumDemand)} fill="url(#transit-demand)"><title>{stop.name}: {numberText(stopMetrics.get(stop.id)?.boarding_demand)} synthetic historical boardings in the latest 30-minute interval</title></circle>)}
        {layers.routes && network.routes.map(route => <g key={route.id} opacity={!selectedRoute || selectedRoute === route.id ? 1 : .15}>
          <polyline points={pointsText(route.geometry)} fill="none" stroke={route.color} strokeWidth={selectedRoute === route.id ? 4.5 : 2.8} strokeLinejoin="round" onClick={() => choose(route.id)} className="to-map-route"><title>{route.id} · {route.name} · {route.current_buses} buses</title></polyline>
          <polyline points={pointsText(route.geometry)} fill="none" stroke="transparent" strokeWidth="18" onClick={() => choose(route.id)} className="to-map-route" />
        </g>)}
        {layers.recommended && allocations.map(allocation => {
          const route = network.routes.find(r => r.id === allocation.route_id);
          const variant = route?.variants.find(v => v.id === allocation.variant_id);
          if (!route || !variant || (selectedRoute && selectedRoute !== route.id)) return null;
          return <polyline key={route.id} points={pointsText(variant.geometry)} fill="none" stroke="#f5f9ff" strokeWidth="3.2" strokeDasharray="8 6" strokeLinejoin="round" opacity=".9"><title>Solver plan {route.id}: {allocation.buses} buses, {variant.name}</title></polyline>;
        })}
        {layers.buses && network.routes.flatMap(route => {
          const active = allocations.find(a => a.route_id === route.id);
          const geometry = route.variants.find(v => v.id === (layers.recommended ? active?.variant_id : route.current_variant_id))?.geometry ?? route.geometry;
          const count = Number(layers.recommended && active ? active.buses : route.current_buses);
          return Array.from({ length: count }, (_, i) => {
            const point = positionAlong(geometry, (i + 1) / (count + 1));
            return <g key={`${route.id}-${i}`} transform={`translate(${point.x},${point.y})`} opacity={!selectedRoute || selectedRoute === route.id ? 1 : .15}><rect x="-5" y="-7" width="10" height="14" rx="3" fill={route.color} stroke="#061426" strokeWidth="2" /><title>{route.id}: illustrative assigned bus {i + 1} of {count}; not GPS</title></g>;
          });
        })}
        {network.stops.map(stop => <g key={stop.id} className="to-map-stop" onClick={() => setSelectedStop(stop.id)}>
          {layers.crowd && stopMetrics.get(stop.id)?.crowd_count != null && <circle cx={stop.x} cy={stop.y} r={12 + Math.min(23, Number(stopMetrics.get(stop.id)?.crowd_count))} stroke="#00e5a0" strokeOpacity=".35" fill="#00e5a0" fillOpacity=".08"><title>{numberText(stopMetrics.get(stop.id)?.crowd_count, 1)} observed people per frame; crowd estimate, not ticketed passengers</title></circle>}
          <circle cx={stop.x} cy={stop.y} r={stop.terminal ? 6 : 4} fill="#091b30" stroke={selectedStop === stop.id ? '#00d9ff' : '#cad8e6'} strokeWidth="2" />
          <text x={stop.x + 11} y={stop.y + (stop.id === 'S02' ? 18 : -9)} className="to-map-label">{stop.name}</text><title>{stop.name} · {stop.essential ? 'Essential stop' : 'Stop'}</title>
        </g>)}
        {network.cameras.map(camera => {
          const stop = network.stops.find(s => s.id === camera.stop_id); if (!stop) return null;
          return <g key={camera.id} transform={`translate(${stop.x - 20},${stop.y - 22})`}><rect x="0" y="0" width="12" height="9" rx="2" stroke="#69a9cc" fill="#102d47" /><path d="M12 2 L16 0 L16 9 L12 7" stroke="#69a9cc" fill="#102d47" /><title>{camera.name}: {camera.status}</title></g>;
        })}
      </g>
      <g transform={`translate(${mapWidth - 36},58)`}><path d="M0 -17 L-5 1 L0 -3 L5 1 Z" fill="#8aa9c3" /><text y="17" x="-4" fill="#8aa9c3" fontSize="10">N</text></g>
    </svg>
    <div className="to-map-zoom"><button aria-label="Zoom in" onClick={() => setZoom(z => Math.min(2, z + .2))}><Plus size={15} /></button><button aria-label="Zoom out" onClick={() => setZoom(z => Math.max(.7, z - .2))}><Minus size={15} /></button><button aria-label="Reset map view" onClick={() => { setZoom(1); choose(''); setSelectedStop(''); }}><RotateCcw size={13} /></button></div>
    <div className="to-map-layers"><button className="to-button subtle" aria-expanded={showLayers} onClick={() => setShowLayers(value => !value)}><Layers size={15} /> Layers</button>{showLayers && <div className="to-layer-options">{[['routes', 'Existing routes'], ['recommended', 'Solver plan'], ['traffic', 'Traffic zones'], ['buses', 'Illustrative buses'], ['demand', 'Passenger demand'], ['crowd', 'Observed crowds']].map(([key, label]) => <label key={key}><input type="checkbox" checked={layers[key as keyof typeof layers]} onChange={() => toggle(key as keyof typeof layers)} disabled={key === 'recommended' && !plan} />{label}</label>)}</div>}</div>
    {selected && <div className="to-map-popover"><button aria-label="Close stop details" onClick={() => setSelectedStop('')}>×</button><MapPin size={15} /><strong>{selected.name}</strong><p>{selected.essential ? 'Essential stop · preserved by optimizer' : 'Bus stop'}</p><p>{network.routes.filter(r => r.stop_ids.includes(selected.id)).map(r => r.id).join(' · ')}</p><p>Latest synthetic boardings: {numberText(stopMetrics.get(selected.id)?.boarding_demand)} / 30 min</p><p>Observed crowd: {numberText(stopMetrics.get(selected.id)?.crowd_count, 1)} people per frame</p></div>}
    <div className="to-map-bottom"><div className="to-map-route-pills"><button className={!selectedRoute ? 'selected' : ''} onClick={() => choose('')}>All routes</button>{network.routes.map(route => <button key={route.id} className={selectedRoute === route.id ? 'selected' : ''} onClick={() => choose(route.id)}><span style={{ background: route.color }} />{route.id}</button>)}</div><span className="to-map-key"><i /> Severe congestion</span></div>
  </div>;
}
