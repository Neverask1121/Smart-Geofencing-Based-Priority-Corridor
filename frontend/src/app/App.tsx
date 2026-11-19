import { useEffect } from 'react'
import { ConflictResolutionPanel } from '../components/coordination/ConflictResolutionPanel'
import { DecisionLog, PriorityRequestPanel } from '../components/coordination/PriorityRequestPanel'
import { ScenarioSelector } from '../components/controls/SimulationControls'
import { EmergencyVehiclePanel } from '../components/dashboard/EmergencyVehiclePanel'
import { IntersectionPanel } from '../components/dashboard/IntersectionPanel'
import { ModelPanel } from '../components/dashboard/ModelPanel'
import { MetricsPanel } from '../components/dashboard/MetricsPanel'
import { DemoOverlay } from '../components/layout/DemoMode'
import { TopBar } from '../components/layout/TopBar'
import { CityMap } from '../components/map/CityMap'
import { LayerControl, RoadTip, VehicleInspector } from '../components/map/MapOverlays'
import { useSimulationSocket } from '../hooks/useSimulationSocket'
import { api } from '../services/api'
import { useStore } from '../state/store'

const TABS = [
  ['intersection', 'Intersection'],
  ['coordination', 'Coordination'],
  ['log', 'Decisions'],
  ['model', 'Model'],
] as const

function RightPanel() {
  const tab = useStore((s) => s.rightTab)
  const setTab = useStore((s) => s.setRightTab)
  const open = useStore((s) => s.metrics?.requests_open ?? 0)
  return (
    <aside className="flex w-[330px] shrink-0 flex-col border-l border-line bg-panel max-[1100px]:order-3 max-[1100px]:w-full max-[1100px]:border-l-0">
      <div role="tablist" className="flex border-b border-line">
        {TABS.map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`flex-1 cursor-pointer border-b-2 py-2.5 text-[12.5px] font-medium ${tab === k ? 'border-accent text-ink' : 'border-transparent text-ink-3 hover:text-ink-2'}`}
          >
            {label}
            {k === 'coordination' && open > 0 && <span className="num ml-1 text-caution">{open}</span>}
          </button>
        ))}
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {tab === 'intersection' && <IntersectionPanel />}
        {tab === 'coordination' && <PriorityRequestPanel />}
        {tab === 'log' && <DecisionLog />}
        {tab === 'model' && <ModelPanel />}
      </div>
    </aside>
  )
}

function Toast() {
  const toast = useStore((s) => s.toast)
  const clear = useStore((s) => s.setToast)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => clear(null), 6000)
    return () => clearTimeout(t)
  }, [toast, clear])
  if (!toast) return null
  return (
    <div role="status" className="glass absolute top-3 left-1/2 z-30 max-w-md -translate-x-1/2 px-3 py-2 text-[12.5px]">
      {toast}
    </div>
  )
}

function SimMessage() {
  const sim = useStore((s) => s.sim)
  const connection = useStore((s) => s.connection)
  if (connection === 'offline') return <Banner title="Backend unreachable" body="Reconnecting. Is the FastAPI server running?" />
  if (sim?.status === 'error') return <Banner title="Simulation stopped" body={sim.message ?? ''} />
  if (sim?.status === 'warming') return <Banner title={`Warming up traffic ${Math.round(sim.warmup_progress * 100)}%`} body="SUMO is filling the road network before the scenario starts." />
  if (!sim || sim.status === 'idle') return <Banner title="Ready" body="Choose a scenario and run it." />
  return null
}

function Banner({ title, body }: { title: string; body: string }) {
  return (
    <div className="glass absolute top-1/2 left-1/2 z-20 -translate-x-1/2 -translate-y-1/2 px-5 py-3 text-center">
      <div className="text-[14px] font-semibold">{title}</div>
      <div className="mt-0.5 text-[12px] text-ink-3">{body}</div>
    </div>
  )
}

export function App() {
  useSimulationSocket()
  const demo = useStore((s) => s.demoMode)

  useEffect(() => {
    const fail = (e: Error) => useStore.getState().setToast(e.message)
    api.signals().then((network) => {
      useStore.setState({ network, signalById: Object.fromEntries(network.signals.map((s) => [s.id, s])) })
    }).catch(fail)
    api.scenarios().then((scenarios) => useStore.setState({ scenarios })).catch(fail)
    api.model().then((model) => useStore.setState({ model })).catch(fail)
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).matches('input, select, textarea')) return
      const s = useStore.getState()
      if (e.key === 'd' || e.key === 'D') s.setDemo(!s.demoMode)
      if (e.key === 'Escape') s.setDemo(false)
    }
    addEventListener('keydown', key)
    return () => removeEventListener('keydown', key)
  }, [])

  return (
    <div className={`${demo ? 'demo-mode ' : ''}flex h-full flex-col overflow-hidden max-[1100px]:h-auto max-[1100px]:overflow-visible`}>
      {!demo && <TopBar />}
      <div className="flex min-h-0 flex-1 max-[1100px]:flex-col">
        {!demo && (
          <aside className="flex w-[292px] shrink-0 flex-col border-r border-line bg-panel max-[1100px]:order-2 max-[1100px]:w-full max-[1100px]:border-r-0">
            <EmergencyVehiclePanel />
            <ScenarioSelector />
          </aside>
        )}
        <main className="flex min-w-0 flex-1 flex-col max-[1100px]:order-1">
          <div className="relative min-h-0 flex-1 max-[1100px]:h-[62vh] max-[1100px]:flex-none">
            <CityMap />
            <Toast />
            <SimMessage />
            {demo ? (
              <DemoOverlay />
            ) : (
              <>
                <div className="absolute top-3 left-3 z-10 flex flex-col items-start gap-2">
                  <LayerControl />
                  <VehicleInspector />
                </div>
                <div className="absolute top-3 right-3 z-10"><ConflictResolutionPanel /></div>
              </>
            )}
            <div className="absolute bottom-8 left-1/2 z-10 -translate-x-1/2"><RoadTip /></div>
          </div>
          {!demo && (
            <div className="shrink-0 border-t border-line bg-panel">
              <MetricsPanel />
            </div>
          )}
        </main>
        {!demo && <RightPanel />}
      </div>
    </div>
  )
}
