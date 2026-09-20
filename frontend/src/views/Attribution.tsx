import { useEffect, useState } from 'react'
import {
  ApiError, fetchAttribution,
  type AttributionContributor, type AttributionReport,
} from '../api'
import { cssVar, longDate, pct } from '../lib'
import { LineChart, type LineSeries } from '../components/LineChart'
import { NeedsPortfolio } from '../components/NeedsPortfolio'

/** Daily returns compound into the cumulative line the screen shows.
 *
 *  A null day is treated as flat rather than skipped, so the line stays
 *  aligned to `dates` — dropping it would shift every later point left.
 */
function cumulate(daily: (number | null)[]): (number | null)[] {
  let acc = 1
  return daily.map((r) => { acc *= 1 + (r ?? 0); return acc - 1 })
}

function ContributorTable(
  { rows, tone }: { rows: AttributionContributor[]; tone: 'up' | 'down' },
) {
  return (
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th className="r">Avg weight</th>
          <th className="r">Contribution</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.ticker}>
            <td><b>{c.ticker}</b></td>
            <td className="r num sub">{(c.average_weight * 100).toFixed(1)}%</td>
            <td className={`r num ${tone}`}>{pct(c.contribution_to_return * 100)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Attribution(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<AttributionReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    if (!portfolio) return
    let live = true
    setRep(null); setError(null)
    fetchAttribution(portfolio, dataDir, 10)
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio])

  if (!portfolio) return <NeedsPortfolio what="Performance attribution" />

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load attribution</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
        <p className="sub">
          Attribution reads pre-computed metrics. If this portfolio has never been
          refreshed, run <code>uv run invest-monitor metrics refresh</code>.
        </p>
      </div>
    )
  }

  if (!rep) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading attribution">
        <div className="card skeleton" style={{ height: 140 }} />
        <div className="card skeleton" style={{ height: 380 }} />
      </div>
    )
  }

  if (rep.dates.length === 0) {
    return (
      <div className="card state">
        <h2>No recorded history for {rep.portfolio_name}</h2>
        <p>Attribution runs off pre-computed daily metrics, and none are stored
           for this portfolio yet.</p>
        <p className="sub">
          Run <code>uv run invest-monitor metrics refresh</code>, then reload.
        </p>
      </div>
    )
  }

  const lines: LineSeries[] = [{
    label: rep.portfolio_name,
    values: cumulate(rep.daily_returns),
    color: cssVar('--marker'),
    width: 2.5,
  }]

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Cumulative return</div>
            <div className={`v num ${rep.cumulative_return >= 0 ? 'up' : 'down'}`}>
              {pct(rep.cumulative_return * 100)}
            </div>
          </div>
          <div className="stat sm">
            <div className="k">Max drawdown</div>
            <div className="v num down">{pct(rep.max_drawdown * 100)}</div>
          </div>
          <div className="stat sm">
            <div className="k">Trading days</div>
            <div className="v num">{rep.dates.length}</div>
          </div>
        </div>
        {/* The window is whatever the metrics job recorded for this
            portfolio, and it differs a lot between them — SCHAB and
            PRU401K start years apart. Saying so stops the number being
            read as "since inception" or compared across accounts. */}
        <div className="note">
          {longDate(rep.start_date)} → {longDate(rep.end_date)} for {rep.portfolio_name}.
          Other portfolios cover different windows, so these returns are not
          comparable across accounts.
        </div>
      </section>

      <section className="card pad">
        <h2 className="h2">Cumulative return</h2>
        <LineChart series={lines} dates={rep.dates} />
      </section>

      <div className="cols">
        <section className="card pad">
          <h2 className="h2">Top contributors</h2>
          {rep.top_contributors.length === 0 ? (
            <p className="sub">
              Nothing contributed over this window — this portfolio holds only
              cash or par instruments.
            </p>
          ) : (
            <div className="tablescroll">
              <ContributorTable rows={rep.top_contributors} tone="up" />
            </div>
          )}
        </section>
        <section className="card pad">
          <h2 className="h2">Top detractors</h2>
          {rep.top_detractors.length === 0 ? (
            <p className="sub">Nothing detracted over this window.</p>
          ) : (
            <div className="tablescroll">
              <ContributorTable rows={rep.top_detractors} tone="down" />
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
