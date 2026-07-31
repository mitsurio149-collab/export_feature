import React, {useState} from 'react'
import { api } from '../api/client'

export function DemoControls({onLoadSuccess, onResetSuccess}){
  const [status, setStatus] = useState({loading:false, error:null, result:null})

  const handleLoadDemo = async () => {
    setStatus({loading:true, error:null, result:null})
    try {
      const result = await api.demoLoad()
      setStatus({loading:false, error:null, result})
      onLoadSuccess?.(result)
    } catch (error) {
      setStatus({loading:false, error, result:null})
    }
  }

  const handleResetDemo = async () => {
    if (!window.confirm('Reset demo sessions? This clears server session state and cannot be undone.')) {
      return
    }
    setStatus({loading:true, error:null, result:null})
    try {
      const result = await api.demoReset()
      setStatus({loading:false, error:null, result})
      onResetSuccess?.()
    } catch (error) {
      setStatus({loading:false, error, result:null})
    }
  }

  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Demo session</p>
          <h2 className="mt-2 text-2xl font-bold text-white">Try the demo project</h2>
          <p className="mt-2 text-slate-400">Load a validated demo workbook or reset server state to a clean session.</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <button onClick={handleLoadDemo} disabled={status.loading} className="rounded-2xl bg-emerald-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-60">
            {status.loading ? 'Loading…' : 'Load demo'}
          </button>
          <button onClick={handleResetDemo} disabled={status.loading} className="rounded-2xl border border-slate-700 bg-slate-950 px-5 py-3 text-sm font-semibold text-slate-200 transition hover:border-emerald-300 hover:text-white disabled:opacity-60">
            Reset demo
          </button>
        </div>
      </div>
      <div className="mt-6">
        {status.loading && <div className="rounded-2xl bg-slate-800 p-4 text-slate-200">Waiting for demo endpoint...</div>}
        {status.error && <div className="rounded-2xl bg-amber-950 p-4 text-amber-100">Demo error: {status.error.message}</div>}
        {status.result && <div className="rounded-2xl bg-slate-950 p-4 text-slate-200">{status.result.message || 'Demo action completed successfully.'}</div>}
      </div>
    </section>
  )
}
