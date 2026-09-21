import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { fetchPortfolios } from './api'
import { Attribution } from './views/Attribution'
import { Dashboard } from './views/Dashboard'
import { Exposure } from './views/Exposure'
import { Holdings } from './views/Holdings'
import { Income } from './views/Income'
import { Performance } from './views/Performance'
import { Projection } from './views/Projection'
import { Risk } from './views/Risk'
import { Stress } from './views/Stress'

type View =
  | 'dashboard' | 'holdings' | 'performance' | 'attribution'
  | 'exposure' | 'risk' | 'stress' | 'projection' | 'income'

const VIEWS: View[] = [
  'dashboard', 'holdings', 'performance', 'attribution', 'exposure', 'risk',
  'stress', 'projection', 'income',
]

/** `null` means every portfolio — the default, and what the API serves when
 *  the `portfolio` param is absent. */
interface Route { view: View; portfolio: string | null }

const routeFromHash = (): Route => {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const cut = raw.indexOf('?')
  const head = cut === -1 ? raw : raw.slice(0, cut)
  const params = new URLSearchParams(cut === -1 ? '' : raw.slice(cut + 1))
  return {
    view: (VIEWS as string[]).includes(head) ? (head as View) : 'dashboard',
    portfolio: params.get('portfolio') || null,
  }
}

const hashFor = ({ view, portfolio }: Route): string =>
  portfolio ? `${view}?${new URLSearchParams({ portfolio })}` : view

/** Keeps view *and* scope in the URL hash, so a scoped screen is as
 *  deep-linkable as an unscoped one and Back steps through both. */
function useHashRoute() {
  const [route, setRoute] = useState<Route>(routeFromHash)
  useEffect(() => {
    const sync = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const go = useCallback((next: Route) => {
    window.location.hash = hashFor(next)
    setRoute(next)
  }, [])
  return [route, go] as const
}

const NAV: { id: View; label: string; icon: ReactNode }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" />
      <rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" />
    </svg>) },
  { id: 'holdings', label: 'Holdings', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 3v18h18" /><path d="M7 14l4-4 3 3 5-6" />
    </svg>) },
  { id: 'performance', label: 'Performance', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 17l5-6 4 4 4-7 5 5" /><path d="M3 21h18" />
    </svg>) },
  { id: 'attribution', label: 'Attribution', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>) },
  { id: 'exposure', label: 'Exposure', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" /><path d="M12 3v9l6.5 6.5" />
    </svg>) },
  { id: 'risk', label: 'Risk', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 3l9 16H3z" /><path d="M12 10v4M12 17h.01" />
    </svg>) },
  { id: 'stress', label: 'Stress test', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M13 2L4 14h7l-1 8 9-12h-7z" />
    </svg>) },
  { id: 'projection', label: 'Projection', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 18c4-10 14-10 18 0" /><path d="M3 21h18" /><circle cx="21" cy="18" r="1.6" />
    </svg>) },
  { id: 'income', label: 'Income', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v10M9.5 9.5h5M9.5 14.5h5" />
    </svg>) },
]

const TITLES: Record<View, string> = {
  dashboard: 'Portfolio', holdings: 'Holdings', performance: 'Performance',
  attribution: 'Attribution', exposure: 'Exposure', risk: 'Risk',
  stress: 'Stress test', projection: 'Projection', income: 'Income',
}

const AllIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" />
  </svg>
)
const OneIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 7h18v12H3z" /><path d="M8 7V5h8v2" />
  </svg>
)

export default function App() {
  const [route, go] = useHashRoute()
  const [dataDir, setDataDir] = useState('data')
  const [names, setNames] = useState<string[]>([])

  // The rail's list comes from the cheap listing endpoint — no price reads,
  // so populating the selector costs nothing even on a scoped deep link.
  //
  // Empty portfolios are left out: the live dataset has six of them, and
  // scoping to one shows $0 on the Dashboard and a 400 on the other three
  // screens. They still resolve if linked to directly — this only decides
  // what the selector offers.
  useEffect(() => {
    let live = true
    fetchPortfolios(dataDir)
      .then((ps) => live && setNames(
        ps.filter((p) => p.position_count > 0).map((p) => p.name)))
      .catch(() => live && setNames([]))
    return () => { live = false }
  }, [dataDir])

  // A scope from one dataset rarely names a portfolio in the other, and a
  // stale name is a 404 on every screen. Switching datasets resets to All.
  const switchDataset = (dir: string) => {
    setDataDir(dir)
    if (route.portfolio) go({ view: route.view, portfolio: null })
  }

  const scope = route.portfolio
  const props = { dataDir, portfolio: scope }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand"><b>Invest</b><span>Monitor</span></div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <button key={n.id} onClick={() => go({ view: n.id, portfolio: scope })}
                    aria-current={route.view === n.id ? 'page' : undefined}>
              {n.icon}{n.label}
            </button>
          ))}

          <div className="navlabel">Scope</div>
          <button onClick={() => go({ view: route.view, portfolio: null })}
                  aria-current={scope === null ? 'page' : undefined}>
            {AllIcon}All portfolios
          </button>
          {names.map((name) => (
            <button key={name} onClick={() => go({ view: route.view, portfolio: name })}
                    aria-current={scope === name ? 'page' : undefined}>
              {OneIcon}{name}
            </button>
          ))}

          <div className="navlabel">Dataset</div>
          <button onClick={() => switchDataset('data')} aria-current={dataDir === 'data' ? 'page' : undefined}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
            </svg>Live
          </button>
          <button onClick={() => switchDataset('data_demo')} aria-current={dataDir === 'data_demo' ? 'page' : undefined}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M8 9h8M8 13h5" />
            </svg>Demo
          </button>
        </nav>
      </aside>

      <main className="main">
        <div className="topbar">
          <h1>{TITLES[route.view]}</h1>
          {/* The scope is named in the header because every number below it
              changes meaning with it — a scoped screen must never be
              mistakeable for the whole portfolio. */}
          <span className="scopechip">{scope ?? 'All portfolios'}</span>
          <div className="spacer" />
          <span className="sub num">{dataDir === 'data' ? 'Live dataset' : 'Demo dataset'}</span>
        </div>

        {route.view === 'dashboard' ? (
          <Dashboard {...props} />
        ) : route.view === 'holdings' ? (
          <Holdings {...props} />
        ) : route.view === 'performance' ? (
          <Performance {...props} />
        ) : route.view === 'attribution' ? (
          <Attribution {...props} />
        ) : route.view === 'exposure' ? (
          <Exposure {...props} />
        ) : route.view === 'risk' ? (
          <Risk {...props} />
        ) : route.view === 'stress' ? (
          <Stress {...props} />
        ) : route.view === 'projection' ? (
          <Projection {...props} />
        ) : (
          <Income {...props} />
        )}
      </main>
    </div>
  )
}
