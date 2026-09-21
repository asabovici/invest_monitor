import { useEffect, useState } from 'react'
import { ApiError, fetchRisk, type RiskReport } from '../api'
import { cssVar, pct, usd } from '../lib'
import { FanChart } from '../components/FanChart'

const R = 62, STROKE = 15, SIZE = 156

/** Ring gauge: one number, so a full donut with a legend would be noise. */
function SuccessRing({ value }: { value: number }) {
  const c = SIZE / 2
  const circumference = 2 * Math.PI * R
  const tone = value >= 0.85 ? '--pos' : value >= 0.6 ? '--c1' : '--neg'
  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
         aria-label={`Chance of success ${(value * 100).toFixed(1)} percent`}>
      <circle cx={c} cy={c} r={R} fill="none" stroke={cssVar('--grid')} strokeWidth={STROKE} />
      <circle cx={c} cy={c} r={R} fill="none" stroke={cssVar(tone)} strokeWidth={STROKE}
              strokeLinecap="round" strokeDasharray={`${circumference * value} ${circumference}`}
              transform={`rotate(-90 ${c} ${c})`} />
      <text x={c} y={c - 1} textAnchor="middle" fontSize="27" fontWeight="700"
            fill={cssVar('--ink')} style={{ fontVariantNumeric: 'tabular-nums' }}>
        {(value * 100).toFixed(1)}%
      </text>
      <text x={c} y={c + 20} textAnchor="middle" fontSize="11" fill={cssVar('--ink-3')}>
        chance of success
      </text>
    </svg>
  )
}

function verdict(p: number) {
  if (p >= 0.9) return { word: 'strong', tone: '--pos', mark: '✓' }
  if (p >= 0.75) return { word: 'good', tone: '--pos', mark: '✓' }
  if (p >= 0.5) return { word: 'uncertain', tone: '--c1', mark: '!' }
  return { word: 'unlikely', tone: '--neg', mark: '!' }
}

const PERCENTILES = ['p5', 'p25', 'p50', 'p75', 'p95'] as const
const PERCENTILE_LABEL: Record<string, string> = {
  p5: 'Poor (5th)', p25: 'Below par (25th)', p50: 'Median',
  p75: 'Good (75th)', p95: 'Excellent (95th)',
}

export function Projection(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<RiskReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [years, setYears] = useState(20)
  const [goal, setGoal] = useState(3_000_000)
  const [monthly, setMonthly] = useState(2000)

  useEffect(() => {
    let live = true
    setRep(null); setError(null)
    fetchRisk({ dataDir, years, goal, monthly, portfolio })
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio, years, goal, monthly])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load the projection</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  const p = rep?.projection
  const v = p?.probability_of_success != null ? verdict(p.probability_of_success) : null

  return (
    <div className="stack">
      <section className="card hero">
        {!rep || !p ? (
          <div className="skeleton" style={{ height: 150 }} />
        ) : (
          <div className="statrow" style={{ alignItems: 'center' }}>
            {p.probability_of_success != null && <SuccessRing value={p.probability_of_success} />}
            <div style={{ flex: 1, minWidth: 240 }}>
              {v && p.goal_amount != null && (
                <div className="verdict">
                  <span className="mark" style={{ background: cssVar(v.tone) }}>{v.mark}</span>
                  <p style={{ margin: 0 }}>
                    This chance of success looks <b style={{ color: cssVar(v.tone) }}>{v.word}</b>.
                    Your portfolio finished at or above <b>{usd(p.goal_amount)}</b> in{' '}
                    <b>{(p.probability_of_success! * 100).toFixed(0)}%</b> of{' '}
                    <b>{p.num_simulations.toLocaleString('en-US')}</b> simulated runs over{' '}
                    <b>{p.years} years</b>.
                  </p>
                </div>
              )}
              <div className="controls">
                <div className="field">
                  <label htmlFor="r-goal">Goal</label>
                  <input id="r-goal" type="number" min={0} step={100000} value={goal}
                         onChange={(e) => setGoal(Math.max(0, +e.target.value))} />
                </div>
                <div className="field">
                  <label htmlFor="r-years">Years</label>
                  <input id="r-years" type="number" min={1} max={60} value={years}
                         onChange={(e) => setYears(Math.min(60, Math.max(1, +e.target.value)))} />
                </div>
                <div className="field">
                  <label htmlFor="r-monthly">Monthly added</label>
                  <input id="r-monthly" type="number" min={0} step={250} value={monthly}
                         onChange={(e) => setMonthly(Math.max(0, +e.target.value))} />
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="card pad">
        <h2 className="h2">Projected value</h2>
        {!rep || !p ? <div className="skeleton" style={{ height: 300 }} /> : (
          <>
            <FanChart bands={p.bands} goal={p.goal_amount} />
            <div className="legend row">
              <div className="lg" style={{ flex: 'none' }}>
                <i className="dot" style={{ background: cssVar('--c4'), opacity: 0.24 }} />
                <span className="nm">Middle 50%</span>
              </div>
              <div className="lg" style={{ flex: 'none' }}>
                <i className="dot" style={{ background: cssVar('--c4'), opacity: 0.14 }} />
                <span className="nm">5th–95th percentile</span>
              </div>
              <div className="lg" style={{ flex: 'none' }}>
                <i className="dot" style={{ background: cssVar('--c4') }} />
                <span className="nm">Median</span>
              </div>
            </div>
            <div className="note" style={{ paddingTop: 10 }}>
              Assumes normally distributed daily returns fitted to{' '}
              {rep.metrics.observations.toLocaleString('en-US')} trading days —
              {' '}{pct(p.assumed_annual_return * 100)} a year at{' '}
              {(p.assumed_annual_volatility * 100).toFixed(1)}% volatility. Real returns are
              fat-tailed, so treat the bands as a spread of plausible outcomes, not a
              confidence interval. Measured tail risk is on the{' '}
              <a href="#risk">Risk</a> screen.
            </div>
          </>
        )}
      </section>

      {rep && p && (
        <section className="card pad">
          <h2 className="h2">Where it lands after {p.years} years</h2>
          <div className="tablescroll">
            <table>
              <thead>
                <tr><th>Outcome</th><th className="r">Portfolio value</th></tr>
              </thead>
              <tbody>
                {PERCENTILES.map((k) => {
                  const value = p.final_percentiles[k]
                  return value == null ? null : (
                    <tr key={k}>
                      <td>{PERCENTILE_LABEL[k]}</td>
                      <td className="r num" style={k === 'p50' ? { fontWeight: 600 } : undefined}>
                        {usd(value)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="note" style={{ paddingTop: 12 }}>
            Of which <b>{usd(p.total_contributions)}</b> is money you put in, not growth.
          </div>
        </section>
      )}
    </div>
  )
}
