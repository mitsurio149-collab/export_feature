import React from 'react'
import { formatScheduleVariance, formatPercent, formatNumber } from '../../../api/formatters'
import { getRecoveryPlanDisplayData } from '../normalizers'

/**
 * RecoveryPlanCard - Individual card for a recovery plan
 * 
 * Displays:
 * - Archetype label with "Recommended" badge if applicable
 * - Key metrics: deadline probability, delay, actions, complexity
 * - Click to expand
 */
function RecoveryPlanCard({ plan, isRecommended, onExpand }) {
  const archetypeLabelMap = {
    SAFE: 'Safe Plan',
    AGGRESSIVE: 'Aggressive Plan',
    MINIMAL_DISRUPTION: 'Minimal Disruption',
  }

  const archetypeDescMap = {
    SAFE: 'High-confidence actions only',
    AGGRESSIVE: 'Maximum delay recovery',
    MINIMAL_DISRUPTION: 'Minimal team disruption',
  }

  const label = archetypeLabelMap[plan.archetype] || plan.archetype
  const description = archetypeDescMap[plan.archetype] || ''
  const score = plan.score || {}
  const explanation = plan.explanation || {}
  const displayData = getRecoveryPlanDisplayData(plan)

  return (
    <article
      onClick={onExpand}
      style={{
        border: `1px solid ${isRecommended ? 'var(--teal)' : 'var(--line)'}`,
        borderRadius: 7,
        background: 'var(--panel)',
        boxShadow: isRecommended ? 'inset 0 0 0 1px var(--teal)' : 'none',
        padding: 11,
        cursor: 'pointer',
        marginBottom: 6,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div>
          {isRecommended && (
            <span style={{ color: 'var(--teal)', fontSize: 8, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.12em', display: 'block', marginBottom: 4 }}>
              AI Recommended Strategy
            </span>
          )}
          <div style={{ fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.1em' }}>
            Strategy goal
          </div>
          <div style={{ fontSize: 13, fontWeight: 800, marginTop: 3 }}>
            {displayData.strategicGoal || label}
          </div>
          <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4, maxWidth: 500 }}>
            {displayData.expectedOutcome || description}
          </div>
        </div>
        <div style={{ flexShrink: 0, border: '1px solid var(--line2)', borderRadius: 3, padding: '3px 7px', fontSize: 8, color: 'var(--quiet)' }}>
          {plan.archetype}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6, marginTop: 10 }}>
        <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
          <div style={{ fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.1em' }}>Expected delay</div>
          <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2, fontFamily: 'DM Mono, monospace' }}>{formatScheduleVariance(score.expected_delay_days)}</div>
        </div>
        <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
          <div style={{ fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.1em' }}>Delivery confidence</div>
          <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2, color: 'var(--teal)' }}>{Math.round((score.deadline_probability || 0) * 100)}%</div>
        </div>
        <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
          <div style={{ fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.1em' }}>Risk score</div>
          <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2, fontFamily: 'DM Mono, monospace' }}>{Math.round(score.overall_risk_score || 0)}</div>
        </div>
      </div>
    </article>
  )
}

export default RecoveryPlanCard
