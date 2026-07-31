export function getRecommendationDisplayMetrics(rec = {}, baselineContext = {}) {
  const baselineProbability = rec.baseline_probability ?? rec.baselineDeadlineProbability ?? rec.baseline_deadline_prob ?? baselineContext.baseline_deadline_prob ?? null
  const afterProbability = rec.after_probability ?? rec.afterDeadlineProbability ?? rec.deadline_probability ?? null
  const baselineDelayDays = rec.baseline_delay_days ?? rec.baseline_delay ?? baselineContext.baseline_delay ?? null
  const afterDelayDays = rec.after_delay_days ?? null
  const expectedDelayGainDays = rec.expected_delay_gain_days ?? rec.delay_gain_days ?? null
  const baselineRiskScore = rec.baseline_risk_score ?? rec.baseline_risk ?? baselineContext.baseline_risk ?? null
  const afterRiskScore = rec.after_risk_score ?? rec.overall_risk_score ?? null

  const impactProfile = rec.pm_intelligence?.impact_profile || rec.details?.impact_profile || {}
  const dimensions = impactProfile.impact_metrics?.dimensions || []
  const delayAttributionIsPercent = dimensions.length > 0
  const delayAttributionSegments = dimensions.length > 0
    ? dimensions.map((d) => ({ source: d.type, days: Math.round((d.score || 0) * 100) }))
    : [
        {
          source: impactProfile.impact_metrics?.primary_dimension || 'Direct impact',
          days: expectedDelayGainDays ?? 0,
        },
      ]

  return {
    baselineDeadlineProbability: baselineProbability,
    afterDeadlineProbability: afterProbability,
    baselineDelayDays,
    afterDelayDays,
    expectedDelayGainDays,
    baselineRiskScore,
    afterRiskScore,
    counterfactualStatement:
      rec?.pm_intelligence?.impact_profile?.explanation?.ignore_consequence ||
      rec?.pm_intelligence?.explanation?.ignore_consequence ||
      rec?.counterfactual_statement ||
      rec?.counterfactual ||
      null,
    delayAttributionIsPercent,
    delayAttributionSegments,
  }
}

/**
 * Compute the primary benefit line for a recommendation card.
 *
 * Preventive recommendations (is_preventive=true) always show a descriptive
 * long-term benefit string instead of a numeric day/percent figure, because
 * their value doesn't show up in schedule deltas — it's project-health
 * improvement that the simulation can't fully capture.
 */
export function getBenefitLine(rec = {}, metrics = {}) {
  const isPreventive = rec?.pm_intelligence?.is_preventive === true
  if (isPreventive) {
    return (
      rec?.pm_intelligence?.impact_profile?.explanation?.strategic_benefits?.[0] ||
      rec?.pm_intelligence?.explanation?.strategic_benefits?.[0] ||
      'Improves long-term project resilience'
    )
  }
  const delayGain = metrics.expectedDelayGainDays ?? rec?.expected_delay_gain_days ?? rec?.delay_gain_days ?? 0
  const riskDrop = (metrics.baselineRiskScore ?? 0) - (metrics.afterRiskScore ?? 0)
  const probGainPct = Math.round(
    ((metrics.afterDeadlineProbability ?? 0) - (metrics.baselineDeadlineProbability ?? 0)) * 100
  )
  if (delayGain < -0.05) return `Adds ${Math.abs(delayGain)}d to schedule (scope correction — improves forecast accuracy)`
  if (delayGain > 0.05) return `${delayGain}d schedule recovery`
  if (riskDrop > 3) return `Risk score −${Math.round(riskDrop)} pts`
  if (probGainPct > 0) return `+${probGainPct}pp delivery confidence`
  return rec?.pm_intelligence?.impact_profile?.explanation?.primary_objective || 'Improves project health'
}

export function getRecoveryPlanDisplayData(plan = {}) {
  const score = plan.score || {}
  const explanation = plan.explanation || {}
  const actions = Array.isArray(plan.actions) ? plan.actions : []
  const expectedOutcome = explanation.expected_outcome ?? explanation.narrative_summary ?? null

  const derivedDecisionGates = explanation.decision_gates?.length
    ? explanation.decision_gates
    : [
        ...(actions.some((action) => action.urgency === 'TODAY') ? ['Confirm immediate actions are started this sprint.'] : []),
        ...(actions.some((action) => action.urgency === 'THIS_SPRINT') ? ['Review sprint-level execution at the next review.'] : []),
        ...(actions.some((action) => action.urgency === 'NEXT_SPRINT') ? ['Reassess readiness before the next planning cycle.'] : []),
      ]

  const derivedSuccessCriteria = explanation.success_criteria?.length
    ? explanation.success_criteria
    : [expectedOutcome || 'Deliver the planned recovery outcome.']

  return {
    strategicGoal: plan.strategic_goal ?? plan.label ?? plan.archetype ?? null,
    expectedOutcome,
    decisionGates: derivedDecisionGates,
    successCriteria: derivedSuccessCriteria,
    baselineDeadlineProbability: score.baseline_deadline_probability ?? null,
    baselineDelayDays: score.baseline_delay_days ?? null,
    baselineRiskScore: score.baseline_risk_score ?? null,
    forecastConfidence: score.forecast_confidence ?? score.confidence ?? score.overall_confidence ?? null,
  }
}
