import type { Data } from './transit';

export type GeoPoint = { latitude: number; longitude: number };
export const TRAFFIC_COLORS = { LOW: '#16a34a', MODERATE: '#eab308', HIGH: '#f97316', SEVERE: '#dc2626', UNKNOWN: '#64748b' };

export function distanceMeters(a: GeoPoint, b: GeoPoint): number {
  const radians = Math.PI / 180;
  const dlat = (b.latitude - a.latitude) * radians, dlon = (b.longitude - a.longitude) * radians;
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(a.latitude * radians) * Math.cos(b.latitude * radians) * Math.sin(dlon / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}

export function validPoint(point: GeoPoint): boolean {
  return Number.isFinite(point.latitude) && Number.isFinite(point.longitude) && Math.abs(point.latitude) <= 90 && Math.abs(point.longitude) <= 180;
}

export function trafficEvidence(camera: Data, now = Date.now()) {
  const o = camera.observation;
  const verified = ['operator_configured', 'bus_gps_at_capture'].includes(camera.coordinate_source);
  const age = o?.timestamp ? now - Date.parse(o.timestamp) : Infinity;
  const lifetime = camera.camera_role === 'bus_road' ? 20000 : 300000;
  const available = Boolean(verified && validPoint(camera as GeoPoint) && o?.live && o?.fresh &&
    o.source === 'REAL_MODEL_DETECTION' && Number.isFinite(o.score) && o.score >= 0 && o.score <= 100 && age >= -60000 && age <= lifetime);
  const category = available ? (['LOW', 'MODERATE', 'HIGH', 'SEVERE'].includes(o.category) ? o.category :
    o.score >= 75 ? 'SEVERE' : o.score >= 50 ? 'HIGH' : o.score >= 25 ? 'MODERATE' : 'LOW') as keyof typeof TRAFFIC_COLORS : 'UNKNOWN';
  return { available, score: available ? o.score as number : null, category, color: TRAFFIC_COLORS[category],
    label: available ? `${category.charAt(0)}${category.slice(1).toLowerCase()} traffic · ${o.score}/100` : !verified ? 'Approximate camera location · traffic unknown' : 'Current traffic unknown' };
}

export function rankTrafficPlaces(cameras: Data[], now = Date.now()) {
  return cameras.filter(camera => trafficEvidence(camera, now).available).sort((a, b) =>
    trafficEvidence(a, now).score! - trafficEvidence(b, now).score! || (a.distance_km ?? 0) - (b.distance_km ?? 0) || String(a.id).localeCompare(String(b.id)));
}

export function distanceToPath(point: GeoPoint, geometry: number[][]): number {
  if (geometry.length < 2) return Infinity;
  const scaleX = 111320 * Math.cos(point.latitude * Math.PI / 180);
  let nearest = Infinity;
  for (let i = 1; i < geometry.length; i++) {
    const a = geometry[i - 1], b = geometry[i];
    const ax = (a[0] - point.longitude) * scaleX, ay = (a[1] - point.latitude) * 111320;
    const dx = (b[0] - a[0]) * scaleX, dy = (b[1] - a[1]) * 111320;
    const t = dx * dx + dy * dy ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) : 0;
    nearest = Math.min(nearest, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return nearest;
}
