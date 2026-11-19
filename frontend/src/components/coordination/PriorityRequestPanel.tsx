import { useStore } from '../../state/store'
import { StatusBadge, clock, fmt } from '../common'

export function PriorityRequestPanel() {
  const requests = useStore((s) => s.requests)
  const selectTls = useStore((s) => s.selectTls)
  if (!requests.length) return <p className="p-3 text-[12px] text-ink-3">No priority requests yet.</p>
  return (
    <div className="space-y-2 p-3">
      {requests.map((r) => (
        <article key={r.id} className={`rounded-lg border p-2.5 ${r.conflicts_with.length && r.closed_at === null ? 'border-caution/50' : 'border-line'}`}>
          <div className="flex items-center gap-2">
            <span className="num font-semibold">{r.id}</span>
            <span className="num text-[11.5px] text-ink-3">{r.ev_id}</span>
            <span className="ml-auto"><StatusBadge status={r.status} /></span>
          </div>
          <button className="mt-1 block w-full truncate text-left text-[12px] text-ink-2 hover:text-ink" onClick={() => selectTls(r.tls, true)} title={r.tls_name}>
            {r.tls_name}
          </button>
          <div className="text-[11.5px] text-ink-3">
            {r.approach} {r.movement}
            {r.early && <span title="Opened by conflict lookahead, before this EV reached its own radius"> · opened early</span>}
          </div>
          <dl className="num mt-1.5 grid grid-cols-3 gap-1 text-[11.5px]">
            <div><dt className="font-sans text-[10.5px] text-ink-3">Radius</dt><dd>{fmt(r.radius)} m</dd></div>
            <div><dt className="font-sans text-[10.5px] text-ink-3">ETA</dt><dd>{fmt(r.eta)} s</dd></div>
            <div><dt className="font-sans text-[10.5px] text-ink-3">Score</dt><dd>{fmt(r.score, 2)}</dd></div>
          </dl>
          <div className="mt-1.5 text-[11.5px] text-ink-2">
            {r.conflicts_with.length > 0 && <span className="text-caution">Conflict with {r.conflicts_with.join(', ')}. </span>}
            {r.arbitration}
          </div>
        </article>
      ))}
    </div>
  )
}

const KIND_LABEL: Record<string, string> = {
  ev_dispatched: 'Dispatch',
  request_created: 'Request',
  conflict_detected: 'Conflict',
  arbitration: 'Arbitration',
  request_accepted: 'Accepted',
  signal_transition: 'Signal',
  priority_granted: 'Green',
  request_serving: 'Serving',
  ev_cleared: 'Cleared',
  restored: 'Restored',
  request_cancelled: 'Cancelled',
  request_expired: 'Expired',
  ev_arrived: 'Arrived',
  ev_rerouted: 'Reroute',
}

export function DecisionLog() {
  const events = useStore((s) => s.events)
  if (!events.length) return <p className="p-3 text-[12px] text-ink-3">Coordination decisions will appear here.</p>
  return (
    <ol className="p-3">
      {events.map((e) => (
        <li key={e.seq} className="border-b border-line/60 py-1.5 last:border-0">
          <div className="flex items-center gap-2">
            <span className="num text-[11px] text-ink-3">{clock(e.t)}</span>
            <span className={`text-[11px] font-semibold ${e.kind === 'conflict_detected' || e.kind === 'arbitration' ? 'text-caution' : 'text-ink-2'}`}>
              {KIND_LABEL[e.kind] ?? e.kind}
            </span>
          </div>
          <p className="mt-0.5 text-[12px] text-ink-2">{e.message}</p>
        </li>
      ))}
    </ol>
  )
}
