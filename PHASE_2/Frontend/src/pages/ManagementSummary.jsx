import React, { useState, useEffect, useCallback } from 'react'
import {
  ChevronDown, ChevronRight, ChevronUp,
  Clock, User, GitBranch, Zap, AlertTriangle
} from 'lucide-react'
import { api } from '../api/client'
import { formatScheduleVariance } from '../api/formatters'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtShort(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return iso }
}

function riskLevel(score) {
  if (score >= 70) return { label: 'High',   bar: 'bg-rose-500',  text: 'text-rose-400',  border: 'border-rose-500/40',  bg: 'bg-rose-500/10'  }
  if (score >= 45) return { label: 'Medium', bar: 'bg-amber-400', text: 'text-amber-400', border: 'border-amber-400/40', bg: 'bg-amber-400/10' }
  return              { label: 'Low',    bar: 'bg-teal-400',  text: 'text-teal-400',  border: 'border-teal-500/40',  bg: 'bg-teal-500/10'  }
}

function StatusPill({ status }) {
  const s = (status || '').toLowerCase()
  const cls = s.includes('progress') ? 'bg-blue-500/15 text-blue-300 border-blue-500/30'
    : s.includes('block')            ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
    : s.includes('done') || s.includes('complet') ? 'bg-teal-500/15 text-teal-300 border-teal-500/30'
    : 'bg-slate-700/50 text-slate-400 border-slate-600'
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {status || 'Unknown'}
    </span>
  )
}

function Section({ label, accent = 'text-slate-500', border = 'border-slate-700', children }) {
  return (
    <div className={`rounded-xl border ${border} bg-slate-900`}>
      <div className={`px-4 py-2 border-b ${border} flex items-center`}>
        <span className={`text-[10px] font-semibold uppercase tracking-[0.22em] ${accent}`}>{label}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

// ── 1. Delivery Forecast ──────────────────────────────────────────────────────
// Manager-friendly labels:
//   Committed Date        → What we promised (target_end_date from MC or forecast)
//   Expected Delivery     → Deterministic forecast (forecast.expected_finish_date)
//   High-Confidence       → 80th percentile Monte Carlo
//   Worst-Case            → 95th percentile Monte Carlo

function barPos(iso, p10, p95) {
  if (!iso || !p10 || !p95) return 50
  const min = new Date(p10).getTime(), max = new Date(p95).getTime(), val = new Date(iso).getTime()
  return max === min ? 0 : Math.min(100, Math.max(0, Math.round(((val - min) / (max - min)) * 100)))
}

function FinishDateWindow({ sessionId }) {
  const [mc, setMc]             = useState(null)
  const [forecast, setForecast] = useState(null)
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    if (!sessionId) return
    Promise.all([
      api.monteCarlo(sessionId),
      api.forecast(sessionId).catch(() => null),
    ]).then(([m, f]) => {
      setMc(m?.monte_carlo ?? m)
      // Forecast wraps in .forecast key
      setForecast(f?.forecast ?? f)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [sessionId])

  const stats     = mc?.statistics || {}
  const p10       = stats.percentile_10
  const p95       = stats.percentile_95
  const onTimePct = mc?.on_time_probability != null ? Math.round(mc.on_time_probability * 100) : null
  const confidence = forecast?.confidence?.confidence_score ?? null

  // Dates: committed comes from the MC target; expected from deterministic forecast
  const targetDate      = mc?.target_end_date ?? forecast?.target_end_date ?? null
  const expectedFinish  = forecast?.expected_finish_date ?? null   // deterministic
  const p80             = stats.percentile_80 ?? null
  const worstCase       = stats.percentile_95 ?? null

  const dotMarkers = [
    { p: 50, dot: '#14b8a6', iso: stats.percentile_50 },
    { p: 80, dot: '#f59e0b', iso: p80 },
    { p: 95, dot: '#f43f5e', iso: worstCase },
  ].map(m => ({ ...m, left: barPos(m.iso, p10, p95) }))

  let onTimeMarker = null
  if (onTimePct != null && targetDate && p10 && p95) {
    onTimeMarker = { left: barPos(targetDate, p10, p95), date: fmtShort(targetDate), pct: onTimePct }
  }

  const onTimeColor = onTimePct == null ? 'text-slate-400'
    : onTimePct >= 60 ? 'text-teal-300'
    : onTimePct >= 40 ? 'text-amber-300'
    : 'text-rose-300'

  const simulationCountLabel = mc?.simulation_count != null
    ? `${mc.simulation_count.toLocaleString()} simulations`
    : '1,000 simulations'
  const simulationSummary = mc?.simulation_count != null && mc?.seed != null
    ? `${mc.simulation_count.toLocaleString()} simulations (seed ${mc.seed})`
    : null

  const DATE_CARDS = [
    {
      label: 'Committed Date',
      hint:  'The contractual or agreed delivery date. All other dates are evaluated relative to this commitment.',
      value: fmtShort(targetDate),
      color: 'text-violet-300', border: 'border-violet-500/40', bg: 'bg-violet-500/5', accent: 'text-violet-400',
    },
    {
      label: 'Deterministic Estimate',
      hint: 'Single-point forecast from remaining effort ÷ current velocity. Use as a sanity check alongside the simulation dates.',
      value: fmtShort(expectedFinish),
      color: 'text-sky-300', border: 'border-sky-500/40', bg: 'bg-sky-500/5', accent: 'text-sky-400',
    },
    {
      label: 'Likely Finish',
      hint:  `The median outcome across ${simulationCountLabel}. Half of all modelled scenarios finish before this date, half after. Use as the baseline planning estimate.`,
      value: fmtShort(stats.percentile_50 ?? null),
      color: 'text-teal-300',   border: 'border-teal-500/40',   bg: 'bg-teal-500/5',   accent: 'text-teal-400',
    },
    {
      label: 'High-Confidence Delivery',
      hint:  '80th percentile outcome — 8 in 10 simulations complete by this date. Suitable for external commitments where a safety buffer is warranted.',
      value: fmtShort(p80),
      color: 'text-amber-300',  border: 'border-amber-400/40',  bg: 'bg-amber-400/5',  accent: 'text-amber-400',
    },
    {
      label: 'Worst-Case Ceiling',
      hint:  '95th percentile outcome — only 1 in 20 simulations exceed this date. Use as the outer boundary for contingency planning, not as a target.',
      value: fmtShort(worstCase),
      color: 'text-rose-300',   border: 'border-rose-500/40',   bg: 'bg-rose-500/5',   accent: 'text-rose-400',
    },
  ]

  return (
    <Section label="Delivery forecast" border="border-slate-700">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-[11px] text-slate-500">
            When will we finish?
            {confidence != null && (
              <span className="ml-2 text-teal-400 font-medium">{Math.round(confidence * 100)}% confidence</span>
            )}
          </p>
          {simulationSummary && (
            <p className="mt-1 text-[10px] text-slate-500">{simulationSummary}</p>
          )}
        </div>
        {onTimePct != null && (
          <div className="text-right">
            <span className={`text-2xl font-bold ${onTimeColor}`}>{onTimePct}%</span>
            <span className="text-[11px] text-slate-500 ml-1.5">on-time</span>
          </div>
        )}
      </div>

      {loading ? <p className="text-sm text-slate-500">Calculating…</p> : (
        <>
          {/* Timeline bar */}
          <div className="relative mt-8 mb-6">
            {onTimeMarker && (
              <div className="absolute -translate-x-1/2 flex flex-col items-center" style={{ left: `${onTimeMarker.left}%`, bottom: '14px' }}>
                <div className={`text-[10px] font-bold whitespace-nowrap px-1.5 py-0.5 rounded bg-slate-800 border border-slate-600 ${onTimeColor}`}>
                  {onTimeMarker.pct}% on-time by {onTimeMarker.date}
                </div>
                <div className="w-px h-2 bg-slate-600" />
              </div>
            )}
            <div className="h-1.5 rounded-full bg-gradient-to-r from-teal-500 via-amber-400 to-rose-500" />
            {dotMarkers.map(({ p, dot, left }) => (
              <div key={p} className="absolute w-3.5 h-3.5 rounded-full border-2 border-slate-900 -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${left}%`, top: '50%', backgroundColor: dot }} />
            ))}
            {targetDate && (() => {
              const left = barPos(targetDate, p10, p95)
              return (
                <div className="absolute -translate-x-1/2 flex flex-col items-center" style={{ left: `${left}%`, top: '14px' }}>
                  <div className="w-px h-2 bg-violet-400" />
                  <div className="text-[10px] font-semibold whitespace-nowrap px-1.5 py-0.5 rounded bg-violet-500/15 border border-violet-500/40 text-violet-300">
                    Committed · {fmtShort(targetDate)}
                  </div>
                </div>
              )
            })()}
            <div className="flex justify-between mt-1 text-[10px] text-slate-600">
              <span>{fmtShort(p10)}</span>
              <span>{fmtShort(p95)}</span>
            </div>
          </div>

          {/* Manager date cards */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 mt-2">
            {DATE_CARDS.map(({ label, hint, value, color, border, bg, accent }) => (
              <div key={label} className={`rounded-lg border ${border} ${bg} p-2.5`}>
                <p className={`text-[10px] font-medium mb-0.5 ${accent}`}>{label}</p>
                <p className={`text-sm font-bold ${color}`}>{value}</p>
                <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">{hint}</p>
              </div>
            ))}
          </div>
          {/* Interpretation guide: P50 < P80 < P95 ordering */}
          <p className="mt-2 text-[10px] text-slate-600 leading-relaxed px-0.5">
            Dates are shown in ascending confidence order. All three are derived from the same {simulationCountLabel} of current velocity, blockers, and scope.
          </p>
        </>
      )}
    </Section>
  )
}

// ── 2. Risk Snapshot ──────────────────────────────────────────────────────────

const RISK_META = {
  schedule:   { oneliner: 'Delay vs. deadline',          weight: 0.40 },
  dependency: { oneliner: 'Task chain tangles',          weight: 0.25 },
  resource:   { oneliner: 'Team load & single points',   weight: 0.20 },
  scope:      { oneliner: 'Work added vs. original plan',weight: 0.15 },
}

function RiskConcentration({ sessionId }) {
  const [risk, setRisk]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [expanded, setExpanded] = useState(null)
  const [showFormula, setShowFormula] = useState(false)

  useEffect(() => {
    if (!sessionId) return
    api.risk(sessionId)
      .then(r => { setRisk(r?.risk_analysis ?? null); setLoading(false) })
      .catch(() => setLoading(false))
  }, [sessionId])

  const overall   = Math.round(risk?.overall_risk_score ?? 0)
  const overallRl = riskLevel(overall)

  const cats = risk ? [
    { key: 'schedule',   label: 'Schedule',     score: risk.schedule_risk?.score,   drivers: risk.schedule_risk?.drivers   || [] },
    { key: 'dependency', label: 'Dependencies', score: risk.dependency_risk?.score, drivers: risk.dependency_risk?.drivers || [] },
    { key: 'resource',   label: 'Team load',    score: risk.resource_risk?.score,   drivers: risk.resource_risk?.drivers   || [] },
    { key: 'scope',      label: 'Scope',        score: risk.scope_risk?.score,      drivers: risk.scope_risk?.drivers      || [] },
  ].filter(c => c.score !== undefined) : []

  return (
    <Section label="Risk snapshot" border="border-slate-700">
      {loading ? <p className="text-sm text-slate-500">Analysing…</p> : (
        <>
          <div className="flex items-center justify-between mb-3">
            <p className="text-[11px] text-slate-500">Where is the pressure?</p>
            {risk && (
              <div className="flex items-center gap-1.5">
                <span className={`text-xl font-bold ${overallRl.text}`}>{overall}</span>
                <span className="text-slate-600 text-sm">/100</span>
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${overallRl.border} ${overallRl.bg} ${overallRl.text}`}>{overallRl.label}</span>
              </div>
            )}
          </div>

          <div className="space-y-1">
            {cats.map(({ key, label, score, drivers }) => {
              const s      = Math.round(score ?? 0)
              const rl     = riskLevel(s)
              const isOpen = expanded === key
              const meta   = RISK_META[key] || {}
              const driverTitles = [...new Set((drivers || []).map(d => d.title).filter(Boolean))].slice(0, 4)

              return (
                <div key={key} className={`rounded-lg border ${rl.border} bg-slate-950 overflow-hidden`}>
                  <button
                    className="w-full px-3 py-2 hover:bg-slate-800/30 transition-colors text-left"
                    onClick={() => setExpanded(isOpen ? null : key)}>
                    <div className="flex items-center gap-2">
                      <span className={`w-8 text-center text-sm font-bold flex-none ${rl.text}`}>{s}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className="text-[11px] font-semibold text-slate-300">{label}</span>
                          <span className="text-[10px] text-slate-600">{meta.oneliner}</span>
                        </div>
                        <div className="h-1 rounded-full bg-slate-800">
                          <div className={`${rl.bar} h-1 rounded-full`} style={{ width: `${Math.min(s, 100)}%` }} />
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 flex-none">
                        <span className={`text-[10px] font-semibold px-1.5 py-px rounded ${rl.bg} ${rl.text}`}>{rl.label}</span>
                        <span className="text-[10px] text-slate-600">·{Math.round((meta.weight || 0) * 100)}%</span>
                        {isOpen ? <ChevronDown className="h-3 w-3 text-slate-600" /> : <ChevronRight className="h-3 w-3 text-slate-600" />}
                      </div>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-2.5 border-t border-slate-800 pt-2">
                      {driverTitles.length > 0 ? (
                        <ul className="space-y-1">
                          {driverTitles.map((title, i) => (
                            <li key={i} className="flex items-center gap-2 text-[11px] text-slate-300">
                              <span className={`h-1.5 w-1.5 rounded-full flex-none ${rl.bar}`} />
                              {title}
                            </li>
                          ))}
                        </ul>
                      ) : <p className="text-[11px] text-slate-600">No signals.</p>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Collapsible formula */}
          {cats.length > 0 && (
            <div className="mt-3">
              <button
                className="flex items-center gap-1.5 text-[10px] text-slate-500 hover:text-slate-400 transition-colors"
                onClick={() => setShowFormula(f => !f)}>
                {showFormula ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {showFormula ? 'Hide' : 'Show'} score formula
              </button>
              {showFormula && (
                <div className="mt-2 rounded-lg bg-slate-950 border border-slate-800 px-3 py-2 space-y-1">
                  {cats.map(({ key, label, score }) => {
                    const meta = RISK_META[key] || {}
                    const s    = Math.round(score ?? 0)
                    const rl   = riskLevel(s)
                    return (
                      <div key={key} className="flex items-center gap-2 text-[11px]">
                        <span className="text-slate-500 w-20 truncate">{label}</span>
                        <span className="text-slate-600">{s} × {Math.round((meta.weight || 0) * 100)}%</span>
                        <span className="text-slate-600">=</span>
                        <span className={`font-semibold ${rl.text}`}>{(s * (meta.weight || 0)).toFixed(1)} pts</span>
                      </div>
                    )
                  })}
                  <div className="border-t border-slate-800 pt-1 flex items-center gap-2 text-[11px]">
                    <span className="text-slate-400 w-20">Total</span>
                    <span className="text-slate-600">sum =</span>
                    <span className={`font-bold ${overallRl.text}`}>{overall} / 100</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Section>
  )
}

// ── 3. Critical Path — horizontal dependency flow ─────────────────────────────

function CriticalPathPanel({ deps, stalledItemIds = [] }) {
  const [selectedId, setSelectedId] = useState(null)

  const cpItems        = deps?.critical_path_details || []
  const cpDurationDays = deps?.critical_path_duration_days
  const cpGrowthPct    = deps?.critical_path_growth_percent
  const numPaths       = deps?.num_critical_paths ?? 1
  const growth         = cpGrowthPct != null ? Math.round(cpGrowthPct) : null
  const stalledSet     = new Set(stalledItemIds)

  if (!cpItems.length) {
    return (
      <Section label="Critical path" border="border-slate-700">
        <p className="text-sm text-slate-500">No dependency chain found — tasks may be running in parallel without dependencies.</p>
      </Section>
    )
  }

  const blockedCount   = cpItems.filter(i => i.is_blocked).length
  const stalledOnPath  = cpItems.filter(i => stalledSet.has(i.item_id)).length
  const selectedIdx    = selectedId ? cpItems.findIndex(i => i.item_id === selectedId) : -1
  const selectedItem   = selectedId ? cpItems.find(i => i.item_id === selectedId) : null
  const firstItem      = cpItems[0]
  const firstHasExternalPred = firstItem && (firstItem.depends_on_count ?? 0) > 0

  const isDone = (item) => {
    const s = (item.status || '').toUpperCase()
    return s === 'COMPLETED' || s === 'DONE'
  }

  const getNodeState = (item, idx) => {
    if (isDone(item))             return selectedId && item.item_id === selectedId ? 'selected' : 'completed'
    if (stalledSet.has(item.item_id)) return selectedId && item.item_id === selectedId ? 'selected' : 'stalled'
    if (!selectedId)              return item.is_blocked ? 'blocked' : 'default'
    if (item.item_id === selectedId) return 'selected'
    if (idx < selectedIdx)        return 'upstream'
    if (idx > selectedIdx)        return 'downstream'
    return 'default'
  }

  const nodeStyles = {
    default:    'border-slate-700 bg-slate-900 text-slate-200 hover:border-slate-500',
    selected:   'border-amber-400 bg-amber-400/10 text-amber-200 ring-1 ring-amber-400/40',
    upstream:   'border-teal-500/60 bg-teal-500/8 text-teal-200 hover:border-teal-400',
    downstream: 'border-sky-500/60 bg-sky-500/8 text-sky-200 hover:border-sky-400',
    blocked:    'border-rose-500/50 bg-rose-500/8 text-rose-200 hover:border-rose-400',
    stalled:    'border-amber-500/60 bg-amber-500/6 text-amber-200 hover:border-amber-400',
    completed:  'border-emerald-600/50 bg-emerald-900/20 text-slate-400 opacity-70 hover:opacity-90',
  }

  const arrowColor = (fromIdx) => {
    if (!selectedId) return 'text-slate-700'
    if (fromIdx < selectedIdx) return 'text-teal-600/60'
    if (fromIdx >= selectedIdx) return 'text-sky-600/60'
    return 'text-slate-700'
  }

  return (
    <Section label="Critical path" accent="text-amber-500" border="border-amber-500/20">

      {/* Header metrics */}
      <div className="flex items-center gap-4 mb-4 pb-3 border-b border-slate-800 flex-wrap">
        <div className="flex flex-col">
          <p className="text-[10px] text-slate-500 mb-0.5 uppercase tracking-wide">Chain length</p>
          <p className="text-xl font-bold text-amber-300">
            {cpDurationDays != null ? `${cpDurationDays.toFixed(1)} days` : '—'}
          </p>
        </div>
        <div className="w-px h-8 bg-slate-800 flex-none" />
        {growth != null && (
          <>
            <div className="flex flex-col">
              <p className="text-[10px] text-slate-500 mb-0.5 uppercase tracking-wide">Critical path growth</p>
              <p className={`text-xl font-bold ${growth > 10 ? 'text-rose-400' : growth > 0 ? 'text-amber-400' : 'text-teal-400'}`}>
                {growth > 0 ? `+${growth}%` : growth === 0 ? '0% — no change' : `${growth}%`}
              </p>
            </div>
            <div className="w-px h-8 bg-slate-800 flex-none" />
          </>
        )}
        {numPaths > 1 && (
          <>
            <div className="flex flex-col">
              <p className="text-[10px] text-slate-500 mb-0.5 uppercase tracking-wide">Parallel paths</p>
              <p className="text-xl font-bold text-sky-300">{numPaths}</p>
            </div>
            <div className="w-px h-8 bg-slate-800 flex-none" />
          </>
        )}
        {blockedCount > 0 && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30">
            <AlertTriangle className="h-3.5 w-3.5 text-rose-400 flex-none" />
            <span className="text-[11px] font-semibold text-rose-300">
              {blockedCount} blocked task{blockedCount !== 1 ? 's' : ''} on this chain
            </span>
          </div>
        )}
        {stalledOnPath > 0 && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <span className="text-[11px] font-semibold text-amber-300">
              ⏸ {stalledOnPath} stalled item{stalledOnPath !== 1 ? 's' : ''} on this chain
            </span>
          </div>
        )}
        {selectedId && (
          <button className="ml-auto text-[10px] text-slate-500 hover:text-slate-300 underline" onClick={() => setSelectedId(null)}>
            Clear selection
          </button>
        )}
      </div>

      {/* Upstream predecessor note — shown when the first chain item has dependencies outside the displayed chain */}
      {firstHasExternalPred && (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-teal-500/20 bg-teal-500/5 px-3 py-2">
          <span className="text-teal-400 text-[10px] mt-px">↑</span>
          <p className="text-[10px] text-teal-300 leading-relaxed">
            <span className="font-semibold">{firstItem.item_id}</span> has{' '}
            {firstItem.depends_on_count} predecessor{firstItem.depends_on_count !== 1 ? 's' : ''} not shown here
            {firstItem.depends_on_labels?.length > 0 && (
              <> ({firstItem.depends_on_labels.map((l, i) => (
                <span key={i} className="font-mono text-teal-400">{l}{i < firstItem.depends_on_labels.length - 1 ? ', ' : ''}</span>
              ))})</>
            )}.{' '}
            These were completed in earlier sprints and are not displayed in this chain.
          </p>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-3 mb-3 text-[10px] text-slate-400 flex-wrap">
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border border-emerald-600/50 bg-emerald-900/30 inline-block" /> Completed</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border border-amber-500/60 bg-amber-500/20 inline-block" /> Stalled</span>
        {selectedId && (
          <>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border border-teal-500/60 bg-teal-500/20 inline-block" /> Upstream</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border border-amber-400 bg-amber-400/20 inline-block" /> Selected</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border border-sky-500/60 bg-sky-500/20 inline-block" /> Downstream</span>
          </>
        )}
      </div>

      {/* Horizontal flow */}
      <div className="overflow-x-auto pb-2">
        <div className="inline-flex items-center gap-0 min-w-max">

          {/* Ghost node — shown when first item has upstream predecessors outside this chain */}
          {firstHasExternalPred && (
            <div className="inline-flex items-center">
              <div className="rounded-lg border border-dashed border-teal-600/40 bg-teal-900/10 px-3 py-2.5 min-w-[80px] max-w-[110px] opacity-60">
                <p className="text-[9px] font-mono text-teal-600 mb-0.5">predecessors</p>
                <p className="text-[10px] text-teal-500 leading-tight">
                  {firstItem.depends_on_count} upstream
                </p>
                <p className="text-[9px] text-teal-700">earlier sprints</p>
              </div>
              <div className="flex items-center px-1.5 text-teal-700/50">
                <svg width="28" height="16" viewBox="0 0 28 16" fill="none">
                  <line x1="0" y1="8" x2="20" y2="8" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
                  <polyline points="14,3 20,8 14,13" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            </div>
          )}

          {cpItems.map((item, idx) => {
            const isLast     = idx === cpItems.length - 1
            const nodeState  = getNodeState(item, idx)
            const isSelected = item.item_id === selectedId
            const isStalled  = stalledSet.has(item.item_id)

            return (
              <div key={item.item_id} className="inline-flex items-center">
                <button
                  onClick={() => setSelectedId(isSelected ? null : item.item_id)}
                  className={`relative rounded-lg border px-3 py-2.5 text-left transition-all cursor-pointer min-w-[100px] max-w-[140px] ${nodeStyles[nodeState]}`}>
                  {isDone(item) && (
                    <span className="absolute top-1.5 right-1.5 text-emerald-400 text-[10px]" title="Completed">✓</span>
                  )}
                  {isStalled && !isDone(item) && (
                    <span className="absolute top-1.5 right-1.5 text-amber-400 text-[9px]" title="Cannot start yet — pending predecessor or past its scheduled start">⏸</span>
                  )}
                  <p className={`text-[10px] font-mono mb-0.5 ${isDone(item) ? 'text-emerald-600' : 'text-slate-500'}`}>{item.item_id}</p>
                  <p className={`text-[11px] font-semibold leading-tight line-clamp-2 ${isDone(item) ? 'line-through text-slate-500' : ''}`}>{item.name}</p>
                  <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                    {isDone(item) ? (
                      <span className="text-[9px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 rounded px-1 py-px font-bold">DONE</span>
                    ) : (
                      <>
                        {item.is_blocked && (
                          <span className="text-[9px] bg-rose-500/20 text-rose-300 border border-rose-500/40 rounded px-1 py-px font-bold">BLK</span>
                        )}
                        {isStalled && (
                          <span className="text-[9px] bg-amber-500/15 text-amber-300 border border-amber-500/30 rounded px-1 py-px font-bold">STALLED</span>
                        )}
                        <span className="text-[10px] text-slate-500">{(item.remaining_hours ?? 0).toFixed(0)}h</span>
                      </>
                    )}
                  </div>
                </button>

                {!isLast && (
                  <div className={`flex items-center px-1.5 ${arrowColor(idx)}`}>
                    <svg width="28" height="16" viewBox="0 0 28 16" fill="none">
                      <line x1="0" y1="8" x2="20" y2="8" stroke="currentColor" strokeWidth="1.5" />
                      <polyline points="14,3 20,8 14,13" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Parallel paths note */}
      {numPaths > 1 && (
        <p className="mt-2 text-[10px] text-slate-500 leading-relaxed">
          {numPaths} chains of the same length exist — only one is shown. A delay on any of them affects the end date equally.
        </p>
      )}

      {/* Selected node detail */}
      {selectedItem && (
        <SelectedNodeDetail item={selectedItem} />
      )}
    </Section>
  )
}

function SelectedNodeDetail({ item }) {
  // depends_on_labels and blocking_labels come from backend (FIX bug-1/bug-2 already in route)
  // depends_on_count = in-degree from full DAG, blocking_count = out-degree from full DAG
  // We show the actual label lists when available, else fall back to counts
  const upstreamLabels   = item.depends_on_labels   || []
  const downstreamLabels = item.blocking_labels      || []
  const upstreamCount    = item.depends_on_count     ?? upstreamLabels.length
  const downstreamCount  = item.blocking_count       ?? downstreamLabels.length

  return (
    <div className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-[10px] font-mono text-slate-500">{item.item_id}</span>
          <p className="text-[13px] font-semibold text-amber-200">{item.name}</p>
        </div>
        <StatusPill status={item.status} />
      </div>

      {/* 4-col stat grid */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { icon: User,      label: 'Owner',      value: item.assigned_resource || '—' },
          { icon: Zap,       label: 'Hours left',  value: `${(item.remaining_hours ?? 0).toFixed(0)} h` },
          { icon: Clock,     label: 'Sprint',      value: item.sprint_id || '—' },
          { icon: GitBranch, label: 'Gates',       value: `${downstreamCount} task${downstreamCount !== 1 ? 's' : ''}` },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded bg-slate-900 border border-slate-800 px-2 py-1.5">
            <p className="text-[9px] text-slate-500 uppercase mb-0.5 flex items-center gap-1">
              <Icon className="h-2.5 w-2.5" /> {label}
            </p>
            <p className="text-[11px] font-semibold text-white truncate">{value}</p>
          </div>
        ))}
      </div>

      {/* Dependency connections — only shown when data exists */}
      {(upstreamCount > 0 || downstreamCount > 0) && (
        <div className="rounded bg-slate-900 border border-slate-800 px-2.5 py-2 space-y-1.5">
          {upstreamCount > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 mb-0.5">
                Waits on <span className="font-semibold text-teal-300">{upstreamCount} upstream task{upstreamCount !== 1 ? 's' : ''}</span>
              </p>
              {upstreamLabels.length > 0 && (
                <ul className="space-y-0.5">
                  {upstreamLabels.map((lbl, i) => (
                    <li key={i} className="text-[10px] text-teal-400 font-mono truncate pl-2 border-l border-teal-500/30">{lbl}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {downstreamCount > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 mb-0.5">
                Gates <span className="font-semibold text-sky-300">{downstreamCount} downstream task{downstreamCount !== 1 ? 's' : ''}</span>
              </p>
              {downstreamLabels.length > 0 && (
                <ul className="space-y-0.5">
                  {downstreamLabels.map((lbl, i) => (
                    <li key={i} className="text-[10px] text-sky-400 font-mono truncate pl-2 border-l border-sky-500/30">{lbl}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      <div className={`rounded px-2.5 py-2 text-[11px] font-medium ${
        item.is_blocked
          ? 'bg-rose-500/10 border border-rose-500/30 text-rose-300'
          : 'bg-amber-500/8 border border-amber-500/20 text-amber-300'
      }`}>
        {item.is_blocked
          ? '⚠ Blocked — work cannot proceed until the blocker is resolved.'
          : '⚠ Any delay to this task delays the project completion.'}
      </div>
    </div>
  )
}

// ── 4. High-Risk Items ────────────────────────────────────────────────────────
// Backend provides: item_id, name, risk_score, status, assigned_resource,
// remaining_hours, float_hours, blocking_count, cascade_depth, risk_drivers, is_blocked, is_on_critical_path
// No schedule_impact_days — derive impact from float_hours + blocking_count + cascade_depth

function HighRiskItemsPanel({ deps }) {
  const [expanded, setExpanded] = useState(null)
  const items = deps?.high_risk_item_details || []
  if (!items.length) return null

  return (
    <Section label={`At-risk items · ${items.length}`} accent="text-rose-400" border="border-rose-500/25">
      <div className="space-y-2">
        {items.map((item) => {
          const isOpen  = expanded === item.item_id
          const riskPct = Math.min(item.risk_score ?? 0, 100)
          const rl      = riskLevel(riskPct)

          // Why bullets — directly from backend risk_drivers
          const whyBullets = item.risk_drivers || []

          // Impact: derive from what we actually have
          // float_hours=0 → zero float (cannot slip at all)
          // blocking_count → fan-out risk
          // cascade_depth → downstream chain length
          const impactLines = []
          if (item.float_hours === 0) {
            impactLines.push('Zero float — any delay directly extends project end date')
          } else if (item.float_hours != null && item.float_hours < 8) {
            impactLines.push(`Only ${item.float_hours.toFixed(0)}h of scheduling buffer remaining`)
          }
          if ((item.blocking_count ?? 0) >= 3) {
            impactLines.push(`Blocks ${item.blocking_count} downstream tasks if it slips`)
          } else if ((item.blocking_count ?? 0) > 0) {
            impactLines.push(`Delays ${item.blocking_count} downstream task${item.blocking_count !== 1 ? 's' : ''}`)
          }
          if ((item.cascade_depth ?? 0) >= 2) {
            impactLines.push(`Triggers a ${item.cascade_depth}-level dependency cascade`)
          }

          return (
            <div key={item.item_id} className={`rounded-lg border ${rl.border} bg-slate-950 overflow-hidden`}>
              {/* Collapsed row */}
              <button
                className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-800/30 transition-colors"
                onClick={() => setExpanded(isOpen ? null : item.item_id)}>
                <span className={`text-[10px] font-mono font-bold flex-none ${rl.text}`}>{item.item_id}</span>
                <span className="flex-1 text-[12px] text-slate-200 font-medium truncate">{item.name}</span>
                <div className="flex items-center gap-1.5 flex-none">
                  {item.is_blocked && (
                    <span className="text-[10px] text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded px-1.5 py-px font-semibold">Blocked</span>
                  )}
                  {item.is_on_critical_path && (
                    <span className="text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-1.5 py-px font-semibold">Critical path</span>
                  )}
                  <span className={`text-[10px] font-semibold px-1.5 py-px rounded border ${rl.border} ${rl.bg} ${rl.text}`}>{rl.label} Risk</span>
                  {isOpen ? <ChevronDown className="h-3 w-3 text-slate-600" /> : <ChevronRight className="h-3 w-3 text-slate-600" />}
                </div>
              </button>

              {/* Expanded detail */}
              {isOpen && (
                <div className="px-3 pb-3 border-t border-slate-800 pt-2.5 space-y-2">
                  {/* Stat row */}
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { icon: Clock,     label: 'Remaining', value: `${(item.remaining_hours ?? 0).toFixed(0)} h` },
                      { icon: User,      label: 'Owner',     value: item.assigned_resource || '—' },
                      { icon: GitBranch, label: 'Gates',     value: (item.blocking_count ?? 0) > 0 ? `${item.blocking_count} task${item.blocking_count !== 1 ? 's' : ''}` : 'None' },
                    ].map(({ icon: Icon, label, value }) => (
                      <div key={label} className="rounded bg-slate-900 border border-slate-800 px-2 py-1.5">
                        <div className="flex items-center gap-1 mb-0.5">
                          <Icon className="h-2.5 w-2.5 text-slate-600" />
                          <span className="text-[9px] text-slate-600 uppercase tracking-wide">{label}</span>
                        </div>
                        <p className="text-[11px] font-semibold text-white truncate">{value}</p>
                      </div>
                    ))}
                  </div>

                  {/* Why? — only render if backend gave us drivers */}
                  {whyBullets.length > 0 && (
                    <div className={`rounded-lg border ${rl.border} ${rl.bg} px-3 py-2`}>
                      <p className={`text-[10px] font-semibold uppercase tracking-wide mb-1.5 ${rl.text}`}>Why?</p>
                      <ul className="space-y-1">
                        {whyBullets.map((d, i) => (
                          <li key={i} className="flex items-start gap-2 text-[11px] text-slate-300">
                            <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-none ${rl.bar}`} />
                            {d}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Impact — only render if we could derive something meaningful */}
                  {impactLines.length > 0 && (
                    <div className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Impact</p>
                      <ul className="space-y-0.5">
                        {impactLines.map((line, i) => (
                          <li key={i} className={`text-[12px] font-semibold ${rl.text}`}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </Section>
  )
}

// ── PMO KPI Suite ─────────────────────────────────────────────────────────────

function spiColor(spi) {
  if (spi == null) return 'text-slate-400'
  if (spi >= 0.95) return 'text-teal-300'
  if (spi >= 0.80) return 'text-amber-300'
  return 'text-rose-300'
}

function spiLabel(spi) {
  if (spi == null) return '—'
  if (spi >= 0.95) return 'On pace'
  if (spi >= 0.80) return 'Slightly behind'
  return 'Behind plan'
}

function pct(v, decimals = 0) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(decimals)}%`
}

function confBar(score, label, color) {
  const w = Math.round((score ?? 0) * 100)
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 text-[10px] text-slate-400 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-slate-700">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${w}%` }} />
      </div>
      <span className="w-8 text-right text-[10px] font-semibold text-slate-300">{w}%</span>
    </div>
  )
}

function PMOKpiPanel({ sessionId, onStalledIds }) {
  const [kpi, setKpi]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState(null)

  useEffect(() => {
    if (!sessionId) { setLoading(false); return }
    api.forecast(sessionId)
      .then(f => {
        const suite = f?.pmo_kpi ?? null
        setKpi(suite)
        setLoading(false)
        if (onStalledIds && Array.isArray(suite?.critical_path_floored_item_ids)) {
          onStalledIds(suite.critical_path_floored_item_ids)
        }
      })
      .catch(err => { setError(err); setLoading(false) })
  }, [sessionId])

  if (loading) return (
    <Section label="PMO health indicators" accent="text-indigo-400" border="border-indigo-500/20">
      <p className="text-sm text-slate-500">Computing PMO KPIs…</p>
    </Section>
  )

  if (error || !kpi) return (
    <Section label="PMO health indicators" accent="text-indigo-400" border="border-indigo-500/20">
      <p className="text-sm text-slate-500">{error?.message || 'PMO KPIs unavailable for this session.'}</p>
    </Section>
  )

  const spi = kpi.schedule_performance_index
  const cd  = kpi.confidence_decomposition || {}

  return (
    <Section label="PMO health indicators" accent="text-indigo-400" border="border-indigo-500/20">
      {/* Legend / definition row */}
      <div className="mb-3 rounded-lg border border-indigo-500/15 bg-indigo-500/5 px-3 py-2 text-[10px] text-slate-400 leading-relaxed">
        Green = on track · Amber = monitor closely · Red = action required
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">

        {/* SPI */}
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500 mb-1">Schedule Pace</p>
          <p className={`text-2xl font-bold ${spiColor(spi)}`}>{spi != null ? spi.toFixed(2) : '—'}</p>
          <p className={`text-[10px] mt-0.5 ${spiColor(spi)}`}>{spiLabel(spi)}</p>
          <p className="text-[9px] text-slate-500 mt-1">
            {pct(kpi.actual_completion_pct)} done · {pct(kpi.planned_completion_pct)} planned
          </p>
          <p className="text-[9px] text-slate-600 mt-1">
            by effort hours
          </p>
          <p className="text-[9px] text-slate-600 mt-1 leading-tight">
            Below 1.0 indicates the team is behind its planned pace as of today.
          </p>
        </div>

        {/* Sprint adherence */}
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500 mb-1">Sprint Adherence</p>
          <p className={`text-2xl font-bold ${kpi.sprint_adherence_index >= 0.8 ? 'text-teal-300' : kpi.sprint_adherence_index >= 0.6 ? 'text-amber-300' : 'text-rose-300'}`}>
            {pct(kpi.sprint_adherence_index)}
          </p>
          <p className="text-[9px] text-slate-500 mt-1.5">
            {kpi.sprints_on_time_count}/{kpi.sprints_due_count} sprints closed on time
          </p>
          <p className="text-[9px] text-slate-500">
            Sprint close quality: {pct(kpi.milestone_adherence_score)}
          </p>
        </div>

        {/* Release readiness */}
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500 mb-1">Release Readiness</p>
          <p className={`text-2xl font-bold ${kpi.release_readiness_index >= 0.8 ? 'text-teal-300' : kpi.release_readiness_index >= 0.5 ? 'text-amber-300' : 'text-rose-300'}`}>
            {pct(kpi.release_readiness_index)}
          </p>
          <p className="text-[9px] text-slate-500 mt-1.5">
            {kpi.resolved_blocker_count} resolved · {kpi.open_blocker_count} open blockers
          </p>
          <p className="text-[9px] text-slate-600 mt-1 leading-tight">
            100% indicates no active blockers are preventing release.
          </p>
        </div>

        {/* Recovery feasibility */}
        <div className={`rounded-lg border bg-slate-800/60 px-3 py-2.5 ${kpi.recovery_feasible ? 'border-teal-500/30' : 'border-rose-500/40'}`}>
          <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500 mb-1">Recovery Feasible</p>
          <p className={`text-2xl font-bold ${kpi.recovery_feasible ? 'text-teal-300' : 'text-rose-300'}`}>
            {kpi.recovery_feasible ? 'Yes' : 'No'}
          </p>
          <p className={`text-[10px] mt-0.5 ${kpi.recovery_feasible ? 'text-teal-400' : 'text-rose-400'}`}>
            {kpi.recovery_feasibility_margin_days >= 0
              ? `${kpi.recovery_feasibility_margin_days.toFixed(1)}d spare at max pace`
              : `${Math.abs(kpi.recovery_feasibility_margin_days).toFixed(1)}d shortfall even at max pace`}
          </p>
          {kpi.max_sustainable_velocity != null && (
            <p className="text-[9px] text-slate-500 mt-1">
              Max sustainable: {kpi.max_sustainable_velocity.toFixed(0)}h/sprint
            </p>
          )}
          <p className="text-[9px] text-slate-600 mt-1 leading-tight">
            "No" means scope reduction or additional resources are required — resolving blockers alone will not be sufficient.
          </p>
        </div>
      </div>

      {/* Critical path drift + dependency pressure */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500 mb-2">Critical Path Drift</p>
          <div className="flex gap-4 flex-wrap">
            <div>
              <p className={`text-lg font-bold ${kpi.critical_path_drift_days > 0 ? 'text-rose-300' : 'text-teal-300'}`}>
                {kpi.critical_path_drift_days > 0 ? `+${kpi.critical_path_drift_days.toFixed(1)}d` : `${kpi.critical_path_drift_days.toFixed(1)}d`}
              </p>
              <p className="text-[9px] text-slate-500">calendar shift</p>
              <p className="text-[9px] text-slate-600 leading-tight mt-0.5">days the end date slipped due to stuck tasks</p>
            </div>
            <div>
              <p className={`text-lg font-bold ${kpi.critical_path_scope_growth_percent > 0 ? 'text-amber-300' : 'text-teal-300'}`}>
                {kpi.critical_path_scope_growth_percent > 0 ? `+${kpi.critical_path_scope_growth_percent.toFixed(1)}%` : `${kpi.critical_path_scope_growth_percent.toFixed(1)}%`}
              </p>
              <p className="text-[9px] text-slate-500">critical path growth</p>
              <p className="text-[9px] text-slate-600 leading-tight mt-0.5">How much longer the critical dependency chain has grown vs. original estimates.</p>
            </div>
            <div>
              <p className={`text-lg font-bold ${kpi.critical_path_floored_item_count > 0 ? 'text-amber-300' : 'text-teal-300'}`}>
                {kpi.critical_path_floored_item_count}
              </p>
              <p className="text-[9px] text-slate-500">stalled on path</p>
              <p className="text-[9px] text-slate-600 leading-tight mt-0.5">critical chain tasks that cannot start yet</p>
            </div>
          </div>

          {/* Stalled item IDs — only those on the critical path */}
          {Array.isArray(kpi.critical_path_floored_item_ids) && kpi.critical_path_floored_item_ids.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1 items-center">
              <span className="text-[9px] text-slate-500 mr-1">On path, stalled:</span>
              {kpi.critical_path_floored_item_ids.map(id => (
                <span key={id} className="text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300">{id}</span>
              ))}
            </div>
          )}

          {/* Network-wide stalled tasks outside the critical chain */}
          {(kpi.network_stalled_item_count ?? 0) > (kpi.critical_path_floored_item_count ?? 0) && (
            <p className="mt-1.5 text-[9px] text-slate-500">
              +{kpi.network_stalled_item_count - kpi.critical_path_floored_item_count} additional tasks are stalled but not on the critical chain — the end date is unaffected by those.
            </p>
          )}

          {kpi.dependency_pressure_item_count > 0 && (
            <p className="mt-2 text-[10px] text-rose-300">
              ⚠ {kpi.dependency_pressure_item_count} downstream task{kpi.dependency_pressure_item_count !== 1 ? 's' : ''} are waiting on a stalled predecessor
              ({kpi.dependency_pressure_hours.toFixed(0)}h at risk)
            </p>
          )}
        </div>

        {/* Calendar variance */}
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500 mb-2">Calendar Variance</p>
          <p className={`text-lg font-bold ${Math.abs(kpi.calendar_variance_days) > 7 ? 'text-rose-300' : Math.abs(kpi.calendar_variance_days) > 2 ? 'text-amber-300' : 'text-teal-300'}`}>
            {kpi.calendar_variance_days > 0 ? `+${kpi.calendar_variance_days.toFixed(1)}d` : `${kpi.calendar_variance_days.toFixed(1)}d`}
          </p>
          <p className="text-[9px] text-slate-500 mt-0.5 leading-relaxed">
            {Math.abs(kpi.calendar_variance_days) > 7
              ? 'Sprint statuses are significantly out of date — overdue sprints should be closed.'
              : Math.abs(kpi.calendar_variance_days) > 2
                ? 'Minor mismatch — review any in-progress sprints that may have overrun.'
                : 'Sprint statuses are aligned with the real calendar.'}
          </p>
        </div>
      </div>

      {/* Sprint Drift Ledger — Gap 3 */}
      {Array.isArray(kpi.sprint_drift_ledger) && kpi.sprint_drift_ledger.length > 0 && (() => {
        const ledger = kpi.sprint_drift_ledger
        const hasAnyDrift = ledger.some(r => r.drift_days > 0)
        const totalDrift = kpi.cumulative_drift_days ?? 0
        return (
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-3 mb-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500">Sprint Schedule Drift Ledger</p>
              {totalDrift > 0 ? (
                <span className="text-[10px] font-semibold text-rose-300 bg-rose-500/10 border border-rose-500/25 rounded px-2 py-0.5">
                  {totalDrift.toFixed(1)}d total accumulated drift
                </span>
              ) : (
                <span className="text-[10px] font-semibold text-teal-300 bg-teal-500/10 border border-teal-500/25 rounded px-2 py-0.5">
                  No accumulated drift
                </span>
              )}
            </div>
            <p className="text-[9px] text-slate-600 mb-3 leading-relaxed">
              Each row represents one sprint. Red entries indicate the sprint ran past its planned end date — that overrun adds directly to the project end date.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px] border-collapse">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700">
                    <th className="text-left py-1.5 pr-3 font-semibold uppercase tracking-wide">Sprint</th>
                    <th className="text-left py-1.5 pr-3 font-semibold uppercase tracking-wide">Planned End</th>
                    <th className="text-left py-1.5 pr-3 font-semibold uppercase tracking-wide">Status</th>
                    <th className="text-right py-1.5 font-semibold uppercase tracking-wide">Drift</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.map((row, i) => {
                    const drift = row.drift_days ?? 0
                    const isPastDue = row.past_due
                    const isCompleted = (row.status || '').toUpperCase() === 'COMPLETED'
                    const rowClass = drift > 0
                      ? 'border-b border-rose-500/10 bg-rose-500/5'
                      : isCompleted && isPastDue
                        ? 'border-b border-teal-500/10 bg-teal-500/5'
                        : 'border-b border-slate-800'
                    const driftColor = drift > 5 ? 'text-rose-300 font-bold' : drift > 0 ? 'text-amber-300 font-semibold' : 'text-teal-400'
                    const statusColor = isCompleted ? 'text-teal-400' : isPastDue ? 'text-rose-400' : 'text-slate-400'
                    return (
                      <tr key={i} className={rowClass}>
                        <td className="py-1.5 pr-3 text-slate-200 font-medium">{row.sprint_name}</td>
                        <td className="py-1.5 pr-3 text-slate-400 font-mono">{row.planned_end}</td>
                        <td className={`py-1.5 pr-3 ${statusColor}`}>
                          {isCompleted ? '✓ Closed' : isPastDue ? '⚠ Still open' : '◌ Future'}
                        </td>
                        <td className={`py-1.5 text-right ${driftColor}`}>
                          {drift > 0 ? `+${drift.toFixed(1)}d` : isCompleted ? '✓' : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                {totalDrift > 0 && (
                  <tfoot>
                    <tr className="border-t-2 border-slate-600">
                      <td colSpan={3} className="py-1.5 pr-3 text-slate-400 font-semibold">Accumulated schedule debt</td>
                      <td className="py-1.5 text-right text-rose-300 font-bold">+{totalDrift.toFixed(1)}d</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>
        )
      })()}

      {/* Forecast confidence decomposition */}
      {cd && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-2.5">
          <div className="flex items-center justify-between mb-1">
            <p className="text-[9px] font-semibold uppercase tracking-[0.22em] text-slate-500">Forecast Confidence Breakdown</p>
            {cd.weakest_component && (
              <span className="text-[9px] bg-amber-500/15 text-amber-300 border border-amber-500/30 rounded px-1.5 py-px">
                Weakest: {cd.weakest_component.replace('_confidence', '')}
              </span>
            )}
          </div>
          <p className="text-[9px] text-slate-600 mb-2 leading-relaxed">
            A shorter bar indicates that signal is reducing forecast reliability.
          </p>
          <div className="space-y-1.5">
            <div>
              {confBar(cd.effort_confidence, 'Effort', 'bg-indigo-400')}
              <p className="text-[9px] text-slate-600 pl-0.5 mt-0.5">Reduces when estimates have changed significantly — frequent re-estimation makes forecasts less reliable.</p>
            </div>
            <div>
              {confBar(cd.velocity_confidence, 'Velocity', 'bg-blue-400')}
              <p className="text-[9px] text-slate-600 pl-0.5 mt-0.5">Reduces when the team's throughput varies significantly between sprints — consistent delivery is easier to forecast.</p>
            </div>
            <div>
              {confBar(cd.calendar_confidence, 'Calendar', 'bg-violet-400')}
              <p className="text-[9px] text-slate-600 pl-0.5 mt-0.5">Reduces when sprint statuses are not kept current — stale tracking data degrades the accuracy of all schedule calculations.</p>
            </div>
          </div>
        </div>
      )}
    </Section>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

// ── Forecast Trend Panel ──────────────────────────────────────────────────────
// Shows how P50 / P80 / P95 dates have moved across sessions.
// Each entry = one analysis build (upload, scope change, recovery plan apply).

function DeltaChip({ days, invert = false }) {
  if (days == null) return null
  const better = invert ? days > 0 : days < 0
  const neutral = days === 0
  const label = days === 0 ? '—' : `${days > 0 ? '+' : ''}${days}d`
  const cls = neutral
    ? 'bg-slate-700 text-slate-400'
    : better
      ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
      : 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
  const arrow = neutral ? '' : better ? ' ↓' : ' ↑'
  return (
    <span className={`inline-flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded ${cls}`}>
      {label}{arrow}
    </span>
  )
}

function SparkLine({ entries, field, color }) {
  if (!entries || entries.length < 2) return null

  const vals = entries.map(e => {
    const raw = e[field]
    if (!raw) return null
    return new Date(raw).getTime()
  })
  if (vals.some(v => v === null)) return null

  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1

  const W = 120, H = 28, PAD = 3
  const pts = vals.map((v, i) => {
    const x = PAD + (i / (vals.length - 1)) * (W - PAD * 2)
    // Later date = worse = higher on chart (inverted Y: good = bottom)
    const y = PAD + ((v - min) / range) * (H - PAD * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const lastBetter = vals[vals.length - 1] < vals[0]

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={lastBetter ? '#10b981' : '#f43f5e'}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {vals.map((v, i) => (
        <circle
          key={i}
          cx={parseFloat(pts[i].split(',')[0])}
          cy={parseFloat(pts[i].split(',')[1])}
          r="2"
          fill={i === vals.length - 1 ? (lastBetter ? '#10b981' : '#f43f5e') : '#475569'}
        />
      ))}
    </svg>
  )
}

function TrendPanel({ sessionId }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    if (!sessionId) { setLoading(false); return }
    api.forecastTrend(sessionId)
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e); setLoading(false) })
  }, [sessionId])

  if (loading) return (
    <Section label="Forecast trend" border="border-slate-700">
      <p className="text-sm text-slate-500">Loading trend data…</p>
    </Section>
  )

  if (error || !data || data.entry_count === 0) return (
    <Section label="Forecast trend" border="border-slate-700">
      <p className="text-[11px] text-slate-500">
        No trend data yet. Upload the updated workbook after each sprint close
        to start tracking sprint-over-sprint movement.
      </p>
    </Section>
  )

  const entries = data.entries
  const latest  = entries[entries.length - 1]
  const first   = entries[0]

  // Overall movement: how much did P80 shift from first entry to now
  const overallP80Delta = latest.p80_date && first.p80_date
    ? Math.round((new Date(latest.p80_date) - new Date(first.p80_date)) / 86400000)
    : null

  const fmtDate = iso => {
    if (!iso) return '—'
    const d = new Date(iso)
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' })
  }

  return (
    <Section label="Forecast trend" accent="text-sky-400" border="border-sky-500/20">

      {/* Summary headline */}
      <div className="flex items-start gap-4 mb-4 pb-3 border-b border-slate-800 flex-wrap">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">
            Movement across runs (one run per sprint close)
          </p>
          <div className="flex items-center gap-2">
            {overallP80Delta != null && (
              <span className={`text-xl font-bold ${overallP80Delta < 0 ? 'text-emerald-300' : overallP80Delta > 0 ? 'text-rose-300' : 'text-slate-300'}`}>
                {overallP80Delta === 0 ? 'No change' : `${overallP80Delta > 0 ? '+' : ''}${overallP80Delta}d`}
              </span>
            )}
            <span className="text-[11px] text-slate-500">on P80 (high-confidence date)</span>
          </div>
          <p className="text-[10px] text-slate-600 mt-0.5">
            {overallP80Delta == null ? '—'
              : overallP80Delta < 0 ? 'The high-confidence finish date has moved earlier — trajectory is improving.'
              : overallP80Delta > 0 ? 'The high-confidence finish date has moved later — situation is deteriorating.'
              : 'No change in the high-confidence finish date across recorded entries.'}
          </p>
        </div>

        <div className="ml-auto flex flex-col items-end gap-1">
          <p className="text-[10px] text-slate-500 uppercase tracking-wide">P80 over time</p>
          <SparkLine entries={entries} field="p80_date" color="amber" />
          <p className="text-[9px] text-slate-600">
            {entries.length} sprint run{entries.length !== 1 ? 's' : ''}
            {' · '}lower = earlier finish
          </p>
        </div>
      </div>

      {/* Date movement table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] uppercase tracking-wide text-slate-500 border-b border-slate-800">
              <th className="py-1.5 pr-3 text-left font-medium">Sprint run</th>
              <th className="py-1.5 px-3 text-right font-medium">Likely finish (P50)</th>
              <th className="py-1.5 px-3 text-right font-medium">High-conf (P80)</th>
              <th className="py-1.5 px-3 text-right font-medium">Ceiling (P95)</th>
              <th className="py-1.5 px-3 text-right font-medium">On-time</th>
              <th className="py-1.5 pl-3 text-right font-medium">vs. Target</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {entries.map((e, i) => {
              const isLatest = i === entries.length - 1
              return (
                <tr key={i} className={isLatest ? 'bg-sky-500/5' : ''}>
                  <td className="py-2 pr-3">
                    <p className={`font-medium ${isLatest ? 'text-sky-300' : 'text-slate-300'}`}>
                      {isLatest ? `${e.label} (current)` : e.label}
                    </p>
                    {e.completed_sprints != null && (
                      <p className="text-[9px] text-slate-500">
                        {e.completed_sprints} sprint{e.completed_sprints !== 1 ? 's' : ''} closed
                      </p>
                    )}
                    <p className="text-[9px] text-slate-600">
                      {new Date(e.recorded_at).toLocaleDateString('en-GB', {
                        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
                      })}
                    </p>
                  </td>
                  <td className="py-2 px-3 text-right">
                    <p className="text-slate-300">{fmtDate(e.p50_date)}</p>
                    {e.p50_delta_days != null && (
                      <div className="flex justify-end mt-0.5">
                        <DeltaChip days={e.p50_delta_days} />
                      </div>
                    )}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <p className={isLatest ? 'text-amber-300 font-semibold' : 'text-slate-300'}>
                      {fmtDate(e.p80_date)}
                    </p>
                    {e.p80_delta_days != null && (
                      <div className="flex justify-end mt-0.5">
                        <DeltaChip days={e.p80_delta_days} />
                      </div>
                    )}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <p className="text-slate-400">{fmtDate(e.p95_date)}</p>
                  </td>
                  <td className="py-2 px-3 text-right">
                    <p className={`font-semibold ${
                      (e.on_time_probability || 0) >= 0.6 ? 'text-emerald-300'
                      : (e.on_time_probability || 0) >= 0.4 ? 'text-amber-300'
                      : 'text-rose-300'
                    }`}>
                      {e.on_time_probability != null
                        ? `${Math.round(e.on_time_probability)}%`
                        : '—'}
                    </p>
                    {e.on_time_delta != null && e.on_time_delta !== 0 && (
                      <div className="flex justify-end mt-0.5">
                        <span className={`inline-flex items-center text-[9px] font-semibold px-1.5 py-0.5 rounded ${
                          e.on_time_delta > 0
                            ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                            : 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
                        }`}>
                          {e.on_time_delta > 0 ? '+' : ''}{Math.round(e.on_time_delta)}pp
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="py-2 pl-3 text-right">
                    <p className={`${(e.expected_delay_days || 0) > 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
                      {e.expected_delay_days != null
                        ? formatScheduleVariance(e.expected_delay_days)
                        : '—'}
                    </p>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[9px] text-slate-600 leading-relaxed">
        Each row corresponds to one tool run — typically one per sprint close.
        Upload the updated workbook after each sprint to populate the next row.
        Delta chips show movement vs the previous run — green = improving, red = deteriorating.
      </p>
    </Section>
  )
}


export function ManagementSummary({ session }) {
  const sessionId = session?.project_summary?.session_id || ''
  const [deps, setDeps]               = useState(null)
  const [depsLoading, setDepsLoading] = useState(true)
  const [depsError, setDepsError]     = useState(null)
  const [stalledIds, setStalledIds]   = useState([])

  const fetchDeps = useCallback(() => {
    if (!sessionId) {
      setDepsError(new Error('No session ID — upload a workbook first.'))
      setDepsLoading(false)
      return
    }
    setDepsLoading(true)
    setDepsError(null)
    api.dependencies(sessionId)
      .then(d => { setDeps(d); setDepsLoading(false) })
      .catch(err => { setDepsError(err); setDepsLoading(false) })
  }, [sessionId])

  useEffect(() => { fetchDeps() }, [fetchDeps])

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between px-0.5">
        <div>
          <p className="text-[10px] uppercase tracking-[0.28em] text-amber-400 mb-0.5">Delivery intelligence</p>
          <h2 className="text-2xl font-bold text-white">Delivery outlook</h2>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-3">
        <div className="xl:col-span-3"><FinishDateWindow sessionId={sessionId} /></div>
        <div className="xl:col-span-2"><RiskConcentration sessionId={sessionId} /></div>
      </div>

      <TrendPanel sessionId={sessionId} />

      {depsLoading ? (
        <div className="rounded-xl border border-amber-500/20 bg-slate-900 p-5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-amber-500 mb-2">Critical path</p>
          <p className="text-sm text-slate-500">Loading dependency graph…</p>
        </div>
      ) : depsError ? (
        <div className="rounded-xl border border-rose-500/30 bg-slate-900 p-5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-rose-400 mb-1">Critical path</p>
          <p className="text-sm text-rose-300 mb-2">{depsError.message || 'Failed to load dependency data.'}</p>
          <button onClick={fetchDeps} className="text-[11px] font-semibold text-rose-300 border border-rose-500/40 rounded px-2.5 py-1 hover:bg-rose-500/10 transition-colors">
            Retry
          </button>
        </div>
      ) : (
        <CriticalPathPanel deps={deps} stalledItemIds={stalledIds} />
      )}

      {!depsLoading && !depsError && <HighRiskItemsPanel deps={deps} />}

      <PMOKpiPanel sessionId={sessionId} onStalledIds={setStalledIds} />
    </div>
  )
}
