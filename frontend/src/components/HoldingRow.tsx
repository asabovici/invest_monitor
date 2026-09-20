import type { Holding } from '../api'
import { colorForType, compact, pct, usd } from '../lib'

/** One line in a holdings group: icon chip, identity, then value on the right. */
export function HoldingRow({ holding, showAccount }: { holding: Holding; showAccount?: boolean }) {
  const gain = holding.market_value - holding.cost
  const gainPct = holding.cost ? (gain / holding.cost) * 100 : 0

  return (
    <div className="hrow">
      <span className="glyph" style={{ background: colorForType(holding.asset_type) }}>
        {holding.asset_type[0]}
      </span>

      <div className="hid">
        {/* Long fund names are ellipsised; keep the full text reachable on hover. */}
        <div className="hname" title={holding.name}>{holding.name}</div>
        <div className="sub">
          {holding.ticker}
          {showAccount && ` · ${holding.account}`}
          {' · '}
          {holding.quantity.toLocaleString('en-US', { maximumFractionDigits: 2 })}
          {' × '}
          ${holding.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      </div>

      <div className="hval">
        <div className="num" style={{ fontWeight: 600 }}>{usd(holding.market_value)}</div>
        <div className={`sub num ${gain >= 0 ? 'up' : 'down'}`}>
          {gain >= 0 ? '+' : ''}{compact(gain)} {pct(gainPct)}
        </div>
      </div>
    </div>
  )
}
