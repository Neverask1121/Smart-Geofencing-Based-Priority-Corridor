import { ScatterplotLayer } from '@deck.gl/layers'
import type { EmergencyVehicle, IntersectionState, SignalInfo } from '../../../types/simulation'

type RGB = [number, number, number]
const GO: RGB = [53, 194, 123]
const CAUTION: RGB = [240, 180, 41]
const STOP: RGB = [239, 90, 90]
const ACCENT: RGB = [90, 160, 240]

export function linkColor(c: string | undefined): RGB {
  if (c === 'G' || c === 'g') return GO
  if (c === 'y' || c === 'Y' || c === 'u') return CAUTION
  return STOP
}

function headColor(links: number[], state: string | undefined): RGB {
  if (!state) return [90, 100, 112]
  const cs = links.map((i) => state[i])
  if (cs.some((c) => c === 'G' || c === 'g')) return GO
  if (cs.some((c) => c === 'y' || c === 'Y')) return CAUTION
  return STOP
}

interface Head {
  position: [number, number]
  links: number[]
  sig: string
}

const M_PER_DEG = 111320
const HEAD_SPACING_M = 4
const DETAIL_ZOOM = 16

/** One head per approach, or at close zoom one per movement, set side by side across the road. */
function buildHeads(list: SignalInfo[], detail: boolean): Head[] {
  return list.flatMap((s) =>
    s.approaches.flatMap((a) => {
      if (!detail) return [{ position: [a.lon, a.lat] as [number, number], links: a.links, sig: s.id }]
      const groups = new Map<string, number[]>()
      for (const i of a.links) {
        const k = s.links.find((l) => l.index === i)?.turn ?? 's'
        groups.set(k, [...(groups.get(k) ?? []), i])
      }
      const rad = (a.bearing * Math.PI) / 180
      const lonScale = M_PER_DEG * Math.cos((a.lat * Math.PI) / 180)
      return [...groups.values()].map((links, i) => {
        const off = (i - (groups.size - 1) / 2) * HEAD_SPACING_M
        const position: [number, number] = [a.lon + (Math.cos(rad) * off) / lonScale, a.lat - (Math.sin(rad) * off) / M_PER_DEG]
        return { position, links, sig: s.id }
      })
    }),
  )
}

const headCache = new Map<boolean, { list: SignalInfo[]; heads: Head[] }>()
function headsFor(list: SignalInfo[], detail: boolean): Head[] {
  const hit = headCache.get(detail)
  if (hit?.list === list) return hit.heads
  const heads = buildHeads(list, detail)
  headCache.set(detail, { list, heads })
  return heads
}

export function signalLayers(
  list: SignalInfo[],
  state: Record<string, string>,
  inter: Record<string, IntersectionState>,
  evs: EmergencyVehicle[],
  selected: string | null,
  time: number,
  zoom: number,
) {
  const heads = headsFor(list, zoom >= DETAIL_ZOOM)
  const upcoming = new Set(evs.flatMap((e) => e.upcoming_tls))
  const targets = new Set(evs.map((e) => e.next_tls))
  const pulse = 0.5 + 0.5 * Math.sin(time / 220)

  const ring = (s: SignalInfo): [number, number, number, number] => {
    const i = inter[s.id]
    if (i?.active_requests.length) return [...(i.mode === 'serving' ? GO : ACCENT), 255]
    if (i?.pending_requests.length) return [...CAUTION, 150 + pulse * 105]
    if (i && i.mode !== 'normal') return [...ACCENT, 200]
    if (targets.has(s.id)) return [232, 237, 242, 220]
    if (upcoming.has(s.id)) return [232, 237, 242, 120]
    return [150, 165, 180, 70]
  }
  const busy = (s: SignalInfo) => {
    const i = inter[s.id]
    return !!i && (i.active_requests.length > 0 || i.pending_requests.length > 0 || i.mode !== 'normal')
  }

  return [
    new ScatterplotLayer<SignalInfo>({
      id: 'signal-rings',
      data: list,
      getPosition: (s) => [s.lon, s.lat],
      getRadius: (s) => (s.id === selected ? 15 : busy(s) ? 13 : targets.has(s.id) ? 11 : 9),
      radiusUnits: 'pixels',
      filled: true,
      getFillColor: (s) => (s.id === selected ? [57, 135, 229, 70] : [10, 14, 19, 150]),
      stroked: true,
      getLineColor: ring,
      getLineWidth: (s) => (s.id === selected || busy(s) ? 3 : 1.5),
      lineWidthUnits: 'pixels',
      pickable: true,
      updateTriggers: {
        getRadius: [selected, inter, evs],
        getFillColor: selected,
        getLineColor: [inter, evs, pulse],
        getLineWidth: [selected, inter],
      },
    }),
    new ScatterplotLayer<Head>({
      id: 'signal-heads',
      data: heads,
      getPosition: (h) => h.position,
      getRadius: 3.2,
      radiusUnits: 'meters',
      radiusMinPixels: 3,
      radiusMaxPixels: 7,
      getFillColor: (h) => headColor(h.links, state[h.sig]),
      stroked: true,
      getLineColor: [6, 9, 13, 255],
      getLineWidth: 1,
      lineWidthUnits: 'pixels',
      updateTriggers: { getFillColor: state },
    }),
  ]
}
