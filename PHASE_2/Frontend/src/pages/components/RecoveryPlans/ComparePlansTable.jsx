import React from 'react'
import { formatScheduleVariance, formatPercent, formatNumber } from '../../../api/formatters'
import { getRecoveryPlanDisplayData } from '../normalizers'

/**
 * ComparePlansTable - Side-by-side comparison of all 3 recovery plans
 * 
 * This is the highest-value UI element for judges:
 * - 3 rows (one per plan)
 * - 5 columns (Archetype, Probability, Delay, Risk, Complexity)
 * - Recommended plan is highlighted
 * - Click row to expand details
 */
function ComparePlansTable({ plans, onSelectPlan }) {
  if (!plans || plans.length === 0) {
    return <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '11px 12px', textAlign: 'center', color: 'var(--muted)' }}>No plans to compare</div>
  }

  return (
    <div style={{ border: '1px solid var(--line2)', borderRadius: 5, overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr 1fr 1fr 1fr 1fr', background: 'var(--panel2)' }}>
        {['Strategy goal', 'Delivery confidence', 'Delay change', 'Execution speed', 'Forecast stability', 'AI confidence'].map((header) => (
          <div key={header} style={{ padding: '7px 8px', borderRight: '1px solid var(--line2)', fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.1em' }}>{header}</div>
        ))}
      </div>

      {plans.map((plan) => {
        const score = plan.score || {}
        const actions = plan.actions || []
        const displayData = getRecoveryPlanDisplayData(plan)
        const executionSpeed = actions.some((action) => action.urgency === 'TODAY') ? 'Fast (immediate)' : 'Moderate (sprint-paced)'
        const aiConfidence = displayData.forecastConfidence || score.confidence || score.overall_confidence || '—'
        const isRecommended = plan.is_recommended || plan.label === 'Recommended'

        return (
          <div
            key={plan.plan_id}
            onClick={() => onSelectPlan(plan.plan_id)}
            style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr 1fr 1fr 1fr 1fr 1fr', borderTop: '1px solid var(--line2)', fontSize: 9, cursor: 'pointer', background: isRecommended ? 'rgba(115, 225, 178, 0.08)' : 'transparent' }}
          >
            <div style={{ padding: '7px 8px', borderRight: '1px solid var(--line2)' }}>
              <div style={{ fontWeight: 800, fontSize: 9 }}>{displayData.strategicGoal || plan.archetype}</div>
              {isRecommended && <div style={{ color: 'var(--teal)', fontSize: 8, marginTop: 2 }}>AI recommended</div>}
            </div>
            <div style={{ padding: '7px 8px', borderRight: '1px solid var(--line2)', color: 'var(--teal)', fontWeight: 800 }}>{Math.round((score.deadline_probability || 0) * 100)}%</div>
            <div style={{ padding: '7px 8px', borderRight: '1px solid var(--line2)', fontFamily: 'DM Mono, monospace' }}>{formatScheduleVariance(score.expected_delay_days)}</div>
            <div style={{ padding: '7px 8px', borderRight: '1px solid var(--line2)', color: 'var(--muted)' }}>{executionSpeed}</div>
            <div style={{ padding: '7px 8px', borderRight: '1px solid var(--line2)', color: 'var(--muted)' }}>{displayData.forecastConfidence || '—'}</div>
            <div style={{ padding: '7px 8px', color: aiConfidence === 'HIGH' ? 'var(--teal)' : aiConfidence === 'LOW' ? 'var(--pink)' : 'var(--yellow)', fontWeight: 800 }}>{aiConfidence}</div>
          </div>
        )
      })}
    </div>
  )
}

function _getStrategyDescription(archetype) {
  const descriptions = {
    SAFE: 'High-confidence actions only',
    AGGRESSIVE: 'Maximum delay recovery',
    MINIMAL_DISRUPTION: 'Minimal team disruption',
  }
  return descriptions[archetype] || archetype
}

export default ComparePlansTable
