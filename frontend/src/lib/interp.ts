/**
 * Presentation-only interpolation. Each moving object eases from where it is drawn to
 * the latest position the backend reported, so what is drawn always lies between two real
 * simulated positions and never predicts ahead of them.
 */
export interface Tween {
  x: number
  y: number
  a: number
  fx: number
  fy: number
  fa: number
  tx: number
  ty: number
  ta: number
  t0: number
  dur: number
}

/** Larger jumps than this are shown as a jump, not a slide across buildings. Degrees (~110 m). */
const SNAP_DEG = 0.001

export function newTween(x: number, y: number, a: number, now: number): Tween {
  return { x, y, a, fx: x, fy: y, fa: a, tx: x, ty: y, ta: a, t0: now, dur: 1 }
}

export function retarget(v: Tween, x: number, y: number, a: number, now: number, dur: number): void {
  if (Math.abs(x - v.x) + Math.abs(y - v.y) > SNAP_DEG) {
    v.x = v.fx = v.tx = x
    v.y = v.fy = v.ty = y
    v.a = v.fa = v.ta = a
    v.t0 = now
    return
  }
  v.fx = v.x
  v.fy = v.y
  v.fa = v.a
  v.tx = x
  v.ty = y
  v.ta = v.a + (((((a - v.a) % 360) + 540) % 360) - 180) // shortest way round
  v.t0 = now
  v.dur = dur
}

export function advance(v: Tween, now: number): void {
  const f = Math.min((now - v.t0) / v.dur, 1)
  v.x = v.fx + (v.tx - v.fx) * f
  v.y = v.fy + (v.ty - v.fy) * f
  v.a = v.fa + (v.ta - v.fa) * f
}
