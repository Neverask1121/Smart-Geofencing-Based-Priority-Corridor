/**
 * High-rate vehicle state, kept outside React. The map's animation loop reads this
 * directly, so vehicle movement never re-renders any component.
 */
import { advance, newTween, retarget, type Tween } from '../lib/interp'
import type { EmergencyVehicle, VehicleBlock } from '../types/simulation'

export interface LiveVehicle extends Tween {
  key: number
  type: number
  speed: number
}

export interface LiveEv extends Tween {
  id: string
}

class LiveState {
  byKey = new Map<number, LiveVehicle>()
  byType: LiveVehicle[][] = [[], [], [], []]
  evs = new Map<string, LiveEv>()
  frameInterval = 500
  private lastFrame = 0
  tick = 0

  reset(): void {
    this.byKey.clear()
    this.byType = [[], [], [], []]
    this.evs.clear()
    this.lastFrame = 0
  }

  private noteFrame(now: number): void {
    if (this.lastFrame) {
      const dt = Math.min(Math.max(now - this.lastFrame, 50), 1500)
      this.frameInterval += 0.2 * (dt - this.frameInterval)
    }
    this.lastFrame = now
  }

  apply(block: VehicleBlock, now: number, snap = false): void {
    this.noteFrame(now)
    const dirty = new Set<number>()
    for (const k of block.del) {
      const v = this.byKey.get(k)
      if (v) {
        this.byKey.delete(k)
        dirty.add(v.type)
      }
    }
    const pending = new Map<number, number>(block.add)
    const p = block.pos
    for (let i = 0; i < p.length; i += 5) {
      const key = p[i]
      let v = this.byKey.get(key)
      if (!v) {
        const type = pending.get(key)
        if (type === undefined) continue
        v = { ...newTween(p[i + 1], p[i + 2], p[i + 3], now), key, type, speed: p[i + 4] }
        this.byKey.set(key, v)
        dirty.add(type)
      } else {
        if (snap) Object.assign(v, newTween(p[i + 1], p[i + 2], p[i + 3], now))
        else retarget(v, p[i + 1], p[i + 2], p[i + 3], now, this.frameInterval)
        v.speed = p[i + 4]
      }
    }
    // New array identities tell deck.gl that membership changed; position-only frames reuse them.
    for (const t of dirty) this.byType[t] = [...this.byKey.values()].filter((v) => v.type === t)
  }

  applyEvs(evs: EmergencyVehicle[], now: number): void {
    const seen = new Set<string>()
    for (const e of evs) {
      if (e.lon === 0 && e.lat === 0) continue // scheduled, not yet on the road
      seen.add(e.id)
      const v = this.evs.get(e.id)
      if (v) retarget(v, e.lon, e.lat, e.angle, now, this.frameInterval)
      else this.evs.set(e.id, { ...newTween(e.lon, e.lat, e.angle, now), id: e.id })
    }
    for (const id of this.evs.keys()) if (!seen.has(id)) this.evs.delete(id)
  }

  advance(now: number): void {
    this.tick++
    for (const v of this.byKey.values()) advance(v, now)
    for (const v of this.evs.values()) advance(v, now)
  }
}

export const live = new LiveState()
