import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { BASE_URL, session, setCredentials } from '../services/api';

export default function AuthGate({children}:{children:ReactNode}) {
  const publicAdmin = import.meta.env.VITE_PUBLIC_ADMIN === 'true';
  const [state,setState]=useState<'loading'|'login'|'ready'|'offline'>('loading');
  const [username,setUsername]=useState('admin');
  const [password,setPassword]=useState('');
  const [error,setError]=useState('');
  const check=async()=>{try{const r=await session();setState(r.ok?'ready':r.status===401?'login':'offline');setError(r.ok?'':`Server returned HTTP ${r.status}`);return r.ok;}catch(e){setError(e instanceof Error?e.message:'Connection failed');setState('offline');return false;}};
  useEffect(()=>{if(!publicAdmin)check();},[publicAdmin]);
  useEffect(()=>{
    if(state!=='offline')return;
    const timer=window.setInterval(()=>{check();},3000);
    return ()=>window.clearInterval(timer);
  },[state]);
  if(publicAdmin || state==='ready')return children;
  return <div className="min-h-screen animated-bg flex items-center justify-center p-6"><div className="glass p-8 max-w-md w-full space-y-5">
    <h1 className="gradient-text text-3xl font-bold">TransitOpt AI</h1>
    <Link to="/" className="text-cyan-400 text-sm">App home</Link><span className="text-slate-500 mx-2">·</span><Link to="/passenger" className="text-cyan-400 text-sm">Passenger navigation</Link>
    {state==='loading'?<p>Connecting to the analysis server…</p>:state==='offline'?<><p>Waiting for the analysis server. Double-click Run-VisionX.bat or run <code>Run-VisionX.bat start</code>.</p><p className="text-sm text-slate-400">This page reconnects automatically when the server is ready. Open the app at <a className="text-cyan-400 underline" href="http://127.0.0.1:8000">http://127.0.0.1:8000</a>.</p><p role="alert" className="text-sm text-amber-300">{error}</p><p className="text-xs text-slate-500 break-all">Connecting to {BASE_URL || window.location.origin}/api/session</p><button className="btn-primary" onClick={check}>Retry connection</button><button className="btn-secondary ml-2" onClick={()=>setState('ready')}>Explore dashboard</button></>:<form className="space-y-4" onSubmit={async e=>{e.preventDefault();setCredentials(username,password);if(!await check())setError('Sign-in failed. Check your credentials.');setPassword('');}}>
      <p>Sign in to the admin and camera ML workspace.</p>
      <label className="block">Username<input autoComplete="username" className="input-field mt-2" value={username} onChange={e=>setUsername(e.target.value)}/></label>
      <label className="block">Password<input autoComplete="current-password" type="password" className="input-field mt-2" value={password} onChange={e=>setPassword(e.target.value)}/></label>
      {error&&<p role="alert" className="text-red-400">{error}</p>}
      <button className="btn-primary w-full">Sign in</button>
    </form>}
  </div></div>;
}
