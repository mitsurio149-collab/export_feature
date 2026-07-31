export function formatScheduleVariance(days) {
  if (days === null || days === undefined || Number.isNaN(days)) return '—'
  if (days > 0.05) return `+${days.toFixed(1)}d late`
  if (days < -0.05) return `${Math.abs(days).toFixed(1)}d ahead`
  return 'On target'
}

// ── Safe formatting helpers ──
// These guard against fields that may be missing/null on any given
// recommendation or recovery plan payload so the UI degrades gracefully
// (shows a neutral placeholder) instead of throwing and blanking the page.

export function formatPercent(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Number(value).toFixed(digits)
}

export function formatDays(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${Number(value).toFixed(digits)}d`
}
