import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertCircle, ArrowUpRight, Loader2, RefreshCw } from 'lucide-react';
import { transitRequest, type Data } from '../../services/transit';

const RevisionContext = createContext({ revision: 0, invalidate: () => {} });
const cache = new Map<string, { at: number; data: any }>();
const pending = new Map<string, Promise<any>>();
export function TransitProvider({ children }: { children: ReactNode }) {
  const [revision, setRevision] = useState(0);
  const invalidate = useCallback(() => { cache.clear(); pending.clear(); setRevision(n => n + 1); }, []);
  return <RevisionContext.Provider value={{ revision, invalidate }}>{children}</RevisionContext.Provider>;
}
export const useTransitRefresh = () => useContext(RevisionContext).invalidate;
export function useResource<T = Data>(path: string) {
  const { revision } = useContext(RevisionContext);
  const [retry, setRetry] = useState(0);
  const [storedData, setData] = useState<{ path: string; value: T | null }>(() => ({ path, value: cache.get(path)?.data ?? null }));
  const data: T | null = storedData.path === path ? storedData.value : (cache.get(path)?.data as T | undefined) ?? null;
  const [loading, setLoading] = useState(!cache.has(path));
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    const saved = cache.get(path);
    if (saved && Date.now() - saved.at < 30000 && !retry) { setData({ path, value: saved.data }); setLoading(false); return; }
    // Keep usable controls visible while refreshing their existing data.
    setLoading(data === null); setError('');
    let promise = pending.get(path);
    if (!promise) {
      promise = transitRequest<T>(path);
      pending.set(path, promise);
      promise.then(value => { if (pending.get(path) === promise) cache.set(path, { at: Date.now(), data: value }); }).catch(() => {}).finally(() => { if (pending.get(path) === promise) pending.delete(path); });
    }
    promise.then(value => { if (current) setData({ path, value }); }).catch(e => { if (current) setError(e.message); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [path, revision, retry]);
  return { data, loading, error, refresh: () => { cache.delete(path); setRetry(n => n + 1); } };
}
export function PageHeading({ eyebrow = 'TRANSIT OPERATIONS', title, description, actions }: { eyebrow?: string; title: string; description: string; actions?: ReactNode }) {
  return <div className="to-heading"><div><div className="to-eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div><div className="to-heading-actions">{actions}</div></div>;
}
export function Panel({ title, subtitle, actions, children, className = '' }: { title?: string; subtitle?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`to-panel ${className}`}>{title && <div className="to-panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{actions}</div>}{children}</section>;
}
export function SourceBadge({ source }: { source?: string }) {
  const labels: Record<string, string> = { SYNTHETIC_DEMO_DATA: 'Synthetic demo', REAL_MODEL_DETECTION: 'Real model detection', ML_FORECAST: 'ML forecast', OPTIMIZATION_RESULT: 'Solver result' };
  return <span className={`to-source ${source === 'REAL_MODEL_DETECTION' ? 'real' : source === 'ML_FORECAST' ? 'forecast' : source === 'OPTIMIZATION_RESULT' ? 'solver' : ''}`}>{labels[source ?? ''] ?? source ?? 'Synthetic demo'}</span>;
}
export function ErrorNotice({ message, retry }: { message?: string; retry?: () => void }) {
  return message ? <div role="alert" className="to-error"><AlertCircle size={17} /><span>{message}</span>{retry && <button className="to-button subtle" onClick={retry}>Retry</button>}</div> : null;
}
export function Loading({ label = 'Loading application data…' }: { label?: string }) { return <div className="to-loading" role="status"><Loader2 className="animate-spin" size={22} />{label}</div>; }
export function Empty({ title, description }: { title: string; description: string }) { return <div className="to-empty"><h3>{title}</h3><p>{description}</p></div>; }
export function Metric({ label, value, unit, detail, icon, accent = 'cyan' }: { label: string; value: ReactNode; unit?: string; detail?: string; icon?: ReactNode; accent?: string }) {
  return <div className={`to-metric ${accent}`}><div className="to-metric-label">{label}{icon}</div><div className="to-metric-value">{value}<span>{unit}</span></div>{detail && <p>{detail}</p>}</div>;
}
export function useAction() {
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [success, setSuccess] = useState('');
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const run = async <T,>(fn: () => Promise<T>, message = ''): Promise<T | undefined> => {
    setBusy(true); setError(''); setSuccess('');
    try { const result = await fn(); if (mounted.current) setSuccess(message); return result; }
    catch (e: any) { if (mounted.current) setError(e.message ?? 'Action failed'); }
    finally { if (mounted.current) setBusy(false); }
  };
  return { busy, error, success, run, setError };
}
export function ActionNotice({ action }: { action: ReturnType<typeof useAction> }) { return <><ErrorNotice message={action.error} />{action.success && <div className="to-success" role="status">{action.success}</div>}</>; }
export const RefreshButton = ({ onClick }: { onClick: () => void }) => <button className="to-button subtle" onClick={onClick}><RefreshCw size={14} /> Refresh</button>;
export const chartTooltip = { backgroundColor: 'var(--tooltip-bg, #0b2342)', borderColor: 'var(--tooltip-border, #24445f)', borderRadius: 10, color: 'var(--text-main, #f5f9ff)', boxShadow: 'var(--shadow-md)' };
