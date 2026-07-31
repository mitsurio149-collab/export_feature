// API client wrapper that follows the backend error contract.
const API_ROOT = '/api'

async function unwrapResponse(resp){
  const text = await resp.text()
  let json = null
  try{ json = text ? JSON.parse(text) : null }catch(e){ }

  if(!resp.ok){
    const detail = json && json.detail ? json.detail : null
    const message = detail && detail.message ? detail.message : (json && json.message) ? json.message : resp.statusText
    const err = new Error(message)
    err.status = resp.status
    err.detail = detail
    throw err
  }

  if(json && json.success===false){
    const msg = json.message || (json.data && json.data.message) || 'Request failed'
    const err = new Error(msg)
    err.detail = json
    throw err
  }

  return json && json.data !== undefined ? json.data : json
}

function sessionUrl(path, sessionId){
  let url = `${API_ROOT}${path}`
  if(sessionId) url += `?session_id=${encodeURIComponent(sessionId)}`
  return url
}

export const api = {
  health: async () => {
    const resp = await fetch(`${API_ROOT}/health`)
    return unwrapResponse(resp)
  },
  upload: async (formData) => {
    const resp = await fetch(`${API_ROOT}/upload`, { method: 'POST', body: formData })
    return unwrapResponse(resp)
  },
  demoLoad: async () => {
    const resp = await fetch(`${API_ROOT}/demo/load`, { method: 'POST' })
    return unwrapResponse(resp)
  },
  demoReset: async () => {
    const resp = await fetch(`${API_ROOT}/demo/reset`, { method: 'POST' })
    return unwrapResponse(resp)
  },

  // ── Single-call overview snapshot (replaces separate forecast + MC + risk + trace calls) ──
  sessionSnapshot: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/session-snapshot', sessionId))
    return unwrapResponse(resp)
  },

  metrics: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/metrics', sessionId))
    return unwrapResponse(resp)
  },
  dependencies: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/dependencies', sessionId))
    return unwrapResponse(resp)
  },
  spillover: async () => {
    const resp = await fetch(`${API_ROOT}/spillover`)
    return unwrapResponse(resp)
  },
  forecast: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/forecast', sessionId))
    return unwrapResponse(resp)
  },
  monteCarlo: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/monte-carlo', sessionId))
    return unwrapResponse(resp)
  },
  forecastTrend: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/forecast-trend', sessionId))
    return unwrapResponse(resp)
  },
  risk: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/risk', sessionId))
    return unwrapResponse(resp)
  },
  recommendations: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/recommendations', sessionId))
    return unwrapResponse(resp)
  },
  simulateRecommendation: async (body, sessionId = '') => {
    let url = sessionUrl('/recommendations/simulate', sessionId)
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return unwrapResponse(resp)
  },
  simulateScenario: async (body, sessionId = '') => {
    let url = sessionUrl('/recommendations/scenario', sessionId)
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return unwrapResponse(resp)
  },
  scopeChange: async (body) => {
    const resp = await fetch(`${API_ROOT}/scope-change`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return unwrapResponse(resp)
  },
  export: async () => {
    const resp = await fetch(`${API_ROOT}/export`)
    if (!resp.ok) {
      const text = await resp.text()
      let json = null; try { json = JSON.parse(text) } catch (e) {}
      const detail = json && json.detail ? json.detail : null
      const message = detail && detail.message ? detail.message : resp.statusText
      throw new Error(message)
    }
    return resp.blob()
  },
  reforecastComparison: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/reforecast-comparison', sessionId))
    return unwrapResponse(resp)
  },
  narrative: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/narrative', sessionId))
    return unwrapResponse(resp)
  },
  reasoningTrace: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/reasoning-trace', sessionId))
    return unwrapResponse(resp)
  },
  diagnosis: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/diagnosis', sessionId))
    return unwrapResponse(resp)
  },
  sprintHealth: async (sessionId = '') => {
    const resp = await fetch(sessionUrl('/sprint-health', sessionId))
    return unwrapResponse(resp)
  },
  learningOutcome: async (body) => {
    const resp = await fetch(`${API_ROOT}/learning/outcome`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return unwrapResponse(resp)
  },
  get: async (path, params = {}) => {
    let url = `${API_ROOT}${path.startsWith('/') ? path : '/' + path}`
    const qs = new URLSearchParams(params).toString()
    if (qs) url += `${url.includes('?') ? '&' : '?'}${qs}`
    const resp = await fetch(url)
    return unwrapResponse(resp)
  },
  post: async (path, body = null, params = {}) => {
    let url = `${API_ROOT}${path.startsWith('/') ? path : '/' + path}`
    const qs = new URLSearchParams(params).toString()
    if (qs) url += `${url.includes('?') ? '&' : '?'}${qs}`
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
    return unwrapResponse(resp)
  },
}
