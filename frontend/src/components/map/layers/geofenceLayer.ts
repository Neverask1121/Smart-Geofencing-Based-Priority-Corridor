import { PathLayer, PolygonLayer, TextLayer } from '@deck.gl/layers'
import { geofenceRing } from '../../../lib/geo'
import { live } from '../../../state/live'
import type { EmergencyVehicle, SignalInfo } from '../../../types/simulation'
import { EV_COLORS } from '../icons'

interface Fence {
  id: string
  ring: [number, number][]
  color: [number, number, number]
  active: boolean
  selected: boolean
}

interface Link {
  path: [number, number][]
  mid: [number, number]
  text: string
  color: [number, number, number]
  active: boolean
}

/** Geofences use the backend's predicted radius in metres, centred on the drawn vehicle. */
export function geofenceLayers(evs: EmergencyVehicle[], signals: Record<string, SignalInfo>, selected: string | null) {
  const fences: Fence[] = []
  const links: Link[] = []
  for (const e of evs) {
    const v = live.evs.get(e.id)
    if (!v || e.radius === null) continue
    const color = EV_COLORS[e.color % EV_COLORS.length]
    fences.push({
      id: e.id,
      ring: geofenceRing(v.x, v.y, e.radius),
      color,
      active: e.in_geofence,
      selected: e.id === selected,
    })
    const sig = e.next_tls ? signals[e.next_tls] : null
    if (sig && e.dist_to_tls !== null) {
      links.push({
        path: [
          [v.x, v.y],
          [sig.lon, sig.lat],
        ],
        mid: [(v.x + sig.lon) / 2, (v.y + sig.lat) / 2],
        text: `${Math.round(e.dist_to_tls)} m ${e.in_geofence ? '<=' : '>'} R ${Math.round(e.radius)} m`,
        color,
        active: e.in_geofence,
      })
    }
  }
  const anySelected = selected !== null
  return [
    new PolygonLayer<Fence>({
      id: 'geofences',
      data: fences,
      getPolygon: (f) => f.ring,
      getFillColor: (f) => [...f.color, f.active ? 46 : anySelected && !f.selected ? 10 : 24],
      getLineColor: (f) => [...f.color, anySelected && !f.selected ? 110 : 235],
      getLineWidth: (f) => (f.selected ? 3 : f.active ? 2.5 : 1.5),
      lineWidthUnits: 'pixels',
      stroked: true,
      filled: true,
      updateTriggers: { getPolygon: live.tick, getFillColor: [selected, evs], getLineColor: selected, getLineWidth: [selected, evs] },
    }),
    new PathLayer<Link>({
      id: 'geofence-links',
      data: links,
      getPath: (l) => l.path,
      getColor: (l) => [...l.color, l.active ? 240 : 130],
      getWidth: 1.5,
      widthUnits: 'pixels',
      updateTriggers: { getPath: live.tick },
    }),
    new TextLayer<Link>({
      id: 'geofence-link-labels',
      data: links,
      getPosition: (l) => l.mid,
      getText: (l) => l.text,
      getSize: 11,
      getColor: [232, 237, 242, 255],
      fontFamily: 'IBM Plex Mono, monospace',
      background: true,
      getBackgroundColor: [10, 14, 19, 200],
      backgroundPadding: [4, 2],
      updateTriggers: { getPosition: live.tick, getText: evs },
    }),
  ]
}
