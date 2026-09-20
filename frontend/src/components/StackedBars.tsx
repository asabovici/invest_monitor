import { useState } from 'react'
import type { ValueSeries } from '../api'
import { colorForType, compact, cssVar, useThemeTick, useWidth } from '../lib'

const H = 230, PAD_L = 8, PAD_R = 62, PAD_T = 12, PAD_B = 26

export function StackedBars({ series, order }: { series: ValueSeries; order: string[] }) {
  const [box, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  useThemeTick()

  const W = Math.max(320, width || 900)

  // One column per year, sampled at that year's last observation.
  const years = [...new Set(series.dates.map((d) => d.slice(0, 4)))]
  const cols = years.map((y) => {
    let idx = -1
    series.dates.forEach((d, i) => { if (d.slice(0, 4) === y) idx = i })
    return { year: y, idx }
  })

  const stacks = cols.map((c) => order.map((t) => series.by_type[t]?.[c.idx] ?? 0))
  const totals = stacks.map((s) => s.reduce((a, b) => a + b, 0))
  const hi = Math.max(...totals, 1) * 1.12

  const slot = (W - PAD_L - PAD_R) / cols.length
  const bw = Math.min(56, slot - 14)
  const X = (i: number) => PAD_L + (i + 0.5) * slot - bw / 2
  const Y = (v: number) => PAD_T + (1 - v / hi) * (H - PAD_T - PAD_B)

  const grid = cssVar('--grid'), ink3 = cssVar('--ink-3')
  const ticks = Array.from({ length: 5 }, (_, i) => (hi * i) / 4)

  return (
    <>
      <div className="plotwrap" ref={box}>
        <svg className="plot" viewBox={`0 0 ${W} ${H}`} height={H} role="img"
             aria-label="Portfolio value by asset type, one column per year">
          {ticks.map((v, i) => (
            <g key={i}>
              <line x1={PAD_L} x2={W - PAD_R} y1={Y(v)} y2={Y(v)} stroke={grid} strokeDasharray="3 4" />
              <text x={W - PAD_R + 8} y={Y(v) + 4} fill={ink3} fontSize="11">{compact(v)}</text>
            </g>
          ))}

          {stacks.map((stack, ci) => {
            let acc = 0
            return (
              <g key={cols[ci].year} onPointerEnter={() => setHover(ci)} onPointerLeave={() => setHover(null)}>
                {stack.map((v, si) => {
                  const top = Y(acc + v), bottom = Y(acc)
                  acc += v
                  // 2px surface gap keeps adjacent segments legible.
                  const h = Math.max(0, bottom - top - 2)
                  if (h < 0.5) return null
                  return (
                    <rect key={order[si]} x={X(ci)} y={top} width={bw} height={h} rx="2"
                          fill={colorForType(order[si])}
                          opacity={hover === null || hover === ci ? 1 : 0.5}
                          style={{ cursor: 'pointer' }} />
                  )
                })}
                <text x={X(ci) + bw / 2} y={H - 6} textAnchor="middle" fontSize="11" fill={ink3}>
                  {cols[ci].year}
                </text>
              </g>
            )
          })}
        </svg>

        {hover !== null && (
          <div className="tip" style={{ left: `${((X(hover) + bw / 2) / W) * 100}%`, top: `${(Y(totals[hover]) / H) * 100}%` }}>
            <div className="d">{cols[hover].year}</div>
            {[...order].reverse().map((t) => (
              <div className="r" key={t}>
                <span className="lbl"><i className="dot" style={{ background: colorForType(t) }} />{t}</span>
                <b className="num">{compact(stacks[hover][order.indexOf(t)])}</b>
              </div>
            ))}
            <div className="r" style={{ borderTop: `1px solid ${cssVar('--border')}`, marginTop: 5, paddingTop: 5 }}>
              <span className="lbl">Total</span>
              <b className="num">{compact(totals[hover])}</b>
            </div>
          </div>
        )}
      </div>

      <div className="legend row">
        {order.map((t) => (
          <div className="lg" key={t} style={{ flex: 'none' }}>
            <i className="dot" style={{ background: colorForType(t) }} />
            <span className="nm">{t}</span>
          </div>
        ))}
      </div>
    </>
  )
}
