/** Low-rate UI state. Components subscribe to narrow slices of this store. */
import { create } from 'zustand'
import type {
  EmergencyVehicle,
  EvRoute,
  HistoryPoint,
  IntersectionState,
  Metrics,
  ModelInfo,
  NetworkSignals,
  PriorityRequest,
  ScenarioInfo,
  ServerMessage,
  SignalInfo,
  SimEvent,
  SimStatus,
} from '../types/simulation'
import { live } from './live'

export type ConnectionState = 'connecting' | 'online' | 'offline'
export type LayerKey = 'roads' | 'vehicles' | 'signals' | 'geofences' | 'routes' | 'labels'

const EVENT_LIMIT = 200
const HISTORY_LIMIT = 360

interface State {
  connection: ConnectionState
  latencyMs: number | null
  sim: SimStatus | null
  evs: EmergencyVehicle[]
  routes: Record<string, EvRoute>
  signals: Record<string, string>
  intersections: Record<string, IntersectionState>
  requests: PriorityRequest[]
  events: SimEvent[]
  metrics: Metrics | null
  history: HistoryPoint[]
  network: NetworkSignals | null
  signalById: Record<string, SignalInfo>
  scenarios: ScenarioInfo[]
  model: ModelInfo | null

  selectedEv: string | null
  selectedTls: string | null
  selectedVehicle: number | null
  demoMode: boolean
  layers: Record<LayerKey, boolean>
  rightTab: 'intersection' | 'coordination' | 'log' | 'model'
  toast: string | null
  focusRequest: { lon: number; lat: number; zoom?: number; n: number } | null

  ingest: (m: ServerMessage) => void
  selectEv: (id: string | null, focus?: boolean) => void
  selectTls: (id: string | null, focus?: boolean) => void
  selectVehicle: (key: number | null) => void
  setDemo: (on: boolean) => void
  toggleLayer: (k: LayerKey) => void
  setRightTab: (t: State['rightTab']) => void
  setToast: (t: string | null) => void
}

const index = (xs: IntersectionState[]) => Object.fromEntries(xs.map((x) => [x.id, x]))

export const useStore = create<State>((set, get) => ({
  connection: 'connecting',
  latencyMs: null,
  sim: null,
  evs: [],
  routes: {},
  signals: {},
  intersections: {},
  requests: [],
  events: [],
  metrics: null,
  history: [],
  network: null,
  signalById: {},
  scenarios: [],
  model: null,

  selectedEv: null,
  selectedTls: null,
  selectedVehicle: null,
  demoMode: false,
  layers: { roads: true, vehicles: true, signals: true, geofences: true, routes: true, labels: true },
  rightTab: 'intersection',
  toast: null,
  focusRequest: null,

  ingest: (m) => {
    const now = performance.now()
    if (m.type === 'snapshot') {
      const prev = get().sim?.run_id
      if (prev !== m.run_id) get().selectVehicle(null)
      live.reset()
      live.apply(m.veh, now, true)
      live.applyEvs(m.evs, now)
      set({
        sim: m.sim,
        evs: m.evs,
        routes: m.routes,
        signals: m.signals,
        intersections: index(m.intersections),
        requests: m.requests,
        events: m.events.slice(-EVENT_LIMIT).reverse(),
        metrics: m.metrics,
        history: m.history,
        ...(prev !== m.run_id ? { selectedEv: null } : {}),
      })
    } else if (m.type === 'frame') {
      live.apply(m.veh, now)
      live.applyEvs(m.evs, now)
      const s = get()
      const liveIds = new Set(m.evs.map((e) => e.id))
      const routes: Record<string, EvRoute> = {}
      for (const [id, r] of Object.entries({ ...s.routes, ...m.routes })) if (liveIds.has(id)) routes[id] = r
      const signals = Object.keys(m.signals).length ? { ...s.signals, ...m.signals } : s.signals
      set({
        sim: m.sim,
        evs: m.evs,
        routes,
        signals,
        requests: m.requests,
        ...(m.intersections ? { intersections: index(m.intersections) } : {}),
        ...(m.events.length ? { events: [...[...m.events].reverse(), ...s.events].slice(0, EVENT_LIMIT) } : {}),
        ...(m.metrics ? { metrics: m.metrics } : {}),
        ...(m.history_point ? { history: [...s.history, m.history_point].slice(-HISTORY_LIMIT) } : {}),
        ...(s.selectedEv && !liveIds.has(s.selectedEv) ? { selectedEv: null } : {}),
      })
    } else if (m.type === 'status') {
      set({ sim: m.sim })
    } else if (m.type === 'error') {
      set({ toast: m.message })
    }
  },

  selectEv: (id, focus = true) => {
    const ev = get().evs.find((e) => e.id === id)
    const n = (get().focusRequest?.n ?? 0) + 1
    set({
      selectedEv: id,
      selectedVehicle: null,
      ...(focus && ev ? { focusRequest: { lon: ev.lon, lat: ev.lat, zoom: 15.5, n } } : {}),
    })
  },
  selectTls: (id, focus = false) => {
    const sig = id ? get().signalById[id] : null
    const n = (get().focusRequest?.n ?? 0) + 1
    set({
      selectedTls: id,
      ...(id ? { rightTab: 'intersection' as const } : {}),
      ...(focus && sig ? { focusRequest: { lon: sig.lon, lat: sig.lat, zoom: 16.2, n } } : {}),
    })
  },
  selectVehicle: (key) => set({ selectedVehicle: key }),
  setDemo: (on) => set({ demoMode: on }),
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),
  setRightTab: (t) => set({ rightTab: t }),
  setToast: (t) => set({ toast: t }),
}))
