import { useEffect, useState } from 'react'
import { ApiError, fetchPerformance, type PerformanceReport } from '../api'
import { colorForType, cssVar, pct, usd } from '../lib'
import { LineChart, type LineSeries } from '../components/LineChart'

const WINDOWS: { label: string; months: number | null }[] = [
  { label: '1Y', months: 12 }, { label: '3Y', months: 36 },
  { label: '5Y', months: 60 }, { label: 'All', months: null },
]

const startFor = (months: number | null): string | null => {
  if (months === null) return null
  const d = new Date()
  d.setMonth(d.getMonth() - months)
  return d.toISOString().slice(0, 10)
}

/** Thirty-three overlapping lines is a hairball; the rest stay in the table. */
const CHARTED = 8

export function Performance(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<PerformanceReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [months, setMonths] = useState<number | null>(12)

  useEffect(() => {
    let live = true
    setRep(null); setError(null)
    fetchPerformance(dataDir, portfolio, startFor(months))
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio, months])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load performance</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  if (!rep) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading performance">
        <div className="card skeleton" style={{ height: 140 }} />
        <div className="card skeleton" style={{ height: 380 }} />
      </div>
    )
  }

  const top = rep.series.slice(0, CHARTED)
  const lines: LineSeries[] = [
    { label: 'Portfolio', values: rep.portfolio_cumulative_return, color: cssVar('--marker'), width: 2.5 },
    ...top.map((s) => ({
      label: s.ticker, values: s.cumulative_return, color: colorForType(s.asset_type),
    })),
  ]

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Total return</div>
            <div className={`v num ${rep.portfolio_total_return >= 0 ? 'up' : 'down'}`}>
              {pct(rep.portfolio_total_return * 100)}
            </div>
          </div>
          <div className="stat sm">
            <div className="k">Holdings charted</div>
            <div className="v num">{rep.series.length}</div>
          </div>
        </div>

        <div className="toolbar">
          <div className="spacer" />
          <span className="sub">Window</span>
          {WINDOWS.map((wd) => (
            <button key={wd.label} className="seg" aria-pressed={months === wd.months}
                    onClick={() => setMonths(wd.months)}>{wd.label}</button>
          ))}
        </div>

        {/* Rebasing per-ticker is the whole reason these lines are
            comparable; saying so stops the 0% start being read as a
            purchase date. */}
        <div className="note">
          Each line is rebased to its own first sample in the window, so a holding
          bought later still starts at 0%. The portfolio line is value-weighted.
        </div>
        {rep.excluded.length > 0 && (
          <div className="note">
            Held at par or without price history, excluded: {rep.excluded.join(', ')}.
          </div>
        )}
      </section>

      <section className="card pad">
        <h2 className="h2">
          Cumulative return
          {top.length < rep.series.length && ` — largest ${top.length} of ${rep.series.length}`}
        </h2>
        <LineChart series={lines} dates={rep.dates} />
      </section>

      <section className="card pad">
        <h2 className="h2">Return by holding</h2>
        <div className="tablescroll">
          <table>
            <thead>
              <tr>
                <th>Holding</th><th className="r">Value</th><th className="r">Return</th>
              </tr>
            </thead>
            <tbody>
              {rep.series.map((s) => (
                <tr key={s.ticker}>
                  <td>
                    <div className="tick">
                      <span className="glyph" style={{ background: colorForType(s.asset_type) }}>
                        {s.asset_type[0]}
                      </span>
                      <div>
                        <div style={{ fontWeight: 600 }}>{s.ticker}</div>
                        <div className="sub">{s.asset_type}</div>
                      </div>
                    </div>
                  </td>
                  <td className="r num">{usd(s.market_value)}</td>
                  <td className={`r num ${s.total_return >= 0 ? 'up' : 'down'}`}>
                    {pct(s.total_return * 100)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
