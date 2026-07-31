import React, {useEffect, useState} from 'react'
import { Dashboard } from './pages/Dashboard'
import { UploadPage } from './pages/Upload'
import { DemoControls } from './pages/DemoControls'
import { api } from './api/client'

export default function App(){
  const [backendOk, setBackendOk] = useState(null)
  const [session, setSession] = useState(null)

  useEffect(()=>{
    let mounted = true
    api.health().then(()=>{ if(mounted) setBackendOk(true)}).catch(()=>{ if(mounted) setBackendOk(false)})
    return ()=> mounted=false
  },[])

  const handleSessionEstablished = (data) => {
    setSession(data)
  }

  const handleReset = async () => {
    try {
      await api.demoReset()
    } catch (error) {
      console.error('Failed to reset session:', error)
    }
    setSession(null)
  }

  return (
    <div className="app-shell font-sans">
      <div className="max-w-7xl mx-auto p-4">
        <header className="flex justify-between items-start px-1 pb-2">
          <div>
            <div className="text-[15px] font-extrabold tracking-tight leading-none">Sprint Whisperer</div>
            <div className="text-[8px] text-[var(--muted)] mt-0.5 tracking-wide">Project forecasting & decision intelligence</div>
          </div>
          <div>
            {backendOk === null ? (
              <span className="text-[9px] font-bold px-2 py-1 bg-slate-700 text-slate-400 rounded">Checking…</span>
            ) : backendOk ? (
              <span className="text-[9px] font-extrabold px-2 py-1 bg-[var(--teal)] text-[var(--bg)] rounded">Backend: OK</span>
            ) : (
              <span className="text-[9px] font-extrabold px-2 py-1 bg-red-600 text-white rounded">Backend unreachable</span>
            )}
          </div>
        </header>

        <main>
          {session ? (
            <Dashboard session={session} onReset={handleReset} />
          ) : (
            <div className="space-y-6">
              <UploadPage onSuccess={handleSessionEstablished} />
              <DemoControls onLoadSuccess={handleSessionEstablished} />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
