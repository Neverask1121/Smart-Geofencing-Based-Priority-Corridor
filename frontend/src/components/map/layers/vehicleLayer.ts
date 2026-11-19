import { IconLayer } from '@deck.gl/layers'
import { live, type LiveVehicle } from '../../../state/live'
import type { RGBA } from '../icons'

const TYPES = ['car', 'motorcycle', 'bus', 'truck'] as const
const SIZE_M = [7, 3.6, 15, 12]
const MIN_PX = [11, 8, 15, 13]
const MOVING: RGBA = [205, 222, 240, 255]
const SLOW: RGBA = [240, 180, 41, 245]
const HALTED: RGBA = [239, 90, 90, 250]
const SELECTED: RGBA = [255, 255, 255, 255]

/** Colour encodes state of flow, so queues at signals stand out from the whole map. */
const flowColor = (v: LiveVehicle): RGBA => (v.speed < 0.5 ? HALTED : v.speed < 3 ? SLOW : MOVING)

export function vehicleLayers(atlas: ReturnType<typeof import('../icons').buildAtlas>, selected: number | null, zoom: number) {
  const t = live.tick
  // Markers shrink when zoomed out so that dense traffic stays separate vehicles rather than a band.
  const scale = Math.min(1, Math.max(0.55, (zoom - 12) / 3))
  return TYPES.map(
    (name, i) =>
      new IconLayer<LiveVehicle>({
        id: `vehicles-${name}`,
        data: live.byType[i],
        iconAtlas: atlas.atlas,
        iconMapping: atlas.mapping,
        getIcon: () => name,
        getPosition: (v) => [v.x, v.y],
        getAngle: (v) => -v.a,
        getColor: (v) => (v.key === selected ? SELECTED : flowColor(v)),
        getSize: SIZE_M[i],
        sizeUnits: 'meters',
        sizeMinPixels: MIN_PX[i] * scale,
        sizeMaxPixels: 44,
        billboard: false,
        pickable: true,
        updateTriggers: { getPosition: t, getAngle: t, getColor: [t, selected] },
      }),
  )
}
