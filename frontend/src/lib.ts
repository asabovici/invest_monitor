import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/** Sign sits outside the currency symbol: -$315, never $-315. */
export function compact(n: number): string {
  const a = Math.abs(n)
  const s = n < 0 ? '-' : ''
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${s}$${Math.round(a / 1e3)}K`
  return `${s}$${Math.round(a)}`
}

export const usd = (n: number) =>
  `${n < 0 ? '-' : ''}$${Math.round(Math.abs(n)).toLocaleString('en-US')}`

export const pct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

export const signed = (n: number) => `${n >= 0 ? '+' : ''}${usd(n)}`

export const shortDate = (iso: string, withDay = false) =>
  new Date(iso).toLocaleDateString('en-US',
    withDay ? { month: 'short', day: 'numeric' } : { month: 'short', year: '2-digit' })

export const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

/** Fixed colour slot per asset type — identity, never rank. */
const SLOT: Record<string, string> = {
  Cash: '--c1', Bond: '--c2', Fund: '--c3', ETF: '--c4', Stock: '--c5',
}
export const ACCOUNT_SLOTS = ['--c4', '--c2', '--c1', '--c3', '--c5']

/** Reads a CSS custom property off :root, so charts follow the active theme. */
export function cssVar(name: string): string {
  if (typeof window === 'undefined') return '#888'
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}
export const colorForType = (t: string) => cssVar(SLOT[t] ?? '--c4')

/** Element width, tracked so SVG charts can re-render on resize. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(el)
    setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

/**
 * Bumps a counter whenever the active theme changes, so chart components
 * that read CSS variables at render time recompute their colours.
 */
export function useThemeTick() {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const bump = () => setTick((t) => t + 1)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', bump)
    const mo = new MutationObserver(bump)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { mq.removeEventListener('change', bump); mo.disconnect() }
  }, [])
  return tick
}
