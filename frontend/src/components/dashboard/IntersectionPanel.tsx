import { useMemo } from 'react'
import { useStore } from '../../state/store'
import type { PriorityRequest, SignalInfo } from '../../types/simulation'
import { Stat, StatusBadge, fmt } from '../common'

const TURN = { s: 'Through', l: 'Left', r: 'Right', t: 'U-turn', L: 'Left', R: 'Right' } as Record<string, string>
const ARROW = { s: '↑', l: '←', r: '→', t: '↶', L: '↖', R: '↗' } as Record<string, string>

function Lamp({ c }: { c: string | undefined }) {
  const on = c === 'G' || c === 'g'
  const y = c === 'y' || c === 'Y'
  const label = on ? 'Green' : y ? 'Yellow' : 'Red'
  return (
    <span
      title={label}
      aria-label={label}
      className={`inline-block h-2.5 w-2.5 rounded-full ${on ? 'bg-go' : y ? 'bg-caution' : 'bg-stop'}`}
    />
  )
}

function Movements({ sig, state, target }: { sig: SignalInfo; state: string; target: string | null }) {
  return (
    <div className="space-y-1.5">
      {sig.approaches.map((a) => {
        const groups = new Map<string, number[]>()
        for (const i of a.links) {
          const l = sig.links.find((x) => x.index === i)
          if (!l) continue
          const k = `${l.turn}|${l.out_edge}`
          groups.set(k, [...(groups.get(k) ?? []), i])
        }
        return (
          <div key={a.edge} className="rounded-md bg-raised/60 px-2 py-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[12px] font-medium">{a.label}</span>
              <span className="truncate text-[11px] text-ink-3">{a.name || 'Unnamed'}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
              {[...groups.entries()].map(([k, links]) => {
                const turn = k.split('|')[0]
                const held = target && !links.some((i) => 'Gg'.includes(target[i]))
                return (
                  <span key={k} className="inline-flex items-center gap-1 text-[11.5px] text-ink-2">
                    <Lamp c={state[links[0]]} />
                    <span aria-hidden>{ARROW[turn] ?? '↑'}</span>
                    {TURN[turn] ?? turn}
                    {target && !held && <span className="text-[10.5px] text-go">priority</span>}
                  </span>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const MODE_LABEL: Record<string, string> = {
  normal: 'Normal program',
  holding_min_green: 'Holding minimum green',
  yellow: 'Yellow clearance',
  all_red: 'All-red clearance',
  serving: 'Priority green',
  restoring: 'Restoring program',
}

function Lifecycle({ r, mode, events }: { r: PriorityRequest; mode: string; events: { kind: string; t: number; req: string | null; tls: string | null }[] }) {
  const after = (k: string) => events.some((e) => e.kind === k && e.tls === r.tls && e.t >= r.created_at)
  const steps: [string, boolean][] = [
    ['Request pending', true],
    ['Signal transition', r.accepted_at !== null && (after('signal_transition') || r.served_at !== null)],
    ['Conflicting movements held', mode === 'all_red' || r.served_at !== null],
    ['Priority granted', r.served_at !== null],
    ['EV cleared intersection', r.status === 'completed'],
    ['Normal operation restored', r.status === 'completed' && mode === 'normal'],
  ]
  return (
    <ol className="mt-2 space-y-1">
      {steps.map(([label, done]) => (
        <li key={label} className={`flex items-center gap-2 text-[11.5px] ${done ? 'text-ink' : 'text-ink-3'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${done ? 'bg-go' : 'bg-line'}`} aria-hidden />
          {label}
        </li>
      ))}
    </ol>
  )
}

export function IntersectionPanel() {
  const id = useStore((s) => s.selectedTls)
  const sig = useStore((s) => (id ? s.signalById[id] : undefined))
  const info = useStore((s) => (id ? s.intersections[id] : undefined))
  const state = useStore((s) => (id ? s.signals[id] : undefined))
  const requests = useStore((s) => s.requests)
  const events = useStore((s) => s.events)
  const list = useStore((s) => s.network?.signals)
  const selectTls = useStore((s) => s.selectTls)
  const here = useMemo(() => requests.filter((r) => r.tls === id).slice(0, 4), [requests, id])
  const options = useMemo(() => [...(list ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [list])

  return (
    <div className="space-y-3 p-3">
      <select className="field" value={id ?? ''} onChange={(e) => selectTls(e.target.value || null, true)} aria-label="Select intersection">
        <option value="">Select an intersection…</option>
        {options.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {!sig && <p className="text-[12px] text-ink-3">Click a signal on the map to inspect it.</p>}
      {sig && (
        <>
          <div>
            <h3 className="text-[14px] leading-snug font-semibold">{sig.name}</h3>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-3">
              <span className="num truncate" title={sig.id}>{sig.id.slice(0, 24)}</span>
              <span className="shrink-0 rounded border border-line px-1" title={sig.source === 'osm' ? 'Signal mapped in OpenStreetMap' : 'No signal in OSM; added at a major crossroads'}>
                {sig.source === 'osm' ? 'OSM signal' : 'Inferred signal'}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <Stat label="Queue" value={info?.queue ?? '–'} unit="veh" />
            <Stat label="Density" value={fmt(info?.density, 0)} unit="/km" />
            <Stat label="Speed" value={fmt(info?.avg_speed, 1)} unit="m/s" />
            <Stat label="On links" value={info?.vehicles ?? '–'} />
          </div>
          <div>
            <div className="eyebrow mb-1">Signal</div>
            <div className="mb-1.5 text-[12px] text-ink-2">
              {MODE_LABEL[info?.mode ?? 'normal'] ?? info?.mode} · {sig.phases.length} program phases
            </div>
            {state ? <Movements sig={sig} state={state} target={info?.target_state ?? null} /> : <p className="text-[12px] text-ink-3">No simulation running.</p>}
          </div>
          {info && info.approaching_evs.length > 0 && (
            <div>
              <div className="eyebrow mb-1">Approaching</div>
              <div className="num text-[12px] text-ink-2">{info.approaching_evs.join(', ')}</div>
            </div>
          )}
          {here.length > 0 && (
            <div className="space-y-2">
              <div className="eyebrow">Requests here</div>
              {here.map((r) => (
                <div key={r.id} className="rounded-md border border-line p-2">
                  <div className="flex items-center justify-between">
                    <span className="num text-[12px]">{r.id} · {r.ev_id}</span>
                    <StatusBadge status={r.status} />
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-ink-3">{r.approach} {r.movement}</div>
                  {r.conflicts_with.length > 0 && <div className="mt-0.5 text-[11.5px] text-caution">Conflicts with {r.conflicts_with.join(', ')}</div>}
                  <Lifecycle r={r} mode={info?.mode ?? 'normal'} events={events} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
