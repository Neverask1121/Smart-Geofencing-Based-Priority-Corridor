import circle from '@turf/circle'

type Pos = [number, number]

/** Geodesic circle around a point, with a true radius in metres. */
export function geofenceRing(lon: number, lat: number, radiusM: number, steps = 96): Pos[] {
  const poly = circle([lon, lat], radiusM / 1000, { steps, units: 'kilometers' })
  return poly.geometry.coordinates[0] as Pos[]
}

/** Haversine distance in metres. */
export function distanceM(a: Pos, b: Pos): number {
  const R = 6371008.8
  const rad = Math.PI / 180
  const dLat = (b[1] - a[1]) * rad
  const dLon = (b[0] - a[0]) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

/** Split a route at `progress` metres into the completed and remaining paths. */
export function splitRoute(coords: Pos[], cum: number[], progress: number): { done: Pos[]; left: Pos[] } {
  if (coords.length < 2) return { done: [], left: coords }
  if (progress <= 0) return { done: [], left: coords }
  if (progress >= cum[cum.length - 1]) return { done: coords, left: [] }
  let lo = 0
  let hi = cum.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (cum[mid] <= progress) lo = mid
    else hi = mid
  }
  const span = cum[hi] - cum[lo]
  const f = span > 0 ? (progress - cum[lo]) / span : 0
  const p: Pos = [coords[lo][0] + (coords[hi][0] - coords[lo][0]) * f, coords[lo][1] + (coords[hi][1] - coords[lo][1]) * f]
  return { done: [...coords.slice(0, hi), p], left: [p, ...coords.slice(hi)] }
}
