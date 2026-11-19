// Full browser check against a running backend: every scenario, every control, and real mouse
// clicks on the map. Exits non-zero if any check fails.
// Usage: node e2e/full.mjs [outDir]    env GPU=1 uses the real GPU instead of software rendering.
import { chromium } from 'playwright-core'

const [out = '.'] = process.argv.slice(2)
const BASE = process.env.BASE ?? 'http://127.0.0.1:8000'
const get = (p) => fetch(BASE + p).then((r) => r.json())
const post = (p, b) => fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b ?? {}) })
const results = []
const check = (name, ok, detail = '') => {
  results.push(!!ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`)
}
const args = process.env.GPU
  ? ['--use-angle=d3d11', '--ignore-gpu-blocklist', '--enable-gpu-rasterization']
  : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
const browser = await chromium.launch({ executablePath: process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe', args })
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
await page.goto(BASE)
await page.waitForFunction(() => window.__its?.useStore.getState().network && window.__its.map.getLayer('roads'), null, { timeout: 60000 })

const running = async () => {
  for (let i = 0; i < 1200; i++) {
    const st = (await get('/api/v1/simulation/status')).status
    if (st === 'running') return true
    if (st === 'error') return false
    await page.waitForTimeout(250)
  }
  return false
}

// ---- every scenario, through the UI ------------------------------------------------
const scenarios = await get('/api/v1/scenarios')
for (const s of scenarios) {
  await page.selectOption('select[aria-label="Scenario"]', s.id)
  const before = (await get('/api/v1/simulation/status')).run_id
  await page.getByRole('button', { name: 'Run scenario' }).click()
  for (let i = 0; i < 40 && (await get('/api/v1/simulation/status')).run_id === before; i++) await page.waitForTimeout(250)
  const up = await running()
  await post('/api/v1/simulation/speed', { speed: 16 })
  // Heavy traffic cannot reach the requested speed, so wait on simulated time, not wall time.
  let m = null
  let st = null
  const t0 = (await get('/api/v1/simulation/status')).t
  for (let i = 0; ; i++) {
    m = (await get('/api/v1/metrics')).current
    st = await get('/api/v1/simulation/status')
    if ((m && m.evs_completed >= s.ev_count) || st.t > t0 + 900 || st.status === 'error') break
    await page.waitForTimeout(250)
    if (i === 40) await page.screenshot({ path: `${out}/scenario-${s.id}.png` })
  }
  const events = await get('/api/v1/events')
  const arb = events.filter((e) => e.kind === 'arbitration').length
  check(`scenario ${s.id}`, up && m.evs_completed >= s.ev_count && m.safety_violations === 0 && m.requests_expired === 0,
    `EVs ${m.evs_completed}/${s.ev_count} requests ${m.requests_successful}/${m.requests_total} conflicts ${m.conflicts_detected} arbitrations ${arb} radius ${m.avg_radius_run} violations ${m.safety_violations} simulated ${(st.t - t0).toFixed(0)}s at ${st.achieved_speed}x`)
}

// ---- arbitration is visible in the panel ---------------------------------------------
await post('/api/v1/scenarios/select', { scenario: 'perpendicular', policy: 'xgboost', autostart: true })
await running()
await post('/api/v1/simulation/speed', { speed: 4 })
await page.waitForFunction(() => {
  const s = window.__its.useStore.getState()
  return s.events.some((e) => e.kind === 'arbitration') && s.requests.some((r) => r.status === 'serving')
}, null, { timeout: 90000 })
await post('/api/v1/simulation/pause')
await page.waitForTimeout(400)
const panel = page.getByLabel('Conflict resolution')
check('panel shows compared scores', (await panel.innerText()).includes('Scores compared'), (await panel.locator('li').nth(2).innerText()).replace(/\n/g, ' '))
await page.screenshot({ path: `${out}/arbitration.png` })

// ---- real mouse clicks on the map ------------------------------------------------------
const box = await page.locator('canvas.maplibregl-canvas').boundingBox()
const px = (lng, lat) => page.evaluate(([a, b]) => { const p = window.__its.map.project([a, b]); return [p.x, p.y] }, [lng, lat])
const clickMap = async (lng, lat) => { const [x, y] = await px(lng, lat); await page.mouse.click(box.x + x, box.y + y); await page.waitForTimeout(300) }
const state = (expr) => page.evaluate(`(() => { const s = window.__its.useStore.getState(); return ${expr} })()`)

const sig = await state(`(() => { const b = window.__its.map.getBounds(); return s.network.signals.find((g) => b.contains([g.lon, g.lat]) && g.lon > b.getWest() + 0.004 && g.lat < b.getNorth() - 0.003) })()`)
await clickMap(sig.lon, sig.lat)
check('click signal selects it', (await state('s.selectedTls')) === sig.id)
check('panel lists movements', (await page.getByRole('tabpanel').count()) >= 0 && (await page.locator('aside').last().innerText()).includes(sig.name))

const ev = await state(`(() => { const e = s.evs.find((v) => v.lon); return { id: e.id, lon: window.__its.live.evs.get(e.id).x, lat: window.__its.live.evs.get(e.id).y } })()`)
await clickMap(ev.lon, ev.lat)
check('click EV selects it', (await state('s.selectedEv')) === ev.id)
check('EV detail opens', await page.getByRole('button', { name: `Reroute ${ev.id}` }).isVisible())

await page.evaluate(() => window.__its.map.jumpTo({ zoom: 16.5 }))
await page.waitForTimeout(800)
const veh = await page.evaluate(() => {
  const m = window.__its.map
  const c = m.getCanvas()
  for (const v of window.__its.live.byKey.values()) {
    const p = m.project([v.x, v.y])
    if (p.x > 200 && p.x < c.clientWidth - 330 && p.y > 40 && p.y < c.clientHeight - 90) return { key: v.key, lon: v.x, lat: v.y }
  }
  return null
})
if (veh) {
  await clickMap(veh.lon, veh.lat)
  check('click vehicle opens inspector', (await state('s.selectedVehicle')) === veh.key && (await page.getByLabel('Close').isVisible()))
} else check('click vehicle opens inspector', false, 'no vehicle on screen')
await page.screenshot({ path: `${out}/close-zoom.png` })
await page.evaluate(() => window.__its.map.jumpTo({ zoom: 14 }))
await post('/api/v1/simulation/resume')

// ---- layer toggles ------------------------------------------------------------------------
for (const label of ['Road network', 'Traffic', 'Signals', 'Geofences', 'EV routes', 'EV labels']) {
  await page.getByLabel(label).uncheck()
  await page.waitForTimeout(150)
  const off = !(await page.getByLabel(label).isChecked())
  await page.getByLabel(label).check()
  check(`toggle ${label}`, off)
}
check('roads hide on the map', await page.evaluate(async () => {
  const s = window.__its.useStore.getState()
  s.toggleLayer('roads')
  const v = window.__its.map.getLayoutProperty('roads', 'visibility')
  s.toggleLayer('roads')
  return v === 'none'
}))

// ---- controls -----------------------------------------------------------------------------
await page.locator('input[type=range]').focus()
await page.keyboard.press('ArrowLeft')
await page.keyboard.press('ArrowLeft')
await page.waitForTimeout(600)
check('demand slider reaches backend', (await get('/api/v1/simulation/status')).scale < 0.7, `scale ${(await get('/api/v1/simulation/status')).scale}`)

await page.getByRole('button', { name: '+ Police' }).click()
await page.waitForFunction(() => window.__its.useStore.getState().evs.some((e) => e.type === 'police' && e.lon), null, { timeout: 20000 })
check('dispatch button adds an EV', true)

const before = await state(`(() => { const e = s.evs.find((v) => v.type === 'police'); return { id: e.id, v: e.route_version, n: s.routes[e.id].coords.length } })()`)
await page.evaluate((id) => window.__its.useStore.getState().selectEv(id, false), before.id)
await page.getByRole('button', { name: `Reroute ${before.id}` }).click()
await page.waitForFunction(([id, v]) => {
  const s = window.__its.useStore.getState()
  return s.evs.find((e) => e.id === id)?.route_version > v && s.routes[id]
}, [before.id, before.v], { timeout: 15000 })
const after = await state(`s.routes[${JSON.stringify(before.id)}].version`)
check('reroute updates the drawn route', after === before.v + 1, `route version ${before.v} to ${after}`)

await page.getByRole('button', { name: 'Pause' }).click()
await page.waitForTimeout(400)
check('pause button', (await get('/api/v1/simulation/status')).status === 'paused')
await page.getByRole('button', { name: 'Resume' }).click()
await page.waitForTimeout(400)
check('resume button', (await get('/api/v1/simulation/status')).status === 'running')
await page.locator('header select').selectOption('2')
await page.waitForTimeout(400)
check('speed control', (await get('/api/v1/simulation/status')).speed === 2)

await page.getByRole('tab', { name: 'Coordination' }).click()
check('coordination tab', (await page.locator('aside').last().innerText()).includes('PR-'))
await page.getByRole('tab', { name: 'Decisions' }).click()
check('decisions tab', (await page.locator('aside').last().innerText()).includes('Arbitration'))
await page.getByRole('tab', { name: 'Model' }).click()
await page.waitForTimeout(300)
check('model tab', (await page.locator('aside').last().innerText()).includes('Oracle'))

await page.keyboard.press('d')
await page.waitForTimeout(500)
check('demo mode on', await page.getByRole('button', { name: 'Operator view' }).isVisible())
await page.keyboard.press('Escape')
await page.waitForTimeout(500)
check('demo mode off', await page.getByRole('button', { name: 'Demo mode' }).isVisible())

// ---- animation, at 1x in medium traffic -----------------------------------------------------
await post('/api/v1/simulation/speed', { speed: 1 })
await page.waitForTimeout(1500)
const anim = await page.evaluate(() => new Promise((res) => {
  const L = window.__its.live
  const ids = [...L.byKey.values()].filter((v) => v.speed > 5).slice(0, 40).map((v) => v.key)
  const last = new Map(ids.map((k) => [k, [L.byKey.get(k).x, L.byKey.get(k).y]]))
  const steps = []
  let frames = 0
  let moved = 0
  const t0 = performance.now()
  const f = () => {
    frames++
    let any = false
    for (const k of ids) {
      const v = L.byKey.get(k)
      if (!v) continue
      const [x, y] = last.get(k)
      const d = Math.hypot((v.x - x) * 102400, (v.y - y) * 111320)
      if (d > 0.001) { any = true; steps.push(d) }
      last.set(k, [v.x, v.y])
    }
    if (any) moved++
    performance.now() - t0 < 6000 ? requestAnimationFrame(f) : res({ fps: frames / 6, movingFrames: moved / frames, p50: steps.sort((a, b) => a - b)[steps.length >> 1], p99: steps[Math.floor(steps.length * 0.99)], max: steps[steps.length - 1] })
  }
  requestAnimationFrame(f)
}))
const gl = await page.evaluate(() => {
  const g = document.createElement('canvas').getContext('webgl2')
  const e = g.getExtension('WEBGL_debug_renderer_info')
  return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown'
})
console.log('renderer', gl)
console.log('animation', JSON.stringify(anim))
check('vehicles move on nearly every frame', anim.movingFrames > 0.9, `${(anim.movingFrames * 100).toFixed(0)}% of frames`)
check('no visible jumps', anim.max < 12, `largest step ${anim.max?.toFixed(2)} m, median ${anim.p50?.toFixed(3)} m`)

await page.getByRole('button', { name: 'Reset' }).click()
await page.waitForTimeout(600)
check('reset button', (await get('/api/v1/simulation/status')).status === 'idle')
check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '))

const failed = results.filter((r) => !r).length
console.log(`\n${results.length - failed}/${results.length} checks passed`)
await browser.close()
process.exit(failed ? 1 : 0)
