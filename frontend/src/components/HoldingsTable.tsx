import { useState } from 'react'
import type { Holding } from '../api'
import { colorForType, compact, pct, usd } from '../lib'

export function HoldingsTable({ holdings }: { holdings: Holding[] }) {
  const [all, setAll] = useState(false)
  const rows = all ? holdings : holdings.slice(0, 12)

  return (
    <section className="card pad">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <h2 className="h2" style={{ margin: 0, flex: 1 }}>Holdings</h2>
        <button className="seg" aria-pressed={!all} onClick={() => setAll(false)}>Top 12</button>
        <button className="seg" aria-pressed={all} onClick={() => setAll(true)}>All {holdings.length}</button>
      </div>

      <div className="tablescroll">
        <table>
          <thead>
            <tr>
              <th>Holding</th><th>Account</th><th className="r">Quantity</th>
              <th className="r">Price</th><th className="r">Value</th><th className="r">Gain</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => {
              const gain = h.market_value - h.cost
              const gainPct = h.cost ? (gain / h.cost) * 100 : 0
              return (
                <tr key={`${h.account}-${h.ticker}`}>
                  <td>
                    <div className="tick">
                      <span className="glyph" style={{ background: colorForType(h.asset_type) }}>
                        {h.asset_type[0]}
                      </span>
                      <div>
                        <div style={{ fontWeight: 600 }}>{h.ticker}</div>
                        <div className="sub">{h.asset_type}</div>
                      </div>
                    </div>
                  </td>
                  <td className="sub">{h.account}</td>
                  <td className="r num">{h.quantity.toLocaleString('en-US', { maximumFractionDigits: 2 })}</td>
                  <td className="r num">${h.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                  <td className="r num" style={{ fontWeight: 600 }}>{usd(h.market_value)}</td>
                  <td className={`r num ${gain >= 0 ? 'up' : 'down'}`}>
                    {gain >= 0 ? '+' : ''}{compact(gain)} <span className="sub">{pct(gainPct)}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
