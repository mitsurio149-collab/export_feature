import { describe, expect, it } from 'vitest'
import { formatScheduleVariance } from './formatters'

describe('formatScheduleVariance', () => {
  it('formats positive delay as late', () => {
    expect(formatScheduleVariance(2)).toBe('+2.0d late')
  })

  it('formats negative delay as ahead', () => {
    expect(formatScheduleVariance(-2)).toBe('2.0d ahead')
  })

  it('formats zero as on target', () => {
    expect(formatScheduleVariance(0)).toBe('On target')
  })
})
