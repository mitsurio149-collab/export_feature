import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../../api/client'

// ─── Constants ────────────────────────────────────────────────────────────────
const RC_META = {
  GENUINE_SKILL_MISMATCH:         { label: 'Genuine Skill Mismatch',        color: 'rose',   icon: '🚫', tip: 'Owner has no domain connection to this skill' },
  RELATED_SKILL_COMPETENCY_GAP:   { label: 'Related Skill — Competency Gap', color: 'orange', icon: '📈', tip: 'Right domain family, but depth not yet sufficient' },
  COMPETENCY_GAP_HIGH:            { label: 'Competency Gap — Critical',      color: 'rose',   icon: '⚠',  tip: 'Skill matched but severely underestimated complexity' },
  COMPETENCY_GAP_MEDIUM:          { label: 'Competency Gap — Moderate',      color: 'amber',  icon: '📊', tip: 'Skill matched but systematically underestimating' },
  DEPENDENCY_BLOCKED:             { label: 'Dependency Blocked',             color: 'sky',    icon: '🔗', tip: 'Upstream dependency was not ready at sprint start' },
  EXTERNAL_BLOCKER:               { label: 'External Blocker',               color: 'rose',   icon: '🚧', tip: 'Third-party or toolchain blocker prevented progress' },
  CAPACITY_SQUEEZE_NOT_STARTED:   { label: 'Capacity Squeeze — Not Started', color: 'amber',  icon: '⏱',  tip: 'Item could not start due to overcommitment' },
  CAPACITY_OVERCOMMIT:            { label: 'Capacity Overcommit',            color: 'amber',  icon: '🔴', tip: 'Sprint was overcommitted for this person' },
  ESTIMATION_DRIFT:               { label: 'Estimation Drift',               color: 'amber',  icon: '📉', tip: 'Systematic underestimation in this task category' },
  MINOR_VARIANCE:                 { label: 'Minor Variance',                 color: 'slate',  icon: '✓',  tip: 'Within acceptable estimation noise' },
}

const HEALTH = {
  NEEDS_IMPROVEMENT: { cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40',   dot: 'bg-rose-400' },
  WATCH:             { cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40',  dot: 'bg-amber-400' },
  MINOR_ISSUES:      { cls: 'bg-sky-500/15 text-sky-300 border-sky-500/40',       dot: 'bg-sky-400' },
  GOOD:              { cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40', dot: 'bg-emerald-400' },
}

const PRIORITY_CLS = {
  CRITICAL: 'bg-rose-500/20 text-rose-200 border border-rose-500/40',
  HIGH:     'bg-orange-500/20 text-orange-200 border border-orange-500/40',
  MEDIUM:   'bg-amber-500/20 text-amber-200 border border-amber-500/40',
  INFO:     'bg-slate-700 text-slate-300 border border-slate-600',
}

const COLOR_CLS = {
  rose:   { bg: 'bg-rose-500/15',   text: 'text-rose-300',   border: 'border-rose-500/30' },
  orange: { bg: 'bg-orange-500/15', text: 'text-orange-300', border: 'border-orange-500/30' },
  amber:  { bg: 'bg-amber-500/15',  text: 'text-amber-300',  border: 'border-amber-500/30' },
  sky:    { bg: 'bg-sky-500/15',    text: 'text-sky-300',    border: 'border-sky-500/30' },
  slate:  { bg: 'bg-slate-700',     text: 'text-slate-300',  border: 'border-slate-600' },
  emerald:{ bg: 'bg-emerald-500/15',text: 'text-emerald-300',border: 'border-emerald-500/30' },
}

function cx(...args) { return args.filter(Boolean).join(' ') }

// ─── Shared components ────────────────────────────────────────────────────────
function Badge({ children, color = 'slate', size = 'sm' }) {
  const palette = {
    rose: { color: 'var(--pink)', border: '1px solid var(--line)' },
    orange: { color: 'var(--orange)', border: '1px solid var(--line)' },
    amber: { color: 'var(--orange)', border: '1px solid var(--line)' },
    sky: { color: 'var(--teal)', border: '1px solid var(--line)' },
    emerald: { color: 'var(--teal)', border: '1px solid var(--line)' },
    slate: { color: 'var(--muted)', border: '1px solid var(--line)' },
  }
  const active = palette[color] || palette.slate
  const pad = size === 'xs' ? { padding: '2px 6px', fontSize: 9 } : { padding: '4px 8px', fontSize: 9, fontWeight: 700 }
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, borderRadius: 999, border: active.border, color: active.color, background: 'var(--panel2)', ...pad }}>{children}</span>
}

function SkillPill({ required, primary, secondary, exact, affinity }) {
  const color = exact ? 'emerald' : affinity ? 'amber' : 'rose'
  const label = exact ? 'Exact match' : affinity ? 'Related skill' : 'Mismatch'
  return (
    <div className="flex flex-wrap items-center gap-2" style={{ fontSize: 9 }}>
      <span style={{ color: 'var(--muted)' }}>Required:</span>
      <span style={{ color: 'var(--text)', fontWeight: 700 }}>{required}</span>
      <span style={{ color: 'var(--line)' }}>|</span>
      <span style={{ color: 'var(--muted)' }}>Owner primary:</span>
      <span style={{ color: 'var(--text)' }}>{primary}</span>
      {secondary && <><span style={{ color: 'var(--line)' }}>·</span><span style={{ color: 'var(--muted)' }}>{secondary}</span></>}
      <Badge color={color} size="xs">{color === 'emerald' ? '✓' : color === 'amber' ? '≈' : '✗'} {label}</Badge>
    </div>
  )
}

function OverrunBar({ est, actual }) {
  if (!est || !actual) return null
  const overrunPct = Math.round((actual / est - 1) * 100)
  const barMax = Math.max(actual, est)
  const estW = Math.round((est / barMax) * 100)
  const actW = Math.round((actual / barMax) * 100)
  const color = overrunPct > 50 ? 'bg-rose-500' : overrunPct > 25 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between" style={{ fontSize: 9 }}>
        <span style={{ color: 'var(--muted)' }}>{est}h estimated</span>
        <span style={{ fontWeight: 700, color: overrunPct > 50 ? 'var(--pink)' : overrunPct > 25 ? 'var(--orange)' : 'var(--teal)' }}>
          {actual}h actual {overrunPct > 0 ? `(+${overrunPct}%)` : ''}
        </span>
      </div>
      <div className="relative h-2 overflow-hidden" style={{ borderRadius: 999, background: 'var(--panel2)' }}>
        <div className="absolute h-2 transition-all" style={{ width: `${estW}%`, borderRadius: 999, background: 'var(--line)' }} />
        <div className="absolute h-2 transition-all" style={{ width: `${actW}%`, borderRadius: 999, background: overrunPct > 50 ? 'var(--pink)' : overrunPct > 25 ? 'var(--orange)' : 'var(--teal)' }} />
      </div>
    </div>
  )
}

// ─── Item detail card ─────────────────────────────────────────────────────────
function ItemCard({ item, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const rc = RC_META[item.root_cause] || RC_META.MINOR_VARIANCE
  const c  = COLOR_CLS[rc.color] || COLOR_CLS.slate
  const sev = item.severity === 'HIGH' || item.severity === 'CRITICAL' ? 'rose'
            : item.severity === 'MEDIUM' ? 'amber' : 'slate'

  return (
    <div className="overflow-hidden" style={{ borderRadius: 7, border: open ? '1px solid var(--line)' : '1px solid var(--line)', background: 'var(--panel)' }}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start justify-between gap-3 p-4 text-left transition"
        style={{ background: 'var(--panel2)' }}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap" style={{ fontSize: 9 }}>
            <span style={{ color: 'var(--muted)' }}>{item.item_id}</span>
            {item.is_spillover && (
              <span style={{ color: 'var(--muted)' }}>S{item.from_sprint}→S{item.to_sprint}</span>
            )}
            {!item.is_spillover && (
              <span style={{ color: 'var(--muted)' }}>Sprint {item.sprint_id}</span>
            )}
          </div>
          <p className="mt-0.5 truncate" style={{ fontSize: 10, fontWeight: 700, color: 'var(--text)' }}>{item.item_title}</p>
          <p className="mt-0.5" style={{ fontSize: 9, color: 'var(--muted)' }}>{item.owner?.replace(/_/g,' ')}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5 flex-none">
          <span className="rounded-full border" style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', border: '1px solid var(--line)', background: 'var(--panel)', color: c.text }}>
            {rc.icon} {rc.label}
          </span>
          {item.overrun_pct !== null && item.overrun_pct !== undefined && (
            <span className="rounded-full" style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', color: item.overrun_pct > 50 ? 'var(--pink)' : item.overrun_pct > 25 ? 'var(--orange)' : 'var(--text)', background: item.overrun_pct > 50 ? 'rgba(226, 90, 123, 0.12)' : item.overrun_pct > 25 ? 'rgba(255, 151, 80, 0.12)' : 'var(--panel2)' }}>
              {item.overrun_pct > 0 ? `+${item.overrun_pct}%` : `${item.overrun_pct}%`}
            </span>
          )}
          <span style={{ color: 'var(--muted)', fontSize: 9 }}>{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4 pt-3" style={{ borderTop: '1px solid var(--line)' }}>
          <SkillPill required={item.required_skill} primary={item.owner_primary} secondary={item.owner_secondary} exact={item.exact_skill_match} affinity={item.affinity_match} />

          {item.actual_hrs > 0 && <OverrunBar est={item.estimated_hrs} actual={item.actual_hrs} />}
          {item.actual_hrs === 0 && item.estimated_hrs > 0 && (
            <div className="font-semibold" style={{ fontSize: 9, color: 'var(--orange)' }}>⏱ {item.estimated_hrs}h planned — item was not started this sprint</div>
          )}

          <div className="p-3" style={{ borderRadius: 7, background: 'var(--panel2)', border: '1px solid var(--line)' }}>
            <div className="mb-1.5 uppercase" style={{ fontSize: 9, letterSpacing: '0.12em', color: 'var(--muted)' }}>Root cause analysis</div>
            <p style={{ fontSize: 10, color: 'var(--text)', lineHeight: 1.6 }}>{item.explanation}</p>
          </div>

          <div className="p-3" style={{ borderRadius: 7, background: 'rgba(115, 225, 178, 0.08)', border: '1px solid rgba(115, 225, 178, 0.26)' }}>
            <div className="mb-1.5 uppercase" style={{ fontSize: 9, letterSpacing: '0.12em', color: 'var(--teal)' }}>Preventive action</div>
            <p style={{ fontSize: 10, color: 'var(--text)', lineHeight: 1.6 }}>{item.prevention}</p>
          </div>

          {item.metric_to_track && (
            <div className="flex items-start gap-2" style={{ fontSize: 9, color: 'var(--muted)' }}>
              <span className="flex-none font-semibold mt-0.5" style={{ color: 'var(--teal)' }}>📏 Track:</span>
              <span>{item.metric_to_track}</span>
            </div>
          )}
          {item.sprint_action && (
            <div className="flex items-start gap-2" style={{ fontSize: 9, color: 'var(--muted)' }}>
              <span className="flex-none font-semibold mt-0.5" style={{ color: 'var(--orange)' }}>⚡ Next sprint:</span>
              <span>{item.sprint_action}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Person card ──────────────────────────────────────────────────────────────
function PersonCard({ person, selected, onSelect }) {
  const h = HEALTH[person.health] || HEALTH.GOOD
  return (
    <button
      onClick={() => onSelect(person)}
      className="w-full p-4 text-left transition"
      style={{ borderRadius: 7, border: selected ? '1px solid var(--orange)' : '1px solid var(--line)', background: selected ? 'rgba(255, 151, 80, 0.08)' : 'var(--panel)', boxShadow: selected ? 'inset 0 0 0 1px rgba(255, 151, 80, 0.18)' : 'none' }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate" style={{ fontSize: 10, fontWeight: 700, color: 'var(--text)' }}>{person.resource_id.replace(/_/g,' ')}</div>
          <div className="mt-0.5 truncate" style={{ fontSize: 9, color: 'var(--muted)' }}>{person.primary_skill}</div>
        </div>
        <span className="flex-none rounded-full border" style={{ fontSize: 9, fontWeight: 700, padding: '4px 8px', border: '1px solid var(--line)', color: 'var(--text)', background: 'var(--panel2)' }}>
          {person.health_label}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-1">
        {[
          { label: 'Assigned', val: person.total_assigned },
          { label: 'Issues',   val: person.total_issues, color: person.total_issues > 3 ? 'var(--pink)' : person.total_issues > 1 ? 'var(--orange)' : 'var(--text)' },
          { label: 'Overrun',  val: person.avg_overrun_pct > 0 ? `${person.avg_overrun_pct}%` : '—', color: person.avg_overrun_pct > 40 ? 'var(--pink)' : person.avg_overrun_pct > 20 ? 'var(--orange)' : 'var(--text)' },
        ].map(({ label, val, color }) => (
          <div key={label} className="py-1.5 text-center" style={{ borderRadius: 7, background: 'var(--panel2)' }}>
            <div style={{ fontSize: 9, color: 'var(--muted)' }}>{label}</div>
            <div style={{ fontSize: 10, fontWeight: 700, color: color || 'var(--text)' }}>{val}</div>
          </div>
        ))}
      </div>

      {person.high_severity_count > 0 && (
        <div className="mt-2">
          <Badge color="rose" size="xs">⚠ {person.high_severity_count} high severity</Badge>
        </div>
      )}
    </button>
  )
}

// ─── Person detail ────────────────────────────────────────────────────────────
function PersonDetail({ person, spilloverItems, overbillingItems }) {
  const mySpillover   = spilloverItems.filter(s => s.owner === person.resource_id)
  const myOverbilling = overbillingItems.filter(o => o.owner === person.resource_id)
  const h = HEALTH[person.health] || HEALTH.GOOD

  return (
    <div className="space-y-4">
      <div className="p-5" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel)' }}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 style={{ fontSize: 13, fontWeight: 800, color: 'var(--text)' }}>{person.resource_id.replace(/_/g,' ')}</h3>
            <p className="mt-0.5" style={{ fontSize: 10, color: 'var(--muted)' }}>{person.primary_skill}</p>
            {person.secondary_skill && <p className="mt-0.5" style={{ fontSize: 9, color: 'var(--muted)' }}>Also: {person.secondary_skill}</p>}
          </div>
          <span className="rounded-full border" style={{ fontSize: 10, fontWeight: 700, padding: '4px 8px', border: '1px solid var(--line)', color: 'var(--text)', background: 'var(--panel2)' }}>{person.health_label}</span>
        </div>

        {person.total_assigned > 0 && (
          <div className="mt-4 space-y-1.5">
            <div className="flex justify-between" style={{ fontSize: 9, color: 'var(--muted)' }}>
              <span>{person.completed_count} of {person.total_assigned} items completed</span>
              <span style={{ fontWeight: 700, color: 'var(--text)' }}>{Math.round(person.completed_count / person.total_assigned * 100)}%</span>
            </div>
            <div className="h-2 overflow-hidden" style={{ borderRadius: 999, background: 'var(--panel2)' }}>
              <div className="h-2 transition-all" style={{ width: `${Math.round(person.completed_count / person.total_assigned * 100)}%`, borderRadius: 999, background: 'var(--teal)' }} />
            </div>
          </div>
        )}

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { l: 'Assigned',   v: person.total_assigned },
            { l: 'Completed',  v: person.completed_count, color: person.completed_count > 0 ? 'var(--teal)' : 'var(--muted)' },
            { l: 'Avg overrun',v: `${person.avg_overrun_pct}%`, color: person.avg_overrun_pct > 40 ? 'var(--pink)' : person.avg_overrun_pct > 20 ? 'var(--orange)' : 'var(--teal)' },
            { l: 'Issues',     v: person.total_issues, color: person.total_issues > 3 ? 'var(--pink)' : person.total_issues > 1 ? 'var(--orange)' : 'var(--text)' },
          ].map(({ l, v, color }) => (
            <div key={l} className="p-3 text-center" style={{ borderRadius: 7, background: 'var(--panel2)', border: '1px solid var(--line)' }}>
              <div style={{ fontSize: 9, color: 'var(--muted)' }}>{l}</div>
              <div style={{ marginTop: 4, fontSize: 13, fontWeight: 800, color: color || 'var(--text)' }}>{v}</div>
            </div>
          ))}
        </div>

        {Object.keys(person.root_cause_breakdown).length > 0 && (
          <div className="mt-4">
            <div className="mb-2 uppercase" style={{ fontSize: 9, letterSpacing: '0.12em', color: 'var(--muted)' }}>Issues breakdown</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(person.root_cause_breakdown).map(([rc, cnt]) => {
                const m = RC_META[rc] || { label: rc, color: 'slate', icon: '•' }
                return <Badge key={rc} color={m.color} size="xs">{m.icon} {m.label} ({cnt})</Badge>
              })}
            </div>
          </div>
        )}
      </div>

      {person.action_plan?.length > 0 && (
        <div className="p-5" style={{ borderRadius: 7, border: '1px solid rgba(255, 151, 80, 0.24)', background: 'rgba(255, 151, 80, 0.08)' }}>
          <p className="mb-3 uppercase" style={{ fontSize: 9, letterSpacing: '0.15em', color: 'var(--orange)' }}>Action Plan for {person.resource_id.replace(/_/g,' ')}</p>
          <div className="space-y-3">
            {person.action_plan.filter(a => a.priority !== 'INFO').map((a, i) => (
              <div key={i} className="flex gap-3">
                <span className="flex-none rounded-full mt-0.5 h-fit" style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', border: '1px solid var(--line)', color: 'var(--text)', background: 'var(--panel2)' }}>
                  {a.priority}
                </span>
                <div>
                  <div className="mb-0.5 uppercase" style={{ fontSize: 9, letterSpacing: '0.1em', color: 'var(--muted)' }}>{a.type.replace(/_/g,' ')}</div>
                  <p style={{ fontSize: 10, color: 'var(--text)', lineHeight: 1.6 }}>{a.action}</p>
                </div>
              </div>
            ))}
            {person.action_plan.every(a => a.priority === 'INFO') && (
              <p style={{ fontSize: 10, color: 'var(--teal)' }}>{person.action_plan[0]?.action}</p>
            )}
          </div>
        </div>
      )}

      {mySpillover.length > 0 && (
        <div className="p-5" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel)' }}>
          <p className="mb-3 uppercase" style={{ fontSize: 9, letterSpacing: '0.15em', color: 'var(--muted)' }}>Spillover items ({mySpillover.length})</p>
          <div className="space-y-2">
            {mySpillover.map(s => <ItemCard key={s.item_id} item={s} />)}
          </div>
        </div>
      )}

      {myOverbilling.length > 0 && (
        <div className="p-5" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel)' }}>
          <p className="mb-3 uppercase" style={{ fontSize: 9, letterSpacing: '0.15em', color: 'var(--muted)' }}>Overbilling items ({myOverbilling.length})</p>
          <div className="space-y-2">
            {myOverbilling.map(o => <ItemCard key={o.item_id + o.sprint_id} item={o} />)}
          </div>
        </div>
      )}

      {person.health === 'GOOD' && mySpillover.length === 0 && myOverbilling.length === 0 && (
        <div className="p-6 text-center" style={{ borderRadius: 7, border: '1px solid rgba(115, 225, 178, 0.24)', background: 'rgba(115, 225, 178, 0.08)' }}>
          <p style={{ fontSize: 13, fontWeight: 700, color: 'var(--teal)' }}>✓ No issues detected</p>
          <p className="mt-1" style={{ fontSize: 10, color: 'var(--muted)' }}>No spillover or overbilling events in analysed sprints.</p>
        </div>
      )}
    </div>
  )
}

// ─── Summary bar ──────────────────────────────────────────────────────────────
function SummaryBar({ summary }) {
  const dist = summary.root_cause_distribution || {}
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1
  const segments = [
    { key: 'GENUINE_SKILL_MISMATCH',       color: 'var(--pink)',   label: 'Skill mismatch' },
    { key: 'RELATED_SKILL_COMPETENCY_GAP', color: 'var(--orange)', label: 'Related skill gap' },
    { key: 'COMPETENCY_GAP_HIGH',          color: 'var(--pink)',   label: 'Comp. gap (high)' },
    { key: 'COMPETENCY_GAP_MEDIUM',        color: 'var(--orange)',  label: 'Comp. gap (med)' },
    { key: 'CAPACITY_SQUEEZE_NOT_STARTED', color: 'var(--orange)',  label: 'Not started' },
    { key: 'CAPACITY_OVERCOMMIT',          color: 'var(--orange)',  label: 'Overcommit' },
    { key: 'DEPENDENCY_BLOCKED',           color: 'var(--teal)',    label: 'Dependency' },
    { key: 'EXTERNAL_BLOCKER',             color: 'var(--teal)',    label: 'Blocker' },
    { key: 'ESTIMATION_DRIFT',             color: 'var(--muted)',  label: 'Estimation drift' },
    { key: 'MINOR_VARIANCE',               color: 'var(--line)',  label: 'Minor variance' },
  ].filter(s => dist[s.key] > 0)

  return (
    <section className="p-6" style={{ border: '1px solid var(--line)', borderRadius: 8, background: 'var(--panel)' }}>
      <div className="flex flex-col gap-1">
        <p className="uppercase" style={{ fontSize: 9, letterSpacing: '0.3em', color: 'var(--orange)' }}>Sprint Health</p>
        <h2 style={{ fontSize: 13, fontWeight: 800, color: 'var(--text)' }}>
          {summary.sprints_analysed} sprints · {summary.total_wasted_hrs}h wasted effort
        </h2>
        <p style={{ fontSize: 10, color: 'var(--muted)' }}>{summary.overall_summary}</p>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Spillover items',    val: summary.total_spillover,   color: 'var(--orange)' },
          { label: 'Overbilling items',  val: summary.total_overbilling,  color: 'var(--pink)' },
          { label: 'Hours wasted',       val: `${summary.total_wasted_hrs}h`, color: 'var(--pink)' },
          { label: 'People to act on',   val: summary.people_critical + summary.people_watch,
            color: summary.people_critical > 0 ? 'var(--pink)' : 'var(--orange)' },
        ].map(({ label, val, color }) => (
          <div key={label} className="p-4" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel2)' }}>
            <div className="uppercase" style={{ fontSize: 9, letterSpacing: '0.12em', color: 'var(--muted)' }}>{label}</div>
            <div className="mt-1" style={{ fontSize: 13, fontWeight: 800, color }}>{val}</div>
          </div>
        ))}
      </div>

      <div className="mt-5">
        <div className="mb-2 uppercase" style={{ fontSize: 9, letterSpacing: '0.12em', color: 'var(--muted)' }}>Root cause distribution</div>
        <div className="flex h-3 overflow-hidden gap-px" style={{ borderRadius: 999 }}>
          {segments.map(s => (
            <div key={s.key} className="h-3 transition-all" style={{ width: `${Math.round(dist[s.key] / total * 100)}%`, background: s.color }} title={`${s.label}: ${dist[s.key]}`} />
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-3">
          {segments.map(s => (
            <div key={s.key} className="flex items-center gap-1.5" style={{ fontSize: 9, color: 'var(--muted)' }}>
              <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: s.color }} />
              {s.label} ({dist[s.key]})
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Systemic actions panel ───────────────────────────────────────────────────
const PRIORITY_CONFIG = {
  CRITICAL: { dot: 'bg-rose-500',   ring: 'border-rose-500/30',   bg: 'bg-rose-500/5',   label: 'Critical', labelCls: 'text-rose-400',   actionBorder: 'border-rose-500/20',   actionBg: 'bg-rose-500/5'   },
  HIGH:     { dot: 'bg-orange-400', ring: 'border-orange-400/30', bg: 'bg-orange-400/5', label: 'High',     labelCls: 'text-orange-400', actionBorder: 'border-orange-400/20', actionBg: 'bg-orange-400/5' },
  MEDIUM:   { dot: 'bg-amber-400',  ring: 'border-amber-400/20',  bg: 'bg-amber-400/5',  label: 'Medium',   labelCls: 'text-amber-400',  actionBorder: 'border-amber-400/20',  actionBg: 'bg-amber-400/5'  },
  INFO:     { dot: 'bg-sky-400',    ring: 'border-sky-400/20',    bg: 'bg-sky-400/5',    label: 'Info',     labelCls: 'text-sky-400',    actionBorder: 'border-sky-400/20',    actionBg: 'bg-sky-400/5'    },
}

function SystemicCard({ priority, sprint, trigger, finding, action, confidence, evidence }) {
  const [open, setOpen] = useState(false)
  const cfg = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.INFO

  return (
    <div className="overflow-hidden transition-all" style={{ borderRadius: 7, border: '1px solid var(--line)', background: open ? 'rgba(255, 151, 80, 0.08)' : 'var(--panel)' }}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-4 px-5 py-4 text-left group"
      >
        <div className="flex-none pt-1">
          <span className={cx('block w-2.5 h-2.5 rounded-full mt-0.5', cfg.dot)} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-3">
            <p style={{ fontSize: 10, fontWeight: 700, color: 'var(--text)', lineHeight: 1.4 }}>{trigger}</p>
            {sprint && (
              <span className="flex-none whitespace-nowrap mt-0.5" style={{ fontSize: 9, color: 'var(--muted)' }}>{sprint}</span>
            )}
          </div>
          <p className="mt-1.5" style={{ fontSize: 9, lineHeight: 1.5, color: cfg.labelCls.includes('text-rose') ? 'var(--pink)' : cfg.labelCls.includes('text-orange') ? 'var(--orange)' : cfg.labelCls.includes('text-amber') ? 'var(--orange)' : 'var(--muted)' }}>
            {action}
          </p>
        </div>

        <div className="flex-none pt-1 transition" style={{ color: 'var(--muted)' }}>
          <svg className={cx('w-4 h-4 transition-transform', open && 'rotate-180')} viewBox="0 0 16 16" fill="none">
            <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </button>

      {open && (
        <div className="px-5 pb-5 pt-1 space-y-4" style={{ borderTop: '1px solid var(--line)' }}>
          {finding && (
            <p style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.6 }}>{finding}</p>
          )}
          <div className="px-4 py-3" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel2)' }}>
            <p className="mb-1.5 uppercase" style={{ fontSize: 9, letterSpacing: '0.15em', fontWeight: 700, color: cfg.labelCls.includes('text-rose') ? 'var(--pink)' : cfg.labelCls.includes('text-orange') ? 'var(--orange)' : cfg.labelCls.includes('text-amber') ? 'var(--orange)' : 'var(--muted)' }}>Recommended action</p>
            <p style={{ fontSize: 10, color: 'var(--text)', lineHeight: 1.6 }}>{action}</p>
          </div>
          {evidence?.length > 0 && (
            <div className="space-y-1.5 pl-1">
              {evidence.map((e, j) => (
                <div key={j} className="flex items-start gap-2" style={{ fontSize: 9, color: 'var(--muted)' }}>
                  <span className="flex-none mt-0.5" style={{ color: 'var(--line)' }}>›</span>
                  <span>{e}</span>
                </div>
              ))}
            </div>
          )}
          {confidence != null && (
            <div className="flex justify-end">
              <Badge color={confidence > 0.7 ? 'emerald' : 'amber'} size="xs">
                {Math.round(confidence * 100)}% confident
              </Badge>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SystemicPanel({ actions, historical }) {
  if (!actions?.length && !historical?.length) return (
    <div className="rounded-3xl border border-emerald-500/30 bg-emerald-500/5 p-10 text-center">
      <p className="text-lg font-semibold text-emerald-300">✓ No systemic issues</p>
      <p className="mt-1 text-sm text-slate-500">All patterns are within acceptable range.</p>
    </div>
  )

  const priorityOrder = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, INFO: 3 }
  const sorted = [...(actions || [])].sort((a, b) =>
    (priorityOrder[a.priority] ?? 4) - (priorityOrder[b.priority] ?? 4)
  )

  // Count by priority for the summary strip
  const counts = sorted.reduce((acc, a) => {
    acc[a.priority] = (acc[a.priority] || 0) + 1
    return acc
  }, {})

  return (
    <div className="space-y-6">

      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {['CRITICAL','HIGH','MEDIUM','INFO'].map(p => {
          const cfg = PRIORITY_CONFIG[p]
          const n = counts[p] || 0
          return (
            <div key={p} className={cx(
              'rounded-2xl border px-4 py-3 flex items-center gap-3',
              n > 0 ? cfg.ring : 'border-slate-800',
              n > 0 ? cfg.bg : 'bg-slate-900/40'
            )}>
              <span className={cx('w-2.5 h-2.5 rounded-full flex-none', n > 0 ? cfg.dot : 'bg-slate-700')} />
              <div>
                <p className={cx('text-xl font-extrabold', n > 0 ? cfg.labelCls : 'text-slate-600')}>{n}</p>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">{cfg.label}</p>
              </div>
            </div>
          )
        })}
      </div>

      {/* Action cards */}
      {sorted.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500 px-1 pb-1">
            Issues requiring attention
          </p>
          {sorted.map((a, i) => (
            <SystemicCard
              key={i}
              priority={a.priority}
              sprint={a.sprint}
              trigger={a.trigger}
              finding={a.finding}
              action={a.action}
            />
          ))}
        </div>
      )}


    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export function SprintHealth({ session }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('people')

  const sessionId = session?.project_summary?.session_id || ''

  const load = useCallback(() => {
    if (!sessionId) { setError(new Error('Missing session id')); setLoading(false); return }
    setLoading(true); setError(null)
    api.sprintHealth(sessionId)
      .then(d => {
        setData(d)
        const first = (d.people || []).find(p => p.health === 'NEEDS_IMPROVEMENT')
          || (d.people || []).find(p => p.health === 'WATCH')
          || d.people?.[0]
        setSelected(first || null)
        setLoading(false)
      })
      .catch(err => { setError(err); setLoading(false) })
  }, [sessionId])

  useEffect(() => { load() }, [load])

  if (loading) return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-8 text-center">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Sprint Health</p>
      <p className="mt-3 text-sm text-slate-400">Analysing sprint history…</p>
    </section>
  )
  if (error) return (
    <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-6">
      <p className="text-rose-400 font-semibold">Sprint Health unavailable</p>
      <p className="mt-1 text-sm text-rose-300">{error.message}</p>
      <button onClick={load} className="mt-3 rounded-2xl border border-rose-500 px-4 py-2 text-sm text-rose-200">Retry</button>
    </section>
  )
  if (!data) return null

  const { summary, people, spillover_items, overbilling_items } = data
  const tabs = [
    { key: 'people',     label: `👤 Team (${people.length})` },
    { key: 'spillover',  label: `→ Spillover (${spillover_items.length})` },
    { key: 'overbilling',label: `⚠ Overbilling (${overbilling_items.length})` },
    { key: 'systemic',   label: `🛡 Systemic Actions (${summary.systemic_actions?.length || 0})` },
  ]

  return (
    <div className="space-y-4">
      <SummaryBar summary={summary} />

      <div className="flex flex-wrap gap-2">
        {tabs.map(t => (
          <button key={t.key} onClick={() => setView(t.key)}
            className={cx('rounded-full px-4 py-2 text-sm font-semibold transition whitespace-nowrap',
              view === t.key ? 'bg-amber-500 text-slate-950 shadow-lg shadow-amber-500/20' : 'bg-slate-800 text-slate-300 hover:bg-slate-700')}>
            {t.label}
          </button>
        ))}
      </div>

      {view === 'people' && (
        <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
          <div className="space-y-2">
            {people.map(p => (
              <PersonCard key={p.resource_id} person={p}
                selected={selected?.resource_id === p.resource_id}
                onSelect={setSelected} />
            ))}
          </div>
          <div>
            {selected
              ? <PersonDetail person={selected} spilloverItems={spillover_items} overbillingItems={overbilling_items} />
              : <div className="rounded-3xl border border-slate-700 bg-slate-900 p-8 text-center text-slate-500">Select a team member to see their profile</div>
            }
          </div>
        </div>
      )}

      {view === 'spillover' && (
        <div className="space-y-3">
          {spillover_items.length === 0
            ? <div className="rounded-3xl border border-emerald-500/30 bg-emerald-500/5 p-8 text-center"><p className="text-emerald-400 font-semibold">No spillover detected</p></div>
            : spillover_items.map(s => <ItemCard key={s.item_id} item={s} defaultOpen={false} />)
          }
        </div>
      )}

      {view === 'overbilling' && (
        <div className="space-y-3">
          {overbilling_items.length === 0
            ? <div className="rounded-3xl border border-emerald-500/30 bg-emerald-500/5 p-8 text-center"><p className="text-emerald-400 font-semibold">No overbilling detected</p></div>
            : overbilling_items.map(o => <ItemCard key={o.item_id + o.sprint_id} item={o} defaultOpen={false} />)
          }
        </div>
      )}

      {view === 'systemic' && (
        <SystemicPanel
          actions={summary.systemic_actions}
          historical={summary.historical_prevention}
        />
      )}
    </div>
  )
}

export default SprintHealth
