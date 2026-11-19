// Does a browser slow the simulation? Samples achieved speed with one page attached.
// Usage: node e2e/backpressure.mjs [seconds] [speed]    env GPU=1 uses the real GPU.
import { chromium } from 'playwright-core'
const [secs = '30', speed = '16'] = process.argv.slice(2)
const BASE = 'http://127.0.0.1:8000'
const args = process.env.GPU
  ? ['--use-angle=d3d11', '--ignore-gpu-blocklist', '--enable-gpu-rasterization']
  : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args })
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
let frames = 0, snaps = 0, bytes = 0, snapBytes = 0
page.on('websocket', (ws) => ws.on('framereceived', (f) => {
  const s = String(f.payload)
  if (s.startsWith('{"type":"snapshot"')) { snaps++; snapBytes += s.length } else { frames++; bytes += s.length }
}))
await page.goto(BASE)
await page.waitForTimeout(4000)
await fetch(BASE + '/api/v1/simulation/speed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ speed: Number(speed) }) })
const gl = await page.evaluate(() => {
  const g = document.createElement('canvas').getContext('webgl2')
  const e = g.getExtension('WEBGL_debug_renderer_info')
  return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown'
})
console.log('renderer', gl)
for (let i = 0; i < Number(secs) / 5; i++) {
  frames = snaps = bytes = snapBytes = 0
  const fps = await page.evaluate(() => new Promise((res) => {
    let n = 0
    const t0 = performance.now()
    const f = () => { n++; performance.now() - t0 < 5000 ? requestAnimationFrame(f) : res(n / 5) }
    requestAnimationFrame(f)
  }))
  const s = await (await fetch(BASE + '/api/v1/simulation/status')).json()
  console.log(`t=${s.t} achieved=${s.achieved_speed} fps=${fps.toFixed(1)} frames/s=${(frames / 5).toFixed(1)} snapshots/5s=${snaps} frameKB=${frames ? (bytes / frames / 1024).toFixed(0) : '-'} snapKB=${snaps ? (snapBytes / snaps / 1024).toFixed(0) : '-'}`)
}
await browser.close()
