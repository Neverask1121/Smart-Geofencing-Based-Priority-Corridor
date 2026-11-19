// Keeps a page open across a backend restart and reports what the operator sees.
// Prints READY once connected; the caller then stops and restarts the backend.
import { chromium } from 'playwright-core'
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 800 } })
await page.goto('http://127.0.0.1:8000')
const state = () => page.evaluate(() => {
  const t = document.querySelector('header')?.innerText ?? ''
  return /Offline/.test(t) ? 'offline' : /Connecting/.test(t) ? 'connecting' : /Live/.test(t) ? 'live' : 'loading'
})
const until = async (want, secs) => {
  for (let i = 0; i < secs * 2; i++) {
    if ((await state()) === want) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}
console.log('live at start', await until('live', 40))
console.log('READY')
console.log('saw offline', await until('offline', 60))
console.log('banner', await page.getByText('Backend unreachable').count())
console.log('recovered', await until('live', 90))
await browser.close()
