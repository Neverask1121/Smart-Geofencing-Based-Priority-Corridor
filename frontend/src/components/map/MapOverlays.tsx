import { useEffect, useState } from 'react'
import { live } from '../../state/live'
import { useStore, type LayerKey } from '../../state/store'

const LAYERS: [LayerKey, string][] = [
  ['roads', 'Road network'],
  ['vehicles', 'Traffic'],
  ['signals', 'Signals'],
  ['geofences', 'Geofences'],
  ['routes', 'EV routes'],
  ['labels', 'EV labels'],
]

const FLOW: [string, string][] = [
  ['#b0c4d8', 'Moving'],
  ['#f0b429', 'Under 3 m/s'],
  ['#ef5a5a', 'Stopped'],
]

export function LayerControl() {
  const layers = useStore((s) => s.layers)
  const toggle = useStore((s) => s.toggleLayer)
  return (
    <div className="glass w-[138px] p-2">
      <div className="eyebrow mb-1">Layers</div>
      {LAYERS.map(([k, label]) => (
        <label key={k} className="flex cursor-pointer items-center gap-1.5 py-[1px] text-[12px] text-ink-2">
          <input type="checkbox" checked={layers[k]} onChange={() => toggle(k)} className="accent-[var(--color-accent)]" />
          {label}
        </label>
      ))}
      <div className="eyebrow mt-2 mb-1">Traffic flow</div>
      {FLOW.map(([c, label]) => (
        <div key={label} className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: c }} aria-hidden />
          {label}
        </div>
      ))}
    </div>
  )
}

const TYPE_NAMES = ['Car', 'Motorcycle', 'Bus', 'Truck']

export function VehicleInspector() {
  const key = useStore((s) => s.selectedVehicle)
  const select = useStore((s) => s.selectVehicle)
  const [, tick] = useState(0)
  useEffect(() => {
    if (key === null) return
    const i = setInterval(() => tick((n) => n + 1), 500)
    return () => clearInterval(i)
  }, [key])
  if (key === null) return null
  const v = live.byKey.get(key)
  if (!v) return null
  return (
    <div className="glass w-[190px] p-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] font-semibold">{TYPE_NAMES[v.type]} #{key}</span>
        <button className="text-ink-3 hover:text-ink" onClick={() => select(null)} aria-label="Close">×</button>
      </div>
      <div className="num mt-1 text-[12px] text-ink-2">{(v.speed * 3.6).toFixed(0)} km/h</div>
      <div className="num text-[11px] text-ink-3">{v.ty.toFixed(5)}, {v.tx.toFixed(5)}</div>
    </div>
  )
}

export function RoadTip() {
  return <div id="road-tip" className="glass pointer-events-none px-2 py-1 text-[11.5px] text-ink-2 opacity-0 transition-opacity" />
}
