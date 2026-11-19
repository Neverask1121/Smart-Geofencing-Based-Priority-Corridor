import { useStore } from '../../state/store'
import { clock } from '../common'
import { SpeedControl, TransportControls } from '../controls/SimulationControls'

const STATUS_TEXT: Record<string, string> = {
  idle: 'Idle', warming: 'Warming up', running: 'Running', paused: 'Paused', finished: 'Finished', error: 'Error',
}
const POLICY: Record<string, string> = { xgboost: 'XGBoost radius', none: 'No priority' }
export const policyLabel = (p: string | null | undefined) =>
  p ? POLICY[p] ?? `Fixed ${p.split('_')[1]} m` : '–'

export function SimClock() {
  const sim = useStore((s) => s.sim)
  const dot = sim?.status === 'running' ? 'bg-go pulse-dot' : sim?.status === 'error' ? 'bg-stop' : sim?.status === 'paused' ? 'bg-caution' : 'bg-ink-3'
  return (
    <div className="flex items-center gap-2">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span className="text-[12px] text-ink-2">
        {STATUS_TEXT[sim?.status ?? 'idle']}
        {sim?.status === 'warming' && ` ${Math.round((sim.warmup_progress ?? 0) * 100)}%`}
      </span>
      <span className="num text-[15px] font-medium">{clock(sim?.t ?? 0)}</span>
    </div>
  )
}

function Connection() {
  const c = useStore((s) => s.connection)
  const ms = useStore((s) => s.latencyMs)
  const cls = c === 'online' ? 'bg-go' : c === 'connecting' ? 'bg-caution pulse-dot' : 'bg-stop'
  return (
    <span className="flex items-center gap-1.5 text-[12px] text-ink-3">
      <span className={`h-1.5 w-1.5 rounded-full ${cls}`} aria-hidden />
      {c === 'online' ? `Live${ms !== null ? ` ${ms} ms` : ''}` : c === 'connecting' ? 'Connecting' : 'Offline'}
    </span>
  )
}

export function TopBar() {
  const sim = useStore((s) => s.sim)
  const setDemo = useStore((s) => s.setDemo)
  return (
    <header className="flex min-h-[52px] shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-4 py-2">
      <div className="min-w-0">
        <div className="truncate text-[14px] leading-tight font-semibold">Adaptive EV Priority</div>
        <div className="truncate text-[11px] leading-tight text-ink-3">Ahmedabad · Navrangpura to Paldi</div>
      </div>
      <div className="mx-1 h-6 w-px bg-line max-[640px]:hidden" />
      <SimClock />
      <div className="hidden min-w-0 flex-col xl:flex">
        <span className="truncate text-[12px] leading-tight text-ink-2">{sim?.scenario_name ?? 'No scenario'}</span>
        <span className="truncate text-[11px] leading-tight text-ink-3">
          {policyLabel(sim?.policy)} · {sim?.traffic ?? '–'} traffic
        </span>
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-3 max-[640px]:ml-0">
        <Connection />
        <SpeedControl />
        <TransportControls />
        <button className="btn" onClick={() => setDemo(true)} title="Presentation view (D)">Demo mode</button>
      </div>
    </header>
  )
}
