import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

const PLAN_LABELS = {
  SAFE: 'Safe',
  AGGRESSIVE: 'Aggressive',
  MINIMAL_DISRUPTION: 'Minimal Disruption',
}

function downloadBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export function ExportPage({ session }) {
  const [plans, setPlans] = useState([])
  const [selectedPlanId, setSelectedPlanId] = useState('')
  const [loading, setLoading] = useState(true)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    setError(null)
    api.get('/recovery-plans', { session_id: sessionId })
      .then((response) => {
        const nextPlans = response?.plans || []
        setPlans(nextPlans)
        setSelectedPlanId(nextPlans[0]?.plan_id || '')
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [sessionId])

  const selectedPlan = plans.find((plan) => plan.plan_id === selectedPlanId)

  const handleExport = async () => {
    if (!sessionId || !selectedPlanId) return
    setDownloading(true)
    setError(null)
    try {
      const blob = await api.export(sessionId, selectedPlanId)
      const planName = (selectedPlan?.archetype || 'plan').toLowerCase()
      downloadBlob(blob, `sprint_plan_${sessionId}_${planName}.xlsx`)
    } catch (err) {
      setError(err)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Export</p>
      <h2 className="mt-2 text-2xl font-semibold text-white">Download a plan-adapted Excel workbook</h2>
      <p className="mt-2 max-w-3xl text-sm text-slate-400">
        Choose Safe, Aggressive, or Minimal Disruption to generate a copy of the original uploaded Excel with
        Work_Items values projected as if that recovery plan were selected. The export does not apply the plan to the live session.
      </p>

      {loading ? (
        <p className="mt-5 text-sm text-slate-400">Loading recovery plans…</p>
      ) : (
        <div className="mt-5 grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Plan to export</span>
            <select
              value={selectedPlanId}
              onChange={(event) => setSelectedPlanId(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            >
              {plans.map((plan) => (
                <option key={plan.plan_id} value={plan.plan_id}>
                  {PLAN_LABELS[plan.archetype] || plan.archetype} — {plan.label} ({plan.actions?.length || 0} actions)
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={handleExport}
            disabled={!selectedPlanId || downloading}
            className="rounded-xl border border-emerald-500 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {downloading ? 'Generating…' : 'Download Excel'}
          </button>
        </div>
      )}

      {selectedPlan && (
        <div className="mt-5 rounded-2xl border border-slate-700 bg-slate-950/60 p-4 text-sm text-slate-300">
          <div className="font-semibold text-white">{PLAN_LABELS[selectedPlan.archetype] || selectedPlan.archetype}</div>
          <div className="mt-1 text-slate-400">{selectedPlan.explanation?.narrative_summary || 'Projected workbook export.'}</div>
        </div>
      )}

      {error && <p className="mt-4 text-sm text-rose-300">{error.message || 'Export failed'}</p>}
    </section>
  )
}

export default ExportPage
