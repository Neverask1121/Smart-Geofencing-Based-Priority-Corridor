import { memo, useState } from 'react'
import { useStore } from '../../state/store'
import type { HistoryPoint, Metrics } from '../../types/simulation'
import { clock, fmt } from '../common'

type Key = keyof HistoryPoint

function Spark({ data, field, unit }: { data: HistoryPoint[]; field: Key; unit: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const pts = data.map((d) => d[field] as number | null).filter((v): v is number => v !== null)
  if (pts.length < 2) return <div className="h-7" />
  const W = 120
  const H = 28
  const series = data.filter((d) => d[field] !== null)
  const lo = Math.min(...pts)
  const hi = Math.max(...pts)
  const x = (i: number) => (i / (pts.length - 1)) * W
  const y = (v: number) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6)
  const line = pts.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  return (
    <div
      className="relative h-7"
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        setHover(Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1)))
      }}
      onMouseLeave={() => setHover(null)}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full" role="img" aria-label={`Trend, latest ${pts[pts.length - 1]} ${unit}`}>
        <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke="var(--color-ink-3)" strokeWidth="1" vectorEffect="non-scaling-stroke" />}
      </svg>
      {hover !== null && (
        <div className="num pointer-events-none absolute bottom-full left-1/2 z-20 mb-1 -translate-x-1/2 rounded border border-line bg-bg px-1.5 py-0.5 text-[11px] whitespace-nowrap">
          {clock(series[hover].t)} · {pts[hover]} {unit}
        </div>
      )}
    </div>
  )
}

function Tile({ label, value, unit, sub, spark }: { label: string; value: string; unit?: string; sub?: string; spark?: React.ReactNode }) {
  return (
    <div className="min-w-[100px] flex-1 border-r border-line px-2.5 py-2 last:border-0">
      <div className="truncate text-[11px] text-ink-3" title={label}>{label}</div>
      <div className="num mt-0.5 text-[19px] leading-6 font-medium">
        {value}
        {unit && <span className="ml-1 text-[11px] font-normal text-ink-3">{unit}</span>}
      </div>
      {spark ?? <div className="truncate pt-1 text-[11px] leading-5 text-ink-3" title={sub}>{sub}</div>}
    </div>
  )
}

function tiles(m: Metrics | null, h: HistoryPoint[]) {
  return (
    <>
      <Tile label="EV travel time" value={fmt(m?.avg_ev_travel_time)} unit="s" sub={`${m?.evs_completed ?? 0} finished`} />
      <Tile label="Civilian delay" value={fmt(m?.avg_civilian_delay, 1)} unit="s" spark={<Spark data={h} field="avg_civilian_delay" unit="s" />} />
      <Tile label="Queue / signal" value={fmt(m?.avg_queue, 1)} unit="veh" spark={<Spark data={h} field="avg_queue" unit="veh" />} />
      <Tile label="Active EVs" value={fmt(m?.active_evs)} sub={`${m?.vehicles ?? 0} on road`} />
      <Tile label="Priority requests" value={fmt(m?.requests_total)} sub={`${m?.conflicts_detected ?? 0} conflicts`} />
      <Tile label="Successful" value={fmt(m?.requests_successful)} sub={`${m?.requests_expired ?? 0} expired`} />
      <Tile label="Predicted radius" value={fmt(m?.avg_radius_now ?? m?.avg_radius_run)} unit="m" spark={<Spark data={h} field="avg_radius_now" unit="m" />} />
      <Tile label="Throughput" value={fmt(m?.throughput_per_min)} unit="veh/min" spark={<Spark data={h} field="throughput_per_min" unit="veh/min" />} />
      <Tile label="Safety violations" value={fmt(m?.safety_violations)} sub={`${m?.predictions ?? 0} predictions`} />
    </>
  )
}

export const MetricsPanel = memo(function MetricsPanel() {
  const m = useStore((s) => s.metrics)
  const h = useStore((s) => s.history)
  return <div className="scroll-thin flex overflow-x-auto">{tiles(m, h)}</div>
})
