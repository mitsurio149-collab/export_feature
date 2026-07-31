// Presentation-only config for RecommendationImpactProfile.impact_metrics.dimensions[].type
// The backend intentionally sends only the stable canonical key (see
// app/engines/recommendation_engine/pm_models.py:ImpactDimensionType) — title,
// icon, and display order are a frontend concern by design. Keep this the
// single place that maps a dimension type to how it's shown.

export const DIMENSION_CONFIG = {
  schedule:    { label: 'Schedule',    order: 1, barColor: 'bg-sky-500' },
  risk:        { label: 'Risk',        order: 2, barColor: 'bg-rose-500' },
  resilience:  { label: 'Resilience',  order: 3, barColor: 'bg-violet-500' },
  quality:     { label: 'Quality',     order: 4, barColor: 'bg-emerald-500' },
  forecast:    { label: 'Forecast',    order: 5, barColor: 'bg-amber-500' },
  governance:  { label: 'Governance',  order: 6, barColor: 'bg-fuchsia-500' },
  resource:    { label: 'Resource',    order: 7, barColor: 'bg-teal-500' },
}

export function dimensionLabel(type) {
  return DIMENSION_CONFIG[type]?.label || (type ? type.charAt(0).toUpperCase() + type.slice(1) : 'Impact')
}

export function dimensionBarColor(type) {
  return DIMENSION_CONFIG[type]?.barColor || 'bg-slate-500'
}

// Sort dimensions by their configured display order; unknown types sort last
// but stay visible (never hidden, per "render dynamically, don't hardcode").
export function sortDimensions(dimensions) {
  if (!Array.isArray(dimensions)) return []
  return [...dimensions].sort((a, b) => {
    const oa = DIMENSION_CONFIG[a.type]?.order ?? 999
    const ob = DIMENSION_CONFIG[b.type]?.order ?? 999
    return oa - ob
  })
}

// Confidence label -> badge color (shared by dimension confidence and
// aggregate/impact-tier confidence, all of which use the same Very High /
// High / Medium / Low vocabulary).
export function confidenceColor(level) {
  switch (level) {
    case 'Very High':
    case 'High':
      return 'bg-emerald-500/20 text-emerald-300'
    case 'Medium':
      return 'bg-amber-500/20 text-amber-300'
    case 'Low':
      return 'bg-rose-500/20 text-rose-300'
    default:
      return 'bg-slate-500/20 text-slate-300'
  }
}

// Execution window -> badge color. No hardcoded meaning beyond display;
// backend sends the canonical enum value verbatim.
export function executionWindowColor(window) {
  switch (window) {
    case 'Immediately':
      return 'bg-rose-500/20 text-rose-300'
    case 'Current Sprint':
      return 'bg-amber-500/20 text-amber-300'
    case 'Before Release':
      return 'bg-fuchsia-500/20 text-fuchsia-300'
    case 'Next Sprint':
      return 'bg-sky-500/20 text-sky-300'
    case 'Long Term':
      return 'bg-slate-500/20 text-slate-300'
    default:
      return 'bg-slate-500/20 text-slate-300'
  }
}

export function impactTierColor(tier) {
  switch (tier) {
    case 'High':
      return 'bg-rose-500/20 text-rose-300'
    case 'Medium':
      return 'bg-amber-500/20 text-amber-300'
    case 'Low':
      return 'bg-slate-500/20 text-slate-300'
    default:
      return 'bg-slate-500/20 text-slate-300'
  }
}
