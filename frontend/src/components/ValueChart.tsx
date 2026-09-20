import { useMemo, useState } from 'react'
import type { ValueSeries } from '../api'
import { compact, cssVar, longDate, shortDate, usd, useThemeTick, useWidth } from '../lib'

const RANGES = [
  { label: '1M', days: 30 },
  { label: '3M', days: 91 },
  { label: '1Y', days: 365 },
  { label: '3Y', days: 1095 },
  { label: 'ALL', days: 0 },
]

const H = 260, PAD_L = 8, PAD_R = 62, PAD_T = 14, PAD_B = 26

export function ValueChart({ series }: { series: ValueSeries }) {
  const [box, width] = useWidth<HTMLDivElement>()
  const [days, setDays] = useState(0)
  const [hover, setHover] = useState<number | null>(null)
  useThemeTick()

  const W = Math.max(320, width || 900)

  const view = useMemo(() => {
    const n = series.dates.length
    if (!days) return { from: 0, to: n - 1 }
    const end = new Date(series.dates[n - 1]).getTime()
    let from = series.dates.findIndex((d) => new Date(d).getTime() >= end - days * 864e5)
    if (from < 0) from = 0
    return { from: Math.min(from, n - 3), to: n - 1 }
  }, [series, days])

  const xs = series.dates.slice(view.from, view.to + 1)
  const ys = series.total.slice(view.from, view.to + 1)

  const lo = Math.min(...ys), hi = Math.max(...ys)
  const pad = (hi - lo) * 0.18 || hi * 0.1
  const y0 = Math.max(0, lo - pad), y1 = hi + pad

  const X = (i: number) => PAD_L + (i / Math.max(1, xs.length - 1)) * (W - PAD_L - PAD_R)
  const Y = (v: number) => PAD_T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - PAD_T - PAD_B)

  const line = ys.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('')
  const area = `${line}L${X(ys.length - 1).toFixed(1)},${Y(y0).toFixed(1)}L${X(0).toFixed(1)},${Y(y0).toFixed(1)}Z`

  const grid = cssVar('--grid'), ink3 = cssVar('--ink-3'), accent = cssVar('--c4')
  const card = cssVar('--card'), marker = cssVar('--marker')

  const ticks = Array.from({ length: 5 }, (_, i) => y0 + ((y1 - y0) * i) / 4)
  const step = Math.max(1, Math.floor(xs.length / 5))
  const xTicks = xs.map((d, i) => ({ d, i })).filter(({ i }) => i % step === 0)

  const last = ys.length - 1
  const change = ys[last] - ys[0]

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * (W - PAD_L - PAD_R)
    const i = Math.round((px / (W - PAD_L - PAD_R)) * (xs.length - 1))
    setHover(Math.max(0, Math.min(xs.length - 1, i)))
  }

  return (
    <>
      <div className="delta">
        <span>{longDate(xs[0])} →</span>
        <b className={change >= 0 ? 'up' : 'down'}>
          {change >= 0 ? '▲' : '▼'} {usd(Math.abs(change))} (
          {`${change >= 0 ? '+' : ''}${((change / (ys[0] || 1)) * 100).toFixed(2)}%`})
        </b>
      </div>

      <div className="plotwrap" ref={box}>
        <svg className="plot" viewBox={`0 0 ${W} ${H}`} height={H} role="img"
             aria-label={`Portfolio value from ${xs[0]} to ${xs[last]}`}>
          <defs>
            <linearGradient id="vfill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accent} stopOpacity="0.34" />
              <stop offset="100%" stopColor={accent} stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {ticks.map((v, i) => (
            <g key={i}>
              <line x1={PAD_L} x2={W - PAD_R} y1={Y(v)} y2={Y(v)} stroke={grid} strokeDasharray="3 4" />
              <text x={W - PAD_R + 8} y={Y(v) + 4} fill={ink3} fontSize="11">{compact(v)}</text>
            </g>
          ))}

          <path d={area} fill="url(#vfill)" />
          <path d={line} fill="none" stroke={accent} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

          <line x1={X(last)} x2={X(last)} y1={PAD_T} y2={H - PAD_B} stroke={marker} strokeWidth="1.5" />
          <circle cx={X(last)} cy={Y(ys[last])} r="4.5" fill={accent} stroke={card} strokeWidth="2" />

          {xTicks.map(({ d, i }) => (
            <text key={i} x={X(i)} y={H - 6} fill={ink3} fontSize="11"
                  textAnchor={i === 0 ? 'start' : i + step >= xs.length ? 'end' : 'middle'}>
              {shortDate(d, !!days && days <= 91)}
            </text>
          ))}

          {hover !== null && (
            <g pointerEvents="none">
              <line x1={X(hover)} x2={X(hover)} y1={PAD_T} y2={H - PAD_B} stroke={ink3} />
              <circle cx={X(hover)} cy={Y(ys[hover])} r="5" fill={accent} stroke={card} strokeWidth="2" />
            </g>
          )}

          <rect x={PAD_L} y={0} width={W - PAD_L - PAD_R} height={H} fill="transparent"
                style={{ cursor: 'crosshair' }}
                onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>

        {hover !== null && (
          <div className="tip" style={{ left: `${(X(hover) / W) * 100}%`, top: `${(Y(ys[hover]) / H) * 100 - 4}%` }}>
            <div className="d">{longDate(xs[hover])}</div>
            <div className="r">
              <span className="lbl"><i className="dot" style={{ background: accent }} />Value</span>
              <b className="num">{usd(ys[hover])}</b>
            </div>
            <div className="r">
              <span className="lbl">From start</span>
              <b className={`num ${ys[hover] - ys[0] >= 0 ? 'up' : 'down'}`}>
                {`${ys[hover] - ys[0] >= 0 ? '+' : ''}${usd(ys[hover] - ys[0])}`}
              </b>
            </div>
          </div>
        )}
      </div>

      <div className="ranges" role="group" aria-label="Time range">
        {RANGES.map((r) => (
          <button key={r.label} className="pill" aria-pressed={days === r.days}
                  onClick={() => setDays(r.days)}>{r.label}</button>
        ))}
      </div>
    </>
  )
}
