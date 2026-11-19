import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { useStore } from '../../state/store'

const run = (p: Promise<unknown>) =>
  p.catch((e: Error) => useStore.getState().setToast(e.message))

export function TransportControls() {
  const status = useStore((s) => s.sim?.status ?? 'idle')
  const [busy, setBusy] = useState(false)
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    await run(fn())
    setBusy(false)
  }
  const warming = status === 'warming'
  return (
    <div className="flex items-center gap-1.5">
      <button className="btn btn-primary" disabled={busy || warming} onClick={() => act(api.start)}>
        {status === 'running' || status === 'paused' ? 'Restart' : 'Start'}
      </button>
      {status === 'paused' ? (
        <button className="btn" onClick={() => act(api.resume)}>Resume</button>
      ) : (
        <button className="btn" disabled={status !== 'running'} onClick={() => act(api.pause)}>Pause</button>
      )}
      <button className="btn" disabled={busy || status === 'idle' || warming} onClick={() => act(api.reset)}>Reset</button>
    </div>
  )
}

const SPEEDS = [0.5, 1, 2, 4, 8, 16]

export function SpeedControl() {
  const speed = useStore((s) => s.sim?.speed ?? 1)
  const achieved = useStore((s) => (s.sim?.status === 'running' ? s.sim.achieved_speed : 0))
  const limited = achieved > 0 && achieved < speed * 0.8
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-ink-3">
      {limited ? <span className="num" title="The simulation cannot run this fast with the current traffic">actual {achieved.toFixed(1)}×</span> : 'Speed'}
      <select className="field !w-[68px]" value={speed} onChange={(e) => run(api.speed(Number(e.target.value)))}>
        {SPEEDS.map((v) => (
          <option key={v} value={v}>{v}×</option>
        ))}
      </select>
    </label>
  )
}

export function ScenarioSelector() {
  const scenarios = useStore((s) => s.scenarios)
  const sim = useStore((s) => s.sim)
  const model = useStore((s) => s.model)
  const [scenario, setScenario] = useState('perpendicular')
  const [traffic, setTraffic] = useState('')
  const [policy, setPolicy] = useState('xgboost')
  const [demand, setDemand] = useState(0.7)
  const running = sim?.status === 'running' || sim?.status === 'paused'
  const warming = sim?.status === 'warming'
  const chosen = scenarios.find((s) => s.id === scenario)

  useEffect(() => {
    if (model && !model.loaded) setPolicy('fixed_300')
  }, [model])
  useEffect(() => {
    if (sim?.scale) setDemand(sim.scale)
  }, [sim?.scale])
  // The backend owns what is running; the form follows it whenever a run starts.
  useEffect(() => {
    if (sim?.scenario) setScenario(sim.scenario)
    if (sim?.policy && ['xgboost', 'none', 'fixed_150', 'fixed_300', 'fixed_450'].includes(sim.policy)) setPolicy(sim.policy)
  }, [sim?.run_id, sim?.scenario, sim?.policy])

  return (
    <section className="space-y-2 border-t border-line p-3">
      <h2 className="eyebrow">Run setup</h2>
      <select className="field" value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">
        {scenarios.map((s) => (
          <option key={s.id} value={s.id}>{s.name}</option>
        ))}
      </select>
      {chosen && <p className="text-[11.5px] text-ink-3">{chosen.description}</p>}
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[11px] text-ink-3">
          Traffic
          <select className="field mt-0.5" value={traffic} onChange={(e) => setTraffic(e.target.value)}>
            <option value="">Scenario default</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
        <label className="text-[11px] text-ink-3">
          Radius policy
          <select className="field mt-0.5" value={policy} onChange={(e) => setPolicy(e.target.value)}>
            <option value="xgboost" disabled={model !== null && !model.loaded}>XGBoost model</option>
            <option value="fixed_150">Fixed 150 m</option>
            <option value="fixed_300">Fixed 300 m</option>
            <option value="fixed_450">Fixed 450 m</option>
            <option value="none">No priority</option>
          </select>
        </label>
      </div>
      <button className="btn btn-primary w-full justify-center" disabled={warming} onClick={() => run(api.select(scenario, traffic || null, policy))}>
        Run scenario
      </button>
      <label className="block text-[11px] text-ink-3">
        <span className="flex justify-between">Live demand <span className="num text-ink-2">{demand.toFixed(2)}×</span></span>
        <input
          type="range" min={0.1} max={1.2} step={0.05} value={demand} disabled={!running} className="w-full accent-[var(--color-accent)]"
          onChange={(e) => setDemand(Number(e.target.value))}
          onMouseUp={() => run(api.demand(demand))}
          onKeyUp={() => run(api.demand(demand))}
        />
      </label>
      <div className="grid grid-cols-3 gap-1.5">
        {(['ambulance', 'fire_engine', 'police'] as const).map((t) => (
          <button key={t} className="btn justify-center !px-1 text-[11.5px]" disabled={!running} onClick={() => run(api.dispatch(t))}>
            + {t === 'fire_engine' ? 'Fire' : t === 'ambulance' ? 'Amb.' : 'Police'}
          </button>
        ))}
      </div>
    </section>
  )
}
