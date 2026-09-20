import { useState } from 'react'
import { cssVar, useThemeTick, useWidth } from '../lib'

export interface LineSeries {
  label: string
  values: (number | null)[]
  color: string
  /** Thicker stroke marks the portfolio blend against its constituents. */
  width?: number
}

const H = 300, PAD_L = 52, PAD_R = 12, PAD_T = 12, PAD_B = 26

/**
 * Multi-series cumulative-return chart. Hand-built SVG like the rest of the
 * charts here, so it reads its colours from CSS custom properties at render
 * time and needs `useThemeTick()` to repaint when the theme flips.
 */
export function LineChart({ series, dates }: { series: LineSeries[]; dates: string[] }) {
  useThemeTick()
  const [hover, setHover] = useState<number | null>(null)
  // The SVG lays out its own x-axis in user units, so it needs a real
  // measured width rather than a percentage.
  const [box, measured] = useWidth<HTMLDivElement>()
  const w = Math.max(measured || 760, 320)

  const flat = series.flatMap((s) => s.values).filter((v): v is number => v !== null)
  const lo = Math.min(0, ...flat), hi = Math.max(0, ...flat)
  const span = hi - lo || 1

  const x = (i: number) => PAD_L + (i / Math.max(dates.length - 1, 1)) * (w - PAD_L - PAD_R)
  const y = (v: number) => PAD_T + (1 - (v - lo) / span) * (H - PAD_T - PAD_B)

  // A gap (null) breaks the path rather than interpolating across it — a
  // holding bought mid-window has no line before it existed.
  const path = (values: (number | null)[]) => {
    let d = '', pen = false
    values.forEach((v, i) => {
      if (v === null) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`
      pen = true
    })
    return d
  }

  const ticks = Array.from({ length: 5 }, (_, i) => lo + (span * i) / 4)

  return (
    <div className="linechart" ref={box}>
      <svg viewBox={`0 0 ${w} ${H}`} width="100%" height={H} role="img"
           aria-label="Cumulative return over time"
           onMouseLeave={() => setHover(null)}
           onMouseMove={(e) => {
             const rect = e.currentTarget.getBoundingClientRect()
             const px = ((e.clientX - rect.left) / rect.width) * w
             const i = Math.round(((px - PAD_L) / (w - PAD_L - PAD_R)) * (dates.length - 1))
             setHover(i >= 0 && i < dates.length ? i : null)
           }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={w - PAD_R} y1={y(t)} y2={y(t)} stroke={cssVar('--grid')} />
            <text x={PAD_L - 8} y={y(t) + 4} textAnchor="end" fontSize="10"
                  fill={cssVar('--ink-3')} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {(t * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        {/* Zero is the reference every line is rebased to, so it gets a
            stronger rule than the gridlines. */}
        <line x1={PAD_L} x2={w - PAD_R} y1={y(0)} y2={y(0)} stroke={cssVar('--marker')} />
        {series.map((s) => (
          <path key={s.label} d={path(s.values)} fill="none" stroke={s.color}
                strokeWidth={s.width ?? 1.5} strokeLinejoin="round" />
        ))}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={PAD_T} y2={H - PAD_B}
                stroke={cssVar('--marker')} strokeDasharray="3 3" />
        )}
      </svg>
      <div className="readout">
        {hover === null ? (
          <span className="sub">Hover the chart for values.</span>
        ) : (
          <>
            <b>{dates[hover]}</b>
            {series.map((s) => {
              const v = s.values[hover]
              return v === null ? null : (
                <span key={s.label}>
                  <i className="dot" style={{ background: s.color }} />
                  {s.label} <b className="num">{(v * 100).toFixed(1)}%</b>
                </span>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}
