import { useEffect, useState } from 'react';

export default function HostingStatus() {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    if (import.meta.env.VITE_HOSTING_MODE !== 'free-hybrid') return;
    let alive = true;
    const check = async () => {
      try {
        const response = await fetch('/gateway/status', { signal: AbortSignal.timeout(15000) });
        const result = await response.json();
        if (alive) setOnline(response.ok && result.ml_online === true);
      } catch { if (alive) setOnline(false); }
    };
    void check();
    const interval = setInterval(() => { if (!document.hidden) void check(); }, 60000);
    return () => { alive = false; clearInterval(interval); };
  }, []);
  if (import.meta.env.VITE_HOSTING_MODE !== 'free-hybrid') return null;
  return <div role="status" style={{ padding: '8px 16px', background: online === false ? '#78350f' : '#164e63', color: '#fff', fontSize: 13, textAlign: 'center' }}>
    {online === null ? 'Connecting to the laptop ML server…' : online ? 'ML connected · Keep the laptop and hosting launcher running.' : 'ML disconnected · Run Start-Free-Hosting.bat on the laptop, then refresh this page.'}
  </div>;
}
