import { useEffect, useMemo, useState } from 'react'
import { ApiError, fetchDashboard, type DashboardSnapshot, type Holding } from '../api'
import { colorForType, compact, pct, usd } from '../lib'
import { HoldingRow } from '../components/HoldingRow'

type GroupBy = 'account' | 'asset_type'

interface Group {
  key: string
  holdings: Holding[]
  value: number
  cost: number
}

/** Groups holdings, largest group first, holdings within a group largest first. */
function group(holdings: Holding[], by: GroupBy): Group[] {
  const map = new Map<string, Holding[]>()
  for (const h of holdings) {
    const k = by === 'account' ? h.account : h.asset_type
    map.set(k, [...(map.get(k) ?? []), h])
  }
  return [...map.entries()]
    .map(([key, hs]) => ({
      key,
      holdings: [...hs].sort((a, b) => b.market_value - a.market_value),
      value: hs.reduce((s, h) => s + h.market_value, 0),
      cost: hs.reduce((s, h) => s + h.cost, 0),
    }))
    .sort((a, b) => b.value - a.value)
}

/** Accounts vary hugely in size (33 holdings vs 2), so long groups collapse —
 *  otherwise one account's tail buries every other card below the fold. */
const COLLAPSE_AT = 10

function GroupList({ holdings, showAccount }: { holdings: Holding[]; showAccount: boolean }) {
  const [open, setOpen] = useState(false)
  const hidden = holdings.length - COLLAPSE_AT
  const rows = open || hidden <= 0 ? holdings : holdings.slice(0, COLLAPSE_AT)

  return (
    <>
      <div className="hlist">
        {rows.map((h) => (
          <HoldingRow key={`${h.account}-${h.ticker}`} holding={h} showAccount={showAccount} />
        ))}
      </div>
      {hidden > 0 && (
        <button className="showall" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Show less' : `Show ${hidden} more`}
        </button>
      )}
    </>
  )
}

export function Holdings(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [snap, setSnap] = useState<DashboardSnapshot | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [by, setBy] = useState<GroupBy>('account')
  const [query, setQuery] = useState('')

  useEffect(() => {
    let live = true
    setSnap(null); setError(null)
    fetchDashboard(dataDir, portfolio)
      .then((d) => live && setSnap(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio])

  // Under a scope every holding shares an account, so that grouping would
  // produce a single group wrapping the whole list. Fall back to asset
  // type rather than rendering a degenerate heading.
  const effectiveBy: GroupBy = portfolio ? 'asset_type' : by

  const groups = useMemo(() => {
    if (!snap) return []
    const q = query.trim().toLowerCase()
    const rows = q
      ? snap.holdings.filter((h) =>
          h.ticker.toLowerCase().includes(q) ||
          h.name.toLowerCase().includes(q) ||
          h.account.toLowerCase().includes(q))
      : snap.holdings
    return group(rows, effectiveBy)
  }, [snap, effectiveBy, query])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load holdings</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  if (!snap) {
    return (
      <div className="cols" aria-busy="true" aria-label="Loading holdings">
        <div className="card skeleton" style={{ height: 320 }} />
        <div className="card skeleton" style={{ height: 320 }} />
      </div>
    )
  }

  const shown = groups.reduce((s, g) => s + g.holdings.length, 0)
  const shownValue = groups.reduce((s, g) => s + g.value, 0)
  const shownCost = groups.reduce((s, g) => s + g.cost, 0)
  const gain = shownValue - shownCost

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">{query ? 'Matching value' : 'Total value'}</div>
            <div className="v num">{usd(shownValue)}</div>
            <div className="delta">
              <span>{shown} of {snap.holdings.length} holdings</span>
            </div>
          </div>
          <div className="stat sm">
            <div className="k">Cost basis</div>
            <div className="v num">{usd(shownCost)}</div>
          </div>
          <div className="stat sm">
            <div className="k">Unrealised gain</div>
            <div className={`v num ${gain >= 0 ? 'up' : 'down'}`}>
              {gain >= 0 ? '+' : ''}{usd(gain)}
              <span className="sub num" style={{ marginLeft: 8 }}>
                {pct(shownCost ? (gain / shownCost) * 100 : 0)}
              </span>
            </div>
          </div>
        </div>

        <div className="toolbar">
          <input className="search" type="search" value={query} placeholder={portfolio ? 'Filter by ticker or name' : 'Filter by ticker, name, or account'}
                 onChange={(e) => setQuery(e.target.value)} aria-label="Filter holdings" />
          <div className="spacer" />
          {portfolio ? (
            <span className="sub">Grouped by asset type</span>
          ) : (
            <>
              <span className="sub">Group by</span>
              <button className="seg" aria-pressed={by === 'account'} onClick={() => setBy('account')}>Account</button>
              <button className="seg" aria-pressed={by === 'asset_type'} onClick={() => setBy('asset_type')}>Asset type</button>
            </>
          )}
        </div>

        {snap.unpriced.length > 0 && (
          <div className="note">Excluded, no price data: {snap.unpriced.join(', ')}.</div>
        )}
      </section>

      {groups.length === 0 ? (
        <div className="card state">
          <h2>Nothing matches “{query}”</h2>
          <p className="sub">Try a ticker, a company name, or an account.</p>
        </div>
      ) : (
        <div className="cols">
          {groups.map((g) => {
            const gGain = g.value - g.cost
            return (
              <section className="card pad" key={g.key}>
                <div className="ghead">
                  <div>
                    <div className="h2" style={{ margin: 0 }}>{g.key}</div>
                    <div className="sub">{g.holdings.length} holding{g.holdings.length === 1 ? '' : 's'}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="num" style={{ fontSize: 19, fontWeight: 700, letterSpacing: '-0.3px' }}>
                      {usd(g.value)}
                    </div>
                    <div className={`sub num ${gGain >= 0 ? 'up' : 'down'}`}>
                      {gGain >= 0 ? '+' : ''}{compact(gGain)} {pct(g.cost ? (gGain / g.cost) * 100 : 0)}
                    </div>
                  </div>
                </div>

                {/* Share-of-group bar: the row list alone hides concentration. */}
                <div className="sharebar" aria-hidden="true">
                  {g.holdings.map((h) => (
                    <span key={h.ticker} style={{
                      width: `${(h.market_value / (g.value || 1)) * 100}%`,
                      background: colorForType(h.asset_type),
                    }} />
                  ))}
                </div>

                <GroupList holdings={g.holdings} showAccount={by === 'asset_type'} />
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
