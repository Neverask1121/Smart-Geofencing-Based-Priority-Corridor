import { MapboxOverlay } from '@deck.gl/mapbox'
import { LngLatBounds, Map as MapLibre, NavigationControl, ScaleControl, setWorkerUrl, type IControl, type StyleSpecification } from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import { api } from '../../services/api'
import { live, type LiveEv, type LiveVehicle } from '../../state/live'
import { useStore } from '../../state/store'
import type { SignalInfo } from '../../types/simulation'
import { arrowImage, buildAtlas } from './icons'
import { emergencyLayers } from './layers/emergencyLayer'
import { geofenceLayers } from './layers/geofenceLayer'
import { routeLayers } from './layers/routeLayer'
import { signalLayers } from './layers/signalLayer'
import { vehicleLayers } from './layers/vehicleLayer'

setWorkerUrl('/maplibre/maplibre-gl-worker.mjs')

// OpenFreeMap: no key or request limits, OSM-based vector tiles. See README for the policy check.
const BASEMAP = 'https://tiles.openfreemap.org/styles/dark'
const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#0d1218' } }],
}

const ROAD_COLOR = ['match', ['get', 'class'], 'primary', '#6d8196', 'secondary', '#5c6f83', 'tertiary', '#4d5e70', '#39465a']
const ROAD_WIDTH = [
  'interpolate', ['exponential', 1.6], ['zoom'],
  12, ['match', ['get', 'class'], 'primary', 1.4, 'secondary', 1.1, 'tertiary', 0.8, 0.3],
  16, ['*', ['match', ['get', 'class'], 'primary', 2.6, 'secondary', 2.4, 'tertiary', 2.2, 1.7], ['max', 1, ['get', 'lanes']]],
  19, ['*', ['match', ['get', 'class'], 'primary', 10, 'secondary', 10, 'tertiary', 9, 8], ['max', 1, ['get', 'lanes']]],
]

function addRoads(map: MapLibre) {
  if (map.getSource('roads')) return
  map.addSource('roads', { type: 'geojson', data: api.roadsUrl })
  // Below the basemap's text, so street names stay readable on top of our network.
  const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id
  map.addLayer({
    id: 'roads',
    type: 'line',
    source: 'roads',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    paint: { 'line-color': ROAD_COLOR as any, 'line-width': ROAD_WIDTH as any, 'line-opacity': 0.9 },
  }, firstLabel)
  if (!map.hasImage('arrow')) map.addImage('arrow', arrowImage())
  map.addLayer({
    id: 'road-arrows',
    type: 'symbol',
    source: 'roads',
    minzoom: 16.3,
    layout: { 'symbol-placement': 'line', 'symbol-spacing': 110, 'icon-image': 'arrow', 'icon-size': 0.6, 'icon-allow-overlap': true },
  })
}

export function CityMap() {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibre | null>(null)
  const focus = useStore((s) => s.focusRequest)

  useEffect(() => {
    if (!focus || !mapRef.current) return
    mapRef.current.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom, duration: 900 })
  }, [focus])

  useEffect(() => {
    const map = new MapLibre({
      container: container.current!,
      style: BASEMAP,
      center: [72.5613, 23.0265],
      zoom: 13.4,
      minZoom: 11.5,
      maxZoom: 19.5,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    })
    mapRef.current = map
    Object.assign(window, { __its: { map, live, useStore } }) // read by the browser tests in e2e/
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
    // If the tile server cannot be reached, fall back to a plain background so the
    // road network, which comes from our own backend, still renders.
    let styled = false
    const fallback = setTimeout(() => {
      if (!styled) {
        useStore.getState().setToast('Basemap unavailable: showing the SUMO road network only.')
        map.setStyle(OFFLINE_STYLE)
      }
    }, 6000)
    map.on('style.load', () => {
      styled = true
      clearTimeout(fallback)
      addRoads(map)
      syncRoads(map, useStore.getState().layers.roads)
    })
    map.on('mousemove', (e) => {
      if (!map.getLayer('roads')) return
      const f = map.queryRenderedFeatures(
        [[e.point.x - 3, e.point.y - 3], [e.point.x + 3, e.point.y + 3]],
        { layers: ['roads'] },
      )[0]
      const tip = document.getElementById('road-tip')
      if (!tip) return
      if (f?.properties) {
        const p = f.properties
        tip.textContent = `${p.name || 'Unnamed road'} · ${p.class} · ${p.lanes} lane${p.lanes > 1 ? 's' : ''} · ${Math.round(p.speed * 3.6)} km/h limit`
        tip.style.opacity = '1'
      } else tip.style.opacity = '0'
    })

    const atlas = buildAtlas()
    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      getCursor: ({ isHovering }) => (isHovering ? 'pointer' : 'grab'),
      onClick: (info) => {
        const s = useStore.getState()
        const id = info.layer?.id ?? ''
        if (id === 'signal-rings') s.selectTls((info.object as SignalInfo).id)
        else if (id === 'ev-icons') s.selectEv((info.object as LiveEv).id, false)
        else if (id.startsWith('vehicles-')) s.selectVehicle((info.object as LiveVehicle).key)
        else {
          s.selectVehicle(null)
          s.selectEv(null, false)
        }
      },
    })
    map.addControl(overlay as unknown as IControl)

    // Keep every EV route in view as vehicles join a run, until the user takes over the camera.
    let fittedRun = -1
    let fittedRoutes = 0
    let userMoved = false
    map.on('dragstart', () => (userMoved = true))
    map.on('wheel', () => (userMoved = true))
    const fitRun = () => {
      const s = useStore.getState()
      const run = s.sim?.run_id ?? -1
      if (run !== fittedRun) {
        fittedRun = run
        fittedRoutes = 0
        userMoved = false
      }
      const routes = Object.values(s.routes)
      if (userMoved || routes.length <= fittedRoutes || s.sim?.status !== 'running') return
      fittedRoutes = routes.length
      const coords = routes.flatMap((r) => r.coords)
      const b = new LngLatBounds(coords[0], coords[0])
      coords.forEach((c) => b.extend(c))
      map.fitBounds(b, { padding: 90, maxZoom: 15.5, duration: 1200 })
    }

    let raf = 0
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame)
      if (document.hidden) return
      live.advance(now)
      const s = useStore.getState()
      const L = s.layers
      overlay.setProps({
        layers: [
          ...(L.routes ? routeLayers(s.evs, s.routes, s.selectedEv) : []),
          ...(L.geofences ? geofenceLayers(s.evs, s.signalById, s.selectedEv) : []),
          ...(L.vehicles ? vehicleLayers(atlas, s.selectedVehicle, map.getZoom()) : []),
          ...(L.signals && s.network
            ? signalLayers(s.network.signals, s.signals, s.intersections, s.evs, s.selectedTls, now, map.getZoom())
            : []),
          ...emergencyLayers(atlas, s.evs, s.selectedEv, L.labels, now),
        ],
      })
      fitRun()
    }
    raf = requestAnimationFrame(frame)

    const unsub = useStore.subscribe((s, p) => {
      if (s.layers.roads !== p.layers.roads) syncRoads(map, s.layers.roads)
      if (s.demoMode !== p.demoMode) requestAnimationFrame(() => map.resize())
    })
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(container.current!)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(fallback)
      ro.disconnect()
      unsub()
      map.remove()
    }
  }, [])

  // MapLibre's stylesheet forces position:relative on its container, so the outer div does the sizing.
  return (
    <div className="absolute inset-0">
      <div ref={container} className="h-full w-full" />
    </div>
  )
}

function syncRoads(map: MapLibre, on: boolean) {
  for (const id of ['roads', 'road-arrows']) {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none')
  }
}
