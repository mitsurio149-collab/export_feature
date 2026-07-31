import React, { useState, useEffect } from 'react'
import { api } from '../../api/client'
import { getRecommendationDisplayMetrics, getBenefitLine } from './normalizers'
import PMIntelligencePanel from './PMIntelligencePanel'
import { dimensionLabel } from '../../config/dimensionConfig'

// Contribution Type icon + color map — matches output_expected.md §"Contribution Types"
const INTENT_CONFIG = {
  RECOVER:  { emoji: '🟢', color: 'var(--red)',    bg: 'color-mix(in srgb, var(--red) 16%, transparent)' },
  PROTECT:  { emoji: '🛡️', color: 'var(--teal)',   bg: 'color-mix(in srgb, var(--teal) 16%, transparent)' },
  PREVENT:  { emoji: '🚫', color: 'var(--yellow)', bg: 'color-mix(in srgb, var(--yellow) 16%, transparent)' },
  IMPROVE:  { emoji: '📈', color: 'var(--purple)', bg: 'color-mix(in srgb, var(--purple) 16%, transparent)' },
  GOVERN:   { emoji: '📈', color: 'var(--teal)',   bg: 'color-mix(in srgb, var(--teal) 12%, transparent)' },
  PREPARE:  { emoji: '🔄', color: 'var(--muted)',  bg: 'color-mix(in srgb, var(--muted) 16%, transparent)' },
  ACCELERATE: { emoji: '⚡', color: 'var(--yellow)', bg: 'color-mix(in srgb, var(--yellow) 14%, transparent)' },
  OPTIMIZE:   { emoji: '⚖️', color: 'var(--purple)', bg: 'color-mix(in srgb, var(--purple) 14%, transparent)' },
  STABILIZE:  { emoji: '🔄', color: 'var(--teal)',   bg: 'color-mix(in srgb, var(--teal) 14%, transparent)' },
}

function IntentBadge({ intent }) {
  const cfg = INTENT_CONFIG[intent] || INTENT_CONFIG.PROTECT
  return (
    <span style={{
      borderRadius: 3, padding: '3px 6px', fontSize: 8, fontWeight: 800,
      textTransform: 'uppercase', color: cfg.color, background: cfg.bg,
      display: 'inline-flex', alignItems: 'center', gap: 3,
    }}>
      <span>{cfg.emoji}</span>
      <span>{intent || '—'}</span>
    </span>
  )
}

/** Show up to 4 top-scoring impact dimensions as small coloured pills. */
function ImprovesPills({ dimensions }) {
  if (!Array.isArray(dimensions) || dimensions.length === 0) return null
  const topDims = [...dimensions]
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .slice(0, 4)
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
      {topDims.map((d) => (
        <span key={d.type} style={{
          fontSize: 8, fontWeight: 700, padding: '2px 5px', borderRadius: 3,
          color: 'var(--teal)', background: 'color-mix(in srgb, var(--teal) 12%, transparent)',
          textTransform: 'capitalize',
        }}>
          {dimensionLabel(d.type)}
        </span>
      ))}
    </div>
  )
}

function RecCard({ rec, expanded, onToggle, onBuildPlan, baselineContext }) {
  const metrics = getRecommendationDisplayMetrics(rec, baselineContext)
  const urgencyLabel = {
    TODAY: 'Act today',
    THIS_SPRINT: 'This sprint',
    NEXT_SPRINT: 'Before planning',
    LATER: 'No immediate deadline',
  }[rec?.urgency] || 'This sprint'

  const tradeOffsList = (
    rec?.pm_intelligence?.impact_profile?.explanation?.trade_offs ||
    rec?.pm_intelligence?.explanation?.trade_offs ||
    (rec?.validation?.trade_offs || []).map((t) => t.description)
  ).filter(Boolean)
  const tradeOff = tradeOffsList[0] || 'No major trade-off noted.'
  const title = rec?.action || rec?.action_summary || rec?.title || 'Recommendation'
  const delayGain = metrics.expectedDelayGainDays ?? rec?.expected_delay_gain_days ?? rec?.delay_gain_days ?? 0
  const riskDrop = (metrics.baselineRiskScore ?? 0) - (metrics.afterRiskScore ?? 0)
  const probGainPct = Math.round(((metrics.afterDeadlineProbability ?? 0) - (metrics.baselineDeadlineProbability ?? 0)) * 100)
  const isPreventive = rec?.pm_intelligence?.is_preventive === true
  // Preventive recs (CROSS_TRAIN_BACKUP, FREEZE_SCOPE_REQUEST, etc.) derive their
  // value from long-term project health, not numeric schedule deltas. Show a
  // descriptive label regardless of whether the simulation delta happens to be
  // exactly zero or a small nonzero float (floating-point noise from the zero-delta
  // fallback should never appear as a confusing day figure).
  const benefitLine = getBenefitLine(rec, metrics)

  const rawIntent = (rec?.pm_intelligence?.impact_profile?.decision_context?.intent || '').toUpperCase() || undefined
  const dimensions = rec?.pm_intelligence?.impact_profile?.impact_metrics?.dimensions || []

  return (
    <div style={{ border: `1px solid ${expanded ? 'var(--teal)' : 'var(--line)'}`, borderRadius: 7, background: expanded ? 'oklch(21% .05 255)' : 'var(--panel)', padding: '9px 10px', marginBottom: 7 }}>
      <div onClick={onToggle} style={{ cursor: 'pointer' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'start' }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <IntentBadge intent={rawIntent} />
              <div style={{ fontSize: 12, fontWeight: 800, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</div>
            </div>
            <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 3 }}>Primary benefit: {benefitLine}</div>
            <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 1 }}>Trade-off: {tradeOff}</div>
          </div>
          <div style={{ textAlign: 'right', minWidth: 80 }}>
            <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, textTransform: 'uppercase' }}>{urgencyLabel}</div>
          </div>
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 8, borderTop: '1px solid var(--line2)', paddingTop: 8 }}>
          {rec?.pm_intelligence && (
            <div style={{ marginBottom: 10 }}>
              <PMIntelligencePanel pmIntelligence={rec.pm_intelligence} variant="full" />
            </div>
          )}
          {dimensions.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase', letterSpacing: '.12em', marginBottom: 4 }}>Improves</div>
              <ImprovesPills dimensions={dimensions} />
            </div>
          )}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase', letterSpacing: '.12em', marginBottom: 6 }}>Current → expected project state</div>
            {(() => {
              // Only show tiles where the metric actually changes meaningfully.
              // Thresholds match Fix 7's preventive-detection epsilons for consistency.
              const showProb = metrics.baselineDeadlineProbability != null
                && metrics.afterDeadlineProbability != null
                && Math.abs(metrics.afterDeadlineProbability - metrics.baselineDeadlineProbability) > 0.005
              const showDelay = metrics.baselineDelayDays != null
                && metrics.afterDelayDays != null
                && Math.abs(metrics.afterDelayDays - metrics.baselineDelayDays) > 0.05
              const showRisk = metrics.baselineRiskScore != null
                && metrics.afterRiskScore != null
                && Math.abs(metrics.afterRiskScore - metrics.baselineRiskScore) > 0.5
              const visibleCount = [showProb, showDelay, showRisk].filter(Boolean).length

              if (visibleCount === 0) {
                // Fully preventive — no measurable metric movement; show benefit text instead
                return (
                  <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                    <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Long-term benefit</div>
                    <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 4 }}>{benefitLine}</div>
                  </div>
                )
              }

              return (
                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${visibleCount}, minmax(0, 1fr))`, gap: 6 }}>
                  {showProb && (
                    <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                      <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Delivery confidence</div>
                      <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>{`${Math.round(metrics.baselineDeadlineProbability * 100)}%`}</div>
                      <div style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 800, marginTop: 2 }}>→ {`${Math.round(metrics.afterDeadlineProbability * 100)}%`}</div>
                    </div>
                  )}
                  {showDelay && (
                    <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                      <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Expected delay</div>
                      <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>{`${metrics.baselineDelayDays}d`}</div>
                      <div style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 800, marginTop: 2 }}>→ {`${metrics.afterDelayDays}d`}</div>
                    </div>
                  )}
                  {showRisk && (
                    <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                      <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Risk score</div>
                      <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>{metrics.baselineRiskScore}</div>
                      <div style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 800, marginTop: 2 }}>→ {metrics.afterRiskScore}</div>
                    </div>
                  )}
                </div>
              )
            })()}
          </div>

          {(delayGain > 0.05 || (metrics.afterRiskScore != null && metrics.afterRiskScore < (metrics.baselineRiskScore ?? 999))) ? (
            <button onClick={onBuildPlan} style={{ width: '100%', border: 'none', background: 'var(--teal)', color: 'var(--bg)', borderRadius: 4, padding: '8px 10px', fontWeight: 800, cursor: 'pointer', fontSize: 10 }}>
              Build recovery plan for this recommendation ↗
            </button>
          ) : (
            <div style={{ fontSize: 9, color: 'var(--muted)', textAlign: 'center', paddingTop: 6, borderTop: '1px solid var(--line2)' }}>
              This action improves forecast accuracy or resilience — implement directly without a recovery plan.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function RecommendationsPage({ session, onNavigate }) {
  const [recs, setRecs] = useState([])
  const [expandedId, setExpandedId] = useState(null)
  const [baselineContext, setBaselineContext] = useState(null)

  useEffect(() => {
    const sessionId = session?.project_summary?.session_id
    if (!sessionId) return

    let mounted = true
    Promise.all([
      api.recommendations(sessionId),
      api.sessionSnapshot(sessionId),
    ])
      .then(([data, snapshot]) => {
        if (!mounted) return
        const list = Array.isArray(data?.recommendations) ? data.recommendations : []
        setRecs(list)
        if (list[0]) setExpandedId(list[0].recommendation_id || list[0].id || 0)
        setBaselineContext({
          baseline_deadline_prob: snapshot?.monte_carlo?.on_time_probability ?? null,
          baseline_delay: snapshot?.forecast?.expected_delay_days ?? null,
          baseline_risk: snapshot?.risk?.overall_risk_score ?? null,
        })
      })
      .catch(() => {
        if (!mounted) return
        setRecs([])
        setBaselineContext(null)
      })

    return () => { mounted = false }
  }, [session?.project_summary?.session_id])

  const totalDelayAtRisk = Math.round(
    recs
      .filter((rec) => !rec?.pm_intelligence?.is_preventive)
      .reduce((sum, rec) => sum + (getRecommendationDisplayMetrics(rec).expectedDelayGainDays ?? 0), 0)
    * 100
  ) / 100
  const preventiveCount = recs.filter((rec) => rec?.pm_intelligence?.is_preventive === true).length
  const highestConfidence = recs.reduce((best, rec) => {
    const score = rec?.priority_score ?? 0
    const name = rec?.action || rec?.action_summary || 'Unnamed'
    if (!best || score > best.score) return { score, value: name }
    return best
  }, null)

  const summaryKpis = [
    { label: 'Decisions needing action', value: recs.length || '—' },
    { label: 'Total delay at risk', value: `${totalDelayAtRisk}d` },
    { label: 'Preventive actions available', value: preventiveCount || '—' },
    { label: 'Urgency recommendation', value: highestConfidence?.value || '—' },
  ]

  return (
    <div>
      <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: '10px 11px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 8, color: 'var(--orange)', fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Decision intelligence</div>
            <div style={{ fontSize: 14, fontWeight: 800, marginTop: 4 }}>{recs.length} decisions need a PM read this sprint</div>
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>Delay days are one signal; make sure the team also considers confidence, trade-offs, and effort.</div>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6, marginTop: 9 }}>
          {summaryKpis.map((kpi) => (
            <div key={kpi.label} style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
              <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase', letterSpacing: '.08em' }}>{kpi.label}</div>
              <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2 }}>{kpi.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 8 }}>
        <div>
          {recs.length === 0 ? (
            <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: '11px 12px', color: 'var(--muted)', fontSize: 10 }}>No recommendations available yet.</div>
          ) : recs.map((rec) => (
            <RecCard
              key={rec.recommendation_id || rec.id || rec.action}
              rec={rec}
              expanded={expandedId === (rec.recommendation_id || rec.id || rec.action)}
              onToggle={() => setExpandedId(expandedId === (rec.recommendation_id || rec.id || rec.action) ? null : (rec.recommendation_id || rec.id || rec.action))}
              onBuildPlan={() => onNavigate && onNavigate('recovery-plans')}
              baselineContext={baselineContext}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
