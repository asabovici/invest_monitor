import { useState } from 'react'
import type { ProjectionBands } from '../api'
import { compact, cssVar, usd, useThemeTick, useWidth } from '../lib'

const H = 300, PAD_L = 8, PAD_R = 68, PAD_T = 16, PAD_B = 28

/**
 * Nested percentile bands rather than a spaghetti of paths: the reader wants
 * the spread of outcomes, and 2,000 overlapping lines communicate none of it.
 */
export function FanChart({ bands, goal }: { bands: ProjectionBands; goal?: number | null }) {
  const [box, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  useThemeTick()

  const W = Math.max(320, width || 900)
  const n = bands.dates.length
  const hi = Math.max(...bands.p95, goal ?? 0) * 1.05
  const lo = 0

  const X = (i: number) => PAD_L + (i / Math.max(1, n - 1)) * (W - PAD_L - PAD_R)
  const Y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD_T - PAD_B)

  /** Closed band: along the upper edge, back along the lower one. */
  const ribbon = (upper: number[], lower: number[]) => {
    const out = upper.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`)
    for (let i = lower.length - 1; i >= 0; i--) {
      out.push(`L${X(i).toFixed(1)},${Y(lower[i]).toFixed(1)}`)
    }
    return `${out.join('')}Z`
  }

  const accent = cssVar('--c4')
  const grid = cssVar('--grid'), ink3 = cssVar('--ink-3'), card = cssVar('--card')

  const ticks = Array.from({ length: 5 }, (_, i) => (hi * i) / 4)
  const step = Math.max(1, Math.floor(n / 5))

  return (
    <div className="plotwrap" ref={box}>
      <svg className="plot" viewBox={`0 0 ${W} ${H}`} height={H} role="img"
           aria-label="Projected portfolio value, 5th to 95th percentile">
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={W - PAD_R} y1={Y(v)} y2={Y(v)} stroke={grid} strokeDasharray="3 4" />
            <text x={W - PAD_R + 8} y={Y(v) + 4} fill={ink3} fontSize="11">{compact(v)}</text>
          </g>
        ))}

        <path d={ribbon(bands.p95, bands.p5)} fill={accent} opacity="0.14" />
        <path d={ribbon(bands.p75, bands.p25)} fill={accent} opacity="0.24" />
        <path d={bands.p50.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('')}
              fill="none" stroke={accent} strokeWidth="2" strokeLinecap="round" />

        {goal ? (
          <>
            <line x1={PAD_L} x2={W - PAD_R} y1={Y(goal)} y2={Y(goal)}
                  stroke={cssVar('--pos')} strokeWidth="1.5" strokeDasharray="5 4" />
            <text x={PAD_L + 4} y={Y(goal) - 6} fill={cssVar('--pos')} fontSize="11" fontWeight="600">
              Goal {compact(goal)}
            </text>
          </>
        ) : null}

        {bands.dates.map((d, i) => i % step === 0 ? (
          <text key={i} x={X(i)} y={H - 6} fill={ink3} fontSize="11"
                textAnchor={i === 0 ? 'start' : i + step >= n ? 'end' : 'middle'}>
            {new Date(d).getFullYear()}
          </text>
        ) : null)}

        {hover !== null && (
          <g pointerEvents="none">
            <line x1={X(hover)} x2={X(hover)} y1={PAD_T} y2={H - PAD_B} stroke={ink3} />
            <circle cx={X(hover)} cy={Y(bands.p50[hover])} r="5" fill={accent} stroke={card} strokeWidth="2" />
          </g>
        )}

        <rect x={PAD_L} y={0} width={W - PAD_L - PAD_R} height={H} fill="transparent"
              style={{ cursor: 'crosshair' }}
              onPointerMove={(e) => {
                const r = e.currentTarget.getBoundingClientRect()
                const px = ((e.clientX - r.left) / r.width) * (W - PAD_L - PAD_R)
                const i = Math.round((px / (W - PAD_L - PAD_R)) * (n - 1))
                setHover(Math.max(0, Math.min(n - 1, i)))
              }}
              onPointerLeave={() => setHover(null)} />
      </svg>

      {hover !== null && (
        <div className="tip" style={{ left: `${(X(hover) / W) * 100}%`, top: `${(Y(bands.p95[hover]) / H) * 100}%` }}>
          <div className="d">{new Date(bands.dates[hover]).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}</div>
          {([['Best 5%', bands.p95], ['Upper 25%', bands.p75], ['Median', bands.p50],
             ['Lower 25%', bands.p25], ['Worst 5%', bands.p5]] as const).map(([label, arr]) => (
            <div className="r" key={label}>
              <span className="lbl">{label}</span>
              <b className="num">{usd(arr[hover])}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
