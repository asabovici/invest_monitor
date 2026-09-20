import { useEffect, useState, type ReactNode } from 'react'
import { Dashboard } from './views/Dashboard'
import { Exposure } from './views/Exposure'
import { Holdings } from './views/Holdings'
import { Income } from './views/Income'
import { Risk } from './views/Risk'

type View = 'dashboard' | 'holdings' | 'exposure' | 'risk' | 'income'

const VIEWS: View[] = ['dashboard', 'holdings', 'exposure', 'risk', 'income']

const viewFromHash = (): View => {
  const h = window.location.hash.replace(/^#\/?/, '')
  return (VIEWS as string[]).includes(h) ? (h as View) : 'dashboard'
}

/** Keeps the view in the URL hash so screens are deep-linkable and Back works. */
function useHashView() {
  const [view, setView] = useState<View>(viewFromHash)
  useEffect(() => {
    const sync = () => setView(viewFromHash())
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const go = (v: View) => {
    window.location.hash = v
    setView(v)
  }
  return [view, go] as const
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
  { id: 'exposure', label: 'Exposure', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" /><path d="M12 3v9l6.5 6.5" />
    </svg>) },
  { id: 'risk', label: 'Risk', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 3l9 16H3z" /><path d="M12 10v4M12 17h.01" />
    </svg>) },
  { id: 'income', label: 'Income', icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v10M9.5 9.5h5M9.5 14.5h5" />
    </svg>) },
]

const TITLES: Record<View, string> = {
  dashboard: 'Portfolio', holdings: 'Holdings', exposure: 'Exposure',
  risk: 'Risk', income: 'Income',
}

export default function App() {
  const [view, go] = useHashView()
  const [dataDir, setDataDir] = useState('data')

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand"><b>Invest</b><span>Monitor</span></div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <button key={n.id} onClick={() => go(n.id)}
                    aria-current={view === n.id ? 'page' : undefined}>
              {n.icon}{n.label}
            </button>
          ))}
          <div className="navlabel">Dataset</div>
          <button onClick={() => setDataDir('data')} aria-current={dataDir === 'data' ? 'page' : undefined}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
            </svg>Live
          </button>
          <button onClick={() => setDataDir('data_demo')} aria-current={dataDir === 'data_demo' ? 'page' : undefined}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M8 9h8M8 13h5" />
            </svg>Demo
          </button>
        </nav>
      </aside>

      <main className="main">
        <div className="topbar">
          <h1>{TITLES[view]}</h1>
          <div className="spacer" />
          <span className="sub num">{dataDir === 'data' ? 'Live dataset' : 'Demo dataset'}</span>
        </div>

        {view === 'dashboard' ? (
          <Dashboard dataDir={dataDir} />
        ) : view === 'holdings' ? (
          <Holdings dataDir={dataDir} />
        ) : view === 'exposure' ? (
          <Exposure dataDir={dataDir} />
        ) : view === 'risk' ? (
          <Risk dataDir={dataDir} />
        ) : (
          <Income dataDir={dataDir} />
        )}
      </main>
    </div>
  )
}
