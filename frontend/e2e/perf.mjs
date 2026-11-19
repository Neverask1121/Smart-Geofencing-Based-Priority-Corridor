// Measures frame rate and WebSocket traffic under load, and checks the phone layout.
// Usage: node e2e/perf.mjs [outDir]
// Headless Chrome here uses a software GPU, so the frame rate is a lower bound.
import { chromium } from 'playwright-core'
const [out = '.'] = process.argv.slice(2)
const BASE = process.env.BASE ?? 'http://127.0.0.1:8000'
const post = (p, b) => fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b ?? {}) })
const get = (p) => fetch(BASE + p).then((r) => r.json())
const browser = await chromium.launch({
  executablePath: process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
const logs = []
page.on('pageerror', (e) => logs.push(e.message))
const sizes = []
page.on('websocket', (ws) => ws.on('framereceived', (f) => sizes.push(f.payload.length)))
await page.goto(BASE)
await page.waitForTimeout(2500)
await post('/api/v1/scenarios/select', { scenario: 'five', policy: 'xgboost', traffic: 'high', autostart: true })
await post('/api/v1/simulation/speed', { speed: 1 })
for (let i = 0; i < 200; i++) {
  if ((await get('/api/v1/simulation/status')).status === 'running') break
  await page.waitForTimeout(500)
}
await page.waitForTimeout(25000)
sizes.length = 0
const fps = await page.evaluate(() => new Promise((res) => {
  let n = 0
  const t0 = performance.now()
  const f = () => { n++; performance.now() - t0 < 10000 ? requestAnimationFrame(f) : res(n / 10) }
  requestAnimationFrame(f)
}))
const small = sizes.filter((s) => s < 200000)
const m = (await get('/api/v1/metrics')).current
const st = await get('/api/v1/simulation/status')
console.log(JSON.stringify({ vehicles: m.vehicles, active_evs: m.active_evs, fps, ws_msgs_per_s: sizes.length / 10, avg_frame_kb: small.reduce((a, b) => a + b, 0) / small.length / 1024, achieved_speed: st.achieved_speed, avg_radius_now: m.avg_radius_now, predictions: m.predictions, violations: m.safety_violations }))
const evs = await get('/api/v1/emergency-vehicles')
console.log('radii', evs.map((e) => `${e.id}:${e.radius}`).join(' '))
await page.screenshot({ path: `${out}/five-high.png` })

const phone = await browser.newPage({ viewport: { width: 390, height: 844 } })
await phone.goto(BASE)
await phone.waitForTimeout(4000)
const over = await phone.evaluate(() => document.documentElement.scrollWidth - innerWidth)
console.log('phone horizontal overflow px', over)
await phone.screenshot({ path: `${out}/phone.png` })
console.log(logs.length ? logs.slice(0, 5).join('\n') : 'no page errors')
await browser.close()
