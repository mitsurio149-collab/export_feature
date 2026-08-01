import React, {useState, useEffect} from 'react'
import { AlertTriangle, CheckCircle2, Clock3, Users, ShieldAlert } from 'lucide-react'
import { api } from '../api/client'
import { formatScheduleVariance } from '../api/formatters'
import RecoveryPlansPage from './components/RecoveryPlans'
import RecommendationsPage from './components/Recommendations'
import { ReasoningTrace } from './components/ReasoningTrace'
import { SprintHealth } from './components/SprintHealth'
import { ManagementSummary } from './ManagementSummary'
import PMIntelligencePanel from './components/PMIntelligencePanel'
import { ExportPage } from './Export'

const tabs = [
  { key: 'overview',              label: 'Overview' },
  { key: 'recommendations',       label: '🎯 Recommendations' },
  { key: 'recovery-plans',        label: 'Recovery Plans' },
  { key: 'export',                label: 'Export' },
  { key: 'delivery_intelligence', label: 'Delivery Intelligence' },
  { key: 'sprint-health',         label: '🏥 Sprint Health' },
  { key: 'reasoning-trace',       label: '🧠 Reasoning Trace' },
]

function OverviewCard({ children, className = '', style = {} }) {
  return (
    <section
      className={className}
      style={{
        border: '1px solid var(--line)',
        borderRadius: 8,
        background: 'var(--panel)',
        padding: '11px 12px',
        ...style,
      }}
    >
      {children}
    </section>
  )
}

function MetricCard({label, value}){
  return (
    <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
      <div className="text-sm uppercase tracking-[0.2em] text-slate-400">{label}</div>
      <div className="mt-3 text-2xl font-semibold text-white">{value}</div>
    </div>
  )
}

function KpiTile({ label, value, color = '', note }) {
  const colorMap = {
    teal:   'var(--teal)',
    yellow: 'var(--yellow)',
    pink:   'var(--pink)',
    orange: 'var(--orange)',
  }
  return (
    <div style={{ border: '1px solid var(--line2)', borderRadius: 5, background: 'oklch(17% .036 255)', padding: '10px 11px' }}>
      <span className="block uppercase tracking-[0.2em] text-slate-300" style={{ fontSize: 10, fontWeight: 700 }}>{label}</span>
      <div style={{ fontSize: 18, fontWeight: 800, marginTop: 3, color: colorMap[color] || 'var(--text)' }}>{value || '—'}</div>
      {note && <div className="text-slate-500" style={{ fontSize: 10, marginTop: 2 }}>{note}</div>}
    </div>
  )
}

function OverviewPage({ session, onNavigate }) {
  const summary = session.project_summary
  const [blockerCount, setBlockerCount] = useState(summary?.total_blockers ?? '—')
  const [blockerLoading, setBlockerLoading] = useState(true)

  useEffect(() => {
    let isMounted = true
    const sessionId = session?.project_summary?.session_id

    if (!sessionId) {
      setBlockerCount(summary?.total_blockers ?? '—')
      setBlockerLoading(false)
      return () => { isMounted = false }
    }

    setBlockerLoading(true)
    api.sessionSnapshot(sessionId)
      .then((snapshot) => {
        if (!isMounted) return
        const activeCount = snapshot?.blocker_metrics?.active_blocker_count
        setBlockerCount(typeof activeCount === 'number' ? activeCount : (summary?.total_blockers ?? '—'))
        setBlockerLoading(false)
      })
      .catch(() => {
        if (!isMounted) return
        setBlockerCount(summary?.total_blockers ?? '—')
        setBlockerLoading(false)
      })

    return () => { isMounted = false }
  }, [session?.project_summary?.session_id, summary?.total_blockers])

  return (
    <div>
      <OverviewCard>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Project</p>
            <h2 style={{ fontSize: 14, fontWeight: 800, marginTop: 4 }}>{summary.project_name}</h2>
            <p style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>{summary.customer} · Managed by {summary.project_manager}</p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6, marginTop: 9 }}>
          <KpiTile label="Sprints completed" value={`${summary.completed_sprints ?? '—'} of ${summary.total_sprints ?? '—'}`} />
          <KpiTile label="Blockers active" value={blockerLoading ? '…' : (blockerCount ?? '—')} color="pink" />
          <KpiTile label="Work items" value={summary.total_work_items ?? '—'} />
          <KpiTile label="Dependencies" value={summary.total_dependencies ?? '—'} />
        </div>
      </OverviewCard>

      <div style={{ marginTop: 9 }}>
        <HeroBanner session={session} onNavigate={onNavigate} />
      </div>
    </div>
  )
}

function HeroBanner({ session, onNavigate }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [snap, setSnap] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  const fetchData = async () => {
    if (!sessionId) { setError(new Error('Missing session id')); setLoading(false); return }
    setLoading(true)
    setError(null)
    try {
      // Single call returns forecast + MC + risk + EMIOS strip
      const s = await api.sessionSnapshot(sessionId)
      setSnap(s)
      setLoading(false)
    } catch (err) {
      setError(err)
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [sessionId])

  if (loading) return (
    <OverviewCard className="shadow-inner shadow-black/20">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Project status</p>
      <h2 className="mt-2 text-3xl font-extrabold text-white">Computing forecast…</h2>
      <p className="mt-2 text-sm text-slate-400">Running Monte Carlo simulation</p>
    </OverviewCard>
  )

  if (error) return (
    <OverviewCard
      className="shadow-inner shadow-black/20"
      style={{ borderColor: 'rgba(244, 63, 94, 0.6)', background: 'rgba(127, 29, 29, 0.12)' }}
    >
      <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Project status</p>
      <h2 className="mt-2 text-3xl font-extrabold text-rose-200">Status unavailable</h2>
      <p className="mt-2 text-sm text-rose-300">{error.message || 'Failed to load forecast or Monte Carlo results'}</p>
      <button onClick={fetchData} className="mt-4 rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
    </OverviewCard>
  )

  const mc = snap?.monte_carlo || {}
  const forecast = snap?.forecast || {}
  const strip = snap?.emios_strip || {}

  const prob = mc.on_time_probability != null ? Math.round(mc.on_time_probability * 100) : '—'
  const delayText = forecast.expected_delay_days != null ? formatScheduleVariance(forecast.expected_delay_days) : '—'

  return (
    <OverviewCard className="summary" style={{ marginBottom: 9 }}>
      <div>
        <div>
          <div className="text-sm uppercase tracking-[0.3em] text-amber-400">AI project verdict</div>
          <div style={{ fontSize: 14, fontWeight: 800, marginTop: 4, maxWidth: 600 }}>{strip.reasoning_explanation || 'Analyzing project…'}</div>

        </div>
      </div>

      <div className="mt-11 grid grid-cols-2 gap-6 sm:grid-cols-4">
        <KpiTile label="Decision needed by" value={strip.urgency_window || '—'} color="orange" />
        <KpiTile label="Delay exposure" value={delayText} color="yellow" note="Monte Carlo P50 · if no action taken" />
        <KpiTile label="On-time probability" value={prob === '—' ? 'Data unavailable' : `${prob}%`} color="teal" note="Chance of hitting the target date" />
        <KpiTile
          label="Diagnosis confidence"
          value={
            strip.confidence_pct == null ? 'Data unavailable'
            : strip.confidence_pct >= 75 ? 'High'
            : strip.confidence_pct >= 50 ? 'Moderate'
            : 'Low'
          }
          color={
            strip.confidence_pct == null ? ''
            : strip.confidence_pct >= 75 ? 'teal'
            : strip.confidence_pct >= 50 ? 'yellow'
            : 'pink'
          }
          note={strip.confidence_pct != null ? `${strip.confidence_pct}% — how certain the engine is` : 'How certain the engine is about the root cause'}
        />
      </div>
    </OverviewCard>
  )
}

function formatDate(iso){
  if(!iso) return '—'
  try{
    const d = new Date(iso)
    return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
  }catch(e){ return iso }
}

function daysBetween(a,b){
  const msPerDay = 1000*60*60*24
  return Math.round((b - a)/msPerDay)
}


const STATUS_STYLES = {
  ON_TRACK: { pill: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300', dot: 'bg-emerald-400', label: 'On track', ring: '#34d399', icon: CheckCircle2 },
  AT_RISK:  { pill: 'border-amber-500/40 bg-amber-500/10 text-amber-300',   dot: 'bg-amber-400',   label: 'At risk', ring: '#fbbf24', icon: Clock3 },
  LATE:     { pill: 'border-rose-500/40 bg-rose-500/10 text-rose-300',      dot: 'bg-rose-400',    label: 'Late', ring: '#fb7185', icon: AlertTriangle },
}

function ProgressRing({ percent, color, mounted }){
  const size = 92
  const stroke = 8
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, percent))
  const offset = circumference - (mounted ? clamped / 100 : 0) * circumference
  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle cx={size/2} cy={size/2} r={radius} stroke="#1e293b" strokeWidth={stroke} fill="none" />
      <circle
        cx={size/2} cy={size/2} r={radius}
        stroke={color} strokeWidth={stroke} fill="none"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 900ms cubic-bezier(0.16, 1, 0.3, 1)' }}
      />
    </svg>
  )
}

const TONE_STYLES = {
  risk:    { bar: 'bg-rose-500',    value: 'text-rose-300' },
  good:    { bar: 'bg-emerald-500', value: 'text-emerald-300' },
  neutral: { bar: 'bg-slate-600',   value: 'text-slate-400' },
}

function SeverityBadge({severity}){
  const s = (severity || '').toLowerCase()
  const cls = s === 'critical' ? 'border-rose-500/50 bg-rose-500/10 text-rose-300'
    : s === 'high' ? 'border-orange-500/50 bg-orange-500/10 text-orange-300'
    : s === 'medium' ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
    : 'border-slate-600 bg-slate-800 text-slate-300'
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${cls}`}>{severity || 'Unknown'}</span>
}

function DelayDiagnosis({session}){
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [historical, setHistorical] = useState(null)
  const [rootCause, setRootCause] = useState(null)
  const [mounted, setMounted] = useState(false)

  const sessionId = session?.project_summary?.session_id || ''

  const fetchData = () => {
    if (!sessionId) { setError(new Error('Missing session id')); setLoading(false); return }
    setLoading(true)
    setError(null)
    Promise.all([
      api.forecast(sessionId),
      api.sessionSnapshot(sessionId),
    ])
      .then(([f, snapshot]) => {
        setForecast(f?.forecast ?? f)
        setHistorical(snapshot?.historical ?? null)
        setLoading(false)
      })
      .catch(err => { setError(err); setLoading(false) })
  }

  useEffect(() => { fetchData() }, [sessionId])
  useEffect(() => {
    if (!sessionId) return
    api.diagnosis(sessionId).then(setRootCause).catch(() => setRootCause(null))
  }, [sessionId])
  useEffect(() => {
    if (forecast?.steering_brief){
      setMounted(false)
      const t = setTimeout(() => setMounted(true), 60)
      return () => clearTimeout(t)
    }
  }, [forecast])

  if(loading){
    return (
      <OverviewCard className="mt-6 shadow-inner shadow-black/20">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Steering summary</p>
        <p className="mt-3 text-sm text-slate-400">Loading delay diagnostics…</p>
      </OverviewCard>
    )
  }

  if(error){
    return (
      <OverviewCard className="mt-6 shadow-inner shadow-black/20" style={{ borderColor: 'rgba(244, 63, 94, 0.6)', background: 'rgba(127, 29, 29, 0.12)' }}>
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Steering summary</p>
            <h2 className="mt-2 text-2xl font-semibold text-rose-100">Unable to load diagnostics</h2>
            <p className="mt-2 text-sm text-rose-300">{error.message || 'Forecast diagnostics could not be retrieved.'}</p>
          </div>
          <button onClick={fetchData} className="rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
        </div>
      </OverviewCard>
    )
  }

  const brief = forecast?.steering_brief

  if(!forecast || !brief){
    return (
      <OverviewCard className="mt-6 shadow-inner shadow-black/20">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Steering summary</p>
        <p className="mt-3 text-sm text-slate-400">No schedule diagnostics are available for this session.</p>
      </OverviewCard>
    )
  }

  const statusStyle = STATUS_STYLES[brief.status] || STATUS_STYLES.AT_RISK
  const StatusIcon = statusStyle.icon
  const maxAbs = Math.max(...brief.waterfall.map(d => Math.abs(d.days || 0)), 1)



  return (
    <OverviewCard className="mt-6 shadow-inner shadow-black/20">
      {/* Header: this is the slide a manager reads out loud */}
      <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          <div className="relative flex-none">
            <ProgressRing percent={(brief.completion_percentage || 0) * 100} color={statusStyle.ring} mounted={mounted} />
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-lg font-bold text-white">{Math.round((brief.completion_percentage || 0) * 100)}%</span>
              <span className="text-[9px] uppercase tracking-wide text-slate-500">complete</span>
              <span className="text-[9px] text-slate-500 mt-0.5">by effort hours</span>
            </div>
          </div>
          <div>
            <div className="flex items-center gap-3">
              <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Steering summary</p>
              <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${statusStyle.pill}`}>
                <StatusIcon className="h-3 w-3" />
                {statusStyle.label}
              </span>
            </div>
            <h2 className="mt-2 text-2xl font-semibold text-white leading-snug">{brief.headline}</h2>
            <p className="mt-1 text-sm text-slate-400">{brief.subheadline}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 md:flex-none">
          <div className="rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-center min-w-[110px]">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Target</p>
            <p className="mt-1 text-sm font-semibold text-white">{formatDate(brief.target_end_date)}</p>
          </div>
          <div className="rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-center min-w-[110px]">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Projected finish</p>
            <p className={`mt-1 text-sm font-semibold ${brief.status === 'ON_TRACK' ? 'text-emerald-300' : 'text-rose-300'}`}>{formatDate(brief.expected_finish_date)}</p>
          </div>
        </div>
      </div>

      {/* Decision ask -- the single loudest thing on the card. This is what the
          room needs to act on, so it outweighs every other element visually. */}
      <div className={`mt-6 rounded-2xl border-2 px-5 py-4 flex items-start gap-3 ${
        brief.status === 'ON_TRACK'
          ? 'border-emerald-500/40 bg-emerald-500/[0.07]'
          : brief.status === 'LATE'
            ? 'border-rose-500/50 bg-rose-500/[0.08] shadow-[0_0_0_1px_rgba(244,63,94,0.15)]'
            : 'border-amber-500/50 bg-amber-500/[0.08]'
      }`}>
        {brief.status === 'ON_TRACK'
          ? <CheckCircle2 className="h-5 w-5 flex-none mt-0.5 text-emerald-400" />
          : <ShieldAlert className={`h-5 w-5 flex-none mt-0.5 ${brief.status === 'LATE' ? 'text-rose-400' : 'text-amber-400'}`} />}
        <div>
          <p className={`text-xs font-bold uppercase tracking-wider mb-1 ${
            brief.status === 'ON_TRACK' ? 'text-emerald-400' : brief.status === 'LATE' ? 'text-rose-400' : 'text-amber-400'
          }`}>{brief.status === 'ON_TRACK' ? 'Status' : 'Decision needed'}</p>
          <p className={`text-base font-medium leading-snug ${
            brief.status === 'ON_TRACK' ? 'text-emerald-100' : brief.status === 'LATE' ? 'text-rose-50' : 'text-amber-50'
          }`}>{brief.decision_ask}</p>
        </div>
      </div>



      {/* Waterfall: exact reconciliation to the headline delay number */}
      <div className="mt-6">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-400">
          {brief.expected_delay_days >= 0
            ? 'What is driving the delay'
            : 'Why we are currently ahead of schedule'}
        </p>
        <div className="mt-4 space-y-4">
          {/* Additive rows: days > 0 or days < 0 — these sum to expected_delay_days */}
          {brief.waterfall.filter(d => d.days !== 0).map((d, i) => {
            const tone = TONE_STYLES[d.tone] || TONE_STYLES.neutral
            const width = Math.max(4, Math.round((Math.abs(d.days || 0) / maxAbs) * 100))
            return (
              <div key={d.key} className="space-y-1.5">
                <div className="flex items-center justify-between text-sm text-slate-300">
                  <span className="font-medium">{d.label}</span>
                  <span className={`font-semibold ${tone.value}`}>
                    {`${d.days > 0 ? '+' : ''}${d.days.toFixed(1)}d`}
                  </span>
                </div>
                <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={`${tone.bar} h-3 rounded-full`}
                    style={{
                      width: mounted ? `${width}%` : '0%',
                      transition: `width 700ms cubic-bezier(0.16, 1, 0.3, 1) ${i * 90}ms`,
                    }}
                  />
                </div>
                <p className="text-xs text-slate-500">{d.detail}</p>
              </div>
            )
          })}

          {/* Risk-signal rows: days = 0 — grouped into a single card so they read as one unit */}
          {brief.waterfall.some(d => d.days === 0) && (() => {
            const riskSignals = brief.waterfall.filter(d => d.days === 0)
            const anyRisk = riskSignals.some(d => d.tone === 'risk')
            return (
              <div className="mt-4 pt-4 border-t border-slate-800">
                <div className={`rounded-xl border px-4 py-3 space-y-3 ${anyRisk ? 'border-amber-500/25 bg-amber-500/5' : 'border-slate-700 bg-slate-900/40'}`}>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Also tracked — already included in the delay above</p>
                  {riskSignals.map(d => {
                    const isRisk = d.tone === 'risk'
                    return (
                      <div key={d.key} className="flex items-start gap-2.5">
                        <span className={`mt-0.5 h-2 w-2 flex-none rounded-full ${isRisk ? 'bg-amber-400' : 'bg-slate-600'}`} />
                        <div>
                          <span className={`text-xs font-semibold ${isRisk ? 'text-amber-300' : 'text-slate-400'}`}>{d.label}</span>
                          <p className="text-[11px] text-slate-500 leading-relaxed mt-0.5">{d.detail}</p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })()}
        </div>
      </div>

      {rootCause?.findings?.length > 0 && (() => {
        const observed = rootCause.findings.filter(f => f.observed)
        const notObserved = rootCause.findings.filter(f => !f.observed)
        return (
          <div className="mt-6">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400 mb-1">
              Why is this project delayed?
            </p>
            {rootCause.headline && (
              <p className="text-xs text-slate-500 mb-3">{rootCause.headline}</p>
            )}

            {/* Observed findings — the actual problems */}
            <div className="grid grid-cols-2 gap-2">
              {observed.map(f => {
                const impactTone =
                  f.max_severity === 'critical' ? 'border-rose-500/50 bg-rose-500/10' :
                  f.impact === 'High'            ? 'border-orange-500/40 bg-orange-500/8' :
                  f.impact === 'Medium'          ? 'border-amber-500/35 bg-amber-500/8' :
                                                   'border-slate-600 bg-slate-800/40'
                const labelColor =
                  f.max_severity === 'critical' ? 'text-rose-200' :
                  f.impact === 'High'            ? 'text-orange-200' :
                  f.impact === 'Medium'          ? 'text-amber-200' :
                                                   'text-slate-300'
                return (
                  <div key={f.category} className={`rounded-xl border px-3 py-3 space-y-2 ${impactTone}`}>
                    <div className="flex items-center justify-between gap-2">
                      <div className={`text-[12px] font-bold ${labelColor}`}>{f.root_cause}</div>
                      {f.max_severity && <SeverityBadge severity={f.max_severity} />}
                    </div>

                    {/* All evidence lines, not just the first */}
                    {f.sample_explanations?.length > 0 && (
                      <ul className="space-y-1">
                        {f.sample_explanations.map((ex, idx) => (
                          <li key={idx} className="flex items-start gap-1.5 text-[11px] text-slate-300 leading-snug">
                            <span className="mt-0.5 text-slate-500 flex-none">›</span>
                            <span>{ex}</span>
                          </li>
                        ))}
                      </ul>
                    )}

                    {/* Project item chips */}
                    {f.contributing_signal_ids?.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-0.5">
                        {f.contributing_signal_ids.slice(0, 6).map(id => (
                          <span key={id} className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400">
                            {id}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="text-[10px] text-slate-500">
                      Detected in {f.signal_count} project check{f.signal_count === 1 ? '' : 's'} · {f.impact} impact
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Not-observed categories — collapsed into a single quiet line */}
            {notObserved.length > 0 && (
              <p className="mt-2 text-[10px] text-slate-600">
                Also checked, not found: {notObserved.map(f => f.root_cause).join(', ')}
              </p>
            )}
          </div>
        )
      })()}

      {brief.scope_note && (
        <div className="mt-5 rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">
          <span className="font-semibold uppercase tracking-wide text-xs mr-2 text-amber-300">Scope</span>
          {brief.scope_note}
        </div>
      )}

      {/* Named, owned blockers -- exactly what a steering committee needs to unblock */}
      {brief.top_blockers?.length > 0 && (
        <div className="mt-6">
          <p className="text-xs uppercase tracking-[0.25em] text-slate-400 mb-3 flex items-center gap-1.5">
            <ShieldAlert className="h-3.5 w-3.5 text-rose-400" />
            Blockers driving the schedule
            {brief.total_open_blockers > brief.top_blockers.length && (
              <span className="normal-case tracking-normal text-slate-500"> — showing top {brief.top_blockers.length} of {brief.total_open_blockers} open</span>
            )}
          </p>
          <div className="overflow-hidden rounded-2xl border border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-950/60 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Blocker</th>
                  <th className="px-4 py-2 font-medium">Owner</th>
                  <th className="px-4 py-2 font-medium">Severity</th>
                  <th className="px-4 py-2 font-medium">Age</th>
                  <th className="px-4 py-2 font-medium">Target date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {brief.top_blockers.map(b => {
                  const ageDays = b.raised_date
                    ? Math.max(0, Math.round((Date.now() - new Date(b.raised_date).getTime()) / 86400000))
                    : null
                  const ageColor = ageDays == null ? 'text-slate-500'
                    : ageDays >= 14 ? 'text-rose-400 font-semibold'
                    : ageDays >= 7  ? 'text-amber-400'
                    : 'text-slate-400'
                  return (
                    <tr key={b.blocker_id} className="bg-slate-900/40 hover:bg-slate-800/50 transition-colors">
                      <td className="px-4 py-3 align-top">
                        <div className="font-semibold text-white">{b.blocker_id} {b.on_critical_path && <span className="ml-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[10px] text-sky-300 align-middle">Critical path</span>}</div>
                        <div className="text-xs text-slate-400 mt-0.5">{b.description}</div>
                      </td>
                      <td className="px-4 py-3 align-top text-slate-300">{b.owner || <span className="text-rose-400">Unassigned</span>}</td>
                      <td className="px-4 py-3 align-top"><SeverityBadge severity={b.severity} /></td>
                      <td className={`px-4 py-3 align-top ${ageColor}`}>
                        {ageDays != null ? `${ageDays}d open` : '—'}
                      </td>
                      <td className="px-4 py-3 align-top text-slate-400">{b.target_resolution_date ? formatDate(b.target_resolution_date) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

        </div>
      )}

      {/* Resource overload -- catches individuals over 100% even when sprint-average utilization looks fine */}
      {brief.overloaded_resources?.length > 0 && (
        <div className="mt-6">
          <p className="text-xs uppercase tracking-[0.25em] text-slate-400 mb-3 flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5 text-amber-400" />
            Resource overload ahead
            {brief.overloaded_resources.length > 0 && (
              <span className="normal-case tracking-normal text-slate-500"> · {brief.overloaded_resources.length} person{brief.overloaded_resources.length !== 1 ? 's' : ''}</span>
            )}
          </p>
          <div className="overflow-hidden rounded-2xl border border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-950/60 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Resource</th>
                  <th className="px-4 py-2 font-medium">Sprint</th>
                  <th className="px-4 py-2 font-medium text-right">Allocation</th>
                  <th className="px-4 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {brief.overloaded_resources.map((r, i) => (
                  <tr key={`${r.resource_name}-${r.sprint_id}-${i}`} className="bg-slate-900/40 hover:bg-slate-800/50 transition-colors">
                    <td className="px-4 py-3 align-top font-semibold text-white">{r.resource_name}</td>
                    <td className="px-4 py-3 align-top text-slate-300">{r.sprint_name}</td>
                    <td className="px-4 py-3 align-top text-right font-semibold text-amber-300">{r.load_pct.toFixed(0)}%</td>
                    <td className="px-4 py-3 align-top">
                      {r.is_blocker_owner && (
                        <span className="rounded-full border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-300">Also owns a blocker</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

        </div>
      )}




    </OverviewCard>
  )
}

function ForecastPage({session}){
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [mc, setMc] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  useEffect(()=>{
    let mounted = true
    if(!sessionId){
      setError(new Error('Missing session id'))
      setLoading(false)
      return () => { mounted = false }
    }
    setLoading(true)
    setError(null)
    Promise.all([api.forecast(sessionId), api.monteCarlo(sessionId)])
      .then(([f, m])=>{ if(mounted){ setForecast(f?.forecast ?? f); setMc(m?.monte_carlo ?? m); setLoading(false) }})
      .catch(err=>{ if(mounted){ setError(err); setLoading(false) }})
    return ()=>{ mounted = false }
  }, [sessionId])

  if(loading){
    return (
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Forecast</p>
        <p className="mt-3 text-sm text-slate-400">Loading forecast and Monte Carlo details…</p>
      </section>
    )
  }

  if(error){
    return (
      <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-6 shadow-inner shadow-black/20">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Forecast</p>
            <h2 className="mt-2 text-2xl font-semibold text-rose-100">Unable to load forecast data</h2>
            <p className="mt-2 text-sm text-rose-300">{error.message || 'Failed to retrieve forecast or Monte Carlo results.'}</p>
          </div>
          <button onClick={()=>{ setLoading(true); setError(null); Promise.all([api.forecast(sessionId), api.monteCarlo(sessionId)]).then(([f,m])=>{ setForecast(f?.forecast ?? f); setMc(m?.monte_carlo ?? m); setLoading(false)}).catch(err=>{ setError(err); setLoading(false) }) }} className="rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
        </div>
      </section>
    )
  }

  if(!forecast && !mc){
    return (
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Forecast</p>
        <p className="mt-3 text-sm text-slate-400">No forecast or Monte Carlo results are available for this session.</p>
      </section>
    )
  }

  // Percentile timeline
  const stats = mc && mc.statistics ? mc.statistics : null
  const percentiles = stats ? [10,25,50,75,80,90,95].map(p => ({ p, iso: stats[`percentile_${p}`] })) : []
  const minIso = stats && stats.percentile_10 ? new Date(stats.percentile_10) : null
  const maxIso = stats && stats.percentile_95 ? new Date(stats.percentile_95) : null
  const rangeMs = minIso && maxIso ? (maxIso - minIso) : null

  const formatDateLabel = (iso) => { if(!iso) return '—'; try{ return new Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: 'short' }) }catch(e){ return iso } }



  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Forecast</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">Finish-date distribution</h2>
            <p className="mt-2 text-sm text-slate-400">Monte Carlo percentiles show likely completion windows.</p>
          </div>
          <div className="rounded-3xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-300">
            {mc && mc.simulation_count ? `${mc.simulation_count.toLocaleString()} simulations` : 'Simulations'}
          </div>
        </div>

        <div className="mt-6">
          <div className="relative h-8 rounded-full bg-slate-800">
            {minIso && maxIso && percentiles.map(pt => {
              const iso = pt.iso
              const left = iso ? Math.round(((new Date(iso) - minIso) / rangeMs) * 100) : 0
              const color = pt.p === 50 ? 'bg-sky-500' : (pt.p <= 25 ? 'bg-emerald-500' : pt.p >= 90 ? 'bg-rose-500' : 'bg-amber-400')
              return (
                <div key={pt.p} className="absolute top-0 h-8 w-0">
                  <div className={`absolute -top-3 h-14 w-0`} style={{ left: `${left}%` }}>
                    <div className={`h-3 w-3 ${color} rounded-full border border-slate-900`} />
                  </div>
                </div>
              )
            })}
            <div className="absolute inset-0 flex items-end justify-between px-2 text-xs text-slate-400">
              <div>{formatDateLabel(stats?.percentile_10)}</div>
              <div>{formatDateLabel(stats?.percentile_95)}</div>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-3">
            {[50, 80, 95].map(p => {
              const pt = percentiles.find(x => x.p === p)
              return pt ? (
                <div key={p} className="rounded-3xl border border-slate-700 bg-slate-950/80 p-3 text-center">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-400">P{p} {p === 50 ? '· Most likely' : p === 80 ? '· Safe target' : '· Worst case'}</div>
                  <div className="mt-2 text-lg font-semibold text-white">{formatDateLabel(pt.iso)}</div>
                </div>
              ) : null
            })}
          </div>
        </div>
      </section>




    </div>
  )
}

function SprintRiskHeatmap({ session }) {
  const [loading, setLoading] = useState(true)
  const [sprints, setSprints] = useState([])
  const sessionId = session?.project_summary?.session_id || ''

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    api.risk(sessionId)
      .then(r => {
        const riskData = r?.risk_assessment ?? r
        setSprints(riskData?.sprint_risks || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [sessionId])

  if (loading) return (
    <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
      <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Sprint risk heatmap</p>
      <p className="mt-2 text-sm text-slate-500">Loading sprint risks…</p>
    </div>
  )

  if (!sprints.length) return null

  const riskColor = (score) => {
    if (score >= 70) return 'bg-rose-500'
    if (score >= 45) return 'bg-amber-500'
    return 'bg-emerald-500'
  }

  const riskTextColor = (score) => {
    if (score >= 70) return 'text-rose-400'
    if (score >= 45) return 'text-amber-400'
    return 'text-emerald-400'
  }

  return (
    <div className="rounded-3xl border border-slate-700 bg-slate-900 p-5">
      <p className="text-xs uppercase tracking-[0.3em] text-amber-400 mb-1">Sprint risk heatmap</p>
      <h3 className="text-lg font-semibold text-white mb-4">At a glance — which sprint is your problem?</h3>
      <div className="flex flex-wrap gap-3">
        {sprints.map((sprint, i) => {
          const score = Math.round(sprint.risk_score ?? sprint.score ?? 0)
          const name = sprint.sprint_name || sprint.sprint_id || `Sprint ${i + 1}`
          const blockerCount = sprint.blocker_count ?? sprint.active_blockers ?? 0
          const spilloverCount = sprint.spillover_count ?? sprint.spillover_items ?? 0
          return (
            <div key={sprint.sprint_id || i} className="relative group cursor-default">
              <div className={`${riskColor(score)} rounded-2xl w-20 h-20 flex flex-col items-center justify-center gap-1 transition hover:opacity-80`}>
                <div className="text-xs font-bold text-white/90 truncate px-2 text-center leading-tight">{name}</div>
                <div className="text-xl font-extrabold text-white">{score}</div>
              </div>
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-10 hidden group-hover:block w-48">
                <div className="rounded-2xl border border-slate-600 bg-slate-800 p-3 shadow-xl text-xs">
                  <div className={`font-bold mb-1 ${riskTextColor(score)}`}>{name} — risk {score}/100</div>
                  {blockerCount > 0 && <div className="text-rose-300">⛔ {blockerCount} active blocker{blockerCount > 1 ? 's' : ''}</div>}
                  {spilloverCount > 0 && <div className="text-amber-300">⚠ {spilloverCount} spillover item{spilloverCount > 1 ? 's' : ''}</div>}
                  {sprint.overload_pct !== undefined && sprint.overload_pct > 100 && <div className="text-amber-300">📈 {Math.round(sprint.overload_pct)}% loaded</div>}
                  {blockerCount === 0 && spilloverCount === 0 && <div className="text-slate-400">No critical issues</div>}
                </div>
                <div className="w-2 h-2 border-b border-r border-slate-600 bg-slate-800 rotate-45 mx-auto -mt-1"></div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-4 flex gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-emerald-500"></span> Low (&lt;45)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-amber-500"></span> Medium (45–69)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-rose-500"></span> High (70+)</span>
      </div>
    </div>
  )
}

function ScenarioColumn({ label, badge, badgeColor, data, probColor, formatDate, summary }) {
  if (!data) return null
  const prob = data.on_time_probability
  const delay = data.expected_delay_days
  const risk = data.overall_risk_score
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm uppercase tracking-[0.3em] text-slate-400">{label}</p>
        <span className={`text-xs font-bold px-3 py-1 rounded-full border ${badgeColor}`}>{badge}</span>
      </div>
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-1">On-time probability</div>
        <div className={`text-6xl font-extrabold ${probColor(prob)}`}>
          {prob !== undefined && prob !== null ? `${prob}%` : '—'}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">Delay</div>
          <div className={`mt-1 text-xl font-bold ${delay > 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
            {delay !== undefined ? (delay > 0 ? `+${delay}d` : `${delay}d`) : '—'}
          </div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">Risk score</div>
          <div className={`mt-1 text-xl font-bold ${risk >= 60 ? 'text-rose-300' : risk >= 40 ? 'text-amber-300' : 'text-emerald-300'}`}>
            {risk !== undefined ? Math.round(risk) : '—'}<span className="text-sm text-slate-500">/100</span>
          </div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3 col-span-2">
          <div className="text-xs text-slate-500 uppercase tracking-wide">P50 finish</div>
          <div className="mt-1 text-sm font-semibold text-white">{formatDate(data.p50_date)}</div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">P80</div>
          <div className="mt-1 text-sm font-semibold text-slate-200">{formatDate(data.p80_date)}</div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">P95</div>
          <div className="mt-1 text-sm font-semibold text-slate-200">{formatDate(data.p95_date)}</div>
        </div>
      </div>
      {summary && (
        <div className="rounded-2xl border border-emerald-800 bg-emerald-900/10 p-3">
          <div className="text-xs uppercase tracking-wide text-emerald-400 mb-1">What changed</div>
          <p className="text-sm text-slate-300">{summary}</p>
        </div>
      )}
    </section>
  )
}

function ReforecastPage({ session }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  const load = () => {
    if (!sessionId) { setError(new Error('Missing session id')); setLoading(false); return }
    setLoading(true)
    setError(null)
    api.reforecastComparison(sessionId)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err); setLoading(false) })
  }

  useEffect(() => { load() }, [sessionId])

  if (loading) return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-8 text-center">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Reforecast</p>
      <p className="mt-3 text-sm text-slate-400">Computing comparison…</p>
    </section>
  )

  if (error) return (
    <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-8">
      <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Reforecast unavailable</p>
      <p className="mt-2 text-sm text-rose-300">{error.message}</p>
      <button onClick={load} className="mt-4 rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
    </section>
  )

  if (!data) return null

  const { baseline, after_recommendation, deltas } = data
  const hasSimulation = after_recommendation?.on_time_risk_level !== 'NO_SIMULATION_YET'

  const probColor = (p) => {
    if (p >= 70) return 'text-emerald-400'
    if (p >= 40) return 'text-amber-400'
    return 'text-rose-400'
  }

  const formatDate = (iso) => {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) }
    catch { return iso }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Reforecast comparison</p>
        <h2 className="mt-2 text-2xl font-bold text-white">Before vs. After</h2>
        <p className="mt-1 text-sm text-slate-400">
          {hasSimulation ? 'Showing impact of your last simulated recommendation.' : 'Simulate a recommendation in the Actions tab to see the after column.'}
        </p>
      </section>
      {hasSimulation && deltas && (
        <section className={`rounded-3xl border p-5 flex flex-col sm:flex-row gap-6 items-center justify-center ${deltas.has_improvement ? 'border-emerald-600 bg-emerald-900/20' : 'border-slate-700 bg-slate-900'}`}>
          <div className="text-center">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Probability gain</div>
            <div className={`mt-1 text-4xl font-extrabold ${deltas.probability_gain_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltas.probability_gain_pct >= 0 ? '+' : ''}{deltas.probability_gain_pct}%
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Days saved</div>
            <div className={`mt-1 text-4xl font-extrabold ${deltas.days_saved >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltas.days_saved >= 0 ? '+' : ''}{deltas.days_saved}d
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Risk reduction</div>
            <div className={`mt-1 text-4xl font-extrabold ${deltas.risk_score_reduction >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltas.risk_score_reduction >= 0 ? '−' : '+'}{Math.abs(deltas.risk_score_reduction)}
            </div>
          </div>
        </section>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <ScenarioColumn label="Baseline" badge="BEFORE" badgeColor="text-rose-300 border-rose-600 bg-rose-900/20" data={baseline} probColor={probColor} formatDate={formatDate} />
        {hasSimulation ? (
          <ScenarioColumn label="After recommendation" badge="AFTER" badgeColor="text-emerald-300 border-emerald-600 bg-emerald-900/20" data={after_recommendation} probColor={probColor} formatDate={formatDate} summary={after_recommendation.summary} />
        ) : (
          <section className="rounded-3xl border border-dashed border-slate-600 bg-slate-900/40 p-6 flex items-center justify-center text-center">
            <div>
              <div className="text-slate-500 text-4xl mb-3">?</div>
              <p className="text-sm uppercase tracking-[0.2em] text-slate-500">No simulation yet</p>
              <p className="mt-2 text-xs text-slate-600">Go to Actions → pick a recommendation → Simulate.</p>
            </div>
          </section>
        )}
      </div>
      <div className="flex justify-center">
        <button onClick={load} className="rounded-2xl border border-slate-600 bg-slate-800 px-5 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-700">Refresh comparison</button>
      </div>
    </div>
  )
}

function ActionsPage({ session, onSimulated }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [recs, setRecs] = useState([])
  const [simulatingId, setSimulatingId] = useState(null)
  const [simulationResult, setSimulationResult] = useState(null)
  const [selected, setSelected] = useState([])
  const [scenarioLoading, setScenarioLoading] = useState(false)

  const sessionId = session?.project_summary?.session_id || ''

  useEffect(()=>{
    let mounted = true
    if(!sessionId){
      setError(new Error('Missing session id'))
      setLoading(false)
      return () => { mounted = false }
    }
    setLoading(true)
    api.recommendations(sessionId).then(resp=>{ if(mounted){ setRecs(resp.recommendations || resp || []); setLoading(false) }}).catch(err=>{ if(mounted){ setError(err); setLoading(false) }})
    return ()=> mounted = false
  }, [sessionId])

  const simulate = async (recommendation_id) => {
    setSimulatingId(recommendation_id)
    setSimulationResult(null)
    try{
      const body = { recommendation_id }
      const resp = await api.simulateRecommendation(body, sessionId)
      setSimulationResult(resp.simulation_result || resp)
      onSimulated && onSimulated()
    }catch(err){
      setError(err)
    }finally{
      setSimulatingId(null)
    }
  }

  const runScenario = async () => {
    if(selected.length === 0) return
    setScenarioLoading(true)
    setError(null)
    try{
      const resp = await api.simulateScenario({ recommendation_ids: selected.slice(0,3) }, sessionId)
      setSimulationResult(resp.simulation_result || resp)
    }catch(err){ setError(err) }finally{ setScenarioLoading(false) }
  }

  const toggleSelect = (id) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x=>x!==id) : [...prev.slice(-2), id])
  }

  if(loading) return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Actions</p>
      <p className="mt-3 text-sm text-slate-400">Loading recommendations…</p>
    </section>
  )

  if(error) return (
    <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-6 shadow-inner shadow-black/20">
      <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Actions</p>
      <p className="mt-2 text-sm text-rose-300">{error.message || 'Failed to load recommendations.'}</p>
    </section>
  )

  if(!recs || recs.length === 0) return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Actions</p>
      <p className="mt-3 text-sm text-slate-400">No recommendations are available for this session.</p>
    </section>
  )

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Actions</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">Recommendations</h2>

          </div>
          <div className="flex items-center gap-3">
            <button onClick={runScenario} disabled={selected.length===0 || scenarioLoading} className="rounded-2xl border border-emerald-500 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 disabled:opacity-50">{scenarioLoading ? 'Simulating selection…' : `Simulate selection (${selected.length})`}</button>
          </div>
        </div>

        <div className="mt-6 grid gap-4">
          {recs.filter(rec => (rec.expected_delay_gain_days || 0) > 0 || rec.impact_level !== 'Low').map(rec => (
            <div key={rec.recommendation_id} className="rounded-3xl border border-slate-700 bg-slate-950/80 p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-400">{rec.impact_level}</div>
                    {rec.urgency && (
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                        rec.urgency === 'TODAY' ? 'bg-rose-500/20 text-rose-300' :
                        rec.urgency === 'THIS_SPRINT' ? 'bg-amber-500/20 text-amber-300' :
                        'bg-sky-500/20 text-sky-300'
                      }`}>{rec.urgency.replace('_', ' ')}</span>
                    )}
                  </div>
                  {rec.blocker_overdue_days > 0 && (
                    <div className="mt-1 text-xs font-semibold text-rose-300">⚠ {rec.blocker_overdue_days} day{rec.blocker_overdue_days !== 1 ? 's' : ''} past target resolution</div>
                  )}
                  <h3 className="mt-1 text-lg font-semibold text-white">{rec.action}</h3>
                  <div className="mt-2 text-sm text-slate-300">{rec.impact_summary}</div>

                  {/* Probability gain bar */}
                  {rec.baseline_probability !== undefined && rec.after_probability !== undefined && (
                    <div className="mt-3 space-y-1">
                      <div className="flex items-center justify-between text-xs text-slate-400">
                        <span>On-time probability</span>
                        <span className="font-semibold text-white">
                          {Math.round(rec.baseline_probability * 100)}%
                          <span className="text-emerald-400 ml-1">→ {Math.round(rec.after_probability * 100)}%</span>
                          {rec.expected_probability_gain > 0 && (
                            <span className="ml-2 text-emerald-300">(+{Math.round(rec.expected_probability_gain * 100)}pp)</span>
                          )}
                        </span>
                      </div>
                      <div className="relative h-2 rounded-full bg-slate-800 overflow-hidden">
                        <div className="absolute h-2 rounded-full bg-slate-600" style={{ width: `${Math.round(rec.baseline_probability * 100)}%` }} />
                        <div className="absolute h-2 rounded-full bg-emerald-500" style={{ width: `${Math.round(rec.after_probability * 100)}%` }} />
                      </div>
                    </div>
                  )}

                  {/* Counterfactual */}
                  {rec.counterfactual_statement && (
                    <div className="mt-2 rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-slate-400 italic">
                      {rec.counterfactual_statement}
                    </div>
                  )}

                  {/* PM Decision Intelligence — additive; falls back to nothing if not attached */}
                  <PMIntelligencePanel pmIntelligence={rec.pm_intelligence} variant="full" />

                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 text-sm text-slate-400">
                    <div>Effort: <span className="text-white font-semibold">{rec.implementation_effort}</span></div>
                    <div>Confidence: <span className="text-white font-semibold">{rec.confidence}</span></div>
                    <div>Priority: <span className="text-white font-semibold">{Math.round(rec.priority_score)}</span></div>
                    <div>Impact: <span className="text-white font-semibold">{rec.impact_confidence || '—'}</span></div>
                  </div>
                  {rec.resource_load_impact && Object.keys(rec.resource_load_impact).length > 0 && (
                    <div className="mt-3 space-y-2">
                      {Object.entries(rec.resource_load_impact).map(([name, loads]) => (
                        <div key={name} className="flex items-center gap-3 text-xs">
                          <span className="w-32 truncate text-slate-400">{name}</span>
                          <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
                            <div
                              className={`h-full ${loads.after > 1.1 ? 'bg-rose-500' : loads.after > 0.9 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                              style={{width: `${Math.min(100, loads.after * 100)}%`}}
                            />
                          </div>
                          <span className="text-slate-500">{Math.round(loads.before*100)}% → <span className="text-white font-semibold">{Math.round(loads.after*100)}%</span></span>
                        </div>
                      ))}
                    </div>
                  )}
                  {rec.dependency_consequence && (
                    <details className="mt-3 text-xs text-slate-400">
                      <summary className="cursor-pointer text-sky-300 hover:text-sky-200">Why this matters</summary>
                      <p className="mt-1 pl-3 border-l border-slate-700">{rec.dependency_consequence}</p>
                    </details>
                  )}
                  {rec.validation && (
                    <details className="mt-4 rounded-2xl border border-slate-700 bg-slate-900/60 p-3">
                      <summary className="cursor-pointer text-sm font-semibold text-emerald-300">Why this recommendation?</summary>
                      <div className="mt-3 space-y-3 text-sm">
                        <div>
                          <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Why selected</div>
                          <ul className="space-y-1 text-slate-300">
                            {(rec.validation.why_selected || []).map((point, i) => (
                              <li key={i} className="flex gap-2"><span className="text-emerald-400">•</span><span>{point}</span></li>
                            ))}
                          </ul>
                        </div>

                        {(rec.validation.why_better_than_alternatives || []).length > 0 && (
                          <div>
                            <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Why better than alternatives</div>
                            <ul className="space-y-1 text-slate-300">
                              {(rec.validation.why_better_than_alternatives || []).map((point, i) => (
                                <li key={i} className="flex gap-2"><span className="text-sky-400">•</span><span>{point}</span></li>
                              ))}
                            </ul>
                          </div>
                        )}

                        <div className="grid grid-cols-2 gap-3">
                          <div className="rounded-xl bg-slate-950 p-2">
                            <div className="text-xs text-slate-500">Expected delay</div>
                            <div className="font-semibold text-white">{rec.validation.delay_reduction_summary}</div>
                          </div>
                          <div className="rounded-xl bg-slate-950 p-2">
                            <div className="text-xs text-slate-500">Deadline probability</div>
                            <div className="font-semibold text-white">{rec.validation.probability_improvement_summary}</div>
                          </div>
                        </div>

                        <div>
                          <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Confidence: {rec.validation.confidence_label}</div>
                          <div className="text-xs text-slate-400">{rec.validation.confidence_reasoning}</div>
                        </div>

                        {(rec.validation.trade_offs || []).length > 0 && (
                          <div>
                            <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Trade-offs</div>
                            <ul className="space-y-1">
                              {(rec.validation.trade_offs || []).map((t, i) => (
                                <li key={i} className="flex gap-2 text-xs">
                                  <span className={t.severity === 'significant' ? 'text-rose-400' : t.severity === 'moderate' ? 'text-amber-400' : 'text-slate-500'}>●</span>
                                  <span className="text-slate-300">{t.description}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </details>
                  )}
                </div>

                <div className="flex flex-col items-end gap-2">
                  <label className="inline-flex items-center gap-2 text-sm text-slate-400">
                    <input type="checkbox" checked={selected.includes(rec.recommendation_id)} onChange={()=>toggleSelect(rec.recommendation_id)} />
                    <span>Select</span>
                  </label>
                  <button onClick={()=>simulate(rec.recommendation_id)} disabled={!!simulatingId} className="rounded-2xl border border-sky-500 bg-sky-500/10 px-3 py-1 text-sm font-semibold text-sky-200">{simulatingId===rec.recommendation_id ? 'Simulating…' : 'Simulate this fix'}</button>
                </div>
              </div>

              {simulationResult && simulationResult.recommendation_id === rec.recommendation_id && (
                <div className="mt-4 rounded-2xl border border-emerald-500 bg-emerald-500/5 p-3">
                  <div className="text-sm text-slate-300">Simulation result</div>
                  <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
                    <div className="rounded-2xl bg-slate-900 p-2 text-center">
                      <div className="text-xs text-slate-400">On-time probability</div>
                      <div className="text-lg font-semibold text-white">{Math.round((simulationResult.after_probability||0)*100)}% <span className="text-slate-400">(was {Math.round((simulationResult.baseline_probability||0)*100)}%)</span></div>
                    </div>
                    <div className="rounded-2xl bg-slate-900 p-2 text-center">
                      <div className="text-xs text-slate-400">Expected delay</div>
                      <div className="text-lg font-semibold text-white">{(simulationResult.after_delay_days||0).toFixed(1)}d <span className="text-slate-400">(was {(simulationResult.baseline_delay_days||0).toFixed(1)}d)</span></div>
                    </div>
                    <div className="rounded-2xl bg-slate-900 p-2 text-center">
                      <div className="text-xs text-slate-400">Risk score</div>
                      <div className="text-lg font-semibold text-white">{Math.round(simulationResult.after_risk_score||0)} <span className="text-slate-400">(was {Math.round(simulationResult.baseline_risk_score||0)})</span></div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {simulationResult && simulationResult.recommendation_id == null && simulationResult.scenario_recommendation_ids && simulationResult.scenario_recommendation_ids.length > 0 && (
        <section className="rounded-3xl border border-emerald-500 bg-emerald-500/5 p-6">
          <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Scenario result</p>
          <div className="mt-1 text-sm text-slate-300">Applied: {simulationResult.scenario_recommendation_ids.join(', ')}</div>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-2xl bg-slate-900 p-3 text-center">
              <div className="text-xs text-slate-400">On-time probability</div>
              <div className="text-lg font-semibold text-white">
                {Math.round((simulationResult.after_probability||0)*100)}%{' '}
                <span className="text-slate-400">(was {Math.round((simulationResult.baseline_probability||0)*100)}%)</span>
              </div>
            </div>
            <div className="rounded-2xl bg-slate-900 p-3 text-center">
              <div className="text-xs text-slate-400">Expected delay</div>
              <div className="text-lg font-semibold text-white">
                {(simulationResult.after_delay_days||0).toFixed(1)}d{' '}
                <span className="text-slate-400">(was {(simulationResult.baseline_delay_days||0).toFixed(1)}d)</span>
              </div>
            </div>
            <div className="rounded-2xl bg-slate-900 p-3 text-center">
              <div className="text-xs text-slate-400">Risk score</div>
              <div className="text-lg font-semibold text-white">
                {Math.round(simulationResult.after_risk_score||0)}{' '}
                <span className="text-slate-400">(was {Math.round(simulationResult.baseline_risk_score||0)})</span>
              </div>
            </div>
          </div>
          {simulationResult.summary && (
            <p className="mt-4 text-sm text-slate-300">{simulationResult.summary}</p>
          )}
        </section>
      )}

      {simulationResult && simulationResult.revised_sprint_plan && simulationResult.revised_sprint_plan.length > 0 && (
        <section className="rounded-3xl border border-emerald-500 bg-emerald-500/5 p-6">
          <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Revised plan</p>
          <h3 className="mt-2 text-xl font-semibold text-white">Sprint plan after applying selected actions</h3>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-700">
                  <th className="pb-2 pr-4">Item</th>
                  <th className="pb-2 pr-4">Hours</th>
                  <th className="pb-2 pr-4">Original owner</th>
                  <th className="pb-2">New owner</th>
                </tr>
              </thead>
              <tbody>
                {simulationResult.revised_sprint_plan.map(row => (
                  <tr key={row.item_id} className={`border-b border-slate-800 ${row.owner_changed ? 'bg-emerald-500/5' : ''}`}>
                    <td className="py-2 pr-4 text-white">{row.title || row.item_id}</td>
                    <td className="py-2 pr-4 text-slate-400">{row.remaining_hours}h</td>
                    <td className="py-2 pr-4 text-slate-500">{row.original_owner}</td>
                    <td className={`py-2 font-semibold ${row.owner_changed ? 'text-emerald-300' : 'text-slate-300'}`}>{row.new_owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function getRiskColor(score){
  if(score >= 80) return {bg:'bg-rose-500', textBg:'bg-rose-500/15 text-rose-200', border:'border-rose-500'}
  if(score >= 60) return {bg:'bg-amber-400', textBg:'bg-amber-400/15 text-amber-200', border:'border-amber-400'}
  if(score >= 40) return {bg:'bg-orange-400', textBg:'bg-orange-400/15 text-orange-200', border:'border-orange-400'}
  if(score >= 20) return {bg:'bg-sky-500', textBg:'bg-sky-500/15 text-sky-200', border:'border-sky-500'}
  return {bg:'bg-emerald-500', textBg:'bg-emerald-500/15 text-emerald-200', border:'border-emerald-500'}
}

function RiskPage({session}){
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [risk, setRisk] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  const fetchRisk = async ()=>{
    if(!sessionId){
      setError(new Error('Missing session id'))
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try{
      const response = await api.risk(sessionId)
      setRisk(response?.risk_analysis ?? response)
    }catch(err){
      setError(err)
    }finally{
      setLoading(false)
    }
  }

  useEffect(()=>{ fetchRisk() }, [sessionId])

  if(loading){
    return (
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Risk analysis</p>
        <div className="mt-4 text-sm text-slate-400">Loading risk results and drivers…</div>
      </section>
    )
  }

  if(error){
    return (
      <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Risk analysis</p>
            <h2 className="mt-2 text-2xl font-semibold text-rose-100">Unable to load risk data</h2>
            <p className="mt-2 text-sm text-rose-300">{error.message || 'Failed to retrieve risk insights.'}</p>
          </div>
          <button onClick={fetchRisk} className="rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
        </div>
      </section>
    )
  }

  if(!risk){
    return (
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Risk analysis</p>
        <div className="mt-4 text-sm text-slate-400">No risk insights are available for this session.</div>
      </section>
    )
  }

  const subRiskCards = [
    {key:'schedule', label:'Schedule risk', data:risk.schedule_risk},
    {key:'dependency', label:'Dependency risk', data:risk.dependency_risk},
    {key:'resource', label:'Resource risk', data:risk.resource_risk},
    {key:'scope', label:'Scope risk', data:risk.scope_risk},
  ]

  const sprintRisks = Array.isArray(risk.sprint_risks) ? [...risk.sprint_risks].sort((a,b)=>a.sprint_id - b.sprint_id) : []

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Overall risk</p>
            <h2 className="mt-2 text-4xl font-extrabold text-white">{Math.round(risk.overall_risk_score)}</h2>
            <div className={`mt-4 inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold ${getRiskColor(risk.overall_risk_score).textBg}`}>
              {risk.overall_risk_level}
            </div>

          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">


          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Risk breakdown</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">Risk by category</h2>
          </div>

        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {subRiskCards.map(item => (
            <SubRiskCard key={item.key} label={item.label} score={item.data?.score} reasons={item.data?.reasons || []} />
          ))}
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <TopRiskDriversPanel drivers={risk.top_risk_drivers || []} />
        <SprintRiskChart sprintRisks={sprintRisks} />
      </div>
    </div>
  )
}

function SubRiskCard({label, score, reasons}){
  const displayScore = typeof score === 'number' ? Math.round(score) : 0
  const color = getRiskColor(displayScore)

  return (
    <div className="rounded-3xl border border-slate-700 bg-slate-950/80 p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm uppercase tracking-[0.2em] text-slate-400">{label}</div>
          <div className="mt-3 text-3xl font-semibold text-white">{displayScore}</div>
        </div>
        <div className={`rounded-full px-3 py-1 text-xs font-semibold ${color.textBg}`}>
          {displayScore}
        </div>
      </div>
      <div className="mt-4 h-3 rounded-full bg-slate-800">
        <div className={`${color.bg} h-3 rounded-full`} style={{ width: `${displayScore}%` }} />
      </div>
      <details className="mt-5 rounded-3xl border border-slate-800 bg-slate-900/80 p-4 text-sm text-slate-300">
        <summary className="cursor-pointer font-semibold text-slate-100">View reasons ({reasons.length})</summary>
        <ul className="mt-3 space-y-2 text-slate-300">
          {reasons.length > 0 ? reasons.map((reason, index) => (
            <li key={index} className="list-disc pl-5">{reason}</li>
          )) : (
            <li className="text-slate-500">No recorded reasons.</li>
          )}
        </ul>
      </details>
    </div>
  )
}

function TopRiskDriversPanel({drivers}){
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-950/80 p-6 shadow-inner shadow-black/20">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Top risk drivers</p>
          <h2 className="mt-2 text-2xl font-semibold text-white">What should be fixed first</h2>
          <p className="mt-2 text-sm text-slate-400">Ranked list of the highest-impact risks across the project.</p>
        </div>
        <div className="rounded-3xl bg-slate-900/80 px-4 py-3 text-sm text-slate-300">Showing top {Math.min(drivers.length, 10)} drivers</div>
      </div>

      <div className="mt-6 space-y-4">
        {drivers.map((driver, index) => (
          <div key={`${driver.title}-${index}`} className="rounded-3xl border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-slate-500">#{index + 1} · {driver.category}</div>
                <h3 className="mt-2 text-lg font-semibold text-white">{driver.title}</h3>
              </div>
              <div className="rounded-full bg-slate-800 px-3 py-1 text-sm font-semibold text-slate-100">Score {Math.round(driver.score)}</div>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div>
                <div className="text-sm uppercase tracking-[0.2em] text-slate-500">Why this matters</div>
                <p className="mt-2 text-sm leading-6 text-slate-300">{driver.description}</p>
              </div>
              <div>
                <div className="text-sm uppercase tracking-[0.2em] text-slate-500">Recommended action</div>
                <p className="mt-2 text-sm leading-6 text-slate-300">{driver.recommendation_hint}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function SprintRiskChart({sprintRisks}){
  const chartItems = sprintRisks.slice(0, 12)

  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-950/80 p-6 shadow-inner shadow-black/20">
      <div>
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Sprint risks</p>
        <h2 className="mt-2 text-2xl font-semibold text-white">Risk trend by sprint</h2>
        <p className="mt-2 text-sm text-slate-400">Per-sprint risk score helps judges see when risk peaks across the timeline.</p>
      </div>

      <div className="mt-6 space-y-4">
        <div className="grid gap-3">
          {chartItems.map(item => (
            <div key={item.sprint_id} className="space-y-2">
              <div className="flex items-center justify-between text-sm text-slate-300">
                <span>Sprint {item.sprint_id}</span>
                <span>{Math.round(item.risk_score)}</span>
              </div>
              <div className="h-3 rounded-full bg-slate-800">
                <div className={`${getRiskColor(item.risk_score).bg} h-3 rounded-full`} style={{ width: `${Math.round(item.risk_score)}%` }} />
              </div>
            </div>
          ))}
        </div>
        {sprintRisks.length === 0 && <div className="text-sm text-slate-500">Sprint risk details are not available.</div>}
      </div>
    </section>
  )
}

function CriticalPathPage({session}){
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [deps, setDeps] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  const fetchDependencies = async ()=>{
    if(!sessionId){
      setError(new Error('Missing session id'))
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)
    try{
      const response = await api.dependencies(sessionId)
      setDeps(response)
    }catch(err){
      setError(err)
    }finally{
      setLoading(false)
    }
  }

  useEffect(()=>{ fetchDependencies() }, [sessionId])

  if(loading){
    return (
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Critical path</p>
        <div className="mt-4 text-sm text-slate-400">Loading dependency graph and critical path details…</div>
      </section>
    )
  }

  if(error){
    return (
      <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Critical path</p>
            <h2 className="mt-2 text-2xl font-semibold text-rose-100">Unable to load dependency analysis</h2>
            <p className="mt-2 text-sm text-rose-300">{error.message || 'Failed to retrieve critical path data.'}</p>
          </div>
          <button onClick={fetchDependencies} className="rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
        </div>
      </section>
    )
  }

  if(!deps){
    return (
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Critical path</p>
        <div className="mt-4 text-sm text-slate-400">No dependency analysis is available for this session.</div>
      </section>
    )
  }

  const chain = Array.isArray(deps.critical_path) ? deps.critical_path : []
  const highRisk = Array.isArray(deps.high_risk_items) ? deps.high_risk_items : []
  const mediumRisk = Array.isArray(deps.medium_risk_items) ? deps.medium_risk_items : []
  const lowRisk = Array.isArray(deps.low_risk_items) ? deps.low_risk_items : []

  const renderIdNode = (id, index) => (
    <div key={id + index} className="inline-flex items-center gap-4">
      <div className="rounded-3xl border border-slate-700 bg-slate-950/90 px-4 py-3 text-sm font-semibold text-white shadow-sm shadow-black/20">{id}</div>
      {index < chain.length - 1 && <span className="text-slate-500">→</span>}
    </div>
  )

  return (
    <div className="space-y-6">
      {deps.has_cycles && (
        <section className="rounded-3xl border border-rose-500 bg-rose-950/80 p-6 text-slate-100 shadow-inner shadow-black/20">
          <div className="flex items-start gap-3">
            <div className="mt-1 rounded-full bg-rose-500/10 px-3 py-1 text-sm font-semibold text-rose-200">Warning</div>
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Circular dependency detected</p>
              <h2 className="mt-2 text-lg font-semibold text-white">The dependency graph contains cycles.</h2>
              <p className="mt-2 text-sm text-slate-300">A circular dependency can prevent the schedule from resolving. Investigate the listed items and break dependency loops.</p>
            </div>
          </div>
        </section>
      )}

      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Critical path</p>
            <h2 className="mt-2 text-3xl font-extrabold text-white">Project critical path</h2>

          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Path duration" value={`${deps.critical_path_duration_days?.toFixed(1) ?? '—'} days`} />
            <MetricCard label="Items on path" value={deps.critical_path_item_count ?? chain.length} />
            <MetricCard label="Growth vs baseline" value={`${deps.critical_path_growth_percent?.toFixed(1) ?? '—'}%`} />
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-slate-700 bg-slate-950/80 p-6 shadow-inner shadow-black/20">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Dependency chain</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">Ordered critical path</h2>
          </div>

        </div>
        <div className="mt-6 overflow-x-auto pb-2">
          <div className="inline-flex items-center gap-3 whitespace-nowrap">
            {chain.length > 0 ? chain.map(renderIdNode) : (
              <span className="text-slate-400">Critical path is not available for this session.</span>
            )}
          </div>
        </div>
      </section>

      {highRisk.length > 0 && (
        <section className="rounded-3xl border border-rose-500/40 bg-rose-950/20 p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-rose-400">High risk items on critical path</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {highRisk.map((id, i) => (
              <span key={i} className="rounded-full border border-rose-500/30 bg-rose-500/10 px-3 py-1 text-sm font-semibold text-rose-200">{id}</span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function RiskGroupList({title, items, color}){
  const colorStyles = {
    rose: 'bg-rose-500/10 text-rose-200 border-rose-500/20',
    amber: 'bg-amber-500/10 text-amber-200 border-amber-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-200 border-emerald-500/20',
  }

  return (
    <div className="rounded-3xl border border-slate-700 bg-slate-950/80 p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm uppercase tracking-[0.2em] text-slate-400">{title}</div>
          <div className="mt-2 text-3xl font-semibold text-white">{items.length}</div>
        </div>
        <div className={`rounded-full px-3 py-1 text-xs font-semibold ${colorStyles[color]}`}>{title.split(' ')[0]}</div>
      </div>
      <div className="mt-5 space-y-2">
        {items.length > 0 ? items.map((itemId, index) => (
          <div key={`${itemId}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-3 text-sm text-slate-200">
            {itemId}
          </div>
        )) : (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-3 text-sm text-slate-500">No items in this group.</div>
        )}
      </div>
    </div>
  )
}

function SectionPlaceholder({title, description}){
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-8 shadow-inner shadow-black/20">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">{title}</p>
      <h2 className="mt-2 text-3xl font-semibold text-white">{title} content coming soon</h2>
      <p className="mt-3 text-sm text-slate-400">{description}</p>
    </section>
  )
}

export function Dashboard({session, onReset}){
  const [active, setActive] = useState('overview')

  const sessionId = session?.project_summary?.session_id || ''


  if (!session) return null

  return (
    <div className="space-y-6">
      <div style={{
        border: '1px solid var(--line)',
        borderRadius: '9px',
        padding: '11px 12px 0',
        background: 'oklch(14% .034 255)',
      }}>
        <div className="flex justify-between items-start">
          <div>
            <div className="text-[8px] font-extrabold tracking-[0.18em] uppercase text-[var(--orange)]">Session dashboard</div>
            <div className="text-[16px] font-extrabold tracking-tight mt-1">Project analytics</div>
          </div>
          <button onClick={onReset} style={{ border: '1px solid var(--pink)', borderRadius: 4, padding: '5px 8px', fontSize: 9, cursor: 'pointer', background: 'transparent', color: 'var(--pink)' }}>
            New Project
          </button>
        </div>

        <nav className="flex gap-[5px] overflow-x-auto mt-2.5">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActive(tab.key)}
              style={{
                border: `1px solid ${active === tab.key ? 'var(--orange)' : 'var(--line2)'}`,
                borderBottom: 0,
                borderRadius: '999px 999px 0 0',
                background: active === tab.key ? 'var(--orange)' : 'var(--panel)',
                color: active === tab.key ? 'var(--bg)' : 'var(--muted)',
                padding: '5px 10px',
                fontSize: 9,
                fontWeight: active === tab.key ? 800 : 400,
                whiteSpace: 'nowrap',
                cursor: 'pointer',
              }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {active === 'delivery_intelligence' && <ManagementSummary session={session} />}
      {active === 'overview' && <>
        <OverviewPage session={session} onNavigate={setActive} />
        <DelayDiagnosis session={session} />
      </>}
      {active === 'recommendations' && <RecommendationsPage session={session} onNavigate={setActive} />}

      {active === 'recovery-plans' && <RecoveryPlansPage session={session} />}
      {active === 'export' && <ExportPage session={session} />}
      {active === 'sprint-health' && <SprintHealth session={session} />}
      {active === 'reasoning-trace' && <ReasoningTrace session={session} />}
    </div>
  )
}
