import React, { useState } from 'react'
import { api } from '../../../api/client'
import { formatScheduleVariance, formatPercent } from '../../../api/formatters'

/**
 * ApplyPlanModal - Confirmation dialog for applying a recovery plan
 * 
 * Shows:
 * - Plan summary
 * - Confirmation message
 * - Apply/Cancel buttons
 * - Loading and success states
 */
function ApplyPlanModal({ plan, session, onClose, onConfirm }) {
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const score = plan.score || {}

  const handleApply = async () => {
    try {
      setApplying(true)
      setError(null)

      const sessionId = session.project_summary?.session_id
      if (!sessionId) {
        throw new Error('Session ID not found')
      }

      const response = await api.post('/recovery-plans/apply', {
        plan_id: plan.plan_id,
        session_id: sessionId,
      })

      if (response.success || response.data?.success) {
        setSuccess(true)
        setTimeout(() => {
          onConfirm()
        }, 2000)
      } else {
        throw new Error('Failed to apply plan')
      }
    } catch (err) {
      setError(err)
      setApplying(false)
    }
  }

  if (success) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
        <div className="rounded-2xl border border-emerald-500 bg-slate-900 p-8 shadow-2xl w-full max-w-md">
          <div className="text-center">
            <div className="inline-block text-4xl mb-4">✓</div>
            <h2 className="text-2xl font-bold text-emerald-400">Plan Applied</h2>
            <p className="mt-3 text-slate-300">
              Recovery plan {plan.archetype} has been successfully applied to your project.
            </p>
            <p className="mt-1 text-sm text-slate-400">
              {score.actions_required ?? '—'} actions scheduled for execution.
            </p>
            <p className="mt-4 text-xs text-slate-500">Redirecting...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl w-full max-w-md">
        {/* Header */}
        <div className="border-b border-slate-700 p-6">
          <h2 className="text-xl font-bold text-white">Apply Recovery Plan</h2>
          <p className="mt-1 text-sm text-slate-400">
            You are about to apply {(plan.archetype || '').toLowerCase()} recovery plan to the project.
          </p>
        </div>

        {/* Content */}
        <div className="space-y-4 p-6">
          {/* Plan Summary */}
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Strategy</span>
                <span className="font-semibold text-slate-200">{plan.archetype}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Actions</span>
                <span className="font-semibold text-slate-200">{score.actions_required ?? '—'}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Deadline Probability</span>
                <span className="font-semibold text-emerald-400">
                  {formatPercent(score.deadline_probability)}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Expected Delay</span>
                <span className="font-semibold text-slate-200">
                  {formatScheduleVariance(score.expected_delay_days)}
                </span>
              </div>
            </div>
          </div>

          {/* Confirmation Message */}
          <div className="text-sm text-slate-300">
            <p className="font-semibold mb-2">Plan will be applied with the following changes:</p>
            <ul className="space-y-1 text-slate-400">
              <li>• All {score.actions_required ?? 'the'} recommended actions will be scheduled</li>
              <li>• Team assignments will be updated according to the plan</li>
              <li>• Sprint schedules may be adjusted</li>
              <li>• Dependencies will be rebalanced</li>
            </ul>
          </div>

          {/* Error State */}
          {error && (
            <div className="rounded-lg border border-rose-500 bg-rose-500/10 p-3 text-sm text-rose-300">
              Failed to apply plan: {error.message}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-3 border-t border-slate-700 p-6">
          <button
            onClick={onClose}
            disabled={applying}
            className="flex-1 rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 font-medium text-slate-300 hover:bg-slate-700 transition disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleApply}
            disabled={applying}
            className="flex-1 rounded-lg bg-emerald-500 px-4 py-2 font-bold text-slate-950 hover:bg-emerald-400 transition disabled:bg-slate-600 disabled:text-slate-400 disabled:cursor-not-allowed"
          >
            {applying ? 'Applying...' : 'Confirm & Apply'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ApplyPlanModal
