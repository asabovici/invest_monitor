import { useEffect, useState } from 'react'
import {
  ApiError, fetchStressScenarios, runStress,
  type StressScenarioInfo, type StressTestResult,
} from '../api'
import { colorForType, compact, cssVar, pct, usd } from '../lib'
import { NeedsPortfolio } from '../components/NeedsPortfolio'

/** Worst first. A stress test is read to find what hurts, so the losses
 *  belong at the top rather than the largest positions. */
const byPain = (a: { change_usd: number }, b: { change_usd: number }) =>
  a.change_usd - b.change_usd

export function Stress(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [catalogue, setCatalogue] = useState<StressScenarioInfo[] | null>(null)
  const [scenario, setScenario] = useState<string | null>(null)
  const [result, setResult] = useState<StressTestResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    let live = true
    setCatalogue(null); setResult(null); setScenario(null); setError(null)
    fetchStressScenarios(dataDir)
      .then((d) => live && setCatalogue(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir])

  // A result belongs to one portfolio; switching scope must not leave the
  // previous portfolio's numbers on screen under a new heading.
  useEffect(() => { setResult(null); setScenario(null) }, [portfolio])

  const run = (id: string) => {
    if (!portfolio) return
    setScenario(id); setRunning(true); setError(null)
    runStress(portfolio, id, dataDir)
      .then(setResult)
      .catch((e) => setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
      .finally(() => setRunning(false))
  }

  if (!portfolio) return <NeedsPortfolio what="Stress testing" />

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t run the stress test</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  const down = result ? result.total_change_usd < 0 : false

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Scenario</div>
            <div className="v" style={{ fontSize: 18 }}>
              {scenario ?? 'None selected'}
            </div>
          </div>
          {result && (
            <>
              <div className="stat sm">
                <div className="k">Value after shock</div>
                <div className="v num">{usd(result.new_value)}</div>
              </div>
              <div className="stat sm">
                <div className="k">Change</div>
                <div className={`v num ${down ? 'down' : 'up'}`}>
                  {down ? '' : '+'}{compact(result.total_change_usd)}
                  <span className="sub num" style={{ marginLeft: 8 }}>
                    {/* total_change_pct is already a percent. */}
                    {pct(result.total_change_pct)}
                  </span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="toolbar" style={{ alignItems: 'flex-start' }}>
          <span className="sub">Scenario</span>
          {catalogue === null ? (
            <span className="sub">Loading…</span>
          ) : (
            catalogue.map((s) => (
              <button key={s.scenario_id} className="seg"
                      aria-pressed={scenario === s.scenario_id}
                      disabled={running}
                      onClick={() => run(s.scenario_id)}>
                {s.scenario_id}
              </button>
            ))
          )}
        </div>

        <div className="note">
          Shocks are applied to today’s holdings at once — a scenario is a single
          instantaneous repricing, not a path through time. Sector shocks hit equities by
          their sector; funds are shocked through their look-through profile where one
          exists, and fall back to a blended average where it doesn’t.
        </div>
      </section>

      {running && <div className="card skeleton" style={{ height: 260 }}
                       aria-busy="true" aria-label="Running stress test" />}

      {!running && !result && (
        <div className="card state">
          <h2>Pick a scenario</h2>
          <p>Choose one above to reprice {portfolio} under it.</p>
        </div>
      )}

      {!running && result && (
        <section className="card pad">
          <h2 className="h2">Position impact — worst first</h2>
          <div className="tablescroll">
            <table>
              <thead>
                <tr>
                  <th>Holding</th>
                  <th>Shock source</th>
                  <th className="r">Shock</th>
                  <th className="r">Value</th>
                  <th className="r">Change</th>
                </tr>
              </thead>
              <tbody>
                {[...result.rows].sort(byPain).map((r) => (
                  <tr key={r.ticker}>
                    <td>
                      <div className="tick">
                        <span className="glyph" style={{ background: colorForType(r.asset_type) }}>
                          {r.asset_type[0]}
                        </span>
                        <div>
                          <div style={{ fontWeight: 600 }}>{r.ticker}</div>
                          <div className="sub">{r.asset_type}</div>
                        </div>
                      </div>
                    </td>
                    {/* Shown because a fallback-derived shock is a much weaker
                        claim than a real sector hit, and they look identical
                        once they're both just a percentage. */}
                    <td className="sub">{r.source}</td>
                    <td className="r num" style={{ color: cssVar(r.shock_pct < 0 ? '--neg' : '--pos') }}>
                      {pct(r.shock_pct)}
                    </td>
                    <td className="r num">{usd(r.new_value)}</td>
                    <td className={`r num ${r.change_usd < 0 ? 'down' : 'up'}`}>
                      {r.change_usd < 0 ? '' : '+'}{compact(r.change_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="note" style={{ paddingTop: 12 }}>
            {result.rows.length} positions repriced from a base of {usd(result.base_value)}.
            Holdings with no price or no applicable shock are not listed and are unchanged.
          </div>
        </section>
      )}
    </div>
  )
}
