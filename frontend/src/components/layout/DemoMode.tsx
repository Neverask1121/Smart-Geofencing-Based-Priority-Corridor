import { useStore } from '../../state/store'
import { ConflictResolutionPanel } from '../coordination/ConflictResolutionPanel'
import { EmergencyVehicleList } from '../dashboard/EmergencyVehiclePanel'
import { MetricsPanel } from '../dashboard/MetricsPanel'
import { SimClock, policyLabel } from './TopBar'

function Ticker() {
  const e = useStore((s) => s.events.find((x) => x.kind !== 'ev_dispatched'))
  if (!e) return null
  return <p className="truncate text-[13px] text-ink">{e.message}</p>
}

function Predictions() {
  const n = useStore((s) => s.metrics?.predictions ?? 0)
  return <span className="num text-ink-3"> · {n} predictions</span>
}

/** Same map, same backend, same model: this only changes what is shown around them. */
export function DemoOverlay() {
  const sim = useStore((s) => s.sim)
  const setDemo = useStore((s) => s.setDemo)
  return (
    <>
      <div className="pointer-events-none absolute inset-x-3 top-3 z-10 flex items-start gap-3">
        <div className="glass pointer-events-auto px-3 py-2">
          <div className="text-[15px] leading-tight font-semibold">Adaptive EV Priority</div>
          <div className="text-[11.5px] text-ink-3">{sim?.scenario_name ?? 'No scenario'}</div>
        </div>
        <div className="glass pointer-events-auto min-w-0 flex-1 px-3 py-2">
          <div className="eyebrow">Latest decision</div>
          <Ticker />
        </div>
        <div className="glass pointer-events-auto flex items-center gap-3 px-3 py-2">
          <div>
            <SimClock />
            <div className="text-[11.5px] text-ink-2">{policyLabel(sim?.policy)}<Predictions /></div>
          </div>
          <button className="btn" onClick={() => setDemo(false)}>Operator view</button>
        </div>
      </div>
      <div className="scroll-thin absolute top-[84px] bottom-[100px] left-3 z-10 w-[270px] overflow-y-auto">
        <EmergencyVehicleList compact />
      </div>
      <div className="absolute top-[84px] right-3 z-10">
        <ConflictResolutionPanel />
      </div>
      <div className="glass absolute inset-x-3 bottom-3 z-10 overflow-hidden">
        <MetricsPanel />
      </div>
    </>
  )
}
