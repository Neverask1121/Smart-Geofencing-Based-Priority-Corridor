import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { copyFileSync, mkdirSync } from 'node:fs'
import { defineConfig } from 'vitest/config'

const backend = 'http://127.0.0.1:8000'

// MapLibre 6 ships its worker as ES modules that a bundler cannot rewrite. Serve them
// unbundled from public/, and point MapLibre there with setWorkerUrl (see CityMap.tsx).
function maplibreWorker() {
  return {
    name: 'maplibre-worker',
    buildStart() {
      mkdirSync('public/maplibre', { recursive: true })
      for (const f of ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']) {
        copyFileSync(`node_modules/maplibre-gl/dist/${f}`, `public/maplibre/${f}`)
      }
    },
  }
}

export default defineConfig({
  plugins: [maplibreWorker(), react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/health': backend,
      '/ws': { target: backend, ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 2500 },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
