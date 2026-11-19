/** Top-down vehicle icons drawn once to a canvas atlas. All point north; deck.gl rotates them. */
const CELL = 96

export type RGBA = [number, number, number, number]

// Fixed EV identity colours, validated with the dataviz palette checker on the panel surface.
export const EV_COLORS: [number, number, number][] = [
  [57, 135, 229],
  [217, 89, 38],
  [25, 158, 112],
  [201, 133, 0],
  [213, 81, 129],
  [144, 133, 233],
]
export const EV_HEX = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9']

function rr(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  c.beginPath()
  c.roundRect(x, y, w, h, r)
  c.fill()
}

type Draw = (c: CanvasRenderingContext2D) => void

const glass = (c: CanvasRenderingContext2D, y: number, w: number, h: number) => {
  c.fillStyle = 'rgba(12,20,30,.75)'
  rr(c, 48 - w / 2, y, w, h, 3)
}

const drawings: Record<string, { draw: Draw; mask: boolean }> = {
  car: {
    mask: true,
    draw: (c) => {
      c.fillStyle = '#fff'
      rr(c, 28, 6, 40, 84, 13)
      c.globalCompositeOperation = 'destination-out'
      rr(c, 34, 26, 28, 13, 4)
      rr(c, 34, 64, 28, 9, 3)
      c.globalCompositeOperation = 'source-over'
    },
  },
  motorcycle: {
    mask: true,
    draw: (c) => {
      c.fillStyle = '#fff'
      rr(c, 40, 6, 16, 84, 8)
      rr(c, 26, 26, 44, 7, 3)
    },
  },
  bus: {
    mask: true,
    draw: (c) => {
      c.fillStyle = '#fff'
      rr(c, 30, 2, 36, 92, 6)
      c.globalCompositeOperation = 'destination-out'
      rr(c, 35, 7, 26, 7, 2)
      c.globalCompositeOperation = 'source-over'
    },
  },
  truck: {
    mask: true,
    draw: (c) => {
      c.fillStyle = '#fff'
      rr(c, 32, 3, 32, 22, 6)
      rr(c, 28, 29, 40, 64, 3)
    },
  },
  ambulance: {
    mask: false,
    draw: (c) => {
      c.fillStyle = '#f6f8fa'
      rr(c, 25, 4, 46, 88, 10)
      glass(c, 13, 34, 11)
      c.fillStyle = '#e02b2b'
      rr(c, 43, 38, 10, 38, 1)
      rr(c, 29, 52, 38, 10, 1)
    },
  },
  fire_engine: {
    mask: false,
    draw: (c) => {
      c.fillStyle = '#e0301e'
      rr(c, 23, 2, 50, 92, 7)
      glass(c, 9, 38, 11)
      c.fillStyle = '#ffd166'
      rr(c, 29, 30, 38, 5, 1)
      rr(c, 29, 50, 38, 5, 1)
      rr(c, 29, 70, 38, 5, 1)
    },
  },
  police: {
    mask: false,
    draw: (c) => {
      c.fillStyle = '#16356b'
      rr(c, 26, 5, 44, 86, 12)
      c.fillStyle = '#f6f8fa'
      rr(c, 26, 38, 44, 22, 1)
      glass(c, 20, 32, 11)
      c.fillStyle = '#e02b2b'
      rr(c, 30, 46, 17, 7, 2)
      c.fillStyle = '#3f8cff'
      rr(c, 49, 46, 17, 7, 2)
    },
  },
}

export function buildAtlas() {
  const names = Object.keys(drawings)
  const canvas = document.createElement('canvas')
  canvas.width = CELL * names.length
  canvas.height = CELL
  const ctx = canvas.getContext('2d')!
  const mapping: Record<string, { x: number; y: number; width: number; height: number; mask: boolean; anchorY: number }> = {}
  names.forEach((name, i) => {
    ctx.save()
    ctx.translate(i * CELL, 0)
    drawings[name].draw(ctx)
    ctx.restore()
    mapping[name] = { x: i * CELL, y: 0, width: CELL, height: CELL, mask: drawings[name].mask, anchorY: CELL / 2 }
  })
  return { atlas: canvas.toDataURL('image/png'), mapping }
}

export function arrowImage(): ImageData {
  const c = document.createElement('canvas')
  c.width = c.height = 24
  const x = c.getContext('2d')!
  x.strokeStyle = 'rgba(190,205,220,.75)'
  x.lineWidth = 2.5
  x.lineCap = 'round'
  x.lineJoin = 'round'
  x.beginPath()
  x.moveTo(8, 6)
  x.lineTo(16, 12)
  x.lineTo(8, 18)
  x.stroke()
  return x.getImageData(0, 0, 24, 24)
}
