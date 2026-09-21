import { useEffect, useState } from 'react'
import { ApiError, fetchRisk, type RiskReport } from '../api'
import { cssVar, pct, usd } from '../lib'

/** The projection needs simulations; this screen doesn't read them, so it
 *  asks for the endpoint's minimum rather than paying for 2,000 paths. */
const MIN_SIMS = 100

function Metric(
  { label, value, tone, hint }:
  { label: string; value: string; tone?: string; hint?: string },
) {
  return (
    <div className="metric">
      <div className="k">{label}</div>
      <div className="v num" style={tone ? { color: cssVar(tone) } : undefined}>{value}</div>
      {hint && <div className="sub" style={{ marginTop: 2 }}>{hint}</div>}
    </div>
  )
}

export function Risk(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<RiskReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    let live = true
    setRep(null); setError(null)
    fetchRisk({ dataDir, years: 1, monthly: 0, portfolio, simulations: MIN_SIMS })
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load risk</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  if (!rep) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading risk">
        <div className="card skeleton" style={{ height: 180 }} />
        <div className="card skeleton" style={{ height: 200 }} />
      </div>
    )
  }

  const m = rep.metrics
  const dailyLoss = (r: number) => usd(Math.abs(r) * rep.market_value)

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Annualised volatility</div>
            <div className="v num">{(m.annualised_volatility * 100).toFixed(1)}%</div>
          </div>
          <div className="stat sm">
            <div className="k">Max drawdown</div>
            <div className="v num down">{pct(m.max_drawdown * 100)}</div>
          </div>
          <div className="stat sm">
            <div className="k">Current drawdown</div>
            <div className="v num" style={m.current_drawdown < 0 ? { color: cssVar('--neg') } : undefined}>
              {pct(m.current_drawdown * 100)}
            </div>
          </div>
        </div>
        <div className="note">
          Measured on {rep.holdings_covered} of {rep.holdings_total} holdings with price
          history, over {m.observations.toLocaleString('en-US')} trading days.
        </div>
      </section>

      <section className="card pad">
        <h2 className="h2">Tail risk</h2>
        <div className="metricgrid">
          <Metric label="Daily VaR (95%)" value={pct(m.historical_var_95 * 100)} tone="--neg"
                  hint={`about ${dailyLoss(m.historical_var_95)}`} />
          <Metric label="Expected shortfall (95%)" value={pct(m.expected_shortfall_95 * 100)} tone="--neg"
                  hint={`about ${dailyLoss(m.expected_shortfall_95)}`} />
          <Metric label="Daily VaR (99%)" value={pct(m.historical_var_99 * 100)} tone="--neg"
                  hint={`about ${dailyLoss(m.historical_var_99)}`} />
          <Metric label="Expected shortfall (99%)" value={pct(m.expected_shortfall_99 * 100)} tone="--neg"
                  hint={`about ${dailyLoss(m.expected_shortfall_99)}`} />
        </div>
        {/* VaR is routinely misread as "the worst case". Saying what each
            number does and doesn't cover is the whole job of this note. */}
        <div className="note" style={{ paddingTop: 14 }}>
          <b>Value at Risk</b> is the daily loss exceeded on 5% (or 1%) of days — a
          threshold, not a worst case. <b>Expected shortfall</b> is the average loss on
          the days that breach it, so it is the figure that grows when the tail is fat.
          Both are measured from this portfolio’s own history, not modelled.
        </div>
      </section>

      <section className="card pad">
        <h2 className="h2">Daily extremes</h2>
        <div className="metricgrid">
          <Metric label="Best day" value={pct(m.best_day * 100)} tone="--pos" />
          <Metric label="Worst day" value={pct(m.worst_day * 100)} tone="--neg" />
          <Metric label="Fitted-normal VaR (95%)" value={pct(m.monte_carlo_var_95 * 100)}
                  hint="parametric counterpart" />
          <Metric label="Observations" value={m.observations.toLocaleString('en-US')} />
        </div>
        <div className="note" style={{ paddingTop: 14 }}>
          The fitted-normal VaR assumes a bell curve. Where it is milder than the
          historical figure above it, this portfolio’s losses are fatter-tailed than
          a normal distribution allows for.
        </div>
      </section>

      {rep.data_notes.length > 0 && (
        <section className="card pad">
          <h2 className="h2">Price data excluded from these figures</h2>
          <div className="barlist">
            {rep.data_notes.map((n) => <div className="sub" key={n}>{n}</div>)}
          </div>
          <div className="note" style={{ paddingTop: 10 }}>
            A price that collapses and returns within days is a bad quote, not a return —
            leaving these in put the fitted return at 35% a year. A genuine spike that also
            reverses can be caught by the same rule, so check these before trusting them as errors.
          </div>
        </section>
      )}
    </div>
  )
}
