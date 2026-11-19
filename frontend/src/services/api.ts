import type { ModelInfo, NetworkSignals, ScenarioInfo } from '../types/simulation'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const body = await r.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body: keep the status line */
    }
    throw new Error(detail)
  }
  return r.json() as Promise<T>
}

const post = <T = { ok: boolean; detail: string }>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export const api = {
  signals: () => request<NetworkSignals>('/api/v1/network/signals'),
  roadsUrl: '/api/v1/network/roads',
  scenarios: () => request<ScenarioInfo[]>('/api/v1/scenarios'),
  model: () => request<ModelInfo>('/api/v1/model'),
  start: () => post('/api/v1/simulation/start'),
  pause: () => post('/api/v1/simulation/pause'),
  resume: () => post('/api/v1/simulation/resume'),
  reset: () => post('/api/v1/simulation/reset'),
  speed: (speed: number) => post('/api/v1/simulation/speed', { speed }),
  demand: (scale: number) => post('/api/v1/simulation/demand', { scale }),
  dispatch: (type: string) => post('/api/v1/emergency-vehicles/dispatch', { type }),
  reroute: (id: string) => post(`/api/v1/emergency-vehicles/${encodeURIComponent(id)}/reroute`),
  select: (scenario: string, traffic: string | null, policy: string) =>
    post('/api/v1/scenarios/select', { scenario, traffic, policy, autostart: true }),
}
