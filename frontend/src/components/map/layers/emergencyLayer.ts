import { IconLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { live, type LiveEv } from '../../../state/live'
import type { EmergencyVehicle } from '../../../types/simulation'
import { EV_COLORS } from '../icons'

export function emergencyLayers(
  atlas: ReturnType<typeof import('../icons').buildAtlas>,
  evs: EmergencyVehicle[],
  selected: string | null,
  labels: boolean,
  time: number,
) {
  const t = live.tick
  const meta = new Map(evs.map((e) => [e.id, e]))
  const data = [...live.evs.values()].filter((v) => meta.has(v.id))
  const pulse = 0.5 + 0.5 * Math.sin(time / 260)
  const color = (v: LiveEv) => EV_COLORS[meta.get(v.id)!.color % EV_COLORS.length]
  return [
    new ScatterplotLayer<LiveEv>({
      id: 'ev-beacon',
      data,
      getPosition: (v) => [v.x, v.y],
      getRadius: (v) => (v.id === selected ? 22 : 17) + pulse * 5,
      radiusUnits: 'pixels',
      getFillColor: (v) => [...color(v), 60 + pulse * 50] as [number, number, number, number],
      stroked: true,
      getLineColor: (v) => [...color(v), 240] as [number, number, number, number],
      getLineWidth: (v) => (v.id === selected ? 2.5 : 1.5),
      lineWidthUnits: 'pixels',
      updateTriggers: { getPosition: t, getRadius: [t, selected], getFillColor: t, getLineWidth: selected },
    }),
    new IconLayer<LiveEv>({
      id: 'ev-icons',
      data,
      iconAtlas: atlas.atlas,
      iconMapping: atlas.mapping,
      getIcon: (v) => meta.get(v.id)!.type,
      getPosition: (v) => [v.x, v.y],
      getAngle: (v) => -v.a,
      getSize: 14,
      sizeUnits: 'meters',
      sizeMinPixels: 26,
      sizeMaxPixels: 60,
      billboard: false,
      pickable: true,
      updateTriggers: { getPosition: t, getAngle: t, getIcon: evs },
    }),
    ...(labels
      ? [
          new TextLayer<LiveEv>({
            id: 'ev-labels',
            data,
            getPosition: (v) => [v.x, v.y],
            getText: (v) => {
              const e = meta.get(v.id)!
              return `${v.id}  ${e.radius === null ? '--' : Math.round(e.radius)} m`
            },
            getColor: [240, 244, 248, 255],
            getSize: 12,
            getPixelOffset: [0, -32],
            fontFamily: 'IBM Plex Mono, monospace',
            fontWeight: 600,
            background: true,
            getBackgroundColor: [10, 14, 19, 215],
            backgroundPadding: [5, 2],
            getBorderColor: (v) => [...color(v), 255] as [number, number, number, number],
            getBorderWidth: 1,
            updateTriggers: { getPosition: t, getText: evs, getBorderColor: evs },
          }),
        ]
      : []),
  ]
}
