import { describe, expect, it } from 'vitest'
import { getRecommendationDisplayMetrics, getRecoveryPlanDisplayData, getBenefitLine } from './normalizers'

describe('getRecommendationDisplayMetrics', () => {
  it('normalizes backend recommendation fields to the UI contract', () => {
    const rec = {
      baseline_probability: 0.42,
      after_probability: 0.68,
      baseline_delay_days: 5.2,
      expected_delay_gain_days: 2.4,
      baseline_risk_score: 70,
      after_risk_score: 55,
      counterfactual_statement: 'Without this action, the project stays at risk.',
    }

    expect(getRecommendationDisplayMetrics(rec, { baseline_deadline_prob: 0.38, baseline_delay: 6.1, baseline_risk: 72 })).toEqual({
      baselineDeadlineProbability: 0.42,
      afterDeadlineProbability: 0.68,
      baselineDelayDays: 5.2,
      expectedDelayGainDays: 2.4,
      baselineRiskScore: 70,
      afterRiskScore: 55,
      counterfactualStatement: 'Without this action, the project stays at risk.',
      delayAttributionSegments: [{ source: 'Direct impact', days: 2.4 }],
    })
  })

  it('derives delay attribution from impact metrics when the backend omits a dedicated field', () => {
    const rec = {
      expected_delay_gain_days: 1.8,
      pm_intelligence: {
        impact_profile: {
          impact_metrics: {
            primary_dimension: 'schedule',
          },
        },
      },
    }

    expect(getRecommendationDisplayMetrics(rec).delayAttributionSegments).toEqual([{ source: 'schedule', days: 1.8 }])
  })
})

describe('getRecoveryPlanDisplayData', () => {
  it('derives recovery-plan display values from the current API response shape', () => {
    const plan = {
      archetype: 'SAFE',
      explanation: {
        narrative_summary: 'Protect the critical path.',
        decision_gates: ['Review staffing at sprint review'],
        success_criteria: ['Stay within budget'],
      },
      score: {
        deadline_probability: 0.74,
        expected_delay_days: 1.8,
        overall_risk_score: 42,
      },
    }

    expect(getRecoveryPlanDisplayData(plan)).toEqual({
      strategicGoal: 'SAFE',
      expectedOutcome: 'Protect the critical path.',
      decisionGates: ['Review staffing at sprint review'],
      successCriteria: ['Stay within budget'],
      baselineDeadlineProbability: null,
      baselineDelayDays: null,
      baselineRiskScore: null,
      forecastConfidence: null,
    })
  })

  it('derives decision gates and success criteria from plan actions when the backend omits them', () => {
    const plan = {
      archetype: 'AGGRESSIVE',
      actions: [{ urgency: 'TODAY' }, { urgency: 'THIS_SPRINT' }],
      explanation: {
        expected_outcome: 'Recover the sprint by closing the critical blockers.',
      },
      score: {
        forecast_confidence: 'HIGH',
      },
    }

    expect(getRecoveryPlanDisplayData(plan)).toEqual({
      strategicGoal: 'AGGRESSIVE',
      expectedOutcome: 'Recover the sprint by closing the critical blockers.',
      decisionGates: ['Confirm immediate actions are started this sprint.', 'Review sprint-level execution at the next review.'],
      successCriteria: ['Recover the sprint by closing the critical blockers.'],
      baselineDeadlineProbability: null,
      baselineDelayDays: null,
      baselineRiskScore: null,
      forecastConfidence: 'HIGH',
    })
  })
})

// ---------------------------------------------------------------------------
// Fix 7 — getBenefitLine preventive-rec tests
// ---------------------------------------------------------------------------

describe('getBenefitLine', () => {
  it('returns the strategic benefit string for a preventive rec, never a numeric day figure', () => {
    const preventiveRec = {
      pm_intelligence: {
        is_preventive: true,
        explanation: {
          strategic_benefits: ['Improves team resilience and bus-factor'],
        },
      },
      // Non-zero delay gain that would normally appear as "0.08d schedule recovery"
      expected_delay_gain_days: 0.08,
    }
    const result = getBenefitLine(preventiveRec, { expectedDelayGainDays: 0.08 })
    expect(result).toBe('Improves team resilience and bus-factor')
    expect(result).not.toMatch(/\d+(\.\d+)?d/)
  })

  it('falls back to the generic resilience string when strategic_benefits is missing', () => {
    const preventiveRec = {
      pm_intelligence: { is_preventive: true },
    }
    const result = getBenefitLine(preventiveRec, {})
    expect(result).toBe('Improves long-term project resilience')
    expect(result).not.toMatch(/\d+(\.\d+)?d/)
  })

  it('uses impact_profile strategic_benefits over top-level explanation', () => {
    const preventiveRec = {
      pm_intelligence: {
        is_preventive: true,
        impact_profile: {
          explanation: {
            strategic_benefits: ['Reduces single-point-of-failure exposure'],
          },
        },
        explanation: {
          strategic_benefits: ['Lower priority benefit'],
        },
      },
    }
    expect(getBenefitLine(preventiveRec, {})).toBe('Reduces single-point-of-failure exposure')
  })

  it('returns numeric schedule recovery for a non-preventive rec with delay gain', () => {
    const rec = {
      pm_intelligence: { is_preventive: false },
    }
    const result = getBenefitLine(rec, { expectedDelayGainDays: 2.4 })
    expect(result).toBe('2.4d schedule recovery')
  })

  it('returns risk score drop label for a non-preventive rec with zero delay gain but high risk drop', () => {
    const rec = { pm_intelligence: { is_preventive: false } }
    const result = getBenefitLine(rec, {
      expectedDelayGainDays: 0,
      baselineRiskScore: 70,
      afterRiskScore: 55,
    })
    expect(result).toBe('Risk score −15 pts')
  })

  it('never shows a numeric day figure for a preventive rec even when delay gain is nonzero', () => {
    // Simulate the floating-point noise scenario: near-zero but non-exact delta
    const preventiveRec = {
      pm_intelligence: { is_preventive: true },
      expected_delay_gain_days: 0.08,
    }
    const result = getBenefitLine(preventiveRec, { expectedDelayGainDays: 0.08 })
    // Must not contain any pattern like "0.08d" or similar
    expect(result).not.toMatch(/\d+\.?\d*d\s/)
    expect(result).not.toMatch(/schedule recovery/)
  })
})
