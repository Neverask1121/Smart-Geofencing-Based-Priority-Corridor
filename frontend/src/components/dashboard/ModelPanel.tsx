import { useEffect } from 'react'
import { api } from '../../services/api'
import { useStore } from '../../state/store'
import { Stat, fmt } from '../common'

interface Card {
  train_crossings: number
  test_crossings: number
  cost_curve_r2_test: number
  best_fixed_radius_m: number
  decision_cost: { no_priority: number; best_fixed: number; model: number; oracle: number }
  model_minus_fixed_ci95: [number, number]
  feature_importance_gain: [string, number][]
  last_latency_ms: number
  predictions: number
}

/** The trained model's record, as served by /api/v1/model. */
export function ModelPanel() {
  const model = useStore((s) => s.model)
  const live = useStore((s) => s.metrics?.predictions ?? 0)

  useEffect(() => {
    api.model().then((m) => useStore.setState({ model: m })).catch(() => undefined)
  }, [])

  if (!model) return <p className="p-3 text-[12px] text-ink-3">Loading…</p>
  if (!model.loaded) return <p className="p-3 text-[12px] text-stop">Model not loaded: {model.error}</p>
  const c = model as unknown as Card
  const rows: [string, number][] = [
    ['No priority', c.decision_cost.no_priority],
    [`Best fixed (${c.best_fixed_radius_m} m)`, c.decision_cost.best_fixed],
    ['XGBoost', c.decision_cost.model],
    ['Oracle', c.decision_cost.oracle],
  ]
  return (
    <div className="space-y-3 p-3">
      <div>
        <h3 className="text-[14px] font-semibold">XGBoost radius model</h3>
        <p className="mt-0.5 text-[12px] text-ink-3">
          Predicts the decision cost of each candidate radius from live traffic. The radius is the soft minimum of that curve.
        </p>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="This run" value={live} unit="calls" />
        <Stat label="Latency" value={fmt(c.last_latency_ms, 1)} unit="ms" />
        <Stat label="Curve R²" value={fmt(c.cost_curve_r2_test, 2)} />
      </div>
      <div>
        <div className="eyebrow mb-1">Held-out decision cost (lower is better)</div>
        <table className="w-full text-[12px]">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="border-b border-line/60 last:border-0">
                <td className="py-1 text-ink-2">{k}</td>
                <td className="num py-1 text-right">{v.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[11.5px] text-ink-3">
          {c.test_crossings} held-out crossings, {c.train_crossings} for training. Model minus fixed, 95% CI{' '}
          <span className="num">{c.model_minus_fixed_ci95[0]} to {c.model_minus_fixed_ci95[1]}</span>.
        </p>
      </div>
      <div>
        <div className="eyebrow mb-1">Most influential inputs</div>
        <ol className="space-y-0.5">
          {c.feature_importance_gain.slice(0, 6).map(([k, v]) => (
            <li key={k} className="flex justify-between text-[12px]">
              <span className="text-ink-2">{k.replaceAll('_', ' ')}</span>
              <span className="num text-ink-3">{(v * 100).toFixed(0)}%</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
