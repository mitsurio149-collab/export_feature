import React from 'react'
import {
  dimensionLabel,
  dimensionBarColor,
  sortDimensions,
  confidenceColor,
  executionWindowColor,
  impactTierColor,
} from '../../config/dimensionConfig'

/**
 * PMIntelligencePanel — renders Recommendation.pm_intelligence
 * (see backend app/api/models_pm_intelligence.py:PMIntelligenceResponse).
 *
 * Used by both the Dashboard recommendation cards and the Recovery Plan
 * action list, so both surfaces render the identical PM Intelligence
 * contract the same way — one implementation, not two.
 *
 * Backward compatible: if `pmIntelligence` is null/undefined (recommendation
 * predates this field, or came from a route that hasn't attached it),
 * renders nothing. Callers should keep their existing legacy fallback
 * rendering (priority/confidence/effort) alongside this — this component
 * only adds the new information, it doesn't replace anything by itself.
 *
 * `variant`:
 *  - "full"    — badges + dimensions + expected outcome + trade-offs (Dashboard cards)
 *  - "compact" — badges only (Recovery Plan action rows, which already show
 *                 their own delay-reduction/confidence line)
 */
function PMIntelligencePanel({ pmIntelligence, variant = 'full' }) {
  if (!pmIntelligence) return null

  const profile = pmIntelligence.impact_profile
  const decisionContext = profile?.decision_context
  const impactMetrics = profile?.impact_metrics
  const explanation = profile?.explanation || pmIntelligence.explanation

  const hasBadges = decisionContext?.intent || decisionContext?.execution_window || impactMetrics?.impact_tier
  if (!hasBadges && !explanation) return null

  return (
    <div className="mt-3 space-y-3">
      {hasBadges && (
        <div className="flex flex-wrap items-center gap-2">
          {decisionContext?.intent && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
              {decisionContext.intent}
            </span>
          )}
          {decisionContext?.execution_window && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${executionWindowColor(decisionContext.execution_window)}`}>
              {decisionContext.execution_window}
            </span>
          )}
          {impactMetrics?.impact_tier && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${impactTierColor(impactMetrics.impact_tier)}`}>
              {impactMetrics.impact_tier} impact
            </span>
          )}
          {impactMetrics?.aggregate_confidence && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${confidenceColor(impactMetrics.aggregate_confidence)}`}>
              {impactMetrics.aggregate_confidence} confidence
            </span>
          )}
        </div>
      )}

      {variant === 'full' && explanation?.expected_outcome && (
        <div className="rounded-xl border border-emerald-800/40 bg-emerald-900/10 px-3 py-2">
          <div className="text-xs uppercase tracking-wide text-emerald-400">Expected Outcome</div>
          <div className="mt-1 text-sm text-emerald-100">{explanation.expected_outcome}</div>
        </div>
      )}

      {variant === 'full' && explanation?.trade_offs?.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Trade-offs</div>
          <ul className="mt-1 space-y-1">
            {explanation.trade_offs.map((t, i) => (
              <li key={i} className="flex gap-2 text-xs text-slate-300">
                <span className="text-amber-400">●</span>
                <span>{t}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default PMIntelligencePanel
