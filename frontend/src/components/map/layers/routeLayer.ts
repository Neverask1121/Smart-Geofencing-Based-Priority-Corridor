import { PathLayer } from '@deck.gl/layers'
import { splitRoute } from '../../../lib/geo'
import type { EmergencyVehicle, EvRoute } from '../../../types/simulation'
import { EV_COLORS } from '../icons'

interface Seg {
  path: [number, number][]
  color: [number, number, number, number]
  width: number
}

/** Remaining route in the EV's colour, completed route dimmed. */
export function routeLayers(evs: EmergencyVehicle[], routes: Record<string, EvRoute>, selected: string | null) {
  const left: Seg[] = []
  const done: Seg[] = []
  for (const e of evs) {
    const r = routes[e.id]
    if (!r) continue
    const c = EV_COLORS[e.color % EV_COLORS.length]
    const s = splitRoute(r.coords, r.cum, e.route_progress_m)
    const dim = selected !== null && selected !== e.id
    if (s.left.length > 1) left.push({ path: s.left, color: [...c, dim ? 90 : 235], width: selected === e.id ? 6 : 4 })
    if (s.done.length > 1) done.push({ path: s.done, color: [120, 134, 148, dim ? 50 : 120], width: 2.5 })
  }
  const base = { widthUnits: 'pixels' as const, capRounded: true, jointRounded: true }
  return [
    new PathLayer<Seg>({ id: 'route-done', data: done, getPath: (d) => d.path, getColor: (d) => d.color, getWidth: (d) => d.width, ...base }),
    new PathLayer<Seg>({ id: 'route-left', data: left, getPath: (d) => d.path, getColor: (d) => d.color, getWidth: (d) => d.width, ...base }),
  ]
}
