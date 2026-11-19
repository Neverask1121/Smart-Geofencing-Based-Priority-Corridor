import type { ReactNode } from 'react'
import type { EvType, RequestStatus } from '../types/simulation'

export const EV_LABEL: Record<EvType, string> = { ambulance: 'Ambulance', fire_engine: 'Fire engine', police: 'Police' }

const STATUS: Record<string, { label: string; cls: string; glyph: string }> = {
  pending: { label: 'Pending', cls: 'text-caution border-caution/50', glyph: '◷' },
  accepted: { label: 'Accepted', cls: 'text-accent border-accent/60', glyph: '✓' },
  serving: { label: 'Serving', cls: 'text-go border-go/60', glyph: '▶' },
  completed: { label: 'Completed', cls: 'text-ink-2 border-line', glyph: '●' },
  cancelled: { label: 'Cancelled', cls: 'text-ink-3 border-line', glyph: '×' },
  expired: { label: 'Expired', cls: 'text-stop border-stop/50', glyph: '!' },
  en_route: { label: 'En route', cls: 'text-ink-2 border-line', glyph: '→' },
  dispatching: { label: 'Dispatching', cls: 'text-ink-3 border-line', glyph: '…' },
  final_leg: { label: 'Final leg', cls: 'text-ink-2 border-line', glyph: '→' },
}

export function StatusBadge({ status }: { status: RequestStatus | string }) {
  const s = STATUS[status] ?? { label: status, cls: 'text-ink-2 border-line', glyph: '' }
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-px text-[11px] font-medium whitespace-nowrap ${s.cls}`}>
      <span aria-hidden>{s.glyph}</span>
      {s.label}
    </span>
  )
}

export function Stat({ label, value, unit }: { label: string; value: ReactNode; unit?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-ink-3">{label}</div>
      <div className="num truncate text-[13px] text-ink">
        {value}
        {unit && <span className="ml-0.5 text-[11px] text-ink-3">{unit}</span>}
      </div>
    </div>
  )
}

export const fmt = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '–' : v.toFixed(d))

export function clock(t: number): string {
  const s = Math.floor(t)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

/** Distance to the signal against the predicted radius: this is the activation decision. */
export function RadiusMeter({ dist, radius, active, color }: { dist: number | null; radius: number | null; active: boolean; color: string }) {
  if (dist === null || radius === null) return null
  const span = Math.max(dist, radius) * 1.1
  return (
    <div className="mt-1.5">
      <div className="relative h-1.5 rounded-full bg-raised">
        <div className="absolute inset-y-0 left-0 rounded-full opacity-40" style={{ width: `${(radius / span) * 100}%`, background: color }} />
        <div
          className="absolute -top-[3px] h-3 w-[3px] rounded-sm bg-ink transition-[left] duration-300"
          style={{ left: `calc(${(dist / span) * 100}% - 1px)` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-ink-3">
        <span className="num">
          {Math.round(dist)} m to signal
        </span>
        <span className={active ? 'text-ink' : ''}>{active ? 'Inside radius' : 'Outside radius'}</span>
      </div>
    </div>
  )
}
