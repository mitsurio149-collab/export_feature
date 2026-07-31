import React, { useState } from 'react'
import { formatScheduleVariance, formatPercent, formatNumber, formatDays } from '../../../api/formatters'
import ApplyPlanModal from './ApplyPlanModal'
import PMIntelligencePanel from '../PMIntelligencePanel'
import { getRecoveryPlanDisplayData } from '../normalizers'

/**
 * PlanDetailView - Expanded view for a single recovery plan
 * 
 * Shows:
 * - Full plan details (archetype, metrics)
 * - List of actions in the plan
 * - Narrative explanation
 * - Trade-offs
 * - Revised sprint plan
 * - Apply Plan button
 */
function PlanDetailView({ plan, session, onBack }) {
  const [showApplyModal, setShowApplyModal] = useState(false)
  const score = plan.score || {}
  const explanation = plan.explanation || {}
  const displayData = getRecoveryPlanDisplayData(plan)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700"
        >
          ← Back
        </button>
        <div>
          <h2 className="text-2xl font-bold text-white">
            {plan.label} Plan: {({ SAFE: 'Safe', AGGRESSIVE: 'Aggressive', MINIMAL_DISRUPTION: 'Minimal Disruption' })[plan.archetype] || plan.archetype}
          </h2>
          <p className="mt-1 text-sm text-slate-400">Recovery strategy and detailed breakdown</p>
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Why this strategy</div>
          <div style={{ fontSize: 14, fontWeight: 800, marginTop: 4 }}>{displayData.strategicGoal || plan.archetype}</div>
          <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4, maxWidth: 600 }}>{displayData.expectedOutcome || explanation.narrative_summary || 'No explanation available.'}</div>
          {explanation.why_recommended && explanation.why_recommended.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
              {explanation.why_recommended.map((reason, idx) => (
                <span key={`${reason}-${idx}`} style={{ border: '1px solid var(--line2)', borderRadius: 4, padding: '4px 8px', fontSize: 9 }}>{reason}</span>
              ))}
            </div>
          )}
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Project state change</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6, marginTop: 8 }}>
            <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
              <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Delivery confidence</div>
              <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>{displayData.baselineDeadlineProbability != null ? `${Math.round(displayData.baselineDeadlineProbability * 100)}%` : '—'}</div>
              <div style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 800, marginTop: 2 }}>→ {score.deadline_probability != null ? `${Math.round(score.deadline_probability * 100)}%` : '—'}</div>
            </div>
            <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
              <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Expected delay</div>
              <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>{displayData.baselineDelayDays != null ? displayData.baselineDelayDays : '—'}</div>
              <div style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 800, marginTop: 2 }}>→ {formatScheduleVariance(score.expected_delay_days)}</div>
            </div>
            <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
              <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Risk score</div>
              <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>{displayData.baselineRiskScore ?? '—'}</div>
              <div style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 800, marginTop: 2 }}>→ {Math.round(score.overall_risk_score || 0)}</div>
            </div>
          </div>
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Execution timeline</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, marginTop: 8 }}>
            {[
              { key: 'TODAY', label: 'Immediate (today)' },
              { key: 'THIS_SPRINT', label: 'This sprint' },
              { key: 'NEXT_SPRINT', label: 'Before next planning' },
            ].map((phase) => (
              <div key={phase.key} style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '8px 9px' }}>
                <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>{phase.label}</div>
                <ul style={{ paddingLeft: 14, margin: '6px 0 0', color: 'var(--muted)', fontSize: 9 }}>
                  {(plan.actions || []).filter((action) => action.urgency === phase.key).map((action, idx) => (
                    <li key={`${action.title}-${idx}`} style={{ marginBottom: 4 }}><span style={{ color: 'var(--teal)', fontWeight: 800 }}>→ </span><strong style={{ color: 'var(--text)' }}>{action.title || 'Untitled action'}</strong> {action.description ? `· ${action.description}` : ''}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Decision gates</div>
          {displayData.decisionGates && displayData.decisionGates.length > 0 ? (
            <ol style={{ paddingLeft: 18, margin: '8px 0 0', color: 'var(--muted)', fontSize: 9 }}>
              {displayData.decisionGates.map((gate, idx) => (
                <li key={`${gate}-${idx}`} style={{ marginBottom: 4 }}><span style={{ color: 'var(--orange)', fontWeight: 800, marginRight: 6 }}>Gate {idx + 1}</span>{gate}</li>
              ))}
            </ol>
          ) : (
            <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 8 }}>No explicit decision gates — review at end of each sprint phase.</div>
          )}
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Success criteria</div>
          {displayData.successCriteria && displayData.successCriteria.length > 0 ? (
            <ul style={{ paddingLeft: 16, margin: '8px 0 0', color: 'var(--muted)', fontSize: 9 }}>
              {displayData.successCriteria.map((item, idx) => <li key={`${item}-${idx}`} style={{ marginBottom: 4 }}><span style={{ color: 'var(--teal)', fontWeight: 800 }}>✓ </span>{item}</li>)}
            </ul>
          ) : (
            <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 8 }}>Derived from expected outcome above.</div>
          )}
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
            <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
              <div style={{ fontSize: 8, color: 'var(--yellow)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Trade-offs</div>
              <ul style={{ paddingLeft: 14, margin: '6px 0 0', color: 'var(--muted)', fontSize: 9 }}>
                {(explanation.trade_offs || []).map((tradeoff, idx) => <li key={`${tradeoff.description}-${idx}`} style={{ marginBottom: 4 }}>{tradeoff.description}</li>)}
              </ul>
            </div>
            <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
              <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Implementation cost</div>
              <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                  <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Actions</div>
                  <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2 }}>{(plan.actions || []).length}</div>
                </div>
                <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                  <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Teams affected</div>
                  <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2 }}>{new Set((plan.actions || []).map((action) => action.action_type)).size}</div>
                </div>
                <div style={{ border: '1px solid var(--line2)', borderRadius: 5, padding: '7px 8px' }}>
                  <div style={{ fontSize: 8, color: 'var(--quiet)', textTransform: 'uppercase' }}>Actions</div>
                  <div style={{ fontSize: 12, fontWeight: 800, marginTop: 2 }}>{(plan.actions || []).length}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 7, background: 'var(--panel)', padding: 11, marginBottom: 9 }}>
          <div style={{ color: 'var(--orange)', fontSize: 8, fontWeight: 800, letterSpacing: '.18em', textTransform: 'uppercase' }}>Action detail</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.35fr) 86px 86px 72px', gap: 0, marginTop: 8 }}>
            <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase' }}>Action</div>
            <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase' }}>Owner</div>
            <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase' }}>Timing</div>
            <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 8, color: 'var(--quiet)', fontWeight: 800, textTransform: 'uppercase' }}>Confidence</div>
            {(plan.actions || []).map((action, idx) => (
              <React.Fragment key={`${action.title}-${idx}`}>
                <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 9, color: 'var(--text)' }}>{action.title || 'Untitled action'}</div>
                <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 9, color: 'var(--muted)' }}>{action.owner || 'Unassigned'}</div>
                <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 9, color: 'var(--muted)' }}>{action.urgency || '—'}</div>
                <div style={{ border: '1px solid var(--line2)', padding: '7px 8px', fontSize: 9, fontWeight: 800, color: action.confidence === 'HIGH' ? 'var(--teal)' : action.confidence === 'LOW' ? 'var(--pink)' : 'var(--yellow)' }}>{action.confidence || '—'}</div>
              </React.Fragment>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 3, marginTop: 4 }}>
          <button
            onClick={() => setShowApplyModal(true)}
            style={{ flex: 1, border: 'none', background: 'var(--teal)', color: 'var(--bg)', borderRadius: 4, padding: '10px 12px', fontWeight: 800, cursor: 'pointer' }}
          >
            Apply This Plan
          </button>
          <button
            onClick={onBack}
            style={{ border: '1px solid var(--line)', background: 'var(--panel)', color: 'var(--muted)', borderRadius: 4, padding: '10px 12px', cursor: 'pointer' }}
          >
            Cancel
          </button>
        </div>
      </div>

      {showApplyModal && (
        <ApplyPlanModal
          plan={plan}
          session={session}
          onClose={() => setShowApplyModal(false)}
          onConfirm={() => {
            setShowApplyModal(false)
            onBack()
          }}
        />
      )}
    </div>
  )
}

export default PlanDetailView
