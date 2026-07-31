import React from 'react'

export default function MetricsRow({metrics}){
  const completionPct = typeof metrics?.completion_pct === 'number' ? Math.round(metrics.completion_pct * 100) : null
  const remainingHours = typeof metrics?.remaining_effort_hours === 'number' ? metrics.remaining_effort_hours : null
  const personDays = remainingHours !== null ? Math.round((remainingHours/8) * 10)/10 : null

  return (
    <>
      <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
        <div className="text-sm uppercase tracking-[0.2em] text-slate-400">Completion %</div>
        <div className="mt-3 text-2xl font-semibold text-white">{completionPct !== null ? `${completionPct}%` : '—'}</div>
        <div className="mt-1 text-xs text-slate-400">by item count</div>
      </div>
      <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
        <div className="text-sm uppercase tracking-[0.2em] text-slate-400">Remaining effort</div>
        <div className="mt-3 text-2xl font-semibold text-white">{remainingHours !== null ? `${remainingHours}h` : '—'}{personDays !== null ? ` (~${personDays} pd)` : ''}</div>
      </div>
    </>
  )
}
