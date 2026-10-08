import { BASE_URL, request } from './api';

export type Data = Record<string, any>;
export interface Point { x: number; y: number }
export interface TransitStop extends Point { id: string; name: string; essential: boolean; terminal?: boolean }
export interface RouteVariant { id: string; name: string; geometry: Point[]; stop_ids: string[]; segment_ids: string[]; cycle_minutes: number; distance_km: number; validated: boolean }
export interface TransitRoute { id: string; name: string; color: string; current_buses: number; current_variant_id: string; bus_capacity: number; capacity: number; min_buses: number; max_headway_minutes: number; corridor_id: string; stop_ids: string[]; geometry: Point[]; variants: RouteVariant[]; source: string }
export interface Network { width: number; height: number; source: string; disclaimer: string; as_of?: string; routes: TransitRoute[]; stops: TransitStop[]; cameras: Data[]; corridors: Data[]; segments: Data[]; stop_metrics?: Data[] }

export async function transitRequest<T = Data>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await request(`${BASE_URL}${path}`, { ...init, headers });
  const data = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.error ?? JSON.stringify(data.detail) ?? 'Request failed');
  return data;
}
export const postTransit = <T = Data>(path: string, data: unknown = {}) => transitRequest<T>(path, { method: 'POST', body: JSON.stringify(data) });
export const patchTransit = <T = Data>(path: string, data: unknown) => transitRequest<T>(path, { method: 'PATCH', body: JSON.stringify(data) });
export async function uploadVision(file: File, cameraId: string, confidence: number): Promise<Data> {
  const body = new FormData(); body.append('file', file); body.append('camera_id', cameraId); body.append('confidence', String(confidence)); body.append('track', 'true');
  const video = file.type.startsWith('video/') || /\.(mp4|avi|mov|mkv|webm)$/i.test(file.name);
  return transitRequest(`/api/vision/analyze-${video ? 'video' : 'image'}`, { method: 'POST', body });
}
export async function exportTransit(kind: string, format: 'csv' | 'json' = 'csv', scenarioId?: string) {
  const path = scenarioId ? `/api/exports/scenarios/${encodeURIComponent(scenarioId)}` : `/api/exports/${kind}`;
  const response = await request(`${BASE_URL}${path}?format=${format}`);
  if (!response.ok) throw new Error('Export failed. Check that this result still exists.');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a'); link.href = url; link.download = `transitopt-${scenarioId ?? kind}.${format}`; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const rows = (value: any): Data[] => Array.isArray(value) ? value : [];
export const numeric = (value: any, fallback = 0): number => Number.isFinite(Number(value)) ? Number(value) : fallback;
export const numberText = (value: any, digits = 0): string => value == null ? 'Unavailable' : numeric(value).toLocaleString('en-IN', { maximumFractionDigits: digits });
export const timeText = (value?: string): string => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Calcutta', dateStyle: 'medium', timeStyle: 'short' }) : 'Not recorded';
