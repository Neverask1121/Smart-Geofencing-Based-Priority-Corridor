// Mirrors backend/app/schemas.py and the frames built in backend/app/engine.py.

export const PROTOCOL = 1

export type EvType = 'ambulance' | 'fire_engine' | 'police'
export type SimStatusName = 'idle' | 'warming' | 'running' | 'paused' | 'finished' | 'error'
export type RequestStatus = 'pending' | 'accepted' | 'serving' | 'completed' | 'cancelled' | 'expired'

export interface SimStatus {
  run_id: number
  status: SimStatusName
  t: number
  speed: number
  achieved_speed: number
  scenario: string | null
  scenario_name: string | null
  traffic: string | null
  scale: number | null
  policy: string | null
  message: string | null
  warmup_progress: number
  clients: number
}

export interface EmergencyVehicle {
  id: string
  type: EvType
  color: number
  lon: number
  lat: number
  angle: number
  speed: number
  status: string
  next_tls: string | null
  next_tls_name: string | null
  dist_to_tls: number | null
  route_dist_to_tls: number | null
  eta: number | null
  radius: number | null
  in_geofence: boolean
  request_id: string | null
  request_status: RequestStatus | null
  route_version: number
  route_progress_m: number
  route_total_m: number
  upcoming_tls: string[]
  time_loss: number
  travel_time: number
  predictions: number
  features: Record<string, number>
}

export interface EvRoute {
  version: number
  coords: [number, number][]
  cum: number[]
}

export interface PriorityRequest {
  id: string
  ev_id: string
  ev_type: EvType
  tls: string
  tls_name: string
  approach: string
  movement: string
  radius: number
  eta: number
  dist: number
  status: RequestStatus
  score: number
  score_parts: Record<string, number>
  conflicts_with: string[]
  arbitration: string
  created_at: number
  accepted_at: number | null
  served_at: number | null
  closed_at: number | null
  early: boolean
}

export interface IntersectionState {
  id: string
  state: string
  mode: string
  target_state: string | null
  queue: number
  vehicles: number
  density: number
  avg_speed: number | null
  active_requests: string[]
  pending_requests: string[]
  approaching_evs: string[]
  safety_violations: number
}

export interface SimEvent {
  seq: number
  t: number
  kind: string
  tls: string | null
  ev: string | null
  req: string | null
  message: string
  detail: Record<string, unknown> | null
}

export interface Metrics {
  t: number
  vehicles: number
  active_evs: number
  evs_completed: number
  avg_ev_travel_time: number | null
  avg_ev_time_loss: number | null
  avg_civilian_delay: number | null
  civilian_trips: number
  avg_queue: number
  run_avg_queue: number | null
  throughput_per_min: number
  requests_total: number
  requests_successful: number
  requests_open: number
  requests_expired: number
  requests_cancelled: number
  conflicts_detected: number
  avg_radius_now: number | null
  avg_radius_run: number | null
  predictions: number
  safety_violations: number
  collisions: number
  teleports: number
}

export type HistoryPoint = Pick<
  Metrics,
  't' | 'avg_queue' | 'avg_civilian_delay' | 'throughput_per_min' | 'vehicles' | 'active_evs' | 'avg_radius_now'
>

export interface VehicleBlock {
  add: [number, number][]
  del: number[]
  pos: number[] // flat: key, lon, lat, angle, speed
}

interface Base {
  v: number
  seq: number
  sim: SimStatus
}

export interface SnapshotMessage extends Base {
  type: 'snapshot'
  run_id: number
  t: number
  veh: VehicleBlock
  evs: EmergencyVehicle[]
  routes: Record<string, EvRoute>
  signals: Record<string, string>
  intersections: IntersectionState[]
  requests: PriorityRequest[]
  events: SimEvent[]
  metrics: Metrics | null
  history: HistoryPoint[]
}

export interface FrameMessage extends Base {
  type: 'frame'
  run_id: number
  t: number
  veh: VehicleBlock
  evs: EmergencyVehicle[]
  routes: Record<string, EvRoute>
  signals: Record<string, string>
  intersections?: IntersectionState[]
  requests: PriorityRequest[]
  events: SimEvent[]
  metrics?: Metrics
  history_point?: HistoryPoint
}

export interface StatusMessage extends Base {
  type: 'status'
}

export type ServerMessage =
  | SnapshotMessage
  | FrameMessage
  | StatusMessage
  | { type: 'pong'; nonce: number | null }
  | { type: 'error'; message: string }

export interface SignalApproach {
  edge: string
  name: string
  label: string
  bearing: number
  lanes: number
  lon: number
  lat: number
  links: number[]
}

export interface SignalLink {
  index: number
  in_edge: string
  out_edge: string
  turn: string
}

export interface SignalInfo {
  id: string
  name: string
  source: 'osm' | 'inferred'
  lon: number
  lat: number
  phases: { state: string; duration: number }[]
  approaches: SignalApproach[]
  links: SignalLink[]
}

export interface NetworkSignals {
  signals: SignalInfo[]
  bbox: [number, number, number, number]
}

export interface ScenarioInfo {
  id: string
  name: string
  description: string
  traffic: 'low' | 'medium' | 'high'
  ev_count: number
  focus: string | null
}

export interface ModelInfo {
  loaded: boolean
  error?: string
  predictions?: number
  last_latency_ms?: number
  [key: string]: unknown
}
