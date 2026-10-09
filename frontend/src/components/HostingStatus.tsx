import { useEffect, useState } from 'react';

export default function HostingStatus() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (import.meta.env.VITE_HOSTING_MODE !== 'free-hybrid') return;
    let alive = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      if (!alive) return;
      setChecking(true);
      let connected = false;
      try {
        const response = await fetch('/gateway/status', { cache: 'no-store', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
        const result = await response.json();
        connected = response.ok && result.ml_online === true;
        if (alive) setOnline(connected);
      } catch { if (alive) setOnline(false); }
      finally {
        if (alive) {
          setChecking(false);
          timer = setTimeout(() => { if (!document.hidden) void check(); }, connected ? 60000 : 10000);
        }
      }
    };
    const resume = () => {
      if (!document.hidden) setRevision(value => value + 1);
    };
    void check();
    document.addEventListener('visibilitychange', resume);
    return () => { alive = false; controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', resume); };
  }, [revision]);
  if (import.meta.env.VITE_HOSTING_MODE !== 'free-hybrid') return null;
  return <div role="status" style={{ padding: '8px 16px', background: online === false ? '#78350f' : '#164e63', color: '#fff', fontSize: 13, textAlign: 'center' }}>
    {import.meta.env.VITE_PUBLIC_ADMIN === 'true' && 'Public admin · '}{online === null ? 'Connecting to the laptop ML server…' : online ? 'ML connected · Keep the laptop and hosting launcher running.' : 'ML connection unavailable · Retrying automatically. Keep Start-Free-Hosting.bat running on the laptop.'}
    {online === false && <button disabled={checking} onClick={() => setRevision(value => value + 1)} style={{ marginLeft: 10, padding: '3px 9px', border: '1px solid #fff', borderRadius: 5, background: 'transparent', color: '#fff', cursor: 'pointer' }}>{checking ? 'Checking…' : 'Retry connection'}</button>}
  </div>;
}
