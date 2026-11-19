// End-to-end check in headless Chrome against a running backend.
// Usage: node e2e/smoke.mjs [outDir] [scenario] [policy] [seconds] [speed]
import { chromium } from 'playwright-core'

const [out = '.', scenario = 'perpendicular', policy = 'xgboost', secs = '40', speed = '4'] = process.argv.slice(2)
const BASE = process.env.BASE ?? 'http://127.0.0.1:8000'
const post = (p, b) =>
  fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined }).then(async (r) => [r.status, await r.text()])

const browser = await chromium.launch({
  executablePath: process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
const logs = []
page.on('console', (m) => ['error', 'warning'].includes(m.type()) && logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`))
await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(3000)
await page.screenshot({ path: `${out}/01-idle.png` })
console.log('select', await post('/api/v1/scenarios/select', { scenario, policy, autostart: true }))
await post('/api/v1/simulation/speed', { speed: Number(speed) })
await page.waitForTimeout(Number(secs) * 500)
await page.screenshot({ path: `${out}/02-mid.png` })
await page.waitForTimeout(Number(secs) * 500)
await page.screenshot({ path: `${out}/03-late.png` })
const m = await (await fetch(BASE + '/api/v1/metrics')).json()
console.log(JSON.stringify(m.current))
console.log(logs.slice(0, 12).join('\n') || 'no console errors')
await browser.close()
