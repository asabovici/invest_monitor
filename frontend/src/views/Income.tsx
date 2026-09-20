import { useEffect, useState } from 'react'
import { ApiError, fetchIncome, type IncomeBucket, type IncomeReport } from '../api'
import { colorForType, compact, cssVar, usd } from '../lib'
import { Donut, type Slice } from '../components/Donut'

const FREQ_LABEL: Record<number, string> = {
  1: 'annual', 2: 'semi-annual', 4: 'quarterly', 12: 'monthly',
}

function BucketBars({ buckets, colorOf }: { buckets: IncomeBucket[]; colorOf: (b: IncomeBucket) => string }) {
  const max = Math.max(...buckets.map((b) => b.annual_income), 1)
  return (
    <div className="barlist">
      {buckets.map((b) => (
        <div className="brow" key={b.label}>
          <div className="blabel">
            <i className="dot" style={{ background: colorOf(b) }} />
            <span className="nm">{b.label}</span>
          </div>
          <div className="bval num">
            {usd(b.annual_income)} <span className="sub num">{b.yield_pct.toFixed(2)}%</span>
          </div>
          <div className="btrack">
            <span style={{ width: `${(b.annual_income / max) * 100}%`, background: colorOf(b) }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function Income(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<IncomeReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [all, setAll] = useState(false)

  useEffect(() => {
    let live = true
    setRep(null); setError(null)
    fetchIncome(dataDir, portfolio)
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load income</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  if (!rep) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading income">
        <div className="card skeleton" style={{ height: 150 }} />
        <div className="cols">
          <div className="card skeleton" style={{ height: 280 }} />
          <div className="card skeleton" style={{ height: 280 }} />
        </div>
      </div>
    )
  }

  const ACCENTS = ['--c4', '--c2', '--c1', '--c3', '--c5']
  const accountSlices: Slice[] = rep.by_account.map((b, i) => ({
    label: b.label, value: b.annual_income, color: cssVar(ACCENTS[i % ACCENTS.length]),
  }))

  const rows = all ? rep.holdings : rep.holdings.slice(0, 10)
  const hidden = rep.holdings.length - rows.length

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Projected annual income</div>
            <div className="v num up">{usd(rep.annual_income)}</div>
            <div className="delta"><span>{usd(rep.monthly_income)} a month on average</span></div>
          </div>
          <div className="stat sm">
            <div className="k">Portfolio yield</div>
            <div className="v num">{rep.portfolio_yield_pct.toFixed(2)}%</div>
          </div>
          <div className="stat sm">
            <div className="k">Income-paying value</div>
            <div className="v num">{usd(rep.market_value - rep.non_income_value)}
              <span className="sub num" style={{ marginLeft: 8 }}>
                of {compact(rep.market_value)}
              </span>
            </div>
          </div>
        </div>
        <div className="note">
          Forward projection from each holding’s current distribution rate — what the book
          would pay over the next year if rates hold. It is not a record of income received.
        </div>
      </section>

      <div className="cols">
        <section className="card pad">
          <h2 className="h2">By asset type</h2>
          <BucketBars buckets={rep.by_asset_type} colorOf={(b) => colorForType(b.label)} />
        </section>

        {/* See Dashboard: a single-slice donut under a scope is noise. */}
        {!portfolio && (
          <section className="card pad">
            <h2 className="h2">By account</h2>
            <Donut slices={accountSlices} title="Annual income by account" />
          </section>
        )}
      </div>

      <section className="card pad">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <h2 className="h2" style={{ margin: 0, flex: 1 }}>Income by holding</h2>
          <button className="seg" aria-pressed={!all} onClick={() => setAll(false)}>Top 10</button>
          <button className="seg" aria-pressed={all} onClick={() => setAll(true)}>
            All {rep.holdings.length}
          </button>
        </div>

        <div className="tablescroll">
          <table>
            <thead>
              <tr>
                <th>Holding</th><th>Account</th><th>Pays</th>
                <th className="r">Value</th><th className="r">Yield</th>
                <th className="r">Monthly</th><th className="r">Annual</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={`${h.account}-${h.ticker}`}>
                  <td>
                    <div className="tick">
                      <span className="glyph" style={{ background: colorForType(h.asset_type) }}>
                        {h.asset_type[0]}
                      </span>
                      <div>
                        <div style={{ fontWeight: 600 }}>{h.ticker}</div>
                        <div className="sub" title={h.name}>{h.name}</div>
                      </div>
                    </div>
                  </td>
                  <td className="sub">{h.account}</td>
                  <td><span className="freq">{FREQ_LABEL[h.payment_frequency] ?? `${h.payment_frequency}×/yr`}</span></td>
                  <td className="r num">{usd(h.market_value)}</td>
                  <td className="r num">{h.yield_pct.toFixed(2)}%</td>
                  <td className="r num">{usd(h.monthly_income)}</td>
                  <td className="r num up" style={{ fontWeight: 600 }}>{usd(h.annual_income)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {hidden > 0 && (
          <button className="showall" onClick={() => setAll(true)}>Show {hidden} more</button>
        )}
      </section>

      {rep.non_income_tickers.length > 0 && (
        <section className="card pad">
          <h2 className="h2">Paying nothing</h2>
          <p className="sub" style={{ margin: 0 }}>
            {usd(rep.non_income_value)} across {rep.non_income_tickers.join(', ')}.
          </p>
          <div className="note" style={{ paddingTop: 10 }}>
            Some of these genuinely pay no distribution; others may just be missing a rate on
            record. The projected total is therefore a floor, not a ceiling.
          </div>
        </section>
      )}
    </div>
  )
}
