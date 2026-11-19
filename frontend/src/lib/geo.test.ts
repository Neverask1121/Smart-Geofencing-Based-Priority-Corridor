import { describe, expect, it } from 'vitest'
import { distanceM, geofenceRing, splitRoute } from './geo'
import { advance, newTween, retarget } from './interp'

describe('geofenceRing', () => {
  it.each([80, 150, 350, 480])('every vertex is %d m from the vehicle', (r) => {
    const c: [number, number] = [72.5613, 23.0327]
    for (const p of geofenceRing(c[0], c[1], r)) {
      expect(Math.abs(distanceM(c, p) - r)).toBeLessThan(r * 0.002)
    }
  })
})

describe('splitRoute', () => {
  const coords: [number, number][] = [[0, 0], [1, 0], [2, 0]]
  const cum = [0, 100, 200]
  it('splits inside a segment', () => {
    const { done, left } = splitRoute(coords, cum, 150)
    expect(done[done.length - 1]).toEqual([1.5, 0])
    expect(left[0]).toEqual([1.5, 0])
    expect(left[left.length - 1]).toEqual([2, 0])
  })
  it('handles both ends', () => {
    expect(splitRoute(coords, cum, 0).done).toEqual([])
    expect(splitRoute(coords, cum, 999).left).toEqual([])
  })
})

describe('interpolation', () => {
  it('stays between the previous and latest simulated positions', () => {
    const v = newTween(10, 20, 0, 0)
    retarget(v, 10.0002, 20, 0, 0, 500)
    for (const t of [0, 100, 250, 499, 500, 900]) {
      advance(v, t)
      expect(v.x).toBeGreaterThanOrEqual(10)
      expect(v.x).toBeLessThanOrEqual(10.0002)
    }
    expect(v.x).toBe(10.0002)
  })
  it('snaps on a teleport instead of sliding', () => {
    const v = newTween(10, 20, 0, 0)
    retarget(v, 10.5, 20, 0, 0, 500)
    expect(v.x).toBe(10.5)
  })
  it('turns the short way round', () => {
    const v = newTween(0, 0, 350, 0)
    retarget(v, 0, 0, 10, 0, 100)
    advance(v, 100)
    expect(v.a).toBe(370)
  })
})
