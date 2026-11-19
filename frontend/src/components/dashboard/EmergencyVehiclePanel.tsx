import { memo } from 'react'
import { api } from '../../services/api'
import { useStore } from '../../state/store'
import type { EmergencyVehicle } from '../../types/simulation'
import { EV_LABEL, RadiusMeter, Stat, StatusBadge, fmt } from '../common'
import { EV_HEX } from '../map/icons'

const FEATURE_LABELS: [string, string, string][] = [
  ['queue_ahead', 'Queue ahead', 'veh'],
  ['density_ahead', 'Density ahead', 'veh/km/ln'],
  ['mean_speed_ahead', 'Speed ahead', 'm/s'],
  ['link_green', 'Movement green', ''],
  ['time_to_green', 'Time to green', 's'],
  ['cross_queue', 'Cross queue', 'veh'],
]

const Card = memo(function Card({ e, selected, compact }: { e: EmergencyVehicle; selected: boolean; compact?: boolean }) {
  const select = useStore((s) => s.selectEv)
  const color = EV_HEX[e.color % EV_HEX.length]
  return (
    <button
      onClick={() => select(selected ? null : e.id)}
      className={`block w-full rounded-lg border p-2.5 text-left transition-colors ${
        selected ? 'border-accent bg-raised' : 'border-line bg-panel hover:bg-raised'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: color }} aria-hidden />
        <span className="num font-semibold">{e.id}</span>
        <span className="truncate text-[11px] text-ink-3">{EV_LABEL[e.type]}</span>
        <span className="ml-auto">
          <StatusBadge status={e.request_status && e.status === e.request_status ? e.request_status : e.status} />
        </span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2">
        <Stat label="Radius" value={fmt(e.radius)} unit="m" />
        <Stat label="Speed" value={fmt(e.speed * 3.6)} unit="km/h" />
        <Stat label="ETA" value={fmt(e.eta)} unit="s" />
      </div>
      {!compact && (
        <div className="mt-1.5 truncate text-[11.5px] text-ink-2" title={e.next_tls_name ?? undefined}>
          {e.next_tls_name ? `Next: ${e.next_tls_name}` : 'No signals left on route'}
        </div>
      )}
      <RadiusMeter dist={e.dist_to_tls} radius={e.radius} active={e.in_geofence} color={color} />
    </button>
  )
})

function Detail({ e }: { e: EmergencyVehicle }) {
  const pct = e.route_total_m ? (e.route_progress_m / e.route_total_m) * 100 : 0
  return (
    <div className="border-t border-line p-3">
      <div className="eyebrow mb-2">{e.id} detail</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Stat label="Location" value={`${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}`} />
        <Stat label="Request" value={e.request_id ?? 'None'} />
        <Stat label="Route distance" value={fmt(e.route_dist_to_tls)} unit="m" />
        <Stat label="Signals left" value={e.upcoming_tls.length} />
        <Stat label="Travel time" value={fmt(e.travel_time)} unit="s" />
        <Stat label="Time lost" value={fmt(e.time_loss, 1)} unit="s" />
      </div>
      <div className="mt-2.5 h-1 rounded-full bg-raised">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <div className="num mt-1 text-[11px] text-ink-3">
        {(e.route_progress_m / 1000).toFixed(2)} of {(e.route_total_m / 1000).toFixed(2)} km
      </div>
      <button
        className="btn mt-2.5 w-full justify-center"
        onClick={() => api.reroute(e.id).catch((x: Error) => useStore.getState().setToast(x.message))}
      >
        Reroute {e.id}
      </button>
      {Object.keys(e.features).length > 0 && (
        <>
          <div className="eyebrow mt-3 mb-1.5">Model inputs, live</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
            {FEATURE_LABELS.map(([k, label, unit]) => (
              <div key={k} className="flex justify-between gap-2 text-[11.5px]">
                <dt className="truncate text-ink-3">{label}</dt>
                <dd className="num text-ink-2">
                  {k === 'link_green' ? (e.features[k] ? 'Yes' : 'No') : `${e.features[k]?.toFixed(1) ?? '–'} ${unit}`}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </div>
  )
}

export function EmergencyVehicleList({ compact }: { compact?: boolean }) {
  const evs = useStore((s) => s.evs)
  const selected = useStore((s) => s.selectedEv)
  if (!evs.length) {
    return <p className="px-1 py-2 text-[12px] text-ink-3">No emergency vehicles active.</p>
  }
  return (
    <div className="space-y-2">
      {evs.map((e) => (
        <Card key={e.id} e={e} selected={e.id === selected} compact={compact} />
      ))}
    </div>
  )
}

export function EmergencyVehiclePanel() {
  const selected = useStore((s) => s.evs.find((e) => e.id === s.selectedEv))
  const n = useStore((s) => s.evs.length)
  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between px-3 pt-3 pb-2">
        <h2 className="eyebrow">Emergency vehicles</h2>
        <span className="num text-[11px] text-ink-3">{n} active</span>
      </header>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <EmergencyVehicleList />
      </div>
      {selected && <Detail e={selected} />}
    </section>
  )
}
