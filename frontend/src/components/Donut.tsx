import { useState } from 'react'
import { compact, cssVar, useThemeTick } from '../lib'

const SIZE = 168, R = 66, STROKE = 17
/** Angular gap ≈ a 2px surface break between adjacent segments. */
const GAP = 0.035

function arc(cx: number, cy: number, r: number, a0: number, a1: number) {
  const p = (a: number) => [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  const [x0, y0] = p(a0)
  const [x1, y1] = p(a1)
  return `M${x0} ${y0}A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1} ${y1}`
}

export interface Slice { label: string; value: number; color: string }

export function Donut({ slices, title }: { slices: Slice[]; title: string }) {
  const [hover, setHover] = useState<number | null>(null)
  useThemeTick()

  const total = slices.reduce((s, d) => s + d.value, 0) || 1
  const c = SIZE / 2
  let angle = -Math.PI / 2

  const segments = slices.map((s, i) => {
    const sweep = (s.value / total) * Math.PI * 2
    const a0 = angle + GAP / 2
    const a1 = angle + sweep - GAP / 2
    angle += sweep
    return { ...s, a0, a1, i }
  })

  return (
    <div className="donutwrap">
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={title}>
        {segments.map((s) =>
          s.a1 > s.a0 ? (
            <path key={s.label} d={arc(c, c, R, s.a0, s.a1)} stroke={s.color} strokeWidth={STROKE}
                  fill="none" opacity={hover === null || hover === s.i ? 1 : 0.45}
                  style={{ cursor: 'pointer' }}
                  onPointerEnter={() => setHover(s.i)} onPointerLeave={() => setHover(null)} />
          ) : null,
        )}
        <text x={c} y={c - 2} textAnchor="middle" fontSize="19" fontWeight="700"
              fill={cssVar('--ink')} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {compact(hover === null ? total : slices[hover].value)}
        </text>
        <text x={c} y={c + 16} textAnchor="middle" fontSize="10.5" fill={cssVar('--ink-3')}>
          {hover === null ? 'Total' : slices[hover].label}
        </text>
      </svg>

      <div className="legend">
        {slices.map((s, i) => (
          <div className="lg" key={s.label}
               onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
            <i className="dot" style={{ background: s.color }} />
            <span className="nm">{s.label}</span>
            <span className="vl num">{compact(s.value)}</span>
            <span className="sub num">{((s.value / total) * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
