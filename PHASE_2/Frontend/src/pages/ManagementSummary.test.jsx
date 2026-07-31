import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

const { mockMonteCarlo } = vi.hoisted(() => ({
  mockMonteCarlo: {
    monte_carlo: {
      target_end_date: '2025-01-15T00:00:00.000Z',
      simulation_count: 2500,
      seed: 123,
      statistics: {
        percentile_50: '2025-01-16T00:00:00.000Z',
        percentile_80: '2025-01-17T00:00:00.000Z',
        percentile_95: '2025-01-18T00:00:00.000Z',
        percentile_10: '2025-01-14T00:00:00.000Z',
      },
      on_time_probability: 0.62,
    },
  },
}))

vi.mock('../api/client', () => {
  const api = {
    monteCarlo: vi.fn().mockResolvedValue(mockMonteCarlo),
    forecast: vi.fn().mockResolvedValue({ forecast: { expected_finish_date: '2025-01-16T00:00:00.000Z', confidence_score: 0.7, target_end_date: '2025-01-15T00:00:00.000Z' } }),
    risk: vi.fn().mockResolvedValue({ risk_analysis: { overall_risk_score: 40 } }),
    dependencies: vi.fn().mockResolvedValue([]),
    forecastTrend: vi.fn().mockResolvedValue({ entry_count: 1, entries: [{ p80_date: '2025-01-17T00:00:00.000Z', p50_date: '2025-01-16T00:00:00.000Z', p95_date: '2025-01-18T00:00:00.000Z', on_time_probability: 0.62, expected_delay_days: 2 }] }),
  }

  return { api }
})

import { ManagementSummary } from './ManagementSummary'

describe('ManagementSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the actual Monte Carlo simulation count and seed', async () => {
    render(<ManagementSummary session={{ project_summary: { session_id: 'abc' } }} />)

    await waitFor(() => {
      expect(screen.getByText(/2,500 simulations \(seed 123\)/i)).toBeInTheDocument()
    })
  })
})
