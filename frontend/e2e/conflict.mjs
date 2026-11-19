// Waits for a live conflict, then captures the junction in operator and demo views.
// Usage: node e2e/conflict.mjs [outDir] [policy] [speed]
import { chromium } from 'playwright-core'
const [out = '.', policy = 'xgboost', speed = '2'] = process.argv.slice(2)
const BASE = process.env.BASE ?? 'http://127.0.0.1:8000'
const get = (p) => fetch(BASE + p).then((r) => r.json())
const post = (p, b) => fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
const browser = await chromium.launch({
  executablePath: process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
await page.goto(BASE)
await page.waitForTimeout(2500)
await post('/api/v1/scenarios/select', { scenario: 'perpendicular', policy, autostart: true })
await post('/api/v1/simulation/speed', { speed: Number(speed) })
let hit = null
for (let i = 0; i < 240 && !hit; i++) {
  const reqs = await get('/api/v1/priority-requests')
  hit = reqs.find((r) => r.conflicts_with.length > 0 && r.status === 'serving')
  if (!hit) await page.waitForTimeout(250)
}
if (!hit) { console.log('no conflict seen'); await browser.close(); process.exit(1) }
console.log('conflict at', hit.tls_name, hit.id, hit.conflicts_with)
await post('/api/v1/simulation/pause', {})
await page.selectOption('select[aria-label="Select intersection"]', hit.tls)
await page.waitForTimeout(2500)
await page.screenshot({ path: `${out}/conflict-operator.png` })
await page.keyboard.press('d')
await page.waitForTimeout(2000)
await page.screenshot({ path: `${out}/conflict-demo.png` })
await post('/api/v1/simulation/resume', {})
await browser.close()
