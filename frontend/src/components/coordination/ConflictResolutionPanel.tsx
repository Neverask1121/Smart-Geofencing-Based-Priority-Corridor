import { useMemo } from 'react'
import { useStore } from '../../state/store'
import type { IntersectionState, PriorityRequest, SimEvent } from '../../types/simulation'
import { StatusBadge, fmt } from '../common'

const LINGER_S = 45 // simulation seconds a resolved conflict stays on screen

/**
 * Explains a conflict using only the backend's requests and events. Finds the latest
 * pair of conflicting requests and reports which stages have really happened.
 */
function findConflict(events: SimEvent[], requests: PriorityRequest[]) {
  const e = events.find((x) => x.kind === 'conflict_detected')
  if (!e?.detail) return null
  const a = requests.find((r) => r.id === e.detail!.a)
  const b = requests.find((r) => r.id === e.detail!.b)
  if (!a || !b) return null
  return { a, b, tls: e.tls!, at: e.t }
}

export function steps(a: PriorityRequest, b: PriorityRequest, tls: string, events: SimEvent[], inter?: IntersectionState) {
  // Scores keep moving as requests wait, so show the ones the decision actually used.
  const decided = events.find((e) => e.kind === 'arbitration' && e.tls === tls && e.t >= Math.min(a.created_at, b.created_at))
  const used = decided?.detail?.scores as Record<string, number> | undefined
  const first = a.served_at !== null && (b.served_at === null || a.served_at <= b.served_at) ? a : b.served_at !== null ? b : a.accepted_at !== null ? a : b
  const second = first === a ? b : a
  const transition = events.some((e) => e.kind === 'signal_transition' && e.tls === tls && e.t >= Math.min(a.created_at, b.created_at))
  const closed = (r: PriorityRequest) => r.closed_at !== null
  return [
    { label: 'Both requests received', done: true },
    { label: 'Conflict detected: no shared phase', done: true },
    {
      label: used
        ? `Scores compared: ${a.id} ${fmt(used[a.id], 2)}, ${b.id} ${fmt(used[b.id], 2)}`
        : `${first.id} already held the junction`,
      done: true,
    },
    { label: first.accepted_at !== null ? `${first.id} ${used ? 'selected' : 'keeps priority'}` : 'Selecting a request', done: first.accepted_at !== null },
    {
      label: transition || first.served_at === null ? 'Safe signal transition' : 'Movement already green: no transition',
      done: transition || first.served_at !== null,
    },
    { label: `${first.ev_id} receives priority`, done: first.served_at !== null },
    { label: `${second.id} stays pending`, done: first.accepted_at !== null },
    { label: `${second.ev_id} served when safe`, done: second.served_at !== null },
    { label: 'Normal operation restored', done: closed(a) && closed(b) && inter?.mode === 'normal' },
  ]
}

export function ConflictResolutionPanel() {
  const events = useStore((s) => s.events)
  const requests = useStore((s) => s.requests)
  const inters = useStore((s) => s.intersections)
  const name = useStore((s) => s.signalById)
  const t = useStore((s) => s.sim?.t ?? 0)
  const c = useMemo(() => findConflict(events, requests), [events, requests])
  if (!c) return null
  const { a, b, tls } = c
  const ended = Math.max(a.closed_at ?? Infinity, b.closed_at ?? Infinity)
  if (t > ended + LINGER_S) return null
  const list = steps(a, b, tls, events, inters[tls])
  const current = list.findIndex((s) => !s.done)
  return (
    <section className="glass w-[330px] p-3" aria-label="Conflict resolution">
      <div className="eyebrow text-caution">Conflict resolution</div>
      <div className="mt-0.5 truncate text-[13px] font-semibold" title={name[tls]?.name}>{name[tls]?.name ?? tls}</div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {[a, b].map((r) => (
          <div key={r.id} className="rounded-md bg-raised/70 p-2">
            <div className="flex items-center justify-between gap-1">
              <span className="num text-[12px] font-semibold">{r.ev_id}</span>
              <StatusBadge status={r.status} />
            </div>
            <div className="truncate text-[11px] text-ink-3">{r.approach}</div>
            <div className="num mt-1 flex justify-between gap-2 text-[11.5px]">
              <span>ETA {fmt(r.eta)} s</span>
              <span>R {fmt(r.radius)} m</span>
            </div>
          </div>
        ))}
      </div>
      <ol className="mt-2.5 space-y-[3px]">
        {list.map((s, i) => (
          <li key={i} className={`flex items-center gap-2 text-[11.5px] ${s.done ? 'text-ink' : i === current ? 'text-ink-2' : 'text-ink-3'}`}>
            <span className={`num grid h-4 w-4 shrink-0 place-items-center rounded-full text-[9.5px] ${s.done ? 'bg-go text-[#06121f]' : 'bg-raised'}`}>{i + 1}</span>
            <span className="truncate">{s.label}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
