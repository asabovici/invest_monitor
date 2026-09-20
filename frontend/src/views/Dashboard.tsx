import { useEffect, useState } from 'react'
import { ApiError, fetchDashboard, type DashboardSnapshot } from '../api'
import { ACCOUNT_SLOTS, colorForType, cssVar, usd } from '../lib'
import { Donut } from '../components/Donut'
import { HoldingsTable } from '../components/HoldingsTable'
import { StackedBars } from '../components/StackedBars'
import { ValueChart } from '../components/ValueChart'

export function Dashboard(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [snap, setSnap] = useState<DashboardSnapshot | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    let live = true
    setSnap(null)
    setError(null)
    fetchDashboard(dataDir, portfolio)
      .then((d) => live && setSnap(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load the dashboard</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  if (!snap) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading dashboard">
        <div className="card skeleton" style={{ height: 430 }} />
        <div className="cols">
          <div className="card skeleton" style={{ height: 220 }} />
          <div className="card skeleton" style={{ height: 220 }} />
        </div>
      </div>
    )
  }

  // Sorted for readability; colour still comes from the asset type itself,
  // so re-ordering never repaints a series.
  const byType = snap.asset_type_order
    .map((t) => ({ label: t, value: snap.totals_by_type[t] ?? 0, color: colorForType(t) }))
    .sort((a, b) => b.value - a.value)

  const byAccount = Object.entries(snap.totals_by_account).map(([label, value], i) => ({
    label, value, color: cssVar(ACCOUNT_SLOTS[i % ACCOUNT_SLOTS.length]),
  }))

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Portfolio value</div>
            <div className="v num">{usd(snap.market_value)}</div>
          </div>
          <div className="stat sm">
            <div className="k">Cost basis</div>
            <div className="v num">{usd(snap.cost)}</div>
          </div>
          <div className="stat sm">
            <div className="k">Unrealised gain</div>
            <div className={`v num ${snap.gain >= 0 ? 'up' : 'down'}`}>
              {snap.gain >= 0 ? '+' : ''}{usd(snap.gain)}
            </div>
          </div>
        </div>

        <ValueChart series={snap.series} />

        <div className="note">
          Current holdings valued at historical prices — a constant-holdings series, not a record of past balances.
          {snap.unpriced.length > 0 && ` Excluded, no price data: ${snap.unpriced.join(', ')}.`}
        </div>
      </section>

      <div className="cols">
        <section className="card pad">
          <h2 className="h2">By asset type</h2>
          <Donut slices={byType} title="Portfolio value by asset type" />
        </section>
        {/* One account under a scope — a donut of a single slice says
            nothing the header hasn't already said. `.cols` is auto-fit,
            so the remaining card widens on its own. */}
        {!portfolio && (
          <section className="card pad">
            <h2 className="h2">By account</h2>
            <Donut slices={byAccount} title="Portfolio value by account" />
          </section>
        )}
      </div>

      <section className="card pad">
        <h2 className="h2">Value by asset type over time</h2>
        <StackedBars series={snap.series} order={snap.asset_type_order} />
      </section>

      <HoldingsTable holdings={snap.holdings} />
    </div>
  )
}
