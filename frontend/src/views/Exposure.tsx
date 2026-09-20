import { useEffect, useState } from 'react'
import { ApiError, fetchExposure, type Breakdown, type ExposureReport } from '../api'
import { compact, cssVar, longDate, usd } from '../lib'

/** Fixed hue order — a bucket keeps its colour as values move. */
const SLOTS = ['--c4', '--c2', '--c3', '--c1', '--c5']

/**
 * Ranked bars rather than a donut: with eleven sectors a ring becomes a
 * colour-matching exercise, while bars stay sorted and directly labelled.
 */
function BarList({ breakdown, unit }: { breakdown: Breakdown; unit: string }) {
  const [open, setOpen] = useState<string | null>(null)
  const max = Math.max(...breakdown.slices.map((s) => s.weight), 0.0001)

  return (
    <div className="barlist">
      {breakdown.slices.map((s, i) => {
        const color = cssVar(SLOTS[i % SLOTS.length])
        const contributors = breakdown.top_contributors[s.label] ?? []
        const expanded = open === s.label
        return (
          <div className="brow" key={s.label}>
            <div className="blabel">
              <i className="dot" style={{ background: color }} />
              <span className="nm">{s.label}</span>
              {contributors.length > 0 && (
                <button className="pill" style={{ padding: '1px 8px', fontSize: 11 }}
                        aria-expanded={expanded}
                        onClick={() => setOpen(expanded ? null : s.label)}>
                  {expanded ? 'hide' : 'why'}
                </button>
              )}
            </div>
            <div className="bval num">
              {usd(s.value)} <span className="sub num">{(s.weight * 100).toFixed(1)}%</span>
            </div>
            <div className="btrack">
              <span style={{ width: `${(s.weight / max) * 100}%`, background: color }} />
            </div>
            {expanded && (
              <div className="bmeta sub" style={{ flexWrap: 'wrap' }}>
                {contributors.map((c) => (
                  <span key={c.ticker} title={c.name}>
                    {c.ticker} {compact(c.value)}
                  </span>
                ))}
              </div>
            )}
          </div>
        )
      })}

      <div className="coverage">
        <span className="badge">
          {((breakdown.covered / (breakdown.base || 1)) * 100).toFixed(0)}% of {unit} classified
        </span>
        {breakdown.unclassified > 0.5 && (
          <span className="sub num">{usd(breakdown.unclassified)} unclassified</span>
        )}
      </div>
    </div>
  )
}

export function Exposure({ dataDir }: { dataDir: string }) {
  const [rep, setRep] = useState<ExposureReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    let live = true
    setRep(null); setError(null)
    fetchExposure(dataDir)
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load exposure</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
      </div>
    )
  }

  if (!rep) {
    return (
      <div className="cols" aria-busy="true" aria-label="Loading exposure">
        <div className="card skeleton" style={{ height: 360 }} />
        <div className="card skeleton" style={{ height: 360 }} />
      </div>
    )
  }

  const top = rep.by_sector.slices[0]
  const equity = rep.by_asset_class.slices.find((s) => s.label === 'Equity')

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Looked-through value</div>
            <div className="v num">{usd(rep.market_value)}</div>
            <div className="delta"><span>Fund profiles as of {longDate(rep.as_of)}</span></div>
          </div>
          {equity && (
            <div className="stat sm">
              <div className="k">Equity exposure</div>
              <div className="v num">{usd(equity.value)}
                <span className="sub num" style={{ marginLeft: 8 }}>{(equity.weight * 100).toFixed(1)}%</span>
              </div>
            </div>
          )}
          {top && (
            <div className="stat sm">
              <div className="k">Largest sector</div>
              <div className="v num">{top.label}
                <span className="sub num" style={{ marginLeft: 8 }}>{(top.weight * 100).toFixed(1)}%</span>
              </div>
            </div>
          )}
        </div>

        <div className="note">
          Every fund is disaggregated into what it actually holds, so an index fund reports
          real sector weight rather than sitting in one opaque bucket.
        </div>
      </section>

      <div className="cols">
        <section className="card pad">
          <h2 className="h2">By asset class</h2>
          <BarList breakdown={rep.by_asset_class} unit="the portfolio" />
        </section>

        <section className="card pad">
          <h2 className="h2">By equity sector</h2>
          <BarList breakdown={rep.by_sector} unit="equity" />
          <div className="note" style={{ paddingTop: 12 }}>
            Shares are of the equity sleeve ({usd(rep.by_sector.base)}), not of total value —
            bond and commodity funds have no sector by construction.
          </div>
        </section>
      </div>

      {(rep.short_equity > 0.5 || rep.unprofiled_funds.length > 0 || rep.renormalised_funds.length > 0) && (
        <section className="card pad">
          <h2 className="h2">Notes on this calculation</h2>
          <div className="barlist">
            {rep.short_equity > 0.5 && (
              <div className="sub">
                <b>{usd(rep.short_equity)} of short equity</b> from inverse funds reduces the Equity
                asset class but can’t be spread across sectors, so the two breakdowns differ by
                exactly that amount.
              </div>
            )}
            {rep.unprofiled_funds.length > 0 && (
              <div className="sub">
                <b>No holdings profile:</b> {rep.unprofiled_funds.join(', ')} — counted as
                unclassified. Run <code>invest-monitor collect fund-profile</code> to fill them in.
              </div>
            )}
            {rep.renormalised_funds.length > 0 && (
              <div className="sub">
                <b>Weights rescaled to 100%:</b> {rep.renormalised_funds.join(', ')} — leveraged and
                inverse funds legitimately report more.
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
