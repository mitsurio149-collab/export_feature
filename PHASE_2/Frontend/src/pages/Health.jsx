import React, {useEffect, useState} from 'react'
import { api } from '../api/client'

export function HealthPage({backendOk}){
  const [status, setStatus] = useState({loading:false, error:null, data:null})

  useEffect(()=>{
    let mounted = true
    setStatus(s=>({...s, loading:true, error:null}))
    api.health().then(data=>{ if(mounted) setStatus({loading:false, error:null, data})}).catch(err=>{ if(mounted) setStatus({loading:false, error: err, data: null})})
    return ()=> mounted=false
  },[])

  if(backendOk===false){
    return (
      <section className="p-6 bg-slate-800 rounded">
        <h2 className="text-xl font-semibold text-red-300">Backend Unreachable</h2>
        <p className="text-slate-300">The backend health check failed. Please ensure the server is running at <code>/api</code>.</p>
      </section>
    )
  }

  if(status.loading) return <div className="p-6 bg-slate-800 rounded">Checking backend health…</div>
  if(status.error) return <div className="p-6 bg-amber-900 rounded text-amber-100">Error: {String(status.error.message || status.error)}</div>
  if(!status.data) return <div className="p-6 bg-slate-800 rounded">No health data returned.</div>

  return (
    <section className="p-6 bg-slate-800 rounded">
      <h2 className="text-2xl font-bold mb-2">Backend Health</h2>
      <div className="text-lg">Status: <span className="font-semibold text-emerald-400">{status.data.status || 'ok'}</span></div>
      <div className="mt-4 text-sm text-slate-300">Raw response: <pre className="bg-slate-900 p-2 rounded mt-2 text-xs">{JSON.stringify(status.data, null, 2)}</pre></div>
    </section>
  )
}
