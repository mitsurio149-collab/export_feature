import React, { useState, useEffect } from 'react'
import { api } from '../../../api/client'
import ComparePlansTable from './ComparePlansTable'
import RecoveryPlanCard from './RecoveryPlanCard'
import PlanDetailView from './PlanDetailView'

/**
 * RecoveryPlansPage - Main container for recovery plan features
 * 
 * Flow:
 * 1. Loads all 3 recovery plans on mount
 * 2. Displays 3-card layout by default
 * 3. Can switch to Compare Plans table view
 * 4. Can expand individual plans for detailed view
 */
function RecoveryPlansPage({ session }) {
  const [plans, setPlans] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [view, setView] = useState('cards')  // 'cards' or 'compare'
  const [expandedPlanId, setExpandedPlanId] = useState(null)

  useEffect(() => {
    if (!session) return
    
    const sessionId = session.project_summary?.session_id
    if (!sessionId) return

    setLoading(true)
    setError(null)

    api
      .get(`/recovery-plans?session_id=${sessionId}`)
      .then(response => {
        if (response && response.plans) {
          setPlans(response.plans)
        } else {
          setError(new Error('Invalid response format'))
        }
        setLoading(false)
      })
      .catch(err => {
        setError(err)
        setLoading(false)
      })
  }, [session])

  if (loading) {
    return (
      <div className="rounded-3xl border border-slate-700 bg-slate-900 p-8 text-center">
        <div className="inline-block">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-emerald-500 border-t-transparent"></div>
        </div>
        <p className="mt-4 text-slate-400">Generating recovery plans...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-3xl border border-rose-700 bg-rose-900/20 p-6">
        <div className="flex items-start gap-4">
          <div className="text-2xl">⚠️</div>
          <div className="flex-1">
            <h3 className="font-semibold text-rose-200">Failed to generate recovery plans</h3>
            <p className="mt-1 text-sm text-rose-300">{error.message}</p>
            <button
              onClick={() => window.location.reload()}
              className="mt-3 rounded-lg border border-rose-500 bg-rose-500/10 px-3 py-1 text-sm font-medium text-rose-200 hover:bg-rose-500/20"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!plans || plans.length === 0) {
    return (
      <div className="rounded-3xl border border-slate-700 bg-slate-900 p-8">
        <p className="text-center text-slate-400">No recovery plans could be generated</p>
      </div>
    )
  }

  // If a plan is expanded, show detail view
  if (expandedPlanId) {
    const expandedPlan = plans.find(p => p.plan_id === expandedPlanId)
    if (expandedPlan) {
      return (
        <PlanDetailView
          plan={expandedPlan}
          session={session}
          onBack={() => setExpandedPlanId(null)}
        />
      )
    }
  }

  return (
    <div className="space-y-6">
      {/* View Toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setView('cards')}
          style={{
            border: view === 'cards' ? '1px solid var(--teal)' : '1px solid var(--line)',
            background: view === 'cards' ? 'oklch(36% .12 168)' : 'var(--panel)',
            color: view === 'cards' ? 'var(--text)' : 'var(--muted)',
            borderRadius: 4,
            padding: '5px 9px',
            fontSize: 9,
            cursor: 'pointer',
          }}
        >
          Strategy Overview
        </button>
        <button
          onClick={() => setView('compare')}
          style={{
            border: view === 'compare' ? '1px solid var(--teal)' : '1px solid var(--line)',
            background: view === 'compare' ? 'oklch(36% .12 168)' : 'var(--panel)',
            color: view === 'compare' ? 'var(--text)' : 'var(--muted)',
            borderRadius: 4,
            padding: '5px 9px',
            fontSize: 9,
            cursor: 'pointer',
          }}
        >
          Compare Strategies
        </button>
      </div>

      {/* Cards View */}
      {view === 'cards' && (
        <div>
          <div className="grid gap-4 grid-cols-1 md:grid-cols-3">
            {plans.map((plan, idx) => (
              <RecoveryPlanCard
                key={plan.plan_id}
                plan={plan}
                isRecommended={plan.label === 'Recommended'}
                onExpand={() => setExpandedPlanId(plan.plan_id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Compare View */}
      {view === 'compare' && (
        <ComparePlansTable
          plans={plans}
          onSelectPlan={(planId) => setExpandedPlanId(planId)}
        />
      )}
    </div>
  )
}

export default RecoveryPlansPage
